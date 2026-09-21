"""Firebase REST 클라이언트. 표준 라이브러리만 쓴다 (에이전트를 가볍게 두려고).

- 로그인: Identity Toolkit signInWithPassword
- 갱신: Secure Token refresh_token
- RTDB: <database_url>/<path>.json?auth=<idToken>
- 구독: 같은 주소에 Accept: text/event-stream (SSE)

비밀번호는 첫 로그인 요청에만 실린다. 기록에는 어떤 경우에도 남기지 않는다.
FIREBASE_AUTH_EMULATOR_HOST 가 있으면 로그인·갱신을 에뮬레이터로 보낸다 (통합 시험용).
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

RENEW_BEFORE_SEC = 60


def _auth_host():
    host = os.environ.get("FIREBASE_AUTH_EMULATOR_HOST")
    return f"http://{host}/identitytoolkit.googleapis.com" if host else "https://identitytoolkit.googleapis.com"


def _token_host():
    host = os.environ.get("FIREBASE_AUTH_EMULATOR_HOST")
    return f"http://{host}/securetoken.googleapis.com" if host else "https://securetoken.googleapis.com"


class HttpError(Exception):
    def __init__(self, status, body):
        super().__init__(f"HTTP {status}")
        self.status = status
        self.body = body


def parse_sse(lines):
    """SSE 줄 목록을 [(event, data)] 로 바꾼다. 빈 줄이 한 덩이의 끝이다."""
    out, event, data = [], None, None
    for line in lines:
        line = line.rstrip("\r")
        if line == "":
            if event is not None:
                out.append((event, data))
            event, data = None, None
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            raw = line[5:].strip()
            try:
                data = json.loads(raw)
            except ValueError:
                data = None
    return out


class Client:
    def __init__(self, cfg, opener=None, clock=time.time):
        self._cfg = cfg
        self._open = opener or urllib.request.urlopen
        self._now = clock
        self._id_token = None
        self._refresh_token = None
        self._expires_at = 0.0

    # --- 토큰 ---------------------------------------------------------
    def _post_json(self, url, payload):
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        return json.loads(self._open(req, timeout=20).read().decode("utf-8"))

    def _sign_in(self):
        r = self._post_json(f"{_auth_host()}/v1/accounts:signInWithPassword?key={self._cfg['api_key']}", {
            "email": self._cfg["email"], "password": self._cfg["password"],
            "returnSecureToken": True})
        self._id_token = r["idToken"]
        self._refresh_token = r["refreshToken"]
        self._expires_at = self._now() + float(r.get("expiresIn", 3600))

    def _refresh(self):
        r = self._post_json(f"{_token_host()}/v1/token?key={self._cfg['api_key']}", {
            "grant_type": "refresh_token", "refresh_token": self._refresh_token})
        self._id_token = r["id_token"]
        self._refresh_token = r["refresh_token"]
        self._expires_at = self._now() + float(r.get("expires_in", 3600))

    def token(self):
        if self._id_token and self._now() < self._expires_at - RENEW_BEFORE_SEC:
            return self._id_token
        if self._refresh_token:
            try:
                self._refresh()
                return self._id_token
            except Exception:
                pass          # 갱신이 막히면 처음부터 다시 로그인한다
        self._sign_in()
        return self._id_token

    def renew(self):
        """다음 요청이 토큰을 새로 받게 한다 (401 을 만났을 때)."""
        self._expires_at = 0.0

    # --- RTDB ---------------------------------------------------------
    def _url(self, path, params=None):
        q = dict(params or {})
        q["auth"] = self.token()
        base = self._cfg["database_url"].rstrip("/")
        # 에뮬레이터 주소는 "http://127.0.0.1:9000/?ns=..." 꼴이라 경로와 질의를 나눠 붙인다
        if "?" in base:
            base, extra = base.split("?", 1)
            base = base.rstrip("/")
            q.update(urllib.parse.parse_qsl(extra))
        return f"{base}/{path.strip('/')}.json?{urllib.parse.urlencode(q)}"

    def _send(self, method, path, value, params=None, retried=False):
        body = None if value is None else json.dumps(value, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self._url(path, params), data=body,
                                     headers={"Content-Type": "application/json"}, method=method)
        try:
            raw = self._open(req, timeout=30).read().decode("utf-8")
        except urllib.error.HTTPError as e:
            if e.code == 401 and not retried:
                self.renew()
                return self._send(method, path, value, params, retried=True)
            raise HttpError(e.code, e.read().decode("utf-8", "replace")) from None
        return json.loads(raw) if raw else None

    def put(self, path, value):
        return self._send("PUT", path, value)

    def patch(self, path, value):
        return self._send("PATCH", path, value)

    def get(self, path, params=None):
        return self._send("GET", path, None, params)

    def delete(self, path):
        return self._send("DELETE", path, None)

    # --- 구독 ---------------------------------------------------------
    def stream(self, path, params=None):
        """SSE 로 구독한다. (event, data) 를 내놓는 제너레이터. 끊기면 그냥 끝난다."""
        req = urllib.request.Request(self._url(path, params),
                                     headers={"Accept": "text/event-stream"})
        resp = self._open(req, timeout=None)
        buf = []
        for raw in resp:
            line = raw.decode("utf-8", "replace").rstrip("\n")
            buf.append(line)
            if line == "":
                for item in parse_sse(buf):
                    yield item
                buf = []
