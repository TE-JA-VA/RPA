# -*- coding: utf-8 -*-
"""사내 서버 ② Task 3 - LanServer: 받기 전에 거르기(허용 대역·연결 수·분당 연결·서명 틀림 거절)와 TLS 악수 5초,
믿을 프록시로 보낸 쪽 주소 client_ip (계획 2026-11-24-lan-2-network, 설계 6.3·6.4 끝줄).
Task 2 의 인증 기관으로 127.0.0.1 서버 인증서를 만들고 LanServer(side="agent", 등록부 하나)를 포트 0 으로 띄운다.
클라이언트는 우리 인증 기관만 믿는 ssl.create_default_context(cadata=…). 보낸 쪽 주소는 srv.peer_ip 를 바꿔 끼워 흉내 낸다.
기다림은 시간이 아니라 조건으로 (until). 윈도우·리눅스(WSL) 둘 다 같은 파일로 돈다.
    D:/AX/RPA/.venv/Scripts/python.exe tests/test_lan_net.py
    wsl.exe -d Ubuntu -e python3 /mnt/d/AX/RPA_StandAlone/tests/test_lan_net.py
"""
import dataclasses
import http.client
import os
import shutil
import socket
import ssl
import sys
import tempfile
import threading
import time

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "firebase", "agent"))
import lan_ca  # noqa: E402
import lan_config  # noqa: E402
import local_server  # noqa: E402
import pc_registry  # noqa: E402
import lan_server  # noqa: E402

fails = []
TMP = tempfile.mkdtemp(prefix="rpa_lan_net_")
LIC = {"edition": "standalone", "company": "시험상사", "cid": "c1", "pc_id": "srv", "issued": "2026-11-24",
       "modules": {}, "features": {}, "limits": {}}
CFG = lan_config.parse({"listen": "127.0.0.1", "names": ["localhost"], "allow": ["10.0.0.0/8"]})


