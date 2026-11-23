"""Firebase REST 클라이언트. 표준 라이브러리만 쓴다 (에이전트를 가볍게 두려고).

- 로그인: Identity Toolkit signInWithPassword
- 갱신: Secure Token refresh_token
- RTDB: <database_url>/<path>.json?auth=<idToken>
- 구독: 같은 주소에 Accept: text/event-stream (SSE)

비밀번호는 로그인 요청에만 실린다 - 처음 한 번, 그리고 갱신이 거부됐을 때(비밀번호 변경·회수) 다시. 기록에는 어떤 경우에도 남기지 않는다.
로그인까지 거부되면 그 뒤로는 망에 나가지 않고 같은 AuthError 만 올린다 (매초 두드리지 않게).
FIREBASE_AUTH_EMULATOR_HOST 가 있으면 로그인·갱신을 에뮬레이터로 보낸다 (통합 시험용) - 소스에서 돌 때만. 설치본은 무시한다 (_dev_env).
"""
import base64
import email.utils
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))   # 저장소·배포 폴더 뿌리 (secret.py 와 같다)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
import server_info  # noqa: E402  서버 주소 한 곳 - 스탠드얼론은 빈 값 (Firebase 에 연결하지 않는다)

RENEW_BEFORE_SEC = 60


def _program_dir(file=None, compiled_dir=None):
    """프로그램 폴더. 에이전트는 원본 {프로그램}\\firebase\\agent\\fb.py 로 돌아 두 단계 위다. ACTOR·옵저버는 컴파일된 것을 쓴다 -
    조각은 {프로그램}\\app\\fb.pyd 라 app 의 한 단계 위, onefile exe 는 exe 가 놓인 폴더 (rpa_status.compiled_dir 와 같은 규칙).
    파일 자리로만 세면 조각에서 한 단계 위로 잘못 잡아 _shipped 가 거짓이 됐다 (검토 2026-11-19).
    compiled_dir: None 이면 스스로 알아본다 (__compiled__), "" 면 컴파일되지 않은 것으로 본다 (시험)."""
    if compiled_dir is None:
        compiled = globals().get("__compiled__")
        compiled_dir = getattr(compiled, "containing_dir", None) if compiled is not None else None
    if compiled_dir:
        return os.path.dirname(compiled_dir) if os.path.basename(compiled_dir).lower() == "app" else compiled_dir
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(file or __file__))))


def _shipped():
    """설치된 프로그램 폴더에서 도는가 - 프로그램 폴더에 버전 목록 manifest.json 이 있다 (소스 폴더에는 없다).
    rpa_status.shipped 와 같은 기준 (이 모듈은 표준 라이브러리만 쓴다)."""
    return os.path.isfile(os.path.join(_program_dir(), "manifest.json"))


def _dev_env(name):
    """시험용 환경 변수. 설치본에서는 무시한다 (보안 감사 2026-11-13 C2, 고객사 보안 검토 2026-11-19) - 그 전에는 같은 윈도우 계정의
    다른 프로그램이 에뮬레이터 주소 변수를 넣으면 에이전트 로그인 요청(비밀번호)이 그 주소로 암호화 없이 갔다."""
    return None if _shipped() else os.environ.get(name)


def _auth_host():
    host = _dev_env("FIREBASE_AUTH_EMULATOR_HOST")
    return f"http://{host}/{server_info.AUTH_HOST}" if host else f"https://{server_info.AUTH_HOST}"


