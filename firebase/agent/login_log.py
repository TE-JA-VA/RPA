# -*- coding: utf-8 -*-
"""사내 서버 웹의 로그인 이력 - <자료 폴더>/logins.db (설계 2026-11-24 6.6 '로그인 이력', 계획 ③ Task 5).

표 logins(id INTEGER PRIMARY KEY, at INTEGER, uid TEXT, ip TEXT, agent TEXT, result TEXT) + at·uid 색인.
    at     = 시각 (ms)
    uid    = 등록된 아이디, 등록되지 않은 아이디는 None (아이디 칸에 비밀번호를 잘못 친 글이 남지 않게 - 적는 쪽이 거른다)
    ip     = 보낸 쪽 주소 (프록시 뒤면 X-Forwarded-For 에서 읽은 주소)
    agent  = 브라우저 종류만 (browser_kind - 'Edge · Windows' 같은 40자 안의 글). User-Agent 원문은 남기지 않는다
    result = RESULTS 가운데 하나
비밀번호·2단계 번호·복구 번호·세션 토큰·로그인 표는 어느 칸에도 싣지 않는다 (받지도 않는다).
웹에서 지우는 길은 없다. 보관 기간(KEEP_DAYS)이 지난 줄은 add 가 하루 한 번 purge 로 지운다 (설계 12절 7).
사내 서버(local_web.Web 에 registry 가 있을 때)만 쓴다 - 단독은 이 파일을 만들지 않는다. 표준 라이브러리만 쓴다.
"""
import os
import sqlite3
import threading
import time

LOGINS_NAME = "logins.db"
KEEP_DAYS = 365
RESULTS = ("ok", "bad_password", "bad_code", "locked", "disabled", "logout", "timeout",
           "mfa_on", "mfa_off", "mfa_reset", "recovery")
SUCCESS = ("ok", "recovery")                  # 로그인이 된 줄 - '마지막 로그인' 은 이 둘에서 찾는다 (복구 번호 로그인도 로그인이다)
AGENT_MAX = 40
FIELD_MAX = 64                                # uid·ip 칸 길이 (아이디는 32자, 주소는 IPv6 도 들어간다)
LIMIT_DEFAULT, LIMIT_MAX = 50, 200
PURGE_EVERY = 86400                           # add 가 purge 를 부르는 간격 (초)
_UA_SCAN = 1024                               # 브라우저 종류를 볼 때 User-Agent 앞쪽만 본다
_COLS = ("id", "at", "uid", "ip", "agent", "result")


def browser_kind(ua):
    """User-Agent → '브라우저 · 운영체제' (예: 'Edge · Windows'). 모르면 '기타' (운영체제를 모르면 브라우저 이름만).
    정해진 낱말만 돌려준다 - 원문 조각은 나가지 않는다. 늘 AGENT_MAX(40)자 안."""
    s = ua[:_UA_SCAN].lower() if isinstance(ua, str) else ""
    if "edg/" in s or "edge/" in s or "edga/" in s or "edgios/" in s:
        name = "Edge"
    elif "firefox/" in s or "fxios/" in s:
        name = "Firefox"
    elif "chrome/" in s or "crios/" in s or "chromium/" in s:
        name = "Chrome"
    elif "safari/" in s and "version/" in s:
        name = "Safari"
    else:
        name = "기타"
    if "windows" in s:
        osname = "Windows"
    elif "iphone" in s or "ipad" in s or "ipod" in s:        # iOS 의 User-Agent 에는 'like Mac OS X' 가 들어 있다 - macOS 보다 먼저
        osname = "iOS"
    elif "android" in s:                                      # 안드로이드에는 'Linux' 가 들어 있다 - 리눅스보다 먼저
        osname = "Android"
    elif "macintosh" in s or "mac os x" in s:
        osname = "macOS"
    elif "linux" in s or "x11" in s:
        osname = "Linux"
    else:
        osname = ""
    if name == "기타" and not osname:
        return "기타"
    return (f"{name} · {osname}" if osname else name)[:AGENT_MAX]


def _text(value, limit):
    return None if value is None else str(value)[:limit]


