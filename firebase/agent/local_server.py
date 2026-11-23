# -*- coding: utf-8 -*-
"""스탠드얼론 로컬 서버 - 에이전트가 Firebase 에 쓰던 자리를 이 PC 안에서 받는다 (127.0.0.1:8781).
이 파일의 저장소 부분: Store(RTDB 자리 흉내 - JSON 나무·구독)와 Runs(Firestore 실행 기록 흉내 - SQLite).
둘 다 HTTP 를 모른다 - 창구(서버·인증·검사)는 이 파일 뒤쪽에 따로 붙는다.
표준 라이브러리만 쓴다.
"""
import copy
import json
import os
import queue
import sqlite3
import tempfile
import threading
import time

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

    def __init__(self, path):
        self.path = os.path.abspath(path)
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
