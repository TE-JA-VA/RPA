# -*- coding: utf-8 -*-
"""사내 서버 ③ Task 5 - 로그인 이력 DB login_log (계획 2026-11-25-lan-3-web-auth, 설계 6.6 '로그인 이력').
넣기·찾기(최신 먼저, 아이디·결과·기간 거르기, before_id 로 다음 쪽, limit 1~200), RESULTS 밖 거절, 1년 지난 줄 지우기(하루 한 번),
브라우저 종류. 포트는 열지 않는다. 윈도우·리눅스(WSL) 둘 다 같은 파일로 돈다.
    D:/AX/RPA/.venv/Scripts/python.exe tests/test_login_log.py
    wsl.exe -d Ubuntu -e python3 /mnt/d/AX/RPA_StandAlone/tests/test_login_log.py
"""
import os
import shutil
import sqlite3
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "firebase", "agent"))
import login_log  # noqa: E402

fails = []
TMP = tempfile.mkdtemp(prefix="rpa_login_log_")
DAY = 86400
T0 = 1_790_000_000.0          # 2026-09 무렵 - 손 시계의 시작


def check(name, ok, detail=""):
    print(f"  [{'통과' if ok else '실패'}] {name}" + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


class Clock:
    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t


def test_add_query():
    print("test_add_query")
    c = Clock()
    log = login_log.LoginLog(":memory:", clock=c)
    rows = [("ok", "boss", "10.0.0.5", "Edge · Windows"), ("bad_password", None, "10.0.0.6", "Chrome · Android"),
            ("ok", "staff", "10.0.0.6", "Firefox · Linux"), ("locked", "staff", "10.0.0.6", "Chrome · Android"),
            ("logout", "boss", "10.0.0.5", "Edge · Windows")]
    for i, (res, uid, ip, agent) in enumerate(rows):
        c.t = T0 + i
        log.add(res, uid, ip, agent)
    got = log.query()
    check("다섯 줄, 넣은 차례 반대로", [g["result"] for g in got] == [r[0] for r in reversed(rows)], repr(got))
    check("칸 id·at·uid·ip·agent·result", got and set(got[0]) == {"id", "at", "uid", "ip", "agent", "result"}, repr(got[:1]))
    check("at 는 ms (손 시계)", [g["at"] for g in got] == [int((T0 + i) * 1000) for i in range(4, -1, -1)], repr(got))
    check("id 는 줄어든다 (최신 먼저)", [g["id"] for g in got] == sorted((g["id"] for g in got), reverse=True))
    check("없는 아이디는 uid None", got[3]["uid"] is None and got[3]["ip"] == "10.0.0.6", repr(got[3]))
    boss = log.query(uid="boss")
    check("uid 거르기 boss → 2", [g["result"] for g in boss] == ["logout", "ok"] and all(g["uid"] == "boss" for g in boss), repr(boss))
    oks = log.query(result="ok")
    check("result 거르기 ok → 2", [g["uid"] for g in oks] == ["staff", "boss"], repr(oks))
    mid = log.query(since_ms=int((T0 + 1) * 1000), until_ms=int((T0 + 3) * 1000))
    check("기간 [1초, 3초) → 2줄 (끝은 빼고)", [g["result"] for g in mid] == ["ok", "bad_password"], repr(mid))
    page1 = log.query(limit=2)
    page2 = log.query(limit=2, before_id=page1[-1]["id"])
    page3 = log.query(limit=2, before_id=page2[-1]["id"])
    check("before_id 로 다음 쪽 (2·2·1)", [len(page1), len(page2), len(page3)] == [2, 2, 1]
          and [g["id"] for g in page1 + page2 + page3] == [g["id"] for g in got], repr((page1, page2, page3)))
    check("limit 0 → 1", len(log.query(limit=0)) == 1)
    check("limit -5 → 1", len(log.query(limit=-5)) == 1)
    for i in range(250):
        log.add("ok", "boss", "10.0.0.5", "Edge · Windows")
    check("limit 999 → 200", len(log.query(limit=999)) == 200)
    check("limit 기본 50", len(log.query()) == 50)
    last = log.last_ok("staff")
    check("last_ok(staff) = 그 ok 줄", last is not None and last["result"] == "ok" and last["ip"] == "10.0.0.6"
          and last["at"] == int((T0 + 2) * 1000), repr(last))
    check("last_ok(before_id) 는 그 앞", log.last_ok("staff", before_id=last["id"]) is None)
    check("last_ok(없는 아이디) None", log.last_ok("ghost") is None)
    log.add("recovery", "solo", "10.0.0.9", "기타")
    check("복구 번호 로그인도 마지막 로그인으로 본다", (log.last_ok("solo") or {}).get("result") == "recovery")
    log.close()


def test_bad_result():
    print("test_bad_result")
    log = login_log.LoginLog(":memory:", clock=Clock())
    for bad in ("weird", None, "OK", ""):
        try:
            log.add(bad, "boss", "10.0.0.5", "Edge · Windows")
            ok = False
        except ValueError:
            ok = True
        check(f"result {bad!r} → ValueError", ok)
    try:
        log.add("ok", 123, "10.0.0.5", "x")
        ok = False
    except ValueError:
        ok = True
    check("uid 가 글이 아니면 ValueError", ok)
    check("거절된 것은 줄이 없다", log.query() == [])
    check("RESULTS 열한 가지", login_log.RESULTS == ("ok", "bad_password", "bad_code", "locked", "disabled", "logout", "timeout",
                                                  "mfa_on", "mfa_off", "mfa_reset", "recovery"))
    check("상수", (login_log.LOGINS_NAME, login_log.KEEP_DAYS) == ("logins.db", 365))
    log.add("ok", "boss", "10.0.0.5", "x" * 500)
    check("agent 는 40자 안으로 자른다", len(log.query()[0]["agent"]) <= 40)
    log.close()


def test_purge():
    print("test_purge")
    c = Clock()
    path = os.path.join(TMP, "purge", login_log.LOGINS_NAME)
    log = login_log.LoginLog(path, clock=c)
    check("파일이 생긴다 (폴더도)", os.path.isfile(path))
    log.add("ok", "boss", "10.0.0.5", "Edge · Windows")              # 첫 add 가 purge 한 번
    T = T0 + DAY                                                      # 다음 purge 시각
    c.t = T - 366 * DAY
    log.add("ok", "old", "10.0.0.5", "Edge · Windows")
    c.t = T - 364 * DAY
    log.add("ok", "young", "10.0.0.5", "Edge · Windows")
    c.t = T0 + 3600
    log.add("ok", "boss", "10.0.0.5", "Edge · Windows")
    check("하루가 안 지났으면 add 가 purge 를 다시 부르지 않는다 (366일 전 줄이 아직 있음)",
          len(log.query(limit=200)) == 4 and log.last_ok("old") is not None)
    c.t = T
    log.add("ok", "boss", "10.0.0.5", "Edge · Windows")
    uids = [g["uid"] for g in log.query(limit=200)]
    check("하루 뒤 add → 366일 전 줄은 지워지고 364일 전은 남음", "old" not in uids and "young" in uids and len(uids) == 4, repr(uids))
    check("그 뒤 purge() 는 0", log.purge() == 0)
    c.t = T + 10 * DAY
    check("purge() 는 지운 수", log.purge() == 1)                        # young 이 이제 374일 전
    log.close()
    db = sqlite3.connect(path)
    try:
        names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'index')")}
        cols = [r[1] for r in db.execute("PRAGMA table_info(logins)")]
    finally:
        db.close()
    check("표 logins 와 at·uid 색인", "logins" in names and len([n for n in names if n != "logins" and not n.startswith("sqlite_")]) >= 2,
          repr(names))
    check("칸 id·at·uid·ip·agent·result", cols == ["id", "at", "uid", "ip", "agent", "result"], repr(cols))
    again = login_log.LoginLog(path, clock=c)                         # 다시 열어도 그대로 (표를 새로 만들지 않는다)
    check("다시 열면 줄이 그대로", len(again.query()) == 3, repr(again.query()))
    again.close()


