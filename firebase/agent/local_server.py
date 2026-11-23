# -*- coding: utf-8 -*-
"""스탠드얼론 로컬 서버 - 에이전트가 Firebase 에 쓰던 자리를 이 PC 안에서 받는다 (127.0.0.1:8781).
이 파일의 저장소 부분: Store(RTDB 자리 흉내 - JSON 나무·구독)와 Runs(Firestore 실행 기록 흉내 - SQLite).
둘 다 HTTP 를 모른다 - 창구(서버·인증·검사)는 이 파일 뒤쪽에 따로 붙는다.
표준 라이브러리만 쓴다.
"""
import copy
import hashlib
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

import local_store  # noqa: E402  요청·응답 서명 (클라이언트와 같은 함수)

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


class Refused(Exception):
    """쓰기 전 확인(guard)이 거절했다 - 아무것도 쓰지 않았다."""


SUB_QUEUE_MAX = 2000      # 구독 하나에 밀려도 되는 이벤트 수 - 넘으면 그 구독을 끊는다 (읽지 않는 연결이 메모리를 잡지 못하게)


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
        text = None
        for attempt in range(5):          # 백신 등이 잠깐 잡고 있어 못 읽은 것은 다시 읽는다 - 멀쩡한 파일을 .broken 으로 치우지 않는다 (검토 10번)
            try:
                with open(self.path, encoding="utf-8") as f:
                    text = f.read()
                break
            except FileNotFoundError:
                return {}
            except UnicodeDecodeError:
                return self._broken()
            except OSError:
                if attempt == 4:
                    raise             # 끝내 못 읽으면 서버가 끝나고 감독이 다시 켠다
                time.sleep(0.2)
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
    def put(self, path, value, guard=None):
        self._write("put", _split(path), [(_split(path), _clean(value))], None, guard)

    def patch(self, path, value, guard=None):
        """value 의 키마다 path 아래 그 자리를 새로 쓴다 (키에 '/' 가 있으면 여러 자리 쓰기 - RTDB PATCH 와 같다)."""
        base = _split(path)
        writes = [(base + _split(k), _clean(v)) for k, v in value.items()]
        self._write("patch", base, writes, copy.deepcopy(value), guard)

    def delete(self, path, guard=None):
        self._write("delete", _split(path), [(_split(path), None)], None, guard)

    def _write(self, kind, base, writes, raw, guard=None):
        """guard(get): 쓰기 직전에 잠금 안에서 부른다 (get(자리 글) = 지금 값). 거짓이면 Refused - 확인과 쓰기 사이에 다른 쓰기가 끼지 못한다."""
        with self._lock:
            old = self._data
            if guard is not None and not guard(lambda p: copy.deepcopy(_lookup(old, _split(p)))):
                raise Refused()
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
                    try:
                        sub["q"].put_nowait(ev)
                    except queue.Full:            # 읽지 않는 구독 - 끊는다 (받는 쪽이 overflow 를 보고 닫는다)
                        sub["q"].overflow = True
                        self._subs = [s for s in self._subs if s is not sub]
                        break

    # --- 구독 ---
    def subscribe(self, path, order_by=None, equal_to=None):
        """path 를 구독한다. 큐의 첫 항목은 ("put", {"path": "/", "data": 지금 값(거른 것)}), 그 뒤로 바뀔 때마다
        ("put"|"patch", {"path": "/<상대 경로>", "data": 값}). 거른 구독은 자식이 조건에 들어오면 그 자식 값을, 빠지면
        ("put", {"path": "/<키>", "data": None}) 을 넣는다. 다 쓰면 unsubscribe."""
        q = queue.Queue(maxsize=SUB_QUEUE_MAX)
        q.overflow = False
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
                was = _matches(_lookup(old, S + [key]), order_by, equal_to)
                child = _lookup(new, S + [key])
                now_in = _matches(child, order_by, equal_to)
                if was and now_in and len(rel) > 1:      # 계속 맞는 자식의 안쪽 칸 - 그 칸만 (Firebase 와 같다)
                    out.append(("put", {"path": "/" + "/".join(rel), "data": copy.deepcopy(_lookup(new, S + rel))}))
                    continue
                if key in seen:
                    continue
                seen.add(key)
                if now_in:
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
# 창구 - HTTP 서버·열쇠·검사 (계획 ① Task 3, 검토 2026-11-23 뒤 고침)
# ----------------------------------------------------------------------------------------------------
# 주소는 Firebase REST 와 같은 꼴이라 에이전트 코드가 그대로 돈다 (local_store.Client 가 부른다):
#   /db/<자리>.json        GET·PUT·PATCH·DELETE, Accept: text/event-stream 이면 구독 (SSE)
#   /fs/<parent>/<collection>?id=<문서 id>   POST 실행 기록 만들기,  /fs/<문서 자리>  GET,  /fs-sum?parent=&collection=&field=&since=
# 열쇠 둘: agent.key = 에이전트, relay.key = ACTOR 실행·옵저버의 인증번호 중계.
# 열쇠는 주고받지 않는다 - 요청마다 열쇠로 만든 서명(local_store.request_mac)을 확인하고, 응답·구독 이벤트에도 서명을 붙인다.
# 그래서 포트를 먼저 잡은 다른 프로그램은 열쇠를 얻지 못하고, 에이전트는 그 프로그램의 답을 믿지 않는다 (검토 1번).
# 검사는 지금 RTDB 규칙과 같은 뜻 - 에이전트는 자기 PC 자리만 쓰고, 명령은 만들지 못하고 상태만 옮긴다.
# 브라우저 쪽(/api/*·웹 파일)은 local_web.py 가 맡는다 (계획 ② Task 2) - 서명이 아니라 로그인 세션 토큰으로 확인하고 응답에 서명이 없다.
# Handler._route 가 서명 확인 앞에서 갈라 넘긴다. 위의 /db·/fs·/fs-sum 은 그대로 서명만 받는다 (세션 토큰은 통하지 않는다).

