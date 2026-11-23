# -*- coding: utf-8 -*-
"""스탠드얼론 로컬 서버의 웹 창구 - 이 PC 의 브라우저가 쓰는 쪽 (설계 2026-11-23-standalone 6.2·6.3·6.5, 계획 ② Task 2).

local_server.Handler 가 서명 확인 **앞에서** `/api/*` 와 웹 파일 GET 을 여기로 넘긴다. 에이전트 창구(`/db`·`/fs`)와는 인증이 다르다:
    에이전트 = 열쇠로 한 요청 서명,  브라우저 = 로그인해서 받은 세션 토큰 (`Authorization: Bearer`).
둘은 서로의 창구에서 통하지 않는다. 이 파일의 응답에는 서명을 붙이지 않는다 (브라우저는 확인할 수 없다).

- 계정(Accounts): `<자료 폴더>/accounts.json`. 비밀번호는 pbkdf2_hmac(sha256, 310000) + 계정마다 소금 16바이트. 기본 계정은 없다.
- 세션(Sessions): 메모리에만 - 서버를 다시 켜면 모두 풀린다. 탭 단위 (쿠키를 쓰지 않는다 → 다른 사이트의 요청에 로그인이 따라가지 않는다).
- 잠금(Lockout): 아이디마다 연속 5번 틀리면 60초.
- 웹 파일: firebase/web 을 그대로 내주되 스탠드얼론에 없어야 할 것(Firebase 설정·SDK 를 부르는 파일)은 내주지 않는다.
비밀번호·세션 토큰·열쇠는 기록에 싣지 않고, 어느 응답에도 열쇠·라이선스 서명·해시·소금을 싣지 않는다.
표준 라이브러리만 쓴다.
"""
import hashlib
import hmac
import json
import os
import queue
import re
import secrets
import socket
import tempfile
import threading
import time
import urllib.parse

import local_server      # log·local_host·KEEPALIVE_SEC·Refused (local_server 는 main() 안에서만 이 파일을 불러온다)

APP = "rpa"
ROLES = ("admin", "viewer")                # 관리자 / 유저(보기만)
ID_RE = re.compile(r"[a-z0-9_.-]{2,32}")   # 아이디 - 소문자로 바꿔 견준다 (fullmatch 로만 쓴다: $ 는 끝의 줄바꿈을 지나친다)
PBKDF2_ITER = 310000
SALT_BYTES = 16
PASSWORD_MIN = 8
ACCOUNTS_NAME = "accounts.json"
ACCOUNTS_MAX = 50
IDLE_SEC = 1800                            # 미사용 30분
MAX_SEC = 43200                            # 로그인 뒤 12시간
LOCK_LIMIT, LOCK_SEC = 5, 60
LOCK_TRACK_MAX = 1000                      # 잠금 표에 기억하는 아이디 수 (없는 아이디를 끝없이 넣어도 메모리가 늘지 않게)
SESSIONS_MAX = 200
QUICK_TTL = 90                             # 실행·중단 명령의 만료 (초) - 지금 RTDB 규칙과 같다
COMMAND_TTL = 600
QUICK_TYPES = ("launch", "stop_erpia", "stop_rpa")
# 웹이 보낼 수 있는 명령 - 프리셋 옮기기 셋·update·rollback 은 스탠드얼론에 없다
WEB_TYPES = ("launch", "stop_erpia", "stop_rpa", "set_modules", "set_schedule", "set_presets", "set_parallel", "set_together", "resume_repeat")
ARGS_DEPTH_MAX = 20
API_BODY_MAX = 64 * 1024
FILE_MAX = 16 * 1024 * 1024
MAX_STREAMS = 16                           # 열어 둘 수 있는 웹 스트림 수 - 서버 연결 상한(local_server.MAX_CONN) 안에서 에이전트 몫을 남긴다
CSP = ("default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'; "
       "base-uri 'none'; form-action 'self'")
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".png": "image/png", ".webp": "image/webp", ".svg": "image/svg+xml", ".ico": "image/x-icon", ".woff2": "font/woff2",
         ".json": "application/json; charset=utf-8"}
EDITION_JS = b'export const EDITION = "standalone";\n'


def edition_js():
    """화면의 edition.js - 늘 스탠드얼론. 시험용 빌드(edition.test_build)면 TEST_BUILD = true (업체 웹 맨 위 띠 '시험용 빌드 - 고객 배포 금지')."""
    try:
        import edition
        test = edition.test_build()
    except Exception:
        test = False
    return EDITION_JS + f"export const TEST_BUILD = {'true' if test else 'false'};\n".encode("ascii")
HIDDEN_FILES = ("firebase-config.js", "data-firebase.js")     # 스탠드얼론 서버는 내주지 않는다 (Firebase 프로젝트 설정·SDK 주소)
STRIP_HTML = b"google-site-verification"                       # 이 글이 든 줄은 빼고 낸다 (일반 버전 사이트의 소유 확인 태그)
SEG_RE = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9_.-]*")           # 웹 파일 주소 조각 (점으로 시작하지 않는다)
DEVICES = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} | {f"{n}{i}" for n in ("COM", "LPT") for i in range(10)}
KEY_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")                    # 명령 키
TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{32,128}")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_DUMMY_SALT = secrets.token_bytes(SALT_BYTES)                  # 없는 아이디도 같은 계산을 하게 (걸리는 시간으로 아이디가 있는지 알 수 없게)
_DUMMY_HASH = secrets.token_bytes(32)


def web_dir():
    """웹 파일 폴더: 설치본은 프로그램 폴더\\firebase\\web, 없으면 소스의 firebase/web."""
    import rpa_status          # 지연 import (local_server.data_dir 와 같은 까닭)
    path = os.path.join(rpa_status.program_dir(), "firebase", "web")
    if os.path.isdir(path):
        return path
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "web"))


# ----------------------------------------------------------------------------------------------------
# 계정
# ----------------------------------------------------------------------------------------------------

class WeakPassword(ValueError):
    """새 비밀번호가 규칙에 맞지 않는다 (auth/weak-password)."""


class WrongPassword(ValueError):
    """현재 비밀번호가 틀렸다 (auth/wrong-password)."""


class NoAccount(ValueError):
    """그 아이디의 계정이 없다."""


def norm_id(raw):
    """아이디를 견주는 꼴로 (앞뒤 빈칸 없이 소문자). 글이 아니면 빈 글."""
    return raw.strip().lower() if isinstance(raw, str) else ""


def _hash(password, salt, rounds=PBKDF2_ITER):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)


def _check_password(password):
    if not isinstance(password, str) or len(password) < PASSWORD_MIN:
        raise WeakPassword(f"비밀번호는 {PASSWORD_MIN}자 이상으로 입력하여 주십시오.")