def _token_host():
    host = _dev_env("FIREBASE_AUTH_EMULATOR_HOST")
    return f"http://{host}/{server_info.TOKEN_HOST}" if host else f"https://{server_info.TOKEN_HOST}"


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
        if not server_info.AUTH_HOST:      # 스탠드얼론 설치본 (빈 server_info) - 에이전트는 local_store 로 이 PC 의 로컬 서버에 붙는다
            raise RuntimeError("스탠드얼론 버전에서는 Firebase 에 연결하지 않습니다.")
        if _shipped() and not str(cfg.get("database_url") or "").lower().startswith("https://"):    # 설치본은 암호화된 주소만 (C2)
            raise ValueError("클라우드 주소가 https 가 아닙니다. '오토파일럿 설정'에서 에이전트 계정을 다시 설정하여 주십시오.")
        self._cfg = cfg
        self._open = opener or urllib.request.urlopen
        self._now = clock
        self._id_token = None
        self._refresh_token = None
        self._expires_at = 0.0
        self._dead = None       # 비밀번호 로그인까지 거부한 AuthError. 새 Client 를 만들면 당연히 비어 있다
        # 토큰 갱신·로그인이 망 오류로 실패하면 2·4·8…60초 물러선다 - 그동안은 망에 안 나가고 같은 예외 (보안 진단 2026-11-23 E-5)
        self._backoff, self._retry_at, self._last_err = 0.0, 0.0, None
        self._offset = 0.0      # 서버 시각 - PC 시각 (RTDB 응답의 Date 머리글, 초 단위 정밀도)

    def server_now(self):
        """서버 시각 (초). PC 시계가 틀려도 맞는 시각 - 전송 자리 만료처럼 여러 PC 가 같이 보는 시각에 쓴다 (2026-10-21).
        아직 응답을 못 받았으면 PC 시각."""
        return self._now() + self._offset

    def _seen(self, resp):
        try:
            self._offset = email.utils.parsedate_to_datetime(resp.headers["Date"]).timestamp() - self._now()
        except Exception:
            pass

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
        if self._last_err is not None and self._now() < self._retry_at:
            raise self._last_err
        try:
            if self._refresh_token:
                try:
                    self._refresh()
                    return self._ok()
                except AuthError:
                    pass      # 갱신이 거부됐다(비밀번호 변경·회수) - 비밀번호로 처음부터 다시 로그인한다. 망 오류는 그대로 올라간다
            try:
                self._sign_in()
            except AuthError as e:
                self._dead = e    # 이 뒤로는 망에 안 나가고 같은 예외를 올린다. agent 가 멈추고 비밀번호를 다시 묻는다
                raise
            return self._ok()
        except AuthError:
            raise
        except Exception as e:      # 망 오류 (5xx·429·끊김) - 물러선다
            self._backoff = min(60.0, max(2.0, self._backoff * 2))
            self._retry_at, self._last_err = self._now() + self._backoff, e
            raise

    def _ok(self):
        self._backoff, self._retry_at, self._last_err = 0.0, 0.0, None
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
        # 경로 조각을 인코딩한다 - 빈칸·제어 글자가 섞인 키(옮겨 온 휴대폰 키 등)면 http.client 가 연결 전에 InvalidURL 을 내며
        # 주소 전체(?auth=<ID 토큰>)를 예외 글에 실었고, 그 글이 실행 로그·클라우드로 갔다 (보안 진단 2026-11-23 E-4)
        path = "/".join(urllib.parse.quote(seg, safe="-_~$:@!") for seg in path.strip("/").split("/"))
        return f"{base}/{path}.json?{urllib.parse.urlencode(q)}"

    def _send(self, method, path, value, params=None, retried=False):
        body = None if value is None else json.dumps(value, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self._url(path, params), data=body,
                                     headers={"Content-Type": "application/json"}, method=method)
        try:
            resp = self._open(req, timeout=30)
            raw = resp.read().decode("utf-8")
            self._seen(resp)
        except urllib.error.HTTPError as e:
            if e.code == 401 and not retried:
                self.renew()
                return self._send(method, path, value, params, retried=True)
            raise HttpError(e.code, e.read().decode("utf-8", "replace")) from None
        return json.loads(raw) if raw else None

    # print=silent: 서버가 쓴 내용을 응답으로 돌려주지 않는다 (204, 빈 응답) - 그 응답이 Realtime DB 다운로드로 잡혔다
    # (5초 heartbeat·현황마다, 2026-11-09). 쓰기 응답을 쓰는 곳은 없고 실패는 그대로 HTTP 오류로 온다.
    def put(self, path, value):
        return self._send("PUT", path, value, {"print": "silent"})

    def patch(self, path, value):
        return self._send("PATCH", path, value, {"print": "silent"})

    def get(self, path, params=None):
        return self._send("GET", path, None, params)

    def delete(self, path):
        return self._send("DELETE", path, None)

    # --- Firestore (이력) ----------------------------------------------
    def _fs_base(self):
        host = _dev_env("FIRESTORE_EMULATOR_HOST")
        root = f"http://{host}/v1" if host else f"https://{server_info.FIRESTORE_HOST}/v1"
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

    def fs_sum(self, parent, collection, field, since=None):
        """parent 아래 collection 문서들의 field 합 - 서버가 더한다 (문서를 내려받지 않는다, 1000건에 읽기 1번).
        그 칸이 없는 문서(토큰 전 옛 기록)는 빠진다. since 면 started_at >= since 인 것만 (복합 색인 started_at·field 가
        rules/firestore.indexes.json 에 있어야 한다 - 에뮬레이터는 색인을 안 따진다)."""
        query = {"from": [{"collectionId": collection}]}
        if since:
            query["where"] = {"fieldFilter": {"field": {"fieldPath": "started_at"}, "op": "GREATER_THAN_OR_EQUAL",
                                              "value": {"stringValue": since}}}
        r = self._fs_call("POST", f"{self._fs_base()}/{parent.strip('/')}:runAggregationQuery", {
            "structuredAggregationQuery": {
                "structuredQuery": query,
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