APP = "rpa"
MAX_BODY = 4 * 1024 * 1024
MAX_CONN = 64                              # 동시에 붙을 수 있는 연결 - 넘으면 바로 닫는다 (빈 연결로 스레드를 잡아 두지 못하게)
READ_TIMEOUT = 15                          # 요청 줄·머리글·본문을 이 안에 못 읽으면 끊는다
KEEPALIVE_SEC = 30
SIGN_WINDOW_MS = 60000                     # 요청 시각이 서버 시각과 이만큼 넘게 다르면 거절 (같은 PC 라 넉넉하다)
NONCE_KEEP_SEC = 150
LOG_NAME = "로컬서버_기록.txt"
LOG_MAX = 1024 * 1024
KEY_FILES = ("agent.key", "relay.key")
VOLATILE = ("apps/otp", f"apps/{APP}/live")   # 인증번호와 현황은 메모리에만 (파일에 남기지 않는다 - 현황은 에이전트가 곧 다시 올린다)
LOCAL_HOSTS = ("127.0.0.1", "localhost")
CMD_WRITABLE = ("state", "result", "started_at", "ended_at")        # 에이전트가 명령에 쓸 수 있는 칸 (그 밖 type·args·by·시각은 못 바꾼다)
CMD_MOVES = {"queued": ("running", "expired", "failed"), "running": ("done", "failed")}
CMD_FINAL = ("done", "failed", "expired")
OTP_KEYS = ("req_id", "site", "senders", "pcId", "created_at")
OTP_MAX_SENDERS = 20
DENIED = {"error": "Permission denied"}     # fb.HttpError 본문을 보는 코드가 같은 글을 찾는다


def _read_text(path, tries=5):
    """글 파일을 읽는다. 없으면 None. 잠깐 못 읽는 것(백신이 잡고 있음 등)은 몇 번 다시 - 끝내 못 읽으면 OSError."""
    for i in range(tries):
        try:
            with open(path, encoding="ascii") as f:
                return f.read().strip()
        except FileNotFoundError:
            return None
        except UnicodeDecodeError:
            return ""
        except OSError:
            if i == tries - 1:
                raise
            time.sleep(0.2)