class Accounts:
    """웹 계정 파일 accounts.json = {"version": 1, "accounts": {<아이디>: {role, salt, hash, iterations, disabled, must_change}}}.
    쓸 때마다 임시 파일 → os.replace (반쯤 쓰인 파일이 남지 않는다). 파일이 없으면 계정이 없는 것 - 기본 계정을 만들지 않는다.
    설치 마법사·설정 창(다른 프로세스)도 같은 파일을 이 클래스로 고친다 - 그래서 파일이 바뀌었으면 다시 읽는다.
    밖으로 주는 계정 dict 는 {id, role, disabled, must_change} 뿐이다 (해시·소금은 나가지 않는다)."""

    def __init__(self, path):
        self.path = os.path.abspath(path)
        self._lock = threading.RLock()
        self._stamp, self._data = None, {}

    # --- 파일 ---
    def _load(self):
        """{아이디: 기록}. 파일이 그대로면 읽어 둔 것을 쓴다. 잠깐 못 읽는 것은 몇 번 다시 - 끝내 못 읽으면 OSError
        (못 읽었다고 '계정 없음' 으로 보고 덮어쓰면 다른 계정이 사라진다)."""
        for attempt in range(5):
            try:
                st = os.stat(self.path)
                stamp = (st.st_mtime_ns, st.st_size, st.st_ino)
                if stamp == self._stamp:
                    return self._data
                with open(self.path, encoding="utf-8") as f:
                    text = f.read()
                break
            except FileNotFoundError:
                self._stamp, self._data = None, {}
                return self._data
            except UnicodeDecodeError:
                text, stamp = "", None
                break
            except OSError:
                if attempt == 4:
                    raise
                time.sleep(0.05 * (attempt + 1))
        try:
            raw = json.loads(text)
            rows = raw.get("accounts") if isinstance(raw, dict) else None
            if not isinstance(rows, dict):
                raise ValueError("계정 파일 꼴이 아님")
        except ValueError:
            try:                                     # 깨진 파일은 옆으로 치우고 계정 없음으로 (서버가 죽지 않게 - Store 와 같다)
                os.replace(self.path, self.path + ".broken")
            except OSError:
                pass
            self._stamp, self._data = None, {}
            return self._data
        data = {}
        for uid, rec in rows.items():
            if (isinstance(uid, str) and ID_RE.fullmatch(uid) and isinstance(rec, dict) and rec.get("role") in ROLES
                    and isinstance(rec.get("salt"), str) and isinstance(rec.get("hash"), str)):
                data[uid] = rec
        self._stamp, self._data = stamp, data
        return data

    def _save(self, data):
        folder = os.path.dirname(self.path)
        os.makedirs(folder, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=folder, prefix=os.path.basename(self.path) + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"version": 1, "accounts": data}, f, ensure_ascii=False, indent=1)
                f.flush()
                os.fsync(f.fileno())
            for attempt in range(6):                  # 읽는 쪽·바이러스 검사가 잠깐 잡고 있으면 바꿔치기가 거절된다
                try:
                    os.replace(tmp, self.path)
                    break
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
        self._stamp = None                            # 다음에 다시 읽는다 (파일에 적힌 것이 기준)

    # --- 안에서 쓰는 것 ---
    @staticmethod
    def _id(raw):
        uid = norm_id(raw)
        if not ID_RE.fullmatch(uid):
            raise ValueError("아이디는 영문 소문자·숫자·점(.)·밑줄(_)·빼기(-) 2~32자로 입력하여 주십시오.")
        return uid

    @staticmethod
    def _public(uid, rec, rev=False):
        out = {"id": uid, "role": rec["role"], "disabled": bool(rec.get("disabled")), "must_change": bool(rec.get("must_change"))}
        if rev:        # 비밀번호 기록이 바뀌면 달라지는 표시 - 세션이 '로그인한 뒤 비밀번호가 바뀌었나' 를 본다. 밖으로 내보내지 않는다
            out["rev"] = hashlib.sha256(f"{rec['salt']}:{rec['hash']}".encode("utf-8")).hexdigest()[:16]
        return out

    @staticmethod
    def _record(password, role, disabled, must_change):
        salt = secrets.token_bytes(SALT_BYTES)
        return {"role": role, "salt": salt.hex(), "hash": _hash(password, salt).hex(), "iterations": PBKDF2_ITER,
                "disabled": bool(disabled), "must_change": bool(must_change)}

    @staticmethod
    def _other_admin(data, uid):
        """uid 말고 쓸 수 있는(중지되지 않은) 관리자가 있나."""
        return any(k != uid and r["role"] == "admin" and not r.get("disabled") for k, r in data.items())

    def _put(self, raw_id, password, role, must_change, new):
        uid = self._id(raw_id)
        _check_password(password)
        if role not in ROLES:
            raise ValueError("권한은 관리자(admin)·유저(viewer) 가운데 하나여야 합니다.")
        with self._lock:
            data = dict(self._load())
            old = data.get(uid)
            if new and old is not None:
                raise ValueError("이미 있는 아이디입니다.")
            if old is None and len(data) >= ACCOUNTS_MAX:
                raise ValueError(f"계정은 {ACCOUNTS_MAX}개까지 만들 수 있습니다.")
            if (old is not None and old["role"] == "admin" and role != "admin" and not old.get("disabled")
                    and not self._other_admin(data, uid)):
                raise ValueError("마지막 관리자는 유저로 바꿀 수 없습니다.")
            data[uid] = self._record(password, role, bool(old and old.get("disabled")), must_change)
            self._save(data)
        return uid

    # --- 밖에서 부르는 것 ---
    def set(self, id, password, role, must_change=False):
        """계정을 만들거나 (있으면) 비밀번호·권한을 다시 정한다 → 아이디(소문자). 사용 중지 여부는 그대로 둔다.
        아이디·비밀번호(8자 이상)·권한이 맞지 않으면 ValueError (사람 말). 설치 마법사·설정 창이 부른다 (계획 ③)."""
        return self._put(id, password, role, must_change, new=False)

    def add(self, id, password, role, must_change=False):
        """새 계정만 만든다 - 이미 있으면 ValueError (있는 계정의 비밀번호를 덮지 않는다)."""
        return self._put(id, password, role, must_change, new=True)

    def get(self, id):
        """계정 하나 {id, role, disabled, must_change, rev} - 없으면 None. rev 는 서버 안에서만 쓴다."""
        uid = norm_id(id)
        with self._lock:
            rec = self._load().get(uid)
            return self._public(uid, rec, rev=True) if rec is not None else None

    def verify(self, id, password):
        """아이디·비밀번호가 맞으면 계정 {id, role, disabled, must_change, rev}, 아니면 None.
        **중지된 계정도 비밀번호가 맞으면 돌려준다** (disabled: True) - 로그인시킬지는 부르는 쪽이 disabled 를 본다.
        없는 아이디도 가짜 소금·해시로 같은 계산을 한 번 한다."""
        uid = norm_id(id)
        with self._lock:
            rec = self._load().get(uid)
        salt, want, rounds = _DUMMY_SALT, _DUMMY_HASH, PBKDF2_ITER
        if rec is not None:
            try:
                salt, want = bytes.fromhex(rec["salt"]), bytes.fromhex(rec["hash"])
                n = rec.get("iterations")
                rounds = n if isinstance(n, int) and not isinstance(n, bool) and 100000 <= n <= 5000000 else PBKDF2_ITER
            except ValueError:
                rec, salt, want = None, _DUMMY_SALT, _DUMMY_HASH
        same = hmac.compare_digest(_hash(password if isinstance(password, str) else "", salt, rounds), want)
        if not same or rec is None or not isinstance(password, str):
            return None
        return self._public(uid, rec, rev=True)

    def list(self):
        """[{id, role, disabled, must_change}] 아이디 순."""
        with self._lock:
            return [self._public(uid, rec) for uid, rec in sorted(self._load().items())]

    def disable(self, id, on):
        """사용 중지(on=True)·다시 사용. 없는 계정은 NoAccount, 마지막 관리자를 중지하려 하면 ValueError."""
        uid = norm_id(id)
        with self._lock:
            data = dict(self._load())
            rec = data.get(uid)
            if rec is None:
                raise NoAccount("없는 계정입니다.")
            if on and rec["role"] == "admin" and not rec.get("disabled") and not self._other_admin(data, uid):
                raise ValueError("마지막 관리자는 사용 중지할 수 없습니다.")
            data[uid] = dict(rec, disabled=bool(on))
            self._save(data)

    def remove(self, id):
        """계정 지우기. 없는 계정은 NoAccount, 마지막 관리자는 ValueError."""
        uid = norm_id(id)
        with self._lock:
            data = dict(self._load())
            rec = data.get(uid)
            if rec is None:
                raise NoAccount("없는 계정입니다.")
            if rec["role"] == "admin" and not rec.get("disabled") and not self._other_admin(data, uid):
                raise ValueError("마지막 관리자는 삭제할 수 없습니다.")
            del data[uid]
            self._save(data)

    def change_password(self, id, current, new):
        """자기 비밀번호 바꾸기 → 바뀐 계정 {id, role, disabled, must_change(False), rev}.
        새 비밀번호가 8자 미만이거나 지금 것과 같으면 WeakPassword, 현재 비밀번호가 틀리면 WrongPassword."""
        _check_password(new)
        acct = self.verify(id, current)
        if acct is None or acct["disabled"]:
            raise WrongPassword("현재 비밀번호가 일치하지 않습니다.")
        if hmac.compare_digest(current.encode("utf-8"), new.encode("utf-8")):
            raise WeakPassword("현재 비밀번호와 다른 비밀번호를 입력하여 주십시오.")
        with self._lock:
            data = dict(self._load())
            if acct["id"] not in data:
                raise NoAccount("없는 계정입니다.")
            data[acct["id"]] = self._record(new, data[acct["id"]]["role"], data[acct["id"]].get("disabled"), False)
            self._save(data)
            return self._public(acct["id"], data[acct["id"]], rev=True)


