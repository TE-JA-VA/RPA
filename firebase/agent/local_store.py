# -*- coding: utf-8 -*-
"""스탠드얼론: 이 PC 의 로컬 서버(local_server.py)에 붙는 클라이언트 - fb.Client 와 같은 메서드 (설계 2026-11-23-standalone 6.2).

에이전트·ACTOR 실행·옵저버가 fb.Client 대신 쓴다 (client_for 가 고른다). Firebase·Google 에는 연결하지 않는다.

서로 확인 (검토 2026-11-23 1번): 열쇠 파일의 값은 **보내지 않는다**. 요청마다 열쇠로 만든 서명(HMAC)을 싣고, 서버도 응답과 구독
이벤트마다 같은 열쇠로 서명해 돌려준다 - 클라이언트는 서명이 맞는 응답만 쓴다. 다른 프로그램이 포트를 먼저 잡아도 열쇠를 얻지 못하고,
그 프로그램이 준 '명령' 은 서명이 없어 버려진다 (AuthError - 에이전트는 멈췄다 다시 켜진다).
오류는 fb 와 같은 예외로 올린다 (HttpError·AuthError) - 에이전트의 다시 시도·큐 코드가 그대로 돈다.

사내 서버(lan, 계획 2026-11-24-lan-2-network Task 5): 주소가 https 면 등록 글로 받은 우리 인증 기관(ca_pem) 하나만 믿는다
(윈도우 신뢰 저장소를 읽지 않는다, 이름 확인 켬). 주소의 호스트가 IP 글자면 사설·루프백만, 이름이면 받는다.
인증서 확인이 실패하면 AuthError(0, CERT_FAILED) - 에이전트가 '다른 서버' 로 본다. 단독(나)은 지금처럼 http·127.0.0.1 만.
"""
import email.utils
import hmac
import json
import re
import secrets
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

import fb
# 서명은 ap_sign 에 있다 (서버와 같이 쓴다 - 서버는 이 모듈을 불러오지 않는다). 같은 이름을 그대로 내보낸다.
from ap_sign import (H_NONCE, H_PC, H_ROLE, H_SIGN, H_TIME, ROLES, _digest, _mac, event_mac,  # noqa: F401
                     request_mac, request_mac2, response_mac)

LOCAL_HOSTS = ("127.0.0.1", "localhost")
PORT = 8781                      # local_server.PORT 와 같다 (서버 모듈을 불러오지 않으려고 여기에도 둔다 - 시험이 같은지 본다)
NOT_VERIFIED = "SERVER_NOT_VERIFIED"     # 답한 쪽이 우리 로컬 서버가 아니다 (서명이 없거나 틀림) - 열쇠가 바뀐 경우도 여기로 온다
PC_DISABLED = "PC_DISABLED"              # 사내 서버 관리자가 이 PC 를 사용 중지했다 (서명된 403)
PC_REMOVED = "PC_REMOVED"                # 사내 서버 등록부에서 이 PC 를 지웠다 (서명된 403)
CERT_FAILED = "SERVER_CERT_FAILED"       # 사내 서버(https)의 인증서를 우리 인증 기관으로 확인하지 못했다 - 다른 서버로 본다
_HOST_NAME_RE = re.compile(r"[A-Za-z0-9.-]{1,253}")    # https 주소의 이름 꼴 (lan_config 의 names 와 같은 글자)


def keys_dir():
    """로컬 서버 열쇠 파일(agent.key·relay.key)이 있는 폴더 - local_server.data_dir() 과 같은 자리 (만들지는 않는다)."""
    import os
    import rpa_status
    return os.path.join(rpa_status.install_root(), "standalone")


