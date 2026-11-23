# -*- coding: utf-8 -*-
"""스탠드얼론: 이 PC 의 로컬 서버(local_server.py)에 붙는 클라이언트 - fb.Client 와 같은 메서드 (설계 2026-11-23-standalone 6.2).

에이전트·ACTOR 실행·옵저버가 fb.Client 대신 쓴다 (client_for 가 고른다). Firebase·Google 에는 연결하지 않는다.

서로 확인 (검토 2026-11-23 1번): 열쇠 파일의 값은 **보내지 않는다**. 요청마다 열쇠로 만든 서명(HMAC)을 싣고, 서버도 응답과 구독
이벤트마다 같은 열쇠로 서명해 돌려준다 - 클라이언트는 서명이 맞는 응답만 쓴다. 다른 프로그램이 포트를 먼저 잡아도 열쇠를 얻지 못하고,
그 프로그램이 준 '명령' 은 서명이 없어 버려진다 (AuthError - 에이전트는 멈췄다 다시 켜진다).
오류는 fb 와 같은 예외로 올린다 (HttpError·AuthError) - 에이전트의 다시 시도·큐 코드가 그대로 돈다.
"""
import email.utils
import hashlib
import hmac
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

import fb

LOCAL_HOSTS = ("127.0.0.1", "localhost")
PORT = 8781                      # local_server.PORT 와 같다 (서버 모듈을 불러오지 않으려고 여기에도 둔다 - 시험이 같은지 본다)
ROLES = ("agent", "relay")
H_ROLE, H_TIME, H_NONCE, H_SIGN = "X-AP-Role", "X-AP-Time", "X-AP-Nonce", "X-AP-Sign"
NOT_VERIFIED = "SERVER_NOT_VERIFIED"     # 답한 쪽이 우리 로컬 서버가 아니다 (서명이 없거나 틀림) - 열쇠가 바뀐 경우도 여기로 온다


def keys_dir():
    """로컬 서버 열쇠 파일(agent.key·relay.key)이 있는 폴더 - local_server.data_dir() 과 같은 자리 (만들지는 않는다)."""
    import os
    import rpa_status
    return os.path.join(rpa_status.install_root(), "standalone")


# --- 서명 (서버와 같이 쓴다) ------------------------------------------------
def _mac(key, parts):
    return hmac.new(key.encode("utf-8"), "\n".join(parts).encode("utf-8"), hashlib.sha256).hexdigest()


def _digest(body):
    return hashlib.sha256(body or b"").hexdigest()


def request_mac(key, role, method, target, ts, nonce, body, digest=None):
    """요청 서명. target 은 보낸 그대로의 경로+질의, ts 는 보낸 시각(ms 글자), nonce 는 요청마다 새 값.
    digest: 본문의 sha256 글을 이미 알면 (서버가 읽으며 계산) body 대신 준다."""
    return _mac(key, ["ap1", "req", role, method, target, str(ts), nonce, digest or _digest(body)])


def response_mac(key, nonce, status, body):
    """응답 서명 - 그 요청의 nonce 에 묶인다 (다른 요청의 응답을 돌려쓰지 못한다)."""
    return _mac(key, ["ap1", "res", nonce, str(status), _digest(body)])


def event_mac(key, nonce, seq, event, raw):
    """구독 이벤트 서명 - 그 구독의 nonce 와 차례(seq, 1부터)에 묶인다."""
    return _mac(key, ["ap1", "sse", nonce, str(seq), event, raw])


def sign_headers(key, role, method, target, body=b"", now_ms=None, nonce=None):
    """요청에 실을 머리글 {역할, 시각, nonce, 서명}. 열쇠는 들어가지 않는다."""
    ts = str(int(time.time() * 1000) if now_ms is None else int(now_ms))
    nonce = nonce or secrets.token_hex(16)
    return {H_ROLE: role, H_TIME: ts, H_NONCE: nonce, H_SIGN: request_mac(key, role, method, target, ts, nonce, body)}


class Client:
    def __init__(self, cfg, opener=None, clock=time.time):
        url = str(cfg.get("server_url") or "")
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != "http" or parts.hostname not in LOCAL_HOSTS:
            raise ValueError("로컬 서버 주소가 이 PC(127.0.0.1)가 아닙니다.")
        if not cfg.get("key"):
            raise ValueError("로컬 서버 열쇠가 없습니다.")
        self._base = url.rstrip("/")
        self._key = cfg["key"]
        self._role = cfg.get("role") if cfg.get("role") in ROLES else "agent"
        # 프록시 설정을 따르지 않는다 - 이 PC 안의 연결이 회사 프록시로 나가면 안 된다
        self._open = opener or urllib.request.build_opener(urllib.request.ProxyHandler({})).open
        self._now = clock
        self._offset = 0.0

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

    def _request(self, method, path, value=None, accept=None, timeout=30):
        """서명한 요청을 보낸다 → (응답, nonce). path 는 '/db/…' 처럼 서버에 보내는 경로+질의."""
        body = b"" if value is None and method in ("GET", "DELETE") else json.dumps(value, ensure_ascii=False).encode("utf-8")
        headers = sign_headers(self._key, self._role, method, path, body, now_ms=self._now() * 1000)
        headers["Content-Type"] = "application/json"
        if accept:
            headers["Accept"] = accept
        req = urllib.request.Request(self._base + path, data=body or None, headers=headers, method=method)
        try:
            return self._open(req, timeout=timeout), headers[H_NONCE]
        except urllib.error.HTTPError as e:
            raw = e.read()
            self._verify(e.headers, headers[H_NONCE], e.code, raw)     # 서명 없는 거절은 우리 서버의 답이 아니다
            raise fb.HttpError(e.code, raw.decode("utf-8", "replace")) from None

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


def client_for(cfg):
    """설정에 맞는 클라이언트 - 스탠드얼론 설정이면 로컬 서버, 아니면 Firebase."""
    return Client(cfg) if cfg.get("standalone") else fb.Client(cfg)
