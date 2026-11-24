# -*- coding: utf-8 -*-
"""사내 서버 ② Task 6 - 웹: 주소별 로그인 잠금(비밀번호 계산 전에), 아이디 잠금 60·300·900초, 믿을 프록시만 X-Forwarded-For,
세션을 주소에 묶기, https Origin 목록, 평문 프록시 모양(web_plain), HSTS, 웹 Host 를 설정 목록으로
(계획 2026-11-24-lan-2-network Task 6, 설계 6.3 '리버스 프록시 뒤에 설 자리'·6.6 로그인 잠금).
make_lan_servers 로 두 포트를 127.0.0.1 에 포트 0 으로 띄우고, 웹 서버의 peer_ip 를 바꿔 끼워 여러 주소를 흉내 낸다.
시계는 Web(clock=…) 에 넣은 손 시계. 클라이언트는 우리 인증 기관만 믿는 ssl.create_default_context(cadata=…) + http.client.
윈도우·리눅스(WSL) 둘 다 같은 파일로 돈다.
    D:/AX/RPA/.venv/Scripts/python.exe tests/test_lan_web_tls.py
    wsl.exe -d Ubuntu -e python3 /mnt/d/AX/RPA_StandAlone/tests/test_lan_web_tls.py
"""
import dataclasses
import http.client
import json
import os
import shutil
import ssl
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

fails = []
TMP = tempfile.mkdtemp(prefix="rpa_lan_web_tls_")
LIC = {"edition": "standalone", "company": "시험상사", "cid": "c1", "pc_id": "srv", "issued": "2026-11-24",
       "modules": {}, "features": {}, "limits": {}}
BOSS_PW, STAFF_PW = "pw-12345678", "staff-pw-0001"
GUIDS = ["11111111-2222-3333-4444-5555555555%02d" % i for i in range(10)]
PROXY_MSG = "프록시를 거쳐 접속하여 주십시오."


