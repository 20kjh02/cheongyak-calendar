#!/usr/bin/env python3
"""LH 임대 공고 수집 -> 캘린더 페이지 생성 -> 접수 시작 1일 전 이메일 알림.

실행 옵션
  --debug      API 응답 원문을 data/debug/ 에 저장 (필드명 확인용)
  --test-mail  알림 메일 연결 테스트용 메일 1통 발송
"""
import json
import os
import re
import smtplib
import sys
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape
from pathlib import Path
from urllib.parse import unquote

import requests

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).parent
DATA_FILE = ROOT / "data" / "notices.json"
DEBUG_DIR = ROOT / "data" / "debug"
OUT_HTML = ROOT / "docs" / "index.html"
TEMPLATE = ROOT / "template.html"

CAL_URL = os.environ.get("CAL_URL", "https://20kjh02.github.io/cheongyak-calendar/")
LIST_URL = "http://apis.data.go.kr/B552555/lhLeaseNoticeInfo1/lhLeaseNoticeInfo1"
# 상세정보 API: '한국토지주택공사_분양임대공고별 상세정보 조회 서비스' (접수처/단지/일정 정보)
# 공공데이터포털에서 이 서비스를 따로 활용신청해야 호출됩니다.
DETAIL_URL = "https://apis.data.go.kr/B552555/lhLeaseNoticeDtlInfo1/getLeaseNoticeDtlInfo1"

REGIONS = {"11": "서울", "41": "경기", "28": "인천"}  # 지역코드
LEASE_TYPE = "06"                                     # 상위유형: 임대주택
STATUSES = ["공고중", "접수중"]
PAGE_SIZE = 50
KEEP_DAYS = 14  # 종료 후 이 기간까지 캘린더에 남김

DEBUG = "--debug" in sys.argv
TEST_MAIL = "--test-mail" in sys.argv
_debug_saved = set()


# ---------- 공통 유틸 ----------
def norm_date(value):
    """'2026.11.20', '20261120', '2026-11-20 10:00' 등을 'YYYY-MM-DD'로."""
    if not value:
        return None
    m = re.search(r"(\d{4})\D?(\d{1,2})\D?(\d{1,2})", str(value))
    if not m:
        return None
    try:
        return datetime(int(m[1]), int(m[2]), int(m[3])).date().isoformat()
    except ValueError:
        return None


def walk(obj):
    """중첩된 JSON 안의 모든 dict를 순회."""
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk(v)


def call_api(url, params, tag):
    try:
        r = requests.get(url, params=params, timeout=30)
    except requests.RequestException as e:
        # 오류 메시지에 인증키가 들어간 URL이 섞일 수 있어 종류만 출력
        raise RuntimeError(f"[{tag}] 요청 실패: {type(e).__name__}") from None
    if r.status_code != 200:
        raise RuntimeError(f"[{tag}] HTTP {r.status_code}: {r.text[:200]}")
    if DEBUG and tag not in _debug_saved:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        (DEBUG_DIR / f"{tag}.txt").write_text(r.text[:20000], encoding="utf-8")
        _debug_saved.add(tag)
    try:
        return r.json()
    except ValueError:
        raise RuntimeError(f"[{tag}] JSON이 아닌 응답: {r.text[:200]}") from None


# ---------- LH 수집 ----------
def fetch_list(key):
    rows = []
    for cnp, region in REGIONS.items():
        for status in STATUSES:
            for page in range(1, 11):
                data = call_api(LIST_URL, {
                    "serviceKey": key, "PG_SZ": PAGE_SIZE, "PAGE": page,
                    "UPP_AIS_TP_CD": LEASE_TYPE, "CNP_CD": cnp, "PAN_SS": status,
                }, f"list_{cnp}_{status}")
                found = [d for obj in walk(data) for d in
                         (obj["dsList"] if isinstance(obj.get("dsList"), list) else [])]
                for d in found:
                    d["_region"] = region
                rows += found
                if len(found) < PAGE_SIZE:
                    break
    return rows


START_RE = re.compile(r"(ACP|SBSC|RCPT|APLY).*(_ST_|_ST$|STR|BGN)", re.I)
END_RE = re.compile(r"(ACP|SBSC|RCPT|APLY).*(CLSG|_ED_|_ED$|END)", re.I)


