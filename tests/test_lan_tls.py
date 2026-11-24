# -*- coding: utf-8 -*-
"""사내 서버 ② Task 4 - 두 포트(웹 8443·에이전트 8444) TLS, 서로의 길 막기, Host 를 설정 목록으로,
서명 틀림·등록 증명 틀림은 주소 거절로, 서명 없는 답엔 서버 시각(Date) 없음, 등록 글에 인증 기관
(계획 2026-11-24-lan-2-network Task 4, 설계 6.3).
Task 2 의 인증 기관으로 127.0.0.1·localhost 서버 인증서를 만들고 make_lan_servers 로 두 포트를 포트 0 으로 띄운다.
클라이언트는 우리 인증 기관만 믿는 ssl.create_default_context(cadata=…) + http.client (프록시 없이).
윈도우·리눅스(WSL) 둘 다 같은 파일로 돈다.
    D:/AX/RPA/.venv/Scripts/python.exe tests/test_lan_tls.py
    wsl.exe -d Ubuntu -e python3 /mnt/d/AX/RPA_StandAlone/tests/test_lan_tls.py
"""
import dataclasses
import email.message
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
import local_store  # noqa: E402
import local_web  # noqa: E402
import pc_registry  # noqa: E402
import lan_server  # noqa: E402

fails = []
TMP = tempfile.mkdtemp(prefix="rpa_lan_tls_")
LIC = {"edition": "standalone", "company": "시험상사", "cid": "c1", "pc_id": "srv", "issued": "2026-11-24",
       "modules": {}, "features": {}, "limits": {}}
BOSS_PW = "pw-12345678"
GUIDS = ["11111111-2222-3333-4444-5555555555%02d" % i for i in range(10)]
LIVE = "/db/apps/rpa/live/c1/{}.json"


