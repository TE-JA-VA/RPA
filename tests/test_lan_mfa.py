# -*- coding: utf-8 -*-
"""사내 서버 ③ - 웹 2단계 인증 (계획 2026-11-25-lan-3-web-auth Task 3·4, 설계 6.6 '2단계 인증').
비밀번호 뒤 5분 표 → 번호(앞뒤 한 칸, 쓴 칸 거절, 틀리면 잠금 셋에 셈)·복구 번호, 범위에 든 계정은 등록 전 다른 창구 거절
(비밀번호 변경 다음), 관리자가 풀어 주기, 서버 시각 창구, '보안' 설정 창구. 단독은 그대로.
make_lan_servers 로 웹 포트를 127.0.0.1 평문(web_plain, 믿을 프록시 127.0.0.1)으로 띄우고, 보낸 쪽 주소는 X-Forwarded-For 로
바꾼다 (test_lan_review2 와 같은 방식). 번호는 Web 에 넘긴 손 시계로 totp.code_at(비밀 값, step_of(clock())) 를 만든다.
윈도우·리눅스(WSL) 둘 다 같은 파일로 돈다.
    D:/AX/RPA/.venv/Scripts/python.exe tests/test_lan_mfa.py
    wsl.exe -d Ubuntu -e python3 /mnt/d/AX/RPA_StandAlone/tests/test_lan_mfa.py
"""
import dataclasses
import http.client
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import types

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "firebase", "agent"))
import lan_ca  # noqa: E402
import lan_config  # noqa: E402
import local_server  # noqa: E402
import local_web  # noqa: E402
import pc_registry  # noqa: E402
import lan_server  # noqa: E402
import totp  # noqa: E402

fails = []
TMP = tempfile.mkdtemp(prefix="rpa_lan_mfa_")
LIC = {"edition": "standalone", "company": "시험상사", "cid": "c1", "pc_id": "srv", "issued": "2026-11-25",
       "modules": {}, "features": {}, "limits": {}}
BOSS_PW, STAFF_PW = "pw-12345678", "staff-pw-0001"
GUIDS = ["11111111-2222-3333-4444-5555555555%02d" % i for i in range(10)]
A, B, C, D = "10.0.0.5", "10.0.0.6", "10.0.0.7", "10.0.0.8"