# ----------------------------------------------------------------------------------------------------
# 세션 · 잠금
# ----------------------------------------------------------------------------------------------------

class Sessions:
    """로그인 세션 - 메모리에만 (서버를 다시 켜면 모두 풀린다). 토큰은 secrets.token_urlsafe(32), 그 글 그대로 표에서 찾는다.
    미사용 idle_sec 또는 로그인 뒤 max_sec 가 지나면 끝난다. 토큰은 기록·파일에 남기지 않는다."""

    def __init__(self, idle_sec=IDLE_SEC, max_sec=MAX_SEC, clock=time.time):
        self.idle_sec, self.max_sec, self._clock = idle_sec, max_sec, clock
        self._lock = threading.Lock()
        self._items = {}

    def _dead(self, s, now):
        return now - s["seen"] > self.idle_sec or now - s["opened"] > self.max_sec

    def open(self, account):
        """account({id, role, rev?})의 새 세션 → 토큰."""
        token = secrets.token_urlsafe(32)
        now = self._clock()
        with self._lock:
            for t in [t for t, s in self._items.items() if self._dead(s, now)]:
                del self._items[t]
            while len(self._items) >= SESSIONS_MAX:       # 가장 오래 안 쓴 세션부터 밀어낸다
                del self._items[min(self._items, key=lambda t: self._items[t]["seen"])]
            self._items[token] = {"id": account["id"], "role": account.get("role"), "rev": account.get("rev"), "opened": now, "seen": now}
        return token

    def get(self, token, touch=False):
        """세션 {id, role, rev, opened, seen} 의 사본 - 없거나 끝났으면 (지우고) None. touch 면 미사용 시계를 다시 0 으로."""
        with self._lock:
            s = self._items.get(token) if isinstance(token, str) else None
            if s is None:
                return None
            now = self._clock()
            if self._dead(s, now):
                del self._items[token]
                return None
            if touch:
                s["seen"] = now
            return dict(s)

    def refresh(self, token, account):
        """비밀번호를 바꾼 뒤 그 탭의 세션을 새 계정 기록에 맞춘다 (그 세션은 살려 둔다)."""
        with self._lock:
            s = self._items.get(token)
            if s is not None:
                s["role"], s["rev"] = account.get("role"), account.get("rev")

    def close(self, token):
        with self._lock:
            self._items.pop(token, None)

    def close_account(self, id, keep=None):
        """그 계정의 세션을 모두 닫는다 (keep 토큰 하나는 남긴다) → 닫은 수."""
        with self._lock:
            gone = [t for t, s in self._items.items() if s["id"] == id and t != keep]
            for t in gone:
                del self._items[t]
            return len(gone)


class Lockout:
    """아이디마다 연속 실패 limit 번이면 lock_sec 초 잠금. 없는 아이디도 똑같이 센다 (잠겼다고 아이디가 있는 것이 아니다).
    잠긴 동안의 시도는 세지 않는다 (잠금이 늘어나지 않는다). 잠금이 풀리면 0 부터 다시 센다."""

    def __init__(self, limit=LOCK_LIMIT, lock_sec=LOCK_SEC, clock=time.time):
        self.limit, self.lock_sec, self._clock = limit, lock_sec, clock
        self._lock = threading.Lock()
        self._items = {}                             # 아이디 → [연속 실패 수, 잠금이 풀리는 시각 (0 = 잠기지 않음)]

    def _entry(self, id, now):
        e = self._items.get(id)
        if e is not None and e[1] and e[1] <= now:   # 잠금이 풀렸다
            del self._items[id]
            e = None
        return e

    def locked(self, id):
        with self._lock:
            e = self._entry(id, self._clock())
            return bool(e and e[1])

    def fail(self, id):
        """실패 한 번 → 이번 실패로 잠겼으면 True."""
        with self._lock:
            now = self._clock()
            e = self._entry(id, now)
            if e is None:
                if len(self._items) >= LOCK_TRACK_MAX:      # 잠기지 않은 것부터 비운다 (잠긴 것은 풀릴 때 지워진다)
                    self._items = {k: v for k, v in self._items.items() if v[1] > now}
                    if len(self._items) >= LOCK_TRACK_MAX:
                        self._items.clear()
                e = self._items[id] = [0, 0]
            if e[1]:
                return False
            e[0] += 1
            if e[0] >= self.limit:
                e[1] = now + self.lock_sec
                return True
            return False

    def ok(self, id):
        with self._lock:
            self._items.pop(id, None)


