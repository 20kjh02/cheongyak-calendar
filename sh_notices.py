"""SH(서울주택도시개발공사) 임대주택 입주자 모집공고 수집.

출처: 서울주거포털(housing.seoul.go.kr)의 'SH공사 공공임대' 목록 페이지.
SH는 공식 공고 API가 확인되지 않아 웹페이지를 읽는 방식(best-effort)입니다.
- 목록: 청약유형, 공고명, 공고게시일, 발표일, 모집상태, 링크
- 접수 기간: 목록에 없어서 상세 본문 글에서 '신청기간' 근처 날짜를 찾아 추정
사이트 구조가 바뀌면 이 파일만 고치면 됩니다. 실패해도 LH 수집은 계속됩니다.
"""
import re
import time
import zlib
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

import requests

LIST_URL = "https://housing.seoul.go.kr/site/main/sh/publicLease/list"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; cheongyak-calendar personal notifier)"}
MAX_PAGES = 3          # 목록 페이지 수 (최근 공고만 보면 충분)
MAX_DETAIL = 10        # 한 번 실행에 읽을 상세 페이지 수 상한
DELAY = 1.0            # 요청 간 대기(초): 서버에 부담을 주지 않기 위함

DATE_RE = re.compile(r"(\d{4})\s*[.\-년]\s*(\d{1,2})\s*[.\-월]\s*(\d{1,2})")
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
KEY_RE = re.compile(r"신청\s*기간|접수\s*기간|신청\s*접수\s*일정|청약\s*신청|신청\s*접수")
STOP_RE = re.compile(r"서류\s*심사\s*대상자|서류\s*제출|당첨자\s*발표|합격자\s*발표")


def _iso(y, m, d):
    from datetime import date
    try:
        return date(int(y), int(m), int(d)).isoformat()
    except ValueError:
        return None


class _TableParser(HTMLParser):
    """<tr>마다 셀 글자와 링크(href)를 모은다."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows, self._row, self._cell = [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = {"cells": [], "hrefs": []}
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
        elif tag == "a" and self._row is not None:
            href = dict(attrs).get("href")
            if href:
                self._row["hrefs"].append(href)

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._row is not None and self._cell is not None:
            self._row["cells"].append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None


def parse_list(html):
    """목록 HTML -> 공고 dict 목록. 날짜 칸(YYYY-MM-DD)을 기준으로 앞뒤 칸을 읽어 열 위치 변화에 강하게."""
    p = _TableParser()
    p.feed(html)
    items = []
    for row in p.rows:
        cells = row["cells"]
        idx = next((i for i, c in enumerate(cells) if ISO_RE.match(c)), None)
        if idx is None or idx < 2:
            continue
        name, kind, posted = cells[idx - 1], cells[idx - 2], cells[idx]
        status = next((c for c in cells[idx + 1:] if c in ("모집중", "모집마감")), "")
        orig = detail = None
        for h in row["hrefs"]:
            full = urljoin(LIST_URL, h)
            if "i-sh.co.kr" in full:
                orig = orig or full
            elif re.search(r"view\?.*seq=", full):
                detail = detail or full
        seq = re.search(r"seq=(\d+)", orig or "") or re.search(r"seq=(\d+)", detail or "")
        pid = f"SH-{seq.group(1)}" if seq else f"SH-{posted}-{zlib.crc32(name.encode()) & 0xffffffff:x}"
        items.append({"id": pid, "name": name, "type": kind, "posted": posted, "status": status,
                      "orig_url": orig, "detail_url": detail})
    return items


def html_to_text(html):
    html = re.sub(r"<(script|style)[\s\S]*?</\1>", " ", html, flags=re.I)
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", html)).split())


def parse_schedule(text, posted):
    """본문에서 접수 시작/종료일 추정. '신청기간' 등 키워드 뒤 ~ '서류심사/당첨자 발표' 앞 구간의 날짜 사용.
    공고게시일 이하의 날짜(공고일 표기 등)는 제외."""
    for m in KEY_RE.finditer(text):
        window = text[m.end(): m.end() + 600]
        stop = STOP_RE.search(window)
        if stop:
            window = window[: stop.start()]
        dates = sorted({d for d in (_iso(*g) for g in DATE_RE.findall(window)) if d and d > (posted or "")})
        if dates:
            return dates[0], dates[-1]
    return None, None


def _get(session, url):
    r = session.get(url, timeout=30)
    r.raise_for_status()
    return r.text


def _save_debug(debug_dir, name, html):
    if debug_dir:
        Path(debug_dir).mkdir(parents=True, exist_ok=True)
        (Path(debug_dir) / name).write_text(html[:30000], encoding="utf-8")


def fetch_sh(store, debug_dir=None):
    """store에 SH 모집중 공고를 추가/갱신. (모집중 반영 건수, 목록 전체 건수) 반환."""
    session = requests.Session()
    session.headers.update(HEADERS)

    items = []
    for page in range(1, MAX_PAGES + 1):
        html = _get(session, f"{LIST_URL}?cp={page}&supplyType=publicLease")
        if page == 1:
            _save_debug(debug_dir, "sh_list.html", html)
        rows = parse_list(html)
        if not rows:
            break
        items += rows
        time.sleep(DELAY)

    used, n = 0, 0
    for it in items:
        if it["status"] != "모집중":
            continue
        old = store.get(it["id"], {})
        rec = {
            "id": it["id"], "org": "SH", "name": it["name"], "region": "서울",
            "type": it["type"] or "임대", "status": it["status"], "posted": it["posted"],
            "close": None,
            "url": it["orig_url"] or it["detail_url"] or LIST_URL,
            "start": old.get("start"), "end": old.get("end"),
            "notified_start": old.get("notified_start", False),
            "notified_new": old.get("notified_new", False),
        }
        if not rec["start"] and used < MAX_DETAIL:  # 접수일을 모르면 매번 재시도
            for url in (it["detail_url"], it["orig_url"]):
                if not url:
                    continue
                used += 1
                try:
                    time.sleep(DELAY)
                    html = _get(session, url)
                except requests.RequestException as e:
                    print(f"  SH 상세 조회 실패({it['id']}): {type(e).__name__}")
                    continue
                if used == 1:
                    _save_debug(debug_dir, "sh_detail.html", html)
                s, e = parse_schedule(html_to_text(html), it["posted"])
                if s:
                    rec["start"], rec["end"] = s, e
                    break
        store[it["id"]] = rec
        n += 1
    return n, len(items)