def ensure_keys(folder):
    """에이전트·인증번호 중계 열쇠 (agent.key, relay.key). 없으면 만든다. 파일 권한은 설치 쪽이 잠근다 (계획 ③).
    있는 파일을 잠깐 못 읽었다고 새 열쇠로 덮지 않는다 - 돌고 있던 ACTOR·옵저버가 끊긴다 (검토 10번). 그때는 OSError."""
    os.makedirs(folder, exist_ok=True)
    out = []
    for name in KEY_FILES:
        path = os.path.join(folder, name)
        key = _read_text(path) or ""
        if len(key) < 32:
            key = secrets.token_urlsafe(32)
            tmp = f"{path}.{os.getpid()}.tmp"
            with open(tmp, "w", encoding="ascii") as f:
                f.write(key + "\n")
            os.replace(tmp, path)
        out.append(key)
    return tuple(out)


def log(folder, text):
    """서버 기록 한 줄. 열쇠·인증번호는 싣지 않는다. 1MB 를 넘으면 .1 로 넘긴다. 예외를 내지 않는다."""
    try:
        path = os.path.join(folder, LOG_NAME)
        try:
            if os.path.getsize(path) > LOG_MAX:
                os.replace(path, path + ".1")
        except OSError:
            pass
        with open(path, "a", encoding="utf-8") as f:
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
    """이 열쇠가 이 자리에 이 일을 해도 되는가 (자리와 방법까지). 내용은 command_patch_ok·command_delete_ok·otp_request_ok 가 본다."""
    kind, cid, pc, rest = classify(parts)
    if kind is None or cid != lic["cid"]:
        return False
    if kind == "live":
        return role == "agent" and pc == lic["pc_id"]
    if kind == "commands":
        if role != "agent" or pc != lic["pc_id"]:
            return False
        return method == "GET" or (method == "PATCH" and len(rest) <= 1) or (method == "DELETE" and len(rest) == 1)
    if kind == "policy":
        return role == "agent" and method == "GET"   # 정책은 라이선스에서 온다 - 쓰는 길이 없다. 중계 열쇠는 읽지도 못한다
    if kind == "phones":
        return method == "GET"
    one = len(rest) == 2 and rest[1] == "current"    # 인증번호 자리는 <휴대폰>/current 하나뿐 (규칙과 같다)
    if kind == "otp_requests":
        return one and method in ("GET", "PUT", "DELETE")      # 에이전트·중계 열쇠 모두 (같은 PC 의 실행)
    if kind == "otp_codes":
        return one and method in ("GET", "DELETE")              # 번호를 쓰는 쪽은 휴대폰 창구뿐 (계획 ④)
    return False


def _number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def command_patch_ok(get, base, rest, patch):
    """에이전트가 명령함에 하는 PATCH 가 '있는 명령의 상태를 한 칸 옮기기' 뿐인가 (규칙: queued→running 은 한 번만).
    get(자리 글) = 지금 값 (Store 가 잠금 안에서 부른다 - 확인과 쓰기 사이에 다른 요청이 끼지 못한다).
    base = 명령함 자리(조각 목록), rest = 그 아래 요청 자리, patch = 요청 본문.
    명령 만들기·통째 덮기·지우기·고정 칸(type·args·by·시각)·모르는 칸·같은 상태로 다시 쓰기는 False."""
    if not isinstance(patch, dict) or not patch or len(rest) > 1:
        return False
    per = {}                                         # 명령 키 → {칸: 값}
    for key, value in patch.items():
        parts = rest + _split(key)
        if len(parts) != 2:                          # <명령>/<칸> 꼴만 - 명령 통째(1)·칸 안쪽(3 이상)은 안 된다
            return False
        per.setdefault(parts[0], {})[parts[1]] = value
    for key, fields in per.items():
        old = get("/".join(base + [key]))
        if not isinstance(old, dict) or "state" not in fields:
            return False
        for name, value in fields.items():
            if name not in CMD_WRITABLE:
                return False
            if name == "state" and not isinstance(value, str):
                return False
            if name == "result" and not (isinstance(value, str) and len(value) <= 2000):
                return False
            if name in ("started_at", "ended_at") and not _number(value):
                return False
        if fields["state"] not in CMD_MOVES.get(old.get("state"), ()):
            return False
    return True


def command_delete_ok(get, path):
    """끝난 명령(done·failed·expired)만 지울 수 있다 (규칙과 같다) - 대기·진행 중인 명령을 지워 없던 일로 만들지 못한다."""
    old = get(path)
    return old is None or (isinstance(old, dict) and old.get("state") in CMD_FINAL)


