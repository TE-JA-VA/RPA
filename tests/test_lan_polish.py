# -*- coding: utf-8 -*-
"""사내 서버 ④ Task 6 - ②·③ 검토에서 넘긴 서버 손질 + 악마의 대변인 전체 검증 1회차 (계획 2026-11-25-lan-4-linux Task 6).
②검-3 허용 대역 필수·받기 고리 거절 기록, ②검-4 에이전트 포트 주소별 분당 2400 (PC 별 1200 의 서명된 429 가 먼저),
②검-5 에이전트 포트 HEAD·OPTIONS 에 Date 없음, ②검-6 깊은 JSON 400, ②검-9 이름 규칙, ②검-10 proxy_only 프록시는 허용 대역 안,
③검-1 이력 지우기 시계 보호(실제 add 경로), Codex 검토 13 평문 프록시 비밀 머리글, ③검-8 이력 쓰기는 로그인 잠금 밖,
③검-9 보안 설정 마지막 값, 전1-1 2단계 등록 경쟁, 전1-2 비밀번호 변경 경쟁, 전1-4 admin-console 예약, 전1-5 라이선스 한도 범위.
경쟁은 시간에 기대지 않는다 - 잠금 앞 손잡이(Web._pause·Accounts._pause)에서 멈추게 해 순서를 강제한다.
make_lan_servers 로 두 포트를 127.0.0.1 에 포트 0 으로 띄우고 웹 서버의 peer_ip 를 바꿔 끼워 여러 주소를 흉내 낸다 (test_lan_review2 와 같은 꼴).
    D:/AX/RPA/.venv/Scripts/python.exe tests/test_lan_polish.py
"""
import dataclasses
import http.client
import json
import os
import re
import shutil
import socket
import sqlite3
import ssl
import sys
import tempfile
import threading
import time
import traceback
import types

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "firebase", "agent"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import lan_ca  # noqa: E402
import lan_config  # noqa: E402
import lan_server  # noqa: E402
import local_server  # noqa: E402
import local_store  # noqa: E402
import local_web  # noqa: E402
import login_log  # noqa: E402
import pc_registry  # noqa: E402
import totp  # noqa: E402
import web_security  # noqa: E402

fails = []
TMP = tempfile.mkdtemp(prefix="rpa_lan_polish_", dir="/tmp" if os.name == "posix" else None)
LIC = {"edition": "standalone", "company": "시험상사", "cid": "c1", "pc_id": "srv", "issued": "2026-11-25",
       "modules": {}, "features": {}, "limits": {}}
BOSS_PW, STAFF_PW = "pw-12345678", "staff-pw-0001"
GUIDS = ["11111111-2222-3333-4444-5555555555%02d" % i for i in range(20)]
SECRET = "proxy-secret-" + "x" * 40
DAY = 86400


