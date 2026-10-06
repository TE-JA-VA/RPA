"""Firebase REST 클라이언트. 표준 라이브러리만 쓴다 (에이전트를 가볍게 두려고).

- 로그인: Identity Toolkit signInWithPassword
- 갱신: Secure Token refresh_token
- RTDB: <database_url>/<path>.json?auth=<idToken>
- 구독: 같은 주소에 Accept: text/event-stream (SSE)

비밀번호는 로그인 요청에만 실린다 - 처음 한 번, 그리고 갱신이 거부됐을 때(비밀번호 변경·회수) 다시. 기록에는 어떤 경우에도 남기지 않는다.
로그인까지 거부되면 그 뒤로는 망에 나가지 않고 같은 AuthError 만 올린다 (매초 두드리지 않게).
FIREBASE_AUTH_EMULATOR_HOST 가 있으면 로그인·갱신을 에뮬레이터로 보낸다 (통합 시험용).
"""
import base64
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


def fs_fields(data):
    """dict → Firestore REST 의 형 붙은 fields. 값은 문자열·불·정수·실수·None·dict(map) 만 (나머지는 JSON 문자열로).
    dict 를 map 으로 두는 것은 서버가 칸마다 더할 수 있게 (실행 기록의 쓴 것 used - 토큰, 2026-10-06)."""
    out = {}
    for k, v in data.items():
        if v is None:
            out[k] = {"nullValue": None}
        elif isinstance(v, bool):
            out[k] = {"booleanValue": v}
        elif isinstance(v, int):
            out[k] = {"integerValue": str(v)}
        elif isinstance(v, float):
            out[k] = {"doubleValue": v}
        elif isinstance(v, str):
            out[k] = {"stringValue": v}
        elif isinstance(v, dict):
            out[k] = {"mapValue": {"fields": fs_fields(v)}}
        else:
            out[k] = {"stringValue": json.dumps(v, ensure_ascii=False, default=str)}
    return out


def fs_value(v):
    """Firestore REST 의 형 붙은 값 하나 → 파이썬 값 (fs_fields 의 거꾸로). 모르는 형은 None."""
    if "integerValue" in v:
        return int(v["integerValue"])
    if "doubleValue" in v:
        return float(v["doubleValue"])
    if "stringValue" in v:
        return v["stringValue"]
    if "booleanValue" in v:
        return v["booleanValue"]
    if "mapValue" in v:
        return {k: fs_value(x) for k, x in (v["mapValue"].get("fields") or {}).items()}
    return None


class HttpError(Exception):
    def __init__(self, status, body):
        super().__init__(f"HTTP {status}")
        self.status = status
        self.body = body


class AuthError(Exception):
    """로그인·갱신을 Identity Toolkit 이 거부한 것(code 가 읽히는 4xx). code 는 error.message 의 첫 낱말
    (INVALID_LOGIN_CREDENTIALS / USER_DISABLED / TOO_MANY_ATTEMPTS_TRY_LATER …). 한국어 문구는 agent 쪽에서 매긴다."""
    def __init__(self, status, code):
        super().__init__(f"HTTP {status} {code}")
        self.status = status
        self.code = code


