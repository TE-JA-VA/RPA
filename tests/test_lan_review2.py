# -*- coding: utf-8 -*-
"""사내 서버 ② 전체 검토에서 나온 다섯 가지 (계획 2026-11-24-lan-2-network, 설계 6.3·6.4·6.6).
1. 프록시 뒤에서도 허용 대역 검사 - 웹 처리기가 client_ip() 로 읽은 주소가 허용 대역 밖이면 403 (기록은 60초에 10줄까지)
2. 프록시 뒤의 주소별 동시 16·분당 600 - 믿을 프록시 연결은 받기 고리에서 주소별로 세지 않고 처리기가 client_ip() 로 센다 (넘으면 429)
3. 아이디 잠금은 (아이디, 보낸 주소) 쌍에 - 아이디 전체 잠금은 10분에 여러 주소 합쳐 30번이면 300초
4. 사내 서버 연결은 악수 뒤 요청(머리글·본문)을 10초 안에 다 보내야 한다 (REQUEST_DEADLINE)
5. 믿을 프록시가 X-Forwarded-For 를 안 보내면 - web_plain 은 403, TLS 웹 포트는 60초에 한 줄 경고. 'IPv4:포트'·'[IPv6]:포트' 는 포트를 뗀다
make_lan_servers 로 두 포트를 127.0.0.1 에 포트 0 으로 띄우고, 웹 서버의 peer_ip 를 바꿔 끼워 여러 주소를 흉내 낸다
(도우미는 test_lan_web_tls·test_lan_tls·test_lan_net 과 같은 꼴). 윈도우·리눅스(WSL) 둘 다 같은 파일로 돈다.
    D:/AX/RPA/.venv/Scripts/python.exe tests/test_lan_review2.py
    wsl.exe -d Ubuntu -e python3 /mnt/d/AX/RPA_StandAlone/tests/test_lan_review2.py
"""
import dataclasses
import http.client
import json
import os
import shutil
import socket
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
TMP = tempfile.mkdtemp(prefix="rpa_lan_review2_")
LIC = {"edition": "standalone", "company": "시험상사", "cid": "c1", "pc_id": "srv", "issued": "2026-11-24",
       "modules": {}, "features": {}, "limits": {}}
BOSS_PW, STAFF_PW = "pw-12345678", "staff-pw-0001"
GUIDS = ["11111111-2222-3333-4444-5555555555%02d" % i for i in range(10)]