def fetch_dates(key, item):
    """상세 API에서 접수 시작/종료일을 찾는다. 못 찾으면 (None, None)."""
    try:
        data = call_api(DETAIL_URL, {
            "serviceKey": key,
            "SPL_INF_TP_CD": item.get("SPL_INF_TP_CD", ""),
            "CCR_CNNT_SYS_DS_CD": item.get("CCR_CNNT_SYS_DS_CD", ""),
            "PAN_ID": item.get("PAN_ID", ""),
            "UPP_AIS_TP_CD": item.get("UPP_AIS_TP_CD", LEASE_TYPE),
            "AIS_TP_CD": item.get("AIS_TP_CD", ""),
        }, "detail")
    except RuntimeError as e:
        print(f"  상세 조회 실패({item.get('PAN_ID')}): {e}")
        return None, None
    starts, ends = [], []
    for obj in walk(data):
        for k, v in obj.items():
            d = norm_date(v) if isinstance(v, (str, int)) else None
            if not d:
                continue
            if START_RE.search(k):
                starts.append(d)
            elif END_RE.search(k):
                ends.append(d)
    return (min(starts) if starts else None, max(ends) if ends else None)


def build_records(key, rows, store):
    for it in rows:
        pid = it.get("PAN_ID")
        if not pid:
            continue
        old = store.get(pid, {})
        rec = {
            "id": pid,
            "org": "LH",
            "name": (it.get("PAN_NM") or "").strip(),
            "region": it["_region"],
            "type": it.get("AIS_TP_CD_NM") or "임대",
            "status": it.get("PAN_SS") or "",
            "posted": norm_date(it.get("PAN_NT_ST_DT")),
            "close": norm_date(it.get("CLSG_DT")),
            "url": it.get("DTL_URL") or "https://apply.lh.or.kr/",
            "start": old.get("start"),
            "end": old.get("end"),
            "notified_start": old.get("notified_start", False),
            "notified_new": old.get("notified_new", False),
        }
        if not rec["start"]:  # 접수 시작일을 아직 모르면 매번 재시도
            s, e = fetch_dates(key, it)
            rec["start"], rec["end"] = s, e or rec["close"]
        store[pid] = rec


# ---------- 이메일 ----------
def send_mail(subject, html):
    user, pw, to = (os.environ.get(k, "").strip() for k in ("GMAIL_USER", "GMAIL_APP_PASSWORD", "MAIL_TO"))
    pw = "".join(pw.split())  # 공백/줄바꿈 제거
    if not (user and pw and to):
        raise RuntimeError("GMAIL_USER / GMAIL_APP_PASSWORD / MAIL_TO 시크릿이 필요합니다.")
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    msg.attach(MIMEText(html, "html", "utf-8"))
    last = None
    for mode in ("ssl465", "starttls587"):  # 한 방식이 막히면 다른 방식으로 재시도
        try:
            if mode == "ssl465":
                server = smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30)
            else:
                server = smtplib.SMTP("smtp.gmail.com", 587, timeout=30)
                server.starttls()
            with server as s:
                s.login(user, pw)
                s.sendmail(user, [to], msg.as_string())
            return
        except smtplib.SMTPAuthenticationError as e:
            raise RuntimeError(f"Gmail 인증 실패({e.smtp_code}): 앱 비밀번호 또는 GMAIL_USER 확인 필요") from None
        except (smtplib.SMTPException, OSError) as e:
            last = f"{mode}: {type(e).__name__}"
            print(f"  메일 전송 방식 실패 - {last}")
    raise RuntimeError(f"메일 전송 실패 ({last})")


def create_issue(title, md):
    """메일이 막힐 때의 대체 경로: GitHub 이슈를 만들어 저장소 주인을 멘션(알림 메일은 GitHub가 발송)."""
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not (token and repo):
        raise RuntimeError("GITHUB_TOKEN / GITHUB_REPOSITORY 없음")
    owner = repo.split("/")[0]
    try:
        r = requests.post(
            f"https://api.github.com/repos/{repo}/issues",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
            json={"title": title, "body": f"@{owner}\n\n{md}"}, timeout=30)
    except requests.RequestException as e:
        raise RuntimeError(f"GitHub 이슈 생성 요청 실패: {type(e).__name__}") from None
    if r.status_code != 201:
        raise RuntimeError(f"GitHub 이슈 생성 실패 HTTP {r.status_code}: {r.text[:200]}")


def notify(subject, html, md):
    """메일을 먼저 시도하고, 실패하면 GitHub 이슈로 알림. 성공한 경로 이름을 반환."""
    try:
        send_mail(subject, html)
        return "메일"
    except Exception as e:
        print(f"메일 실패: {e} -> GitHub 이슈로 대체")
    create_issue(subject, md)
    return "GitHub 이슈"


def notice_rows_md(recs):
    out = []
    for r in recs:
        period = f"{r['start']} ~ {r['end'] or '?'}" if r["start"] else f"공고일 {r['posted'] or '?'} (접수일 확인 필요)"
        out.append(f"- **[{r['region']}] {r['name']}**  \n  {r['type']} · {period} · [공고 원문]({r['url']})")
    return "\n".join(out)


