# -*- coding: utf-8 -*-
"""사내 서버 ③ 전체 검토 고침 - 웹 인증 보강 (계획 2026-11-25-lan-3-web-auth, 설계 6.6).
    1. logins.db 가 깨졌으면 .broken 으로 치우고 새로, 그래도 못 열면 이력 없이 켜진다 (로그인은 되고 이력 창구 503)
    2. 계정마다 2단계 번호 연속 10번 틀리면 모든 주소에서 3600초 막음, 로그인 성공 응답의 failedSince
    3. 자동 로그아웃 이력 줄의 시각 = 세션이 실제로 끝난 시각 (미사용 30분·12시간 가운데 먼저)
    4. 켜진 계정의 setup 이 비밀번호만으로 (아이디, 주소) 잠금 셈을 지우지 않음
    5. 켜진 계정의 setup 은 비밀번호 + 지금 번호 또는 복구 번호
    6. 이미 쓴 칸의 번호는 400 auth/code-used - 잠금·이력에 세지 않음
    7. 계정의 mfa 칸 꼴이 틀리면 사내 서버 로그인 403 auth/mfa-broken (관리자 mfaReset 으로만 풀림)
도우미(서버 띄우기·api·손 시계·번호)는 test_lan_mfa.py 의 것을 쓴다. 윈도우·리눅스(WSL) 둘 다.
    D:/AX/RPA/.venv/Scripts/python.exe tests/test_lan_mfa_review.py
    wsl.exe -d Ubuntu -e python3 /mnt/d/AX/RPA_StandAlone/tests/test_lan_mfa_review.py
"""
import copy
import dataclasses
import http.client
import json
import os
import shutil
import sys
import tempfile
import threading
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_lan_mfa as m  # noqa: E402  (인증서·도우미 - 불러오면 임시 폴더와 인증 기관을 만든다)

local_server, local_web, lan_config, lan_server, pc_registry, totp = (
    m.local_server, m.local_web, m.lan_config, m.lan_server, m.pc_registry, m.totp)
check, api, login, token, enroll, code_now, wrong_code, hist, count, log_text = (
    m.check, m.api, m.login, m.token, m.enroll, m.code_now, m.wrong_code, m.hist, m.count, m.log_text)
A, B, C, D = m.A, m.B, m.C, m.D
BOSS_PW, STAFF_PW = m.BOSS_PW, m.STAFF_PW