def otp_request_ok(body, lic):
    """인증번호 요청의 모양 (규칙과 같은 뜻): 정해진 칸만, 이 PC 의 요청, 발신번호는 숫자 글 → true 로 OTP_MAX_SENDERS 개까지.
    등록된 휴대폰·그 휴대폰의 발신번호 목록과 견주기는 휴대폰 창구(계획 ④)가 더한다."""
    if not isinstance(body, dict) or set(body) - set(OTP_KEYS):
        return False
    if not (isinstance(body.get("req_id"), str) and 0 < len(body["req_id"]) <= 64):
        return False
    if not (isinstance(body.get("site"), str) and len(body["site"]) <= 200):
        return False
    if body.get("pcId") != lic["pc_id"]:
        return False
    senders = body.get("senders", {})
    if not isinstance(senders, dict) or len(senders) > OTP_MAX_SENDERS:
        return False
    return all(isinstance(k, str) and k.isdigit() and len(k) <= 20 and v is True for k, v in senders.items())


def local_host(headers, port):
    """Host 머리글이 이 PC 주소·이 포트인가 - 다른 이름으로 이 PC 를 가리킨 요청(DNS 바꿔치기)을 거른다.
    에이전트 창구(Handler._role)와 웹 창구(local_web.Web.handle)가 같이 쓴다."""
    host = (headers.get("Host") or "").rsplit(":", 1)
    return host[0] in LOCAL_HOSTS and (len(host) == 1 or host[1] == str(port))


def _agent_path(path):
    """에이전트 창구의 주소인가 (/db·/fs·/fs-sum) - 여기는 늘 요청 서명을 본다 (웹 창구로 넘기지 않는다)."""
    return path in ("/db", "/fs", "/fs-sum") or path.startswith(("/db/", "/fs/"))


class LocalServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False      # 윈도우에서 켜면 같은 포트에 두 번째 서버가 조용히 뜬다 (rpa_dashboard.DashboardServer 와 같다)

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        socketserver.TCPServer.server_bind(self)     # HTTPServer.server_bind 의 getfqdn 은 망에 따라 수 초 멈춘다
        self.server_name, self.server_port = self.server_address[:2]

    def process_request(self, request, client_address):
        with self.conn_lock:
            if self.conns >= MAX_CONN:               # 연결을 쌓아 두는 프로그램이 있어도 스레드가 끝없이 늘지 않게 (검토 4번)
                self.shutdown_request(request)
                return
            self.conns += 1
        super().process_request(request, client_address)

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            with self.conn_lock:
                self.conns -= 1

    def fresh_nonce(self, nonce, now):
        """이 nonce 를 처음 보는가 (같은 요청을 다시 보내기 막기). 지난 것은 지운다."""
        with self.conn_lock:
            if len(self.nonces) > 5000:
                for k in [k for k, t in self.nonces.items() if t < now]:
                    del self.nonces[k]
            if self.nonces.get(nonce, 0) >= now:
                return False
            self.nonces[nonce] = now + NONCE_KEEP_SEC
            return True

    def shutdown(self):
        self.stopping.set()          # 열린 구독(SSE)이 먼저 끝나게 - 에이전트가 끝을 보고 다시 붙는다
        super().shutdown()


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "AutopilotLocal"
    sys_version = ""
    timeout = READ_TIMEOUT           # 아무것도 보내지 않는 연결은 끊는다
    _auth = None                     # (열쇠, nonce) - 서명을 확인한 뒤 채운다. 그 뒤의 응답에는 서명이 붙는다

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
        if self._auth:
            self.send_header(local_store.H_SIGN, local_store.response_mac(self._auth[0], self._auth[1], status, body))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _read(self):
        """요청 본문 → (bytes 또는 너무 크면 None, sha256 글). 길이가 이상하면 응답을 보내고 _Stop."""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0 or length > 16 * MAX_BODY:
            self._reply(400, {"error": "Bad request"})
            raise _Stop()
        h, chunks, left = hashlib.sha256(), [], length
        while left > 0:
            chunk = self.rfile.read(min(65536, left))
            if not chunk:
                break
            h.update(chunk)
            if length <= MAX_BODY:
                chunks.append(chunk)
            left -= len(chunk)
        return (b"".join(chunks) if length <= MAX_BODY else None), h.hexdigest()

    # --- 검사 ---
    def _role(self, method, digest):
        """Host 와 요청 서명을 보고 'agent'·'relay'. 아니면 (서명 없는) 응답을 보내고 _Stop."""
        srv = self.server
        if not local_host(self.headers, srv.server_port):
            self._reply(403, DENIED)                 # 다른 이름으로 이 PC 를 가리킨 요청 (DNS 바꿔치기)
            raise _Stop()
        role = self.headers.get(local_store.H_ROLE) or ""
        ts, nonce = self.headers.get(local_store.H_TIME) or "", self.headers.get(local_store.H_NONCE) or ""
        sign = self.headers.get(local_store.H_SIGN) or ""
        now = time.time()
        ok = role in local_store.ROLES and ts.isdigit() and 16 <= len(nonce) <= 64 and abs(now * 1000 - int(ts)) <= SIGN_WINDOW_MS
        if ok:
            key = srv.keys[local_store.ROLES.index(role)]
            want = local_store.request_mac(key, role, method, self.path, ts, nonce, b"", digest=digest)
            ok = hmac.compare_digest(sign, want) and srv.fresh_nonce(nonce, now)
        if not ok:
            self._reply(401, {"error": "Unauthorized"})
            raise _Stop()
        self._auth = (key, nonce)
        return role

    def _parts(self, raw):
        """주소의 자리 조각. 빈 조각·'.'·'..'·제어 글자, 풀었을 때 '/'·'\\' 가 든 조각(%2F - 깊이 검사를 속인다, 검토 3번)은 400."""
        parts = [urllib.parse.unquote(p) for p in raw.split("/")]
        if any(not p or p in (".", "..") or "/" in p or "\\" in p or any(ord(c) < 32 for c in p) for p in parts):
            self._reply(400, {"error": "Bad path"})
            raise _Stop()
        return parts

    def _json_body(self, raw):
        if raw is None:
            self._reply(413, {"error": "Too large"})
            raise _Stop()
        if not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._reply(400, {"error": "Bad request"})
            raise _Stop() from None

    # --- 길 ---
    def _route(self, method):
        try:
            url = urllib.parse.urlsplit(self.path)
            query = dict(urllib.parse.parse_qsl(url.query))
            raw, digest = self._read()
            web = getattr(self.server, "web", None)
            if web is not None and not _agent_path(url.path) and (url.path.startswith("/api/") or method == "GET"):
                # 브라우저 창구 (/api/*·웹 파일) - 세션 토큰으로 확인하고 응답에 서명을 붙이지 않는다 (_auth 는 None 그대로).
                # Host 검사는 local_web 이 같은 local_host 로 한다. 처리하지 않은 것(False)만 아래 서명 확인으로 간다
                if web.handle(self, method, url.path, query, raw):
                    return
            role = self._role(method, digest)
            if url.path.startswith("/db/") and url.path.endswith(".json"):
                return self._db(method, role, self._parts(url.path[4:-5]), query, raw)
            if url.path.startswith("/fs/") and method in ("GET", "POST"):
                return self._fs(method, role, self._parts(url.path[4:]), query, raw)
            if url.path == "/fs-sum" and method == "GET":
                return self._fs_sum(role, query)
            self._reply(404, {"error": "Not found"})
        except _Stop:
            pass
        except (BrokenPipeError, ConnectionError, TimeoutError):
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
    def _db(self, method, role, parts, query, raw):
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
        try:
            if method == "DELETE":
                guard = (lambda get: command_delete_ok(get, path)) if kind == "commands" else None
                srv.store.delete(path, guard=guard)
                return self._reply(200, None)
            body = _server_values(self._json_body(raw), int(time.time() * 1000))
            if kind == "commands":                   # PATCH 만 여기 온다 (allowed) - 확인과 쓰기를 한 잠금 안에서
                if not isinstance(body, dict):
                    return self._reply(403, DENIED)
                srv.store.patch(path, body, guard=lambda get: command_patch_ok(get, parts[:5], rest, body))
            elif kind == "otp_requests":             # PUT 만 여기 온다
                if not otp_request_ok(body, lic):
                    return self._reply(403, DENIED)
                srv.store.put(path, dict(body, created_at=int(time.time() * 1000)))
            elif method == "PATCH":
                if not isinstance(body, dict):
                    return self._reply(400, {"error": "Bad request"})
                srv.store.patch(path, body)
            else:
                srv.store.put(path, body)
        except Refused:
            return self._reply(403, DENIED)
        if query.get("print") == "silent":
            return self._reply(204, empty=True)
        return self._reply(200, body)

    def _stream(self, path, order_by, equal_to):
        srv = self.server
        key, nonce = self._auth
        q = srv.store.subscribe(path, order_by, equal_to)
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header(local_store.H_SIGN, local_store.response_mac(key, nonce, 200, b""))
            self.end_headers()
            quiet, seq = time.monotonic(), 0
            while not srv.stopping.is_set():
                try:
                    event, data = q.get(timeout=0.5)
                except queue.Empty:
                    if getattr(q, "overflow", False):      # 읽지 않아 밀린 구독 - 끊는다 (다시 붙으면 처음 값부터 받는다)
                        break
                    if time.monotonic() - quiet < KEEPALIVE_SEC:
                        continue
                    event, data = "keep-alive", None
                seq += 1
                text = json.dumps(data, ensure_ascii=False)
                mac = local_store.event_mac(key, nonce, seq, event, text)
                self.wfile.write(f"event: {event}\ndata: {text}\nmac: {mac}\n\n".encode("utf-8"))
                self.wfile.flush()
                quiet = time.monotonic()
        finally:
            srv.store.unsubscribe(q)

    # --- 실행 기록 (Firestore 꼴) ---
    def _fs(self, method, role, parts, query, raw):
        srv, lic = self.server, self.server.lic
        ok = role == "agent" and parts[:2] == ["runs", lic["cid"]] and parts[2:3] == ["items"]
        if method == "POST":
            if not ok or len(parts) != 3:
                return self._reply(403, DENIED)
            doc, doc_id = self._json_body(raw), query.get("id") or ""
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
    rows = [(v.get(order_by), k, v) for k, v in children.items() if isinstance(v, dict) and _number(v.get(order_by))]
    if _number(end_at):
        rows = [r for r in rows if r[0] <= end_at]
    rows.sort(key=lambda r: (r[0], r[1]))
    try:
        rows = rows[:max(0, int(limit))] if limit is not None else rows
    except ValueError:
        pass
    return {k: v for _, k, v in rows} or None