def notice_rows_html(recs):
    out = []
    for r in recs:
        period = f"{r['start']} ~ {r['end'] or '?'}" if r["start"] else f"공고일 {r['posted'] or '?'} (접수일 확인 필요)"
        out.append(
            f"<li style='margin-bottom:10px'><b>[{escape(r['region'])}] {escape(r['name'])}</b><br>"
            f"{escape(r['type'])} · {period}<br><a href='{escape(r['url'])}'>공고 원문 보기</a></li>"
        )
    return "<ul style='padding-left:18px'>" + "".join(out) + "</ul>"


def alert(store, today):
    tomorrow = today + timedelta(days=1)
    due = [r for r in store.values()
           if r["start"] and today.isoformat() <= r["start"] <= tomorrow.isoformat()
           and not r["notified_start"]]
    unknown = [r for r in store.values() if not r["start"] and not r["notified_new"]]
    if not due and not unknown:
        print("보낼 알림 없음")
        return
    body, md = "", ""
    if due:
        body += f"<h3>내일 접수 시작 ({len(due)}건)</h3>" + notice_rows_html(due)
        md += f"### 내일 접수 시작 ({len(due)}건)\n{notice_rows_md(due)}\n\n"
    if unknown:
        body += (f"<h3>신규 공고 - 접수일 확인 필요 ({len(unknown)}건)</h3>"
                 "<p style='color:#666'>접수 시작일을 자동으로 읽지 못한 공고입니다. 원문에서 일정을 확인하세요.</p>"
                 + notice_rows_html(unknown))
        md += (f"### 신규 공고 - 접수일 확인 필요 ({len(unknown)}건)\n"
               "접수 시작일을 자동으로 읽지 못한 공고입니다. 원문에서 일정을 확인하세요.\n"
               f"{notice_rows_md(unknown)}\n\n")
    body += f"<p><a href='{CAL_URL}'>청약 캘린더 열기</a></p>"
    md += f"[청약 캘린더 열기]({CAL_URL})"
    subject = "[청약알림] " + (f"내일 접수 시작 {len(due)}건" if due else f"신규 공고 {len(unknown)}건")
    how = notify(subject, body, md)
    for r in due:
        r["notified_start"] = True
    for r in unknown:
        r["notified_new"] = True
    print(f"{how} 알림 완료: 접수 임박 {len(due)}건, 일정 미확인 {len(unknown)}건")


# ---------- 캘린더 페이지 ----------
def render(store, now):
    records = sorted(store.values(), key=lambda r: r["start"] or r["posted"] or "")
    public = [{k: r[k] for k in ("id", "org", "name", "region", "type", "status",
                                 "posted", "start", "end", "url")} for r in records]
    meta = {"updated": now.strftime("%Y-%m-%d %H:%M")}
    html = TEMPLATE.read_text(encoding="utf-8")
    dump = lambda o: json.dumps(o, ensure_ascii=False).replace("</", "<\\/")
    html = html.replace("/*DATA*/[]", dump(public)).replace("/*META*/{}", dump(meta))
    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUT_HTML.write_text(html, encoding="utf-8")


def main():
    now = datetime.now(KST)
    today = now.date()

    test_error = None
    if TEST_MAIL:
        try:
            how = notify("[청약알림] 테스트 알림",
                         f"<p>알림 설정이 정상입니다.</p><p><a href='{CAL_URL}'>청약 캘린더 열기</a></p>",
                         f"알림 설정이 정상입니다.\n\n[청약 캘린더 열기]({CAL_URL})")
            print(f"테스트 알림 발송 완료 ({how})")
        except Exception as e:  # 알림이 실패해도 LH 수집 확인은 계속 진행
            test_error = e
            print(f"테스트 알림 실패: {e}")

    key = unquote(os.environ.get("LH_API_KEY", "").strip())
    if not key:
        sys.exit("LH_API_KEY 시크릿이 없습니다.")

    store = json.loads(DATA_FILE.read_text(encoding="utf-8")) if DATA_FILE.exists() else {}
    rows = fetch_list(key)
    print(f"목록 {len(rows)}건 수집")
    build_records(key, rows, store)

    cutoff = (today - timedelta(days=KEEP_DAYS)).isoformat()
    store = {k: r for k, r in store.items()
             if (r["end"] or r["start"] or r["posted"] or "9999") >= cutoff}

    mail_error = test_error
    if not test_error:
        try:
            alert(store, today)
        except Exception as e:  # 메일이 실패해도 캘린더와 데이터는 저장
            mail_error = e

    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps(store, ensure_ascii=False, indent=1), encoding="utf-8")
    render(store, now)
    print(f"저장 완료: {len(store)}건")
    if mail_error:
        sys.exit(f"알림 발송 실패: {mail_error}")


if __name__ == "__main__":
    main()