# --- 서명 머리글 (서명 함수는 ap_sign) ---------------------------------------
def sign_headers(key, role, method, target, body=b"", now_ms=None, nonce=None, pc_id=None):
    """요청에 실을 머리글 {역할, 시각, nonce, 서명}. 열쇠는 들어가지 않는다.
    pc_id 가 있으면 사내 서버(ap2) - PC 번호 머리글을 싣고 request_mac2 로 서명한다. 없으면 단독(ap1) 그대로."""
    ts = str(int(time.time() * 1000) if now_ms is None else int(now_ms))
    nonce = nonce or secrets.token_hex(16)
    if pc_id is None:
        return {H_ROLE: role, H_TIME: ts, H_NONCE: nonce, H_SIGN: request_mac(key, role, method, target, ts, nonce, body)}
    return {H_ROLE: role, H_PC: pc_id, H_TIME: ts, H_NONCE: nonce,
            H_SIGN: request_mac2(key, pc_id, role, method, target, ts, nonce, body)}


def _error_body(raw):
    """거절 본문 JSON dict (아니면 None)."""
    try:
        obj = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    return obj if isinstance(obj, dict) else None


def _clock_ms(raw):
    """서명된 401 본문이 {"error": "clock", "server_ms": <정수>} 이면 서버 시각(ms), 아니면 None."""
    obj = _error_body(raw)
    if obj is None or obj.get("error") != "clock":
        return None
    ms = obj.get("server_ms")
    return ms if isinstance(ms, int) and not isinstance(ms, bool) else None


def _lan_tls(url, ca_pem):
    """사내 서버 https 주소를 검사하고 우리 인증 기관(ca_pem) 하나만 믿는 TLS 컨텍스트를 만든다. 틀리면 ValueError.
    호스트가 IP 글자면 사설·루프백(lan_config.PRIVATE_NETS)만, 이름이면 받는다 (PC 가 풀어 본 주소 확인은 ⑤).
    lan_config 는 여기서만 불러온다 - 일반(클라우드) 버전 경로는 불러오지 않는다."""
    import ipaddress
    import lan_config
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname
    if parts.scheme != "https" or not host:
        raise ValueError("사내 서버 주소의 형식이 올바르지 않습니다.")
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        addr = None
    if addr is not None:
        if addr.version == 6 and addr.ipv4_mapped is not None:
            addr = addr.ipv4_mapped
        if not any(addr.version == n.version and addr in n for n in lan_config.PRIVATE_NETS):
            raise ValueError("사내 서버 주소가 사내(사설) 주소가 아닙니다.")
    elif not _HOST_NAME_RE.fullmatch(host):
        raise ValueError("사내 서버 주소의 이름이 올바르지 않습니다.")
    parts.port                                   # 포트 글자가 틀리면 여기서 ValueError
    if not isinstance(ca_pem, str) or not ca_pem.strip():
        raise ValueError("사내 서버의 인증 기관 정보가 없습니다. PC 를 다시 등록해 주세요.")
    try:
        # cadata 를 주면 윈도우·리눅스 신뢰 저장소를 읽지 않는다 - 우리 인증 기관만. 이름 확인·인증서 확인은 켜진 채로.
        ctx = ssl.create_default_context(cadata=ca_pem)
    except (ssl.SSLError, ValueError, TypeError):
        raise ValueError("사내 서버의 인증 기관 정보를 읽지 못했습니다.") from None
    if not ctx.get_ca_certs():
        raise ValueError("사내 서버의 인증 기관 정보를 읽지 못했습니다.")
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


def _build_open(ctx):
    """프록시를 따르지 않는 opener 의 open. ctx 가 있으면 https 는 그 컨텍스트(우리 인증 기관)로만."""
    if ctx is None:
        return urllib.request.build_opener(urllib.request.ProxyHandler({})).open
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=ctx)).open


def _cert_failed(e):
    """인증서 확인 실패인가 (그대로, 또는 urllib 의 URLError 에 싸여)."""
    if isinstance(e, ssl.SSLCertVerificationError):
        return True
    return isinstance(e, urllib.error.URLError) and isinstance(e.reason, ssl.SSLCertVerificationError)