# ----------------------------------------------------------------------------------------------------
# 창구
# ----------------------------------------------------------------------------------------------------

class _Fail(Exception):
    """이 요청은 여기서 끝 - {"code", "message"} 로 답한다."""

    def __init__(self, status, code, message):
        super().__init__(code)
        self.status, self.code, self.message = status, code, message


_SENT = object()         # 응답을 이미 보냈다 (스트림)


def _scan_args(value, depth=0):
    """명령 인자 검사 → "deep"(너무 깊음)·"excel_pw"(엑셀 비밀번호 칸이 있음)·None(괜찮음)."""
    if depth > ARGS_DEPTH_MAX:
        return "deep"
    if isinstance(value, dict):
        if "excel_pw" in value:
            return "excel_pw"
        children = value.values()
    elif isinstance(value, list):
        children = value
    else:
        return None
    for child in children:
        bad = _scan_args(child, depth + 1)
        if bad:
            return bad
    return None


class Web:
    """웹 창구 하나 (서버 하나에 하나). handle() 이 /api/* 와 웹 파일 GET 을 처리한다.

    미사용 시계(30분)를 되돌리는 요청 = **사람이 한 일**: 로그인, `GET /api/session?touch=1`(화면이 입력을 본 뒤 보낸다),
    명령 보내기, 비밀번호 바꾸기, 계정 창구(목록 포함). 되돌리지 않는 것 = 화면이 혼자 하는 읽기: 그냥 `GET /api/session`,
    업체 정보, 명령 하나 읽기, 실행 기록, 스트림 - 탭을 열어만 둬도 세션이 이어지면 안 된다."""

    def __init__(self, store, runs, lic, folder, web_dir, clock=time.time):
        self.store, self.runs, self.lic, self.folder = store, runs, lic, folder
        self.web_dir = os.path.realpath(web_dir) if web_dir else None
        self.accounts = Accounts(os.path.join(folder, ACCOUNTS_NAME))
        self.sessions = Sessions(clock=clock)
        self.lockout = Lockout(clock=clock)
        self._clock = clock
        self._login_lock = threading.Lock()          # 비밀번호 확인은 한 번에 하나 - 잠금 확인과 실패 세기 사이에 다른 시도가 끼지 못한다
        self._streams, self._streams_lock = 0, threading.Lock()
        self._live = f"apps/{APP}/live/{lic['cid']}/{lic['pc_id']}"
        self._cmds = f"apps/{APP}/commands/{lic['cid']}/{lic['pc_id']}"
        self._routes = {
            ("login", False): {"POST": self._login},
            ("logout", False): {"POST": self._logout},
            ("session", False): {"GET": self._session_get},
            ("password", False): {"POST": self._password},
            ("company", False): {"GET": self._company},
            ("stream", False): {"GET": self._stream},
            ("commands", False): {"POST": self._command_new},
            ("commands", True): {"GET": self._command_get},
            ("runs", False): {"GET": self._runs},
            ("accounts", False): {"GET": self._accounts_list, "POST": self._account_add},
            ("accounts", True): {"POST": self._account_edit, "DELETE": self._account_remove},
            # 휴대폰 (계획 ④ Task 3) - 관리자만. phone = local_phone.Service (main 이 단다)
            ("phones", False): {"GET": self._phones_list},
            ("phones", True): {"POST": self._phone_edit, "DELETE": self._phone_remove},
            ("phone-pair", False): {"GET": self._pair_state, "POST": self._pair_start, "DELETE": self._pair_cancel},
        }
        self.phone = None

    # --- 들어오는 길 ---
    def handle(self, handler, method, path, query, body=None):
        """요청 하나를 처리한다 → 처리했으면 True (응답을 보냈다). body 는 Handler 가 이미 읽은 본문 (너무 커서 버렸으면 None).
        여기 오는 것은 /api/* (모든 방법) 와 그 밖의 GET (웹 파일) 이다 - 그 밖은 False (에이전트 창구가 서명을 본다)."""
        api = path.startswith("/api/")
        if not api and method != "GET":
            return False
        try:
            if not local_server.local_host(handler.headers, handler.server.server_port):
                raise _Fail(403, "forbidden", "이 PC 의 주소(127.0.0.1)로 접속하여 주십시오.")     # 다른 이름으로 이 PC 를 가리킨 요청 (DNS 바꿔치기)
            if api:
                out = self._api(handler, method, path, query or {}, body)
                if out is not _SENT:
                    self._json(handler, 200, out)
            else:
                self._file(handler, path)
        except _Fail as e:
            self._json(handler, e.status, {"code": e.code, "message": e.message})
        except (BrokenPipeError, ConnectionError, TimeoutError):
            raise                                    # 끊긴 연결 - Handler 가 조용히 끝낸다
        except Exception as e:                       # 서버가 죽지 않게 - 까닭의 종류만 남긴다
            self._log(f"웹 요청 처리 오류: {type(e).__name__}")
            try:
                self._json(handler, 500, {"code": "internal", "message": "요청을 처리하지 못했습니다. 잠시 후 다시 시도하여 주십시오."})
            except Exception:
                pass
        return True

    def _api(self, h, method, path, query, body):
        # 다른 사이트의 화면이 이 PC 주소로 보낸 요청은 받지 않는다. 브라우저는 POST 와 다른 출처의 요청에 Origin 을 싣는다
        # (주소창에 친 GET 은 Origin 이 없다). 세션이 쿠키가 아니라 머리글이라 따라갈 로그인도 없지만 한 겹 더 막는다.
        port = h.server.server_port
        origin = h.headers.get("Origin")
        if origin is not None and origin not in (f"http://127.0.0.1:{port}", f"http://localhost:{port}"):
            raise _Fail(403, "forbidden", "이 화면에서 보낸 요청이 아닙니다.")
        site = h.headers.get("Sec-Fetch-Site")
        if site is not None and site not in ("same-origin", "none"):
            raise _Fail(403, "forbidden", "이 화면에서 보낸 요청이 아닙니다.")
        if body is None or len(body) > API_BODY_MAX:
            raise _Fail(413, "too-large", "보낸 내용이 너무 큽니다.")
        parts = path[len("/api/"):].split("/")
        methods = self._routes.get((parts[0], len(parts) > 1))
        if methods is None or len(parts) > 2:
            raise _Fail(404, "not-found", "없는 주소입니다.")
        fn = methods.get(method)
        if fn is None:
            raise _Fail(405, "method-not-allowed", "이 주소에서 쓸 수 없는 방법입니다.")
        return fn(h, query, body, *parts[1:])

    # --- 응답 ---
    def _send(self, h, status, body, ctype, cache):
        h.send_response(status)
        h.send_header("Content-Type", ctype)
        if body is not None:
            h.send_header("Content-Length", str(len(body)))
        h.send_header("Cache-Control", cache)
        h.send_header("Content-Security-Policy", CSP)
        h.send_header("X-Content-Type-Options", "nosniff")
        h.send_header("X-Frame-Options", "DENY")
        h.send_header("Referrer-Policy", "no-referrer")
        h.end_headers()
        if body:
            h.wfile.write(body)

    def _json(self, h, status, value):
        self._send(h, status, json.dumps(value, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", "no-store")

    def _log(self, text):
        local_server.log(self.folder, text)

    # --- 요청에서 읽기 ---
    @staticmethod
    def _dict(body):
        """JSON 본문 (dict) - 아니면 400."""
        try:
            value = json.loads(body.decode("utf-8")) if body else None
        except (ValueError, UnicodeDecodeError, RecursionError):
            value = None
        if not isinstance(value, dict):
            raise _Fail(400, "invalid-argument", "보낸 내용의 형식이 올바르지 않습니다.")
        return value

    @staticmethod
    def _arg(raw, pattern, lower=False):
        """주소 조각 하나 (명령 키·아이디) - 풀었을 때 정해진 글자뿐이어야 한다 ('/'·'\\'·'..' 가 끼지 못한다)."""
        try:
            value = urllib.parse.unquote(raw, errors="strict")
        except UnicodeDecodeError:
            value = ""
        value = value.lower() if lower else value
        if not pattern.fullmatch(value) or ".." in value:
            raise _Fail(400, "invalid-argument", "주소가 올바르지 않습니다.")
        return value

    def _account_of(self, token):
        """이 토큰의 세션이 살아 있고 그 계정이 지금도 쓸 수 있으면 계정, 아니면 None (세션을 닫는다).
        계정이 없어졌거나 중지됐거나 로그인한 뒤 비밀번호가 다시 정해졌으면 (설정 창이 파일을 고친 경우 포함) 끝난 세션이다."""
        sess = self.sessions.get(token) if token else None
        if sess is None:
            return None
        acct = self.accounts.get(sess["id"])
        if acct is None or acct["disabled"] or acct["rev"] != sess["rev"]:
            # 이 탭이 비밀번호를 바꾸는 중이면 파일은 이미 바뀌고 세션은 아직 옛 rev 다 (_password 가 _login_lock 안에서 둘을 차례로 고친다) -
            # 그 사이에 스트림의 1초 확인이 끼면 자기 세션을 닫아 버렸다 (2026-11-23 화면 시험의 흔들리는 401). 끝나기를 기다려 다시 본다
            with self._login_lock:
                sess = self.sessions.get(token)
                acct = self.accounts.get(sess["id"]) if sess is not None else None
                if sess is None or acct is None or acct["disabled"] or acct["rev"] != sess["rev"]:
                    self.sessions.close(token)
                    return None
        return acct

    def _auth(self, h, touch=False, admin=False, must_ok=False):
        """Authorization: Bearer <세션 토큰> → (토큰, 계정). 없거나 끝난 세션 401, admin 창구에 유저 403.
        비밀번호를 바꿔야 하는 계정(must_change)은 must_ok 창구(세션·로그아웃·비밀번호·업체 정보·스트림)만 쓴다 - 그 밖은
        403 auth/must-change (화면도 계정 화면만 보이지만 서버가 한 겹 더 막는다, 계획 ② Task 3)."""
        raw = h.headers.get("Authorization") or ""
        token = raw[7:].strip() if raw.startswith("Bearer ") else ""
        token = token if TOKEN_RE.fullmatch(token) else None
        acct = self._account_of(token)
        if acct is None:
            raise _Fail(401, "unauthenticated", "로그인이 필요합니다. 다시 로그인하여 주십시오.")
        if acct["must_change"] and not must_ok:
            raise _Fail(403, "auth/must-change", "비밀번호를 먼저 바꿔 주십시오.")
        if admin and acct["role"] != "admin":
            raise _Fail(403, "PERMISSION_DENIED", "권한이 없습니다. 관리자 계정으로 로그인하여 주십시오.")
        if touch:
            self.sessions.get(token, touch=True)
        return token, acct

    def _public(self, acct):
        """화면에 주는 세션 (uid = email = 아이디 - 일반 버전 화면이 쓰는 칸 이름에 맞춘다)."""
        return {"uid": acct["id"], "id": acct["id"], "email": acct["id"], "cid": self.lic["cid"], "role": acct["role"],
                "mustChange": bool(acct["must_change"])}

    def _shown(self, uid):
        """기록에 적을 아이디 - 등록된 아이디만 그대로 (아이디 칸에 비밀번호를 잘못 친 글이 기록에 남지 않게)."""
        return uid if ID_RE.fullmatch(uid) and self.accounts.get(uid) is not None else "(등록되지 않은 아이디)"

    # --- 로그인 · 세션 ---
    def _login(self, h, query, body):
        data = self._dict(body)
        raw_id, password = data.get("id"), data.get("password")
        if not isinstance(raw_id, str) or not isinstance(password, str):
            raise _Fail(400, "invalid-argument", "아이디와 비밀번호를 입력하여 주십시오.")
        uid = norm_id(raw_id)
        key = uid[:64]
        with self._login_lock:
            if self.lockout.locked(key):             # 맞는 비밀번호도 받지 않는다 - 없는 아이디도 똑같이 잠긴다
                raise _Fail(429, "auth/too-many-requests", "로그인 시도가 많아 잠시 잠겼습니다. 1분 뒤 다시 시도하여 주십시오.")
            acct = self.accounts.verify(uid, password)
            if acct is None:
                shown = self._shown(uid)
                if self.lockout.fail(key):
                    self._log(f"웹 로그인 실패 - {self.lockout.limit}번 틀려 {self.lockout.lock_sec}초 잠금  아이디={shown}")
                else:
                    self._log(f"웹 로그인 실패  아이디={shown}")
                raise _Fail(401, "auth/invalid-credential", "아이디 또는 비밀번호가 일치하지 않습니다.")
            if acct["disabled"]:                     # 비밀번호가 맞을 때만 알려 준다 (틀리면 위에서 그냥 '틀림')
                self._log(f"웹 로그인 거절 - 사용 중지된 계정  아이디={uid}")
                raise _Fail(403, "auth/user-disabled", "사용이 중지된 계정입니다.")
            self.lockout.ok(key)
            token = self.sessions.open(acct)
        self._log(f"웹 로그인  아이디={uid}  권한={acct['role']}")
        return {"token": token, "session": self._public(acct)}

    def _logout(self, h, query, body):
        token, acct = self._auth(h, must_ok=True)
        self.sessions.close(token)
        self._log(f"웹 로그아웃  아이디={acct['id']}")
        return {"ok": True}

    def _session_get(self, h, query, body):
        _, acct = self._auth(h, touch=query.get("touch") == "1", must_ok=True)
        return {"session": self._public(acct), "now_ms": int(self._clock() * 1000)}

    def _password(self, h, query, body):
        token, acct = self._auth(h, touch=True, must_ok=True)
        data = self._dict(body)
        current, new = data.get("current"), data.get("next")
        if not isinstance(current, str) or not isinstance(new, str):
            raise _Fail(400, "invalid-argument", "현재 비밀번호와 새 비밀번호를 입력하여 주십시오.")
        uid = acct["id"]
        with self._login_lock:
            if self.lockout.locked(uid):             # 열린 탭으로 현재 비밀번호를 찍어 맞히지 못하게 로그인과 같은 잠금을 쓴다
                raise _Fail(429, "auth/too-many-requests", "시도가 많아 잠시 잠겼습니다. 1분 뒤 다시 시도하여 주십시오.")
            try:
                fresh = self.accounts.change_password(uid, current, new)
            except WeakPassword as e:
                raise _Fail(400, "auth/weak-password", str(e)) from None
            except WrongPassword as e:
                if self.lockout.fail(uid):
                    self._log(f"웹 비밀번호 변경 실패 - {self.lockout.limit}번 틀려 {self.lockout.lock_sec}초 잠금  아이디={uid}")
                raise _Fail(403, "auth/wrong-password", str(e)) from None      # 401 이 아니다 - 화면은 401 을 '세션 끝' 으로 본다
            except ValueError as e:
                raise _Fail(400, "invalid-argument", str(e)) from None
            self.lockout.ok(uid)
            self.sessions.refresh(token, fresh)                  # 바꾼 탭은 그대로 두고
            self.sessions.close_account(uid, keep=token)         # 그 계정의 다른 세션은 닫는다
        self._log(f"웹 비밀번호 변경  아이디={uid}")
        return {"ok": True, "session": self._public(fresh)}

    def _company(self, h, query, body):
        self._auth(h, must_ok=True)
        lic = self.lic
        return {"name": lic.get("company") or "", "stts": 0, "pcs": {lic["pc_id"]: {"label": socket.gethostname()}},
                "apps": {APP: {"modules": lic.get("modules") or {}, "limits": lic.get("limits") or {}, "features": lic.get("features") or {}}},
                "cid": lic["cid"], "pcId": lic["pc_id"]}

    # --- 명령 ---
    def _command_new(self, h, query, body):
        _, acct = self._auth(h, touch=True, admin=True)
        data = self._dict(body)
        kind, args = data.get("type"), data.get("args")
        if not isinstance(kind, str) or kind not in WEB_TYPES:
            raise _Fail(400, "invalid-argument", "보낼 수 없는 명령입니다.")
        if args is not None and not isinstance(args, dict):
            raise _Fail(400, "invalid-argument", "명령의 내용이 올바르지 않습니다.")
        bad = _scan_args(args)
        if bad == "excel_pw":                        # 엑셀 비밀번호는 명령에 싣지 않는다 (RTDB 규칙과 같은 뜻 - 옵저버에서만 넣는다)
            raise _Fail(400, "invalid-argument", "엑셀 비밀번호는 명령으로 보낼 수 없습니다. 옵저버에서 입력하여 주십시오.")
        if bad:
            raise _Fail(400, "invalid-argument", "명령의 내용이 올바르지 않습니다.")
        now = self._clock()
        # by·시각·상태는 서버가 정한다 (보낸 쪽이 적은 값은 쓰지 않는다)
        cmd = {"type": kind, "args": args, "by": acct["id"], "created_at": int(now),
               "expires_at": int(now) + (QUICK_TTL if kind in QUICK_TYPES else COMMAND_TTL), "state": "queued"}
        for _ in range(5):
            key = f"{int(now * 1000):013d}{secrets.token_hex(4)}"     # 만든 순서로 줄 선다
            path = f"{self._cmds}/{key}"
            try:
                self.store.put(path, cmd, guard=lambda get, path=path: get(path) is None)     # 같은 키를 덮지 않는다
            except local_server.Refused:
                continue
            return {"key": key, "value": self.store.get(path)}
        raise _Fail(503, "unavailable", "명령을 보내지 못했습니다. 다시 시도하여 주십시오.")

    def _command_get(self, h, query, body, raw_key):
        self._auth(h)
        return self.store.get(f"{self._cmds}/{self._arg(raw_key, KEY_RE)}")       # 없으면 null

    # --- 실행 기록 ---
    def _runs(self, h, query, body):
        self._auth(h)
        lic = self.lic
        if query.get("pcId", lic["pc_id"]) != lic["pc_id"] or query.get("cid", lic["cid"]) != lic["cid"]:
            raise _Fail(403, "permission-denied", "권한이 없습니다.")           # 이 PC 의 기록만 (다른 PC·업체 값은 받지 않는다)
        date = query.get("date") or None
        if date is not None and not DATE_RE.fullmatch(date):
            raise _Fail(400, "invalid-argument", "날짜는 YYYY-MM-DD 로 입력하여 주십시오.")
        try:
            limit = min(200, max(1, int(query.get("limit") or 100)))
        except ValueError:
            raise _Fail(400, "invalid-argument", "개수가 올바르지 않습니다.") from None
        return {"runs": self.runs.query(f"runs/{lic['cid']}", "items", lic["pc_id"], date, limit)}

    # --- 계정 관리 (관리자) ---
    def _accounts_out(self):
        return {"accounts": [{"id": a["id"], "role": a["role"], "disabled": a["disabled"], "mustChange": a["must_change"]}
                             for a in self.accounts.list()]}

    def _accounts_list(self, h, query, body):
        self._auth(h, touch=True, admin=True)
        return self._accounts_out()

    def _account_add(self, h, query, body):
        _, me = self._auth(h, touch=True, admin=True)
        data = self._dict(body)
        raw_id, password, role = data.get("id"), data.get("password"), data.get("role")
        if not isinstance(raw_id, str) or not isinstance(password, str) or not isinstance(role, str):
            raise _Fail(400, "invalid-argument", "아이디·비밀번호·권한을 입력하여 주십시오.")
        try:
            uid = self.accounts.add(raw_id, password, role, must_change=True)     # 관리자가 비밀번호를 안다 → 첫 로그인에 바꾸게
        except WeakPassword as e:
            raise _Fail(400, "auth/weak-password", str(e)) from None
        except ValueError as e:
            raise _Fail(400, "invalid-argument", str(e)) from None
        self._log(f"웹 계정 추가  아이디={uid}  권한={role}  처리={me['id']}")
        return self._accounts_out()

    def _account_edit(self, h, query, body, raw_id):
        _, me = self._auth(h, touch=True, admin=True)
        uid = self._arg(raw_id, ID_RE, lower=True)
        data = self._dict(body)
        disabled, password = data.get("disabled"), data.get("password")
        if (disabled is None and password is None) or (disabled is not None and not isinstance(disabled, bool)) \
                or (password is not None and not isinstance(password, str)):
            raise _Fail(400, "invalid-argument", "바꿀 내용이 올바르지 않습니다.")
        target = self.accounts.get(uid)
        if target is None:
            raise _Fail(404, "not-found", "없는 계정입니다.")
        if uid == me["id"]:      # 자기 중지 막기 + 자기 비밀번호는 현재 비밀번호를 확인하는 /api/password 로만
            raise _Fail(400, "invalid-argument", "자기 계정은 여기서 바꿀 수 없습니다. 비밀번호는 '비밀번호 변경'에서 바꾸어 주십시오.")
        try:
            if password is not None:
                _check_password(password)
                self.accounts.set(uid, password, target["role"], must_change=True)     # 다음 로그인에 바꾸게 한다
            if disabled is not None:
                self.accounts.disable(uid, disabled)
        except WeakPassword as e:
            raise _Fail(400, "auth/weak-password", str(e)) from None
        except NoAccount as e:
            raise _Fail(404, "not-found", str(e)) from None
        except ValueError as e:
            raise _Fail(400, "invalid-argument", str(e)) from None
        finally:
            self.sessions.close_account(uid)         # 바뀐 계정의 열린 세션을 닫는다
        did = [] if password is None else ["비밀번호 다시 정함"]
        did += [] if disabled is None else ["사용 중지" if disabled else "다시 사용"]
        self._log(f"웹 계정 변경 ({'·'.join(did)})  아이디={uid}  처리={me['id']}")
        return self._accounts_out()

    def _account_remove(self, h, query, body, raw_id):
        _, me = self._auth(h, touch=True, admin=True)
        uid = self._arg(raw_id, ID_RE, lower=True)
        if uid == me["id"]:
            raise _Fail(400, "invalid-argument", "자기 계정은 삭제할 수 없습니다.")
        try:
            self.accounts.remove(uid)
        except NoAccount as e:
            raise _Fail(404, "not-found", str(e)) from None
        except ValueError as e:
            raise _Fail(400, "invalid-argument", str(e)) from None
        self.sessions.close_account(uid)
        self._log(f"웹 계정 삭제  아이디={uid}  처리={me['id']}")
        return self._accounts_out()

    # --- 휴대폰 (관리자, 계획 ④ Task 3) ---
    # 짝 열쇠(QR 의 k)는 POST /api/phone-pair 응답에 한 번만 나간다 - 기록·저장 파일·다른 응답에 싣지 않는다.
    # GET /api/phone-pair·GET /api/phones 는 화면이 혼자 묻는 읽기라 미사용 시계를 되돌리지 않는다.
    def _phone_service(self, h, touch):
        _, me = self._auth(h, touch=touch, admin=True)
        if self.phone is None:
            raise _Fail(404, "not-found", "없는 주소입니다.")
        return self.phone, me

    def _phones_out(self, svc, gate=None):
        gate = gate or svc.gate.status()
        return {"phones": svc.phones.list(gate.get("fingerprint")), "gate": gate}

    @staticmethod
    def _phone_fields(data, need_label):
        """{label, owner, senders} 에서 바꿀 값 (없는 칸은 None). 꼴이 틀리면 400 (사람 말)."""
        import local_phone
        out = {}
        try:
            if need_label or data.get("label") is not None:
                label = local_phone.clean_name(data.get("label"), "휴대폰 이름")
                if not label:
                    raise ValueError("휴대폰 이름을 입력하여 주십시오. (예: 김OO 휴대폰)")
                out["label"] = label
            if data.get("owner") is not None:
                out["owner"] = local_phone.clean_name(data.get("owner"), "담당자")
            if data.get("senders") is not None:
                out["senders"] = local_phone.parse_senders(data.get("senders"))
        except ValueError as e:
            raise _Fail(400, "invalid-argument", str(e)) from None
        return out

    def _phone_id(self, raw):
        import local_phone
        return self._arg(raw, local_phone.PHONE_ID_RE)

    def _phones_list(self, h, query, body):
        svc, _ = self._phone_service(h, touch=False)
        return self._phones_out(svc)

    def _pair_start(self, h, query, body):
        import local_phone
        svc, me = self._phone_service(h, touch=True)
        fields = self._phone_fields(self._dict(body), need_label=True)
        if svc.phones.count() >= local_phone.PHONES_MAX:
            raise _Fail(400, "invalid-argument", f"휴대폰은 {local_phone.PHONES_MAX}대까지 등록할 수 있습니다.")
        try:
            gate = svc.gate.open()                                # 주소·방화벽·인증서 - 못 열면 짝짓기를 시작하지 않는다
        except local_phone.GateError as e:
            self._log(f"휴대폰 포트를 열지 못했습니다 ({e.code})  처리={me['id']}")
            raise _Fail(409, f"phone/{e.code}", e.message) from None
        got = svc.pairing.start(fields["label"], fields.get("owner", ""), fields.get("senders", []))
        self._log(f"휴대폰 짝짓기 시작  번호={got['phone_id']}  이름={fields['label']}  처리={me['id']}")
        return {"qr": local_phone.qr_text(gate["hosts"], gate["port"], got["phone_id"], got["secret"], gate["fingerprint"]),
                "phone_id": got["phone_id"], "expires_in": local_phone.PAIR_SEC, "hosts": gate["hosts"], "port": gate["port"],
                "fingerprint": gate["fingerprint"]}

    def _pair_state(self, h, query, body):
        svc, _ = self._phone_service(h, touch=False)
        return svc.pairing.state()

    def _pair_cancel(self, h, query, body):
        svc, me = self._phone_service(h, touch=True)
        was = svc.pairing.waiting()
        svc.pairing.cancel()
        gate = svc.gate.sync()
        if was:
            self._log(f"휴대폰 짝짓기 취소  처리={me['id']}")
        return {"state": "none", "gate": gate}

    def _phone_edit(self, h, query, body, raw_id):
        svc, me = self._phone_service(h, touch=True)
        pid = self._phone_id(raw_id)
        fields = self._phone_fields(self._dict(body), need_label=False)
        if not svc.phones.update(pid, **fields):
            raise _Fail(404, "not-found", "없는 휴대폰입니다.")
        self._log(f"휴대폰 정보 변경  번호={pid}  처리={me['id']}")
        return self._phones_out(svc)

    def _phone_remove(self, h, query, body, raw_id):
        svc, me = self._phone_service(h, touch=True)
        pid = self._phone_id(raw_id)
        rec = svc.phones.get(pid)
        if rec is None or not svc.phones.remove(pid):
            raise _Fail(404, "not-found", "없는 휴대폰입니다.")
        svc.desk.forget(pid)                                      # 그 휴대폰의 요청·번호 자리
        gate = svc.gate.sync()                                    # 0대면 포트·방화벽 규칙을 닫는다
        self._log(f"휴대폰 삭제  번호={pid}  이름={rec.get('label') or ''}  처리={me['id']}")
        return self._phones_out(svc, gate)

    # --- 스트림 (SSE) ---
    def _stream(self, h, query, body):
        """현황·명령이 바뀔 때마다 민다 (Firebase onValue 자리). local_server.Handler._stream 과 같은 꼴 - 구독 큐를 0.5초씩 기다리며
        서버 끝·밀린 구독·세션을 본다. 이벤트:
            live      = 현황 전체 (붙을 때 한 번 - 없으면 null - 그리고 바뀔 때마다)
            command   = {"key", "value"} 바뀐 명령 하나의 지금 값 (지워졌으면 null)
            keep-alive= 조용할 때 KEEPALIVE_SEC 마다,  gone = 세션이 끝났다 (보내고 닫는다 - 화면은 로그인으로)
        이벤트에 서명은 없다 (브라우저용). 세션은 1초에 한 번쯤 다시 본다 - 미사용 시계는 되돌리지 않는다."""
        token, _ = self._auth(h, must_ok=True)
        with self._streams_lock:
            if self._streams >= MAX_STREAMS:
                raise _Fail(503, "unavailable", "열어 둔 화면이 너무 많습니다. 쓰지 않는 탭을 닫아 주십시오.")
            self._streams += 1
        srv, q = h.server, None
        live_at, cmds_at = self._live.split("/")[2:], self._cmds.split("/")[2:]      # 구독 자리(apps/rpa) 아래의 조각

        def send(event, data):
            h.wfile.write(f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8"))
            h.wfile.flush()

        try:
            q = self.store.subscribe(f"apps/{APP}")              # 현황과 명령을 한 구독으로 (큐 하나)
            self._send(h, 200, None, "text/event-stream; charset=utf-8", "no-store")
            quiet = checked = time.monotonic()
            while not srv.stopping.is_set():
                if time.monotonic() - checked >= 1.0:            # 이벤트가 이어져도 1초에 한 번은 세션을 본다
                    checked = time.monotonic()
                    if self._account_of(token) is None:
                        send("gone", None)
                        return _SENT
                try:
                    batch = [q.get(timeout=0.5)]
                except queue.Empty:
                    if getattr(q, "overflow", False):            # 읽지 않아 밀린 구독 - 끊는다 (화면이 다시 붙어 처음 값부터 받는다)
                        break
                    if time.monotonic() - quiet >= local_server.KEEPALIVE_SEC:
                        send("keep-alive", None)
                        quiet = time.monotonic()
                    continue
                while len(batch) < 200:                          # 몰려온 변경은 모아서 한 번씩만 보낸다 (값은 어차피 지금 값을 읽는다)
                    try:
                        batch.append(q.get_nowait())
                    except queue.Empty:
                        break
                live, keys = False, []
                for event, data in batch:
                    base = [p for p in str(data.get("path") or "").split("/") if p]
                    value = data.get("data")
                    spots = [base + [p for p in str(k).split("/") if p] for k in value] if event == "patch" and isinstance(value, dict) else [base]
                    for spot in spots:
                        if spot[:len(live_at)] == live_at or live_at[:len(spot)] == spot:       # 현황 자리나 그 아래·윗자리
                            live = True
                        if spot[:len(cmds_at)] == cmds_at and len(spot) > len(cmds_at) and spot[len(cmds_at)] not in keys:
                            keys.append(spot[len(cmds_at)])      # 명령 하나(나 그 안쪽 칸). 명령함 통째('/')는 건너뛴다
                if live:
                    send("live", self.store.get(self._live))
                for key in keys:
                    send("command", {"key": key, "value": self.store.get(f"{self._cmds}/{key}")})
                if live or keys:
                    quiet = time.monotonic()
        finally:
            if q is not None:
                self.store.unsubscribe(q)
            with self._streams_lock:
                self._streams -= 1
        return _SENT

    # --- 웹 파일 ---
    def _segments(self, path):
        """주소 → 웹 폴더 아래 조각 목록, 받을 수 없는 주소면 None. 파일을 건드리기 **전에** 글자만 보고 거른다:
        풀었을 때(%xx) 영문·숫자·_·-·. 뿐이고 점으로 시작하거나 끝나지 않는 조각만 - '..'·'\\'·':'(드라이브·다른 스트림)·NUL·빈칸·
        두 번 싼 %25 가 모두 여기서 떨어진다. 윈도우 장치 이름(CON·NUL·COM1…)도 거른다."""
        if not path.startswith("/"):
            return None
        raw = path[1:].split("/")
        if raw == [""]:
            return ["index.html"]
        if len(raw) > 6:
            return None
        segs = []
        for part in raw:
            try:
                seg = urllib.parse.unquote(part, errors="strict")
            except UnicodeDecodeError:
                return None
            if len(seg) > 100 or not SEG_RE.fullmatch(seg) or ".." in seg or seg.endswith(".") or seg.split(".")[0].upper() in DEVICES:
                return None
            segs.append(seg)
        return segs

    def _file(self, h, path):
        segs = self._segments(path)
        ext = os.path.splitext(segs[-1])[1].lower() if segs else ""
        body = None
        if segs and ext in TYPES and segs[-1].lower() not in HIDDEN_FILES:
            if len(segs) == 1 and segs[0].lower() == "edition.js":
                body = edition_js()                  # 파일에 무엇이 적혀 있든 스탠드얼론 (화면이 data-local 을 고른다)
            elif self.web_dir:
                # 두 번째 겹 (위의 글자 검사와 따로 선다): 웹 폴더 글 뒤에 조각을 **이어 붙인** 자리의 진짜 자리(realpath)가 그 글과
                # 글자까지 같아야 한다. os.path.join 을 쓰지 않는다 - 조각이 'C:\\…' 같은 절대 경로면 앞을 버린다.
                # 폴더 밖을 가리키는 링크, 대소문자만 다른 이름(윈도우는 같은 파일로 연다 → 숨길 파일·edition.js 규칙을 비켜 간다),
                # 짧은 이름(8.3), '..' 가 모두 여기서 떨어진다 (진짜 자리가 달라진다)
                root = self.web_dir.rstrip("\\/")
                full = root + os.sep + os.sep.join(segs)
                real = os.path.realpath(full)
                if real == full and real.startswith(root + os.sep) and os.path.isfile(real) and os.path.getsize(real) <= FILE_MAX:
                    with open(real, "rb") as f:
                        body = f.read()
                    if ext == ".html":
                        body = b"\n".join(line for line in body.split(b"\n") if STRIP_HTML not in line)
        if body is None:
            raise _Fail(404, "not-found", "없는 주소입니다.")
        self._send(h, 200, body, TYPES[ext], "no-cache")
