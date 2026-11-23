# -*- coding: utf-8 -*-
"""스탠드얼론 로컬 서버 - 에이전트가 Firebase 에 쓰던 자리를 이 PC 안에서 받는다 (127.0.0.1:8781).
이 파일의 저장소 부분: Store(RTDB 자리 흉내 - JSON 나무·구독)와 Runs(Firestore 실행 기록 흉내 - SQLite).
둘 다 HTTP 를 모른다 - 창구(서버·인증·검사)는 이 파일 뒤쪽에 따로 붙는다.
표준 라이브러리만 쓴다.
"""
import copy
import hmac
import http.server
import json
import os
import queue
import secrets
import socket
import socketserver
import sqlite3
import sys
import tempfile
import threading
import time
import urllib.parse

RPA_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
if RPA_DIR not in sys.path:
    sys.path.insert(0, RPA_DIR)          # rpa_status·license_check (agent.py 와 같은 규칙)

PORT = 8781


def data_dir():
    """로컬 서버 자료 폴더 install_root()\\standalone (store.json·runs.db·agent.key·relay.key). 없으면 만든다."""
    import rpa_status          # 지연 import - 저장소 쪽은 rpa_status 없이도 쓸 수 있다
    path = os.path.join(rpa_status.install_root(), "standalone")
    os.makedirs(path, exist_ok=True)
    return path


# ----------------------------------------------------------------------------------------------------
# Store - RTDB 자리 흉내
# ----------------------------------------------------------------------------------------------------

def _split(path):
    """'a/b/c' → ['a','b','c'] (앞뒤·겹친 슬래시 무시). 빈 글은 루트 []."""
    return [p for p in str(path or "").split("/") if p]