class LoginLog:
    """logins.db 한 개. HTTP 서버가 스레드마다 부르므로 연결 하나를 잠금으로 감싼다 (local_server.Runs 와 같은 꼴).
    clock = 초 단위 시계 (시험이 손 시계를 넘긴다). path 가 ':memory:' 면 파일 없이."""

    def __init__(self, path, clock=time.time):
        """열기(연결·표 만들기)에 실패하면 그 파일(보통 파일일 때만)을 logins.db.broken 으로 치우고(있으면 덮어씀) 한 번 더 새로 연다
        (전체 검토 1 - 깨진 이력 때문에 웹이 켜지지 않으면 안 된다). moved_broken = 치웠나. 그래도 실패하면 예외 (부르는 쪽이 이력 없이 켠다)."""
        self._clock = clock
        self._lock = threading.Lock()
        self._purged = None                    # 마지막 purge 시각 (초) - add 가 하루 한 번 부른다
        self.moved_broken = False
        if path != ":memory:":
            path = os.path.abspath(path)
            os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            self._db = self._open(path)
        except (sqlite3.Error, OSError):
            if path == ":memory:" or not os.path.isfile(path):
                raise                          # 폴더 같은 것은 건드리지 않는다
            self._aside(path)
            self.moved_broken = True
            self._db = self._open(path)

    @staticmethod
    def _open(path):
        fresh = path != ":memory:" and not os.path.exists(path)
        db = sqlite3.connect(path, check_same_thread=False, timeout=10)
        try:
            if fresh and os.name == "posix":   # 서비스 계정만 읽게 (설계 4절 - 자료 폴더의 파일은 600)
                try:
                    os.chmod(path, 0o600)
                except OSError:
                    pass
            with db:
                db.execute("CREATE TABLE IF NOT EXISTS logins(id INTEGER PRIMARY KEY, at INTEGER, uid TEXT, ip TEXT, agent TEXT,"
                           " result TEXT)")
                db.execute("CREATE INDEX IF NOT EXISTS logins_at ON logins(at)")
                db.execute("CREATE INDEX IF NOT EXISTS logins_uid ON logins(uid, id)")
        except BaseException:
            db.close()                         # 윈도우는 열린 파일을 옮기지 못한다
            raise
        return db

    @staticmethod
    def _aside(path):
        """깨진 파일과 곁 파일(-journal·-wal·-shm)을 .broken 이름으로 옮긴다 - 옛 곁 파일이 새 파일에 덮어 쓰이지 않게."""
        for tail in ("", "-journal", "-wal", "-shm"):
            if os.path.isfile(path + tail):
                os.replace(path + tail, path + ".broken" + tail)

    def close(self):
        with self._lock:
            self._db.close()

    def add(self, result, uid, ip, agent, at_ms=None):
        """한 줄 넣기. result 는 RESULTS 안만, uid 는 등록된 아이디 글 또는 None - 아니면 ValueError.
        at_ms = 그 일이 있었던 시각(ms) - 없으면 지금 (자동 로그아웃은 세션이 실제로 끝난 시각을 넘긴다, 전체 검토 3).
        넣은 뒤 마지막 purge 에서 하루가 지났으면 purge 를 부른다."""
        if result not in RESULTS:
            raise ValueError(f"로그인 이력 결과가 올바르지 않습니다: {result!r}")
        if uid is not None and not isinstance(uid, str):
            raise ValueError("로그인 이력 아이디는 글이어야 합니다.")
        now = self._clock()
        at = int(now * 1000) if at_ms is None else int(at_ms)
        with self._lock, self._db:
            self._db.execute("INSERT INTO logins(at, uid, ip, agent, result) VALUES(?,?,?,?,?)",
                             (at, _text(uid, FIELD_MAX), _text(ip, FIELD_MAX), _text(agent, AGENT_MAX), result))
        if self._purged is None or now - self._purged >= PURGE_EVERY:
            self._purged = now
            self.purge()

    @staticmethod
    def _row(row):
        return dict(zip(_COLS, row))

    def query(self, uid=None, since_ms=None, until_ms=None, result=None, limit=LIMIT_DEFAULT, before_id=None):
        """최신 먼저 (id 가 큰 것부터). since_ms 이상·until_ms 미만, before_id 보다 작은 id (다음 쪽). limit 은 1~200 으로 맞춘다.
        → [{id, at, uid, ip, agent, result}, …]"""
        sql, args = "SELECT id, at, uid, ip, agent, result FROM logins WHERE 1=1", []
        for cond, value in (("uid = ?", uid), ("at >= ?", since_ms), ("at < ?", until_ms), ("result = ?", result),
                            ("id < ?", before_id)):
            if value is not None:
                sql += " AND " + cond
                args.append(value)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(min(LIMIT_MAX, max(1, int(limit))))
        with self._lock:
            return [self._row(r) for r in self._db.execute(sql, args).fetchall()]

    def last_ok(self, uid, before_id=None):
        """그 아이디의 마지막 로그인 줄 (ok·recovery) - before_id 를 주면 그보다 앞의 것. 없으면 None."""
        sql = ("SELECT id, at, uid, ip, agent, result FROM logins WHERE uid = ? AND result IN ("
               + ",".join("?" * len(SUCCESS)) + ")")
        args = [uid, *SUCCESS]
        if before_id is not None:
            sql += " AND id < ?"
            args.append(before_id)
        with self._lock:
            row = self._db.execute(sql + " ORDER BY id DESC LIMIT 1", args).fetchone()
        return self._row(row) if row else None

    def failed_count(self, uid, after_id=None):
        """그 아이디의 틀린 비밀번호·번호 줄(bad_password·bad_code) 수 - after_id 를 주면 그보다 뒤의 것만 (로그인 응답 failedSince)."""
        sql = "SELECT COUNT(*) FROM logins WHERE uid = ? AND result IN (?, ?)"
        args = [uid, "bad_password", "bad_code"]
        if after_id is not None:
            sql += " AND id > ?"
            args.append(after_id)
        with self._lock:
            return self._db.execute(sql, args).fetchone()[0]

    def purge(self):
        """보관 기간(KEEP_DAYS)이 지난 줄을 지운다 → 지운 수."""
        cut = int((self._clock() - KEEP_DAYS * 86400) * 1000)
        with self._lock, self._db:
            return self._db.execute("DELETE FROM logins WHERE at < ?", (cut,)).rowcount