class Client:
    def __init__(self, cfg, opener=None, clock=time.time):
        url = str(cfg.get("server_url") or "")
        parts = urllib.parse.urlsplit(url)
        self._ctx = None
        if cfg.get("lan") and parts.scheme == "https":
            self._ctx = _lan_tls(url, cfg.get("ca_pem"))      # 사내 서버: 우리 인증 기관만 믿는다
        elif parts.scheme != "http" or parts.hostname not in LOCAL_HOSTS:
            raise ValueError("로컬 서버 주소가 이 PC(127.0.0.1)가 아닙니다.")
        if not cfg.get("key"):
            raise ValueError("로컬 서버 열쇠가 없습니다.")
        self._base = url.rstrip("/")
        self._key = cfg["key"]
        self._role = cfg.get("role") if cfg.get("role") in ROLES else "agent"
        # 프록시 설정을 따르지 않는다 - 이 PC 안의 연결이 회사 프록시로 나가면 안 된다 (사내 서버도 같다).
        # 구독(stream)도 같은 opener 를 쓴다 - https 면 우리 인증 기관만 믿는 길.
        self._open = opener or _build_open(self._ctx)
        self._now = clock
        self._offset = 0.0
        # 사내 서버(lan): 모든 요청을 PC 번호로 서명(ap2)하고, 서명된 시계 답을 받으면 차이를 더한다. 단독은 둘 다 그대로 (pc None·차이 0).
        self._pc = None
        self._skew_ms = 0
        if cfg.get("lan"):
            import pc_registry               # 일반·단독 버전 경로는 불러오지 않는다
            pc = cfg.get("pc_id")
            if not isinstance(pc, str) or not pc_registry.PC_RE.fullmatch(pc):
                raise ValueError("사내 서버에 등록한 PC 번호가 올바르지 않습니다.")
            self._pc = pc

    # --- fb.Client 와 같은 겉모양 ----------------------------------------
    def server_now(self):
        """서버 시각 (초). 같은 PC 라 PC 시각과 같지만 fb 와 같은 길로 둔다."""
        return self._now() + self._offset

    def token(self):
        """fb 는 ID 토큰을 돌려준다 - 여기는 보낼 토큰이 없다 (열쇠는 내보내지 않는다)."""
        return ""

    def renew(self):
        """fb 는 토큰을 새로 받는다 - 여기는 할 일이 없다."""

    def _seen(self, resp):
        try:
            self._offset = email.utils.parsedate_to_datetime(resp.headers["Date"]).timestamp() - self._now()
        except Exception:
            pass

    def _request(self, method, path, value=None, accept=None, timeout=30, retry=True):
        """서명한 요청을 보낸다 → (응답, nonce). path 는 '/db/…' 처럼 서버에 보내는 경로+질의.
        사내 서버: 서명된 401 clock 이면 서버 시각과의 차이를 기억하고 그 요청을 한 번만 다시 보낸다 (새 nonce).
        서명된 403 pc_disabled·pc_removed 는 AuthError(403, PC_DISABLED·PC_REMOVED)."""
        body = b"" if value is None and method in ("GET", "DELETE") else json.dumps(value, ensure_ascii=False).encode("utf-8")
        headers = sign_headers(self._key, self._role, method, path, body, now_ms=self._now() * 1000 + self._skew_ms, pc_id=self._pc)
        headers["Content-Type"] = "application/json"
        if accept:
            headers["Accept"] = accept
        req = urllib.request.Request(self._base + path, data=body or None, headers=headers, method=method)
        try:
            return self._open(req, timeout=timeout), headers[H_NONCE]
        except urllib.error.HTTPError as e:
            raw = e.read()
            self._verify(e.headers, headers[H_NONCE], e.code, raw)     # 서명 없는 거절은 우리 서버의 답이 아니다
            if self._pc is not None:
                if e.code == 401 and retry:
                    server_ms = _clock_ms(raw)
                    if server_ms is not None:
                        self._skew_ms = server_ms - int(self._now() * 1000)
                        return self._request(method, path, value, accept, timeout, retry=False)
                if e.code == 403:
                    err = (_error_body(raw) or {}).get("error")
                    code = {"pc_disabled": PC_DISABLED, "pc_removed": PC_REMOVED}.get(err) if isinstance(err, str) else None
                    if code:
                        raise fb.AuthError(403, code) from None
            raise fb.HttpError(e.code, raw.decode("utf-8", "replace")) from None
        except (urllib.error.URLError, ssl.SSLCertVerificationError) as e:
            if self._ctx is not None and _cert_failed(e):
                raise fb.AuthError(0, CERT_FAILED) from None       # 우리 인증 기관이 서명한 서버가 아니다
            raise                                                  # 그 밖의 연결 오류는 지금처럼 (큐에 쌓는 쪽)

    def _verify(self, headers, nonce, status, raw):
        got = (headers.get(H_SIGN) if headers is not None else None) or ""
        if not hmac.compare_digest(got, response_mac(self._key, nonce, status, raw)):
            raise fb.AuthError(0, NOT_VERIFIED) from None

    def _json(self, method, path, value=None):
        resp, nonce = self._request(method, path, value)
        raw = resp.read()
        self._verify(resp.headers, nonce, resp.status, raw)
        self._seen(resp)
        return json.loads(raw.decode("utf-8")) if raw else None

    @staticmethod
    def _db(path, params=None):
        path = "/".join(urllib.parse.quote(seg, safe="-_~$:@!") for seg in path.strip("/").split("/"))
        q = f"?{urllib.parse.urlencode(params)}" if params else ""
        return f"/db/{path}.json{q}"

    # --- 자리 (RTDB 꼴) --------------------------------------------------
    def put(self, path, value):
        return self._json("PUT", self._db(path, {"print": "silent"}), value)

    def patch(self, path, value):
        return self._json("PATCH", self._db(path, {"print": "silent"}), value)

    def get(self, path, params=None):
        return self._json("GET", self._db(path, params))

    def delete(self, path):
        return self._json("DELETE", self._db(path))

    def stream(self, path, params=None, timeout=90):
        """SSE 구독 - fb.Client.stream 과 같은 (event, data) 제너레이터. 서버가 닫으면 끝난다.
        서버는 30초마다 keep-alive 를 보낸다 - timeout 초 동안 조용하면 끊긴 연결로 보고 예외.
        이벤트마다 서버 서명(mac 줄)을 확인한다 - 틀리면 AuthError."""
        resp, nonce = self._request("GET", self._db(path, params), accept="text/event-stream", timeout=timeout)
        try:
            self._verify(resp.headers, nonce, resp.status, b"")
            seq, event, raw, mac = 0, None, None, ""
            for line in resp:
                line = line.decode("utf-8", "replace").rstrip("\r\n")
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    raw = line[5:].strip()
                elif line.startswith("mac:"):
                    mac = line[4:].strip()
                elif line == "" and event is not None:
                    seq += 1
                    if not hmac.compare_digest(mac, event_mac(self._key, nonce, seq, event, raw or "")):
                        raise fb.AuthError(0, NOT_VERIFIED)
                    try:
                        data = json.loads(raw) if raw else None
                    except ValueError:
                        data = None
                    yield event, data
                    event, raw, mac = None, None, ""
        finally:
            close = getattr(resp, "close", None)
            if close:
                close()

    # --- 실행 기록 (Firestore 꼴) ----------------------------------------
    def fs_create(self, path, fields, doc_id):
        """문서를 만든다. fields 는 fb.fs_fields 가 만든 Firestore 꼴 - 보통 값으로 풀어 보낸다. 이미 있으면 False."""
        plain = {k: fb.fs_value(v) for k, v in fields.items()}
        try:
            self._json("POST", f"/fs/{path.strip('/')}?id={urllib.parse.quote(doc_id, safe='')}", plain)
        except fb.HttpError as e:
            if e.status == 409:
                return False
            raise
        return True

    def fs_get(self, path):
        """문서 하나의 값 dict (없으면 None)."""
        try:
            return self._json("GET", f"/fs/{path.strip('/')}")
        except fb.HttpError as e:
            if e.status == 404:
                return None
            raise

    def fs_sum(self, parent, collection, field, since=None):
        q = {"parent": parent.strip("/"), "collection": collection, "field": field}
        if since:
            q["since"] = since
        return (self._json("GET", f"/fs-sum?{urllib.parse.urlencode(q)}") or {}).get("sum") or 0