def check(name, ok, detail=""):
    print(f"  [{'통과' if ok else '실패'}] {name}" + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


def until(fn, sec):
    end = time.time() + sec
    while time.time() < end:
        if fn():
            return True
        time.sleep(0.02)
    return bool(fn())


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


class Broken(Got):
    """연결이 답 없이 끊겼다 (받기 고리가 닫은 연결 등)."""

    def __init__(self, err):
        super().__init__(None, {}, b"")
        self.err = err

    def __repr__(self):
        return f"<끊김 {type(self.err).__name__}: {self.err}>"


def call(port, method, path, body=None, headers=None, tls=True):
    """요청 하나 → Got (끊기면 Broken). headers 에 Host 가 있으면 그것을 싣는다."""
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
    except (OSError, http.client.HTTPException) as ex:
        return Broken(ex)
    finally:
        c.close()


class Clock:
    """손 시계 - Web 의 세션·잠금·기록 줄이기, LanServer 의 분당 셈이 쓴다."""

    def __init__(self):
        self.t = time.time()

    def __call__(self):
        return self.t

    def go(self, sec):
        self.t += sec


SERVERS, RUNS = [], []
BASE = {"listen": "127.0.0.1", "names": ["localhost"], "allow": ["127.0.0.0/8", "10.0.0.0/8"]}


def start(extra=None, plain=False):
    """사내 서버 두 포트 (웹 서버의 peer_ip 는 env.peer["ip"] 를 돌려준다 - 여러 주소 흉내)."""
    folder = tempfile.mkdtemp(dir=TMP)
    with open(os.path.join(folder, "security.json"), "w", encoding="utf-8") as f:     # 2단계 범위 끔 (2단계는 test_lan_mfa, 계획 ③)
        f.write('{"version":1,"totp_scope":"off","show_own_history":true}')
    store = local_server.Store(os.path.join(folder, "store.json"), volatile=local_server.VOLATILE)
    runs = local_server.Runs(":memory:")
    RUNS.append(runs)
    reg = pc_registry.Registry(os.path.join(folder, "pcs.json"), seats=20)
    clock = Clock()
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


def xff(addr, extra=None):
    return dict({"X-Forwarded-For": addr}, **(extra or {}))


def bearer(tok, extra=None):
    return dict({"Authorization": "Bearer " + (tok or "")}, **(extra or {}))


def log_text(env):
    try:
        with open(os.path.join(env.folder, local_server.LOG_NAME), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def log_lines(env, word):
    return [ln for ln in log_text(env).splitlines() if word in ln]


def active_pc(env, label="PC", guid_i=0):
    """등록부에 PC 하나를 바로 등록 → pc 번호."""
    st = env.reg.start(label)
    rand = os.urandom(32).hex()
    env.reg.enroll(st["pc_id"], rand, GUIDS[guid_i], "PC-A", pc_registry.enroll_proof(st["token"], st["pc_id"], rand, GUIDS[guid_i], "PC-A"))
    return st["pc_id"]


class Stream:
    """웹 구독 /api/stream 하나 - 연 채로 두고 받은 이벤트를 모은다."""

    def __init__(self, env, tok, pc, headers=None):
        self.c = http.client.HTTPSConnection("127.0.0.1", env.wp, context=ctx(), timeout=30)
        self.events, self.status = [], None
        try:
            self.c.request("GET", f"/api/stream?pcId={pc}", headers=bearer(tok, headers))
            self.r = self.c.getresponse()
            self.status = self.r.status
        except (OSError, http.client.HTTPException) as ex:
            self.r, self.status = None, repr(ex)
            return
        if self.status == 200:
            threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        try:
            while True:
                line = self.r.fp.readline()
                if not line:
                    break
                if line.startswith(b"event: "):
                    self.events.append(line[7:].strip().decode())
                elif line.startswith(b"data: ") and self.events:
                    self.events[-1] += " " + line[6:].strip().decode("utf-8")
        except Exception:
            pass

    def close(self):
        for x in (self.r, self.c):
            try:
                if x is not None:
                    x.close()
            except Exception:
                pass


def nudge_until(env, pc, fn, sec=10):
    """닫힌 구독을 서버가 알아차리게 현황을 바꿔 가며 (쓰기가 실패해야 고리가 끝난다) fn() 이 참이 될 때까지."""
    end, n = time.time() + sec, 0
    while time.time() < end:
        if fn():
            return True
        n += 1
        env.store.put(f"apps/rpa/live/c1/{pc}", {"state": "idle", "n": n})
        time.sleep(0.2)
    return bool(fn())


def tls_open(port, timeout=10):
    raw = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    try:
        return ctx().wrap_socket(raw, server_hostname="127.0.0.1")
    except BaseException:
        raw.close()
        raise


# ----------------------------------------------------------------------------------------------------
# 1. 프록시 뒤 허용 대역
# ----------------------------------------------------------------------------------------------------

def test_allow_behind_proxy():
    print("1. 프록시 뒤에서도 허용 대역을 본다 (test_allow_behind_proxy)")
    e = start({"allow": ["10.0.0.0/8"], "trusted_proxies": ["127.0.0.1"]})
    out = "203.0.113.5"
    g = req(e, "127.0.0.1", "GET", "/index.html", headers=xff(out))
    check("프록시 경유 XFF 203.0.113.5 → GET /index.html 403", g.status == 403 and g.code == "forbidden", g)
    g = login(e, "127.0.0.1", headers=xff(out))
    check("프록시 경유 XFF 203.0.113.5 → 관리자 로그인 403 (토큰 없음)",
          g.status == 403 and not (g.json() or {}).get("token"), g)
    g = req(e, "127.0.0.1", "GET", "/index.html", headers=xff("10.0.0.5"))
    check("같은 설정에서 XFF 10.0.0.5 → GET /index.html 200", g.status == 200 and b"<title>" in g.raw, g)
    g = login(e, "127.0.0.1", headers=xff("10.0.0.5"))
    check("같은 설정에서 XFF 10.0.0.5 → 로그인 200", g.status == 200 and (g.json() or {}).get("token"), g)
    g = req(e, "127.0.0.1", "GET", "/index.html")
    check("XFF 없이 프록시(루프백) 자신 → 200 (막지 않는다)", g.status == 200, g)
    lines = log_lines(e, "허용 대역 밖")
    check("기록에 거절 줄 (주소=203.0.113.5)", any("주소=203.0.113.5" in ln for ln in lines), log_text(e)[-600:])

    print("  기록은 60초에 10줄까지")
    for i in range(15):
        req(e, "127.0.0.1", "GET", "/index.html", headers=xff(f"198.51.100.{i + 1}"))
    lines = log_lines(e, "허용 대역 밖")
    check("17번 거절해도 거절 줄은 10줄", len(lines) == 10, len(lines))
    e.clock.go(61)
    g = req(e, "127.0.0.1", "GET", "/index.html", headers=xff("198.51.100.99"))
    check("60초 뒤에도 403", g.status == 403, g)
    lines = log_lines(e, "허용 대역 밖")
    check("60초 뒤 다시 적는다 (주소=198.51.100.99)", any("주소=198.51.100.99" in ln for ln in lines), lines[-3:])
    check("생략한 수를 한 줄로 (7건 더)", any("7건 더" in ln for ln in log_text(e).splitlines()), log_text(e)[-600:])


# ----------------------------------------------------------------------------------------------------
# 2. 프록시 뒤 주소별 동시·분당
# ----------------------------------------------------------------------------------------------------

def test_proxy_per_client_limits():
    print("2. 프록시 뒤의 주소별 동시 16·분당 600 은 보낸 사람(client_ip)마다 (test_proxy_per_client_limits)")
    e = start({"trusted_proxies": ["127.0.0.1"]})
    tok = (login(e, "127.0.0.1", headers=xff("10.0.0.50")).json() or {}).get("token")
    pc = active_pc(e, "구독", 1)
    streams = []
    try:
        for _ in range(lan_server.PER_IP_CONN):
            streams.append(Stream(e, tok, pc, xff("10.0.0.50")))
        check("프록시 경유 구독 16개가 열린다", all(s.status == 200 for s in streams), [s.status for s in streams])
        check("서버 연결 수 16", until(lambda: e.web.conns == 16, 3), e.web.conns)
        g = req(e, "127.0.0.1", "GET", "/index.html", headers=xff("10.0.0.77"))
        check("그 상태에서 다른 사용자(XFF 10.0.0.77)의 GET /index.html → 200", g.status == 200, g)
        g = req(e, "127.0.0.1", "GET", "/index.html", headers=xff("10.0.0.50"))
        check("같은 XFF 로 17번째 동시 요청 → 429", g.status == 429, g)
        check("  429 뒤에도 셈은 16 그대로 (거절한 요청은 바로 돌려준다)",
              until(lambda: getattr(e.web, "clients", {}).get("10.0.0.50") == 16 and e.web.conns == 16, 3),
              (getattr(e.web, "clients", None), e.web.conns))
    finally:
        for s in streams:
            s.close()
    check("구독을 닫으면 셈이 돌아온다 (보낸 사람 표·연결 수)",
          nudge_until(e, pc, lambda: not getattr(e.web, "clients", {1: 1}) and e.web.conns == 0 and not e.web.per_ip),
          (getattr(e.web, "clients", None), e.web.conns, e.web.per_ip))
    check("믿을 프록시 연결은 받기 고리의 주소별 표(per_ip·minute)에 남지 않는다",
          "127.0.0.1" not in e.web.per_ip and "127.0.0.1" not in e.web.minute, (e.web.per_ip, list(e.web.minute)))

    print("  분당 (시험용 상한 5)")
    e2 = start({"trusted_proxies": ["127.0.0.1"]})
    clock = Clock()
    e2.web.clock = clock
    old = lan_server.PER_IP_MIN
    lan_server.PER_IP_MIN = 5
    try:
        got = [req(e2, "127.0.0.1", "GET", "/index.html", headers=xff("10.0.0.60")).status for _ in range(5)]
        check("XFF 10.0.0.60 다섯 번은 200", got == [200] * 5, got)
        g = req(e2, "127.0.0.1", "GET", "/index.html", headers=xff("10.0.0.60"))
        check("여섯 번째는 429", g.status == 429, g)
        g = req(e2, "127.0.0.1", "GET", "/index.html", headers=xff("10.0.0.61"))
        check("다른 사람(10.0.0.61)은 200", g.status == 200, g)
        clock.t += 61
        g = req(e2, "127.0.0.1", "GET", "/index.html", headers=xff("10.0.0.60"))
        check("1분 뒤 10.0.0.60 다시 200", g.status == 200, g)

        print("  믿을 프록시가 아닌 연결은 지금처럼 받기 고리에서")
        got = [req(e2, "10.0.0.7", "GET", "/index.html").status for _ in range(5)]
        g = req(e2, "10.0.0.7", "GET", "/index.html")
        check("프록시 아닌 10.0.0.7: 다섯 번 200, 여섯 번째는 답 없이 끊긴다", got == [200] * 5 and isinstance(g, Broken), (got, g))
        check("  그 주소는 받기 고리의 분당 표에 있다", "10.0.0.7" in e2.web.minute, list(e2.web.minute))
    finally:
        lan_server.PER_IP_MIN = old
    check("연결 수가 돌아온다", until(lambda: e2.web.conns == 0 and not e2.web.per_ip and not getattr(e2.web, "clients", {1: 1}), 5),
          (e2.web.conns, e2.web.per_ip, getattr(e2.web, "clients", None)))


# ----------------------------------------------------------------------------------------------------
# 3. 아이디 잠금은 (아이디, 주소) 쌍에
# ----------------------------------------------------------------------------------------------------

def test_id_lock_per_address():
    print("3. 아이디 잠금은 (아이디, 보낸 주소) 쌍에 (test_id_lock_per_address)")
    e = start()
    a, b = "10.0.0.1", "10.0.0.2"
    for _ in range(local_web.LOCK_LIMIT):
        login(e, a, "boss", "wrong-pw-000")
    g = login(e, a)
    check("주소 A 에서 boss 를 5번 틀리면 A 의 맞는 비밀번호도 429", g.status == 429 and g.code == "auth/too-many-requests", g)
    g = login(e, b)
    check("그동안 주소 B 에서 boss 로 맞게 로그인 → 200", g.status == 200 and (g.json() or {}).get("token"), g)
    g = login(e, a)
    check("B 가 성공해도 A 는 아직 잠김 (쌍마다)", g.status == 429, g)
    e.clock.go(61)
    g = login(e, a)
    check("60초 뒤 A 도 된다", g.status == 200, g)

    print("  비밀번호 바꾸기(/api/password)도 같은 규칙")
    c, d = "10.0.0.3", "10.0.0.4"
    tok_c = (login(e, c, "staff", STAFF_PW).json() or {}).get("token")
    tok_d = (login(e, d, "staff", STAFF_PW).json() or {}).get("token")
    for i in range(local_web.LOCK_LIMIT):
        req(e, c, "POST", "/api/password", {"current": f"wrong-cur-{i:04d}", "next": "new-pw-00001"}, bearer(tok_c))
    g = req(e, c, "POST", "/api/password", {"current": STAFF_PW, "next": "new-pw-00001"}, bearer(tok_c))
    check("주소 C 에서 5번 틀리면 C 의 맞는 현재 비밀번호도 429", g.status == 429, g)
    g = req(e, d, "POST", "/api/password", {"current": STAFF_PW, "next": "new-pw-00002"}, bearer(tok_d))
    check("주소 D 의 탭은 비밀번호를 바꿀 수 있다 → 200", g.status == 200, g)

    print("  아이디 전체 잠금 - 여러 주소에서 10분에 합쳐 30번이면 300초 (손 시계)")
    e2 = start()
    ips = ["10.2.0.1", "10.2.0.2", "10.2.0.3"]

    def ten_wrong(ip):
        for _ in range(local_web.LOCK_LIMIT):
            login(e2, ip, "boss", "wrong-pw-000")
        e2.clock.go(61)                   # 쌍 잠금(60초)이 풀린 뒤 다섯 번 더 - 이 주소는 10번째에 주소 잠금
        for _ in range(local_web.LOCK_LIMIT):
            login(e2, ip, "boss", "wrong-pw-000")
    ten_wrong(ips[0])
    ten_wrong(ips[1])
    g = login(e2, "10.2.0.9")
    check("두 주소에서 20번 틀린 뒤 네 번째 주소는 200", g.status == 200, g)
    ten_wrong(ips[2])
    g = login(e2, "10.2.0.10")
    check("세 주소에서 합쳐 30번 틀리면 다른 주소의 맞는 비밀번호도 429 '5분 뒤'",
          g.status == 429 and g.code == "auth/too-many-requests" and "5분 뒤" in (g.message or ""), g)
    check("기록에 아이디 전체 잠금 줄 (여러 주소·300초)",
          any("여러 주소" in ln and "300초" in ln and "아이디=boss" in ln for ln in log_text(e2).splitlines()), log_text(e2)[-800:])
    e2.clock.go(298)
    check("298초 뒤에도 429", login(e2, "10.2.0.11").status == 429)
    e2.clock.go(3)
    g = login(e2, "10.2.0.12")
    check("300초가 지나면 200", g.status == 200, g)
    g = login(e2, "10.2.0.12", "staff", STAFF_PW)
    check("다른 아이디(staff)는 처음부터 상관없다", g.status == 200, g)

    print("  단독 (make_server + Web, cfg 없음) 은 그대로 - 아이디 하나에 잠금")
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
    for _ in range(5):
        call(port, "POST", "/api/login", {"id": "boss", "password": "wrong-pw-000"}, tls=False)
    g = call(port, "POST", "/api/login", {"id": "boss", "password": BOSS_PW}, tls=False)
    check("단독: 5번 틀리면 429 '1분 뒤'", g.status == 429 and "1분 뒤" in (g.message or ""), g)
    check("단독: 잠금 표의 열쇠는 아이디 그대로 ('boss')", web.lockout.locked("boss"), list(web.lockout._items))


# ----------------------------------------------------------------------------------------------------
# 4. 악수 뒤 요청 마감 10초
# ----------------------------------------------------------------------------------------------------

def drip(port, head, rest, step=1.0, limit=20.0):
    """TLS 악수 뒤 head 를 한 번에, rest 를 step 초에 한 바이트씩 → (악수 끝에서 끊길 때까지 초 또는 None, 받은 글)."""
    try:
        s = tls_open(port)
    except (ssl.SSLError, OSError) as ex:
        return None, repr(ex)
    t0 = time.monotonic()
    got = b""
    try:
        if head:
            s.sendall(head)
        s.settimeout(step)
        i = 0
        while time.monotonic() - t0 < limit:
            if i < len(rest):
                s.sendall(rest[i:i + 1])
                i += 1
            try:
                b = s.recv(4096)
            except socket.timeout:
                continue
            if not b:
                return time.monotonic() - t0, got
            got += b
    except (ssl.SSLError, ConnectionError, OSError):
        return time.monotonic() - t0, got
    finally:
        try:
            s.close()
        except OSError:
            pass
    return None, got


def test_request_deadline():
    print("4. 악수 뒤 요청을 10초 안에 다 보내지 않으면 끊는다 (test_request_deadline)")
    check("REQUEST_DEADLINE = 10", getattr(lan_server, "REQUEST_DEADLINE", None) == 10, getattr(lan_server, "REQUEST_DEADLINE", None))
    e = start()
    tok = (login(e, "127.0.0.1").json() or {}).get("token")
    pc = active_pc(e, "마감", 2)
    stream = Stream(e, tok, pc)
    t_stream = time.monotonic()
    check("정상 구독이 열린다", stream.status == 200, stream.status)
    res = {}
    head_drip = b"GET /index.html HTTP/1.1\r\nHost: 127.0.0.1\r\nX-Pad: " + b"a" * 40
    body_head = (f"POST /api/login HTTP/1.1\r\nHost: 127.0.0.1:{e.wp}\r\nContent-Type: application/json\r\n"
                 f"Content-Length: 60\r\n\r\n").encode()
    ths = [threading.Thread(target=lambda: res.__setitem__("head", drip(e.wp, b"", head_drip)), daemon=True),
           threading.Thread(target=lambda: res.__setitem__("body", drip(e.wp, body_head, b"{" + b" " * 59)), daemon=True)]
    for t in ths:
        t.start()
    check("두 느린 연결이 서버에 잡혀 있다 (구독까지 3)", until(lambda: e.web.conns >= 3, 3), e.web.conns)
    times = []
    for _ in range(3):
        a = time.monotonic()
        g = req(e, "127.0.0.1", "GET", "/index.html")
        times.append((g.status, round(time.monotonic() - a, 2)))
    check("그동안 다른 요청은 정상 (2초 안에 200)", all(st == 200 and sec < 2 for st, sec in times), times)
    for t in ths:
        t.join(25)
    h_sec, h_got = res.get("head", (None, None))
    b_sec, b_got = res.get("body", (None, None))
    check("머리글을 1초에 한 바이트 → 10초 남짓에 끊긴다 (답 없이)", h_sec is not None and 8.5 <= h_sec <= 13 and not h_got,
          (h_sec, h_got))
    check("본문을 1초에 한 바이트 → 10초 남짓에 끊긴다 (답 없이)", b_sec is not None and 8.5 <= b_sec <= 13 and not b_got,
          (b_sec, b_got))
    check("느린 연결의 연결 수를 돌려준다 (구독 하나만 남는다)", until(lambda: e.web.conns == 1, 5), e.web.conns)
    left = 15.5 - (time.monotonic() - t_stream)
    if left > 0:
        time.sleep(left)
    e.store.put(f"apps/rpa/live/c1/{pc}", {"state": "busy"})
    check("정상 구독은 15초 넘게 살아 있다 (그 뒤 바뀐 현황을 받는다)",
          until(lambda: any(x.startswith("live") and "busy" in x for x in stream.events), 5), stream.events)
    stream.close()
    check("모두 닫으면 연결 수 0", nudge_until(e, pc, lambda: e.web.conns == 0 and not e.web.per_ip), (e.web.conns, e.web.per_ip))
    check("마감 타이머 표가 비었다", not getattr(e.web, "reading", {}), getattr(e.web, "reading", None))


# ----------------------------------------------------------------------------------------------------
# 5. X-Forwarded-For 없음·포트 붙은 꼴
# ----------------------------------------------------------------------------------------------------

def test_missing_xff():
    print("5. 믿을 프록시가 X-Forwarded-For 를 안 보내면 (test_missing_xff)")
    one = lan_config.parse({"listen": "10.0.0.5", "allow": ["10.0.0.0/8", "fd00::/8"], "trusted_proxies": ["10.0.0.9", "fd00::9"]})
    check("'10.0.0.7:5678' → 포트를 떼고 10.0.0.7", lan_server.client_ip("10.0.0.9", "10.0.0.7:5678", one) == "10.0.0.7",
          lan_server.client_ip("10.0.0.9", "10.0.0.7:5678", one))
    check("'[fd00::7]:443' → fd00::7", lan_server.client_ip("10.0.0.9", "[fd00::7]:443", one) == "fd00::7",
          lan_server.client_ip("10.0.0.9", "[fd00::7]:443", one))
    check("괄호 없는 IPv6 'fd00::7' 은 그대로", lan_server.client_ip("10.0.0.9", "fd00::7", one) == "fd00::7")
    check("'1.2.3.4, 10.0.0.7:80' → 오른쪽부터 10.0.0.7", lan_server.client_ip("10.0.0.9", "1.2.3.4, 10.0.0.7:80", one) == "10.0.0.7")
    for bad in ("10.0.0.7:", "10.0.0.7:abc", "10.0.0.7:123456", "evil.example:80", "[fd00::7]x", "fd00::7]:443", "[10.0.0.7]:80"):
        check(f"IP 가 아닌 글자 {bad!r} → peer (버린다)", lan_server.client_ip("10.0.0.9", bad, one) == "10.0.0.9",
              lan_server.client_ip("10.0.0.9", bad, one))

    print("  web_plain (평문 프록시 모양)")
    e = start({"trusted_proxies": ["127.0.0.1"], "web_plain": True, "public_web": ["ap.corp.local"]}, plain=True)
    https = {"X-Forwarded-Proto": "https"}
    g = req(e, "127.0.0.1", "GET", "/index.html", headers=https)
    check("X-Forwarded-Proto https 만 (XFF 없음) → 403", g.status == 403 and g.code == "forbidden", g)
    check("  안내 글은 한국어 업무 말투 (X-Forwarded-For 를 말한다)",
          "X-Forwarded-For" in (g.message or "") and (g.message or "").endswith("주십시오."), g.message)
    g = login(e, "127.0.0.1", headers=https)
    check("XFF 없는 로그인도 403 (토큰 없음)", g.status == 403 and not (g.json() or {}).get("token"), g)
    g = req(e, "127.0.0.1", "GET", "/index.html", headers=dict(https, **xff("evil.example")))
    check("읽을 수 없는 XFF(evil.example)도 403", g.status == 403, g)
    g = req(e, "127.0.0.1", "GET", "/index.html", headers=dict(https, **xff("10.0.0.5")))
    check("XFF 10.0.0.5 → 200", g.status == 200, g)
    g = login(e, "127.0.0.1", "boss", "wrong-pw-000", headers=dict(https, **xff("10.0.0.5:5678")))
    check("XFF '10.0.0.5:5678' 로 틀린 로그인 → 401", g.status == 401, g)
    text = log_text(e)
    check("기록의 주소는 포트를 뗀 10.0.0.5 (127.0.0.1 이 아니다)",
          any("로그인 실패" in ln and "주소=10.0.0.5" in ln for ln in text.splitlines())
          and not any("로그인 실패" in ln and "주소=127.0.0.1" in ln for ln in text.splitlines()), text[-600:])
    check("XFF 없음은 기록에 남긴다", any("X-Forwarded-For" in ln for ln in text.splitlines()), text[-600:])

    print("  TLS 웹 포트 - 믿을 프록시가 XFF 없이 보내도 막지 않고 60초에 한 줄 경고")
    t = start({"trusted_proxies": ["127.0.0.1"]})
    for _ in range(3):
        g = req(t, "127.0.0.1", "GET", "/index.html")
        if g.status != 200:
            break
    check("XFF 없는 요청 셋 → 모두 200", g.status == 200, g)
    warn = [ln for ln in log_text(t).splitlines() if "X-Forwarded-For" in ln]
    check("경고는 한 줄", len(warn) == 1, warn)
    t.clock.go(61)
    req(t, "127.0.0.1", "GET", "/index.html")
    warn = [ln for ln in log_text(t).splitlines() if "X-Forwarded-For" in ln]
    check("60초 뒤 다시 한 줄", len(warn) == 2, warn)
    g = req(t, "10.0.0.7", "GET", "/index.html")
    warn2 = [ln for ln in log_text(t).splitlines() if "X-Forwarded-For" in ln]
    check("프록시가 아닌 주소의 XFF 없는 요청은 경고하지 않는다", g.status == 200 and len(warn2) == 2, (g, warn2))

    print("  에이전트 포트는 그대로 (늘 소켓 주소)")
    import email.message
    x = local_server.Handler.__new__(local_server.Handler)
    x.client_address = ("10.0.0.9", 50000)
    x.server = types.SimpleNamespace(cfg=one, side="agent", peer_ip=lambda addr: str(addr[0]))
    x.headers = email.message.Message()
    x.headers["X-Forwarded-For"] = "10.0.0.7:5678"
    check("에이전트 쪽 Handler.client_ip 는 소켓 주소", x.client_ip() == "10.0.0.9", x.client_ip())


try:
    for fn in (test_allow_behind_proxy, test_proxy_per_client_limits, test_id_lock_per_address, test_request_deadline,
               test_missing_xff):
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