def check(name, ok, detail=""):
    print(f"  [{'통과' if ok else '실패'}] {name}" + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


def raises_config(fn, word=None):
    try:
        fn()
    except lan_config.ConfigError as e:
        return word is None or word in str(e)
    except Exception:
        return False
    return False


def until(fn, sec):
    end = time.time() + sec
    while time.time() < end:
        if fn():
            return True
        time.sleep(0.02)
    return bool(fn())


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
    def __init__(self, err):
        super().__init__(None, {}, b"")
        self.err = err

    def __repr__(self):
        return f"<끊김 {type(self.err).__name__}: {self.err}>"


def call(port, method, path, body=None, headers=None, tls=True):
    data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8"))
    hs = dict(headers or {})
    if data is not None:
        hs.setdefault("Content-Type", "application/json")
    c = (http.client.HTTPSConnection("127.0.0.1", port, context=ctx(), timeout=15) if tls
         else http.client.HTTPConnection("127.0.0.1", port, timeout=15))
    try:
        c.request(method, path, body=data, headers=hs)
        r = c.getresponse()
        return Got(r.status, r.headers, r.read())
    except (OSError, http.client.HTTPException) as ex:
        return Broken(ex)
    finally:
        c.close()


class Clock:
    def __init__(self, t=None):
        self.t = time.time() if t is None else t

    def __call__(self):
        return self.t

    def go(self, sec):
        self.t += sec


SERVERS, RUNS = [], []
BASE = {"listen": "127.0.0.1", "names": ["localhost"], "allow": ["127.0.0.0/8", "10.0.0.0/8"]}


def start(extra=None, plain=False, clock=None, runs_db=":memory:"):
    folder = tempfile.mkdtemp(dir=TMP)
    with open(os.path.join(folder, "security.json"), "w", encoding="utf-8") as f:
        f.write('{"version":1,"totp_scope":"off","show_own_history":true}')
    store = local_server.Store(os.path.join(folder, "store.json"), volatile=local_server.VOLATILE)
    runs = local_server.Runs(runs_db)
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


def log_text(env_or_folder):
    folder = env_or_folder if isinstance(env_or_folder, str) else env_or_folder.folder
    try:
        with open(os.path.join(folder, local_server.LOG_NAME), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def log_lines(env, word):
    return [ln for ln in log_text(env).splitlines() if word in ln]


def active_pc(env, label="PC", guid_i=0):
    st = env.reg.start(label)
    rand = os.urandom(32).hex()
    env.reg.enroll(st["pc_id"], rand, GUIDS[guid_i], "PC-A", pc_registry.enroll_proof(st["token"], st["pc_id"], rand, GUIDS[guid_i], "PC-A"))
    return st["pc_id"]


def signed(env, method, path, pc, body=None):
    """에이전트 포트에 ap2 서명 요청 → (Got, 응답 서명이 맞는가)."""
    keys = env.reg.keys(pc)
    data = b"" if body is None else json.dumps(body).encode("utf-8")
    hs = local_store.sign_headers(keys[0], "agent", method, path, data, pc_id=pc)
    g = call(env.ap, method, path, body=data or None, headers=hs)
    ok = (g.headers.get(local_store.H_SIGN) or "") == local_store.response_mac(keys[0], hs[local_store.H_NONCE], g.status or 0, g.raw)
    return g, ok


def raw_request(port, data, tls=True, sec=10):
    """요청 바이트를 그대로 보내고 받은 바이트 전부."""
    s = socket.create_connection(("127.0.0.1", port), timeout=sec)
    try:
        if tls:
            s = ctx().wrap_socket(s, server_hostname="127.0.0.1")
        s.sendall(data)
        got = b""
        while True:
            try:
                b = s.recv(4096)
            except (socket.timeout, OSError):
                break
            if not b:
                break
            got += b
        return got
    finally:
        s.close()


def guard(fn):
    print(fn.__name__)
    try:
        fn()
    except Exception as ex:
        check(f"{fn.__name__} - 예외 없이 끝난다", False, f"{type(ex).__name__}: {ex}\n{traceback.format_exc()[-1500:]}")


# ----------------------------------------------------------------------------------------------------
# ②검-3 허용 대역 필수 · 받기 고리 거절 기록
# ----------------------------------------------------------------------------------------------------

def test_allow_required():
    check("listen 이 루프백이 아닌데 allow 가 비면 ConfigError('허용 대역(allow)을 적어 주십시오')",
          raises_config(lambda: lan_config.parse({"listen": "192.168.1.230"}), "허용 대역(allow)을 적어 주십시오"))
    check("allow 빈 목록도 같다", raises_config(lambda: lan_config.parse({"listen": "10.0.0.5", "allow": []}), "allow"))
    check("allow 가 있으면 된다", lan_config.parse({"listen": "192.168.1.230", "allow": ["192.168.1.0/24"]}).allowed("192.168.1.9"))
    check("루프백 listen 은 allow 없이도 된다 (같은 장비만)", lan_config.parse({"listen": "127.0.0.1"}).allow == ()
          and lan_config.parse({"listen": "::1"}).allow == ())


def test_accept_reject_logged():
    e = start({"allow": ["10.0.0.0/8"]})
    clock = Clock()
    e.web.clock = clock
    first = req(e, "192.168.9.9", "GET", "/index.html")
    check("허용 대역 밖 주소는 답 없이 닫힌다", isinstance(first, Broken), first)
    check("기록에 받기 고리 거절 줄 (까닭·주소·포트)", until(lambda: any("192.168.9.9" in ln and "허용 대역 밖" in ln and "웹" in ln
                                                           for ln in log_lines(e, "연결 거절")), 3), log_text(e)[-500:])
    for i in range(15):
        req(e, f"192.168.9.{i + 10}", "GET", "/index.html")
    lines = [ln for ln in log_lines(e, "연결 거절") if "허용 대역 밖" in ln and "건 더" not in ln]
    check("16번 거절해도 같은 까닭은 60초에 10줄", len(lines) == 10, len(lines))
    clock.go(61)
    req(e, "192.168.9.99", "GET", "/index.html")
    check("60초 뒤 다시 적고, 생략한 수를 한 줄로 (6건 더)",
          until(lambda: any("192.168.9.99" in ln for ln in log_lines(e, "연결 거절")), 3)
          and any("6건 더" in ln for ln in log_lines(e, "연결 거절")), log_text(e)[-600:])
    # 주소별 분당 - 까닭이 따로 센다
    old = lan_server.PER_IP_MIN
    lan_server.PER_IP_MIN = 3
    try:
        got = [req(e, "10.0.0.7", "GET", "/index.html") for _ in range(4)]
    finally:
        lan_server.PER_IP_MIN = old
    check("웹 포트 주소별 분당 상한(시험 3)을 넘으면 닫힌다", [g.status for g in got[:3]] == [200] * 3 and isinstance(got[3], Broken), got)
    check("분당 거절도 까닭과 함께 기록", until(lambda: any("10.0.0.7" in ln and "분당" in ln for ln in log_lines(e, "연결 거절")), 3),
          log_text(e)[-500:])


# ----------------------------------------------------------------------------------------------------
# ②검-4 에이전트 포트 주소별 분당 · PC 별 서명된 429
# ----------------------------------------------------------------------------------------------------

def test_agent_rate_vs_pc_429():
    check("상수: 에이전트 포트 주소별 분당 2400, 웹 600 그대로, PC 별 1200",
          (getattr(lan_server, "PER_IP_MIN_AGENT", None), lan_server.PER_IP_MIN, local_server.PC_REQ_MIN) == (2400, 600, 1200))
    check("에이전트 포트 주소별 상한이 PC 별 상한보다 크다 (서명된 429 가 먼저 닿는다)",
          getattr(lan_server, "PER_IP_MIN_AGENT", 0) > local_server.PC_REQ_MIN)
    e = start()
    pc = active_pc(e, "속도", 1)
    saved = (local_server.PC_REQ_MIN, lan_server.PER_IP_MIN, getattr(lan_server, "PER_IP_MIN_AGENT", None))
    local_server.PC_REQ_MIN, lan_server.PER_IP_MIN, lan_server.PER_IP_MIN_AGENT = 6, 3, 12     # 비율은 그대로 줄인 시험 상한
    try:
        got = [signed(e, "GET", f"/db/apps/rpa/commands/c1/{pc}.json", pc) for _ in range(7)]
    finally:
        local_server.PC_REQ_MIN, lan_server.PER_IP_MIN = saved[0], saved[1]
        if saved[2] is not None:
            lan_server.PER_IP_MIN_AGENT = saved[2]
    statuses = [g.status for g, _ in got]
    check("PC 별 상한(시험 6)까지는 답한다 (웹 포트 상한 3 에 걸리지 않는다)", statuses[:6] == [200] * 6, statuses)
    g, ok = got[6]
    check("일곱 번째는 연결이 닫히지 않고 서명된 429", g.status == 429 and ok, (g, ok))


# ----------------------------------------------------------------------------------------------------
# ②검-5 HEAD·OPTIONS · ②검-6 깊은 JSON
# ----------------------------------------------------------------------------------------------------

def test_head_no_date():
    e = start()
    for m in ("HEAD", "OPTIONS"):
        raw = raw_request(e.ap, f"{m} /db/x.json HTTP/1.1\r\nHost: 127.0.0.1:{e.ap}\r\n\r\n".encode())
        head = raw.split(b"\r\n\r\n", 1)[0].decode("latin-1")
        check(f"에이전트 포트 {m} → 답은 오지만 Date 머리글이 없다", head.startswith("HTTP/") and "\ndate:" not in head.lower(), head)
    # 단독(이 PC 의 127.0.0.1 서버) 응답 모양은 그대로
    folder = tempfile.mkdtemp(dir=TMP)
    store = local_server.Store(os.path.join(folder, "store.json"))
    runs = local_server.Runs(":memory:")
    RUNS.append(runs)
    srv = local_server.make_server(store, runs, LIC, ("k" * 43, "r" * 43), port=0, folder=folder)
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    SERVERS.append(srv)
    raw = raw_request(srv.server_address[1], b"HEAD / HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n", tls=False)
    head = raw.split(b"\r\n\r\n", 1)[0].decode("latin-1")
    check("단독 HEAD 는 지금 그대로 (http.server 의 501, Date 있음)", head.startswith("HTTP/1.0 501") and "\ndate:" in head.lower(), head)


def test_deep_json_400():
    e = start()
    deep = b"[" * 200000 + b"]" * 200000
    g = call(e.ap, "POST", "/enroll", deep, headers={"Content-Type": "application/json"})
    check("/enroll 에 깊게 겹친 JSON → 400 (500 아님)", g.status == 400, g)
    check("기록에 '요청 처리 오류' 줄이 없다", "요청 처리 오류" not in log_text(e), log_text(e)[-300:])


# ----------------------------------------------------------------------------------------------------
# ②검-9 이름 규칙 · ②검-10 프록시는 허용 대역 안
# ----------------------------------------------------------------------------------------------------

def test_names_rules():
    L = {"listen": "192.168.1.230", "allow": ["192.168.1.0/24"]}
    for bad in ("kr", "nt", "a..b", "-x.corp", "nt.", ".nt.corp", "x_y.corp", "8.8.8.8", "169.254.1.1", "2001:4860::1"):
        check(f"names {bad!r} 거절", raises_config(lambda: lan_config.parse(dict(L, names=[bad]))))
    good = ("nt.corp.local", "AP.Corp.Local", "localhost", "192.168.1.230", "10.0.0.5", "fd00::5")
    c = lan_config.parse(dict(L, names=list(good)))
    check("점이 든 이름·localhost·사설 IP 는 받는다 (이름은 소문자로)",
          set(c.names) == {"192.168.1.230", "nt.corp.local", "ap.corp.local", "localhost", "10.0.0.5", "fd00::5"}, c.names)
    for n in c.names:
        check(f"받은 이름 {n!r} 은 인증서 발급(lan_ca)도 받는다", lan_ca._ip(n) is not None or lan_ca._dns(n) == n)


def test_proxy_outside_allow():
    L = {"listen": "10.0.0.5", "allow": ["10.0.0.0/16"]}
    check("proxy_only 인데 믿을 프록시가 allow 밖 → ConfigError",
          raises_config(lambda: lan_config.parse(dict(L, trusted_proxies=["10.1.0.0/16"], proxy_only=True)), "trusted_proxies"))
    check("proxy_only 인데 프록시 대역이 allow 보다 넓으면 → ConfigError",
          raises_config(lambda: lan_config.parse(dict(L, trusted_proxies=["10.0.0.0/8"], proxy_only=True))))
    check("allow 안의 프록시는 된다", lan_config.parse(dict(L, trusted_proxies=["10.0.0.9"], proxy_only=True)).proxy_only)
    check("루프백 프록시도 된다", lan_config.parse(dict(L, trusted_proxies=["127.0.0.1"], proxy_only=True)).proxy_only)
    check("proxy_only 가 아니면 전처럼 (믿을 프록시 표만)", lan_config.parse(dict(L, trusted_proxies=["10.1.0.0/16"])).is_proxy("10.1.2.3"))


# ----------------------------------------------------------------------------------------------------
# ③검-1 이력 지우기 시계 보호 (실제 add 경로)
# ----------------------------------------------------------------------------------------------------

def test_purge_clock_jump():
    t0 = time.time()
    clock = Clock(t0)
    e = start(clock=clock)
    g = login(e, "10.0.0.5", "boss", "wrong-pw-1234")
    check("준비: 로그인 실패 한 줄 (지금)", g.status == 401 and len(e.ui.login_log.query(limit=200)) == 1, g)
    db = sqlite3.connect(os.path.join(e.folder, login_log.LOGINS_NAME))
    try:
        meta = dict(db.execute("SELECT k, v FROM meta").fetchall())
    finally:
        db.close()
    check("정상으로 끝난 정비 시각이 meta 표에", abs(meta.get("last_purge", 0) - int(t0 * 1000)) < 2000, meta)
    clock.go(2 * 365 * DAY)                          # 시계가 2년 앞으로 뛴다
    e.ui.lockout = local_web.Lockout(clock=clock)    # (잠금 셈은 이 시험과 상관없다)
    g = login(e, "10.0.0.5", "boss", "wrong-pw-1234")
    rows = e.ui.login_log.query(limit=200)
    check("2년 뛴 시계로 로그인 실패 한 번(add) → 옛 줄이 남는다", g.status == 401 and len(rows) == 2, (g, rows))
    check("기록에 정비를 건너뛴 까닭 한 줄 (시계)", any("시계" in ln for ln in log_lines(e, "로그인 이력")), log_text(e)[-500:])
    # 시계가 30일 넘게 뒤로 가도 지우지 않는다
    clock2 = Clock(t0)
    path = os.path.join(TMP, "back", login_log.LOGINS_NAME)
    ll = login_log.LoginLog(path, clock=clock2)
    ll.add("ok", None, "10.0.0.5", "Edge · Windows")
    clock2.go(-40 * DAY)
    ll._purged = None                                # 하루 한 번 셈은 이 시험과 상관없다
    ll.add("bad_password", None, "10.0.0.5", "Edge · Windows")
    clock2.go(80 * DAY + 400 * DAY)                  # 이번에는 마지막 정비(t0)보다 440일 뒤 - 이것도 건너뛴다
    ll._purged = None
    ll.add("bad_password", None, "10.0.0.5", "Edge · Windows")
    check("시계가 뒤로 40일·앞으로 440일 뛰어도 지우지 않는다", len(ll.query(limit=200)) == 3, ll.query(limit=200))
    ll.close()
    # 보통은 그대로 지운다 (366일 - 400일 안)
    clock3 = Clock(t0)
    ll = login_log.LoginLog(os.path.join(TMP, "normal", login_log.LOGINS_NAME), clock=clock3)
    ll.add("ok", None, "10.0.0.5", "Edge · Windows")
    clock3.go(366 * DAY)
    ll.add("ok", None, "10.0.0.6", "Edge · Windows")
    rows = ll.query(limit=200)
    check("366일 뒤 add → 1년 지난 줄은 지운다 (정비 확인 → 넣기)", [r["ip"] for r in rows] == ["10.0.0.6"], rows)
    ll.close()


# ----------------------------------------------------------------------------------------------------
# Codex 검토 13 평문 프록시 비밀 머리글
# ----------------------------------------------------------------------------------------------------

def test_plain_proxy_secret():
    P = {"listen": "10.0.0.5", "allow": ["10.0.0.0/8"], "trusted_proxies": ["127.0.0.1"], "web_plain": True}
    check("web_plain 인데 proxy_secret 이 없으면 ConfigError", raises_config(lambda: lan_config.parse(P), "proxy_secret"))
    check("proxy_secret 31자 → ConfigError", raises_config(lambda: lan_config.parse(dict(P, proxy_secret="a" * 31)), "proxy_secret"))
    check("proxy_secret 에 빈칸 → ConfigError", raises_config(lambda: lan_config.parse(dict(P, proxy_secret="a" * 20 + " " + "b" * 20))))
    c = lan_config.parse(dict(P, proxy_secret=SECRET))
    check("32자 이상이면 된다", c.web_plain and c.proxy_secret == SECRET)
    check("설정의 repr 에 비밀 값이 실리지 않는다", SECRET not in repr(c), repr(c)[:200])
    e = start({"trusted_proxies": ["127.0.0.1"], "web_plain": True, "public_web": ["ap.corp.local"], "proxy_secret": SECRET}, plain=True)
    fwd = {"X-Forwarded-Proto": "https", "X-Forwarded-For": "10.0.0.30"}
    g = req(e, "127.0.0.1", "GET", "/index.html", headers=fwd)
    check("X-Autopilot-Proxy 가 없으면 403", g.status == 403, g)
    g = req(e, "127.0.0.1", "GET", "/index.html", headers=dict(fwd, **{"X-Autopilot-Proxy": SECRET[:-1] + "y"}))
    check("값이 틀리면 403", g.status == 403, g)
    g = req(e, "127.0.0.1", "POST", "/api/login", {"id": "boss", "password": BOSS_PW}, fwd)
    check("로그인도 머리글 없으면 403 (토큰 없음)", g.status == 403 and not (g.json() or {}).get("token"), g)
    g = req(e, "127.0.0.1", "GET", "/index.html", headers=dict(fwd, **{"X-Autopilot-Proxy": SECRET}))
    check("맞는 값이면 200", g.status == 200 and b"<title>" in g.raw, g)
    check("기록에 비밀 값이 없다", SECRET not in log_text(e))


# ----------------------------------------------------------------------------------------------------
# ③검-8 이력 쓰기는 로그인 잠금 밖 · ③검-9 보안 설정 마지막 값
# ----------------------------------------------------------------------------------------------------

def test_login_log_outside_lock():
    e = start()
    path = os.path.join(e.folder, login_log.LOGINS_NAME)
    real_add = e.ui.login_log.add
    in_add, go_on, seen = threading.Event(), threading.Event(), {}

    def spy(*a, **k):
        if a and a[0] == "bad_password" and "lock_free" not in seen:
            seen["lock_free"] = not e.ui._login_lock.locked()      # 이력을 쓰는 때 로그인 잠금이 비어 있나
            in_add.set()
            go_on.wait(30)                                          # A 를 이력 쓰기 바로 앞에 세워 둔다 (순서를 손잡이로)
        return real_add(*a, **k)
    e.ui.login_log.add = spy
    blocker = sqlite3.connect(path, timeout=0)
    blocker.execute("BEGIN IMMEDIATE")              # 다른 연결이 이력 DB 의 쓰기 잠금을 쥔다
    try:
        box = {}
        t = threading.Thread(target=lambda: box.setdefault("a", login(e, "10.0.0.5", "staff", "wrong-pw-9999")), daemon=True)
        t.start()
        check("A(틀린 비밀번호)가 이력 쓰기에 들어갔다", in_add.wait(15))
        check("A 의 이력 쓰기는 로그인 잠금을 놓은 뒤", seen.get("lock_free") is True, seen)
        t0 = time.time()
        g = login(e, "10.0.0.6", "boss", BOSS_PW)
        took = time.time() - t0
        check("A 가 이력 쓰기에 머무는 동안 다른 계정 B 의 로그인이 2초 안에 끝난다 (B 의 이력 쓰기도 1초에 포기)",
              g.status == 200 and took < 2.0, (g, took))
        go_on.set()
        t.join(15)
        check("A 는 401 (이력을 못 써도 로그인 답은 그대로)", (box.get("a") or Got(None, {}, b"")).status == 401, box)
        check("못 쓴 이력은 서버 기록에 종류만 한 줄", "로그인 이력 쓰기 오류: OperationalError" in log_text(e), log_text(e)[-300:])
    finally:
        go_on.set()
        blocker.rollback()
        blocker.close()
    p1 = os.path.join(TMP, "t1", login_log.LOGINS_NAME)
    db = login_log.LoginLog(p1)
    db._purged = time.time()                         # 하루 한 번 정비는 이 확인과 상관없다 (넣기 한 번의 기다림만 잰다)
    try:
        blocker = sqlite3.connect(p1, timeout=0)
        blocker.execute("BEGIN IMMEDIATE")
        t0 = time.time()
        try:
            db.add("ok", None, "10.0.0.5", "x")
            err = None
        except sqlite3.OperationalError as ex:
            err = ex
        took = time.time() - t0
        blocker.rollback()
        blocker.close()
        check("잠긴 이력 DB 에 쓰기는 1초 안팎에 포기한다 (10초가 아니다)", err is not None and took < 2.5, (err, took))
    finally:
        db.close()


def test_security_last_value():
    folder = tempfile.mkdtemp(dir=TMP)
    path = os.path.join(folder, web_security.SECURITY_NAME)
    sec = web_security.Security(path)
    sec.set(totp_scope="all")
    check("읽은 값 all", sec.get()["totp_scope"] == "all")
    os.replace(path, path + ".moved")
    os.mkdir(path)                                    # 잠깐 못 읽는 자리 (OSError)
    check("잠깐 못 읽으면 마지막으로 읽은 값(all) - 기본값 admin 이 아니다", sec.get()["totp_scope"] == "all", sec.get())
    fresh = web_security.Security(path)
    check("처음부터 못 읽으면 기본값", fresh.get() == dict(web_security.DEFAULT), fresh.get())
    os.rmdir(path)
    check("파일이 없어지면 기본값 (없는 것은 못 읽은 것이 아니다)", sec.get() == dict(web_security.DEFAULT), sec.get())


# ----------------------------------------------------------------------------------------------------
# 전1-1 2단계 등록 경쟁 · 전1-2 비밀번호 변경 경쟁
# ----------------------------------------------------------------------------------------------------

class Pause:
    """잠금 앞 손잡이 - stage 의 첫 부름만 release 가 될 때까지 세운다 (그 뒤 부름은 그냥 지나간다)."""

    def __init__(self, stage, action=None):
        self.stage, self.action = stage, action
        self.reached, self.release = threading.Event(), threading.Event()
        self.used = False

    def __call__(self, stage):
        if stage != self.stage or self.used:
            return
        self.used = True
        if self.action is not None:
            self.action()
            return
        self.reached.set()
        self.release.wait(30)


def code_now(secret, clock):
    return totp.code_at(secret, totp.step_of(clock()))


def test_mfa_enable_after_session_closed():
    e = start()
    ip = "10.0.0.5"
    ta = (login(e, ip, "staff", STAFF_PW).json() or {}).get("token")
    tb = (login(e, ip, "staff", STAFF_PW).json() or {}).get("token")
    sa = (req(e, ip, "POST", "/api/mfa/setup", {}, bearer(ta)).json() or {}).get("secret")
    sb = (req(e, ip, "POST", "/api/mfa/setup", {}, bearer(tb)).json() or {}).get("secret")
    check("두 세션이 각각 등록 시작", bool(sa and sb and sa != sb), (sa, sb))
    pause = Pause("mfa_enable")
    e.ui._pause = pause
    box = {}
    t = threading.Thread(target=lambda: box.setdefault("b", req(e, ip, "POST", "/api/mfa/enable", {"code": code_now(sb, e.clock)},
                                                                  bearer(tb))), daemon=True)
    t.start()
    check("B 가 확인을 마치고 로그인 잠금 앞에서 멈췄다", pause.reached.wait(15))
    ga = req(e, ip, "POST", "/api/mfa/enable", {"code": code_now(sa, e.clock)}, bearer(ta))
    check("그동안 A 가 2단계를 켠다 (B 세션은 닫힌다)", ga.status == 200 and len((ga.json() or {}).get("recovery") or []) == 8, ga)
    pause.release.set()
    t.join(15)
    gb = box.get("b") or Got(None, {}, b"")
    check("B 의 enable 은 잠금 안에서 세션을 다시 보고 401", gb.status == 401, gb)
    check("계정의 2단계 비밀 값은 A 것 그대로", e.ui.accounts.mfa_secret("staff") == sa)
    e.ui._pause = None


def test_mfa_enable_changed_since_setup():
    e = start()
    ip = "10.0.0.5"
    tok = (login(e, ip, "staff", STAFF_PW).json() or {}).get("token")
    s1 = (req(e, ip, "POST", "/api/mfa/setup", {}, bearer(tok)).json() or {}).get("secret")
    s2 = totp.new_secret()
    e.ui.accounts.mfa_enable("staff", s2, code_now(s2, e.clock), e.clock())     # 다른 길(설정 창·다른 프로세스)로 2단계가 바뀜
    g = req(e, ip, "POST", "/api/mfa/enable", {"code": code_now(s1, e.clock)}, bearer(tok))
    check("등록 시작 뒤 다른 길로 2단계가 바뀌면 409 '다른 곳에서 2단계 설정이 바뀌었습니다'",
          g.status == 409 and "다른 곳에서 2단계 설정이 바뀌었습니다" in (g.message or ""), g)
    check("계정의 비밀 값은 바뀐 것(s2) 그대로", e.ui.accounts.mfa_secret("staff") == s2)
    acc = local_web.Accounts(os.path.join(tempfile.mkdtemp(dir=TMP), "a.json"))
    acc.set("u1", "pw-12345678", "viewer")
    mark = acc.mfa_mark("u1")
    sx = totp.new_secret()
    acc.mfa_enable("u1", sx, totp.code_at(sx, totp.step_of(time.time())), time.time())
    try:
        sy = totp.new_secret()
        acc.mfa_enable("u1", sy, totp.code_at(sy, totp.step_of(time.time())), time.time(), expect=mark)
        raised = False
    except local_web.MfaChanged:
        raised = True
    check("Accounts.mfa_enable(expect=) 는 표시가 다르면 MfaChanged", raised and acc.mfa_secret("u1") == sx)


def test_change_password_race_admin_reset():
    e = start()
    ip = "10.0.0.5"
    tok = (login(e, ip, "staff", STAFF_PW).json() or {}).get("token")
    reset_pw = "admin-reset-pw-01"
    e.ui.accounts._pause = Pause("change_password",
                                 action=lambda: e.ui.accounts.set("staff", reset_pw, "viewer", must_change=True))
    g = req(e, ip, "POST", "/api/password", {"current": STAFF_PW, "next": "my-new-password-1"}, bearer(tok))
    e.ui.accounts._pause = None
    check("검증과 저장 사이에 관리자 초기화 → 변경 거절 ('비밀번호가 방금 바뀌었습니다')",
          g.status in (401, 403) and "비밀번호가 방금 바뀌었습니다" in (g.message or ""), g)
    got = e.ui.accounts.verify("staff", reset_pw)
    check("초기화한 비밀번호와 must_change 그대로", got is not None and got["must_change"] is True, got)
    check("새 비밀번호로는 들어가지 못한다", e.ui.accounts.verify("staff", "my-new-password-1") is None)
    acc = local_web.Accounts(os.path.join(tempfile.mkdtemp(dir=TMP), "a.json"))
    acc.set("u1", "pw-12345678", "viewer")
    acc._pause = Pause("change_password", action=lambda: acc.set("u1", "reset-pw-1234", "viewer", must_change=True))
    try:
        acc.change_password("u1", "pw-12345678", "next-pw-12345")
        err = None
    except local_web.WrongPassword as ex:
        err = str(ex)
    check("Accounts.change_password 는 WrongPassword", err is not None and "방금 바뀌었습니다" in err, err)


# ----------------------------------------------------------------------------------------------------
# 전1-4 admin-console 예약 · 전1-5 라이선스 한도 범위
# ----------------------------------------------------------------------------------------------------

def test_reserved_admin_console():
    acc = local_web.Accounts(os.path.join(tempfile.mkdtemp(dir=TMP), "a.json"))
    for fn in (lambda: acc.add("admin-console", "pw-1234567890", "admin"), lambda: acc.set("Admin-Console", "pw-1234567890", "admin")):
        try:
            fn()
            err = None
        except ValueError as ex:
            err = str(ex)
        check("로컬 계정 admin-console 거절 ('쓸 수 없는 아이디입니다')", err is not None and "쓸 수 없는 아이디입니다" in err, err)
    e = start()
    tok = (login(e, "10.0.0.5").json() or {}).get("token")
    g = req(e, "10.0.0.5", "POST", "/api/accounts", {"id": "admin-console", "password": "pw-1234567890", "role": "viewer"}, bearer(tok))
    check("웹 계정 추가도 400", g.status == 400 and "쓸 수 없는 아이디입니다" in (g.message or ""), g)
    with open(os.path.join(ROOT, "firebase", "web", "app.js"), encoding="utf-8") as f:
        js = f.read()
    uses = [ln.strip() for ln in js.splitlines() if "CONSOLE_UID" in ln and "import" not in ln]
    check("app.js 의 콘솔 계정 처리는 모두 일반 버전(!STANDALONE)에서만",
          bool(uses) and all("isConsole(" in ln or "!STANDALONE" in ln for ln in uses), uses)


def test_server_phone_pair_404():
    """Task 8 넘김: 사내 서버 묶음에는 local_phone 이 없다 - 페어링 창구가 import 전에 휴대폰 창구가 없음을 보고 404 (500 이 아니다)."""
    e = start()
    tok = (login(e, "10.0.0.5").json() or {}).get("token")
    saved = sys.modules.get("local_phone", "없음")
    sys.modules["local_phone"] = None                      # import local_phone → ImportError (서버 묶음 흉내)
    try:
        for method, path, body in (("POST", "/api/phone-pair", {"label": "김 휴대폰"}), ("GET", "/api/phone-pair", None),
                                   ("DELETE", "/api/phone-pair", None), ("GET", "/api/phones", None),
                                   ("POST", "/api/phones/ab12", {"label": "x"}), ("DELETE", "/api/phones/ab12", None)):
            g = req(e, "10.0.0.5", method, path, body, bearer(tok))
            check(f"사내 서버 {method} {path} → 404 '이 서버에서는 휴대폰 페어링을 쓰지 않습니다'",
                  g.status == 404 and "이 서버에서는 휴대폰 페어링을 쓰지 않습니다" in (g.message or ""), g)
    finally:
        if saved == "없음":
            sys.modules.pop("local_phone", None)
        else:
            sys.modules["local_phone"] = saved


def test_server_edition_test_build():
    """Task 8 넘김: 사내 서버 묶음에는 edition 모듈이 없다 - edition.js 의 시험용 빌드 표시는 묶음 manifest.json 의 test_build 로."""
    saved, old = sys.modules.get("edition", "없음"), getattr(local_web, "SERVER_MANIFEST", None)
    sys.modules["edition"] = None
    d = tempfile.mkdtemp(dir=TMP)
    try:
        check("local_web.SERVER_MANIFEST 는 app/ 옆의 manifest.json",
              old == os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(local_web.__file__))), "manifest.json"), old)
        for label, doc, want in (("kind server·test_build true", {"kind": "server", "test_build": True}, True),
                                 ("kind server·test_build false", {"kind": "server", "test_build": False}, False),
                                 ("kind 없음", {"test_build": True}, False), ("파일 없음", None, False),
                                 ("깨진 파일", "{", False)):
            p = os.path.join(d, label.replace(" ", "_").replace("·", "_") + ".json")
            if doc is not None:
                with open(p, "w", encoding="utf-8") as f:
                    f.write(doc if isinstance(doc, str) else json.dumps(doc))
            local_web.SERVER_MANIFEST = p
            js = local_web.edition_js().decode("ascii")
            check(f"edition 모듈 없음 + {label} → TEST_BUILD = {'true' if want else 'false'}",
                  f"TEST_BUILD = {'true' if want else 'false'};" in js and 'EDITION = "standalone"' in js, js)
    finally:
        local_web.SERVER_MANIFEST = old
        if saved == "없음":
            sys.modules.pop("edition", None)
        else:
            sys.modules["edition"] = saved


