# -*- coding: utf-8 -*-
"""스탠드얼론: 이 PC 의 로컬 서버(local_server.py)에 붙는 클라이언트 - fb.Client 와 같은 메서드 (설계 2026-11-23-standalone 6.2).

에이전트·ACTOR 실행·옵저버가 fb.Client 대신 쓴다 (client_for 가 고른다). Firebase·Google 에는 연결하지 않는다.
인증은 로그인이 아니라 그 PC 의 열쇠 파일 값(Authorization: Bearer) - 열쇠는 로그·예외 글에 싣지 않는다.
오류는 fb 와 같은 예외로 올린다 (HttpError·AuthError) - 에이전트의 다시 시도·큐 코드가 그대로 돈다.
"""
import email.utils
import json
import time
import urllib.error
import urllib.parse
import urllib.request

import fb

LOCAL_HOSTS = ("127.0.0.1", "localhost")
PORT = 8781                      # local_server.PORT 와 같다 (서버 모듈을 불러오지 않으려고 여기에도 둔다 - 시험이 같은지 본다)


def keys_dir():
    """로컬 서버 열쇠 파일(agent.key·relay.key)이 있는 폴더 - local_server.data_dir() 과 같은 자리 (만들지는 않는다)."""
    import os
    import rpa_status
    return os.path.join(rpa_status.install_root(), "standalone")


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
        # 프록시 설정을 따르지 않는다 - 이 PC 안의 연결이 회사 프록시로 나가면 안 된다
        self._open = opener or urllib.request.build_opener(urllib.request.ProxyHandler({})).open
        self._now = clock
        self._offset = 0.0

    # --- fb.Client 와 같은 겉모양 ----------------------------------------
    def server_now(self):
        """서버 시각 (초). 같은 PC 라 PC 시각과 같지만 fb 와 같은 길로 둔다."""
        return self._now() + self._offset

    def token(self):
        return self._key

    def renew(self):
        """fb 는 토큰을 새로 받는다 - 여기는 열쇠라 할 일이 없다."""

    def _seen(self, resp):
        try:
            self._offset = email.utils.parsedate_to_datetime(resp.headers["Date"]).timestamp() - self._now()
        except Exception:
            pass

    def _request(self, method, url, value=None, accept=None, timeout=30):
        body = None if value is None else json.dumps(value, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self._key}"}
        if accept:
            headers["Accept"] = accept
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            return self._open(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            text = e.read().decode("utf-8", "replace")
            if e.code == 401:
                raise fb.AuthError(401, "INVALID_KEY") from None
            raise fb.HttpError(e.code, text) from None

    def _json(self, method, url, value=None):
        resp = self._request(method, url, value)
        raw = resp.read().decode("utf-8")
        self._seen(resp)
        return json.loads(raw) if raw else None

    def _db(self, path, params=None):
        path = "/".join(urllib.parse.quote(seg, safe="-_~$:@!") for seg in path.strip("/").split("/"))
        q = f"?{urllib.parse.urlencode(params)}" if params else ""
        return f"{self._base}/db/{path}.json{q}"

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
        서버는 30초마다 keep-alive 를 보낸다 - timeout 초 동안 조용하면 끊긴 연결로 보고 예외."""
        resp = self._request("GET", self._db(path, params), accept="text/event-stream", timeout=timeout)
        buf = []
        try:
            for raw in resp:
                line = raw.decode("utf-8", "replace").rstrip("\n")
                buf.append(line)
                if line == "":
                    for item in fb.parse_sse(buf):
                        yield item
                    buf = []
        finally:
            close = getattr(resp, "close", None)
            if close:
                close()

    # --- 실행 기록 (Firestore 꼴) ----------------------------------------
    def fs_create(self, path, fields, doc_id):
        """문서를 만든다. fields 는 fb.fs_fields 가 만든 Firestore 꼴 - 보통 값으로 풀어 보낸다. 이미 있으면 False."""
        plain = {k: fb.fs_value(v) for k, v in fields.items()}
        url = f"{self._base}/fs/{path.strip('/')}?id={urllib.parse.quote(doc_id, safe='')}"
        try:
            self._json("POST", url, plain)
        except fb.HttpError as e:
            if e.status == 409:
                return False
            raise
        return True

    def fs_get(self, path):
        """문서 하나의 값 dict (없으면 None)."""
        try:
            return self._json("GET", f"{self._base}/fs/{path.strip('/')}")
        except fb.HttpError as e:
            if e.status == 404:
                return None
            raise

    def fs_sum(self, parent, collection, field, since=None):
        q = {"parent": parent.strip("/"), "collection": collection, "field": field}
        if since:
            q["since"] = since
        return (self._json("GET", f"{self._base}/fs-sum?{urllib.parse.urlencode(q)}") or {}).get("sum") or 0


def client_for(cfg):
    """설정에 맞는 클라이언트 - 스탠드얼론 설정이면 로컬 서버, 아니면 Firebase."""
    return Client(cfg) if cfg.get("standalone") else fb.Client(cfg)