def _clean(value):
    """쓸 값을 새로 복사하면서 None·빈 dict 를 없앤다 (RTDB 는 빈 가지를 두지 않는다). 다 없어지면 None."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            c = _clean(v)
            if c is not None:
                out[str(k)] = c
        return out or None
    return copy.deepcopy(value)


def _eq(a, b):
    """같은 값인가 - 불리언과 숫자는 다르게 본다 (파이썬은 True == 1)."""
    if isinstance(a, bool) != isinstance(b, bool):
        return False
    return a == b


def _lookup(node, parts):
    for p in parts:
        if not isinstance(node, dict) or p not in node:
            return None
        node = node[p]
    return None if node == {} else node        # 빈 루트도 없는 것과 같다


def _set(node, parts, value):
    """node 아래 parts 자리에 value 를 쓴다 (None 이면 지운다). 고친 node 를 돌려준다 - 비게 되면 None (빈 가지 없앰)."""
    if not parts:
        return value
    if not isinstance(node, dict):
        if value is None:
            return node           # 지울 것이 없다
        node = {}                 # 잎이던 자리 아래로 쓰면 가지로 바뀐다
    child = _set(node.get(parts[0]), parts[1:], value)
    if child is None:
        node.pop(parts[0], None)
    else:
        node[parts[0]] = child
    return node or None


def _matches(child, order_by, equal_to):
    return isinstance(child, dict) and order_by in child and _eq(child[order_by], equal_to)


def _filtered(node, order_by, equal_to):
    """node 의 자식 가운데 order_by 칸이 equal_to 인 것만. order_by·equal_to 가 둘 다 있어야 거른다."""
    if order_by is None or equal_to is None:
        return node
    if not isinstance(node, dict):
        return None
    return {k: v for k, v in node.items() if _matches(v, order_by, equal_to)} or None


class Store:
    """JSON 나무 하나를 파일에 둔 저장소 (RTDB 자리 흉내). 쓸 때마다 파일에 원자적으로 저장한다.
    - 값이 None 이거나 비어 있으면 지운 것 - 빈 가지는 없앤다 (get 은 None).
    - 쓰기는 나무를 복사해 고친 뒤 저장이 끝나야 바꿔 끼운다 (저장이 실패하면 메모리도 그대로).
    - 읽기는 잠금 없이 (바꿔 끼운 나무는 다시 고치지 않는다). 쓰기와 구독 알림은 잠금 하나로 묶는다."""

    def __init__(self, path, volatile=()):
        """volatile: 파일에 남기지 않는 자리들 (예 "apps/otp" - 인증번호). 메모리에는 있고 구독도 되지만 다시 켜면 비어 있다."""
        self.path = os.path.abspath(path)
        self._volatile = [_split(p) for p in volatile]
        self._lock = threading.Lock()
        self._subs = []
        self._data = self._load()

    # --- 파일 ---
    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                text = f.read()
        except FileNotFoundError:
            return {}
        except (OSError, UnicodeDecodeError):
            return self._broken()
        try:
            data = json.loads(text)
            if not isinstance(data, dict):
                raise ValueError("나무가 dict 가 아님")
        except ValueError:
            return self._broken()
        return _clean(data) or {}

    def _broken(self):
        """깨진(반쯤 쓰인) 파일은 .broken 으로 옮기고 빈 나무로 시작한다 - 서버가 죽지 않게."""
        try:
            os.replace(self.path, self.path + ".broken")
        except OSError:
            pass
        return {}

    def _save(self, data):
        folder = os.path.dirname(self.path)
        os.makedirs(folder, exist_ok=True)
        for parts in self._volatile:
            if _lookup(data, parts) is not None:
                data = _set(copy.deepcopy(data), parts, None) or {}
        fd, tmp = tempfile.mkstemp(dir=folder, prefix=os.path.basename(self.path) + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            for attempt in range(6):          # 바이러스 검사 등이 잠깐 잡고 있으면 바꿔치기가 거절된다
                try:
                    os.replace(tmp, self.path)
                    return
                except PermissionError:
                    if attempt == 5:
                        raise
                    time.sleep(0.05 * (attempt + 1))
        except BaseException:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise

    # --- 읽기 ---
    def get(self, path, order_by=None, equal_to=None):
        """path 자리의 값 (없으면 None). order_by·equal_to: path 의 자식 가운데 자식의 order_by 칸이 equal_to 인 것만."""
        node = _lookup(self._data, _split(path))
        return copy.deepcopy(_filtered(node, order_by, equal_to))

    # --- 쓰기 ---
    def put(self, path, value):
        self._write("put", _split(path), [(_split(path), _clean(value))], None)

    def patch(self, path, value):
        """value 의 키마다 path 아래 그 자리를 새로 쓴다 (키에 '/' 가 있으면 여러 자리 쓰기 - RTDB PATCH 와 같다)."""
        base = _split(path)
        writes = [(base + _split(k), _clean(v)) for k, v in value.items()]
        self._write("patch", base, writes, copy.deepcopy(value))

    def delete(self, path):
        self._write("delete", _split(path), [(_split(path), None)], None)

    def _write(self, kind, base, writes, raw):
        with self._lock:
            old = self._data
            new = copy.deepcopy(old)
            for parts, value in writes:
                if not parts:
                    if value is not None and not isinstance(value, dict):
                        raise ValueError("루트에는 dict 만 쓸 수 있습니다")
                    new = value or {}
                else:
                    new = _set(new, parts, value) or {}
            self._save(new)
            self._data = new
            for sub in list(self._subs):
                for ev in self._events(sub, kind, base, writes, raw, old, new):
                    sub["q"].put(ev)

    # --- 구독 ---
    def subscribe(self, path, order_by=None, equal_to=None):
        """path 를 구독한다. 큐의 첫 항목은 ("put", {"path": "/", "data": 지금 값(거른 것)}), 그 뒤로 바뀔 때마다
        ("put"|"patch", {"path": "/<상대 경로>", "data": 값}). 거른 구독은 자식이 조건에 들어오면 그 자식 값을, 빠지면
        ("put", {"path": "/<키>", "data": None}) 을 넣는다. 다 쓰면 unsubscribe."""
        q = queue.Queue()
        sub = {"q": q, "parts": _split(path), "order_by": order_by, "equal_to": equal_to}
        with self._lock:
            node = _filtered(_lookup(self._data, sub["parts"]), order_by, equal_to)
            q.put(("put", {"path": "/", "data": copy.deepcopy(node)}))
            self._subs.append(sub)
        return q

    def unsubscribe(self, q):
        with self._lock:
            self._subs = [s for s in self._subs if s["q"] is not q]

    @staticmethod
    def _events(sub, kind, base, writes, raw, old, new):
        S, n = sub["parts"], len(sub["parts"])
        order_by, equal_to = sub["order_by"], sub["equal_to"]
        whole, rels = False, []
        for parts, _ in writes:                      # 이번 쓰기 가운데 구독 자리와 만나는 것
            if len(parts) <= n:
                if S[:len(parts)] == parts:
                    whole = True                     # 구독 자리 자신이나 그 윗자리를 썼다
            elif parts[:n] == S:
                rels.append(parts[n:])
        if not whole and not rels:
            return []
        if whole:
            return [("put", {"path": "/", "data": copy.deepcopy(_filtered(_lookup(new, S), order_by, equal_to))})]
        if order_by is not None and equal_to is not None:
            out, seen = [], set()
            for rel in rels:
                key = rel[0]
                if key in seen:
                    continue
                seen.add(key)
                was = _matches(_lookup(old, S + [key]), order_by, equal_to)
                child = _lookup(new, S + [key])
                if _matches(child, order_by, equal_to):
                    out.append(("put", {"path": "/" + key, "data": copy.deepcopy(child)}))
                elif was:
                    out.append(("put", {"path": "/" + key, "data": None}))
            return out
        if kind == "patch" and base[:n] == S:        # 구독 자리나 그 아래에 한 번 patch
            return [("patch", {"path": "/" + "/".join(base[n:]), "data": copy.deepcopy(raw)})]
        return [("put", {"path": "/" + "/".join(rel), "data": copy.deepcopy(_lookup(new, S + rel))}) for rel in rels]


# ----------------------------------------------------------------------------------------------------
# Runs - Firestore 실행 기록 흉내 (SQLite)
# ----------------------------------------------------------------------------------------------------

class Runs:
    """실행 기록. 문서 하나 = (parent, collection, id) 한 줄, 칸은 JSON 으로 doc 에 둔다 (pc_id·date·started_at 은 거르기용 사본).
    HTTP 서버가 스레드마다 부르므로 연결 하나를 잠금으로 감싼다."""

    def __init__(self, db_path):
        if db_path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(db_path, check_same_thread=False, timeout=10)
        with self._lock, self._db:
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS docs(parent TEXT, collection TEXT, id TEXT, pc_id TEXT, date TEXT,"
                " started_at TEXT, doc TEXT, PRIMARY KEY(parent, collection, id))")

    def close(self):
        with self._lock:
            self._db.close()

    @staticmethod
    def _text(value):
        return None if value is None else str(value)

    def create(self, parent, collection, doc_id, fields):
        """기록 하나 만들기. 이미 있으면 False (덮어쓰지 않는다)."""
        with self._lock, self._db:
            cur = self._db.execute(
                "INSERT OR IGNORE INTO docs(parent, collection, id, pc_id, date, started_at, doc) VALUES(?,?,?,?,?,?,?)",
                (parent, collection, doc_id, self._text(fields.get("pcId")), self._text(fields.get("date")),
                 self._text(fields.get("started_at")), json.dumps(fields, ensure_ascii=False)))
            return cur.rowcount == 1

    def get(self, path):
        """path = '<parent>/<collection>/<id>' (parent 에 '/' 가 들어 있어도 된다). 없으면 None."""
        parts = _split(path)
        if len(parts) < 3:
            return None
        parent, collection, doc_id = "/".join(parts[:-2]), parts[-2], parts[-1]
        with self._lock:
            row = self._db.execute("SELECT doc FROM docs WHERE parent=? AND collection=? AND id=?",
                                   (parent, collection, doc_id)).fetchone()
        return json.loads(row[0]) if row else None

    def sum(self, parent, collection, field, since=None):
        """field 칸의 합. since 가 있으면 started_at >= since 인 문서만. 칸이 없거나 숫자가 아닌 문서는 뺀다."""
        sql = "SELECT doc FROM docs WHERE parent=? AND collection=?"
        args = [parent, collection]
        if since is not None:
            sql += " AND started_at >= ?"
            args.append(str(since))
        with self._lock:
            rows = self._db.execute(sql, args).fetchall()
        total = 0
        for (doc,) in rows:
            v = json.loads(doc).get(field)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                total += v
        return total

    def query(self, parent, collection, pc_id=None, date=None, limit=50):
        """started_at 내림차순(최근 먼저) 문서 목록."""
        sql = "SELECT doc FROM docs WHERE parent=? AND collection=?"
        args = [parent, collection]
        if pc_id is not None:
            sql += " AND pc_id=?"
            args.append(str(pc_id))
        if date is not None:
            sql += " AND date=?"
            args.append(str(date))
        sql += " ORDER BY started_at DESC, rowid DESC LIMIT ?"
        args.append(int(limit))
        with self._lock:
            rows = self._db.execute(sql, args).fetchall()
        return [json.loads(r[0]) for r in rows]


# ----------------------------------------------------------------------------------------------------
# 창구 - HTTP 서버·열쇠·검사 (계획 ① Task 3)
# ----------------------------------------------------------------------------------------------------
# 주소는 Firebase REST 와 같은 꼴이라 에이전트 코드가 그대로 돈다 (local_store.Client 가 부른다):
#   /db/<자리>.json        GET·PUT·PATCH·DELETE, Accept: text/event-stream 이면 구독 (SSE)
#   /fs/<parent>/<collection>?id=<문서 id>   POST 실행 기록 만들기,  /fs/<문서 자리>  GET,  /fs-sum?parent=&collection=&field=&since=
# 열쇠 둘 (Authorization: Bearer): agent.key = 에이전트, relay.key = ACTOR 실행·옵저버의 인증번호 중계.
# 검사는 지금 RTDB 규칙과 같은 뜻 - 에이전트는 자기 PC 자리만 쓰고, 명령은 만들지 못하고 상태만 옮긴다.

APP = "rpa"
MAX_BODY = 4 * 1024 * 1024
KEEPALIVE_SEC = 30
LOG_NAME = "로컬서버_기록.txt"
KEY_FILES = ("agent.key", "relay.key")
VOLATILE = ("apps/otp",)                   # 인증번호 요청·번호는 메모리에만 (파일에 남기지 않는다 - 설계 6.2)
LOCAL_HOSTS = ("127.0.0.1", "localhost")
CMD_FIXED = ("type", "args", "by", "created_at", "expires_at")      # 에이전트가 못 바꾸는 명령 칸
CMD_MOVES = {"queued": ("running", "expired", "failed"), "running": ("done", "failed")}
DENIED = {"error": "Permission denied"}     # fb.HttpError 본문을 보는 코드가 같은 글을 찾는다


def ensure_keys(folder):
    """에이전트·인증번호 중계 열쇠 (agent.key, relay.key). 없으면 만든다. 파일 권한은 설치 쪽이 잠근다 (계획 ③)."""
    os.makedirs(folder, exist_ok=True)
    out = []
    for name in KEY_FILES:
        path = os.path.join(folder, name)
        key = ""
        try:
            with open(path, encoding="ascii") as f:
                key = f.read().strip()
        except (OSError, UnicodeDecodeError):
            pass
        if len(key) < 32:
            key = secrets.token_urlsafe(32)
            tmp = f"{path}.{os.getpid()}.tmp"
            with open(tmp, "w", encoding="ascii") as f:
                f.write(key + "\n")
            os.replace(tmp, path)
        out.append(key)
    return tuple(out)


def log(folder, text):
    """서버 기록 한 줄. 열쇠·인증번호는 싣지 않는다. 예외를 내지 않는다."""
    try:
        with open(os.path.join(folder, LOG_NAME), "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {text}\n")
    except OSError:
        pass


def _server_values(value, now_ms):
    """{".sv": "timestamp"} 를 서버 시각(ms)으로 (RTDB 와 같다 - 인증번호 요청의 created_at)."""
    if isinstance(value, dict):
        if value == {".sv": "timestamp"}:
            return now_ms
        return {k: _server_values(v, now_ms) for k, v in value.items()}
    return value


def classify(parts):
    """자리의 종류와 (업체, PC, 나머지). 모르는 자리는 (None, …)."""
    n = len(parts)
    if n >= 5 and parts[:2] == ["apps", APP] and parts[2] in ("live", "commands"):
        return parts[2], parts[3], parts[4], parts[5:]
    if n >= 5 and parts[:2] == ["meta", "companies"] and parts[3:5] == ["apps", APP]:
        return "policy", parts[2], None, parts[5:]
    if n == 4 and parts[:2] == ["meta", "companies"] and parts[3] == "phones":
        return "phones", parts[2], None, []
    if n >= 4 and parts[:2] == ["apps", "otp"] and parts[2] in ("requests", "codes"):
        return "otp_" + parts[2], parts[3], None, parts[4:]
    return None, None, None, []


def allowed(role, method, parts, lic):
    """이 열쇠가 이 자리에 이 일을 해도 되는가. 명령 자리의 쓰기는 command_writes_ok 가 내용까지 본다."""
    kind, cid, pc, rest = classify(parts)
    if kind is None or cid != lic["cid"]:
        return False
    if kind == "live":
        return role == "agent" and pc == lic["pc_id"]
    if kind == "commands":
        if role != "agent" or pc != lic["pc_id"]:
            return False
        return method in ("GET", "PATCH") or (method == "DELETE" and len(rest) == 1)
    if kind in ("policy", "phones"):
        return method == "GET"                       # 정책은 라이선스에서 온다 - 쓰는 길이 없다
    if kind == "otp_requests":
        return True                                  # 에이전트·중계 열쇠 모두 (같은 PC 의 실행)
    if kind == "otp_codes":
        return method in ("GET", "DELETE")           # 번호를 쓰는 쪽은 휴대폰 창구뿐 (계획 ④)
    return False


def command_writes_ok(store, base, rest, patch):
    """에이전트가 명령함에 하는 PATCH 가 '있는 명령의 상태 옮기기' 뿐인가.
    base = 명령함 자리(목록), rest = 그 아래 요청 자리, patch = 요청 본문. 명령 만들기·통째 덮기·고정 칸 바꾸기는 False."""
    if not isinstance(patch, dict) or len(rest) > 1:
        return False
    per = {}                                         # 명령 키 → {칸: 값}
    for key, value in patch.items():
        parts = rest + _split(key)
        if not parts:
            return False
        if len(parts) == 1:
            if value is not None:
                return False                         # 명령 통째로 쓰기 (None = 지우기는 둔다)
            per.setdefault(parts[0], {})
            continue
        if len(parts) > 2 and parts[1] in CMD_FIXED:
            return False                             # args 안쪽 고치기
        per.setdefault(parts[0], {})["/".join(parts[1:])] = value
    for key, fields in per.items():
        old = store.get("/".join(base + [key]))
        if not isinstance(old, dict):
            if fields:
                return False                         # 없는 명령에 쓰기 = 만들기
            continue
        for name, value in fields.items():
            top = name.split("/")[0]
            if top in CMD_FIXED and value != old.get(top):
                return False
        if "state" in fields and fields["state"] != old.get("state"):
            if fields["state"] not in CMD_MOVES.get(old.get("state"), ()):
                return False
    return True


class LocalServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False      # 윈도우에서 켜면 같은 포트에 두 번째 서버가 조용히 뜬다 (rpa_dashboard.DashboardServer 와 같다)

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        socketserver.TCPServer.server_bind(self)     # HTTPServer.server_bind 의 getfqdn 은 망에 따라 수 초 멈춘다
        self.server_name, self.server_port = self.server_address[:2]

    def shutdown(self):
        self.stopping.set()          # 열린 구독(SSE)이 먼저 끝나게 - 에이전트가 끝을 보고 다시 붙는다
        super().shutdown()


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "AutopilotLocal"
    sys_version = ""

    def log_message(self, *args):    # 요청마다 찍지 않는다 (창 없는 프로세스, 주소에 자리 이름이 든다)
        pass

    # --- 응답 ---
    def _reply(self, status, value=None, empty=False):
        body = b"" if empty else json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _body(self):
        """요청 본문(JSON). 없으면 None. 크거나 깨졌으면 응답을 보내고 _Stop."""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0:
            self._reply(400, {"error": "Bad request"})
            raise _Stop()
        if length > MAX_BODY:
            left = length
            while left > 0 and length <= 16 * MAX_BODY:      # 다 읽어 줘야 보내는 쪽이 413 을 받는다
                chunk = self.rfile.read(min(65536, left))
                if not chunk:
                    break
                left -= len(chunk)
            self._reply(413, {"error": "Too large"})
            raise _Stop()
        if not length:
            return None
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._reply(400, {"error": "Bad request"})
            raise _Stop() from None

    # --- 검사 ---
    def _role(self):
        """Host 와 열쇠를 보고 'agent'·'relay'. 아니면 응답을 보내고 _Stop."""
        host = (self.headers.get("Host") or "").rsplit(":", 1)
        if host[0] not in LOCAL_HOSTS or (len(host) == 2 and host[1] != str(self.server.server_port)):
            self._reply(403, DENIED)                 # 다른 이름으로 이 PC 를 가리킨 요청 (DNS 바꿔치기)
            raise _Stop()
        auth = self.headers.get("Authorization") or ""
        given = auth[7:].strip() if auth.startswith("Bearer ") else ""
        for role, key in zip(("agent", "relay"), self.server.keys):
            if given and hmac.compare_digest(given.encode("utf-8"), key.encode("utf-8")):
                return role
        self._reply(401, {"error": "Unauthorized"})
        raise _Stop()

    def _parts(self, raw):
        """주소의 자리 조각. 빈 조각·'.'·'..'·제어 글자가 있으면 400."""
        parts = [urllib.parse.unquote(p) for p in raw.split("/")]
        if any(not p or p in (".", "..") or any(ord(c) < 32 for c in p) for p in parts):
            self._reply(400, {"error": "Bad path"})
            raise _Stop()
        return parts

    # --- 길 ---
    def _route(self, method):
        try:
            url = urllib.parse.urlsplit(self.path)
            query = dict(urllib.parse.parse_qsl(url.query))
            role = self._role()
            if url.path.startswith("/db/") and url.path.endswith(".json"):
                return self._db(method, role, self._parts(url.path[4:-5]) if url.path != "/db/.json" else [], query)
            if url.path.startswith("/fs/") and method in ("GET", "POST"):
                return self._fs(method, role, self._parts(url.path[4:]), query)
            if url.path == "/fs-sum" and method == "GET":
                return self._fs_sum(role, query)
            self._reply(404, {"error": "Not found"})
        except _Stop:
            pass
        except (BrokenPipeError, ConnectionError):
            pass
        except Exception as e:                       # 서버가 죽지 않게 - 까닭의 종류만 남긴다
            log(self.server.folder, f"요청 처리 오류: {type(e).__name__}")
            try:
                self._reply(500, {"error": "Server error"})
            except Exception:
                pass

    def do_GET(self):
        self._route("GET")

    def do_PUT(self):
        self._route("PUT")

    def do_PATCH(self):
        self._route("PATCH")

    def do_DELETE(self):
        self._route("DELETE")

    def do_POST(self):
        self._route("POST")

    # --- 자리 (RTDB 꼴) ---
    def _db(self, method, role, parts, query):
        srv, lic = self.server, self.server.lic
        if method not in ("GET", "PUT", "PATCH", "DELETE") or not allowed(role, method, parts, lic):
            return self._reply(403, DENIED)
        kind, cid, pc, rest = classify(parts)
        path = "/".join(parts)
        if method == "GET":
            if kind == "policy":
                tree = {"modules": lic.get("modules") or {}, "features": lic.get("features") or {}, "limits": lic.get("limits") or {}}
                return self._reply(200, _lookup(tree, rest))
            if kind == "phones":
                return self._reply(200, srv.store.get(f"phones/{cid}"))
            order_by, equal_to = _json_arg(query.get("orderBy")), _json_arg(query.get("equalTo"))
            if "text/event-stream" in (self.headers.get("Accept") or ""):
                return self._stream(path, order_by, equal_to)
            value = srv.store.get(path, order_by, equal_to)
            if order_by is not None and isinstance(value, dict) and ("endAt" in query or "limitToFirst" in query):
                value = _range(value, order_by, _json_arg(query.get("endAt")), query.get("limitToFirst"))
            return self._reply(200, value)
        if method == "DELETE":
            srv.store.delete(path)
            return self._reply(200, None)
        body = _server_values(self._body(), int(time.time() * 1000))
        if kind == "commands":                       # PATCH 만 여기 온다 (allowed)
            if not command_writes_ok(srv.store, parts[:5], rest, body):
                return self._reply(403, DENIED)
        if method == "PATCH":
            if not isinstance(body, dict):
                return self._reply(400, {"error": "Bad request"})
            srv.store.patch(path, body)
        else:
            srv.store.put(path, body)
        if query.get("print") == "silent":
            return self._reply(204, empty=True)
        return self._reply(200, body)

    def _stream(self, path, order_by, equal_to):
        srv = self.server
        q = srv.store.subscribe(path, order_by, equal_to)
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            quiet = time.monotonic()
            while not srv.stopping.is_set():
                try:
                    event, data = q.get(timeout=0.5)
                except queue.Empty:
                    if time.monotonic() - quiet < KEEPALIVE_SEC:
                        continue
                    event, data = "keep-alive", None
                self.wfile.write(f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8"))
                self.wfile.flush()
                quiet = time.monotonic()
        finally:
            srv.store.unsubscribe(q)

    # --- 실행 기록 (Firestore 꼴) ---
    def _fs(self, method, role, parts, query):
        srv, lic = self.server, self.server.lic
        ok = role == "agent" and parts[:2] == ["runs", lic["cid"]] and parts[2:3] == ["items"]
        if method == "POST":
            if not ok or len(parts) != 3:
                return self._reply(403, DENIED)
            doc, doc_id = self._body(), query.get("id") or ""
            if not isinstance(doc, dict) or not 0 < len(doc_id) <= 200:
                return self._reply(400, {"error": "Bad request"})
            if not srv.runs.create("/".join(parts[:2]), parts[2], doc_id, doc):
                return self._reply(409, {"error": "Already exists"})
            return self._reply(200, {"id": doc_id})
        if not ok or len(parts) != 4:
            return self._reply(403, DENIED)
        doc = srv.runs.get("/".join(parts))
        return self._reply(200, doc) if doc is not None else self._reply(404, {"error": "Not found"})

    def _fs_sum(self, role, query):
        lic = self.server.lic
        if role != "agent" or query.get("parent") != f"runs/{lic['cid']}" or query.get("collection") != "items" or not query.get("field"):
            return self._reply(403, DENIED)
        return self._reply(200, {"sum": self.server.runs.sum(query["parent"], "items", query["field"], query.get("since") or None)})


class _Stop(Exception):
    """응답을 이미 보냈다 - 처리를 그만둔다."""


def _json_arg(raw):
    """질의 값 ("state" 처럼 JSON 으로 적힌 것). 없으면 None, JSON 이 아니면 글 그대로."""
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def _range(children, order_by, end_at, limit):
    """orderBy 칸으로 줄 세워 endAt 이하·앞에서 limitToFirst 개 (지난 명령 정리 agent.cleanup_commands 가 쓴다). 칸이 없는 자식은 뺀다."""
    rows = [(v.get(order_by), k, v) for k, v in children.items()
            if isinstance(v, dict) and isinstance(v.get(order_by), (int, float)) and not isinstance(v.get(order_by), bool)]
    if isinstance(end_at, (int, float)):
        rows = [r for r in rows if r[0] <= end_at]
    rows.sort(key=lambda r: (r[0], r[1]))
    try:
        rows = rows[:max(0, int(limit))] if limit is not None else rows
    except ValueError:
        pass
    return {k: v for _, k, v in rows} or None


def make_server(store, runs, lic, keys, host="127.0.0.1", port=PORT, folder=None):
    """로컬 서버를 만든다 (serve_forever 는 부르는 쪽이). 이 PC 주소에만 묶는다 - 포트가 쓰이는 중이면 OSError."""
    if host not in LOCAL_HOSTS:
        raise ValueError("로컬 서버는 이 PC(127.0.0.1)에만 엽니다.")
    srv = LocalServer(("127.0.0.1", port), Handler)
    srv.store, srv.runs, srv.lic, srv.keys = store, runs, lic, tuple(keys)
    srv.folder = folder or os.path.dirname(store.path or "") or "."
    srv.stopping = threading.Event()
    return srv


def main():
    """로컬 서버를 돈다. 종료 코드: 0 정상 끝, 2 라이선스가 없거나 맞지 않음 (다시 켜도 같다), 3 포트를 못 엶."""
    import license_check
    import rpa_status as st
    folder = data_dir()
    try:
        lic = license_check.load()
    except license_check.LicenseError as e:
        log(folder, f"로컬 서버를 열지 않았습니다 - {e}")
        return 2
    keys = ensure_keys(folder)
    store = Store(os.path.join(folder, "store.json"), volatile=VOLATILE)
    runs = Runs(os.path.join(folder, "runs.db"))
    try:
        port = int(st.dev_env("RPA_LOCAL_PORT") or PORT)
    except ValueError:
        port = PORT
    try:
        srv = make_server(store, runs, lic, keys, port=port, folder=folder)
    except OSError as e:
        log(folder, f"로컬 서버를 열지 못했습니다 - 포트 {port} 을(를) 다른 프로그램이 쓰고 있습니다. ({type(e).__name__})")
        return 3
    log(folder, f"로컬 서버 시작  업체={lic['cid']}  포트={port}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
        runs.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
