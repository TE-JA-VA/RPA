# -*- coding: utf-8 -*-
"""사내 서버의 사내망 창구 LanServer (계획 2026-11-24-lan-2-network Task 3, 설계 6.3·6.4 끝줄).

웹(8443)·에이전트(8444) 포트 하나에 LanServer 하나. 처리기는 ① 의 local_server.Handler 그대로다.
- 받기 고리에서 (TLS 악수 전에) 보낸 쪽 소켓 주소로 거른다: ① 허용 대역 (웹 쪽에 proxy_only 면 믿을 프록시만)
  ② 서버 전체 동시 연결 deploy.max_conn ③ 주소마다 동시 연결 PER_IP_CONN ④ 주소마다 분당 연결 PER_IP_MIN
  ⑤ 서명 틀림으로 거절 중인 주소 (blocked). 하나라도 걸리면 응답 없이 닫는다 - 사내망 밖 주소는 서버 인증서도 받지 못한다.
- 듣는 소켓은 TLS 로 감싸지 않는다. 악수는 연결마다 일하는 스레드에서 HANDSHAKE_SEC 안에 (local_phone.PhoneServer 와 같은 방식) -
  악수를 끄는 연결 하나가 받기 고리를 세우지 못하고, 한 바이트씩 보내 시간 제한을 늘리는 연결도 타이머가 끊는다.
- 연결 수는 받을 때 한 번 세고 끝날 때 한 번 돌려준다 (_release) - 악수 실패·처리 중 예외·스레드를 못 띄운 경우 모두.
  LocalServer.process_request·process_request_thread 의 세기는 거치지 않는다 (두 번 세지 않게 여기서 함께 센다).
- 보낸 쪽 주소 client_ip: 믿을 프록시에서 온 연결만 X-Forwarded-For 를 오른쪽부터 읽는다 (설계 6.3 '그때만 믿기').
기록에 열쇠·서명을 싣지 않는다. 이름 풀이(DNS)를 하지 않는다. 표준 라이브러리만.
"""
import dataclasses
import socket
import ssl
import threading
import time

import lan_config
import local_server

PER_IP_CONN = 16          # 주소마다 동시 연결
# 주소마다 분당 요청. 받기 고리에서 연결을 센다 - 처리기(local_server.Handler)는 HTTP/1.0 이라 연결 하나에 요청 하나만
# 받고 닫으므로 (keep-alive 없음) 분당 연결 수가 곧 분당 요청 수다. 처리기가 keep-alive 를 쓰게 되면 요청도 따로 세야 한다
PER_IP_MIN = 600
HANDSHAKE_SEC = 5         # TLS 악수
BAD_LIMIT = 20            # 서명 틀림이 BAD_WINDOW 초 안에 이만큼이면
BAD_WINDOW = 60
BAD_BLOCK = 300           # 그 주소를 이만큼 거절
TRACK_MAX = 5000          # 분당 연결·서명 틀림 표에 기억하는 주소 수
SIDES = ("web", "agent")