def make_server(store, runs, lic, keys, host="127.0.0.1", port=PORT, folder=None, web=None):
    """로컬 서버를 만든다 (serve_forever 는 부르는 쪽이). 이 PC 주소에만 묶는다 - 포트가 쓰이는 중이면 OSError.
    web: 브라우저 창구 (local_web.Web). 없으면 에이전트 창구만 연다 (/api·웹 파일은 서명 없는 요청으로 거절된다)."""
    if host not in LOCAL_HOSTS:
        raise ValueError("로컬 서버는 이 PC(127.0.0.1)에만 엽니다.")
    srv = LocalServer(("127.0.0.1", port), Handler, bind_and_activate=False)
    srv.store, srv.runs, srv.lic, srv.keys = store, runs, lic, tuple(keys)
    srv.web = web
    srv.folder = folder or os.path.dirname(store.path or "") or "."
    srv.stopping = threading.Event()
    srv.conn_lock, srv.conns, srv.nonces = threading.Lock(), 0, {}
    try:
        srv.server_bind()
        srv.server_activate()
    except BaseException:
        srv.server_close()
        raise
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
    sys.modules.setdefault("local_server", sys.modules[__name__])     # `python local_server.py` 로 켜면 이 모듈은 __main__ - local_web 이 같은 것을 쓰게 (두 벌로 불러오면 Refused 등이 서로 다른 클래스가 된다)
    import local_web
    web = local_web.Web(store, runs, lic, folder, local_web.web_dir())
    if not os.path.isdir(web.web_dir):
        log(folder, f"웹 파일 폴더가 없습니다 - 화면을 내주지 못합니다. ({web.web_dir})")
    try:
        srv = make_server(store, runs, lic, keys, port=port, folder=folder, web=web)
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