def check(name, ok, detail=""):
    print(f"  [{'통과' if ok else '실패'}] {name}" + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


# --- 인증서 (에이전트 포트는 늘 TLS) ---
CA_DIR, OUT = os.path.join(TMP, "ca"), os.path.join(TMP, "srv")
lan_ca.make_ca(CA_DIR, ["localhost"], ["127.0.0.1"])
CERT, KEY = lan_ca.issue_server(CA_DIR, OUT, ["localhost"], ["127.0.0.1"])
CA_PEM = lan_ca.ca_pem(CA_DIR)


class Got:
    def __init__(self, status, raw):
        self.status, self.raw = status, raw

    def json(self):
        try:
            return json.loads(self.raw) if self.raw else None
        except ValueError:
            return None

    @property
    def code(self):
        v = self.json()
        return v.get("code") if isinstance(v, dict) else None

    def __repr__(self):
        return f"<{self.status} {self.raw[:300]!r}>"


class Clock:
    def __init__(self):
        self.t = time.time()

    def __call__(self):
        return self.t

    def go(self, sec):
        self.t += sec


SERVERS, RUNS = [], []
CFG = {"listen": "127.0.0.1", "names": ["localhost"], "allow": ["127.0.0.0/8", "10.0.0.0/8"],
       "trusted_proxies": ["127.0.0.1"], "web_plain": True, "public_web": ["ap.corp.local"]}


def write_security(folder, scope, show=True):
    with open(os.path.join(folder, "security.json"), "w", encoding="utf-8") as f:
        json.dump({"version": 1, "totp_scope": scope, "show_own_history": show}, f)


def start(scope=None):
    """사내 서버 (웹은 평문 프록시 모양). scope 를 주면 security.json 을 먼저 쓴다 (없으면 기본 = 관리자만 필수)."""
    folder = tempfile.mkdtemp(dir=TMP)
    if scope is not None:
        write_security(folder, scope)
    store = local_server.Store(os.path.join(folder, "store.json"), volatile=local_server.VOLATILE)
    runs = local_server.Runs(":memory:")
    RUNS.append(runs)
    reg = pc_registry.Registry(os.path.join(folder, "pcs.json"), seats=20)
    clock = Clock()
    web = local_web.Web(store, runs, LIC, folder, None, clock=clock, registry=reg)
    web.accounts.set("boss", BOSS_PW, "admin")
    web.accounts.set("staff", STAFF_PW, "viewer")
    cfg = dataclasses.replace(lan_config.parse(CFG), web_port=0, agent_port=0)
    w, a = lan_server.make_lan_servers(store, runs, LIC, reg, web, cfg, CERT, KEY, CA_PEM)
    for s in (w, a):
        threading.Thread(target=s.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        SERVERS.append(s)
    st = reg.start("PC")
    rand = os.urandom(32).hex()
    reg.enroll(st["pc_id"], rand, GUIDS[0], "PC-A", pc_registry.enroll_proof(st["token"], st["pc_id"], rand, GUIDS[0], "PC-A"))
    return types.SimpleNamespace(wp=w.server_address[1], ui=web, folder=folder, clock=clock, pc=st["pc_id"], reg=reg)


def api(env, ip, method, path, body=None, tok=None):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    hs = {"X-Forwarded-Proto": "https", "X-Forwarded-For": ip}
    if data is not None:
        hs["Content-Type"] = "application/json"
    if tok:
        hs["Authorization"] = "Bearer " + tok
    c = http.client.HTTPConnection("127.0.0.1", env.wp, timeout=15)
    try:
        c.request(method, path, body=data, headers=hs)
        r = c.getresponse()
        return Got(r.status, r.read().decode("utf-8", "replace"))
    finally:
        c.close()


def login(env, ip, uid="boss", pw=BOSS_PW):
    return api(env, ip, "POST", "/api/login", {"id": uid, "password": pw})


def token(env, ip, uid="boss", pw=BOSS_PW):
    r = login(env, ip, uid, pw)
    return (r.json() or {}).get("token")


def code_now(env, secret, shift=0):
    return totp.code_at(secret, totp.step_of(env.clock()) + shift)


def wrong_code(env, secret):
    good = {code_now(env, secret, d) for d in (-1, 0, 1)}
    n = 0
    while f"{n:06d}" in good:
        n += 1
    return f"{n:06d}"


def enroll(env, ip, tok):
    """그 세션으로 2단계 등록 → (비밀 값, 복구 번호 목록). 쓴 칸을 넘기려 시계를 한 칸 민다."""
    s = api(env, ip, "POST", "/api/mfa/setup", {}, tok).json() or {}
    secret = s.get("secret")
    r = api(env, ip, "POST", "/api/mfa/enable", {"code": code_now(env, secret)}, tok)
    env.clock.go(totp.STEP)
    return secret, (r.json() or {}).get("recovery")


def mfa_login(env, ip, uid, pw, secret):
    """두 단계 로그인 → 세션 토큰 (쓴 칸을 넘기려 시계를 한 칸 민다)."""
    t = (login(env, ip, uid, pw).json() or {}).get("ticket")
    r = api(env, ip, "POST", "/api/login/mfa", {"ticket": t, "code": code_now(env, secret)})
    env.clock.go(totp.STEP)
    return (r.json() or {}).get("token")


def runs_of(env, ip, tok):
    return api(env, ip, "GET", f"/api/runs?pcId={env.pc}", tok=tok)


def log_text(env):
    try:
        with open(os.path.join(env.folder, local_server.LOG_NAME), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


# ----------------------------------------------------------------------------------------------------
# Task 3
# ----------------------------------------------------------------------------------------------------

def test_enroll_flow():
    print("test_enroll_flow")
    e = start()
    check("security.json 이 없으면 기본 범위(관리자만)", not os.path.exists(os.path.join(e.folder, "security.json")))
    r = login(e, A)
    s = (r.json() or {}).get("session") or {}
    tok = (r.json() or {}).get("token")
    check("관리자 로그인 200 - 세션 mustEnroll 참·mfa 거짓", r.status == 200 and s.get("mustEnroll") is True and s.get("mfa") is False, r)
    g = runs_of(e, A, tok)
    check("등록 전 /api/runs → 403 auth/must-enroll-mfa", g.status == 403 and g.code == "auth/must-enroll-mfa", g)
    g = api(e, A, "GET", "/api/accounts", tok=tok)
    check("등록 전 /api/accounts → 403 auth/must-enroll-mfa", g.status == 403 and g.code == "auth/must-enroll-mfa", g)
    g = api(e, A, "GET", "/api/session", tok=tok)
    check("등록 전 /api/session → 200", g.status == 200 and (g.json() or {}).get("session", {}).get("mustEnroll") is True, g)
    g = api(e, A, "GET", "/api/server-time")
    check("/api/server-time 로그인 없이 → nowMs (손 시계)",
          g.status == 200 and abs((g.json() or {}).get("nowMs", 0) - int(e.clock() * 1000)) <= 1, g)
    g = api(e, A, "POST", "/api/mfa/enable", {"code": "123456"}, tok)
    check("setup 전 enable → 409 failed-precondition", g.status == 409 and g.code == "failed-precondition", g)
    g = api(e, A, "POST", "/api/mfa/setup", {}, tok)
    sec = (g.json() or {}).get("secret") or ""
    uri = (g.json() or {}).get("uri") or ""
    check("setup → secret(32자)·uri", g.status == 200 and len(sec) == 32 and uri.startswith("otpauth://totp/")
          and f"secret={sec}" in uri, g)
    tok2 = token(e, A)
    g = api(e, A, "POST", "/api/mfa/enable", {"code": wrong_code(e, sec)}, tok)
    check("틀린 번호 → 400 auth/invalid-code", g.status == 400 and g.code == "auth/invalid-code", g)
    g = api(e, A, "POST", "/api/mfa/enable", {"code": code_now(e, sec)}, tok)
    rec = (g.json() or {}).get("recovery") or []
    s = (g.json() or {}).get("session") or {}
    check("맞는 번호 → 복구 번호 8개·세션 mfa 참·mustEnroll 거짓",
          g.status == 200 and len(rec) == 8 and len(set(rec)) == 8 and s.get("mfa") is True and s.get("mustEnroll") is False, g)
    check("등록한 뒤 /api/runs → 200", runs_of(e, A, tok).status == 200)
    check("같은 계정의 다른 세션은 닫힌다 (401)", api(e, A, "GET", "/api/session", tok=tok2).status == 401)
    text = log_text(e)
    check("기록에 2단계 켬 줄", "웹 2단계 켬" in text and "아이디=boss" in text, text[-500:])
    check("기록에 비밀 값·복구 번호 없음", sec not in text and not any(c in text for c in rec))
    st = login(e, A, "staff", STAFF_PW)
    stok = (st.json() or {}).get("token")
    check("유저(viewer)는 등록 없이 mustEnroll 거짓", ((st.json() or {}).get("session") or {}).get("mustEnroll") is False, st)
    check("유저 /api/runs → 200", runs_of(e, A, stok).status == 200)


def test_must_change_first():
    print("test_must_change_first")
    e = start()
    e.ui.accounts.set("newadm", "newadm-pw-001", "admin", must_change=True)
    tok = token(e, A, "newadm", "newadm-pw-001")
    g = api(e, A, "POST", "/api/mfa/setup", {}, tok)
    check("비밀번호를 바꿔야 하는 관리자의 setup → 403 auth/must-change", g.status == 403 and g.code == "auth/must-change", g)
    g = runs_of(e, A, tok)
    check("  /api/runs 도 must-change 가 먼저", g.status == 403 and g.code == "auth/must-change", g)
    g = api(e, A, "POST", "/api/password", {"current": "newadm-pw-001", "next": "newadm-pw-002"}, tok)
    check("비밀번호 변경 → 200 (등록 전이어도 비밀번호 창구는 열림)", g.status == 200, g)
    g = runs_of(e, A, tok)
    check("바꾼 뒤 /api/runs → 403 must-enroll-mfa", g.status == 403 and g.code == "auth/must-enroll-mfa", g)
    g = api(e, A, "POST", "/api/mfa/setup", {}, tok)
    check("바꾼 뒤 setup → 200", g.status == 200 and (g.json() or {}).get("secret"), g)


def test_two_step_login():
    print("test_two_step_login")
    e = start()
    secret, rec = enroll(e, A, token(e, A))
    check("등록 (복구 번호 8개)", secret and rec and len(rec) == 8, repr(rec))
    r = login(e, A)
    j = r.json() or {}
    check("켜진 계정 로그인 → mfa·ticket·ttl 300, token 없음",
          r.status == 200 and j.get("mfa") is True and j.get("ttl") == 300 and isinstance(j.get("ticket"), str)
          and "token" not in j and "session" not in j, r)
    c = code_now(e, secret)
    g = api(e, A, "POST", "/api/login/mfa", {"ticket": j.get("ticket"), "code": c})
    gj = g.json() or {}
    check("번호 → 세션 (token·session)", g.status == 200 and gj.get("token") and gj.get("session", {}).get("mfa") is True, g)
    check("  세션 토큰으로 /api/runs 200", runs_of(e, A, gj.get("token")).status == 200)
    t2 = (login(e, A).json() or {}).get("ticket")
    g = api(e, A, "POST", "/api/login/mfa", {"ticket": t2, "code": c})
    check("같은 번호로 새 표 → 401 auth/invalid-code (쓴 칸)", g.status == 401 and g.code == "auth/invalid-code", g)
    g = api(e, A, "POST", "/api/login/mfa", {"ticket": t2, "recovery": rec[0].upper().replace("-", "")})
    gj = g.json() or {}
    check("복구 번호 (같은 표 - 틀린 번호 뒤에도 표는 남음) → 세션·recoveryLeft 7",
          g.status == 200 and gj.get("token") and gj.get("recoveryLeft") == 7, g)
    t3 = (login(e, A).json() or {}).get("ticket")
    g = api(e, A, "POST", "/api/login/mfa", {"ticket": t3, "recovery": rec[0]})
    check("쓴 복구 번호 다시 → 401 auth/invalid-code", g.status == 401 and g.code == "auth/invalid-code", g)
    g = api(e, A, "POST", "/api/login/mfa", {"ticket": t3})
    check("번호·복구 번호 없음 → 400", g.status == 400, g)
    g = api(e, A, "POST", "/api/login/mfa", {"ticket": t3, "code": "1", "recovery": "x"})
    check("둘 다 → 400", g.status == 400, g)
    text = log_text(e)
    check("기록에 표·복구 번호 없음", t2 not in text and t3 not in text and not any(x in text for x in rec))


def test_ticket_rules():
    print("test_ticket_rules")
    e = start()
    secret, _ = enroll(e, A, token(e, A))
    t = (login(e, A).json() or {}).get("ticket")
    g = api(e, B, "POST", "/api/login/mfa", {"ticket": t, "code": code_now(e, secret)})
    check("다른 주소에서 쓴 표 → 401 auth/ticket-expired", g.status == 401 and g.code == "auth/ticket-expired", g)
    g = api(e, A, "POST", "/api/login/mfa", {"ticket": t, "code": code_now(e, secret)})
    check("  그 표는 지워졌다 (원래 주소에서도 401 ticket-expired)", g.status == 401 and g.code == "auth/ticket-expired", g)
    t = (login(e, A).json() or {}).get("ticket")
    e.clock.go(301)
    g = api(e, A, "POST", "/api/login/mfa", {"ticket": t, "code": code_now(e, secret)})
    check("301초 뒤 → 401 ticket-expired", g.status == 401 and g.code == "auth/ticket-expired", g)
    t = (login(e, A).json() or {}).get("ticket")
    g = api(e, A, "POST", "/api/login/mfa", {"ticket": t, "code": code_now(e, secret)})
    boss = (g.json() or {}).get("token")
    check("새 표 → 200", g.status == 200 and boss, g)
    e.clock.go(totp.STEP)
    g = api(e, A, "POST", "/api/login/mfa", {"ticket": t, "code": code_now(e, secret)})
    check("쓴 표 다시 → 401 ticket-expired", g.status == 401 and g.code == "auth/ticket-expired", g)
    g = api(e, A, "POST", "/api/login/mfa", {"ticket": "x" * 43, "code": code_now(e, secret)})
    check("없는 표 → 401 ticket-expired", g.status == 401 and g.code == "auth/ticket-expired", g)
    # 유저도 2단계를 켠 뒤 - 표를 받은 다음 관리자가 비밀번호를 다시 정하면 그 표는 끝
    ssec, _ = enroll(e, C, token(e, C, "staff", STAFF_PW))
    t = (login(e, C, "staff", STAFF_PW).json() or {}).get("ticket")
    g = api(e, A, "POST", "/api/accounts/staff", {"password": "staff-pw-0002"}, boss)
    check("관리자가 유저 비밀번호를 다시 정함 → 200", g.status == 200, g)
    g = api(e, C, "POST", "/api/login/mfa", {"ticket": t, "code": code_now(e, ssec)})
    check("비밀번호가 바뀐 계정의 표 → 401 ticket-expired", g.status == 401 and g.code == "auth/ticket-expired", g)
    t = (login(e, C, "staff", "staff-pw-0002").json() or {}).get("ticket")
    g = api(e, A, "POST", "/api/accounts/staff", {"disabled": True}, boss)
    check("관리자가 유저를 사용 중지 → 200", g.status == 200, g)
    g = api(e, C, "POST", "/api/login/mfa", {"ticket": t, "code": code_now(e, ssec)})
    check("중지된 계정의 표 → 401 ticket-expired", g.status == 401 and g.code == "auth/ticket-expired", g)


def test_code_lockout():
    print("test_code_lockout")
    e = start()
    secret, _ = enroll(e, A, token(e, A))
    t = (login(e, A).json() or {}).get("ticket")
    bad = [api(e, A, "POST", "/api/login/mfa", {"ticket": t, "code": wrong_code(e, secret)}) for _ in range(5)]
    check("틀린 번호 5번 → 모두 401 invalid-code", all(g.status == 401 and g.code == "auth/invalid-code" for g in bad), bad)
    g = api(e, A, "POST", "/api/login/mfa", {"ticket": t, "code": code_now(e, secret)})
    check("다음은 맞는 번호도 429 (아이디 잠금 쌍)", g.status == 429 and g.code == "auth/too-many-requests", g)
    g = login(e, A)
    check("  같은 주소의 비밀번호 로그인도 429", g.status == 429, g)
    g = login(e, B)
    check("  다른 주소의 같은 아이디는 잠기지 않음", g.status == 200 and (g.json() or {}).get("ticket"), g)
    for _ in range(4):
        login(e, A, "ghost", "wrong-password-1")
    g = login(e, A, "staff", STAFF_PW)
    check("번호 5 + 비밀번호 4 = 9번 틀린 주소 - 아직 막히지 않음", g.status == 200, g)
    login(e, A, "ghost", "wrong-password-1")
    g = login(e, A, "staff", STAFF_PW)
    check("10번째 실패 뒤 다른 아이디의 비밀번호 로그인도 429 (주소 잠금에 번호 실패가 들어감)",
          g.status == 429 and g.code == "auth/too-many-requests", g)
    check("  다른 주소는 됨", login(e, C, "staff", STAFF_PW).status == 200)


def test_same_code_race():
    print("test_same_code_race")
    e = start()
    secret, _ = enroll(e, A, token(e, A))
    t1 = (login(e, A).json() or {}).get("ticket")
    t2 = (login(e, A).json() or {}).get("ticket")
    c = code_now(e, secret)
    out = {}
    gate = threading.Barrier(2)

    def go(name, t):
        gate.wait()
        out[name] = api(e, A, "POST", "/api/login/mfa", {"ticket": t, "code": c})

    th = [threading.Thread(target=go, args=(n, t)) for n, t in (("a", t1), ("b", t2))]
    for x in th:
        x.start()
    for x in th:
        x.join(20)
    got = sorted(g.status for g in out.values())
    check("같은 번호 두 탭 동시에 → 200 하나·401 하나", got == [200, 401], repr(out))
    check("  401 은 invalid-code", [g.code for g in out.values() if g.status == 401] == ["auth/invalid-code"], repr(out))


def test_admin_reset_and_disable():
    print("test_admin_reset_and_disable")
    e = start()
    e.ui.accounts.set("boss2", "boss2-pw-0001", "admin")
    boss = token(e, A)
    enroll(e, A, boss)
    b2 = token(e, D, "boss2", "boss2-pw-0001")
    enroll(e, D, b2)
    check("boss2 2단계 켜짐", e.ui.accounts.mfa_info("boss2")["enabled"] is True)
    g = api(e, A, "POST", "/api/accounts/boss2", {"mfaReset": True}, boss)
    check("관리자 A 가 B 의 mfaReset → 200", g.status == 200, g)
    check("  B 의 2단계가 풀림", e.ui.accounts.mfa_info("boss2")["enabled"] is False)
    check("  B 의 세션은 닫힘 (401)", api(e, D, "GET", "/api/session", tok=b2).status == 401)
    r = login(e, D, "boss2", "boss2-pw-0001")
    j = r.json() or {}
    check("  B 다시 로그인 → 표 없이 세션, mustEnroll 참", r.status == 200 and j.get("token")
          and (j.get("session") or {}).get("mustEnroll") is True, r)
    check("  기록 '웹 계정 변경 (2단계 해제)'", "웹 계정 변경 (2단계 해제)  아이디=boss2  처리=boss" in log_text(e), log_text(e)[-400:])
    g = api(e, A, "POST", "/api/accounts/boss", {"mfaReset": True}, boss)
    check("자기 계정 mfaReset → 400", g.status == 400, g)
    g = api(e, A, "POST", "/api/accounts/boss2", {"mfaReset": "yes"}, boss)
    check("mfaReset 이 참이 아닌 값 → 400", g.status == 400, g)
    # 범위 끔 - 유저가 켠 2단계를 스스로 끈다
    write_security(e.folder, "off")
    stok = token(e, C, "staff", STAFF_PW)
    ssec, _ = enroll(e, C, stok)
    check("유저 2단계 켬", e.ui.accounts.mfa_info("staff")["enabled"] is True)
    g = api(e, C, "POST", "/api/mfa/disable", {"password": "wrong-pass-01", "code": code_now(e, ssec)}, stok)
    check("disable 틀린 비밀번호 → 403 auth/wrong-password", g.status == 403 and g.code == "auth/wrong-password", g)
    g = api(e, C, "POST", "/api/mfa/disable", {"password": STAFF_PW, "code": wrong_code(e, ssec)}, stok)
    check("disable 틀린 번호 → 400 auth/invalid-code", g.status == 400 and g.code == "auth/invalid-code", g)
    g = api(e, C, "POST", "/api/mfa/disable", {"password": STAFF_PW, "code": code_now(e, ssec)}, stok)
    check("disable 비밀번호·번호 맞음 → ok", g.status == 200 and (g.json() or {}).get("ok") is True, g)
    check("  유저 2단계 꺼짐", e.ui.accounts.mfa_info("staff")["enabled"] is False)
    # 범위 관리자만 - 관리자는 끌 수 없다
    write_security(e.folder, "admin")
    secret_boss = e.ui.accounts.mfa_secret("boss")
    g = api(e, A, "POST", "/api/mfa/disable", {"password": BOSS_PW, "code": code_now(e, secret_boss)}, boss)
    check("범위 admin 에서 관리자 disable → 409", g.status == 409, g)
    check("  관리자 2단계 그대로", e.ui.accounts.mfa_info("boss")["enabled"] is True)


def test_setup_needs_password_when_on():
    print("test_setup_needs_password_when_on")
    e = start()
    boss = token(e, A)
    enroll(e, A, boss)
    g = api(e, A, "POST", "/api/mfa/setup", {}, boss)
    check("이미 켜진 계정의 setup 비밀번호 없이 → 403 auth/wrong-password", g.status == 403 and g.code == "auth/wrong-password", g)
    g = api(e, A, "POST", "/api/mfa/setup", {"password": "wrong-pass-01"}, boss)
    check("  틀린 비밀번호 → 403 auth/wrong-password", g.status == 403 and g.code == "auth/wrong-password", g)
    g = api(e, A, "POST", "/api/mfa/setup", {"password": BOSS_PW}, boss)
    check("  맞는 비밀번호 → 200 새 비밀 값", g.status == 200 and len((g.json() or {}).get("secret") or "") == 32, g)


def test_single_unchanged():
    print("test_single_unchanged")
    folder = tempfile.mkdtemp(dir=TMP)
    store = local_server.Store(os.path.join(folder, "store.json"), volatile=local_server.VOLATILE)
    runs = local_server.Runs(":memory:")
    RUNS.append(runs)
    keys = local_server.ensure_keys(folder)
    web = local_web.Web(store, runs, dict(LIC, pc_id="p1"), folder, None)
    web.accounts.set("boss", BOSS_PW, "admin")
    srv = local_server.make_server(store, runs, dict(LIC, pc_id="p1"), keys, port=0, folder=folder, web=web)
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    SERVERS.append(srv)
    port = srv.server_address[1]

    def call(method, path, body=None, tok=None):
        data = None if body is None else json.dumps(body).encode("utf-8")
        hs = {"Content-Type": "application/json"} if data is not None else {}
        if tok:
            hs["Authorization"] = "Bearer " + tok
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
        try:
            c.request(method, path, body=data, headers=hs)
            r = c.getresponse()
            return Got(r.status, r.read().decode("utf-8", "replace"))
        finally:
            c.close()

    r = call("POST", "/api/login", {"id": "boss", "password": BOSS_PW})
    j = r.json() or {}
    check("단독 로그인 응답 키 token·session", r.status == 200 and set(j) == {"token", "session"}, r)
    check("  세션 칸이 지금과 같다 (mfa·mustEnroll 없음)",
          set(j.get("session") or {}) == {"uid", "id", "email", "cid", "role", "mustChange"}, r)
    tok = j.get("token")
    for method, path in (("POST", "/api/mfa/setup"), ("POST", "/api/mfa/enable"), ("POST", "/api/mfa/disable"),
                         ("GET", "/api/server-time"), ("POST", "/api/login/mfa"), ("GET", "/api/security"),
                         ("POST", "/api/security")):
        g = call(method, path, {} if method == "POST" else None, tok)
        check(f"단독 {method} {path} → 404", g.status == 404 and g.code == "not-found", g)
    g = call("GET", "/api/runs", tok=tok)
    check("단독 /api/runs 는 그대로 200 (등록 강제 없음)", g.status == 200, g)
    g = call("POST", "/api/accounts/boss", {"mfaReset": True}, tok)
    check("단독 mfaReset 만 → 400 (지금처럼 바꿀 내용 없음)", g.status == 400, g)
    check("자료 폴더에 security.json 없음", not os.path.exists(os.path.join(folder, "security.json")))
    check("Web.security None·lan 거짓", getattr(web, "security", "x") is None and getattr(web, "lan", None) is False)


TESTS = [test_enroll_flow, test_must_change_first, test_two_step_login, test_ticket_rules, test_code_lockout,
         test_same_code_race, test_admin_reset_and_disable, test_setup_needs_password_when_on, test_single_unchanged]

if __name__ == "__main__":
    try:
        for fn in TESTS:
            try:
                fn()
            except Exception as ex:          # 한 시험이 터져도 나머지는 돈다
                check(f"{fn.__name__} 가 예외 없이 끝난다", False, f"{type(ex).__name__}: {ex}")
    finally:
        for s in SERVERS:
            try:
                s.shutdown()
                s.server_close()
            except Exception:
                pass
        for r in RUNS:
            r.close()
        shutil.rmtree(TMP, ignore_errors=True)
    print(f"\n실패: {len(fails)}" + (" (" + ", ".join(fails) + ")" if fails else ""))
    sys.exit(1 if fails else 0)