EDGE = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 "
        "Edg/131.0.0.0")
CHROME_MAC = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 "
              "Safari/537.36")
CHROME_ANDROID = ("Mozilla/5.0 (Linux; Android 14; SM-S921N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile "
                  "Safari/537.36")
FIREFOX_LINUX = "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0"
SAFARI_IOS = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 "
              "Mobile/15E148 Safari/604.1")
SAFARI_MAC = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 "
              "Safari/605.1.15")
CHROME_IOS = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/131.0.6778.73 "
              "Mobile/15E148 Safari/604.1")


def test_browser_kind():
    print("test_browser_kind")
    want = [(EDGE, "Edge · Windows"), (CHROME_MAC, "Chrome · macOS"), (CHROME_ANDROID, "Chrome · Android"),
            (FIREFOX_LINUX, "Firefox · Linux"), (SAFARI_IOS, "Safari · iOS"), (SAFARI_MAC, "Safari · macOS"),
            (CHROME_IOS, "Chrome · iOS"), ("", "기타"), (None, "기타"), ("curl/8.5.0", "기타")]
    for ua, kind in want:
        got = login_log.browser_kind(ua)
        check(f"{kind} ← {(ua or repr(ua))[:40]}", got == kind, got)
    weird = ("Windows Edg/ Firefox/ \x00\n" + "가" * 300 + "<script>" * 30)[:520]
    got = login_log.browser_kind(weird)
    check("500자 넘는 이상한 글도 40자 안·원문 조각 없음", len(got) <= 40 and "<" not in got and "가" not in got, got)
    check("글이 아닌 값 → 기타", login_log.browser_kind(12345) == "기타")


TESTS = [test_add_query, test_bad_result, test_purge, test_browser_kind]

if __name__ == "__main__":
    try:
        for fn in TESTS:
            try:
                fn()
            except Exception as ex:          # 한 시험이 터져도 나머지는 돈다
                check(f"{fn.__name__} 가 예외 없이 끝난다", False, f"{type(ex).__name__}: {ex}")
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    print(f"\n실패: {len(fails)}" + (" (" + ", ".join(fails) + ")" if fails else ""))
    sys.exit(1 if fails else 0)