def enroll(text, guid, host, opener=None, rand_hex=None, nonce=None):
    """사내 서버에 이 PC 를 등록한다 (설계 6.4) → {"server_url", "pc_id", "agent_key", "relay_key"} (+ https 면 "ca_pem").
    text 는 관리자가 준 등록 글(APE1.…). 토큰은 보내지 않고 증명(HMAC)만 보낸다 - 열쇠는 토큰과 이 PC 의 난수로 양쪽이 따로 만든다.
    서버 답은 새 에이전트 열쇠와 이 요청의 nonce 로 서명되어 있어야 한다 (아니면 AuthError(0, NOT_VERIFIED)).
    서버 거절(서명 없음)은 HttpError - 본문의 error 코드(unknown·expired·bad_proof·duplicate·seats) 그대로.
    https 주소면 등록 글의 ca(우리 인증 기관)만 믿고 보낸다 - 인증서 확인 실패는 AuthError(0, CERT_FAILED).
    rand_hex·nonce 는 시험용 (없으면 새로 만든다). 등록 글 꼴이 틀리거나, http 인데 이 PC 가 아니거나,
    https 인데 ca 가 없거나 사설 주소가 아니면 ValueError."""
    import pc_registry                       # 일반·단독 버전 경로는 불러오지 않는다
    info = pc_registry.decode_enrollment(text)
    url = info["url"].rstrip("/")
    parts = urllib.parse.urlsplit(url)
    ctx = None
    if parts.scheme == "https":                                             # ② 사내 주소 - 등록 글의 인증 기관만 믿는다
        if not info.get("ca"):
            raise ValueError("등록 글에 사내 서버의 인증 기관 정보가 없습니다.")
        ctx = _lan_tls(url, info["ca"])
    elif parts.scheme != "http" or parts.hostname not in LOCAL_HOSTS:      # http 는 이 PC 만
        raise ValueError("등록 글의 서버 주소가 이 PC(127.0.0.1)가 아닙니다.")
    pc_id, token = info["pc"], info["token"]
    if not pc_registry.PC_RE.fullmatch(pc_id):
        raise ValueError("등록 글의 PC 번호가 올바르지 않습니다.")
    rand_hex = rand_hex or secrets.token_hex(32)
    nonce = nonce or secrets.token_hex(16)
    proof = pc_registry.enroll_proof(token, pc_id, rand_hex, guid, host)
    agent_key, relay_key = pc_registry.derive_keys(token, rand_hex)
    body = json.dumps({"v": 1, "pc": pc_id, "rand": rand_hex, "guid": guid, "host": host, "nonce": nonce, "proof": proof},
                      ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url + "/enroll", data=body, headers={"Content-Type": "application/json"}, method="POST")
    open_ = opener or _build_open(ctx)
    try:
        resp = open_(req, timeout=30)
    except urllib.error.HTTPError as e:
        raise fb.HttpError(e.code, e.read().decode("utf-8", "replace")) from None
    except (urllib.error.URLError, ssl.SSLCertVerificationError) as e:
        if ctx is not None and _cert_failed(e):
            raise fb.AuthError(0, CERT_FAILED) from None
        raise
    try:
        raw = resp.read()
        got = (resp.headers.get(H_SIGN) if resp.headers is not None else None) or ""
        if resp.status != 200 or not hmac.compare_digest(got, response_mac(agent_key, nonce, resp.status, raw)):
            raise fb.AuthError(0, NOT_VERIFIED)
    finally:
        close = getattr(resp, "close", None)
        if close:
            close()
    out = {"server_url": url, "pc_id": pc_id, "agent_key": agent_key, "relay_key": relay_key}
    if ctx is not None:
        out["ca_pem"] = info["ca"]               # 사내 서버(https): 설정에 두고 Client 가 이 인증 기관만 믿는다
    return out


def client_for(cfg):
    """설정에 맞는 클라이언트 - 스탠드얼론 설정이면 로컬 서버, 아니면 Firebase."""
    return Client(cfg) if cfg.get("standalone") else fb.Client(cfg)