def check(name, ok, detail=""):
    print(f"  [{'통과' if ok else '실패'}] {name}" + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


def until(fn, sec):
    """fn() 이 참이 될 때까지 (시간이 아니라 조건으로 기다린다) → 참이 됐으면 True."""
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


def ctx():
    return ssl.create_default_context(cadata=CA_PEM)


class Clock:
    """시험 시계 - srv.clock 에 끼워 300초 거절·60초 창을 기다리지 않고 넘긴다."""
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


SERVERS = []


def start(side="agent", cfg=CFG, tls=True):
    folder = tempfile.mkdtemp(dir=TMP)
    store = local_server.Store(os.path.join(folder, "store.json"), volatile=local_server.VOLATILE)
    runs = local_server.Runs(":memory:")
    reg = pc_registry.Registry(os.path.join(folder, "pcs.json"), seats=5)
    srv = lan_server._open(cfg, side, ("127.0.0.1", 0), lan_server.tls_context(CERT, KEY) if tls else None,
                           store, runs, LIC, reg, folder=folder)
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    SERVERS.append((srv, runs))
    return srv, srv.server_address[1]


def stop(srv):
    srv.shutdown()
    srv.server_close()


def tls_open(port, timeout=5):
    """우리 인증 기관만 믿고 악수까지 끝낸 소켓. 실패하면 예외."""
    raw = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    try:
        return ctx().wrap_socket(raw, server_hostname="127.0.0.1")
    except BaseException:
        raw.close()
        raise


def refused(port):
    """악수가 실패하는가 (응답 없이 닫혔다)."""
    try:
        s = tls_open(port)
    except (ssl.SSLError, ConnectionError, OSError):
        return True
    s.close()
    return False


def accepted(port):
    return not refused(port)


def get_status(port, path="/db/apps/rpa/live/c1/pc_01.json", timeout=5):
    """TLS 로 요청 하나 → 상태 번호 (서명 없는 요청이라 401 이 정상 답)."""
    c = http.client.HTTPSConnection("127.0.0.1", port, context=ctx(), timeout=timeout)
    try:
        # Host 는 설정 목록(CFG.agent_hosts - 포트 8444)으로 본다 (Task 4) - 포트 0 으로 띄운 서버라 설정의 포트를 싣는다
        c.request("GET", path, headers={"Host": f"127.0.0.1:{CFG.agent_port}"})
        r = c.getresponse()
        r.read()
        return r.status
    finally:
        c.close()


def wait_closed(sock, sec):
    """sock 이 서버 쪽에서 닫힐 때까지 (받은 바이트, 걸린 초). sec 안에 안 닫히면 걸린 초는 None."""
    sock.settimeout(sec)
    t0, got = time.monotonic(), b""
    try:
        while True:
            b = sock.recv(4096)
            if not b:
                break
            got += b
    except (ConnectionError, OSError) as e:
        if isinstance(e, TimeoutError) or isinstance(e, socket.timeout):
            return got, None
    return got, time.monotonic() - t0


def idle(srv, sec=5):
    """서버의 연결 수가 0 으로 돌아오는가 (세기와 돌려주기가 한 번씩 - 새지 않는다)."""
    return until(lambda: srv.conns == 0 and not srv.per_ip, sec)


def test_constants():
    print("상수·TLS 설정")
    check("상수", (lan_server.PER_IP_CONN, lan_server.PER_IP_MIN, lan_server.HANDSHAKE_SEC, lan_server.BAD_LIMIT,
                 lan_server.BAD_WINDOW, lan_server.BAD_BLOCK, lan_server.TRACK_MAX) == (16, 600, 5, 20, 60, 300, 5000))
    c = lan_server.tls_context(CERT, KEY)
    check("서버 컨텍스트, TLS 1.2 이상", c.protocol == ssl.PROTOCOL_TLS_SERVER and c.minimum_version == ssl.TLSVersion.TLSv1_2)
    check("재협상 끔", bool(c.options & getattr(ssl, "OP_NO_RENEGOTIATION", 0)) or not hasattr(ssl, "OP_NO_RENEGOTIATION"))
    names = {x["name"] for x in c.get_ciphers() if x["protocol"] == "TLSv1.2"}
    check("TLS 1.2 암호는 ECDHE + AESGCM·CHACHA20 만", names and all(n.startswith("ECDHE-") and ("GCM" in n or "CHACHA20" in n)
                                                                  for n in names), names)
    check("LanServer 는 LocalServer 를 잇는다", issubclass(lan_server.LanServer, local_server.LocalServer))


def test_open_guards():
    print("만들 때 검사")
    st = local_server.Store(os.path.join(TMP, "g.json"))
    tls = lan_server.tls_context(CERT, KEY)

    def bad(fn):
        try:
            srv = fn()
        except ValueError:
            return True
        srv.server_close()
        return False
    check("에이전트 쪽은 TLS 없이 못 연다", bad(lambda: lan_server._open(CFG, "agent", ("127.0.0.1", 0), None, st, None, LIC, None)))
    check("side 는 web·agent 만", bad(lambda: lan_server._open(CFG, "both", ("127.0.0.1", 0), tls, st, None, LIC, None)))
    check("공인 주소에는 듣지 않는다", bad(lambda: lan_server._open(CFG, "agent", ("8.8.8.8", 0), tls, st, None, LIC, None)))
    check("0.0.0.0 에는 듣지 않는다", bad(lambda: lan_server._open(CFG, "agent", ("0.0.0.0", 0), tls, st, None, LIC, None)))
    srv, port = start()
    check("만든 서버의 cfg·side·tls·배치", srv.cfg is CFG and srv.side == "agent" and isinstance(srv.tls, ssl.SSLContext)
          and srv.deploy == local_server.LAN and srv.registry is not None, (srv.side, srv.deploy))
    check("127.0.0.1 에만 묶였다", srv.server_address[0] == "127.0.0.1", srv.server_address)
    check("TLS 로 요청 → 처리기가 답한다 (서명 없는 401)", get_status(port) == 401)
    check("평문 HTTP 는 답 없이 끊긴다", plain_http_closed(port))
    check("악수 실패도 연결 수를 돌려준다", idle(srv), (srv.conns, srv.per_ip))
    stop(srv)


def plain_http_closed(port):
    with socket.create_connection(("127.0.0.1", port), timeout=8) as s:
        s.sendall(b"GET /db/x.json HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
        got, sec = wait_closed(s, 8)
    return sec is not None and not got.startswith(b"HTTP/")


def test_outside_allow_closed_before_tls():
    print("허용 대역 밖 주소는 TLS 악수 전에 닫힌다")
    srv, port = start()
    srv.peer_ip = lambda addr: "203.0.113.9"
    err = None
    try:
        tls_open(port).close()
    except Exception as e:
        err = e
    check("악수 실패 (SSLError·ConnectionError)", isinstance(err, (ssl.SSLError, ConnectionError)), repr(err))
    with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
        got, sec = wait_closed(s, 5)
    check("서버는 아무것도 보내지 않고 닫는다 (서버 인증서를 받지 못한다)", got == b"" and sec is not None, (got[:20], sec))
    check("밖 주소는 세지도 표에 남지도 않는다", srv.conns == 0 and not srv.per_ip and "203.0.113.9" not in srv.minute,
          (srv.conns, srv.per_ip, list(srv.minute)))
    srv.peer_ip = lambda addr: "10.1.2.3"
    s = tls_open(port)
    check("허용 대역 안 주소면 악수 성공·서버 인증서를 받는다", bool(s.getpeercert()))
    s.close()
    del srv.peer_ip
    check("루프백은 늘 허용", accepted(port))
    check("연결 수가 돌아온다", idle(srv), (srv.conns, srv.per_ip))
    stop(srv)

    print("  웹 쪽 proxy_only - 믿을 프록시에서 온 연결만")
    cfg = lan_config.parse({"listen": "127.0.0.1", "allow": ["10.0.0.0/8"], "trusted_proxies": ["10.0.0.9"], "proxy_only": True})
    srv, port = start(side="web", cfg=cfg)
    srv.peer_ip = lambda addr: "10.0.0.7"
    check("프록시가 아닌 사내 주소 → 닫힌다", refused(port))
    srv.peer_ip = lambda addr: "10.0.0.9"
    check("믿을 프록시 → 악수 성공", accepted(port))
    check("연결 수가 돌아온다 (웹)", idle(srv), (srv.conns, srv.per_ip))
    stop(srv)
    srv, port = start(side="agent", cfg=cfg)
    srv.peer_ip = lambda addr: "10.0.0.7"
    check("에이전트 쪽은 proxy_only 와 상관없이 허용 대역이면 된다", accepted(port))
    stop(srv)


def test_slow_handshake_cut():
    print("악수를 끄는 연결은 5초에 끊기고 다른 연결은 계속 된다")
    srv, port = start()
    silent = socket.create_connection(("127.0.0.1", port), timeout=10)
    drip = socket.create_connection(("127.0.0.1", port), timeout=10)
    t0 = time.monotonic()
    results = {}

    def watch(name, sock):
        results[name] = wait_closed(sock, 9)
    stop_drip = threading.Event()

    def dribble():           # TLS 레코드 머리(5바이트) 뒤에 0.3초마다 한 바이트 - 받을 때마다 시간 제한이 새로 시작되는 연결
        try:
            drip.sendall(b"\x16\x03\x01\x02\x00")
            while not stop_drip.wait(0.3):
                drip.sendall(b"\x01")
        except OSError:
            pass
    ws = [threading.Thread(target=watch, args=(n, s), daemon=True) for n, s in (("silent", silent), ("drip", drip))]
    for w in ws:
        w.start()
    threading.Thread(target=dribble, daemon=True).start()
    check("두 연결이 서버에 잡혀 있다", until(lambda: srv.conns >= 2, 2), srv.conns)
    times = []
    for _ in range(3):
        a = time.monotonic()
        st = get_status(port, timeout=2)
        times.append((st, round(time.monotonic() - a, 2)))
    check("그동안 다른 클라이언트는 2초 안에 답을 받는다", all(st == 401 and sec < 2 for st, sec in times), times)
    check("그동안 열린 두 연결은 아직 끊기지 않았다", "silent" not in results and "drip" not in results, results)
    for w in ws:
        w.join(10)
    stop_drip.set()
    s_sec = results.get("silent", (b"", None))[1]
    d_sec = results.get("drip", (b"", None))[1]
    check("아무것도 보내지 않는 연결은 6초 안에 닫힌다", s_sec is not None and time.monotonic() - t0 > 0 and s_sec < 6.5, s_sec)
    check("한 바이트씩 보내는 연결도 6초 안에 닫힌다 (받을 때마다 늘어나지 않는다)", d_sec is not None and d_sec < 6.5, d_sec)
    check("둘 다 4초 전에는 닫히지 않았다 (5초 기준)", (s_sec or 0) >= 4 and (d_sec or 0) >= 4, (s_sec, d_sec))
    silent.close()
    drip.close()
    check("끊긴 연결도 연결 수를 돌려준다", idle(srv), (srv.conns, srv.per_ip))
    stop(srv)


def test_per_ip_conn_cap():
    print("주소마다 동시 연결 16")
    srv, port = start()
    open_ = [tls_open(port) for _ in range(lan_server.PER_IP_CONN)]
    check("16개는 열린다", until(lambda: srv.per_ip.get("127.0.0.1") == 16, 3), srv.per_ip)
    check("전체 연결 수도 16 (한 번만 센다)", srv.conns == 16, srv.conns)
    check("17번째는 바로 닫힌다", refused(port))
    check("거절한 연결은 세지 않는다", srv.conns == 16 and srv.per_ip.get("127.0.0.1") == 16, (srv.conns, srv.per_ip))
    srv.peer_ip = lambda addr: "10.0.0.5"
    other = tls_open(port)
    check("다른 주소는 된다", srv.per_ip.get("10.0.0.5") == 1 or until(lambda: srv.per_ip.get("10.0.0.5") == 1, 2), srv.per_ip)
    other.close()
    del srv.peer_ip
    open_.pop().close()
    check("하나 닫으면 다시 된다", until(lambda: accepted(port), 5))
    for s in open_:
        s.close()
    check("모두 닫으면 0 (새지 않는다)", idle(srv), (srv.conns, srv.per_ip))

    print("  서버 전체 연결 상한 (deploy.max_conn)")
    srv.deploy = dataclasses.replace(local_server.LAN, max_conn=3)
    socks = [tls_open(port) for _ in range(3)]
    check("세 개 뒤 네 번째는 닫힌다", until(lambda: srv.conns == 3, 2) and refused(port), srv.conns)
    for s in socks:
        s.close()
    check("모두 닫으면 0", idle(srv), (srv.conns, srv.per_ip))
    stop(srv)


def test_per_ip_minute_cap():
    print("주소마다 분당 연결")
    srv, port = start()
    clock = Clock()
    srv.clock = clock
    old = lan_server.PER_IP_MIN, lan_server.PER_IP_MIN_AGENT
    lan_server.PER_IP_MIN = lan_server.PER_IP_MIN_AGENT = 5      # 이 서버는 에이전트 포트 - 사내 서버 ④ ②검-4 부터 PER_IP_MIN_AGENT
    try:
        oks = [accepted(port) for _ in range(5)]
        check("1분에 5번까지 된다 (시험용 상한 5)", all(oks), oks)
        check("6번째는 닫힌다", refused(port))
        srv.peer_ip = lambda addr: "10.0.0.6"
        check("다른 주소는 따로 센다", accepted(port))
        del srv.peer_ip
        clock.t += 61
        check("1분이 지나면 다시 된다", accepted(port))
    finally:
        lan_server.PER_IP_MIN, lan_server.PER_IP_MIN_AGENT = old
    check("연결 수가 돌아온다", idle(srv), (srv.conns, srv.per_ip))
    srv.minute.clear()
    for i in range(lan_server.TRACK_MAX + 10):
        srv.minute[f"10.9.{i // 256}.{i % 256}"] = [clock.t - 120, 1]
    check("표가 커지면 지난 것을 정리한다", accepted(port) and len(srv.minute) <= lan_server.TRACK_MAX, len(srv.minute))
    stop(srv)


def test_bad_signature_block():
    print("서명 틀림 60초에 20번이면 그 주소 300초 거절")
    srv, port = start()
    clock = Clock()
    srv.clock = clock
    srv.peer_ip = lambda addr: "10.0.0.7"
    for _ in range(lan_server.BAD_LIMIT - 1):
        srv.note_bad("10.0.0.7")
    check("19번까지는 거절하지 않는다", not srv.blocked("10.0.0.7") and accepted(port))
    srv.note_bad("10.0.0.7")
    check("20번째에 거절 시작", srv.blocked("10.0.0.7"))
    check("그 주소의 새 연결은 닫힌다", refused(port))
    srv.peer_ip = lambda addr: "10.0.0.8"
    check("다른 주소는 된다", accepted(port) and not srv.blocked("10.0.0.8"))
    srv.peer_ip = lambda addr: "10.0.0.7"
    clock.t += lan_server.BAD_BLOCK - 1
    check("300초 안은 계속 닫힌다", srv.blocked("10.0.0.7") and refused(port))
    clock.t += 2
    check("300초 뒤 다시 된다", not srv.blocked("10.0.0.7") and accepted(port))

    print("  60초 창이 지나면 다시 센다")
    for _ in range(lan_server.BAD_LIMIT - 1):
        srv.note_bad("10.0.0.9")
    clock.t += lan_server.BAD_WINDOW + 1
    srv.note_bad("10.0.0.9")
    check("창이 지난 뒤의 한 번으로는 거절하지 않는다", not srv.blocked("10.0.0.9"))
    for i in range(lan_server.TRACK_MAX + 10):
        srv.bad[f"10.8.{i // 256}.{i % 256}"] = [1, clock.t - 1000, 0]
    srv.note_bad("10.0.0.10")
    check("표가 커지면 지난 것을 정리한다", len(srv.bad) <= lan_server.TRACK_MAX, len(srv.bad))
    check("연결 수가 돌아온다", idle(srv), (srv.conns, srv.per_ip))
    stop(srv)


def test_release_paths():
    print("세기와 돌려주기는 한 번씩 - 일하는 스레드를 못 띄워도")
    srv, port = start()

    def boom(*a):
        raise RuntimeError("스레드를 못 띄움 (시험)")
    srv._start = boom
    check("스레드를 못 띄우면 연결을 닫는다", refused(port))
    check("그때 센 것을 돌려준다", srv.conns == 0 and not srv.per_ip, (srv.conns, srv.per_ip))
    del srv._start
    check("그 뒤 정상 연결은 된다", get_status(port) == 401)
    check("연결 수가 돌아온다", idle(srv), (srv.conns, srv.per_ip))
    stop(srv)


def test_client_ip():
    print("보낸 쪽 주소 client_ip")
    none = lan_config.parse({"listen": "10.0.0.5", "allow": ["10.0.0.0/8"]})
    check("믿을 프록시가 없으면 머리글을 버린다", lan_server.client_ip("10.0.0.7", "1.2.3.4", none) == "10.0.0.7")
    one = lan_config.parse({"listen": "10.0.0.5", "allow": ["10.0.0.0/8"], "trusted_proxies": ["10.0.0.9"]})
    check("프록시가 아닌 곳에서 온 머리글도 버린다", lan_server.client_ip("10.0.0.7", "1.2.3.4", one) == "10.0.0.7")
    check("프록시 10.0.0.9: '1.2.3.4, 10.0.0.7' → 10.0.0.7 (오른쪽부터 첫 비프록시)",
          lan_server.client_ip("10.0.0.9", "1.2.3.4, 10.0.0.7", one) == "10.0.0.7")
    check("머리글이 없으면 peer", lan_server.client_ip("10.0.0.9", None, one) == "10.0.0.9"
          and lan_server.client_ip("10.0.0.9", "", one) == "10.0.0.9")
    two = lan_config.parse({"listen": "10.0.0.5", "allow": ["10.0.0.0/8"], "trusted_proxies": ["10.0.0.9", "10.0.0.8"]})
    check("프록시 둘: '10.0.0.7, 10.0.0.8' → 10.0.0.7", lan_server.client_ip("10.0.0.9", "10.0.0.7, 10.0.0.8", two) == "10.0.0.7")
    check("글자가 IP 가 아니면 peer", lan_server.client_ip("10.0.0.9", "evil.example", one) == "10.0.0.9"
          and lan_server.client_ip("10.0.0.9", "1.2.3.4, nonsense", one) == "10.0.0.9"
          and lan_server.client_ip("10.0.0.9", "10.0.0.7:abc", one) == "10.0.0.9"
          and lan_server.client_ip("10.0.0.9", "10.0.0.7,,", one) == "10.0.0.9")
    # ② 전체 검토 5 (2026-11-24): 'IPv4:포트' 는 포트를 떼고 읽는다 (예전에는 peer 로 버렸다)
    check("'IPv4:포트' 는 포트를 뗀다", lan_server.client_ip("10.0.0.9", "10.0.0.7:5555", one) == "10.0.0.7")
    check("오른쪽 비프록시에서 멈춘다 - 그 왼쪽의 글자는 보지 않는다",
          lan_server.client_ip("10.0.0.9", "junk, 10.0.0.7", one) == "10.0.0.7")
    check("모두 프록시면 가장 왼쪽", lan_server.client_ip("10.0.0.9", "10.0.0.8, 10.0.0.9", two) == "10.0.0.8")
    check("대역으로 적은 프록시", lan_server.client_ip("10.1.0.3", "10.0.0.7",
          lan_config.parse({"listen": "10.0.0.5", "allow": ["10.0.0.0/8"], "trusted_proxies": ["10.1.0.0/16"]})) == "10.0.0.7")
    check("IPv4 를 담은 IPv6 는 IPv4 글자로", lan_server.client_ip("10.0.0.9", "::ffff:10.0.0.7", one) == "10.0.0.7")


try:
    test_constants()
    test_open_guards()
    test_outside_allow_closed_before_tls()
    test_slow_handshake_cut()
    test_per_ip_conn_cap()
    test_per_ip_minute_cap()
    test_bad_signature_block()
    test_release_paths()
    test_client_ip()
finally:
    for s, r in SERVERS:
        try:
            s.shutdown()
            s.server_close()
        except Exception:
            pass
        r.close()
    shutil.rmtree(TMP, ignore_errors=True)

print(f"\n실패 {len(fails)}건" + (": " + ", ".join(fails) if fails else ""))
sys.exit(1 if fails else 0)
