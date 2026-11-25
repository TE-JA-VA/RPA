# -*- coding: utf-8 -*-
"""스탠드얼론 로컬 서버 - 에이전트가 Firebase 에 쓰던 자리를 이 PC 안에서 받는다 (127.0.0.1:8781).
이 파일의 저장소 부분: Store(RTDB 자리 흉내 - JSON 나무·구독)와 Runs(Firestore 실행 기록 흉내 - SQLite).
둘 다 HTTP 를 모른다 - 창구(서버·인증·검사)는 이 파일 뒤쪽에 따로 붙는다.
표준 라이브러리만 쓴다.
"""
import contextlib
import copy
import dataclasses
import hashlib
import hmac
import http.server
import json
import os
import queue
import re
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

import ap_sign  # noqa: E402  요청·응답·구독 서명 (클라이언트 local_store 와 같은 함수 - 서버는 PC 클라이언트를 불러오지 않는다)
import pc_registry  # noqa: E402  사내 서버 PC 등록부 (EnrollError·PC_RE - 표준 라이브러리만 쓴다)
import server_log  # noqa: E402  사내 서버(리눅스)의 server.log·audit.log - 정하지 않으면(단독) log 는 지금 그대로 (사내 서버 ④ Task 1)

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
_NOLOCK = contextlib.nullcontext()   # 영속 쓰기 잠금이 없을 때 (단독 - 지금 그대로)