def start(scope=None, prep=None):
    """test_lan_mfa.start 와 같다 - prep(folder) 를 Web 을 만들기 **전에** 부른다 (logins.db 를 미리 망가뜨리기)."""
    folder = tempfile.mkdtemp(dir=m.TMP)
    if scope is not None:
        m.write_security(folder, scope)
    if prep is not None:
        prep(folder)
    store = local_server.Store(os.path.join(folder, "store.json"), volatile=local_server.VOLATILE)
    runs = local_server.Runs(":memory:")
    m.RUNS.append(runs)
    reg = pc_registry.Registry(os.path.join(folder, "pcs.json"), seats=20)
    clock = m.Clock()
    web = local_web.Web(store, runs, m.LIC, folder, None, clock=clock, registry=reg)
    m.WEBS.append(web)
    web.accounts.set("boss", BOSS_PW, "admin")
    web.accounts.set("staff", STAFF_PW, "viewer")
    cfg = dataclasses.replace(lan_config.parse(m.CFG), web_port=0, agent_port=0)
    w, a = lan_server.make_lan_servers(store, runs, m.LIC, reg, web, cfg, m.CERT, m.KEY, m.CA_PEM)
    for s in (w, a):
        threading.Thread(target=s.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        m.SERVERS.append(s)
    return types.SimpleNamespace(wp=w.server_address[1], ui=web, folder=folder, clock=clock, reg=reg)


def ticket(env, ip, uid="boss", pw=BOSS_PW):
    return (login(env, ip, uid, pw).json() or {}).get("ticket")


def code_login(env, ip, t, code):
    return api(env, ip, "POST", "/api/login/mfa", {"ticket": t, "code": code})


def msg(g):
    v = g.json()
    return v.get("message", "") if isinstance(v, dict) else ""


def corrupt_mfa(env, uid, fn):
    """accounts.json 의 그 계정 mfa 칸을 fn(기록) 으로 바꾼다 (사람이 파일을 잘못 고친 자리)."""
    path = os.path.join(env.folder, "accounts.json")
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    fn(raw["accounts"][uid])
    with open(path, "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False)
    env.ui.accounts._stamp = None            # 크기가 같아도 다시 읽게


# ----------------------------------------------------------------------------------------------------
# 1. logins.db 가 깨졌거나 열리지 않을 때
# ----------------------------------------------------------------------------------------------------

GARBAGE = b"this is not a sqlite database - " * 256


def test_broken_logins_db():
    print("test_broken_logins_db")

    def garbage(folder):
        with open(os.path.join(folder, "logins.db"), "wb") as f:
            f.write(GARBAGE)
        with open(os.path.join(folder, "logins.db.broken"), "wb") as f:      # 앞서 치운 것이 있어도 덮어쓴다
            f.write(b"old broken")

    try:
        e = start("off", prep=garbage)
    except Exception as ex:
        check("쓰레기 logins.db 로도 Web 을 만든다", False, f"{type(ex).__name__}: {ex}")
        return
    check("쓰레기 logins.db 로도 Web 을 만든다 (login_log 있음)", e.ui.login_log is not None)
    with open(os.path.join(e.folder, "logins.db.broken"), "rb") as f:
        check("  깨진 파일은 logins.db.broken 으로 (옛 .broken 은 덮어씀)", f.read() == GARBAGE)
    r = login(e, A)
    check("  로그인 200", r.status == 200 and (r.json() or {}).get("token"), r)
    rows = hist(e)
    check("  새 logins.db 에 이력 줄이 쓰인다 (ok boss)", count(rows, "ok", "boss", A) == 1 and len(rows) == 1, repr(rows))
    check("  서버 기록에 옮긴 일 한 줄", "logins.db.broken" in log_text(e), log_text(e)[-300:])

    def folder_in_place(folder):              # 그 자리에 폴더 - 열 수 없고 옮기지도 않는다
        os.makedirs(os.path.join(folder, "logins.db"))

    try:
        e = start("off", prep=folder_in_place)
    except Exception as ex:
        check("logins.db 를 열 수 없어도 Web 을 만든다", False, f"{type(ex).__name__}: {ex}")
        return
    check("logins.db 를 열 수 없어도 Web 을 만든다 (login_log None)", e.ui.login_log is None)
    check("  서버 기록 '로그인 이력을 열지 못했습니다: <종류>'", "로그인 이력을 열지 못했습니다: " in log_text(e), log_text(e)[-300:])
    r = login(e, A)
    j = r.json() or {}
    check("  로그인 200·lastLogin None·failedSince 0", r.status == 200 and j.get("token") and j.get("lastLogin") is None
          and j.get("failedSince") == 0, r)
    boss = j.get("token")
    for path in ("/api/logins", "/api/logins/me"):
        g = api(e, A, "GET", path, tok=boss)
        check(f"  {path} → 503 unavailable", g.status == 503 and g.code == "unavailable", g)
    g = login(e, A, "staff", "wrong-pass-01")
    check("  틀린 비밀번호는 그대로 401", g.status == 401, g)
    g = api(e, A, "POST", "/api/logout", {}, boss)
    check("  로그아웃 200", g.status == 200, g)
    check("  폴더는 그대로 (치우지 않음)", os.path.isdir(os.path.join(e.folder, "logins.db"))
          and not os.path.exists(os.path.join(e.folder, "logins.db.broken")))


# ----------------------------------------------------------------------------------------------------
# 2. 계정마다 2단계 번호 연속 실패 제한 · failedSince
# ----------------------------------------------------------------------------------------------------

def test_mfa_fail_limit():
    print("test_mfa_fail_limit")
    e = start()
    boss = token(e, A)
    secret, rec = enroll(e, A, boss)
    ips = [f"10.0.2.{i}" for i in range(1, 12)]
    bad = [code_login(e, ip, ticket(e, ip), wrong_code(e, secret)) for ip in ips[:10]]
    check("서로 다른 주소 10곳에서 틀린 번호 한 번씩 → 모두 401 invalid-code",
          all(g.status == 401 and g.code == "auth/invalid-code" for g in bad), bad)
    rows = hist(e)
    check("  10번째에 locked 한 줄 (10번째 주소)", count(rows, "locked", "boss") == 1 and count(rows, "locked", "boss", ips[9]) == 1,
          repr([(r["result"], r["ip"]) for r in rows]))
    check("  서버 기록에 2단계 번호 잠금 줄", "웹 2단계 번호 잠금" in log_text(e) and "아이디=boss" in log_text(e), log_text(e)[-400:])
    t = ticket(e, ips[10])
    check("11번째 주소 - 비밀번호 단계는 그대로 표", bool(t))
    n = len(hist(e))
    g = code_login(e, ips[10], t, code_now(e, secret))
    check("  맞는 번호도 429 too-many-requests (1시간 안내)", g.status == 429 and g.code == "auth/too-many-requests"
          and "1시간" in msg(g) and "관리자" in msg(g), g)
    g = code_login(e, ips[10], t, wrong_code(e, secret))
    check("  막힌 동안 틀린 번호도 429, 이력 줄이 늘지 않음", g.status == 429 and len(hist(e)) == n, g)
    g = api(e, ips[10], "POST", "/api/login/mfa", {"ticket": t, "recovery": rec[0]})
    check("  복구 번호도 429", g.status == 429, g)
    check("  복구 번호는 쓰이지 않음 (8개 그대로)", e.ui.accounts.mfa_info("boss")["recovery_left"] == 8)
    g = api(e, A, "POST", "/api/security", {"totpScope": "off", "password": BOSS_PW, "code": code_now(e, secret)}, boss)
    check("  보안 범위 줄이기의 번호 확인도 429", g.status == 429 and e.ui.security.get()["totp_scope"] == "admin", g)
    g = api(e, A, "POST", "/api/mfa/setup", {"password": BOSS_PW, "code": code_now(e, secret)}, boss)
    check("  다시 등록(setup)도 429", g.status == 429, g)
    e.clock.go(3601)
    t = ticket(e, ips[10])
    g = code_login(e, ips[10], t, code_now(e, secret))
    j = g.json() or {}
    check("3601초 뒤 맞는 번호 → 200", g.status == 200 and j.get("token"), g)
    check("  failedSince 10 (앞 로그인 뒤 틀린 번호 10줄)", j.get("failedSince") == 10, g)
    e.clock.go(totp.STEP)
    more = [code_login(e, ip, ticket(e, ip), wrong_code(e, secret)) for ip in (f"10.0.3.{i}" for i in range(1, 10))]
    check("맞힌 뒤 셈은 0 - 다시 9번 틀려도 401", all(g.status == 401 for g in more), more)
    g = code_login(e, "10.0.3.20", ticket(e, "10.0.3.20"), code_now(e, secret))
    check("  그 뒤 맞는 번호 200·failedSince 9", g.status == 200 and (g.json() or {}).get("failedSince") == 9, g)

    # 막힘이 끝난 뒤 (성공 없이) 첫 시도가 틀리면 다시 3600초
    e2 = start()
    sec2, _ = enroll(e2, A, token(e2, A))
    for i in range(1, 11):
        ip = f"10.0.4.{i}"
        code_login(e2, ip, ticket(e2, ip), wrong_code(e2, sec2))
    e2.clock.go(3601)
    t = ticket(e2, "10.0.4.20")
    g = code_login(e2, "10.0.4.20", t, wrong_code(e2, sec2))
    check("막힘이 끝난 뒤 첫 틀린 번호 → 401 (확인함)", g.status == 401 and g.code == "auth/invalid-code", g)
    g = code_login(e2, "10.0.4.20", t, code_now(e2, sec2))
    check("  곧바로 다시 막힘 - 맞는 번호도 429", g.status == 429, g)
    check("  locked 줄 둘", count(hist(e2), "locked", "boss") == 2, repr([r["result"] for r in hist(e2)]))
    e2.clock.go(3601)
    g = code_login(e2, "10.0.4.20", ticket(e2, "10.0.4.20"), code_now(e2, sec2))
    check("  3601초 뒤 200", g.status == 200, g)

    # 관리자가 2단계를 풀어 주면 막힘도 풀린다 (다시 등록할 수 있게)
    e3 = start()
    e3.ui.accounts.set("boss2", "boss2-pw-0001", "admin")
    b2 = token(e3, D, "boss2", "boss2-pw-0001")
    enroll(e3, D, b2)
    sec3, _ = enroll(e3, A, token(e3, A))
    for i in range(1, 11):
        ip = f"10.0.5.{i}"
        code_login(e3, ip, ticket(e3, ip), wrong_code(e3, sec3))
    g = code_login(e3, A, ticket(e3, A), code_now(e3, sec3))
    check("관리자 해제 전 - 429", g.status == 429, g)
    g = api(e3, D, "POST", "/api/accounts/boss", {"mfaReset": True}, b2)
    check("  관리자 mfaReset → 200", g.status == 200, g)
    tok = token(e3, A)
    s = api(e3, A, "POST", "/api/mfa/setup", {}, tok).json() or {}
    g = api(e3, A, "POST", "/api/mfa/enable", {"code": code_now(e3, s.get("secret") or "A" * 32)}, tok)
    check("  풀린 뒤 다시 등록(enable) 200", g.status == 200 and len((g.json() or {}).get("recovery") or []) == 8, g)


def test_failed_since():
    print("test_failed_since")
    e = start("off")
    r = login(e, A)
    check("첫 로그인 failedSince 0 (이력 없음)", r.status == 200 and (r.json() or {}).get("failedSince") == 0, r)
    login(e, B, "boss", "wrong-pass-01")
    login(e, B, "boss", "wrong-pass-01")
    login(e, B, "staff", "wrong-pass-01")                    # 다른 계정의 실패는 세지 않는다
    login(e, B, "ghost", "wrong-pass-01")
    r = login(e, A)
    check("틀린 비밀번호 2번 뒤 로그인 → failedSince 2", r.status == 200 and (r.json() or {}).get("failedSince") == 2, r)
    r = login(e, A)
    boss = (r.json() or {}).get("token")
    check("  바로 다음 로그인 → 0", r.status == 200 and (r.json() or {}).get("failedSince") == 0, r)
    secret, _ = enroll(e, A, boss)
    login(e, C, "boss", "wrong-pass-01")
    t = ticket(e, A)
    code_login(e, A, t, wrong_code(e, secret))
    g = code_login(e, A, t, code_now(e, secret))
    check("2단계 로그인 - 틀린 비밀번호 1 + 틀린 번호 1 → failedSince 2", g.status == 200 and (g.json() or {}).get("failedSince") == 2, g)
    e.clock.go(totp.STEP)
    g = code_login(e, A, ticket(e, A), code_now(e, secret))
    check("  다음 2단계 로그인 → 0", g.status == 200 and (g.json() or {}).get("failedSince") == 0, g)


# ----------------------------------------------------------------------------------------------------
# 3. 자동 로그아웃 이력 줄의 시각
# ----------------------------------------------------------------------------------------------------

def test_timeout_at():
    print("test_timeout_at")
    e = start("off")
    t0 = e.clock()
    token(e, D, "staff", STAFF_PW)
    e.clock.go(72 * 3600)
    login(e, A)                                             # 다른 사람의 로그인이 끝난 세션을 치운다
    rows = [r for r in hist(e) if r["result"] == "timeout"]
    check("요청 없이 72시간 → timeout 줄 at = 로그인 + 1800초", len(rows) == 1 and rows[0]["uid"] == "staff" and rows[0]["ip"] == D
          and rows[0]["at"] == int((t0 + 1800) * 1000), repr(rows) + f" 기대 {int((t0 + 1800) * 1000)}")
    t1 = e.clock()
    stok = token(e, C, "staff", STAFF_PW)
    ok = True
    for _ in range(28):                                     # 25분마다 손을 대 12시간 가까이 이어 간다
        e.clock.go(1500)
        ok = ok and api(e, C, "GET", "/api/session?touch=1", tok=stok).status == 200
    check("  25분마다 쓰면 11시간 40분까지 이어진다", ok)
    e.clock.go(72 * 3600)
    login(e, A)
    rows = [r for r in hist(e) if r["result"] == "timeout" and r["uid"] == "staff" and r["ip"] == C]
    check("12시간 상한으로 끝난 세션 → at = 로그인 + 43200초", len(rows) == 1 and rows[0]["at"] == int((t1 + 43200) * 1000),
          repr(rows) + f" 기대 {int((t1 + 43200) * 1000)}")


# ----------------------------------------------------------------------------------------------------
# 4·5. 켜진 계정의 다시 등록(setup)
# ----------------------------------------------------------------------------------------------------

def test_setup_keeps_pair_count():
    print("test_setup_keeps_pair_count")
    e = start("off")
    stok = token(e, C, "staff", STAFF_PW)
    ssec, _ = enroll(e, C, stok)
    bad = [api(e, C, "POST", "/api/mfa/disable", {"password": STAFF_PW, "code": wrong_code(e, ssec)}, stok) for _ in range(4)]
    check("disable 틀린 번호 4번 → 400", all(g.status == 400 for g in bad), bad)
    api(e, C, "POST", "/api/mfa/setup", {"password": STAFF_PW}, stok)
    g = api(e, C, "POST", "/api/mfa/disable", {"password": STAFF_PW, "code": wrong_code(e, ssec)}, stok)
    check("  setup(비밀번호) 뒤 틀린 번호 1번 더 → 400", g.status == 400, g)
    g = api(e, C, "POST", "/api/mfa/disable", {"password": STAFF_PW, "code": code_now(e, ssec)}, stok)
    check("  쌍 잠금이 걸렸다 - 맞는 번호도 429", g.status == 429 and g.code == "auth/too-many-requests", g)
    check("  locked 한 줄 (staff, 주소 C)", count(hist(e), "locked", "staff", C) == 1, repr([r["result"] for r in hist(e)]))
    check("  2단계는 그대로 켜짐", e.ui.accounts.mfa_info("staff")["enabled"] is True)


def test_setup_needs_code_when_on():
    print("test_setup_needs_code_when_on")
    e = start()
    boss = token(e, A)
    secret, rec = enroll(e, A, boss)
    g = api(e, A, "POST", "/api/mfa/setup", {"password": BOSS_PW}, boss)
    check("켜진 계정 setup 비밀번호만 → 400 auth/invalid-code", g.status == 400 and g.code == "auth/invalid-code", g)
    g = api(e, A, "POST", "/api/mfa/setup", {}, boss)
    check("  아무것도 없이 → 403 auth/wrong-password", g.status == 403 and g.code == "auth/wrong-password", g)
    g = api(e, A, "POST", "/api/mfa/setup", {"password": "wrong-pass-01", "code": code_now(e, secret)}, boss)
    check("  틀린 비밀번호 + 맞는 번호 → 403 auth/wrong-password", g.status == 403 and g.code == "auth/wrong-password", g)
    g = api(e, A, "POST", "/api/mfa/setup", {"password": BOSS_PW, "code": wrong_code(e, secret)}, boss)
    check("  비밀번호 + 틀린 번호 → 400 auth/invalid-code", g.status == 400 and g.code == "auth/invalid-code", g)
    g = api(e, A, "POST", "/api/mfa/setup", {"password": BOSS_PW, "code": code_now(e, secret), "recovery": rec[0]}, boss)
    check("  번호와 복구 번호 둘 다 → 400 invalid-argument", g.status == 400 and g.code == "invalid-argument", g)
    g = api(e, A, "POST", "/api/mfa/setup", {"password": BOSS_PW, "code": code_now(e, secret)}, boss)
    check("  비밀번호 + 지금 번호 → 200 새 비밀 값", g.status == 200 and len((g.json() or {}).get("secret") or "") == 32, g)
    e.clock.go(totp.STEP)
    g = api(e, A, "POST", "/api/mfa/setup", {"password": BOSS_PW, "recovery": rec[0]}, boss)
    j = g.json() or {}
    check("  비밀번호 + 복구 번호 → 200 새 비밀 값·recoveryLeft 7", g.status == 200 and len(j.get("secret") or "") == 32
          and j.get("recoveryLeft") == 7, g)
    check("  남은 복구 번호가 하나 줄었다 (7)", e.ui.accounts.mfa_info("boss")["recovery_left"] == 7)
    g = api(e, A, "POST", "/api/mfa/setup", {"password": BOSS_PW, "recovery": rec[0]}, boss)
    check("  쓴 복구 번호 다시 → 400 auth/invalid-code", g.status == 400 and g.code == "auth/invalid-code", g)
    g = api(e, A, "POST", "/api/mfa/setup", {"password": BOSS_PW, "recovery": rec[1]}, boss)
    new = (g.json() or {}).get("secret") or "A" * 32
    g = api(e, A, "POST", "/api/mfa/enable", {"code": totp.code_at(new, totp.step_of(e.clock()))}, boss)
    check("  새 비밀 값으로 enable → 200 복구 번호 8개 (다시 등록 끝)", g.status == 200 and len((g.json() or {}).get("recovery") or []) == 8, g)
    check("  기록에 비밀번호·복구 번호 없음", BOSS_PW not in log_text(e) and not any(x in log_text(e) for x in rec))


# ----------------------------------------------------------------------------------------------------
# 6. 이미 쓴 칸의 번호
# ----------------------------------------------------------------------------------------------------

def _lock_state(e):
    return copy.deepcopy((e.ui.lockout._items, e.ui.addr_lock._items, e.ui.id_lock._items,
                          getattr(e.ui, "_mfa_fails", {})))


def test_code_used():
    print("test_code_used")
    e = start()
    boss = token(e, A)
    secret, _ = enroll(e, A, boss)
    c = code_now(e, secret)
    g = code_login(e, A, ticket(e, A), c)
    tok = (g.json() or {}).get("token")
    check("번호로 로그인 200", g.status == 200 and tok, g)
    t2 = ticket(e, A)
    n, state = len(hist(e)), _lock_state(e)
    g = api(e, A, "POST", "/api/security", {"totpScope": "off", "password": BOSS_PW, "code": c}, tok)
    check("같은 30초 안에 그 번호로 보안 범위 줄이기 → 400 auth/code-used", g.status == 400 and g.code == "auth/code-used"
          and "방금 쓴 번호" in msg(g), g)
    check("  범위 그대로 admin", e.ui.security.get()["totp_scope"] == "admin")
    g = code_login(e, A, t2, c)
    check("  새 표에 같은 번호 → 400 auth/code-used", g.status == 400 and g.code == "auth/code-used", g)
    g = api(e, A, "POST", "/api/mfa/setup", {"password": BOSS_PW, "code": c}, tok)
    check("  다시 등록(setup)에 같은 번호 → 400 auth/code-used", g.status == 400 and g.code == "auth/code-used", g)
    check("  잠금 셈 변화 없음", _lock_state(e) == state, repr(_lock_state(e)))
    check("  이력 줄 변화 없음", len(hist(e)) == n, repr(hist(e)[n:]))
    e.clock.go(totp.STEP)
    g = code_login(e, A, t2, code_now(e, secret))
    check("  표는 남아 있다 - 다음 번호로 200", g.status == 200 and (g.json() or {}).get("token"), g)


# ----------------------------------------------------------------------------------------------------
# 7. 계정의 mfa 칸 꼴이 틀릴 때
# ----------------------------------------------------------------------------------------------------

def test_mfa_broken():
    print("test_mfa_broken")
    e = start()
    e.ui.accounts.set("boss2", "boss2-pw-0001", "admin")
    b2 = token(e, D, "boss2", "boss2-pw-0001")
    enroll(e, D, b2)
    enroll(e, A, token(e, A))
    corrupt_mfa(e, "boss", lambda rec: rec["mfa"].update(last_step="x"))
    r = login(e, A)
    check("mfa.last_step 이 글 → 비밀번호 단계 403 auth/mfa-broken", r.status == 403 and r.code == "auth/mfa-broken"
          and "손상" in msg(r) and "관리자" in msg(r), r)
    check("  세션·표 없음", "token" not in (r.json() or {}) and "ticket" not in (r.json() or {}), r)
    check("  서버 기록에 한 줄 (아이디=boss)", any("2단계 인증 정보" in ln and "아이디=boss" in ln for ln in log_text(e).splitlines()),
          log_text(e)[-400:])
    g = api(e, D, "POST", "/api/accounts/boss", {"mfaReset": True}, b2)
    check("관리자 mfaReset → 200", g.status == 200, g)
    r = login(e, A)
    j = r.json() or {}
    check("  풀린 뒤 로그인 200 - mustEnroll 참", r.status == 200 and j.get("token") and (j.get("session") or {}).get("mustEnroll") is True, r)
    corrupt_mfa(e, "staff", lambda rec: rec.__setitem__("mfa", None))
    r = login(e, C, "staff", STAFF_PW)
    check("mfa 칸이 null 이어도 403 auth/mfa-broken", r.status == 403 and r.code == "auth/mfa-broken", r)
    r = login(e, C, "staff", "wrong-pass-01")
    check("  비밀번호가 틀리면 그냥 401 (손상 여부를 알려 주지 않음)", r.status == 401 and r.code == "auth/invalid-credential", r)

    # 단독 - 영향 없음
    folder = tempfile.mkdtemp(dir=m.TMP)
    store = local_server.Store(os.path.join(folder, "store.json"), volatile=local_server.VOLATILE)
    runs = local_server.Runs(":memory:")
    m.RUNS.append(runs)
    keys = local_server.ensure_keys(folder)
    web = local_web.Web(store, runs, dict(m.LIC, pc_id="p1"), folder, None)
    web.accounts.set("boss", BOSS_PW, "admin")
    path = os.path.join(folder, "accounts.json")
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    raw["accounts"]["boss"]["mfa"] = {"secret": "x", "last_step": "x"}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(raw, f)
    web.accounts._stamp = None
    srv = local_server.make_server(store, runs, dict(m.LIC, pc_id="p1"), keys, port=0, folder=folder, web=web)
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    m.SERVERS.append(srv)
    c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=15)
    try:
        c.request("POST", "/api/login", body=json.dumps({"id": "boss", "password": BOSS_PW}).encode("utf-8"),
                  headers={"Content-Type": "application/json"})
        resp = c.getresponse()
        r = m.Got(resp.status, resp.read().decode("utf-8", "replace"))
    finally:
        c.close()
    check("단독은 그대로 - 200·응답 키 token·session (failedSince 없음)", r.status == 200 and set(r.json() or {}) == {"token", "session"}, r)


TESTS = [test_broken_logins_db, test_mfa_fail_limit, test_failed_since, test_timeout_at, test_setup_keeps_pair_count,
         test_setup_needs_code_when_on, test_code_used, test_mfa_broken]

if __name__ == "__main__":
    try:
        for fn in TESTS:
            try:
                fn()
            except Exception as ex:          # 한 시험이 터져도 나머지는 돈다
                check(f"{fn.__name__} 가 예외 없이 끝난다", False, f"{type(ex).__name__}: {ex}")
    finally:
        for s in m.SERVERS:
            try:
                s.shutdown()
                s.server_close()
            except Exception:
                pass
        for r in m.RUNS:
            r.close()
        for w in m.WEBS:                     # logins.db 를 닫아야 윈도우에서 임시 폴더가 지워진다
            log = getattr(w, "login_log", None)
            if log is not None:
                log.close()
        shutil.rmtree(m.TMP, ignore_errors=True)
    print(f"\n실패: {len(m.fails)}" + (" (" + ", ".join(m.fails) + ")" if m.fails else ""))
    sys.exit(1 if m.fails else 0)
