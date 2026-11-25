# -*- coding: utf-8 -*-
"""사내 서버 ③ - 웹 2단계 인증·로그인 이력 (계획 2026-11-25-lan-3-web-auth Task 3·4·5, 설계 6.6 '2단계 인증'·'로그인 이력').
비밀번호 뒤 5분 표 → 번호(앞뒤 한 칸, 쓴 칸 거절, 틀리면 잠금 셋에 셈)·복구 번호, 범위에 든 계정은 등록 전 다른 창구 거절
(비밀번호 변경 다음), 관리자가 풀어 주기, 서버 시각 창구, '보안' 설정 창구, 로그인 이력(남기는 일·창구·마지막 로그인·
비밀 값이 어디에도 새지 않음). 단독은 그대로.
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


SERVERS, RUNS, WEBS = [], [], []
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
    WEBS.append(web)
    return types.SimpleNamespace(wp=w.server_address[1], ui=web, folder=folder, clock=clock, pc=st["pc_id"], reg=reg)


UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 "
      "Edg/131.0.0.0")                       # 이력의 agent 칸은 'Edge · Windows' 만 (원문은 남지 않는다)
SEEN = None                                  # test_no_secret_leaks 가 [] 로 두면 받은 응답을 모두 모은다 (경로, 응답)


def api(env, ip, method, path, body=None, tok=None):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    hs = {"X-Forwarded-Proto": "https", "X-Forwarded-For": ip, "User-Agent": UA}
    if data is not None:
        hs["Content-Type"] = "application/json"
    if tok:
        hs["Authorization"] = "Bearer " + tok
    c = http.client.HTTPConnection("127.0.0.1", env.wp, timeout=15)
    try:
        c.request(method, path, body=data, headers=hs)
        r = c.getresponse()
        got = Got(r.status, r.read().decode("utf-8", "replace"))
        if SEEN is not None:
            SEEN.append((path, got))
        return got
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
    check("같은 번호로 새 표 → 400 auth/code-used (쓴 칸 - 틀린 번호로 세지 않음, ③ 전체 검토 6)",
          g.status == 400 and g.code == "auth/code-used", g)
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
    check("같은 번호 두 탭 동시에 → 200 하나·400 하나", got == [200, 400], repr(out))
    check("  400 은 code-used (쓴 칸, ③ 전체 검토 6)", [g.code for g in out.values() if g.status == 400] == ["auth/code-used"], repr(out))


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
    secret, _ = enroll(e, A, boss)
    g = api(e, A, "POST", "/api/mfa/setup", {}, boss)
    check("이미 켜진 계정의 setup 비밀번호 없이 → 403 auth/wrong-password", g.status == 403 and g.code == "auth/wrong-password", g)
    g = api(e, A, "POST", "/api/mfa/setup", {"password": "wrong-pass-01"}, boss)
    check("  틀린 비밀번호 → 403 auth/wrong-password", g.status == 403 and g.code == "auth/wrong-password", g)
    g = api(e, A, "POST", "/api/mfa/setup", {"password": BOSS_PW, "code": code_now(e, secret)}, boss)
    check("  맞는 비밀번호 + 지금 번호 → 200 새 비밀 값 (번호도 요구 - ③ 전체 검토 5, test_lan_mfa_review)",
          g.status == 200 and len((g.json() or {}).get("secret") or "") == 32, g)


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



# ----------------------------------------------------------------------------------------------------
# Task 4 - '보안' 설정 창구
# ----------------------------------------------------------------------------------------------------

def test_security_get_set():
    print("test_security_get_set")
    e = start()
    stok = token(e, C, "staff", STAFF_PW)
    g = api(e, C, "GET", "/api/security", tok=stok)
    check("유저 GET /api/security → 403", g.status == 403, g)
    g = api(e, C, "POST", "/api/security", {"totpScope": "off"}, stok)
    check("유저 POST /api/security → 403", g.status == 403, g)
    boss = token(e, A)
    g = api(e, A, "GET", "/api/security", tok=boss)
    check("등록 전 관리자도 403 must-enroll-mfa", g.status == 403 and g.code == "auth/must-enroll-mfa", g)
    secret, _ = enroll(e, A, boss)
    g = api(e, A, "GET", "/api/security", tok=boss)
    j = g.json() or {}
    check("기본 → totpScope admin·showOwnHistory 참·nowMs", g.status == 200 and j.get("totpScope") == "admin"
          and j.get("showOwnHistory") is True and abs(j.get("nowMs", 0) - int(e.clock() * 1000)) <= 1, g)
    g = api(e, A, "POST", "/api/security", {"totpScope": "all"}, boss)
    check("all 로 올리기 - 비밀번호 없이 200", g.status == 200 and (g.json() or {}).get("totpScope") == "all", g)
    g = api(e, A, "POST", "/api/security", {"totpScope": "off"}, boss)
    check("off 로 줄이기 비밀번호 없이 → 403 auth/wrong-password", g.status == 403 and g.code == "auth/wrong-password", g)
    g = api(e, A, "POST", "/api/security", {"totpScope": "off", "password": "wrong-pass-01"}, boss)
    check("  틀린 비밀번호 → 403 auth/wrong-password", g.status == 403 and g.code == "auth/wrong-password", g)
    g = api(e, A, "POST", "/api/security", {"totpScope": "off", "password": BOSS_PW}, boss)
    check("  비밀번호만 (관리자 2단계 켜짐) → 400 auth/invalid-code", g.status == 400 and g.code == "auth/invalid-code", g)
    g = api(e, A, "POST", "/api/security", {"totpScope": "off", "password": BOSS_PW, "code": wrong_code(e, secret)}, boss)
    check("  틀린 번호 → 400 auth/invalid-code", g.status == 400 and g.code == "auth/invalid-code", g)
    check("  거절된 동안 범위 그대로 all", e.ui.security.get()["totp_scope"] == "all")
    before = [ln for ln in log_text(e).splitlines() if "웹 보안 설정 변경" in ln]
    g = api(e, A, "POST", "/api/security", {"totpScope": "off", "password": BOSS_PW, "code": code_now(e, secret)}, boss)
    check("  비밀번호·번호 둘 다 맞음 → 200 off", g.status == 200 and (g.json() or {}).get("totpScope") == "off", g)
    after = [ln for ln in log_text(e).splitlines() if "웹 보안 설정 변경" in ln]
    new = after[len(before):]
    check("  기록 줄 하나 (범위 all→off·처리·주소)", len(new) == 1 and "2단계 범위=all→off" in new[0] and "유저 이력 보이기=" in new[0]
          and "처리=boss" in new[0] and f"주소={A}" in new[0], repr(new))
    check("  비밀번호·번호는 기록에 없음", BOSS_PW not in log_text(e) and code_now(e, secret) not in "\n".join(new))
    g = api(e, A, "POST", "/api/security", {"totpScope": "some"}, boss)
    check("틀린 값 some → 400", g.status == 400, g)
    g = api(e, A, "POST", "/api/security", {"showOwnHistory": "no"}, boss)
    check("showOwnHistory 참·거짓 아님 → 400", g.status == 400, g)
    g = api(e, A, "POST", "/api/security", {}, boss)
    check("바꿀 것 없음 → 400", g.status == 400, g)
    g = api(e, A, "POST", "/api/security", {"showOwnHistory": False}, boss)
    check("showOwnHistory 끄기는 줄이는 변경이 아님 - 비밀번호 없이 200",
          g.status == 200 and (g.json() or {}).get("showOwnHistory") is False, g)
    with open(os.path.join(e.folder, "security.json"), encoding="utf-8") as f:
        saved = json.load(f)
    check("security.json = version 1·off·false", saved == {"version": 1, "totp_scope": "off", "show_own_history": False}, repr(saved))
    g = api(e, A, "POST", "/api/security", {"totpScope": "admin"}, boss)
    check("다시 admin 으로 올리기 → 200", g.status == 200 and (g.json() or {}).get("totpScope") == "admin", g)
    e.ui.accounts.set("boss3", "boss3-pw-0001", "admin")
    b3 = token(e, D, "boss3", "boss3-pw-0001")
    g = api(e, D, "POST", "/api/security", {"totpScope": "off", "password": "boss3-pw-0001"}, b3)
    check("등록 전 관리자는 범위를 못 바꾼다 (403 must-enroll-mfa)", g.status == 403 and g.code == "auth/must-enroll-mfa", g)


def test_scope_raise_live_session():
    print("test_scope_raise_live_session")
    e = start()
    boss = token(e, A)
    enroll(e, A, boss)
    stok = token(e, C, "staff", STAFF_PW)
    check("범위 admin - 유저는 등록 없이 /api/runs 200", runs_of(e, C, stok).status == 200)
    g = api(e, A, "POST", "/api/security", {"totpScope": "all"}, boss)
    check("관리자가 all 로 올림 → 200", g.status == 200, g)
    g = runs_of(e, C, stok)
    check("같은 유저 세션의 다음 /api/runs → 403 must-enroll-mfa", g.status == 403 and g.code == "auth/must-enroll-mfa", g)
    g = api(e, C, "GET", "/api/session", tok=stok)
    check("  /api/session 200·mustEnroll 참", g.status == 200 and (g.json() or {}).get("session", {}).get("mustEnroll") is True, g)
    check("  관리자(등록함)는 그대로 /api/runs 200", runs_of(e, A, boss).status == 200)


# ----------------------------------------------------------------------------------------------------
# Task 5 - 로그인 이력
# ----------------------------------------------------------------------------------------------------

KIND = "Edge · Windows"


def hist(env):
    """이력 전체 - 오래된 것부터."""
    return list(reversed(env.ui.login_log.query(limit=200)))


def count(rows, result, uid="*", ip="*"):
    return sum(1 for r in rows if r["result"] == result and (uid == "*" or r["uid"] == uid) and (ip == "*" or r["ip"] == ip))


def test_history_events():
    print("test_history_events")
    e = start()
    check("사내 서버는 logins.db 를 만든다", os.path.isfile(os.path.join(e.folder, "logins.db")))
    boss = token(e, A)                                                  # ok boss A
    secret, rec = enroll(e, A, boss)                                    # mfa_on boss A
    login(e, B, "staff", "wrong-pass-01")                               # bad_password staff B
    login(e, B, "ghost", "wrong-pass-01")                               # bad_password None B (없는 아이디)
    for _ in range(5):
        login(e, C, "staff", "wrong-pass-01")                           # bad_password staff C ×5, 다섯 번째에 locked staff C
    n = len(hist(e))
    rej = [login(e, C, "staff", STAFF_PW) for _ in range(3)]
    check("잠긴 동안 거절 3번 (429)", all(g.status == 429 for g in rej), rej)
    check("  잠긴 동안의 거절은 줄이 늘지 않음", len(hist(e)) == n, repr(hist(e)[n:]))
    e.ui.accounts.set("gone", "gone-pw-0001", "viewer")
    e.ui.accounts.disable("gone", True)
    g = login(e, D, "gone", "gone-pw-0001")                             # disabled gone D
    check("중지 계정 로그인 → 403", g.status == 403, g)
    stok = token(e, D, "staff", STAFF_PW)                               # ok staff D
    ssec, _ = enroll(e, D, stok)                                        # mfa_on staff D
    g = api(e, D, "POST", "/api/mfa/disable", {"password": STAFF_PW, "code": code_now(e, ssec)}, stok)    # mfa_off staff D
    check("유저 2단계 끔 → 200", g.status == 200, g)
    e.clock.go(totp.STEP)
    ssec, _ = enroll(e, D, stok)                                        # mfa_on staff D (두 번째)
    g = api(e, A, "POST", "/api/accounts/staff", {"mfaReset": True}, boss)    # mfa_reset staff (처리한 관리자의 주소 A)
    check("관리자가 유저 2단계 풂 → 200", g.status == 200, g)
    t = (login(e, A).json() or {}).get("ticket")
    g = api(e, A, "POST", "/api/login/mfa", {"ticket": t, "code": wrong_code(e, secret)})    # bad_code boss A
    check("틀린 번호 → 401", g.status == 401, g)
    g = api(e, A, "POST", "/api/login/mfa", {"ticket": t, "recovery": rec[0]})              # recovery boss A
    check("복구 번호 로그인 → 200", g.status == 200 and (g.json() or {}).get("token"), g)
    stok = token(e, D, "staff", STAFF_PW)                               # ok staff D (2단계 풀림 - 표 없이)
    g = api(e, D, "POST", "/api/logout", {}, stok)                      # logout staff D
    check("로그아웃 → 200", g.status == 200, g)
    stok = token(e, D, "staff", STAFF_PW)                               # ok staff D
    t_last = e.clock()
    e.clock.go(1801)
    g = api(e, D, "GET", "/api/session", tok=stok)                      # timeout staff D
    check("1801초 뒤 세션 → 401", g.status == 401, g)
    rows = hist(e)
    want = [("ok", "boss", A, 1), ("ok", "staff", D, 3), ("mfa_on", "boss", A, 1), ("mfa_on", "staff", D, 2),
            ("bad_password", "staff", B, 1), ("bad_password", None, B, 1), ("bad_password", "staff", C, 5),
            ("locked", "staff", C, 1), ("disabled", "gone", D, 1), ("mfa_off", "staff", D, 1), ("mfa_reset", "staff", A, 1),
            ("bad_code", "boss", A, 1), ("recovery", "boss", A, 1), ("logout", "staff", D, 1), ("timeout", "staff", D, 1)]
    for res, uid, ip, n in want:
        got = count(rows, res, uid, ip)
        check(f"  {res} 아이디={uid} 주소={ip} → {n}줄", got == n, f"{got}줄")
    check("  줄 수 합이 맞다 (다른 줄 없음)", len(rows) == sum(w[3] for w in want), repr([(r["result"], r["uid"], r["ip"]) for r in rows]))
    check("  agent 는 브라우저 종류만 (Edge · Windows)", all(r["agent"] == KIND for r in rows), repr({r["agent"] for r in rows}))
    check("  ghost 글자는 어디에도 없음", not any("ghost" in json.dumps(r, ensure_ascii=False) for r in rows))
    check("  at 은 손 시계 ms (마지막 ok 줄 = 그때 시각)", len(rows) > 1 and rows[-2]["result"] == "ok"
          and rows[-2]["at"] == int(t_last * 1000), repr(rows[-2:]))
    check("  timeout 줄 at = 세션이 끝난 시각 (로그인 + 1800초, ③ 전체 검토 3)", rows and rows[-1]["at"] == int((t_last + 1800) * 1000),
          repr(rows[-1:]))
    check("  timeout 줄은 맨 끝", rows and rows[-1]["result"] == "timeout")

    # 잠금마다 한 줄 - 주소 잠금 (없는 아이디 열 개를 한 번씩), 아이디 전체 잠금 (여러 주소에서 네 번씩)
    e2 = start("off")
    for i in range(10):
        login(e2, B, f"nobody{i}", "wrong-pass-01")
    rows = hist(e2)
    check("주소 잠금 - 10번째 실패에 locked 한 줄 (uid None)", count(rows, "bad_password", None, B) == 10
          and count(rows, "locked", None, B) == 1 and len(rows) == 11, repr([(r["result"], r["uid"]) for r in rows]))
    g = login(e2, B, "staff", STAFF_PW)
    check("  막힌 주소의 다음 시도 429·줄 없음", g.status == 429 and len(hist(e2)) == 11, g)
    ips = [f"10.0.1.{i}" for i in range(1, 9)]
    for ip in ips:
        for _ in range(4):
            login(e2, ip, "staff", "wrong-pass-01")
    rows = hist(e2)[11:]
    check("아이디 전체 잠금 - 30번째 실패에 locked 한 줄 (그 뒤 두 번은 429, 줄 없음)",
          count(rows, "bad_password", "staff") == 30 and count(rows, "locked", "staff", ips[-1]) == 1 and len(rows) == 31,
          repr([(r["result"], r["uid"], r["ip"]) for r in rows]))


def test_history_access():
    print("test_history_access")
    e = start("off")
    t1 = e.clock()
    r = login(e, A)
    check("첫 로그인 응답 lastLogin None (칸은 있음)", r.status == 200 and "lastLogin" in (r.json() or {})
          and (r.json() or {}).get("lastLogin") is None, r)
    e.clock.go(60)
    r = login(e, B)
    boss = (r.json() or {}).get("token")
    check("두 번째 로그인 lastLogin = 첫 로그인 시각·주소", (r.json() or {}).get("lastLogin") == {"at": int(t1 * 1000), "ip": A}, r)
    stok = token(e, C, "staff", STAFF_PW)
    g = api(e, C, "GET", "/api/logins", tok=stok)
    check("유저 /api/logins → 403", g.status == 403, g)
    g = api(e, C, "GET", "/api/logins/me", tok=stok)
    items = (g.json() or {}).get("items")
    check("유저 /api/logins/me → 자기 것만", g.status == 200 and items and all(x["uid"] == "staff" for x in items), g)
    check("  칸 id·at·uid·ip·agent·result", items and set(items[0]) == {"id", "at", "uid", "ip", "agent", "result"}, repr(items))
    g = api(e, B, "GET", "/api/logins/other", tok=boss)
    check("/api/logins/<me 말고> → 404", g.status == 404, g)
    g = api(e, B, "GET", "/api/logins", tok=boss)
    items = (g.json() or {}).get("items") or []
    check("관리자 /api/logins → 모든 계정 (ok 셋)", g.status == 200 and [x["uid"] for x in items] == ["staff", "boss", "boss"], g)
    g = api(e, B, "GET", "/api/logins?id=staff", tok=boss)
    check("  id=staff 거르기", g.status == 200 and [x["uid"] for x in (g.json() or {}).get("items", [])] == ["staff"], g)
    g = api(e, B, "GET", "/api/logins?result=ok&limit=1", tok=boss)
    first = (g.json() or {}).get("items") or []
    check("  result=ok·limit=1", g.status == 200 and len(first) == 1 and first[0]["uid"] == "staff", g)
    g = api(e, B, "GET", f"/api/logins?result=ok&limit=5&before={first[0]['id'] if first else 0}", tok=boss)
    check("  before 로 다음 쪽", g.status == 200 and [x["uid"] for x in (g.json() or {}).get("items", [])] == ["boss", "boss"], g)
    today = time.strftime("%Y-%m-%d", time.localtime(e.clock()))
    g = api(e, B, "GET", f"/api/logins?from={today}&to={today}", tok=boss)
    check("  from·to 오늘 → 셋", g.status == 200 and len((g.json() or {}).get("items", [])) == 3, g)
    g = api(e, B, "GET", "/api/logins?from=2000-01-01&to=2000-01-02", tok=boss)
    check("  지난 기간 → 없음", g.status == 200 and (g.json() or {}).get("items") == [], g)
    for q in ("from=2026-13-40", "to=abc", "result=bogus", "id=Bad!!", "limit=x", "before=-x"):
        g = api(e, B, "GET", f"/api/logins?{q}", tok=boss)
        check(f"  틀린 값 {q} → 400", g.status == 400, g)
    g = api(e, C, "GET", "/api/logins/me?limit=x", tok=stok)
    check("  me 틀린 limit → 400", g.status == 400, g)
    # 계정 목록에 2단계 켬 여부 (사내 서버만)
    enroll(e, C, stok)
    g = api(e, B, "GET", "/api/accounts", tok=boss)
    accts = {a["id"]: a for a in (g.json() or {}).get("accounts", [])}
    check("/api/accounts 계정마다 mfa (staff 참·boss 거짓)", g.status == 200 and accts.get("staff", {}).get("mfa") is True
          and accts.get("boss", {}).get("mfa") is False, g)
    stok = mfa_token = None
    # 유저 이력 보이기 끄기
    g = api(e, B, "POST", "/api/security", {"showOwnHistory": False}, boss)
    check("관리자가 showOwnHistory 끔 → 200", g.status == 200, g)
    stok = token(e, C, "staff", STAFF_PW)          # 2단계를 켰으니 표가 온다 - 그 표로 세션
    if stok is None:
        sec = e.ui.accounts.mfa_secret("staff")
        mfa_token = mfa_login(e, C, "staff", STAFF_PW, sec)
    g = api(e, C, "GET", "/api/logins/me", tok=stok or mfa_token)
    check("  유저 me → 403", g.status == 403, g)
    g = api(e, B, "GET", "/api/logins/me", tok=boss)
    check("  관리자 me → 200 (자기 것만)", g.status == 200 and all(x["uid"] == "boss" for x in (g.json() or {}).get("items", [])), g)


def test_no_secret_leaks():
    print("test_no_secret_leaks")
    global SEEN
    SEEN = []
    try:
        e = start()
        new_staff = "staff-pw-0777"
        wrong = "wrong-pass-0999"
        boss = token(e, A)
        secret, rec = enroll(e, A, boss)
        api(e, A, "POST", "/api/logout", {}, boss)
        t = (login(e, A).json() or {}).get("ticket")
        api(e, A, "POST", "/api/login/mfa", {"ticket": t, "code": wrong_code(e, secret)})
        g = api(e, A, "POST", "/api/login/mfa", {"ticket": t, "recovery": rec[1]})
        api(e, A, "POST", "/api/logout", {}, (g.json() or {}).get("token"))
        boss = mfa_login(e, A, "boss", BOSS_PW, secret)
        login(e, B, "staff", wrong)
        stok = token(e, B, "staff", STAFF_PW)
        api(e, B, "POST", "/api/password", {"current": wrong, "next": new_staff}, stok)
        api(e, B, "POST", "/api/password", {"current": STAFF_PW, "next": new_staff}, stok)
        api(e, A, "POST", "/api/security", {"totpScope": "off", "password": wrong, "code": code_now(e, secret)}, boss)
        g = api(e, A, "POST", "/api/security", {"totpScope": "off", "password": BOSS_PW, "code": code_now(e, secret)}, boss)
        check("범위 줄이기 → 200", g.status == 200, g)
        for path in ("/api/logins", "/api/logins/me", "/api/accounts", "/api/session", "/api/security"):
            api(e, A, "GET", path, tok=boss)
        seen = list(SEEN)
    finally:
        SEEN = None
    secrets_ = [secret, secret.lower()] + [x for c in rec for x in (c, c.upper(), c.replace("-", ""))]
    passwords = [BOSS_PW, STAFF_PW, new_staff, wrong]
    tickets, tokens = [], []
    for _, g in seen:
        j = g.json() if isinstance(g.json(), dict) else {}
        if j.get("ticket"):
            tickets.append(j["ticket"])
        if j.get("token"):
            tokens.append(j["token"])
    check("시험 중 표·세션을 받았다", len(tickets) >= 2 and len(tokens) >= 3, f"{len(tickets)} {len(tokens)}")
    shown = [(p, g.raw) for p, g in seen if p not in ("/api/mfa/setup", "/api/mfa/enable")]
    leak = [p for p, raw in shown if any(s in raw for s in secrets_ + passwords)]
    check("응답(등록 시작·완료 빼고)에 비밀 값·복구 번호·비밀번호 없음", not leak, repr(leak))
    many = [t for t in tickets if sum(t in raw for _, raw in shown) != 1]
    check("표는 그것을 준 로그인 응답 하나에만", not many, repr(many))
    log = log_text(e)
    db = os.path.join(e.folder, "logins.db")
    con = __import__("sqlite3").connect(db)
    try:
        cells = "\n".join(str(v) for row in con.execute("SELECT * FROM logins") for v in row)
    finally:
        con.close()
    with open(os.path.join(e.folder, "security.json"), encoding="utf-8") as f:
        sec_text = f.read()
    for name, text in (("서버 기록", log), ("logins.db", cells), ("security.json", sec_text)):
        bad = [s for s in secrets_ + passwords + tickets + tokens if s in text]
        check(f"{name} 에 비밀 값·복구 번호·비밀번호·표·세션 토큰 없음", not bad, repr(bad[:3]))
    check("logins.db 에 User-Agent 원문 없음", "Mozilla" not in cells and "Edg/" not in cells)
    check("logins.db 에 줄이 있다 (시험이 이력을 남겼다)", cells.count("\n") > 10, repr(cells[:200]))


def test_history_write_failure():
    print("test_history_write_failure")
    e = start("off")
    e.ui.login_log.close()                   # 이력 DB 가 쓰이지 않는 상태 (디스크 오류 자리)
    r = login(e, A)
    check("이력을 못 써도 로그인 200·lastLogin None", r.status == 200 and (r.json() or {}).get("token")
          and (r.json() or {}).get("lastLogin") is None, r)
    g = login(e, A, "staff", "wrong-pass-01")
    check("  틀린 비밀번호는 그대로 401", g.status == 401, g)
    g = api(e, A, "POST", "/api/logout", {}, (r.json() or {}).get("token"))
    check("  로그아웃 200", g.status == 200, g)
    text = log_text(e)
    check("  서버 기록에 종류만 한 줄씩 ('로그인 이력 쓰기 오류: <종류>')",
          "로그인 이력 쓰기 오류: ProgrammingError" in text and "로그인 이력 읽기 오류: ProgrammingError" in text, text[-400:])
    boss = token(e, A)
    g = api(e, A, "GET", "/api/logins", tok=boss)
    check("  이력 창구는 503 (화면에 다시 시도)", g.status == 503 and g.code == "unavailable", g)
    e.ui.login_log = None                    # 끝정리에서 두 번 닫지 않게


def test_single_no_history():
    print("test_single_no_history")
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
    tok = (r.json() or {}).get("token")
    check("단독 로그인 응답에 lastLogin 없음", r.status == 200 and "lastLogin" not in (r.json() or {}), r)
    for path in ("/api/logins", "/api/logins/me"):
        g = call("GET", path, tok=tok)
        check(f"단독 GET {path} → 404", g.status == 404 and g.code == "not-found", g)
    g = call("GET", "/api/accounts", tok=tok)
    check("단독 /api/accounts 계정 칸 그대로 (mfa 없음)", g.status == 200
          and all(set(a) == {"id", "role", "disabled", "mustChange"} for a in (g.json() or {}).get("accounts", [])), g)
    call("POST", "/api/logout", {}, tok)
    check("자료 폴더에 logins.db 없음", not os.path.exists(os.path.join(folder, "logins.db")), os.listdir(folder))
    check("Web.login_log None", getattr(web, "login_log", "x") is None)


TESTS = [test_enroll_flow, test_must_change_first, test_two_step_login, test_ticket_rules, test_code_lockout,
         test_same_code_race, test_admin_reset_and_disable, test_setup_needs_password_when_on, test_single_unchanged,
         test_security_get_set, test_scope_raise_live_session,
         test_history_events, test_history_access, test_no_secret_leaks, test_history_write_failure, test_single_no_history]

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
        for w in WEBS:                       # logins.db 를 닫아야 윈도우에서 임시 폴더가 지워진다
            log = getattr(w, "login_log", None)
            if log is not None:
                log.close()
        shutil.rmtree(TMP, ignore_errors=True)
    print(f"\n실패: {len(fails)}" + (" (" + ", ".join(fails) + ")" if fails else ""))
    sys.exit(1 if fails else 0)