class Store:
    """JSON 나무 하나를 파일에 둔 저장소 (RTDB 자리 흉내). 쓸 때마다 파일에 원자적으로 저장한다.
    - 값이 None 이거나 비어 있으면 지운 것 - 빈 가지는 없앤다 (get 은 None).
    - 쓰기는 나무를 복사해 고친 뒤 저장이 끝나야 바꿔 끼운다 (저장이 실패하면 메모리도 그대로).
    - 읽기는 잠금 없이 (바꿔 끼운 나무는 다시 고치지 않는다). 쓰기와 구독 알림은 잠금 하나로 묶는다.
    persist_lock: 사내 서버(리눅스)의 같은 시점 백업 잠금 (server_backup.attach 가 단다) - 파일 쓰기를 이 잠금 안에서 한다.
    단독은 None (지금 그대로)."""

    persist_lock = None

    def __init__(self, path, volatile=()):
        """volatile: 파일에 남기지 않는 자리들 (예 "apps/otp" - 인증번호). 메모리에는 있고 구독도 되지만 다시 켜면 비어 있다."""
        self.path = os.path.abspath(path)
        self._volatile = [_split(p) for p in volatile]
        self._lock = threading.Lock()
        self._subs = []
        self._data = self._load()
        self.saves = 0                    # 파일을 실제로 쓴 횟수 (시험이 센다)

    def _volatile_only(self, writes):
        """이번 쓰기가 모두 메모리에만 두는 자리(volatile) 아래인가 - 그러면 파일 내용이 그대로라 다시 쓰지 않는다
        (사내 서버 ① Task 1, 설계 2026-11-24 13절 2번 - 현황은 PC 수만큼 가장 자주 오는 쓰기). 윗자리(루트 포함) 쓰기는 아니다."""
        return bool(writes) and all(any(len(parts) >= len(v) and parts[:len(v)] == v for v in self._volatile) for parts, _ in writes)

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
            if not self._volatile_only(writes):
                with self.persist_lock or _NOLOCK:
                    self._save(new)
                self.saves += 1
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
    HTTP 서버가 스레드마다 부르므로 연결 하나를 잠금으로 감싼다.
    persist_lock: 사내 서버의 같은 시점 백업 잠금 (server_backup.attach) - 쓰기는 이 잠금 → 연결 잠금 차례로 잡는다."""

    persist_lock = None

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

    def backup_to(self, path):
        """SQLite 백업 기능으로 path 에 사본을 뜬다 (사내 서버 백업 - server_backup.snapshot 이 영속 잠금을 쥔 채 부른다)."""
        with self._lock:
            dst = sqlite3.connect(path)
            try:
                self._db.backup(dst)
            finally:
                dst.close()

    @staticmethod
    def _text(value):
        return None if value is None else str(value)

    @staticmethod
    def _key(doc_id, pc_id):
        """표에 두는 문서 키. 사내 서버(pc_id 있음)는 '<PC 번호>:<id>' - 같은 id 를 PC 마다 따로 만들고, 남의 문서는 없는 것과 같다
        (사내 서버 ② Task 7, 검토 M-6). 단독(pc_id 없음)은 id 그대로 - 옛 runs.db 를 그대로 읽는다."""
        return doc_id if pc_id is None else f"{pc_id}:{doc_id}"

    def create(self, parent, collection, doc_id, fields, pc_id=None):
        """기록 하나 만들기. 이미 있으면 False (덮어쓰지 않는다). pc_id: 사내 서버의 PC 번호 (문서 키에 넣는다, _key)."""
        with self.persist_lock or _NOLOCK, self._lock, self._db:
            cur = self._db.execute(
                "INSERT OR IGNORE INTO docs(parent, collection, id, pc_id, date, started_at, doc) VALUES(?,?,?,?,?,?,?)",
                (parent, collection, self._key(doc_id, pc_id), self._text(fields.get("pcId")), self._text(fields.get("date")),
                 self._text(fields.get("started_at")), json.dumps(fields, ensure_ascii=False)))
            return cur.rowcount == 1

    def get(self, path, pc_id=None):
        """path = '<parent>/<collection>/<id>' (parent 에 '/' 가 들어 있어도 된다). 없으면 None.
        pc_id: 사내 서버의 PC 번호 - 그 PC 가 만든 문서만 찾는다 (_key)."""
        parts = _split(path)
        if len(parts) < 3:
            return None
        parent, collection, doc_id = "/".join(parts[:-2]), parts[-2], parts[-1]
        with self._lock:
            row = self._db.execute("SELECT doc FROM docs WHERE parent=? AND collection=? AND id=?",
                                   (parent, collection, self._key(doc_id, pc_id))).fetchone()
        return json.loads(row[0]) if row else None

    def sum(self, parent, collection, field, since=None, pc_id=None):
        """field 칸의 합. since 가 있으면 started_at >= since 인 문서만. 칸이 없거나 숫자가 아닌 문서는 뺀다.
        pc_id 가 있으면 그 PC 의 문서만 (사내 서버 - 남의 PC 기록을 더해 보지 못하게, 검토 2026-11-24 I-2)."""
        sql = "SELECT doc FROM docs WHERE parent=? AND collection=?"
        args = [parent, collection]
        if pc_id is not None:
            sql += " AND pc_id=?"
            args.append(str(pc_id))
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

    def purge(self, before_ms):
        """시작 시각(started_at - 'YYYY-MM-DDTHH:MM:SS' 꼴의 이 컴퓨터 시각)이 before_ms 보다 앞인 기록을 지운다 → 지운 수.
        사내 서버 입구(server_main)의 하루 한 번 정비가 1년(365일) 지난 기록에 부른다 (사내 서버 ④ Task 3).
        시작 시각이 없거나 그 꼴이 아닌 기록은 남긴다. 단독은 부르지 않는다."""
        import datetime
        cut = datetime.datetime.fromtimestamp(before_ms / 1000).isoformat(timespec="seconds")
        with self.persist_lock or _NOLOCK, self._lock, self._db:
            return self._db.execute(
                "DELETE FROM docs WHERE started_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]*' AND started_at < ?",
                (cut,)).rowcount

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
# 열쇠는 주고받지 않는다 - 요청마다 열쇠로 만든 서명(ap_sign.request_mac)을 확인하고, 응답·구독 이벤트에도 서명을 붙인다.
# 그래서 포트를 먼저 잡은 다른 프로그램은 열쇠를 얻지 못하고, 에이전트는 그 프로그램의 답을 믿지 않는다 (검토 1번).
# 검사는 지금 RTDB 규칙과 같은 뜻 - 에이전트는 자기 PC 자리만 쓰고, 명령은 만들지 못하고 상태만 옮긴다.
# 브라우저 쪽(/api/*·웹 파일)은 local_web.py 가 맡는다 (계획 ② Task 2) - 서명이 아니라 로그인 세션 토큰으로 확인하고 응답에 서명이 없다.
# Handler._route 가 서명 확인 앞에서 갈라 넘긴다. 위의 /db·/fs·/fs-sum 은 그대로 서명만 받는다 (세션 토큰은 통하지 않는다).

APP = "rpa"
MAX_BODY = 4 * 1024 * 1024
MAX_CONN = 64                              # 동시에 붙을 수 있는 연결 - 넘으면 바로 닫는다 (빈 연결로 스레드를 잡아 두지 못하게)
READ_TIMEOUT = 15                          # 요청 줄·머리글·본문을 이 안에 못 읽으면 끊는다
KEEPALIVE_SEC = 30
TOO_MANY_MSG = "요청이 너무 많습니다. 잠시 후 다시 시도하여 주십시오."     # 사내망 웹 포트의 프록시 뒤 보낸 사람마다 상한 (lan_server.client_hold)
SIGN_WINDOW_MS = 60000                     # 요청 시각이 서버 시각과 이만큼 넘게 다르면 거절 (같은 PC 라 넉넉하다)
NONCE_KEEP_SEC = 150
NONCE_SWEEP_SEC = 10                       # nonce 표에서 지난 것을 지우는 간격 (표 크기가 아니라 시간으로 - 검토 M-7)
PC_REQ_MIN = 1200                          # 사내 서버: PC 하나의 분당 서명 요청 - 넘으면 서명된 429 (검토 M-7)
LOG_NAME = "로컬서버_기록.txt"
LOG_MAX = 1024 * 1024
REJECT_LOG_MAX, REJECT_LOG_SEC = 10, 60    # PC 등록 거절 기록은 서버 전체에서 60초에 10줄까지 (쓰레기 /enroll 로 기록을 채우지 못하게, 검토 I-3)
KEY_FILES = ("agent.key", "relay.key")
VOLATILE = ("apps/otp", f"apps/{APP}/live")   # 인증번호와 현황은 메모리에만 (파일에 남기지 않는다 - 현황은 에이전트가 곧 다시 올린다)
LOCAL_HOSTS = ("127.0.0.1", "localhost")
CMD_WRITABLE = ("state", "result", "started_at", "ended_at")        # 에이전트가 명령에 쓸 수 있는 칸 (그 밖 type·args·by·시각은 못 바꾼다)
CMD_MOVES = {"queued": ("running", "expired", "failed"), "running": ("done", "failed")}
CMD_FINAL = ("done", "failed", "expired")
OTP_KEYS = ("req_id", "site", "senders", "pcId", "created_at")
OTP_MAX_SENDERS = 20
DENIED = {"error": "Permission denied"}     # fb.HttpError 본문을 보는 코드가 같은 글을 찾는다


@dataclasses.dataclass(frozen=True)
class Deploy:
    """서버 배치 (사내 서버 ① Task 4, 설계 6.4·6.5). make_server 의 registry 가 있으면 LAN, 없으면 SINGLE (지금 그대로).
    max_conn 동시 연결, web_streams 웹 구독, agent_streams 에이전트 구독 전체, per_pc_streams PC 하나의 에이전트 구독
    (0 이면 세지 않는다), sign_window_ms 요청 시각 허용 차이."""
    mode: str
    max_conn: int
    web_streams: int
    agent_streams: int
    per_pc_streams: int
    sign_window_ms: int


SINGLE = Deploy("single", MAX_CONN, 16, 0, 0, SIGN_WINDOW_MS)   # 단독(나) - 지금 상수 그대로
LAN = Deploy("lan", 256, 32, 64, 4, 120000)                       # 사내 서버 - PC 여러 대, 닫힌 망이라 시계 차이를 넉넉히
STATE_CHECK_SEC = 1.0                      # 사내 서버 구독 고리가 PC 상태(중지·지워짐)를 다시 보는 간격
ENROLL_NONCE = re.compile(r"[A-Za-z0-9_-]{16,64}")
ENROLL_FIELDS = ("pc", "rand", "guid", "host", "nonce", "proof")


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


LOCKED_FILES = ("agent.key", "relay.key", "accounts.json",
                "phone_key.pem", "phones.json",     # 휴대폰 포트의 인증서 개인 열쇠·짝지은 휴대폰의 서명 열쇠 (계획 ④ - local_cert·local_phone)
                "pcs.json")                         # 사내 서버의 PC 등록부 - PC 마다의 열쇠 (사내 서버 ① Task 2 - pc_registry)
ADMIN_SIDS = ("*S-1-5-32-544", "*S-1-5-18")       # 관리자, SYSTEM


def lock_key_files(folder, readers=(), run=None):
    """열쇠·계정 파일(LOCKED_FILES)에 따로 붙은 권한을 지우고 관리자·SYSTEM 만 남긴다 (계획 ③ Task 4). readers(윈도우 계정 이름)가
    있으면 relay.key 에만 읽기를 더한다 - 기본은 없다 (옵저버·ACTOR 도 관리자 권한으로 돈다). 설정 폴더의 권한 다시 잠그기
    (rpa_settings.lock_data_acl 의 /reset /T)가 지운 뒤에도 같은 상태가 되게 서버가 켤 때마다·설치 마무리가 부른다.
    icacls 종료 코드 목록. 예외를 내지 않는다 - 실패해도 서버는 켜진다. run 은 시험용 (args, timeout) → (코드, 출력).
    posix(사내 서버 리눅스, 사내 서버 ④ Task 1 - ②-T8): icacls 를 부르지 않고 있는 파일을 0600, 폴더를 0700 으로 (readers 는 쓰지
    않는다 - 서비스 계정 하나만 읽는다). 목록은 파일마다 0(됨)·-1(못 함), 끝에 폴더 하나."""
    if os.name == "posix":
        codes = []
        for name in LOCKED_FILES:
            path = os.path.join(folder, name)
            if not os.path.isfile(path):
                continue
            try:
                os.chmod(path, 0o600)
                codes.append(0)
            except OSError:
                codes.append(-1)
        try:
            os.chmod(folder, 0o700)
            codes.append(0)
        except OSError:
            codes.append(-1)
        return codes
    import subprocess

    def default(args, timeout=60):
        r = subprocess.run(args, capture_output=True, timeout=timeout, creationflags=0x08000000)
        return r.returncode, ""
    run = run or default
    icacls = os.path.join(os.environ.get("SystemRoot") or r"C:\Windows", "System32", "icacls.exe")
    codes = []
    for name in LOCKED_FILES:
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            continue
        grants = [f"{sid}:F" for sid in ADMIN_SIDS] + ([f"{r}:R" for r in readers] if name == "relay.key" else [])
        for args in ([path, "/reset", "/C", "/Q"], [path, "/inheritance:r", "/grant:r", *grants, "/C", "/Q"]):
            try:
                codes.append(run([icacls, *args], timeout=60)[0])
            except Exception:
                codes.append(-1)
    return codes


def ensure_keys(folder, lock=None):
    """에이전트·인증번호 중계 열쇠 (agent.key, relay.key). 없으면 만든다. 그 뒤 열쇠·계정 파일 권한을 잠근다 (lock_key_files) -
    lock 이 None 이면 설치본에서만 (소스·시험은 일반 권한으로 돌아 잠그면 스스로 못 읽는다).
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
    if lock is None:
        try:
            import rpa_status
            lock = rpa_status.shipped()
        except Exception:
            lock = False
    if lock:
        lock_key_files(folder)
    return tuple(out)