def check(name, ok, detail=""):
    print(f"  [{'통과' if ok else '실패'}] {name}" + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


def pending(name, why):
    print(f"  [보류] {name}  - {why}")


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


def ctx(ca=None):
    return ssl.create_default_context(cadata=ca or CA_PEM)


class Got:
    def __init__(self, status, headers, raw):
        self.status, self.headers, self.raw = status, headers, raw

    def json(self):
        try:
            return json.loads(self.raw) if self.raw else None
        except ValueError:
            return None

    def __repr__(self):
        return f"<{self.status} {self.raw[:200]!r}>"


def call(port, method, path, body=None, headers=None, tls=True, ca=None):
    """요청 하나 → Got. headers 에 Host 가 있으면 그것을 싣는다 (http.client 는 자기 Host 를 붙이지 않는다).
    ca 는 믿을 인증 기관 글 (없으면 우리 것 CA_PEM)."""
    data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8"))
    hs = dict(headers or {})
    if data is not None:
        hs.setdefault("Content-Type", "application/json")
    c = (http.client.HTTPSConnection("127.0.0.1", port, context=ctx(ca), timeout=10) if tls
         else http.client.HTTPConnection("127.0.0.1", port, timeout=10))
    try:
        c.request(method, path, body=data, headers=hs)
        r = c.getresponse()
        return Got(r.status, r.headers, r.read())
    finally:
        c.close()


def signed(port, method, path, keys, pc, body=None, role="agent", host=None, key=None):
    """ap2 서명 요청 → (Got, 응답 서명이 맞는가)."""
    data = b"" if body is None and method in ("GET", "DELETE") else json.dumps(body).encode("utf-8")
    k = key or keys[local_store.ROLES.index(role)]
    hs = local_store.sign_headers(k, role, method, path, data, pc_id=pc)
    if host:
        hs["Host"] = host
    g = call(port, method, path, body=data or None, headers=hs)
    ok = (g.headers.get(local_store.H_SIGN) or "") == local_store.response_mac(keys[local_store.ROLES.index(role)],
                                                                              hs[local_store.H_NONCE], g.status, g.raw)
    return g, ok


def enroll_raw(port, start, rand, guid, host="PC-A", proof=None):
    """등록 요청을 손으로 (pc_registry.enroll_proof·derive_keys) → (Got, 열쇠 둘, 응답 서명이 맞는가)."""
    nonce = os.urandom(16).hex()
    pc, token = start["pc"], start["token"]
    keys = pc_registry.derive_keys(token, rand)
    body = {"v": 1, "pc": pc, "rand": rand, "guid": guid, "host": host, "nonce": nonce,
            "proof": proof or pc_registry.enroll_proof(token, pc, rand, guid, host)}
    g = call(port, "POST", "/enroll", body)
    return g, keys, (g.headers.get(local_store.H_SIGN) or "") == local_store.response_mac(keys[0], nonce, g.status, g.raw)


def closed_without_reply(port, data=b"GET /index.html HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n", sec=8):
    """평문을 보내면 HTTP 답 없이 닫히는가."""
    with socket.create_connection(("127.0.0.1", port), timeout=sec) as s:
        s.sendall(data)
        s.settimeout(sec)
        got = b""
        try:
            while True:
                b = s.recv(4096)
                if not b:
                    break
                got += b
        except socket.timeout:
            return False
        except (ConnectionError, OSError):
            pass
    return not got.startswith(b"HTTP/")


def refused(port):
    raw = socket.create_connection(("127.0.0.1", port), timeout=5)
    try:
        s = ctx().wrap_socket(raw, server_hostname="127.0.0.1")
    except (ssl.SSLError, ConnectionError, OSError):
        raw.close()
        return True
    s.close()
    return False


# --- 서버 둘 ---
SERVERS, RUNS = [], []


def start(cfg_data=None, web_dir=WEB_DIR, cert=None, key=None, ca_pem=None):
    """두 포트를 띄운다. cert·key·ca_pem 을 주면 그 인증서로 (다른 인증 기관 시험), 아니면 우리 것."""
    cert, key, ca_pem = cert or CERT, key or KEY, ca_pem or CA_PEM
    folder = tempfile.mkdtemp(dir=TMP)
    store = local_server.Store(os.path.join(folder, "store.json"), volatile=local_server.VOLATILE)
    runs = local_server.Runs(":memory:")
    RUNS.append(runs)
    reg = pc_registry.Registry(os.path.join(folder, "pcs.json"), seats=20)
    web = local_web.Web(store, runs, LIC, folder, web_dir, registry=reg)
    web.accounts.set("boss", BOSS_PW, "admin")
    cfg = lan_config.parse(cfg_data or {"listen": "127.0.0.1", "names": ["localhost"], "allow": ["127.0.0.0/8"]})
    cfg = dataclasses.replace(cfg, web_port=0, agent_port=0)      # 포트 0 - make_lan_servers 가 묶인 포트로 고쳐 쓴다
    w, a = lan_server.make_lan_servers(store, runs, LIC, reg, web, cfg, cert, key, ca_pem)
    for s in (w, a):
        threading.Thread(target=s.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        SERVERS.append(s)
    return types.SimpleNamespace(web=w, agent=a, wp=w.server_address[1], ap=a.server_address[1], store=store, reg=reg, ui=web,
                                 folder=folder, ca=ca_pem)


def login(port, ca=None):
    g = call(port, "POST", "/api/login", {"id": "boss", "password": BOSS_PW}, ca=ca)
    return (g.json() or {}).get("token")


def add_pc(env, label):
    """관리자가 웹 포트의 /api/pcs 로 PC 를 추가 → (Got, 등록 글을 푼 dict)."""
    tok = login(env.wp, env.ca)
    g = call(env.wp, "POST", "/api/pcs", {"label": label}, headers={"Authorization": "Bearer " + tok}, ca=env.ca)
    text = (g.json() or {}).get("enrollment")
    return g, (pc_registry.decode_enrollment(text) if text else None), text


def enrolled(env, label="PC", guid_i=0):
    """PC 하나를 손으로 등록 → (pc 번호, 열쇠 둘)."""
    _, info, _ = add_pc(env, label)
    g, keys, _ = enroll_raw(env.ap, info, os.urandom(32).hex(), GUIDS[guid_i])
    assert g.status == 200, g
    return info["pc"], keys


ENV = None


def test_layout():
    print("두 포트 만들기 make_lan_servers")
    e = ENV
    check("웹·에이전트 side", e.web.side == "web" and e.agent.side == "agent", (e.web.side, e.agent.side))
    check("같은 store·runs·registry, 배치 LAN", e.web.store is e.agent.store and e.web.runs is e.agent.runs
          and e.web.registry is e.agent.registry is e.reg and e.web.deploy == e.agent.deploy == local_server.LAN)
    check("둘 다 TLS", isinstance(e.web.tls, ssl.SSLContext) and isinstance(e.agent.tls, ssl.SSLContext))
    check("두 포트가 다르고 127.0.0.1 에만", e.wp != e.ap and e.web.server_address[0] == e.agent.server_address[0] == "127.0.0.1")
    check("포트 0 이면 cfg 를 묶인 포트로 고쳐 둘이 같이 쓴다", e.web.cfg is e.agent.cfg and e.web.cfg.web_port == e.wp
          and e.web.cfg.agent_port == e.ap, (e.web.cfg.web_port, e.web.cfg.agent_port, e.wp, e.ap))
    check("등록 글의 서버 주소는 에이전트 포트의 IP (https)", e.ui.public_url == f"https://127.0.0.1:{e.ap}", e.ui.public_url)
    check("웹 창구에 인증 기관 글·설정", e.ui.lan_ca_pem == CA_PEM and e.ui.cfg is e.web.cfg)
    check("웹 창구가 없는 처리기 (lan_ca_pem·cfg 는 None 으로 시작)",
          local_web.Web(e.store, None, LIC, e.folder, None).lan_ca_pem is None
          and local_web.Web(e.store, None, LIC, e.folder, None).cfg is None)
    check("처리기는 HTTP/1.0 (연결 하나에 요청 하나 - 분당 연결 = 분당 요청)", local_server.Handler.protocol_version == "HTTP/1.0")
    check("단독 서버(LocalServer)는 side both·cfg 없음", local_server.LocalServer.side == "both" and local_server.LocalServer.cfg is None)

    print("  준비는 local_server._prepare 하나로 (make_server·make_lan_servers 같이)")
    check("lan_server 에 따로 된 _prepare 가 없다", not hasattr(lan_server, "_prepare"))
    seen = []
    orig = local_server._prepare

    def spy(srv, *a, **k):
        seen.append(type(srv).__name__)
        return orig(srv, *a, **k)
    local_server._prepare = spy
    try:
        s1 = local_server.make_server(e.store, None, LIC, ("a" * 40, "b" * 40), port=0, folder=e.folder)
        s1.server_close()
        env2 = start()
    finally:
        local_server._prepare = orig
    check("make_server 와 make_lan_servers 가 모두 _prepare 를 부른다", seen.count("LocalServer") == 1 and seen.count("LanServer") == 2, seen)
    check("단독 make_server 는 그대로 SINGLE·side both", s1.deploy == local_server.SINGLE and s1.side == "both" and s1.cfg is None)
    stop(env2)

    print("  만들 때 검사")
    try:
        lan_server.make_lan_servers(e.store, None, LIC, None, None, e.web.cfg, CERT, KEY, CA_PEM)
        check("등록부 없이는 열지 않는다", False)
    except ValueError:
        check("등록부 없이는 열지 않는다", True)

    print("  평문 프록시 모양 (web_plain) - 웹 포트만 평문·127.0.0.1, 에이전트는 늘 TLS")
    p = start({"listen": "127.0.0.1", "names": ["localhost"], "allow": ["127.0.0.0/8"], "trusted_proxies": ["127.0.0.1"],
               "web_plain": True})
    check("웹 포트는 TLS 없음, 에이전트는 TLS", p.web.tls is None and isinstance(p.agent.tls, ssl.SSLContext))
    g = call(p.wp, "GET", "/index.html", tls=False)
    check("웹 포트에 평문으로 로그인 화면 200", g.status == 200, g)
    check("에이전트 포트에 평문은 답 없이 끊긴다", closed_without_reply(p.ap))
    stop(p)


def test_ports_do_not_mix():
    print("서로의 길이 섞이지 않는다 (Review Focus 5)")
    e = ENV
    calls = []
    real = e.ui.handle
    e.ui.handle = lambda *a, **k: (calls.append(a[2]), real(*a, **k))[1]
    try:
        for method, path in (("GET", LIVE.format("pc_01")), ("POST", "/enroll"), ("PATCH", LIVE.format("pc_01")),
                             ("GET", "/fs/runs/c1/items/x"), ("POST", "/fs/runs/c1/items?id=x"), ("GET", "/fs-sum?parent=runs/c1"),
                             ("PUT", "/db/x.json"), ("DELETE", "/index.html")):
            g = call(e.wp, method, path, body={} if method in ("POST", "PATCH", "PUT") else None)
            check(f"웹 포트 {method} {path} → 404 (서명 없음)", g.status == 404 and not g.headers.get(local_store.H_SIGN), g)
        before = len(calls)
        for method, path in (("GET", "/api/session"), ("GET", "/index.html"), ("GET", "/"), ("POST", "/api/login"),
                             ("GET", "/edition.js"), ("DELETE", "/api/pcs/pc_01")):
            g = call(e.ap, method, path, body={"id": "boss", "password": BOSS_PW} if method == "POST" else None)
            check(f"에이전트 포트 {method} {path} → 404", g.status == 404, g)
        check("에이전트 포트는 웹 창구(web.handle)를 부르지 않는다", len(calls) == before, calls[before:])
    finally:
        e.ui.handle = real
    g = call(e.wp, "GET", "/index.html")
    check("웹 포트의 로그인 화면 파일은 200", g.status == 200 and b"<title>" in g.raw, g)
    g = call(e.ap, "GET", LIVE.format("pc_01"))
    check("에이전트 포트의 서명 없는 /db 는 401 (그대로)", g.status == 401, g)


def test_https_only():
    print("두 포트 모두 https 만")
    e = ENV
    check("웹 포트에 평문 http → 답 없이 끊긴다", closed_without_reply(e.wp))
    check("에이전트 포트에 평문 http → 답 없이 끊긴다", closed_without_reply(e.ap, b"POST /enroll HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n"))


def test_host_checked():
    print("Host 를 설정 목록으로")
    e = ENV
    g = call(e.wp, "GET", "/index.html", headers={"Host": f"evil.example:{e.wp}"})
    check("웹 포트에 Host evil.example → 403", g.status == 403, g)
    for h in (f"127.0.0.1:{e.wp}", f"localhost:{e.wp}"):
        g = call(e.wp, "GET", "/index.html", headers={"Host": h})
        check(f"웹 포트에 맞는 Host {h} → 200", g.status == 200, g)
    pc, keys = enrolled(e, "Host 시험", 1)
    g, ok = signed(e.ap, "GET", LIVE.format(pc), keys, pc, host=f"127.0.0.1:{e.wp}")
    check("에이전트 포트에 웹 포트 번호의 Host → 403 (서명이 맞아도, 서명 확인 전)", g.status == 403 and not ok, g)
    g, ok = signed(e.ap, "GET", LIVE.format(pc), keys, pc, host=f"evil.example:{e.ap}")
    check("에이전트 포트에 모르는 이름 → 403", g.status == 403, g)
    g, ok = signed(e.ap, "GET", LIVE.format(pc), keys, pc, host=f"LOCALHOST:{e.ap}")
    check("에이전트 포트에 맞는 Host (대소문자 무시) → 서명된 200", g.status == 200 and ok, g)
    g = call(e.ap, "POST", "/enroll", {"v": 1}, headers={"Host": f"127.0.0.1:{e.wp}"})
    check("등록도 Host 를 본다 (웹 포트 번호 → 403)", g.status == 403, g)

    print("  host_ok - cfg 가 없으면 지금 local_host 그대로")
    single = types.SimpleNamespace(server_port=8781)
    msg = email.message.Message()
    msg["Host"] = "127.0.0.1:8781"
    check("단독: 127.0.0.1:8781", local_server.host_ok(msg, single))
    msg.replace_header("Host", "localhost")
    check("단독: 포트 없는 localhost", local_server.host_ok(msg, single) == local_server.local_host(msg, 8781) is True)
    msg.replace_header("Host", "192.168.1.5:8781")
    check("단독: 사내 주소는 안 된다", not local_server.host_ok(msg, single))
    cfg = lan_config.parse({"listen": "192.168.1.230", "names": ["nt"], "public_web": ["ap.corp.local"]})
    web = types.SimpleNamespace(server_port=8443, cfg=cfg, side="web")
    agent = types.SimpleNamespace(server_port=8444, cfg=cfg, side="agent")
    for h, w_ok, a_ok in (("192.168.1.230:8443", True, False), ("NT:8443", True, False), ("ap.corp.local", True, False),
                          ("192.168.1.230:8444", False, True), ("nt:8444", False, True), ("127.0.0.1:8443", False, False),
                          ("", False, False)):
        msg.replace_header("Host", h)
        check(f"사내: Host {h!r} 웹 {w_ok}·에이전트 {a_ok}", local_server.host_ok(msg, web) == w_ok and local_server.host_ok(msg, agent) == a_ok)


def test_enroll_over_tls_with_ca():
    print("등록 글에 인증 기관, TLS 로 등록")
    e = ENV
    g, info, text = add_pc(e, "등록 시험")
    check("관리자 PC 추가 200", g.status == 200 and info is not None, g)
    if info is None:
        return
    check("등록 글에 ca (우리 인증 기관 글)", info.get("ca") == CA_PEM)
    check("url 은 https://127.0.0.1:<에이전트 포트>", info["url"] == f"https://127.0.0.1:{e.ap}", info["url"])

    print("  서버 쪽 (등록 요청을 손으로)")
    rand = os.urandom(32).hex()
    g, keys, ok = enroll_raw(e.ap, info, rand, GUIDS[2])
    check("TLS 로 /enroll → 새 열쇠로 서명된 200", g.status == 200 and ok, g)
    g, ok = signed(e.ap, "PATCH", LIVE.format(info["pc"]) + "?print=silent", keys, info["pc"], body={"state": "idle"})
    check("그 열쇠로 현황 PATCH → 서명된 204/200", g.status in (200, 204) and ok, g)
    check("현황이 저장소에 있다", (e.store.get(f"apps/rpa/live/c1/{info['pc']}") or {}).get("state") == "idle")

    print("  에이전트 클라이언트 (local_store.enroll)")
    g, info2, text2 = add_pc(e, "클라이언트 시험")
    got = local_store.enroll(text2, GUIDS[3], "PC-C")
    check("local_store.enroll 이 https 로 등록", got.get("pc_id") == info2["pc"], got)
    check("등록 답에 인증 기관 글 (ca_pem)", got.get("ca_pem") == CA_PEM and got.get("server_url") == f"https://127.0.0.1:{e.ap}", got)
    check("등록 답의 열쇠가 서버 등록부와 같다", (got.get("agent_key"), got.get("relay_key")) == e.reg.keys(got["pc_id"]))
    cl = local_store.Client({"server_url": got["server_url"], "key": got["agent_key"], "lan": True, "pc_id": got["pc_id"],
                             "ca_pem": got.get("ca_pem")})
    cl.patch(f"apps/rpa/live/c1/{got['pc_id']}", {"state": "idle"})
    check("그 클라이언트로 현황 PATCH", (e.store.get(f"apps/rpa/live/c1/{got['pc_id']}") or {}).get("state") == "idle")
    check("그 클라이언트로 읽기 (서명된 응답·Date 로 시계)", cl.get(f"apps/rpa/live/c1/{got['pc_id']}") == {"state": "idle"}
          and abs(cl.server_now() - time.time()) < 5)
    try:
        local_store.enroll(text2, GUIDS[3], "PC-C")
        check("같은 글로 두 번째 등록은 거절", False, "예외 없음")
    except local_store.fb.HttpError as ex:
        check("같은 글로 두 번째 등록은 거절", ex.status == 403 and "unknown" in ex.body, repr(ex.body))


def test_other_ca_refused():
    print("다른 인증 기관으로 만든 서버에는 붙지 않는다")
    ca2, out2 = os.path.join(TMP, "ca2"), os.path.join(TMP, "srv2")
    lan_ca.make_ca(ca2, ["localhost"], ["127.0.0.1"])
    cert2, key2 = lan_ca.issue_server(ca2, out2, ["localhost"], ["127.0.0.1"])
    other = start(cert=cert2, key=key2, ca_pem=lan_ca.ca_pem(ca2))
    try:
        _, info, text = add_pc(other, "남의 서버")
        check("남의 서버의 등록 글에는 그 서버의 인증 기관", info is not None and info.get("ca") == lan_ca.ca_pem(ca2) != CA_PEM)
        # 우리 인증 기관을 실은 등록 글로 남의 서버에 등록하려 하면 (주소만 같다)
        mine = pc_registry.encode_enrollment(dict(info, ca=CA_PEM))
        try:
            local_store.enroll(mine, GUIDS[8], "PC-X")
            check("등록: 인증서 확인 실패 → AuthError(0, CERT_FAILED)", False, "예외 없음")
        except local_store.fb.AuthError as ex:
            check("등록: 인증서 확인 실패 → AuthError(0, CERT_FAILED)", ex.status == 0 and ex.code == local_store.CERT_FAILED, repr(ex))
        check("남의 서버 등록부에 그 PC 는 아직 등록 전 (요청이 닿지 않았다)", other.reg.state(info["pc"]) != "active",
              other.reg.state(info["pc"]))
        cl = local_store.Client({"server_url": f"https://127.0.0.1:{other.ap}", "key": "k" * 64, "lan": True, "pc_id": "pc_01",
                                 "ca_pem": CA_PEM})
        for name, fn in (("GET", lambda: cl.get("apps/rpa/live/c1/pc_01")),
                         ("PATCH", lambda: cl.patch("apps/rpa/live/c1/pc_01", {"state": "idle"})),
                         ("구독", lambda: list(cl.stream("apps/rpa/commands/c1/pc_01", timeout=10)))):
            try:
                fn()
                check(f"{name}: 인증서 확인 실패 → AuthError(0, CERT_FAILED)", False, "예외 없음")
            except local_store.fb.AuthError as ex:
                check(f"{name}: 인증서 확인 실패 → AuthError(0, CERT_FAILED)", ex.status == 0 and ex.code == local_store.CERT_FAILED,
                      repr(ex))
            except Exception as ex:
                check(f"{name}: 인증서 확인 실패 → AuthError(0, CERT_FAILED)", False, f"{type(ex).__name__}: {ex}")
        check("남의 서버 저장소에 아무것도 쓰이지 않았다", other.store.get("apps/rpa/live/c1/pc_01") is None)
    finally:
        stop(other)

    print("  같은 인증 기관이라도 주소가 인증서에 없으면 (이름 확인은 켜져 있다)")
    ca3, out3 = os.path.join(TMP, "ca3"), os.path.join(TMP, "srv3")
    lan_ca.make_ca(ca3, ["localhost", "nt"], ["127.0.0.1"])
    cert3, key3 = lan_ca.issue_server(ca3, out3, ["nt"], [])          # SAN 은 이름 nt 뿐 - 127.0.0.1 은 없다
    pem3 = lan_ca.ca_pem(ca3)
    named = start(cert=cert3, key=key3, ca_pem=pem3)
    try:
        cl = local_store.Client({"server_url": f"https://127.0.0.1:{named.ap}", "key": "k" * 64, "lan": True, "pc_id": "pc_01",
                                 "ca_pem": pem3})
        try:
            cl.get("apps/rpa/live/c1/pc_01")
            check("인증서에 없는 주소 → AuthError(0, CERT_FAILED)", False, "예외 없음")
        except local_store.fb.AuthError as ex:
            check("인증서에 없는 주소 → AuthError(0, CERT_FAILED)", ex.status == 0 and ex.code == local_store.CERT_FAILED, repr(ex))
        except Exception as ex:
            check("인증서에 없는 주소 → AuthError(0, CERT_FAILED)", False, f"{type(ex).__name__}: {ex}")
    finally:
        stop(named)


class HeldOpener:
    """Client 의 TLS opener 를 감싸 구독 응답을 잡아 둔다 (스레드의 제너레이터는 밖에서 닫지 못한다)."""

    def __init__(self, client):
        self.real, self.held, self.used = client._open, [], 0
        client._open = self

    def __call__(self, req, timeout=None):
        self.used += 1
        resp = self.real(req, timeout=timeout)
        if (req.get_header("Accept") or "") == "text/event-stream":
            self.held.append(resp)
        return resp

    def close(self):
        for r in self.held:
            try:
                r.close()
            except Exception:
                pass


class CmdStream:
    """Client.stream(명령함, state==queued) 을 스레드에서 돌려 본 명령 키를 모은다 (test_lan_e2e 와 같은 꼴)."""

    def __init__(self, client, pc):
        self.client, self.pc = client, pc
        self.events, self.keys, self.error = [], set(), None
        self.ended = threading.Event()
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            for event, data in self.client.stream(f"apps/rpa/commands/c1/{self.pc}",
                                                  {"orderBy": '"state"', "equalTo": '"queued"'}, timeout=60):
                self.events.append((event, data))
                if event in ("put", "patch") and isinstance(data, dict):
                    path, val = data.get("path") or "/", data.get("data")
                    if path == "/":
                        if isinstance(val, dict):
                            self.keys.update(k for k, v in val.items() if v is not None)
                    elif val is not None:
                        self.keys.add(path.strip("/").split("/")[0])
        except Exception as ex:
            self.error = ex
        self.ended.set()

    def started(self):
        return any(ev == "put" for ev, _ in list(self.events))


def test_three_pcs_over_tls():
    print("PC 셋 - TLS 두 포트로 등록·현황·구독, 한 PC 에만 명령 (① test_lan_e2e 1~3단계)")
    env = start()
    held, subs = [], {}
    try:
        clients = {}
        for i in range(3):
            g, info, text = add_pc(env, f"{i + 1}층")
            pc = info["pc"] if info else None
            check(f"PC 추가 → {pc} (https 등록 글·인증 기관)", g.status == 200 and info["url"] == f"https://127.0.0.1:{env.ap}"
                  and info.get("ca") == CA_PEM, g)
            got = local_store.enroll(text, GUIDS[i], f"OFFICE-{i + 1}")
            check(f"{pc} 등록, 서버와 열쇠가 같다", got.get("pc_id") == pc and (got["agent_key"], got["relay_key"]) == env.reg.keys(pc)
                  and env.reg.state(pc) == "active", sorted(got))
            cl = local_store.Client({"standalone": True, "server_url": got["server_url"], "key": got["agent_key"], "role": "agent",
                                     "lan": True, "pc_id": pc, "ca_pem": got["ca_pem"]})
            held.append(HeldOpener(cl))
            clients[pc] = cl
        pcs = sorted(clients)
        check("번호 셋", pcs == ["pc_01", "pc_02", "pc_03"], pcs)

        for pc in pcs:
            clients[pc].patch(f"apps/rpa/live/c1/{pc}", {"state": "idle", "who": pc})
        check("셋이 각자 자기 현황을 썼다", all((env.store.get(f"apps/rpa/live/c1/{pc}") or {}).get("who") == pc for pc in pcs))
        try:
            clients["pc_01"].patch("apps/rpa/live/c1/pc_02", {"state": "evil"})
            check("남의 현황은 쓰지 못한다", False, "예외 없음")
        except local_store.fb.HttpError as ex:
            check("남의 현황은 쓰지 못한다 (서명된 403)", ex.status == 403)
        subs = {pc: CmdStream(clients[pc], pc) for pc in pcs}
        check("셋의 구독이 TLS 로 열리고 첫 값(put)이 온다", until(lambda: all(s.started() for s in subs.values()), 5)
              and not any(s.ended.is_set() for s in subs.values()), {pc: (s.events, s.error) for pc, s in subs.items()})
        check("구독도 클라이언트의 TLS opener 로 (우리 인증 기관만 믿는 길)", all(len(h.held) == 1 for h in held))

        tok = login(env.wp)
        g = call(env.wp, "POST", "/api/commands", {"type": "launch", "pcId": "pc_02"}, headers={"Authorization": "Bearer " + tok})
        k = (g.json() or {}).get("key")
        check("관리자가 웹 포트로 pc_02 에 launch → 200", g.status == 200 and bool(k), g)
        check("3초 안에 pc_02 구독에 그 명령이 온다", until(lambda: k in subs["pc_02"].keys, 3), subs["pc_02"].events)
        marks = {}
        for pc in ("pc_01", "pc_03"):
            g = call(env.wp, "POST", "/api/commands", {"type": "launch", "pcId": pc}, headers={"Authorization": "Bearer " + tok})
            marks[pc] = (g.json() or {}).get("key")
        check("pc_01·pc_03 구독에는 자기 표시 명령만, pc_02 의 명령은 오지 않는다",
              until(lambda: all(marks[pc] in subs[pc].keys for pc in marks), 3) and all(k not in subs[pc].keys for pc in marks),
              {pc: subs[pc].keys for pc in marks})
        check("pc_02 구독에는 남의 명령이 오지 않는다", not (set(marks.values()) & subs["pc_02"].keys), subs["pc_02"].keys)
    finally:
        for h in held:
            h.close()
        for s in subs.values():
            s.ended.wait(3)
        stop(env)


def test_unsigned_reply_has_no_date():
    print("서명 없는 답엔 Date 가 없다 (M-4), 서명된 답에는 있다")
    e = ENV
    g = call(e.ap, "GET", LIVE.format("pc_01"))
    check("사내: 서명 없는 401 에 Date 없음", g.status == 401 and g.headers.get("Date") is None, dict(g.headers))
    g = call(e.wp, "GET", LIVE.format("pc_01"))
    check("사내: 웹 포트의 막힌 길 404 에도 Date 없음", g.status == 404 and g.headers.get("Date") is None, dict(g.headers))
    pc, keys = enrolled(e, "Date 시험", 4)
    g, ok = signed(e.ap, "GET", LIVE.format(pc), keys, pc)
    check("사내: 서명된 200 에는 Date 있음", g.status == 200 and ok and g.headers.get("Date"), dict(g.headers))
    g, ok = signed(e.ap, "GET", "/db/apps/rpa/live/c2/x.json", keys, pc)
    check("사내: 서명된 403 에도 Date 있음", g.status == 403 and ok and g.headers.get("Date"), dict(g.headers))

    print("  단독 (make_server, registry 없음)")
    folder = tempfile.mkdtemp(dir=TMP)
    store = local_server.Store(os.path.join(folder, "store.json"), volatile=local_server.VOLATILE)
    runs = local_server.Runs(":memory:")
    RUNS.append(runs)
    keys1 = local_server.ensure_keys(folder, lock=False)
    s = local_server.make_server(store, runs, LIC, keys1, port=0, folder=folder)
    SERVERS.append(s)
    threading.Thread(target=s.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    port = s.server_address[1]
    g = call(port, "GET", LIVE.format("srv"), tls=False)
    check("단독: 서명 없는 401 에 Date 없음", g.status == 401 and g.headers.get("Date") is None, dict(g.headers))
    check("단독: 서명 없는 401 에도 Server 머리글은 그대로", (g.headers.get("Server") or "").startswith("AutopilotLocal"),
          dict(g.headers))
    path = LIVE.format("srv")
    hs = local_store.sign_headers(keys1[0], "agent", "GET", path)
    g = call(port, "GET", path, headers=hs, tls=False)
    check("단독: 서명된 200 에는 Date 있음", g.status == 200 and g.headers.get("Date")
          and g.headers.get(local_store.H_SIGN) == local_store.response_mac(keys1[0], hs[local_store.H_NONCE], 200, g.raw),
          dict(g.headers))


def test_bad_signature_blocks_ip():
    print("에이전트 포트의 서명 틀림 20번 → 그 주소 거절")
    e = ENV
    pc, keys = enrolled(e, "틀림 시험", 5)
    e.agent.bad.clear()
    for i in range(lan_server.BAD_LIMIT):
        g, _ = signed(e.ap, "GET", LIVE.format(pc), keys, pc, key="x" * 64)
        if g.status != 401:
            check(f"{i + 1}번째 틀린 서명 → 401", False, g)
            break
    check("20번 뒤 거절 중", e.agent.blocked("127.0.0.1"))
    check("21번째 연결은 끊긴다 (TLS 악수도 못 한다)", refused(e.ap))
    check("웹 포트는 따로 (막히지 않는다)", call(e.wp, "GET", "/index.html").status == 200)
    e.agent.bad.clear()
    check("거절을 풀면 다시 된다", signed(e.ap, "GET", LIVE.format(pc), keys, pc)[0].status == 200)

    print("  맞는 서명·다른 까닭의 401 은 세지 않는다")
    before = dict(e.agent.bad)
    g = call(e.ap, "GET", LIVE.format(pc), headers={"Host": f"evil.example:{e.ap}"})
    check("Host 거절 403 은 세지 않는다", g.status == 403 and e.agent.bad == before, (g, e.agent.bad))

    print("  /enroll 의 bad_proof 도 센다")
    st = e.reg.start("증명 시험")
    info = {"pc": st["pc_id"], "token": st["token"]}
    g, _, _ = enroll_raw(e.ap, info, os.urandom(32).hex(), GUIDS[6], proof="0" * 64)
    check("틀린 증명 → 403 bad_proof", g.status == 403 and (g.json() or {}).get("error") == "bad_proof", g)
    check("서명 틀림 표에 한 번", (e.agent.bad.get("127.0.0.1") or [0])[0] == 1, e.agent.bad)
    g, _, _ = enroll_raw(e.ap, {"pc": "pc_99", "token": "t" * 43}, os.urandom(32).hex(), GUIDS[7])
    check("모르는 번호(unknown)는 세지 않는다", g.status == 403 and (e.agent.bad.get("127.0.0.1") or [0])[0] == 1, e.agent.bad)
    e.agent.bad.clear()


def test_handler_client_ip():
    print("처리기의 보낸 쪽 주소 Handler.client_ip")
    cfg = lan_config.parse({"listen": "10.0.0.5", "allow": ["10.0.0.0/8"], "trusted_proxies": ["10.0.0.9"]})

    def h(side, peer, xffs=(), with_cfg=True):
        x = local_server.Handler.__new__(local_server.Handler)
        x.client_address = (peer, 50000)
        if with_cfg:
            x.server = types.SimpleNamespace(cfg=cfg, side=side, peer_ip=lambda addr: str(addr[0]))
        else:
            x.server = types.SimpleNamespace(cfg=None, side="both")
        x.headers = email.message.Message()
        for v in xffs:
            x.headers["X-Forwarded-For"] = v
        return x.client_ip()
    check("cfg 가 없으면 소켓 주소", h("both", "127.0.0.1", ["1.2.3.4"], with_cfg=False) == "127.0.0.1")
    check("웹 쪽 믿을 프록시 → X-Forwarded-For 의 오른쪽 첫 비프록시", h("web", "10.0.0.9", ["10.0.0.7"]) == "10.0.0.7")
    check("웹 쪽 프록시가 아니면 머리글을 버린다 (Review Focus 1)", h("web", "10.0.0.7", ["10.0.0.3"]) == "10.0.0.7")
    check("에이전트 쪽은 늘 소켓 주소", h("agent", "10.0.0.9", ["10.0.0.7"]) == "10.0.0.9")
    check("머리글이 여러 줄이면 차례로 이어 읽는다", h("web", "10.0.0.9", ["1.2.3.4", "10.0.0.6"]) == "10.0.0.6")


def stop(env):
    for s in (env.web, env.agent):
        s.shutdown()
        s.server_close()


try:
    ENV = start()
    test_layout()
    test_ports_do_not_mix()
    test_https_only()
    test_host_checked()
    test_enroll_over_tls_with_ca()
    test_other_ca_refused()
    test_three_pcs_over_tls()
    test_unsigned_reply_has_no_date()
    test_bad_signature_blocks_ip()
    test_handler_client_ip()
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