def tls_context(cert, key):
    """사내망 포트의 TLS: 서버, 1.2 이상, 1.2 는 ECDHE+AESGCM·ECDHE+CHACHA20 만, 재협상 끔 (local_phone.tls_context 와 같은 꼴)."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.set_ciphers("ECDHE+AESGCM:ECDHE+CHACHA20")
    ctx.options |= getattr(ssl, "OP_NO_RENEGOTIATION", 0)
    ctx.load_cert_chain(cert, key)
    return ctx


def client_ip(peer, xff, cfg):
    """보낸 쪽 주소. peer(소켓 주소)가 믿을 프록시가 아니거나 X-Forwarded-For 가 없으면 peer.
    믿을 프록시면 머리글을 쉼표로 나눠 오른쪽부터 읽어 믿을 프록시가 아닌 첫 주소 (모두 프록시면 가장 왼쪽).
    읽다가 IP 글자가 아닌 것(빈 칸·이름·포트 붙은 것)을 만나면 peer - 지어 보낸 머리글을 믿지 않는다."""
    if not xff or not cfg.is_proxy(peer):
        return peer
    last = None
    for item in reversed(xff.split(",")):
        a = lan_config._ip(item.strip())
        if a is None:
            return peer
        last = str(a)
        if not cfg.is_proxy(last):
            return last
    return last or peer


class LanServer(local_server.LocalServer):
    """사내망 포트 하나 (웹 또는 에이전트). 생성 인자는 LocalServer 와 같고, 만든 뒤 cfg·tls·side 를 단다 (_open).
    tls 가 None 이면 평문 - web_plain 의 웹 포트(127.0.0.1)뿐. cfg 가 없으면 모든 연결을 닫는다."""

    def __init__(self, server_address, RequestHandlerClass, bind_and_activate=True):
        if ":" in str(server_address[0]):
            self.address_family = socket.AF_INET6       # IPv6 사내 주소 (ULA)
        self.cfg, self.tls, self.side = None, None, "agent"
        self.conn_lock, self.conns, self.nonces, self.streams = threading.Lock(), 0, {}, {}
        self.per_ip, self.minute, self.bad = {}, {}, {}
        self.stopping = threading.Event()
        self.clock = time.monotonic                     # 분당 연결·서명 틀림 거절의 시계 (시험이 바꿔 끼운다)
        super().__init__(server_address, RequestHandlerClass, bind_and_activate)

    def peer_ip(self, client_address):
        """보낸 쪽 소켓 주소를 읽는 한 곳 (시험이 바꿔 끼워 여러 주소를 흉내 낸다). IPv4 를 담은 IPv6 는 IPv4 글자로."""
        a = lan_config._ip(client_address[0])
        return str(a) if a is not None else str(client_address[0])

    def _trim(self, table, keep):
        """표가 TRACK_MAX 를 넘으면 지난 것을 지우고, 그래도 넘으면 비운다 (local_phone.PhoneServer._trim 과 같다)."""
        if len(table) > TRACK_MAX:
            for k in [k for k, v in table.items() if not keep(v)]:
                del table[k]
            if len(table) > TRACK_MAX:
                table.clear()

    def _admit(self, ip):
        """받아도 되는 주소인가 (허용 대역, 웹 쪽 proxy_only 면 믿을 프록시만)."""
        cfg = self.cfg
        if cfg is None or not cfg.allowed(ip):
            return False
        return not (self.side == "web" and cfg.proxy_only and not cfg.is_proxy(ip))

    def process_request(self, request, client_address):
        """받기 고리에서 부른다 - 걸리면 응답 없이 닫고, 통과하면 연결 수를 한 번 세고 일하는 스레드로."""
        ip = self.peer_ip(client_address)
        ok = self._admit(ip)
        if ok:
            now = self.clock()
            with self.conn_lock:
                minute = self.minute.get(ip)
                if minute is None or now - minute[0] >= 60:
                    minute = self.minute[ip] = [now, 0]
                minute[1] += 1
                self._trim(self.minute, lambda v: now - v[0] < 60)
                e = self.bad.get(ip)
                ok = (self.conns < self.deploy.max_conn and self.per_ip.get(ip, 0) < PER_IP_CONN
                      and minute[1] <= PER_IP_MIN and not (e and e[2] > now))
                if ok:
                    self.conns += 1
                    self.per_ip[ip] = self.per_ip.get(ip, 0) + 1
        if not ok:
            self.shutdown_request(request)
            return
        try:
            self._start(request, client_address, ip)
        except Exception:
            self._release(ip)
            self.shutdown_request(request)

    def _start(self, request, client_address, ip):
        threading.Thread(target=self.process_request_thread, args=(request, client_address, ip), daemon=True).start()

    def _release(self, ip):
        with self.conn_lock:
            self.conns -= 1
            n = self.per_ip.get(ip, 1) - 1
            if n > 0:
                self.per_ip[ip] = n
            else:
                self.per_ip.pop(ip, None)

    def process_request_thread(self, request, client_address, ip=None):
        """일하는 스레드: TLS 악수(HANDSHAKE_SEC) → 처리기. 끝나면 연결 수를 돌려주고 소켓을 닫는다."""
        ip = ip if ip is not None else self.peer_ip(client_address)
        conn = None
        try:
            if self.tls is not None:
                conn = self.tls.wrap_socket(request, server_side=True, do_handshake_on_connect=False)
                # 감싼 뒤에는 request 가 떼어져(detach) 있다 - 타이머는 감싼 소켓의 TCP 를 끊는다 (SSLSocket.shutdown 은 거치지 않는다)
                timer = threading.Timer(HANDSHAKE_SEC, self._kill, args=(conn,))
                conn.settimeout(HANDSHAKE_SEC)
                timer.start()
                try:
                    conn.do_handshake()
                finally:
                    timer.cancel()
            else:
                conn = request
            self.finish_request(conn, client_address)
        except Exception:
            pass                     # 악수 실패(TLS 없이 온 HTTP·시간 넘김)·끊김 - 응답 없이 닫는다. 처리기 안의 오류는 처리기가 기록한다
        finally:
            self._release(ip)
            self.shutdown_request(conn if conn is not None else request)   # 안에서 OSError 를 삼킨다
            try:
                request.close()      # 감쌌으면 이미 떼어진 소켓 - 아무 일도 하지 않는다
            except OSError:
                pass

    @staticmethod
    def _kill(sock):
        try:
            socket.socket.shutdown(sock, socket.SHUT_RDWR)
        except OSError:
            pass

    # --- 서명 틀림 거절 (Task 4 의 처리기가 note_bad 를 부른다) ---
    def blocked(self, ip):
        now = self.clock()
        with self.conn_lock:
            e = self.bad.get(ip)
            return bool(e and e[2] > now)

    def note_bad(self, ip):
        """서명 틀림 한 번 - 그 주소에서 BAD_WINDOW 초 안에 BAD_LIMIT 번이면 BAD_BLOCK 초 동안 새 연결을 닫는다.
        표 = 주소 → [틀린 수, 세기 시작, 거절 끝]."""
        now = self.clock()
        start = False
        with self.conn_lock:
            e = self.bad.get(ip)
            if e is None or now - e[1] > BAD_WINDOW:
                e = self.bad[ip] = [0, now, e[2] if e else 0]
            e[0] += 1
            if e[0] >= BAD_LIMIT:
                e[0], e[1], e[2] = 0, now, now + BAD_BLOCK
                start = True
            self._trim(self.bad, lambda v: v[2] > now or now - v[1] <= BAD_WINDOW)
        if start and getattr(self, "folder", None):
            local_server.log(self.folder, f"주소 거절 시작  주소={ip}  까닭=서명 틀림 {BAD_LIMIT}번  {BAD_BLOCK}초")


def _open(cfg, side, address, tls, store, runs, lic, registry, folder=None, web=None, phone=None):
    """사내망 포트 하나를 만들어 묶는다 (serve_forever 는 부르는 쪽이). make_lan_servers 가 부른다.
    사설·루프백 주소에만 듣는다. 에이전트 쪽은 늘 TLS. 등록부가 꼭 있어야 한다 (사내 서버 배치 LAN). 포트가 쓰이는 중이면 OSError.
    준비는 단독 make_server 와 같은 local_server._prepare 로."""
    if side not in SIDES:
        raise ValueError(f"side 는 web·agent 가운데 하나여야 합니다: {side!r}")
    if side == "agent" and tls is None:
        raise ValueError("에이전트 포트는 TLS 로만 엽니다.")
    a = lan_config._ip(str(address[0]))
    if a is None or not lan_config._private_ip(a):
        raise ValueError(f"사내 서버는 사설·루프백 주소에만 듣습니다: {address[0]}")
    if registry is None:
        raise ValueError("사내망 포트는 PC 등록부가 있어야 엽니다.")
    srv = LanServer((str(a), address[1]), local_server.Handler, bind_and_activate=False)
    local_server._prepare(srv, store, runs, lic, None, registry, folder=folder, web=web, phone=phone)
    srv.cfg, srv.tls, srv.side = cfg, tls, side
    try:
        srv.server_bind()
        srv.server_activate()
    except BaseException:
        srv.server_close()
        raise
    return srv


def make_lan_servers(store, runs, lic, registry, web, cfg, cert, key, ca_pem, phone=None):
    """사내망 두 포트 → (웹, 에이전트) LanServer (serve_forever 는 부르는 쪽이). 둘 다 같은 store·runs·registry 를 쓰고 길만 나눈다.
    웹: cfg.web_listen:cfg.web_port, web_plain 이면 평문 (같은 장비의 프록시가 TLS 를 끝낸 모양 - 127.0.0.1 에서만), 아니면 TLS.
    에이전트: cfg.listen:cfg.agent_port, 늘 TLS (우리 인증 기관의 서버 인증서 - 에이전트는 그 인증 기관만 믿는다).
    웹 창구(web, local_web.Web)에 등록 글의 서버 주소 public_url(이름이 아니라 IP - 사내 PC 가 이름을 못 풀어도 붙고, 서버 인증서
    SAN 에 늘 있다)·인증 기관 글 lan_ca_pem·설정 cfg 를 적는다. 포트 0(시험)이면 묶인 포트로 cfg 를 고쳐 두 서버·웹 창구가 같이 쓴다.
    한쪽을 못 열면 다른 쪽도 닫고 OSError·ValueError 를 그대로 낸다."""
    tls = tls_context(cert, key)
    w = _open(cfg, "web", (cfg.web_listen, cfg.web_port), None if cfg.web_plain else tls, store, runs, lic, registry,
              web=web, phone=phone)
    try:
        a = _open(cfg, "agent", (cfg.listen, cfg.agent_port), tls, store, runs, lic, registry, web=web, phone=phone)
    except BaseException:
        w.server_close()
        raise
    ports = (w.server_address[1], a.server_address[1])
    if ports != (cfg.web_port, cfg.agent_port):
        cfg = dataclasses.replace(cfg, web_port=ports[0], agent_port=ports[1])
        w.cfg = a.cfg = cfg
    if web is not None:
        web.public_url = f"https://{lan_config._host(cfg.listen, cfg.agent_port)}"
        web.lan_ca_pem = ca_pem
        web.cfg = cfg
    return w, a