def log(folder, text):
    """서버 기록 한 줄. 열쇠·인증번호는 싣지 않는다. 1MB 를 넘으면 .1 로 넘긴다. 예외를 내지 않는다.
    사내 서버(리눅스)가 server_log.configure 로 자리를 정했으면 server.log 로 (10MB 다섯 개) - 단독은 지금 그대로 folder 에."""
    if server_log.write_server(text):
        return
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


def audit(folder, text):
    """감사 기록 한 줄 - 누가 계정·보안 설정·PC·명령을 바꾸었나 (사내 서버 ④ Task 1, ③-1). 사내 서버가 server_log 자리를
    정했으면 audit.log 로, 아니면 log 와 같다 (단독 그대로). 비밀번호·열쇠·토큰은 싣지 않는다. 예외를 내지 않는다."""
    if not server_log.write_audit(text):
        log(folder, text)


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


def allowed(role, method, parts, lic, pc_id=None):
    """이 열쇠가 이 자리에 이 일을 해도 되는가 (자리와 방법까지). 내용은 command_patch_ok·command_delete_ok·otp_request_ok 가 본다.
    pc_id: 서명으로 확인한 PC 번호 (사내 서버). None 이면 라이선스의 PC 번호 (단독)."""
    me = lic["pc_id"] if pc_id is None else pc_id
    kind, cid, pc, rest = classify(parts)
    if kind is None or cid != lic["cid"]:
        return False
    if kind == "live":
        return role == "agent" and pc == me
    if kind == "commands":
        if role != "agent" or pc != me:
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


OTP_REQ_ID = re.compile(r"[A-Za-z0-9_-]{8,64}")


def otp_request_ok(body, lic, phone=None, pc_id=None):
    """인증번호 요청의 모양 (규칙과 같은 뜻): 정해진 칸만, 이 PC 의 요청, req_id 는 [A-Za-z0-9_-] 8~64자, 사이트 이름 100자까지,
    발신번호는 숫자 글 → true 로 1~OTP_MAX_SENDERS 개. phone = 짝지은 휴대폰 (local_phone.Phones.get) - 없으면 False
    (짝짓지 않은 휴대폰으로는 요청을 못 연다). 그 휴대폰에 허용 발신번호가 있으면 요청의 발신번호가 모두 그 안이어야 한다
    (PC 가 은행 번호를 넣어 직원 휴대폰의 다른 인증번호를 받아 가지 못하게 - 일반 버전 규칙과 같다).
    pc_id: 서명으로 확인한 PC 번호 (사내 서버) - 요청의 pcId 가 같아야 한다. None 이면 라이선스의 PC 번호 (단독)."""
    if not isinstance(phone, dict):
        return False
    if not isinstance(body, dict) or set(body) - set(OTP_KEYS):
        return False
    if not (isinstance(body.get("req_id"), str) and OTP_REQ_ID.fullmatch(body["req_id"])):
        return False
    if not (isinstance(body.get("site"), str) and len(body["site"]) <= 100):
        return False
    if body.get("pcId") != (lic["pc_id"] if pc_id is None else pc_id):
        return False
    senders = body.get("senders")
    if not isinstance(senders, dict) or not 0 < len(senders) <= OTP_MAX_SENDERS:
        return False
    if not all(isinstance(k, str) and k.isdigit() and len(k) <= 20 and v is True for k, v in senders.items()):
        return False
    allow = phone.get("senders") or []
    return not allow or all(k in allow for k in senders)


def local_host(headers, port):
    """Host 머리글이 이 PC 주소·이 포트인가 - 다른 이름으로 이 PC 를 가리킨 요청(DNS 바꿔치기)을 거른다.
    에이전트 창구(Handler._role)와 웹 창구(local_web.Web.handle)가 같이 쓴다."""
    host = (headers.get("Host") or "").rsplit(":", 1)
    return host[0] in LOCAL_HOSTS and (len(host) == 1 or host[1] == str(port))


def host_ok(headers, server):
    """Host 머리글이 이 서버를 가리키는가. 사내망 포트(server.cfg 가 있음)는 그 포트 쪽 목록 - 웹은 cfg.web_hosts(),
    에이전트는 cfg.agent_hosts() - 에 있어야 한다 (소문자로 견준다, 사내 서버 ② Task 4). cfg 가 없으면 local_host 그대로."""
    cfg = getattr(server, "cfg", None)
    if cfg is None:
        return local_host(headers, server.server_port)
    hosts = cfg.agent_hosts() if server.side == "agent" else cfg.web_hosts()
    return (headers.get("Host") or "").strip().lower() in hosts


def _agent_path(path):
    """에이전트 창구의 주소인가 (/db·/fs·/fs-sum) - 여기는 늘 요청 서명을 본다 (웹 창구로 넘기지 않는다)."""
    return path in ("/db", "/fs", "/fs-sum") or path.startswith(("/db/", "/fs/"))


class LocalServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    # 윈도우에서 켜면 같은 포트에 두 번째 서버가 조용히 뜬다 (rpa_dashboard.DashboardServer 와 같다) - 윈도우는 False 그대로.
    # 리눅스의 SO_REUSEADDR 은 남은 TIME_WAIT 만 넘는다 (다른 프로세스가 듣는 포트는 여전히 거절) - 서비스를 다시 켤 때 1분 동안
    # 포트를 못 여는 일이 없게 켠다 (사내 서버 ④ Task 1, ②보-1)
    allow_reuse_address = os.name != "nt"
    # listen 대기열. 기본 5 는 연결이 몰리면(화면 새로 고침·에이전트·구독이 한꺼번에) 윈도우가 차서 거절된 연결을 0.5초 뒤 다시 붙인다.
    # 넉넉히 두어도 동시 처리 수는 MAX_CONN 이 막는다 (계획 ③ 남은 일)
    request_queue_size = 64
    deploy = SINGLE                  # make_server 가 정한다 (registry 가 있으면 LAN)
    registry = None
    side = "both"                    # 길 나누기 - 이 서버는 에이전트·웹 창구를 같이 연다 (사내망 lan_server.LanServer 는 "web"·"agent")
    cfg = None                       # 사내망 설정 lan_config.LanConfig - 이 서버(127.0.0.1)에는 없다
    nonce_swept = 0.0                # nonce 표를 마지막으로 정리한 시각 (fresh_nonce)
    # 사내 서버(리눅스): 자리 서명 비밀 값(seat.ensure_key)과 서버 라이선스 파일 원문({"body", "sig"}) - 서버 입구(server_main)가
    # 적는다. 있으면 PC 등록 응답에 자리 증명서와 라이선스를 싣는다 (사내 서버 ④ Task 2). 없으면(단독·①~③ 시험) 응답은 지금 그대로
    seat_secret = None
    license_doc = None

    def note_bad(self, ip):
        """서명 틀림 한 번 - 이 서버(127.0.0.1)는 세지 않는다. 사내망 포트(lan_server.LanServer)가 주소 거절로 잇는다."""

    def request_read(self, conn):
        """처리기가 요청을 다 읽었다 - 이 서버(127.0.0.1)는 요청 마감이 없다 (사내망 포트 lan_server.LanServer 가 타이머를 거둔다)."""

    def client_hold(self, handler):
        """보낸 사람마다 요청 세기 - 이 서버는 세지 않는다 → (True, None). 사내망 웹 포트(LanServer)가 프록시 뒤 사람마다 센다."""
        return True, None

    def client_free(self, key):
        """client_hold 로 센 것 돌려주기 - 이 서버는 할 일이 없다."""

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        socketserver.TCPServer.server_bind(self)     # HTTPServer.server_bind 의 getfqdn 은 망에 따라 수 초 멈춘다
        self.server_name, self.server_port = self.server_address[:2]

    def process_request(self, request, client_address):
        with self.conn_lock:
            if self.conns >= self.deploy.max_conn:   # 연결을 쌓아 두는 프로그램이 있어도 스레드가 끝없이 늘지 않게 (검토 4번)
                self.shutdown_request(request)
                return
            self.conns += 1
        try:
            super().process_request(request, client_address)
        except Exception:                            # 스레드를 못 띄웠다 - 센 연결을 돌려주고 닫는다 (② 검토 T3b, LanServer 와 같다)
            with self.conn_lock:
                self.conns -= 1
            self.shutdown_request(request)

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            with self.conn_lock:
                self.conns -= 1

    def fresh_nonce(self, nonce, now, keep=NONCE_KEEP_SEC):
        """이 nonce 를 처음 보는가 (같은 요청을 다시 보내기 막기). 지난 것은 지운다.
        keep: 기억하는 초 - 허용 시각 차이의 두 배보다 길어야 한다 (앞당겨 서명한 요청을 기억이 끝난 뒤 다시 보내지 못하게).
        지난 것 지우기는 NONCE_SWEEP_SEC 마다 한 번 (표가 커져도 요청마다 전체를 훑지 않는다, 검토 M-7)."""
        with self.conn_lock:
            if now - self.nonce_swept >= NONCE_SWEEP_SEC:
                self.nonce_swept = now
                for k in [k for k, t in self.nonces.items() if t < now]:
                    del self.nonces[k]
            if self.nonces.get(nonce, 0) >= now:
                return False
            self.nonces[nonce] = now + keep
            return True

    def pc_rate_ok(self, pc_id):
        """사내 서버: 이 PC 의 서명 요청 한 번을 센다 → 분당 PC_REQ_MIN 안이면 True (검토 M-7). 표 = PC → [창 시작, 센 수].
        PC 수는 등록부 자리 수로 막혀 있어 표가 커지지 않는다. 시계는 rate_clock (시험이 바꿔 끼운다)."""
        now = self.rate_clock()
        with self.conn_lock:
            win = self.pc_reqs.get(pc_id)
            if win is None or now - win[0] >= 60:
                win = self.pc_reqs[pc_id] = [now, 0]
            win[1] += 1
            return win[1] <= PC_REQ_MIN

    def enroll_reject_log(self, text):
        """PC 등록 거절 한 줄 - REJECT_LOG_SEC 창마다 REJECT_LOG_MAX 줄까지만 쓰고 나머지는 센다. 창이 넘어간 뒤 첫 거절 때
        생략한 수를 한 줄로 남긴다 (검토 2026-11-24 I-3). 창 = [시작, 이 창의 거절 수, 생략한 수], 시계는 log_clock."""
        now = self.log_clock()
        with self.conn_lock:
            win = self.reject_win
            skipped = 0
            if now - win[0] >= REJECT_LOG_SEC:
                skipped = win[2]
                win[:] = [now, 0, 0]
            win[1] += 1
            write = win[1] <= REJECT_LOG_MAX
            if not write:
                win[2] += 1
        if skipped:
            log(self.folder, f"PC 등록 거절 {skipped}건 더 (기록 생략)")
        if write:
            log(self.folder, text)

    def stream_slot(self, pc_id, on):
        """사내 서버 에이전트 구독 자리 잡기(on=True)·돌려주기(False). 잡기는 전체·PC 하나 상한 안일 때만 True."""
        d = self.deploy
        with self.conn_lock:
            if not on:
                n = self.streams.get(pc_id, 0) - 1
                if n > 0:
                    self.streams[pc_id] = n
                else:
                    self.streams.pop(pc_id, None)
                return True
            if sum(self.streams.values()) >= d.agent_streams or self.streams.get(pc_id, 0) >= d.per_pc_streams:
                return False
            self.streams[pc_id] = self.streams.get(pc_id, 0) + 1
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

    def send_error(self, code, message=None, explain=None):
        """http.server 가 직접 내는 오류 (모르는 방법 HEAD·OPTIONS 의 501, 틀린 요청 줄 400 등). 사내 서버 에이전트 포트에서는
        _reply 처럼 Date 없이 답한다 - 열쇠 없는 쪽에 서버 시각을 알려 주지 않는다 (②검-5, 검토 M-4 와 같은 뜻).
        단독(이 PC 의 127.0.0.1 서버)과 웹 포트는 http.server 그대로."""
        if getattr(self.server, "side", None) != "agent":
            return super().send_error(code, message, explain)
        self.close_connection = True
        self._auth = None
        try:
            phrase = http.HTTPStatus(code).phrase
        except ValueError:
            phrase = "Error"
        if self.command == "HEAD" or code < 200 or code in (204, 304):
            self._reply(code, empty=True)
        else:
            self._reply(code, {"error": phrase})

    # --- 응답 ---
    def _reply(self, status, value=None, empty=False):
        body = b"" if empty else json.dumps(value, ensure_ascii=False).encode("utf-8")
        if self._auth:
            self.send_response(status)               # 서명된 답에는 Date - local_store.Client._seen 이 서버 시각을 읽는다
        else:
            # 서명 없는 답(401·403·404 등)에는 서버 시각을 싣지 않는다 - 열쇠 없는 쪽에 시각을 알려 주지 않게 (검토 2026-11-24 M-4)
            self.send_response_only(status)
            self.send_header("Server", self.version_string())
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if self._auth:
            self.send_header(ap_sign.H_SIGN, ap_sign.response_mac(self._auth[0], self._auth[1], status, body))
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
    def client_ip(self):
        """보낸 쪽 주소를 읽는 한 곳 (사내 서버 ② Task 4). 사내망 포트(서버에 cfg)면 소켓 주소는 srv.peer_ip 로 읽고,
        웹 쪽만 믿을 프록시의 X-Forwarded-For 를 본다 (lan_server.client_ip - 프록시가 아닌 곳에서 온 머리글은 버린다).
        에이전트 쪽은 늘 소켓 주소 (프록시 뒤에 서지 않는다, 설계 6.3). cfg 가 없으면 소켓 주소."""
        srv = self.server
        cfg = getattr(srv, "cfg", None)
        if cfg is None:
            return str(self.client_address[0])
        peer = srv.peer_ip(self.client_address)
        if srv.side != "web":
            return peer
        return self.forwarded_ip() or peer

    def forwarded_ip(self):
        """웹 쪽 믿을 프록시가 X-Forwarded-For 로 넘긴 보낸 쪽 주소 (lan_server.forwarded_ip - 'IPv4:포트' 꼴은 포트를 뗀다).
        사내망 웹 포트가 아니거나, 소켓 주소가 믿을 프록시가 아니거나, 머리글이 없거나 읽을 수 없으면 None."""
        srv = self.server
        cfg = getattr(srv, "cfg", None)
        if cfg is None or srv.side != "web":
            return None
        import lan_server            # 지연 import - lan_server 가 이 파일을 불러온다 (단독은 여기 오지 않는다)
        xff = ", ".join(self.headers.get_all("X-Forwarded-For") or []) or None     # 여러 줄이면 차례대로 이어 읽는다
        return lan_server.forwarded_ip(srv.peer_ip(self.client_address), xff, cfg)

    def _role(self, method, digest):
        """Host 와 요청 서명을 보고 (역할 'agent'·'relay', 서명으로 확인한 PC 번호). 아니면 응답을 보내고 _Stop.
        단독(SINGLE): 지금 검사 그대로 (ap1), PC 번호는 라이선스의 것. PC 번호 머리글(X-AP-PC)이 있으면 401.
        사내 서버(LAN): _role_lan."""
        srv = self.server
        if not host_ok(self.headers, srv):
            self._reply(403, DENIED)                 # 다른 이름으로 이 서버를 가리킨 요청 (DNS 바꿔치기) - 서명 확인 전에
            raise _Stop()
        if srv.registry is not None:
            return self._role_lan(method, digest)
        role = self.headers.get(ap_sign.H_ROLE) or ""
        ts, nonce = self.headers.get(ap_sign.H_TIME) or "", self.headers.get(ap_sign.H_NONCE) or ""
        sign = self.headers.get(ap_sign.H_SIGN) or ""
        now = time.time()
        ok = (role in ap_sign.ROLES and ts.isdigit() and 16 <= len(nonce) <= 64 and abs(now * 1000 - int(ts)) <= SIGN_WINDOW_MS
              and self.headers.get(ap_sign.H_PC) is None)
        if ok:
            key = srv.keys[ap_sign.ROLES.index(role)]
            want = ap_sign.request_mac(key, role, method, self.path, ts, nonce, b"", digest=digest)
            # ASCII 가 아닌 서명 글은 compare_digest 가 TypeError 를 낸다 - 틀린 서명으로 본다 (검토 2026-11-24 M-5)
            ok = sign.isascii() and hmac.compare_digest(sign, want) and srv.fresh_nonce(nonce, now)
        if not ok:
            self._reply(401, {"error": "Unauthorized"})
            raise _Stop()
        self._auth = (key, nonce)
        return role, srv.lic["pc_id"]

    def _role_lan(self, method, digest):
        """사내 서버의 요청 서명 (ap2 - 서명 글에 PC 번호). 차례: PC 번호 머리글이 등록부에 있음 → 역할·시각 글자·nonce 길이 →
        그 PC 열쇠의 서명 - 여기까지 틀리면 서명 없는 401 (무엇이 틀렸는지·서버 시각을 알려 주지 않는다).
        서명이 맞은 뒤에만: 시각 차이가 크면 서명된 401 clock(서버 시각), 다시 보낸 nonce 는 401, 중지·지운 PC 는 서명된 403."""
        srv = self.server
        pc = self.headers.get(ap_sign.H_PC) or ""
        role = self.headers.get(ap_sign.H_ROLE) or ""
        ts, nonce = self.headers.get(ap_sign.H_TIME) or "", self.headers.get(ap_sign.H_NONCE) or ""
        sign = self.headers.get(ap_sign.H_SIGN) or ""
        keys = srv.registry.keys(pc) if pc_registry.PC_RE.fullmatch(pc) else None
        ok = keys is not None and role in ap_sign.ROLES and ts.isdigit() and len(ts) <= 16 and 16 <= len(nonce) <= 64
        if ok:
            key = keys[ap_sign.ROLES.index(role)]
            want = ap_sign.request_mac2(key, pc, role, method, self.path, ts, nonce, b"", digest=digest)
            ok = sign.isascii() and hmac.compare_digest(sign, want)     # ASCII 가 아니면 틀린 서명 (검토 2026-11-24 M-5)
        if not ok:
            srv.note_bad(self.client_ip())          # 사내망 포트: 60초에 20번이면 그 주소를 300초 거절 (lan_server) - 답보다 먼저 센다
            self._reply(401, {"error": "Unauthorized"})
            raise _Stop()
        now = time.time()
        window = srv.deploy.sign_window_ms
        if abs(now * 1000 - int(ts)) > window:
            self._auth = (key, nonce)                # 서명이 맞은 요청에만 서버 시각을 서명해 알려 준다 (한 번 다시 보내게)
            self._reply(401, {"error": "clock", "server_ms": int(now * 1000)})
            raise _Stop()
        if not srv.fresh_nonce(f"{pc}\n{nonce}", now, keep=max(NONCE_KEEP_SEC, 2 * window // 1000 + 30)):
            self._reply(401, {"error": "Unauthorized"})
            raise _Stop()
        self._auth = (key, nonce)
        state = srv.registry.state(pc)
        if state != "active":                        # 'disabled'·'removed' - 에이전트는 사람이 고쳐야 하는 멈춤으로 끝난다
            self._reply(403, {"error": "pc_removed" if state == "removed" else "pc_disabled"})
            raise _Stop()
        if not srv.pc_rate_ok(pc):                   # PC 하나의 분당 서명 요청 상한 (검토 M-7) - 서명된 429, 에이전트는 잠시 뒤 다시
            self._reply(429, {"error": "Too many requests"})
            raise _Stop()
        srv.registry.seen(pc)
        return role, pc

    def _enroll(self, raw):
        """POST /enroll (사내 서버만, 서명 머리글 없음 - 열쇠가 아직 없다). 본문 {"v": 1, pc, rand, guid, host, nonce, proof} →
        registry.enroll → 200 {"pc"} 를 새 agent 열쇠와 본문 nonce 로 서명 (PC 는 서명이 맞아야 열쇠를 저장한다).
        거절(EnrollError)은 서명 없는 403 {"error": code}, 꼴이 틀리면 400. 기록에 토큰·열쇠·증명을 싣지 않는다."""
        srv = self.server
        if srv.registry is None:
            return self._reply(404, {"error": "Not found"})
        if not host_ok(self.headers, srv):
            return self._reply(403, DENIED)
        body = self._json_body(raw)
        if not (isinstance(body, dict) and body.get("v") == 1 and not isinstance(body.get("v"), bool)
                and all(isinstance(body.get(k), str) for k in ENROLL_FIELDS) and ENROLL_NONCE.fullmatch(body["nonce"])):
            return self._reply(400, {"error": "Bad request"})
        pc = body["pc"]
        try:
            agent_key, _ = srv.registry.enroll(pc, body["rand"], body["guid"], body["host"], body["proof"])
        except pc_registry.EnrollError as e:
            if e.code == "bad_proof":
                srv.note_bad(self.client_ip())      # 틀린 증명은 틀린 서명과 같이 센다 (사내망 포트의 주소 거절로 이어진다)
            if pc_registry.PC_RE.fullmatch(pc):
                srv.enroll_reject_log(f"PC 등록 거절  번호={pc}  까닭={e.code}")
            return self._reply(403, {"error": e.code})
        log(srv.folder, f"PC 등록  번호={pc}  컴퓨터={body['host']}")
        reply = {"pc": pc}
        if srv.seat_secret is not None:              # 사내 서버 입구가 자리 열쇠를 단 서버 - 자리 증명서 (PC 쪽 확인은 ⑤)
            import seat                              # 지연 import - 단독은 여기 오지 않는다
            reply["seat"] = seat.issue(srv.seat_secret, (srv.lic or {}).get("cid"), pc, body["guid"], int(time.time() * 1000))
        if srv.license_doc is not None:              # PC 가 seat_pub 을 믿을 근거 - 공급사 서명이 붙은 라이선스 원문
            reply["server_license"] = srv.license_doc
        self._auth = (agent_key, body["nonce"])
        return self._reply(200, reply)

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
        except (ValueError, UnicodeDecodeError, RecursionError):        # 깊게 겹친 JSON 도 400 (500·기록 줄 없이, ②검-6)
            self._reply(400, {"error": "Bad request"})
            raise _Stop() from None

    # --- 길 ---
    def _route(self, method):
        held = None
        try:
            url = urllib.parse.urlsplit(self.path)
            query = dict(urllib.parse.parse_qsl(url.query))
            raw, digest = self._read()
            self.server.request_read(self.request)  # 사내망 포트: 요청을 다 읽었다 - 마감 타이머를 거둔다 (lan_server.REQUEST_DEADLINE)
            ok, held = self.server.client_hold(self)   # 사내망 웹 포트의 프록시 뒤: 보낸 사람마다 동시·분당 (lan_server)
            if not ok:
                return self._reply(429, {"code": "too-many-requests", "message": TOO_MANY_MSG})
            web = getattr(self.server, "web", None)
            side = self.server.side          # "both"(이 PC 의 127.0.0.1 서버) · "web"(사내망 8443) · "agent"(사내망 8444)
            if side == "agent" and not (_agent_path(url.path) or url.path == "/enroll"):
                return self._reply(404, {"error": "Not found"})     # 에이전트 포트에 /api·웹 파일 - 웹 창구를 부르지 않는다
            if side != "agent" and web is not None and not _agent_path(url.path) and (url.path.startswith("/api/") or method == "GET"):
                # 브라우저 창구 (/api/*·웹 파일) - 세션 토큰으로 확인하고 응답에 서명을 붙이지 않는다 (_auth 는 None 그대로).
                # Host 검사는 local_web 이 한다. 처리하지 않은 것(False)만 아래 서명 확인으로 간다
                if web.handle(self, method, url.path, query, raw):
                    return
            if side == "web":
                return self._reply(404, {"error": "Not found"})     # 웹 포트에 /db·/fs·/fs-sum·/enroll 과 그 밖 - 서명 확인으로 가지 않는다
            if url.path == "/enroll" and method == "POST":     # 사내 서버 PC 등록 - 서명 확인 앞에서 (아직 열쇠가 없다). 단독은 404
                return self._enroll(raw)
            role, pc = self._role(method, digest)
            if url.path.startswith("/db/") and url.path.endswith(".json"):
                return self._db(method, role, self._parts(url.path[4:-5]), query, raw, pc)
            if url.path.startswith("/fs/") and method in ("GET", "POST"):
                return self._fs(method, role, self._parts(url.path[4:]), query, raw, pc)
            if url.path == "/fs-sum" and method == "GET":
                return self._fs_sum(role, query, pc)
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
        finally:
            if held is not None:
                self.server.client_free(held)    # 처리 끝 (스트림 끝·예외 포함) - 센 것을 꼭 돌려준다

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
    def _db(self, method, role, parts, query, raw, me=None):
        """me: 서명으로 확인한 PC 번호 (_role) - 자리 검사는 이 번호로 한다 (단독은 라이선스의 PC 번호와 같다)."""
        srv, lic = self.server, self.server.lic
        if method not in ("GET", "PUT", "PATCH", "DELETE") or not allowed(role, method, parts, lic, me):
            return self._reply(403, DENIED)
        kind, cid, pc, rest = classify(parts)
        path = "/".join(parts)
        reg = srv.registry
        # 사내 서버의 현황 쓰기는 쓰는 순간(Store 잠금 안)에도 그 PC 가 active 인지 본다 - 서명 검사(_role_lan)를 통과한 뒤
        # 관리자가 지운·중지한 PC 의 쓰기가 지운 자리를 다시 만들지 못하게 (검토 M-3). 거절은 _role_lan 의 403 과 같은 꼴
        live_guard = (lambda get: reg.state(me) == "active") if reg is not None and kind == "live" else None
        if method == "GET":
            if kind == "policy":
                tree = {"modules": lic.get("modules") or {}, "features": lic.get("features") or {}, "limits": lic.get("limits") or {}}
                return self._reply(200, _lookup(tree, rest))
            phone = getattr(srv, "phone", None)
            if kind == "phones":                     # 짝지은 휴대폰 표 (서명 열쇠·지문은 빼고 일반 버전과 같은 꼴) - 없으면 null
                return self._reply(200, phone.phones.public() if phone is not None else None)
            if kind == "otp_codes":                  # 번호는 요청이 열려 있고 req_id 가 같고 그 요청을 연 PC 일 때만 (local_phone.Desk.read_code)
                pc_me = lic["pc_id"] if me is None else me
                return self._reply(200, phone.desk.read_code(rest[0], pc_me) if phone is not None else None)
            order_by, equal_to = _json_arg(query.get("orderBy")), _json_arg(query.get("equalTo"))
            if "text/event-stream" in (self.headers.get("Accept") or ""):
                return self._stream(path, order_by, equal_to, me)
            value = srv.store.get(path, order_by, equal_to)
            if kind == "otp_requests" and isinstance(value, dict):
                # 남의 요청은 누가·언제 열었는지만 (otp_relay.PhoneRelay._free 가 보는 두 칸). req_id·발신번호·사이트는 연 PC 만 본다
                # - req_id 를 알아 둔 PC 가 만료 뒤 같은 번호로 다시 열지 못하게 (검토 2026-11-24 I-1)
                pc_me = lic["pc_id"] if me is None else me
                if value.get("pcId") != pc_me:
                    value = {k: value[k] for k in ("pcId", "created_at") if k in value} or None
            if order_by is not None and isinstance(value, dict) and ("endAt" in query or "limitToFirst" in query):
                value = _range(value, order_by, _json_arg(query.get("endAt")), query.get("limitToFirst"))
            return self._reply(200, value)
        try:
            if method == "DELETE":
                guard = (lambda get: command_delete_ok(get, path)) if kind == "commands" else None
                phone = getattr(srv, "phone", None)
                if kind in ("otp_requests", "otp_codes") and phone is not None:     # 다른 PC 의 살아 있는 요청·번호는 못 지운다 (Task 5)
                    pc_me = lic["pc_id"] if me is None else me
                    guard = lambda get: phone.desk.close_ok(get, rest[0], pc_me)    # noqa: E731
                srv.store.delete(path, guard=guard)
                return self._reply(200, None)
            body = _server_values(self._json_body(raw), int(time.time() * 1000))
            if kind == "commands":                   # PATCH 만 여기 온다 (allowed) - 확인과 쓰기를 한 잠금 안에서
                if not isinstance(body, dict):
                    return self._reply(403, DENIED)
                srv.store.patch(path, body, guard=lambda get: command_patch_ok(get, parts[:5], rest, body))
            elif kind == "otp_requests":             # PUT 만 여기 온다 - 짝지은 휴대폰에만 (계획 ④)
                phone = getattr(srv, "phone", None)
                if not otp_request_ok(body, lic, phone.phones.get(rest[0]) if phone is not None else None, me):
                    return self._reply(403, DENIED)
                # 휴대폰마다 요청 하나 (Task 5) - 다른 PC 의 살아 있는 요청이 있으면 일반 버전 규칙 거절과 같은 403 (otp_relay 가 기다렸다 다시 연다)
                if not phone.desk.open(rest[0], body, lic["pc_id"] if me is None else me):
                    return self._reply(403, DENIED)
            elif method == "PATCH":
                if not isinstance(body, dict):
                    return self._reply(400, {"error": "Bad request"})
                srv.store.patch(path, body, guard=live_guard)
            else:
                srv.store.put(path, body, guard=live_guard)
        except Refused:
            if live_guard is not None:
                return self._reply(403, {"error": "pc_removed" if reg.state(me) == "removed" else "pc_disabled"})
            return self._reply(403, DENIED)
        if query.get("print") == "silent":
            return self._reply(204, empty=True)
        return self._reply(200, body)

    def _stream(self, path, order_by, equal_to, me=None):
        """구독 (SSE). 사내 서버: 에이전트 구독을 전체·PC 하나 상한으로 세고 (넘으면 서명된 503), 고리가 1초마다 그 PC 가
        아직 active 인지 본다 - 중지·지운 PC 가 열어 둔 구독은 곧 끝난다 (다시 붙으면 서명된 403 을 받는다)."""
        srv = self.server
        lan = srv.registry is not None
        if lan and not srv.stream_slot(me, True):
            return self._reply(503, {"error": "Too many streams"})
        try:
            self._stream_loop(path, order_by, equal_to, me if lan else None)
        finally:
            if lan:
                srv.stream_slot(me, False)

    def _stream_loop(self, path, order_by, equal_to, lan_pc):
        srv = self.server
        key, nonce = self._auth
        q = srv.store.subscribe(path, order_by, equal_to)
        checked = time.monotonic()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header(ap_sign.H_SIGN, ap_sign.response_mac(key, nonce, 200, b""))
            self.end_headers()
            quiet, seq = time.monotonic(), 0
            while not srv.stopping.is_set():
                if lan_pc is not None and time.monotonic() - checked >= STATE_CHECK_SEC:
                    if srv.registry.state(lan_pc) != "active":
                        break
                    checked = time.monotonic()
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
                mac = ap_sign.event_mac(key, nonce, seq, event, text)
                self.wfile.write(f"event: {event}\ndata: {text}\nmac: {mac}\n\n".encode("utf-8"))
                self.wfile.flush()
                quiet = time.monotonic()
        finally:
            srv.store.unsubscribe(q)

    # --- 실행 기록 (Firestore 꼴) ---
    def _fs(self, method, role, parts, query, raw, me=None):
        """사내 서버는 문서의 pcId 가 서명으로 확인한 PC 번호(me)와 같아야 올리고, 문서 키에 PC 번호를 넣는다 (Runs._key, 검토 M-6) -
        같은 id 를 다른 PC 가 먼저 차지하지 못하고, 남의 문서는 없는 것과 같다 (404 - 있는지조차 알려 주지 않는다)."""
        srv, lic = self.server, self.server.lic
        lan = srv.registry is not None
        owner = me if lan else None
        ok = role == "agent" and parts[:2] == ["runs", lic["cid"]] and parts[2:3] == ["items"]
        if method == "POST":
            if not ok or len(parts) != 3:
                return self._reply(403, DENIED)
            doc, doc_id = self._json_body(raw), query.get("id") or ""
            if not isinstance(doc, dict) or not 0 < len(doc_id) <= 200:
                return self._reply(400, {"error": "Bad request"})
            if lan and doc.get("pcId") != me:
                return self._reply(403, DENIED)
            if not srv.runs.create("/".join(parts[:2]), parts[2], doc_id, doc, pc_id=owner):
                return self._reply(409, {"error": "Already exists"})
            return self._reply(200, {"id": doc_id})
        if not ok or len(parts) != 4:
            return self._reply(403, DENIED)
        doc = srv.runs.get("/".join(parts), pc_id=owner)
        if doc is not None and lan and doc.get("pcId") != me:
            doc = None                               # 키로 이미 갈렸다 - 그래도 남의 pcId 면 없는 것으로
        return self._reply(200, doc) if doc is not None else self._reply(404, {"error": "Not found"})

    def _fs_sum(self, role, query, me=None):
        """합 읽기. 사내 서버는 서명으로 확인한 PC(me)의 문서만 더한다 (검토 2026-11-24 I-2). 단독은 지금 그대로 업체 전체."""
        lic = self.server.lic
        if role != "agent" or query.get("parent") != f"runs/{lic['cid']}" or query.get("collection") != "items" or not query.get("field"):
            return self._reply(403, DENIED)
        mine = me if self.server.registry is not None else None
        return self._reply(200, {"sum": self.server.runs.sum(query["parent"], "items", query["field"], query.get("since") or None,
                                                             pc_id=mine)})


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


def _prepare(srv, store, runs, lic, keys, registry, folder=None, web=None, phone=None):
    """만든(묶기 전) 서버에 저장소·라이선스·열쇠·배치·잠금·표를 단다 - make_server 와 사내망 lan_server.make_lan_servers 가
    같이 쓴다 (사내 서버 ② Task 4). registry 가 있으면 사내 서버 배치(LAN, keys 는 쓰지 않는다), 없으면 단독(SINGLE)."""
    srv.store, srv.runs, srv.lic = store, runs, lic
    srv.keys = tuple(keys) if keys is not None else ()
    srv.deploy, srv.registry = (LAN, registry) if registry is not None else (SINGLE, None)
    srv.web = web
    srv.phone = phone
    srv.folder = folder or os.path.dirname(store.path or "") or "."
    srv.stopping = threading.Event()
    srv.conn_lock, srv.conns, srv.nonces, srv.streams = threading.Lock(), 0, {}, {}
    srv.nonce_swept, srv.pc_reqs, srv.rate_clock = 0.0, {}, time.monotonic
    srv.log_clock, srv.reject_win = time.monotonic, [float("-inf"), 0, 0]


def check_web(web, registry):
    """웹 창구의 등록부가 서버에 넘긴 등록부와 같은 것인가 (검토 M-11) - 다르면 화면이 보는 PC 와 서명을 확인하는 PC 가 갈린다.
    make_server·lan_server.make_lan_servers 가 포트를 열기 전에 부른다. 다르면 ValueError."""
    if web is not None and getattr(web, "registry", None) is not registry:
        raise ValueError("웹 창구의 PC 등록부가 서버의 등록부와 다릅니다.")


def make_server(store, runs, lic, keys, host="127.0.0.1", port=PORT, folder=None, web=None, phone=None, registry=None):
    """로컬 서버를 만든다 (serve_forever 는 부르는 쪽이). 이 PC 주소에만 묶는다 - 포트가 쓰이는 중이면 OSError.
    web: 브라우저 창구 (local_web.Web). 없으면 에이전트 창구만 연다 (/api·웹 파일은 서명 없는 요청으로 거절된다).
    phone: 휴대폰 창구 (local_phone.Service) - 짝지은 휴대폰 표·인증번호 자리 규칙. 없으면 인증번호 요청을 열지 못한다.
    사내망 휴대폰 포트는 이 서버와 따로 선다 (local_phone.Gate - 이 서버는 늘 127.0.0.1).
    registry: PC 등록부 (pc_registry.Registry) - 있으면 사내 서버 배치(LAN): PC 마다의 열쇠로 ap2 서명을 확인하고 keys 는 쓰지
    않는다 (None 이어도 된다). 없으면 단독(SINGLE) - 열쇠 둘(keys)이 꼭 있어야 한다 (없으면 ValueError, 검토 M-10).
    web 의 등록부는 registry 와 같은 것이어야 한다 (check_web)."""
    if host not in LOCAL_HOSTS:
        raise ValueError("로컬 서버는 이 PC(127.0.0.1)에만 엽니다.")
    if registry is None and keys is None:
        raise ValueError("단독 서버는 에이전트·중계 열쇠가 있어야 엽니다.")
    check_web(web, registry)
    srv = LocalServer(("127.0.0.1", port), Handler, bind_and_activate=False)
    _prepare(srv, store, runs, lic, keys, registry, folder=folder, web=web, phone=phone)
    try:
        srv.server_bind()
        srv.server_activate()
    except BaseException:
        srv.server_close()
        raise
    if web is not None:
        web.public_url = f"http://127.0.0.1:{srv.server_address[1]}"     # 등록 글에 싣는 서버 주소 (② 에서 사내 주소로)
        web.server = srv                             # 웹 구독 상한은 이 서버의 배치를 따른다 (Web.max_streams, 검토 M-11)
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
    import local_phone
    web = local_web.Web(store, runs, lic, folder, local_web.web_dir())
    if not os.path.isdir(web.web_dir):
        log(folder, f"웹 파일 폴더가 없습니다 - 화면을 내주지 못합니다. ({web.web_dir})")
    phone = local_phone.Service(folder, store, lic)          # 휴대폰 창구 - 짝지은 휴대폰이 있거나 짝짓기 중일 때만 사내망 포트를 연다
    web.phone = phone
    try:
        srv = make_server(store, runs, lic, keys, port=port, folder=folder, web=web, phone=phone)
    except OSError as e:
        log(folder, f"로컬 서버를 열지 못했습니다 - 포트 {port} 을(를) 다른 프로그램이 쓰고 있습니다. ({type(e).__name__})")
        return 3
    log(folder, f"로컬 서버 시작  업체={lic['cid']}  포트={port}")
    phone.start()                                            # 첫 고리에서 휴대폰 포트를 맞춘다 (Gate.sync - 서버 시작을 붙잡지 않게 고리 스레드에서)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        phone.stop()                                         # 휴대폰 포트를 닫는다 (휴대폰이 0대면 방화벽 규칙도)
        srv.server_close()
        runs.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