def test_make_license_limits_range():
    import make_license
    import rpa_status
    with open(os.path.join(ROOT, "firebase", "agent", "agent.py"), encoding="utf-8") as f:
        m = re.search(r"^SCHEDULE_LIMIT_MAX\s*=\s*(\d+)", f.read(), re.M)
    check("발급 상한이 PC 쪽 상수와 같다 (presets·parallel·schedule)",
          (make_license.PRESETS_RANGE, make_license.PARALLEL_RANGE, make_license.SCHEDULE_RANGE)
          == ((rpa_status.PRESET_MIN, rpa_status.PRESET_MAX), (rpa_status.PARALLEL_MIN, rpa_status.PARALLEL_MAX),
              (0, int(m.group(1)) if m else -1)),
          (make_license.PRESETS_RANGE, make_license.PARALLEL_RANGE, make_license.SCHEDULE_RANGE))
    info = {"company": "시험상사", "cid": "c1"}
    pc = "0123456789abcdef"

    def try_limits(**kw):
        try:
            return make_license.build_body(pc, dict(info, limits=kw))
        except ValueError:
            return None
    for k, bad in (("presets", 0), ("presets", 1), ("presets", 51), ("parallel", 0), ("parallel", 17), ("schedule", 13), ("schedule", -1)):
        check(f"limits.{k} {bad} 거절", try_limits(**{k: bad}) is None)
    for k, ok in (("presets", 2), ("presets", 50), ("parallel", 1), ("parallel", 16), ("schedule", 0), ("schedule", 12), ("presets", None)):
        b = try_limits(**{k: ok})
        check(f"limits.{k} {ok} 발급", b is not None and b["limits"][k] == (ok if not (k == "schedule" and ok is None) else 2), b)
    req_doc = {"server_id": "a" * 32, "seat_pub": "b" * 64}
    try:
        make_license.build_server_body(req_doc, dict(info, seats=3, limits={"presets": 51}))
        srv_ok = False
    except ValueError:
        srv_ok = True
    check("서버 라이선스도 같은 범위 검사", srv_ok)


try:
    print("②·③ 손질과 전체 검증 1회차 (test_lan_polish)")
    for t in (test_allow_required, test_accept_reject_logged, test_agent_rate_vs_pc_429, test_head_no_date, test_deep_json_400,
              test_names_rules, test_proxy_outside_allow, test_purge_clock_jump, test_plain_proxy_secret, test_login_log_outside_lock,
              test_security_last_value, test_mfa_enable_after_session_closed, test_mfa_enable_changed_since_setup,
              test_change_password_race_admin_reset, test_reserved_admin_console, test_make_license_limits_range,
              test_server_phone_pair_404, test_server_edition_test_build):
        guard(t)
finally:
    for s in SERVERS:
        try:
            s.shutdown()
            s.server_close()
        except Exception:
            pass
    for r in RUNS:
        try:
            r.close()
        except Exception:
            pass
    shutil.rmtree(TMP, ignore_errors=True)

print(f"\n실패: {len(fails)}" + (f" ({', '.join(fails)})" if fails else ""))
sys.exit(1 if fails else 0)
