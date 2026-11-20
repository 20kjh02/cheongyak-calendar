"""청년안심주택 모집공고 수집 (서울시 청년안심주택 공식 사이트, soco.seoul.go.kr/youth).

공고 목록 표는 자바스크립트로 채워져 서버 응답에는 비어 있습니다. 대신 각 공고의 상세 페이지는
서버에서 완성되어 내려오므로, 마지막으로 확인한 공고에서 '다음글' 링크를 따라가며 새 공고를 모읍니다.
- 최초모집 / 추가모집 / 신규모집 등 유형 구분 없이 게시판의 모든 공고를 수집
- 접수 시작일 = 상세 페이지의 '청약신청일', 종료일 = 본문 '청약신청 : ... ~ ...' 구간(있을 때)
- 마지막 확인 위치는 data/youth_state.json 에 저장 (지우면 SEED 위치부터 다시 훑음)
사이트 구조가 바뀌면 이 파일만 고치면 됩니다. 실패해도 LH/SH 수집은 계속됩니다.
"""
import json
import os
import re
import time
from datetime import date, timedelta
from html import unescape
from pathlib import Path

import requests

from sh_notices import HEADERS, html_to_text

VIEW_URL = "https://soco.seoul.go.kr/youth/bbs/BMSR00015/view.do?boardId={}&menuNo=400008"
SEED_ID = 6718          # 처음 실행할 때 출발하는 공고 번호 (2026-11-03 게시 공고)
MAX_PAGES = 60          # 한 번 실행에 따라갈 최대 공고 수
DELAY = 1.0             # 요청 간 대기(초)
KEEP_DAYS = 14          # 접수 종료 후 이 기간이 지난 공고는 추가하지 않음
STATE_FILE = Path(__file__).parent / "data" / "youth_state.json"

ORG = "청년안심주택"
DATE = r"(\d{4}-\d{2}-\d{2})"
TITLE_RE = re.compile(r"((?:\[[^\]]{1,15}\]\s*)+[^\[]*?)\s*담당부서\s*/\s*사업자")
RANGE_RE = re.compile(
    r"청약\s*신청\s*[:：]\s*[‘'’`]?\s*(\d{2,4})\s*\.\s*(\d{1,2})\s*\.\s*(\d{1,2})\s*\.?[^~\n]{0,30}~\s*"
    r"(?:[‘'’`]?\s*(\d{2,4})\s*\.\s*)?(\d{1,2})\s*\.\s*(\d{1,2})")
PHASE_RE = re.compile(r"((?:최초|추가|신규|재|잔여)\s*(?:모집|공급))")


def _year(y):
    y = int(y)
    return y + 2000 if y < 100 else y


def _iso(y, m, d):
    try:
        return date(_year(y), int(m), int(d)).isoformat()
    except ValueError:
        return None


def parse_detail(html, board_id):
    """상세 페이지 -> 공고 dict. 공고 페이지가 아니면 None."""
    text = html_to_text(html)
    posted = re.search(r"공고게시일\s*" + DATE, text)
    if not posted:
        return None
    posted = posted.group(1)
    field_start = re.search(r"청약신청일\s*" + DATE, text)
    start = field_start.group(1) if field_start else None
    end = None
    m = RANGE_RE.search(text)
    if m:
        rs = _iso(m[1], m[2], m[3])
        ey = m[4] or m[1]
        re_ = _iso(ey, m[5], m[6])
        if rs and (start is None or rs == start):
            start = start or rs
            end = re_
    if start and not end:
        end = start
    t = TITLE_RE.search(text)
    title = " ".join(t.group(1).split()) if t else f"청년안심주택 모집공고 {board_id}"
    brackets = re.findall(r"\[([^\]]+)\]", title)
    kind = next((b for b in brackets if re.search(r"임대|민간|공공", b)), "")  # [정정] 등은 유형에서 제외
    phase = PHASE_RE.search(title)
    district = re.search(r"카테고리\s*([가-힣]{2,4}구)", text)
    type_ = " ".join(x for x in (kind, phase.group(1).replace(" ", "") if phase else "") if x) or "청년안심주택"
    if district:
        type_ += f" ({district.group(1)})"
    return {
        "id": f"YS-{board_id}", "org": ORG, "name": title, "region": "서울", "type": type_,
        "status": "게시", "posted": posted, "close": None,
        "url": VIEW_URL.format(board_id), "start": start, "end": end,
        "notified_start": False, "notified_new": False,
    }


def parse_next(html, cur_id):
    """'다음글' 링크의 boardId. 현재보다 큰 번호만 인정(거꾸로 가거나 맴도는 것 방지)."""
    i = html.find("다음글")
    if i < 0:
        return None
    j = html.find("이전글", i)
    seg = html[i: j if j > i else i + 800]
    m = re.search(r'href="([^"]*boardId=(\d+)[^"]*)"', unescape(seg))
    if m and int(m.group(2)) > cur_id:
        return int(m.group(2))
    return None


def _get(session, url):
    r = session.get(url, timeout=30)
    r.raise_for_status()
    return r.text


def _load_state():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def _dup_of_sh(rec, store):
    """[공공임대] 글은 SH 수집기가 이미 잡은 같은 공고일 수 있어 게시일이 비슷하면 건너뜀."""
    if "공공" not in rec["type"]:
        return False
    for r in store.values():
        if r.get("org") == "SH" and "청년안심주택" in (r["name"] + r["type"]) and r.get("posted"):
            if abs((date.fromisoformat(r["posted"]) - date.fromisoformat(rec["posted"])).days) <= 3:
                return True
    return False


def fetch_youth(store, today, debug_dir=None):
    """새 공고를 따라가며 store에 반영. (반영 건수, 확인한 공고 수) 반환."""
    session = requests.Session()
    session.headers.update(HEADERS)
    state = _load_state()
    cur = int(state.get("last_board_id") or os.environ.get("YOUTH_SEED_ID") or SEED_ID)
    cutoff = (today - timedelta(days=KEEP_DAYS)).isoformat()

    seen, added, last = set(), 0, None
    while cur and cur not in seen and len(seen) < MAX_PAGES:
        seen.add(cur)
        html = _get(session, VIEW_URL.format(cur))
        if len(seen) == 1 and debug_dir:
            Path(debug_dir).mkdir(parents=True, exist_ok=True)
            (Path(debug_dir) / "youth_detail.html").write_text(html[:30000], encoding="utf-8")
        rec = parse_detail(html, cur)
        if rec:
            last = rec
            ref = rec["end"] or rec["start"] or rec["posted"]
            if ref >= cutoff and not _dup_of_sh(rec, store):
                old = store.get(rec["id"], {})
                rec["notified_start"] = old.get("notified_start", False)
                rec["notified_new"] = old.get("notified_new", False)
                store[rec["id"]] = rec
                added += 1
        state["last_board_id"] = cur
        nxt = parse_next(html, cur)
        if not nxt:
            break
        cur = nxt
        time.sleep(DELAY)
    _save_state(state)

    if last and (today - date.fromisoformat(last["posted"])).days > 21:
        print(f"  [참고] 청년안심주택 마지막 공고가 {last['posted']} 게시분입니다. "
              "새 공고가 없는 것인지, 다음글 연결이 끊긴 것인지 사이트에서 한 번 확인해 주세요.")
    return added, len(seen)