def check(name, ok, detail=""):
    print(f"  [{'통과' if ok else '실패'}] {name}" + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


# --- 인증서 (Task 2) ---
CA_DIR, OUT = os.path.join(TMP, "ca"), os.path.join(TMP, "srv")
lan_ca.make_ca(CA_DIR, ["localhost"], ["127.0.0.1"])
CERT, KEY = lan_ca.issue_server(CA_DIR, OUT, ["localhost"], ["127.0.0.1"])
CA_PEM = lan_ca.ca_pem(CA_DIR)
WEB_DIR = os.path.join(TMP, "web")
os.makedirs(WEB_DIR)
with open(os.path.join(WEB_DIR, "index.html"), "w", encoding="utf-8") as f:
    f.write("<!doctype html><title>로그인</title>")


def ctx():
    return ssl.create_default_context(cadata=CA_PEM)


class Got:
    def __init__(self, status, headers, raw):
        self.status, self.headers, self.raw = status, headers, raw

    def json(self):
        try:
            return json.loads(self.raw) if self.raw else None
        except ValueError:
            return None

    @property
    def code(self):
        v = self.json()
        return v.get("code") if isinstance(v, dict) else None

    @property
    def message(self):
        v = self.json()
        return v.get("message") if isinstance(v, dict) else None

    def __repr__(self):
        return f"<{self.status} {self.raw[:200]!r}>"


def call(port, method, path, body=None, headers=None, tls=True):
    """요청 하나 → Got. headers 에 Host 가 있으면 그것을 싣는다."""
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    hs = dict(headers or {})
    if data is not None:
        hs.setdefault("Content-Type", "application/json")
    c = (http.client.HTTPSConnection("127.0.0.1", port, context=ctx(), timeout=10) if tls
         else http.client.HTTPConnection("127.0.0.1", port, timeout=10))
    try:
        c.request(method, path, body=data, headers=hs)
        r = c.getresponse()
        return Got(r.status, r.headers, r.read())
    finally:
        c.close()


class Clock:
    """손 시계 - Web 의 세션·잠금이 쓴다."""

    def __init__(self):
        self.t = time.time()

    def __call__(self):
        return self.t

    def go(self, sec):
        self.t += sec


SERVERS, RUNS = [], []
BASE = {"listen": "127.0.0.1", "names": ["localhost"], "allow": ["127.0.0.0/8", "10.0.0.0/8"]}


def start(extra=None, clock=None, plain=False):
    """사내 서버 두 포트 (웹 서버의 peer_ip 는 env.peer["ip"] 를 돌려준다 - 여러 주소 흉내)."""
    folder = tempfile.mkdtemp(dir=TMP)
    store = local_server.Store(os.path.join(folder, "store.json"), volatile=local_server.VOLATILE)
    runs = local_server.Runs(":memory:")
    RUNS.append(runs)
    reg = pc_registry.Registry(os.path.join(folder, "pcs.json"), seats=20)
    clock = clock or Clock()
    web = local_web.Web(store, runs, LIC, folder, WEB_DIR, clock=clock, registry=reg)
    web.accounts.set("boss", BOSS_PW, "admin")
    web.accounts.set("staff", STAFF_PW, "viewer")
    cfg = lan_config.parse(dict(BASE, **(extra or {})))
    cfg = dataclasses.replace(cfg, web_port=0, agent_port=0)
    w, a = lan_server.make_lan_servers(store, runs, LIC, reg, web, cfg, CERT, KEY, CA_PEM)
    peer = {"ip": "127.0.0.1"}
    w.peer_ip = lambda addr: peer["ip"]
    for s in (w, a):
        threading.Thread(target=s.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        SERVERS.append(s)
    return types.SimpleNamespace(web=w, agent=a, wp=w.server_address[1], ap=a.server_address[1], store=store, reg=reg, ui=web,
                                 folder=folder, clock=clock, peer=peer, tls=not plain)


def req(env, ip, method, path, body=None, headers=None):
    env.peer["ip"] = ip
    return call(env.wp, method, path, body, headers, tls=env.tls)


def login(env, ip, uid="boss", pw=BOSS_PW, headers=None):
    return req(env, ip, "POST", "/api/login", {"id": uid, "password": pw}, headers)


def bearer(tok, extra=None):
    return dict({"Authorization": "Bearer " + (tok or "")}, **(extra or {}))


def log_text(env):
    try:
        with open(os.path.join(env.folder, local_server.LOG_NAME), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


class HashCount:
    """local_web._hash 를 부른 횟수 (pbkdf2 계산)."""

    def __enter__(self):
        self.n, self.orig = 0, local_web._hash

        def spy(*a, **k):
            self.n += 1
            return self.orig(*a, **k)
        local_web._hash = spy
        return self

    def __exit__(self, *exc):
        local_web._hash = self.orig


def active_pc(env, label="PC", guid_i=0):
    """등록부에 PC 하나를 바로 등록 → pc 번호."""
    st = env.reg.start(label)
    rand = os.urandom(32).hex()
    env.reg.enroll(st["pc_id"], rand, GUIDS[guid_i], "PC-A", pc_registry.enroll_proof(st["token"], st["pc_id"], rand, GUIDS[guid_i], "PC-A"))
    return st["pc_id"]


# ----------------------------------------------------------------------------------------------------

def test_units():
    print("잠금 부품 (AddrLock·Lockout steps)")
    c = Clock()
    lo = local_web.Lockout(limit=5, lock_sec=60, clock=c)
    check("Lockout 기본 steps 는 (lock_sec,) - 단독 그대로", lo.steps == (60,), lo.steps)
    check("상수 LOCK_SEC 그대로 60", local_web.LOCK_SEC == 60 and local_web.LAN_LOCK_STEPS == (60, 300, 900))
    for _ in range(5):
        lo.fail("x")
    c.go(61)
    for _ in range(5):
        lo.fail("x")
    check("단독 Lockout 은 두 번째 잠금도 60초", 0 < lo.remaining("x") <= 60, lo.remaining("x"))
    lo2 = local_web.Lockout(clock=c, steps=(60, 300, 900))
    got = []
    for _ in range(4):
        for _ in range(5):
            lo2.fail("y")
        got.append(round(lo2.remaining("y")))
        c.go(got[-1] + 1)
    check("steps (60,300,900) → 잠길 때마다 다음 칸, 끝 칸에 머문다", got == [60, 300, 900, 900], got)
    lo2.ok("y")
    for _ in range(5):
        lo2.fail("y")
    check("성공하면 처음(60초)부터", round(lo2.remaining("y")) == 60, lo2.remaining("y"))

    al = local_web.AddrLock(clock=c)
    check("AddrLock 기본값 10번·600초·600초", (al.limit, al.window, al.block) == (10, 600, 600))
    res = [al.fail("10.0.0.1") for _ in range(10)]
    check("10번째 실패에 막힌다 (fail 이 True)", res == [False] * 9 + [True] and al.blocked("10.0.0.1"), res)
    check("다른 주소는 막히지 않는다", not al.blocked("10.0.0.2"))
    c.go(601)
    check("600초 뒤 풀린다", not al.blocked("10.0.0.1"))
    al2 = local_web.AddrLock(clock=c)
    for _ in range(9):
        al2.fail("10.0.0.3")
    c.go(601)
    check("10분이 지난 실패는 세지 않는다", al2.fail("10.0.0.3") is False and not al2.blocked("10.0.0.3"))
    al2.ok("10.0.0.3")
    check("ok 는 그 주소의 셈을 지운다", "10.0.0.3" not in al2._items)
    al3 = local_web.AddrLock(clock=c)
    for i in range(local_web.LOCK_TRACK_MAX + 50):
        al3.fail(f"ip{i}")
    check("표 상한 LOCK_TRACK_MAX", len(al3._items) <= local_web.LOCK_TRACK_MAX, len(al3._items))

    print("  세션 주소 (Sessions.open ip·get ip)")
    s = local_web.Sessions(clock=c)
    t1 = s.open({"id": "a", "role": "admin"}, ip="10.0.0.1")
    t2 = s.open({"id": "b", "role": "admin"})
    check("주소 묶인 세션: 같은 주소 → 있음", s.get(t1, ip="10.0.0.1") is not None)
    check("주소 묶인 세션: 다른 주소 → None", s.get(t1, ip="10.0.0.2") is None)
    check("주소 묶인 세션: 주소 없이 묻기 → None", s.get(t1) is None)
    check("다른 주소로 물어도 세션을 지우지 않는다 (훔친 토큰으로 주인을 쫓아내지 못하게)", s.get(t1, ip="10.0.0.1") is not None)
    check("주소 없는 세션은 어느 주소로도 된다", s.get(t2, ip="10.0.0.9") is not None and s.get(t2) is not None)


def test_addr_lock():
    print("주소 기준 잠금 - 비밀번호 계산 전에 (test_addr_lock)")
    e = start()
    a, b = "10.0.0.1", "10.0.0.2"
    for i in range(10):
        g = login(e, a, f"nobody{i}", "wrong-pw-000")
        if g.status != 401:
            check(f"주소 A {i + 1}번째 틀림 → 401", False, g)
            break
    with HashCount() as hc:
        g = login(e, a)
    check("주소 A: 서로 다른 아이디로 10번 틀린 뒤 맞는 비밀번호도 429", g.status == 429 and g.code == "auth/too-many-requests", g)
    check("  안내 글은 '이 PC 에서 … 10분 뒤'", "이 PC 에서 로그인 시도가 많아" in (g.message or "") and "10분 뒤" in (g.message or ""), g.message)
    check("  막힌 주소에서는 비밀번호를 계산하지 않는다 (pbkdf2 0번)", hc.n == 0, hc.n)
    g = login(e, b)
    check("주소 B 의 관리자 로그인은 된다", g.status == 200 and (g.json() or {}).get("token"), g)
    check("기록에 주소 잠금 줄 (주소=10.0.0.1)", "주소=10.0.0.1" in log_text(e) and "주소 잠금" in log_text(e), log_text(e)[-600:])
    e.clock.go(601)
    g = login(e, a)
    check("10분 뒤 주소 A 다시 된다", g.status == 200, g)

    print("  비밀번호 바꾸기(_password)도 같은 주소 잠금")
    c = "10.0.0.3"
    tok = (login(e, c, "staff", STAFF_PW).json() or {}).get("token")
    for i in range(5):
        login(e, c, f"ghost{i}", "wrong-pw-000")
    for i in range(5):
        g = req(e, c, "POST", "/api/password", {"current": f"wrong-cur-{i:04d}", "next": "new-pw-00001"}, bearer(tok))
        if g.status != 403:
            check(f"  비밀번호 바꾸기 {i + 1}번째 틀림 → 403", False, g)
            break
    with HashCount() as hc:
        g = req(e, c, "POST", "/api/password", {"current": STAFF_PW, "next": "new-pw-00001"}, bearer(tok))
    check("  로그인 5번 + 비밀번호 바꾸기 5번 틀린 주소 → 맞는 현재 비밀번호도 429 (주소 잠금 글)",
          g.status == 429 and g.code == "auth/too-many-requests" and "이 PC 에서" in (g.message or ""), g)
    check("  그때도 비밀번호를 계산하지 않는다", hc.n == 0, hc.n)
    check("  비밀번호는 그대로", e.ui.accounts.verify("staff", STAFF_PW) is not None)


def test_id_lock_grows():
    print("같은 아이디 잠금이 늘어난다 60 → 300 → 900, 성공하면 60 부터 (test_id_lock_grows)")
    e = start()
    check("사내 서버 Web 의 steps (60, 300, 900)", e.ui.lockout.steps == (60, 300, 900), e.ui.lockout.steps)
    ips = iter(f"10.1.0.{i}" for i in range(1, 50))

    def five_wrong():
        ip = next(ips)
        for _ in range(5):
            login(e, ip, "boss", "wrong-pw-000")
        return ip

    for want, minutes in ((60, 1), (300, 5), (900, 15)):
        five_wrong()
        g = login(e, next(ips))
        check(f"{want}초 잠금: 맞는 비밀번호도 429, 안내 글 '{minutes}분 뒤'",
              g.status == 429 and g.code == "auth/too-many-requests" and f"{minutes}분 뒤" in (g.message or ""), g)
        check(f"  남은 시간 {want}초", round(e.ui.lockout.remaining("boss")) == want, e.ui.lockout.remaining("boss"))
        e.clock.go(want - 2)
        check(f"  {want - 2}초 뒤에도 잠김", login(e, next(ips)).status == 429)
        e.clock.go(3)
    g = login(e, next(ips))
    check("900초가 지나면 맞는 비밀번호로 로그인", g.status == 200, g)
    five_wrong()
    check("성공한 뒤 다시 잠기면 60초부터", round(e.ui.lockout.remaining("boss")) == 60, e.ui.lockout.remaining("boss"))
    check("기록의 잠금 줄에 실제 초 (900초 잠금)", "900초 잠금" in log_text(e), log_text(e)[-800:])


def test_forged_xff_ignored():
    print("프록시 밖에서 지어 보낸 X-Forwarded-For 는 버린다 (test_forged_xff_ignored, Review Focus 1)")
    e = start({"trusted_proxies": ["10.0.0.9"]})
    for i in range(10):
        login(e, "10.0.0.7", f"nobody{i}", "wrong-pw-000", headers={"X-Forwarded-For": "10.9.9.9"})
    check("잠금은 소켓 주소(10.0.0.7)로", e.ui.addr_lock.blocked("10.0.0.7") and not e.ui.addr_lock.blocked("10.9.9.9"))
    g = login(e, "10.0.0.7", headers={"X-Forwarded-For": "10.2.2.2"})
    check("  머리글을 바꿔 보내도 10.0.0.7 은 429", g.status == 429, g)
    text = log_text(e)
    check("기록도 소켓 주소 (주소=10.0.0.7, 10.9.9.9 없음)", "주소=10.0.0.7" in text and "10.9.9.9" not in text, text[-600:])

    print("  믿을 프록시(10.0.0.9)에서 온 것은 머리글의 주소로")
    for i in range(10):
        login(e, "10.0.0.9", f"nobody{i}", "wrong-pw-000", headers={"X-Forwarded-For": "10.0.0.50"})
    check("잠금은 머리글의 주소(10.0.0.50)로, 프록시는 막히지 않는다",
          e.ui.addr_lock.blocked("10.0.0.50") and not e.ui.addr_lock.blocked("10.0.0.9"))
    g = login(e, "10.0.0.9", headers={"X-Forwarded-For": "10.0.0.51"})
    check("  같은 프록시 뒤의 다른 사람(10.0.0.51)은 로그인된다", g.status == 200, g)
    g = login(e, "10.0.0.9", headers={"X-Forwarded-For": "10.0.0.50"})
    check("  10.0.0.50 은 429", g.status == 429, g)
    check("기록에 주소=10.0.0.50·주소=10.0.0.51", "주소=10.0.0.50" in log_text(e) and "주소=10.0.0.51" in log_text(e))


def test_session_bound_to_ip():
    print("세션을 주소에 묶는다 (test_session_bound_to_ip)")
    e = start()
    a, b = "10.0.0.11", "10.0.0.12"
    tok = (login(e, a).json() or {}).get("token")
    g = req(e, b, "GET", "/api/session", headers=bearer(tok))
    check("주소 A 의 토큰을 주소 B 에서 → 401", g.status == 401 and g.code == "unauthenticated", g)
    g = req(e, a, "GET", "/api/session", headers=bearer(tok))
    check("주소 A 에서는 그대로 200 (B 의 시도가 세션을 닫지 않았다)", g.status == 200, g)
    g = req(e, a, "GET", "/api/session?touch=1", headers=bearer(tok))
    check("touch 도 같은 주소로", g.status == 200, g)

    print("  스트림의 1초 세션 확인도 같은 주소로")
    pc = active_pc(e, "스트림", 1)
    e.peer["ip"] = a
    c = http.client.HTTPSConnection("127.0.0.1", e.wp, context=ctx(), timeout=10)
    events = []
    try:
        c.request("GET", f"/api/stream?pcId={pc}", headers=bearer(tok))
        r = c.getresponse()
        check("스트림 200", r.status == 200, r.status)
        e.peer["ip"] = b                      # 이 뒤의 연결은 B 로 보인다 - 열린 스트림은 처음 주소(A)를 쓴다

        def read():
            try:
                while True:
                    line = r.fp.readline()
                    if not line:
                        break
                    if line.startswith(b"event: "):
                        events.append(line[7:].strip().decode())
                    elif line.startswith(b"data: ") and events:
                        events[-1] += " " + line[6:].strip().decode("utf-8")
            except Exception:
                pass
        th = threading.Thread(target=read, daemon=True)
        th.start()
        time.sleep(1.8)                        # 세션 확인이 한 번 이상 돈다
        e.store.put(f"apps/rpa/live/c1/{pc}", {"state": "idle"})
        end = time.time() + 5
        while time.time() < end and not any(x.startswith("live") and "idle" in x for x in events) and "gone" not in events:
            time.sleep(0.05)
    finally:
        c.close()
    check("1초 확인 뒤에도 gone 없이 live 를 받는다", "gone" not in events and any(x.startswith("live") and "idle" in x for x in events),
          events)

    print("  bind_session_ip=False 면 묶지 않는다")
    e2 = start({"bind_session_ip": False})
    tok = (login(e2, a).json() or {}).get("token")
    g = req(e2, b, "GET", "/api/session", headers=bearer(tok))
    check("주소 A 의 토큰을 B 에서 → 200", g.status == 200, g)


def test_origin_https_list():
    print("Origin 은 https:// + 웹 Host 목록 (test_origin_https_list)")
    e = start({"public_web": ["ap.corp.local"]})
    for origin, want in ((f"http://127.0.0.1:{e.wp}", 403), (f"http://localhost:{e.wp}", 403), ("https://evil.example", 403),
                         (f"https://127.0.0.1:{e.wp + 1}", 403), (f"https://127.0.0.1:{e.wp}", 200),
                         (f"https://localhost:{e.wp}", 200), ("https://ap.corp.local", 200), ("https://AP.corp.local", 200)):
        g = login(e, "127.0.0.1", headers={"Origin": origin})
        check(f"Origin {origin} → {want}", g.status == want and (want == 200 or g.code == "forbidden"), g)
    g = login(e, "127.0.0.1")
    check("Origin 없는 요청은 그대로 된다", g.status == 200, g)


def test_host_lan():
    print("웹 Host 는 설정 목록 (local_server.host_ok) - 사내 주소 Host 가 된다")
    e = start({"public_web": ["192.168.1.230:8443", "ap.corp.local"]})
    for host, want in (("192.168.1.230:8443", 200), ("AP.CORP.LOCAL", 200), (f"127.0.0.1:{e.wp}", 200), (f"localhost:{e.wp}", 200),
                       ("evil.example", 403), (f"127.0.0.1:{e.ap}", 403), ("127.0.0.1", 403), ("192.168.1.231:8443", 403)):
        g = req(e, "127.0.0.1", "GET", "/index.html", headers={"Host": host})
        check(f"웹 Host {host} → {want}", g.status == want, g)
    g = req(e, "127.0.0.1", "POST", "/api/login", {"id": "boss", "password": BOSS_PW},
            {"Host": "192.168.1.230:8443", "Origin": "https://192.168.1.230:8443"})
    check("사내 주소 Host·Origin 으로 로그인 200", g.status == 200, g)


def test_hsts_and_log():
    print("HSTS·기록의 주소 - 사내 서버만")
    e = start()
    for path in ("/index.html", "/api/session"):
        g = req(e, "10.0.0.21", "GET", path)
        check(f"사내: {path} 에 HSTS max-age=31536000", g.headers.get("Strict-Transport-Security") == "max-age=31536000", dict(g.headers))
    tok = (login(e, "10.0.0.21").json() or {}).get("token")
    req(e, "10.0.0.21", "POST", "/api/logout", {}, bearer(tok))
    text = log_text(e)
    check("사내: 로그인·로그아웃 줄에 주소=10.0.0.21",
          any("웹 로그인 " in ln and "주소=10.0.0.21" in ln for ln in text.splitlines())
          and any("웹 로그아웃" in ln and "주소=10.0.0.21" in ln for ln in text.splitlines()), text[-600:])

    print("  단독 (make_server + Web, cfg 없음) 은 그대로")
    folder = tempfile.mkdtemp(dir=TMP)
    store = local_server.Store(os.path.join(folder, "store.json"), volatile=local_server.VOLATILE)
    runs = local_server.Runs(":memory:")
    RUNS.append(runs)
    web = local_web.Web(store, runs, LIC, folder, WEB_DIR)
    web.accounts.set("boss", BOSS_PW, "admin")
    keys = local_server.ensure_keys(folder, lock=False)
    s = local_server.make_server(store, runs, LIC, keys, port=0, folder=folder, web=web)
    SERVERS.append(s)
    threading.Thread(target=s.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    port = s.server_address[1]
    check("단독: cfg 없음·steps (60,)", web.cfg is None and web.lockout.steps == (60,))
    g = call(port, "GET", "/index.html", tls=False)
    check("단독: HSTS 없음", g.status == 200 and g.headers.get("Strict-Transport-Security") is None, dict(g.headers))
    g = call(port, "POST", "/api/login", {"id": "boss", "password": BOSS_PW}, {"Origin": f"http://127.0.0.1:{port}"}, tls=False)
    check("단독: Origin http://127.0.0.1:<포트> 그대로 200", g.status == 200, g)
    g = call(port, "POST", "/api/login", {"id": "boss", "password": BOSS_PW}, {"Origin": f"https://127.0.0.1:{port}"}, tls=False)
    check("단독: Origin https://… 는 그대로 403", g.status == 403, g)
    g = call(port, "GET", "/index.html", headers={"Host": f"192.168.1.230:{port}"}, tls=False)
    check("단독: 사내 주소 Host 는 그대로 403", g.status == 403, g)
    text = ""
    try:
        with open(os.path.join(folder, local_server.LOG_NAME), encoding="utf-8") as f:
            text = f.read()
    except OSError:
        pass
    check("단독: 로그인 줄에 주소= 없음", "웹 로그인" in text and "주소=" not in text, text[-400:])
    for _ in range(5):
        call(port, "POST", "/api/login", {"id": "boss", "password": "wrong-pw-000"}, tls=False)
    g = call(port, "POST", "/api/login", {"id": "boss", "password": BOSS_PW}, tls=False)
    check("단독: 5번 틀리면 429 '1분 뒤' (그대로)", g.status == 429 and "1분 뒤" in (g.message or ""), g)


def test_plain_proxy_mode():
    print("평문 프록시 모양 web_plain (test_plain_proxy_mode)")
    e = start({"trusted_proxies": ["127.0.0.1"], "web_plain": True, "public_web": ["ap.corp.local"]}, plain=True)
    check("웹 포트는 평문", e.web.tls is None)
    g = req(e, "127.0.0.1", "GET", "/index.html")
    check("X-Forwarded-Proto 없음 → 403 '프록시를 거쳐…'", g.status == 403 and g.message == PROXY_MSG, g)
    g = req(e, "127.0.0.1", "GET", "/index.html", headers={"X-Forwarded-Proto": "http"})
    check("X-Forwarded-Proto http → 403", g.status == 403 and g.message == PROXY_MSG, g)
    g = req(e, "127.0.0.1", "GET", "/index.html", headers={"X-Forwarded-Proto": "https"})
    check("X-Forwarded-Proto https → 200", g.status == 200 and b"<title>" in g.raw, g)
    check("  HSTS 머리글이 있다", g.headers.get("Strict-Transport-Security") == "max-age=31536000", dict(g.headers))
    g = req(e, "10.0.0.7", "GET", "/index.html", headers={"X-Forwarded-Proto": "https"})
    check("소켓 주소가 믿을 프록시가 아니면 (https 머리글이 있어도) 403", g.status == 403 and g.message == PROXY_MSG, g)
    g = req(e, "127.0.0.1", "POST", "/api/login", {"id": "boss", "password": BOSS_PW}, {"X-Forwarded-Proto": "https"})
    check("API 도 https 머리글이 있으면 로그인 200", g.status == 200, g)
    g = req(e, "127.0.0.1", "POST", "/api/login", {"id": "boss", "password": BOSS_PW})
    check("API 도 머리글 없으면 403", g.status == 403 and g.message == PROXY_MSG, g)
    hs = {"X-Forwarded-Proto": "https", "Host": "ap.corp.local", "Origin": "https://ap.corp.local", "X-Forwarded-For": "10.0.0.31"}
    g = req(e, "127.0.0.1", "POST", "/api/login", {"id": "boss", "password": BOSS_PW}, hs)
    check("프록시가 내건 이름의 Host·https Origin → 200", g.status == 200, g)
    g = req(e, "127.0.0.1", "POST", "/api/login", {"id": "boss", "password": BOSS_PW}, dict(hs, Origin="http://ap.corp.local"))
    check("평문 모양이어도 http Origin → 403", g.status == 403 and g.code == "forbidden", g)
    check("기록의 주소는 프록시가 넘긴 10.0.0.31", "주소=10.0.0.31" in log_text(e), log_text(e)[-400:])


try:
    for t in (test_units, test_addr_lock, test_id_lock_grows, test_forged_xff_ignored, test_session_bound_to_ip,
              test_origin_https_list, test_host_lan, test_hsts_and_log, test_plain_proxy_mode):
        try:
            t()
        except Exception as ex:          # 한 시험이 터져도 나머지는 돈다
            check(f"{t.__name__} 가 예외 없이 끝난다", False, f"{type(ex).__name__}: {ex}")
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

print(f"\n실패 {len(fails)}건" + (": " + ", ".join(fails) if fails else ""))
sys.exit(1 if fails else 0)