def claims(id_token):
    """ID 토큰 가운데 조각(JSON)을 읽는다. 서명은 확인하지 않는다 - 값을 믿는 쪽은 어차피 규칙이 지킨다."""
    part = id_token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))


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
        self._dead = None       # 비밀번호 로그인까지 거부한 AuthError. 새 Client 를 만들면 당연히 비어 있다

    # --- 토큰 ---------------------------------------------------------
    def _post_json(self, url, payload):
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            return json.loads(self._open(req, timeout=20).read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                code = str(json.loads(e.read().decode("utf-8", "replace"))["error"]["message"]).split()[0]   # "CODE : 설명" 꼴도 온다
            except Exception:
                code = ""
            # Identity Toolkit 이 code 를 준 4xx 만 인증 거부다. 5xx·429·프록시 407·포털 403(HTML 본문) 은 망 사정이라 그대로
            # 올린다 - 에이전트가 멈추거나 비밀번호를 다시 묻지 않고 전처럼 1초마다 다시 시도한다 (날 HTTPError 라 큐에서도 안 버린다)
            if e.code >= 500 or e.code == 429 or not code:
                raise
            raise AuthError(e.code, code) from None          # 본문은 보관하지 않는다 - code 만

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
        if self._dead:
            raise self._dead
        if self._id_token and self._now() < self._expires_at - RENEW_BEFORE_SEC:
            return self._id_token
        if self._refresh_token:
            try:
                self._refresh()
                return self._id_token
            except AuthError:
                pass          # 갱신이 거부됐다(비밀번호 변경·회수) - 비밀번호로 처음부터 다시 로그인한다. 망 오류는 그대로 올라간다
        try:
            self._sign_in()
        except AuthError as e:
            self._dead = e    # 이 뒤로는 망에 안 나가고 같은 예외를 올린다. agent 가 멈추고 비밀번호를 다시 묻는다
            raise
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

    # --- Firestore (이력) ----------------------------------------------
    def _fs_base(self):
        host = os.environ.get("FIRESTORE_EMULATOR_HOST")
        root = f"http://{host}/v1" if host else "https://firestore.googleapis.com/v1"
        return f"{root}/projects/{self._cfg['project_id']}/databases/(default)/documents"

    def fs_create(self, path, fields, doc_id, retried=False):
        """문서를 만든다 (같은 id 가 이미 있으면 그대로 둔다 - 409 는 성공으로 본다)."""
        url = f"{self._fs_base()}/{path.strip('/')}?documentId={urllib.parse.quote(doc_id, safe='')}"
        body = json.dumps({"fields": fields}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST", headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {self.token()}"})
        try:
            self._open(req, timeout=30).read()
        except urllib.error.HTTPError as e:
            if e.code == 409:
                return False
            if e.code == 401 and not retried:
                self.renew()
                return self.fs_create(path, fields, doc_id, retried=True)
            raise HttpError(e.code, e.read().decode("utf-8", "replace")) from None
        return True

    def _fs_call(self, method, url, body=None, retried=False):
        """Firestore REST 한 번 (401 이면 토큰을 새로 받아 한 번 더). 없는 문서(404)는 None."""
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {self.token()}"})
        try:
            return json.loads(self._open(req, timeout=30).read().decode("utf-8") or "null")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code == 401 and not retried:
                self.renew()
                return self._fs_call(method, url, body, retried=True)
            raise HttpError(e.code, e.read().decode("utf-8", "replace")) from None

    def fs_get(self, path):
        """문서 하나의 값 dict (없으면 None)."""
        doc = self._fs_call("GET", f"{self._fs_base()}/{path.strip('/')}")
        return None if doc is None else {k: fs_value(v) for k, v in (doc.get("fields") or {}).items()}

    def fs_sum(self, parent, collection, field):
        """parent 아래 collection 문서들의 field 합 - 서버가 더한다 (문서를 내려받지 않는다, 1000건에 읽기 1번).
        그 칸이 없는 문서(토큰 전 옛 기록)는 빠진다."""
        r = self._fs_call("POST", f"{self._fs_base()}/{parent.strip('/')}:runAggregationQuery", {
            "structuredAggregationQuery": {
                "structuredQuery": {"from": [{"collectionId": collection}]},
                "aggregations": [{"alias": "s", "sum": {"field": {"fieldPath": field}}}]}})
        return fs_value(((r or [{}])[0].get("result") or {}).get("aggregateFields", {}).get("s", {})) or 0

    # --- 구독 ---------------------------------------------------------
    def stream(self, path, params=None, timeout=90):
        """SSE 로 구독한다. (event, data) 를 내놓는 제너레이터. 서버가 닫으면 그냥 끝난다.

        Firebase 는 30초마다 keep-alive 를 보낸다. timeout 초 동안 아무것도 안 오면 끊긴 연결로 보고 예외를 낸다 -
        PC 절전이나 망 끊김 뒤 TCP 가 소리 없이 죽으면 read 가 영원히 막히는 것을 막는다."""
        req = urllib.request.Request(self._url(path, params),
                                     headers={"Accept": "text/event-stream"})
        resp = self._open(req, timeout=timeout)
        buf = []
        try:
            for raw in resp:
                line = raw.decode("utf-8", "replace").rstrip("\n")
                buf.append(line)
                if line == "":
                    for item in parse_sse(buf):
                        yield item
                    buf = []
        finally:
            close = getattr(resp, "close", None)
            if close:
                close()
