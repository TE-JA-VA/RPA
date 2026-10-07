# -*- coding: utf-8 -*-
r"""RPA 현황 대시보드. 사내 다른 PC 나 휴대폰 브라우저에서 진행 상황을 본다.

프리페어 RPA / 루틴 RPA 가 rpa_status 로 남기는 기록을 읽어서 보여준다.

로그인 (운영 정책: 보는 건 로그인한 모두, 바꾸고 실행하는 건 관리자만)
    화면을 열면 업체코드 / 아이디 / 비밀번호를 묻는다. 업체코드는 확인하지 않고 표시에만 쓴다.
    기본 계정 (처음 뜰 때 settings.json 에 해시로 만들어 둔다. 비밀번호는 화면에서 바꿀 수 있다)
        관리자      admin / admin   현황·이력 보기 + 지금 실행 + 자동 실행 설정 + 실행 모듈 선택 + ERPia 종료
        일반 사용자 user  / user    현황·이력 보기
    비밀번호를 잊었으면 settings.json 의 "accounts" 를 지우고 대시보드를 다시 띄운다 (기본값으로 돌아간다).

실행
    RPA_Dashboard.exe                  포트 8765 로 띄운다
    RPA_Dashboard.exe --port 9000      포트 바꾸기
    RPA_Dashboard.exe --host 127.0.0.1 이 PC 에서만 볼 수 있게 한다
    python rpa_dashboard.py --status-dir <폴더>   (점검용) 다른 기록 폴더를 본다

보는 주소
    같은 PC     http://localhost:8765
    다른 PC/폰  http://<이 PC 의 IP>:8765   (시작할 때 창에 주소를 찍어 준다)
    사내망에서만 쓸 것. HTTP 라 비밀번호가 사내망 안에서 평문으로 지나간다.

권한
    지금 실행·자동 실행·ERPia 종료는 ERPia(관리자 권한) 를 다루므로, 이 프로그램도 관리자 권한으로
    떠 있어야 제대로 된다. Run_All.bat 을 관리자로 실행하면 같이 관리자로 뜬다.
"""
import argparse
import ctypes
import datetime
import hashlib
import hmac
import http.cookies
import http.server
import json
import os
import secrets
import socket
import socketserver
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request

import rpa_status as st

DEFAULT_PORT = 8765
SIGNATURE = "ERPIA_RPA_DASHBOARD"
PERIODS = ("today", "7", "30", "all")
ERPIA_EXE = "ERPiaMain.exe"
RUN_BAT = "Run_All.bat"
ACTION_HEADER = "X-RPA-Action"     # 화면의 자바스크립트만 붙이는 머리글. 단순 폼 전송을 막는다.
MAX_BODY = 64 * 1024
SCHEDULER_TICK = 5.0
# 대시보드를 다시 켰을 때 이만큼 안에 지난 예약은 그대로 돌리고, 더 오래된 것은 건너뛴다
MISSED_GRACE_SEC = 120
NOW = datetime.datetime.now   # 예약 계산의 지금 - 시험이 가짜 시계로 바꾼다 (tests/test_schedule_repeat.py)
WEEKDAY_NAMES = "월화수목금토일"
ACCOUNT_CACHE_SEC = 30.0

SESSION_COOKIE = "rpa_session"
SESSION_IDLE_SEC = 12 * 3600       # 이만큼 안 쓰면 다시 로그인
LOGIN_MAX_FAILS = 5                # 같은 주소에서 이만큼 틀리면
LOGIN_LOCK_SEC = 60                # 이 시간 동안 막는다
PBKDF2_ROUNDS = 120_000
DEFAULT_ACCOUNTS = (("admin", "admin", "admin"), ("user", "user", "user"))   # (아이디, 비밀번호, 역할)
ROLE_LABEL = {"admin": "관리자", "user": "일반 사용자"}
DRY_RUN = os.environ.get("RPA_DASHBOARD_DRY_RUN") == "1"   # 시험용: Run_All.bat 을 실제로 띄우지 않는다

# 화면이 외부 자원을 부르지 않으므로 모두 막는다. 인라인 스크립트/스타일만 허용한다.
HTML_CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
            "connect-src 'self'; img-src 'self' data:; base-uri 'none'; "
            "form-action 'none'; frame-ancestors 'none'")


def resource_path(name):
    """exe 로 묶이면 함께 넣은 파일은 임시 폴더(_MEIPASS)에 풀린다."""
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, name)


_page_cache = {"mtime": None, "html": b"", "version": ""}


def page_html():
    """dashboard.html 과 그 판 번호(내용 해시). 화면 코드가 바뀌면 열려 있는 탭이 알아채고 새로고침을 권한다."""
    path = resource_path("dashboard.html")
    mtime = os.path.getmtime(path)
    if _page_cache["mtime"] != mtime:
        with open(path, "rb") as f:
            raw = f.read()
        version = hashlib.sha1(raw).hexdigest()[:12]
        _page_cache.update(mtime=mtime, version=version,
                           html=raw.replace(b'name="page-version" content=""',
                                            b'name="page-version" content="' + version.encode() + b'"', 1))
    return _page_cache["html"], _page_cache["version"]


def app_dir():
    """exe 면 exe 가 있는 폴더, 소스로 돌리면 이 파일이 있는 폴더."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def run_command_path():
    """지금 실행 / 자동 실행 때 띄울 Run_All.bat.

    exe 로 돌면 exe 옆의 것. 소스로 돌릴 때는 dist 폴더(exe 들이 있는 곳)를 먼저 본다 -
    소스 폴더의 Run_All.bat 은 옆에 exe 가 없어서 띄워도 바로 실패한다.
    """
    base = app_dir()
    folders = (base,) if getattr(sys, "frozen", False) else (os.path.join(base, "dist"), base)
    for folder in folders:
        candidate = os.path.join(folder, RUN_BAT)
        if os.path.isfile(candidate):
            return candidate
    return os.path.join(base, RUN_BAT)


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def period_since(period):
    today = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "today":
        return today.isoformat()
    if period in ("7", "30"):
        return (today - datetime.timedelta(days=int(period) - 1)).isoformat()
    return None


def now_text():
    return datetime.datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# 계정 / 세션
# ---------------------------------------------------------------------------
_settings_lock = threading.Lock()


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ROUNDS)
    return salt, digest.hex()


def verify_password(account, password):
    try:
        _, digest = hash_password(password, account["salt"])
        return hmac.compare_digest(digest, account["hash"])
    except Exception:
        return False


def ensure_accounts():
    """계정이 하나도 없으면 기본 계정(admin/admin, user/user)을 해시로 만들어 둔다."""
    with _settings_lock:
        cfg = st.read_settings()
        if cfg.get("accounts"):
            return False
        accounts = {}
        for user_id, password, role in DEFAULT_ACCOUNTS:
            salt, digest = hash_password(password)
            accounts[user_id] = {"role": role, "salt": salt, "hash": digest,
                                 "created_at": now_text(), "default_password": True}
        cfg["accounts"] = accounts
        st.write_settings(cfg)
        return True


def find_account(user_id):
    accounts = st.read_settings().get("accounts") or {}
    acc = accounts.get(str(user_id or "").strip())
    return dict(acc, user_id=str(user_id).strip()) if isinstance(acc, dict) else None


def change_password(user_id, current, new):
    if not isinstance(new, str) or len(new) < 4 or len(new) > 64:
        raise ValueError("새 비밀번호는 4자 이상 64자 이하여야 합니다")
    with _settings_lock:
        cfg = st.read_settings()
        acc = (cfg.get("accounts") or {}).get(user_id)
        if not acc or not verify_password(acc, current or ""):
            raise PermissionError("현재 비밀번호가 맞지 않습니다")
        salt, digest = hash_password(new)
        acc.update(salt=salt, hash=digest, changed_at=now_text(), default_password=False)
        if not st.write_settings(cfg):
            raise RuntimeError("설정 파일을 쓰지 못했습니다")


class Sessions:
    """메모리에만 둔다. 대시보드를 다시 띄우면 모두 다시 로그인한다."""

    def __init__(self):
        self.lock = threading.Lock()
        self.items = {}
        self.fails = {}   # 주소 -> [횟수, 막힌 시각(끝)]

    def create(self, user_id, role, admin_code):
        token = secrets.token_urlsafe(32)
        with self.lock:
            self.items[token] = {"user_id": user_id, "role": role, "admin_code": admin_code,
                                 "created": time.time(), "seen": time.time()}
        return token

    def get(self, token):
        if not token:
            return None
        with self.lock:
            s = self.items.get(token)
            if s is None:
                return None
            if time.time() - s["seen"] > SESSION_IDLE_SEC:
                del self.items[token]
                return None
            s["seen"] = time.time()
            return dict(s)

    def drop(self, token):
        with self.lock:
            self.items.pop(token, None)

    def drop_user(self, user_id):
        """비밀번호를 바꾸면 그 계정의 다른 세션도 끊는다."""
        with self.lock:
            for t in [t for t, s in self.items.items() if s["user_id"] == user_id]:
                del self.items[t]

    def locked_for(self, addr):
        with self.lock:
            f = self.fails.get(addr)
            if f and f[1] > time.time():
                return int(f[1] - time.time())
            return 0

    def note_fail(self, addr):
        with self.lock:
            f = self.fails.setdefault(addr, [0, 0])
            f[0] += 1
            if f[0] >= LOGIN_MAX_FAILS:
                f[0] = 0
                f[1] = time.time() + LOGIN_LOCK_SEC

    def note_ok(self, addr):
        with self.lock:
            self.fails.pop(addr, None)


SESSIONS = Sessions()


# ---------------------------------------------------------------------------
# ERPia 프로세스 (종료 = 로그아웃)
# ---------------------------------------------------------------------------
TH32CS_SNAPPROCESS = 0x00000002
PROCESS_TERMINATE = 0x0001
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
ERROR_ACCESS_DENIED = 5


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.c_uint32),
        ("cntUsage", ctypes.c_uint32),
        ("th32ProcessID", ctypes.c_uint32),
        ("th32DefaultHeapID", ctypes.c_void_p),
        ("th32ModuleID", ctypes.c_uint32),
        ("cntThreads", ctypes.c_uint32),
        ("th32ParentProcessID", ctypes.c_uint32),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", ctypes.c_uint32),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


_K32 = None


def _k32():
    """이 모듈 전용 kernel32 (전역 ctypes.windll 의 함수 원형을 건드리지 않는다)."""
    global _K32
    if _K32 is None and os.name == "nt":
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
        k.CreateToolhelp32Snapshot.argtypes = (ctypes.c_uint32, ctypes.c_uint32)
        k.Process32FirstW.argtypes = (ctypes.c_void_p, ctypes.POINTER(_PROCESSENTRY32W))
        k.Process32NextW.argtypes = (ctypes.c_void_p, ctypes.POINTER(_PROCESSENTRY32W))
        k.OpenProcess.restype = ctypes.c_void_p
        k.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
        k.TerminateProcess.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
        k.CloseHandle.argtypes = (ctypes.c_void_p,)
        _K32 = k
    return _K32


def find_pids(exe_name):
    """이름이 같은 프로세스 번호 목록."""
    k = _k32()
    if k is None:
        return []
    snap = k.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == INVALID_HANDLE_VALUE:
        return []
    pids = []
    try:
        entry = _PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        ok = k.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            if entry.szExeFile.lower() == exe_name.lower():
                pids.append(int(entry.th32ProcessID))
            ok = k.Process32NextW(snap, ctypes.byref(entry))
    finally:
        k.CloseHandle(snap)
    return pids


def terminate_pid(pid):
    """프로세스를 끝낸다. 성공하면 None, 실패하면 이유 문자열."""
    k = _k32()
    if k is None:
        return "윈도우가 아닙니다"
    h = k.OpenProcess(PROCESS_TERMINATE, 0, int(pid))
    if not h:
        err = ctypes.get_last_error()
        if err == ERROR_ACCESS_DENIED:
            return "접근 거부 - 대시보드가 관리자 권한이 아닙니다"
        return f"프로세스를 열 수 없습니다 (오류 {err})"
    try:
        if not k.TerminateProcess(h, 1):
            return f"종료 실패 (오류 {ctypes.get_last_error()})"
    finally:
        k.CloseHandle(h)
    return None


def erpia_running():
    try:
        return bool(find_pids(ERPIA_EXE))
    except Exception:
        return None


def any_rpa_running(snapshot=None):
    return st.running_programs(snapshot)


# ---------------------------------------------------------------------------
# 실행 (지금 실행 / 자동 실행)
# ---------------------------------------------------------------------------
_launch_lock = threading.Lock()
LAUNCHED = []   # 시험용(DRY_RUN) 기록: "target:by"
LAUNCHED_ENV = []   # 시험용(DRY_RUN): 띄울 때 더한 환경 변수 (LAUNCHED 와 같은 순서)
LAUNCH_GRACE_SEC = 90   # 프로세스 손잡이를 잃었을 때(대시보드 재시작 등)를 대비한 최소 잠금 시간
TARGETS = {
    # target: (설명, 파일 이름, 추가 인자). 파일은 Run_All.bat 과 같은 폴더에 있다.
    "all": ("전체 실행 (프리페어 → 루틴)", RUN_BAT, ()),
    "prepare": ("프리페어 RPA", "Prepare_RPA.exe", ("--all", "--no-keep-open")),
    "routine": ("루틴 RPA", "ERPia_RPA.exe", ()),
}
_active = {"target": None, "by": None, "at": 0.0, "proc": None, "until": 0.0, "checked": False}
# 토큰 확인 (2026-10-06): 에이전트가 agent.Tokens.gate 를 단다 - 띄우기 직전에 target 으로 부르고, 남은 토큰이 없으면
# RuntimeError(사람에게 보일 글). 에이전트 없이 도는 옛 8765 대시보드·시험은 None (막지 않는다)
TOKEN_GATE = None
_check_lock = threading.Lock()   # 에이전트 순환과 명령 처리가 같이 launch_state 를 불러도 한 번만 남긴다


def target_path(target):
    folder = os.path.dirname(run_command_path())
    return os.path.join(folder, TARGETS[target][1])


def launch_state():
    """대시보드가 띄운 실행이 아직 살아 있으면 {target, by, sec}, 아니면 None.

    전체 실행은 프리페어가 끝나고 루틴 exe 가 풀리기까지 몇 초 동안 기록상으로는
    '도는 RPA 없음' 이 된다. 그 틈에 버튼이 풀리지 않도록 띄운 프로세스 자체를 본다.
    """
    if not _active["at"]:
        return None
    proc = _active["proc"]
    if proc is not None:
        code = proc.poll()
        alive = code is None                 # 손잡이가 있으면 프로세스 생사가 곧 답이다
        if not alive:
            with _check_lock:
                first, _active["checked"] = not _active["checked"], True
            if first:
                _note_start_failure(code)
    else:
        alive = time.time() < _active["until"]   # 손잡이가 없을 때(시험 모드)만 유예 시간을 쓴다
    if not alive:
        return None
    return {"target": _active["target"], "by": _active["by"], "sec": int(time.time() - _active["at"])}


def _note_start_failure(code):
    """띄운 것이 끝났는데 그 뒤로 기록을 하나도 안 남긴 프로그램은 '시작하지 못함' 이력으로 남긴다. 두 프로그램 모두
    정상이면 맨 먼저 status.start 를 부르니, 기록이 없으면 켜지자마자 죽은 것이다 (2026-09-29 노트북: exe 가
    ImportError 로 죽었는데 기록 탭이 비어 있었다). 종료 코드는 안 본다 - Run_All.bat 은 늘 0 으로 끝난다."""
    try:
        target = _active["target"]
        since = datetime.datetime.fromtimestamp(_active["at"]).replace(microsecond=0)
        try:
            raw = open(os.path.join(st.status_dir(), f"stderr_{target}.txt"), "rb").read()
        except OSError:
            raw = b""
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("cp949", "replace")     # 파일로 받은 exe 출력이 CP949 일 때가 있다 (샌드박스 실측)
        tail = [ln for ln in text.splitlines() if ln.strip()][-20:]
        reason = "시작하지 못했습니다 - " + (tail[-1].strip() if tail else f"오류 출력 없음, 종료 코드 {code}")
        for program in (("prepare", "routine") if target == "all" else (target,)):
            started = st.parse_iso((st.read_json(st.status_path(program)) or {}).get("started_at"))
            if started is None or started < since:
                st.record_start_failure(program, since.isoformat(), reason, tail)
    except Exception:
        pass   # 기록은 RPA·에이전트를 멈추게 하면 안 된다


def launching_sec():
    """띄운 것이 살아 있는데 아직 어느 RPA 도 기록을 남기지 않았으면 몇 초째인지, 아니면 None."""
    ls = launch_state()
    if ls and not any_rpa_running():
        return ls["sec"]
    return None


def launch(target, by, env=None):
    """RPA 를 새 콘솔 창으로 띄우고 설정에 기록한다.

    target: all / prepare / routine,  by: 'auto' 또는 'manual:<아이디>'
    env: 자식에게 더할 환경 변수 - 예약 줄의 이번 실행 모듈(RPA_RUN_MODULES)·띄운 까닭(RPA_RUN_TRIGGER)
    """
    if target not in TARGETS:
        raise ValueError("실행 대상이 잘못되었습니다")
    label, name, args = TARGETS[target]
    path = target_path(target)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"{name} 이(가) 없습니다: {path}")
    with _launch_lock:
        running = any_rpa_running()
        if running:
            names = ", ".join(st.PROGRAMS.get(p, p) for p in running)
            raise RuntimeError(f"{names} 가 이미 돌고 있습니다")
        ls = launch_state()
        if ls:
            raise RuntimeError(f"{TARGETS[ls['target']][0]} 이(가) 아직 진행 중입니다 ({ls['sec']}초째)")
        if st.observer_open():
            raise RuntimeError("옵저버가 켜져 있습니다. 옵저버를 닫은 뒤 실행하세요")
        if TOKEN_GATE is not None:
            TOKEN_GATE(target)             # 실행 단추·예약 모두 여기를 지난다
        proc = None
        if DRY_RUN:
            LAUNCHED.append(f"{target}:{by}")
            LAUNCHED_ENV.append(dict(env or {}))
        else:
            cmd = ["cmd.exe", "/c", path] if path.lower().endswith(".bat") else [path, *args]
            # 새 콘솔 창은 프로그램이 끝나면 바로 닫혀 오류 출력이 사라진다. stderr 만 파일로 남긴다.
            err_path = os.path.join(st.status_dir(), f"stderr_{target}.txt")
            try:
                err_fh = open(err_path, "w", encoding="utf-8")
            except OSError:
                err_fh = None
            try:
                # 여기서 띄우는 실행은 모두 무인이다 (원격 버튼·자동 실행). RPA 가 사람에게 묻는 창(ERPia 위치 고르기 등)을
                # 띄우고 기다리면 아무도 없는 PC 에서 멈추므로, 표시를 넘겨 바로 멈추고 사유를 남기게 한다.
                proc = subprocess.Popen(cmd, cwd=os.path.dirname(path), stderr=err_fh,
                                        env={**os.environ, "RPA_UNATTENDED": "1", **(env or {})},
                                        creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
            finally:
                if err_fh is not None:
                    err_fh.close()   # 자식이 손잡이를 물려받았으므로 여기서는 닫아도 된다
        now_t = time.time()
        _active.update(target=target, by=by, at=now_t, proc=proc, checked=False,
                       until=now_t + (3 if DRY_RUN else LAUNCH_GRACE_SEC))
        now = NOW()
        with _settings_lock:
            cfg = st.read_settings()
            sch = cfg["schedule"]
            sch["last_launch_at"] = now.isoformat(timespec="seconds")
            sch["last_launch_by"] = by
            sch["last_launch_target"] = target
            sch["last_error"] = None
            if sch.get("enabled") and by == "auto":
                # 이번 예약을 썼으니 다음 예약 시각으로 넘긴다.
                # 수동 실행은 예약을 건드리지 않는다 (정해진 시각에는 정해진 대로 돈다).
                advance(sch, now)
            st.write_settings(cfg)
    return path


def launch_run_all(by):
    return launch("all", by)


# ---------------------------------------------------------------------------
# 자동 실행 예약 (2026-10-07 시각별 모듈, 설계 2026-10-06-settings-schedule 5절)
#   schedule = {enabled, days(월=0, 모든 줄이 같이 씀), slots:[{at, run?}], next_run_at, next_slot, policy?, last_*}
#   run 이 없는 줄은 '전체' (쇼핑몰 받기 + 실행 모듈 카드), 있으면 그 모듈만 - 띄울 때 RPA_RUN_MODULES 로 넘긴다
# ---------------------------------------------------------------------------
ROUTINE_KEYS = tuple(k for k, _ in st.ROUTINE_CONFIG_MODULES)      # Login, Sales, Hold, Logistics, Output
RUN_KEYS = ("Prepare",) + ROUTINE_KEYS                             # 줄의 run 에 쓰는 키. 이 순서로 저장한다
SLOT_NAMES = {"Prepare": "쇼핑몰 받기", "Sales": "주문매핑", "Hold": "물류대기", "Logistics": "물류관리", "Output": "운송장"}   # 화면 단추와 같은 말
REST_MIN_DEFAULT = 2
REST_MIN_RANGE = (1, 60)   # 반복 시간대 쉬는 시간 (분)


def normalize_days(days):
    """요일 목록 [0..6] (월=0) 을 검증해 중복 없이 정렬한다. 틀리면 ValueError."""
    if not isinstance(days, list) or not days:
        raise ValueError("요일을 하나 이상 고르세요")
    out = set()
    for v in days:
        if not isinstance(v, int) or isinstance(v, bool) or not 0 <= v <= 6:
            raise ValueError("요일 값이 잘못되었습니다")
        out.add(v)
    return sorted(out)


def _check_time(t):
    """"HH:MM" 5분 단위 → 고친 글. 틀리면 ValueError (사람에게 보일 글)."""
    if not isinstance(t, str) or len(t) != 5 or t[2] != ":" or not (t[:2] + t[3:]).isdigit():
        raise ValueError(f"시간 형식이 잘못되었습니다: {t!r}")
    hh, mm = int(t[:2]), int(t[3:])
    if hh > 23 or mm > 59 or mm % st.SCHEDULE_MINUTE_STEP:
        raise ValueError(f"시간은 00:00~23:55 사이 {st.SCHEDULE_MINUTE_STEP}분 단위여야 합니다: {t}")
    return f"{hh:02d}:{mm:02d}"


def normalize_times(times):
    """옛 모양의 시각 목록 ["HH:MM", ...] (옛 8765 화면·옛 웹이 보낸다) 을 검증해 중복 없이 정렬한다."""
    if not isinstance(times, list) or not times:
        raise ValueError("실행 시간을 하나 이상 넣으세요")
    out = sorted({_check_time(t) for t in times})
    if len(out) > st.SCHEDULE_MAX_SLOTS:
        raise ValueError(f"실행 시간은 {st.SCHEDULE_MAX_SLOTS}개까지 넣을 수 있습니다")
    return out


def normalize_run(run):
    """줄의 run (돌릴 모듈 키 목록). None 이면 '전체'. 고친 목록 (RUN_KEYS 순서). 틀리면 ValueError."""
    if run is None:
        return None
    if not isinstance(run, list) or not all(isinstance(k, str) for k in run):
        raise ValueError("모듈 목록이 잘못되었습니다")
    bad = [k for k in run if k not in RUN_KEYS]
    if bad:
        raise ValueError(f"모르는 모듈입니다: {', '.join(bad)}")
    if len(set(run)) != len(run):
        raise ValueError("같은 모듈이 두 번 있습니다")
    picked = set(run)
    if picked & {k for k in ROUTINE_KEYS if k != "Login"}:
        picked.add("Login")          # 루틴을 돌리면 로그인은 늘 (실행 모듈 카드처럼 못 끈다)
    else:
        picked.discard("Login")      # 루틴 모듈이 없으면 로그인만 돌릴 까닭이 없다
    if "Output" in picked and "Logistics" not in picked:
        raise ValueError("운송장 출력은 물류관리와 같이 골라야 합니다")
    if not picked:
        raise ValueError("모듈을 하나 이상 고르세요")
    return [k for k in RUN_KEYS if k in picked]


def normalize_slots(slots):
    """줄 목록 검사 → 시각 순으로 정렬한 새 목록. 틀리면 ValueError (사람에게 보일 글)."""
    if not isinstance(slots, list) or not slots:
        raise ValueError("실행 시간을 하나 이상 넣으세요")
    if len(slots) > st.SCHEDULE_MAX_SLOTS:
        raise ValueError(f"자동 실행은 {st.SCHEDULE_MAX_SLOTS}개까지 넣을 수 있습니다")
    out = []
    for s in slots:
        if not isinstance(s, dict):
            raise ValueError("자동 실행 줄이 잘못되었습니다")
        item = {"at": _check_time(s.get("at"))}
        run = normalize_run(s.get("run"))
        if s.get("until") is not None:                 # 반복 시간대 (설계 6-1)
            item["until"] = _check_time(s.get("until"))
            if item["until"] <= item["at"]:
                raise ValueError(f"반복 끝 시각은 시작({item['at']})보다 늦어야 합니다")
            rest = s.get("rest_min", REST_MIN_DEFAULT)
            if not isinstance(rest, int) or isinstance(rest, bool) or not REST_MIN_RANGE[0] <= rest <= REST_MIN_RANGE[1]:
                raise ValueError("쉬는 시간은 1~60분 정수여야 합니다")
            if s.get("on_fail", "stop") != "stop":
                raise ValueError("실패하면 '멈춤' 만 됩니다")
            if run is None:
                raise ValueError("반복에는 '전체' 를 쓸 수 없습니다 - 모듈을 고르세요")
            if "Prepare" in run:
                raise ValueError("반복에는 쇼핑몰 받기를 넣을 수 없습니다")
            item.update(rest_min=rest, on_fail="stop")
        if run is not None:
            item["run"] = run
        out.append(item)
    out.sort(key=lambda x: x["at"])
    for w in (x for x in out if "until" in x):
        for x in out:
            if x is w:
                continue
            if "until" in x and x["at"] < w["until"] and w["at"] < x["until"]:
                raise ValueError(f"반복 시간대가 겹칩니다: {w['at']}~{w['until']}, {x['at']}~{x['until']}")
            if "until" not in x and w["at"] <= x["at"] < w["until"]:
                raise ValueError(f"{w['at']}~{w['until']} 반복 안에는 시각을 넣을 수 없습니다")
    ats = [x["at"] for x in out]
    dup = sorted({a for a in ats if ats.count(a) > 1})
    if dup:
        raise ValueError(f"같은 시각이 두 번 있습니다: {', '.join(dup)}")
    return out


def next_slot(days, times, after):
    """after 보다 뒤인 가장 가까운 예약 시각. 요일·시간이 비었거나 틀리면 None."""
    try:
        days = normalize_days(days)
        times = normalize_times(times)
    except ValueError:
        return None
    for offset in range(8):   # 오늘 포함 8일이면 어떤 요일 조합이든 한 번은 걸린다
        day = after.date() + datetime.timedelta(days=offset)
        if day.weekday() not in days:
            continue
        for t in times:
            cand = datetime.datetime.combine(day, datetime.time(int(t[:2]), int(t[3:])))
            if cand > after:
                return cand
    return None


def sorted_slots(sch):
    """적힌 줄 (시각 순). 잘못 적힌 줄은 건너뛴다."""
    return sorted((s for s in sch.get("slots") or [] if isinstance(s, dict) and isinstance(s.get("at"), str)),
                  key=lambda s: s["at"])


def active_slots(sch):
    """도는 줄 (시각 순). 업체 한도(policy.limit - 에이전트가 적는다)를 넘는 줄은 뺀다: 시각 순으로 앞 N줄만 (설계 5-3).
    한도를 모르면 (에이전트가 한 번도 못 읽었으면) 자르지 않는다 - PC 상한 12 는 저장할 때 지킨다."""
    out = sorted_slots(sch)
    limit = (sch.get("policy") or {}).get("limit")
    if isinstance(limit, int) and not isinstance(limit, bool) and limit >= 0:
        return out[:limit]
    return out


def set_policy(limit, off):
    """에이전트가 읽은 업체 정책(자동 실행 개수·안 쓰는 모듈)을 settings.json 에 적는다 - 껐다 켜도·끊겨도 마지막 값.
    같으면 안 쓴다 (False). 다음 줄을 다시 잡는다 - 한도를 올리면 새로 들어온 줄이 그날부터 돌게, 가리키던 줄이 빠졌으면 다음 줄로.
    때가 됐는데 아직 못 띄운 줄(바쁨)은 그대로 둔다. 다른 칸(줄·반복 상태)은 그대로."""
    new = {"limit": limit, "off": sorted(off)}
    with _settings_lock:
        cfg = st.read_settings()
        sch = cfg["schedule"]
        old = sch.get("policy") or {}
        if (old.get("limit"), old.get("off")) == (new["limit"], new["off"]):
            return False
        sch["policy"] = dict(new, read_at=now_text())
        due = st.parse_iso(sch.get("next_run_at"))
        if due is None or due > NOW() or sch.get("next_slot") not in [s["at"] for s in active_slots(sch)]:
            advance(sch, NOW())
        st.write_settings(cfg)
        return True


def next_due(sch, after):
    """after 뒤 가장 가까운 예약 (시각, 그 줄). 없으면 (None, None)."""
    slots = active_slots(sch)
    when = next_slot(sch.get("days"), [s["at"] for s in slots], after)
    if when is None:
        return None, None
    at = when.strftime("%H:%M")
    return when, next(s for s in slots if s["at"] == at)


def advance(sch, now):
    """다음 예약 (next_run_at·next_slot) 을 now 뒤로 잡는다. 꺼져 있으면 비운다."""
    when, slot = next_due(sch, now) if sch.get("enabled") else (None, None)
    sch["next_run_at"] = when.isoformat(timespec="seconds") if when else None
    sch["next_slot"] = slot["at"] if slot else None


def next_run_iso(sch, after):
    when, _ = next_due(sch, after)
    return when.isoformat(timespec="seconds") if when else None


def slot_of(sch):
    """next_run_at 이 가리키는 줄 (next_slot, 없으면 next_run_at 의 시각으로 찾는다). 도는 줄에 없으면 None."""
    at = sch.get("next_slot") or (sch.get("next_run_at") or "")[11:16]
    return next((s for s in active_slots(sch) if s["at"] == at), None)


def slot_target(slot, off=()):
    """줄 하나 → (띄울 target, 자식 환경). '전체' 줄은 ('all', {}). 업체가 안 쓰는 모듈(off)을 빼고 나서 돌릴 게 없으면 (None, {})."""
    run = slot.get("run")
    if run is None:
        return "all", {}
    keys = [k for k in run if k not in set(off)]
    routine = [k for k in keys if k in ROUTINE_KEYS]
    if "Output" in routine and "Logistics" not in routine:
        routine.remove("Output")            # 물류관리가 빠지면 출력도 (루틴과 같은 규칙)
    if not set(routine) - {"Login"}:
        routine = []                         # 로그인만 남으면 루틴은 안 돈다
    prepare = "Prepare" in keys
    if not routine:
        return ("prepare", {}) if prepare else (None, {})
    return ("all" if prepare else "routine"), {"RPA_RUN_MODULES": ",".join(routine)}


def launch_slot(slot, by="auto", trigger="auto"):
    """예약 줄 하나를 띄운다. 업체가 안 쓰는 모듈만 남으면 RuntimeError (사람에게 보일 글 - 예약 칸의 까닭이 된다)."""
    off = (st.read_settings()["schedule"].get("policy") or {}).get("off") or []
    target, env = slot_target(slot, off)
    if target is None:
        raise RuntimeError("업체가 쓰지 않는 모듈만 남아 건너뜁니다")
    return launch(target, by, dict(env, RPA_RUN_TRIGGER=trigger))


def open_window(sch, now):
    """지금 열려 있는 반복 시간대 (그날 요일 + 시작 ≤ 지금 < 끝, 한도 안의 줄). 없으면 None."""
    if not sch.get("enabled") or now.weekday() not in (sch.get("days") or []):
        return None
    hm = now.strftime("%H:%M")
    return next((s for s in active_slots(sch) if s.get("until") and s["at"] <= hm < s["until"]), None)


def last_finished():
    """루틴·프리페어 상태 파일에서 가장 늦게 끝난 시각 (누가 띄웠든). 쉬는 시간은 여기서부터 센다 (설계 6-2)."""
    ends = []
    for program in st.PROGRAMS:
        v = st.read_json(st.status_path(program)) or {}
        t = st.parse_iso(v.get("finished_at")) if v.get("state") != "running" else None
        if t is not None:
            ends.append(t)
    return max(ends) if ends else None


def processed(status):
    """반복 회차가 처리한 게 있나 - 로그인 말고 '완료' 로 끝난 모듈 (대상 없음은 처리가 아니다)."""
    return any(m.get("state") == "done" and m.get("key") != "login" for m in status.get("modules") or [])


def stop_reason(status):
    """멈춘 회차의 까닭 한 줄: '10:23 물류관리 실패로 반복을 멈췄습니다: <사유>'."""
    bad = next((m for m in status.get("modules") or [] if m.get("state") in ("failed", "stopped")), None) or {}
    word = "오류" if status.get("state") == "crashed" else "실패"
    why = status.get("reason") or bad.get("reason") or "까닭 없음"
    return f"{(status.get('finished_at') or '')[11:16]} {bad.get('label') or '루틴'} {word}로 반복을 멈췄습니다: {why}".strip()


def repeat_state(sch, win, now):
    """오늘 열린 시간대 win 의 상태 (sch["repeat"]). 날이 바뀌었거나 다른 시간대면 새로 만든다. (상태, 새로 만들었나)
    지난 시간대에 띄운 회차가 아직 안 끝났으면(pending) 이어서 기다린다."""
    rep = sch.get("repeat")
    key = (now.date().isoformat(), win["at"], win["until"])
    if isinstance(rep, dict) and (rep.get("date"), rep.get("at"), rep.get("until")) == key:
        return rep, False
    rep = {"date": key[0], "at": key[1], "until": key[2], "runs": 0, "done": 0, "stopped": None,
           "pending": rep.get("pending") if isinstance(rep, dict) else None, "last_launch_at": None, "next_at": None}
    sch["repeat"] = rep
    return rep, True


def launched_in(rep, since):
    """since(띄운 때) 가 rep 의 시간대 안인가. 붙은 시간대로 넘어온 회차(repeat_state 가 pending 을 잇는다)는 아니다."""
    return rep.get("date") == since.date().isoformat() and (rep.get("at") or "") <= since.strftime("%H:%M") < (rep.get("until") or "")


def resume_repeat():
    """[반복 다시 시작] (명령 resume_repeat). 열린 시간대의 멈춤을 풀어 바로 다음 회차. 멈춘 반복이 없으면 RuntimeError."""
    now = NOW()
    with _settings_lock:
        cfg = st.read_settings()
        sch = cfg["schedule"]
        win = open_window(sch, now)
        rep = sch.get("repeat") or {}
        if win is None or not rep.get("stopped") or (rep.get("date"), rep.get("at")) != (now.date().isoformat(), win["at"]):
            raise RuntimeError("지금은 멈춘 반복이 없습니다")
        rep.update(stopped=None, next_at=None, resumed_at=now.isoformat(timespec="seconds"))   # 쉬는 시간을 안 기다리고 바로 (tick_repeat)
        st.write_settings(cfg)
    return f"반복을 다시 시작했습니다 ({win['until']}까지)"


def days_label(days):
    picked = sorted(set(v for v in (days or []) if isinstance(v, int) and 0 <= v <= 6))
    if picked == list(range(7)):
        return "매일"
    if picked == [0, 1, 2, 3, 4]:
        return "평일"
    if picked == [5, 6]:
        return "주말"
    return "·".join(WEEKDAY_NAMES[v] for v in picked) or "요일 없음"


def slot_text(s):
    """줄 한 칸 글: '10:00' / '11:00 물류관리' / '11:00~12:00 반복 물류관리' (로그인은 안 적는다)."""
    head = f"{s['at']}~{s['until']} 반복" if s.get("until") else s["at"]
    if s.get("run") is None:
        return head
    return f"{head} {'·'.join(SLOT_NAMES[k] for k in s['run'] if k != 'Login')}".strip()


def schedule_label(sch):
    """'평일 09:00, 11:00 물류관리' 처럼 한 줄로. 줄이 많으면 앞 3개만."""
    parts = [slot_text(s) for s in sorted_slots(sch)]
    shown = ", ".join(parts[:3]) + (f" 외 {len(parts) - 3}개" if len(parts) > 3 else "")
    return f"{days_label(sch.get('days'))} {shown}".strip()


class Scheduler(threading.Thread):
    """settings.json 의 schedule (요일 + 줄) 대로 띄운다. 줄마다 무엇을 띄울지는 slot_target.

    - 이 프로그램(에이전트)이 떠 있는 동안만 돈다.
    - 꺼져 있던 동안 지난 예약은 켤 때 건너뛴다 (resync). 켜자마자 갑자기 돌지 않게.
    - RPA 가 이미 돌고 있으면 끝날 때까지 미룬다 (건너뛰지 않는다). 그 사이 지난 예약들은 한 번으로 합쳐진다.
    - 옵저버가 떠 있어도 닫힐 때까지 미룬다 (기록하던 사람과 RPA 가 화면·마우스를 두고 부딪히지 않게).
    - 띄운 뒤에는 다음 예약으로 옮긴다 (advance).
    """

    def __init__(self):
        super().__init__(name="rpa-scheduler", daemon=True)
        self.stop = threading.Event()
        self.waiting_reason = None
        self.skipped_at = None   # resync 가 건너뛴 예약 시각 (시작 안내용)

    def resync(self):
        """저장된 다음 실행 시각이 오래전에 지났으면 지금 이후의 예약으로 다시 잡는다."""
        with _settings_lock:
            cfg = st.read_settings()
            sch = cfg["schedule"]
            if not sch.get("enabled"):
                return
            now = NOW()
            nxt = st.parse_iso(sch.get("next_run_at"))
            if nxt is not None and (now - nxt).total_seconds() <= MISSED_GRACE_SEC:
                return
            if nxt is not None:
                self.skipped_at = nxt
            advance(sch, now)
            st.write_settings(cfg)

    def run(self):
        while not self.stop.wait(SCHEDULER_TICK):
            self.tick_safe()

    def tick_safe(self):
        try:
            self.tick()
        except RuntimeError as e:          # launch 의 거절 (토큰이 없음 등) - 사람에게 보일 글 그대로
            self._record_error(str(e))
        except Exception as e:
            self._record_error(f"{type(e).__name__}: {e}")

    def _record_error(self, text):
        with _settings_lock:
            cfg = st.read_settings()
            sch = cfg["schedule"]
            sch["last_error"] = text
            advance(sch, NOW())             # 같은 오류로 5초마다 되풀이하지 않게 다음 예약으로
            st.write_settings(cfg)

    def _advance_now(self, now):
        with _settings_lock:
            cfg = st.read_settings()
            advance(cfg["schedule"], now)
            st.write_settings(cfg)
        return cfg["schedule"]

    def busy(self):
        """지금 띄우면 안 되는 까닭 (없으면 None)."""
        if any_rpa_running():
            return "RPA 가 아직 돌고 있어 끝나기를 기다립니다"
        if launch_state() is not None:
            return "대시보드가 띄운 실행이 끝나기를 기다립니다"
        if st.observer_open():
            return "옵저버가 켜져 있어 닫히기를 기다립니다"
        return None

    def tick(self):
        now = NOW()
        self.check_repeat_result(now)            # 띄운 반복 회차가 끝났으면 센다 (시간대가 끝났어도, 자동 실행을 껐어도)
        sch = st.read_settings()["schedule"]
        if not sch.get("enabled"):
            self.waiting_reason = None
            return
        next_run = st.parse_iso(sch.get("next_run_at"))
        if next_run is None:
            if not self._advance_now(now)["next_run_at"]:
                self.waiting_reason = "요일·시간 설정이 비어 있습니다"
                return
        elif now >= next_run:
            slot = slot_of(sch)
            if slot is not None and not slot.get("until"):
                self.waiting_reason = self.busy()
                if self.waiting_reason is None:
                    self.launch(slot)
                return
            self._advance_now(now)               # 가리키던 줄이 없어졌거나 반복 시간대 - 다음 줄로 (시간대는 아래 반복이 맡는다)
        win = open_window(st.read_settings()["schedule"], now)
        if win is None:
            self.waiting_reason = None
            return
        self.tick_repeat(win, now)

    def tick_repeat(self, win, now):
        """열린 반복 시간대: 멈췄거나 띄운 회차가 아직이면 기다리고, 쉬는 시간이 지났으면 다음 회차를 띄운다."""
        with _settings_lock:
            cfg = st.read_settings()
            rep, new = repeat_state(cfg["schedule"], win, now)
            if new:
                st.write_settings(cfg)
        if rep.get("stopped"):
            self.waiting_reason = "반복을 멈췄습니다 - [반복 다시 시작] 을 누르면 이어 돕니다"
            return
        if rep.get("pending"):
            self.waiting_reason = "반복 회차가 끝나기를 기다립니다"
            return
        end = last_finished()
        resumed = st.parse_iso(rep.get("resumed_at"))       # [반복 다시 시작] 뒤 첫 회차는 쉬지 않는다 - 그 회차가 끝나면 다시 쉰다
        if end is not None and (resumed is None or resumed < end) and now < end + datetime.timedelta(minutes=win.get("rest_min", REST_MIN_DEFAULT)):
            self.waiting_reason = None
            return
        self.waiting_reason = self.busy()
        if self.waiting_reason is not None:
            return
        stamp = now.isoformat(timespec="seconds")
        try:
            launch_slot(win, trigger="repeat")
        except Exception as e:                   # 토큰이 없음·업체가 안 쓰는 모듈만·exe 없음 - 넘기지 않고 멈춘다 (5초마다 다시 띄우지 않게)
            self.mark_repeat(stopped={"at": stamp, "reason": f"{now:%H:%M} {e or type(e).__name__}"})
            return
        self.mark_repeat(pending=stamp, last_launch_at=stamp)

    def check_repeat_result(self, now):
        """띄운 반복 회차가 끝났으면 센다. 성공 → 회차 +1 (처리했으면 처리 +1), 실패·중단·오류 → 그 시간대 반복 멈춤 + 까닭."""
        since = st.parse_iso((st.read_settings()["schedule"].get("repeat") or {}).get("pending"))
        if since is None or launch_state() is not None:
            return
        v = st.read_json(st.status_path("routine")) or {}
        if v.get("state") == "running":
            return
        started = st.parse_iso(v.get("started_at"))
        fresh = started is not None and started >= since
        if not fresh and now < since + datetime.timedelta(seconds=LAUNCH_GRACE_SEC):
            return                               # 띄운 프로그램이 아직 기록 전일 수 있다 (에이전트를 다시 켜 손잡이를 잃은 직후 등)
        with _settings_lock:
            cfg = st.read_settings()
            sch = cfg["schedule"]
            rep = sch.get("repeat")
            if not isinstance(rep, dict) or rep.get("pending") is None:
                return
            rep["pending"] = None
            stamp = now.isoformat(timespec="seconds")
            if not fresh:                        # 띄운 회차가 기록도 못 남기고 끝났다 ('시작하지 못함' 이력은 launch_state 가 남긴다)
                rep["stopped"] = {"at": stamp, "reason": f"{now:%H:%M} 반복 회차가 시작하지 못했습니다"}
            elif not launched_in(rep, since):
                pass                             # 앞 시간대에 띄운 회차가 붙은 시간대가 열린 뒤 끝났다 - 이 시간대 회차가 아니니 세지도 멈추지도 않는다
            elif v.get("trigger") != "repeat":
                pass                             # 다른 실행(사람이 누른 단추 등)이 상태를 덮었다 - 회차 결과를 모르니 세지도 멈추지도 않는다
            elif v.get("state") == "success":
                rep["runs"] = int(rep.get("runs") or 0) + 1
                rep["done"] = int(rep.get("done") or 0) + (1 if processed(v) else 0)
                rest = next((s.get("rest_min", REST_MIN_DEFAULT) for s in active_slots(sch)
                             if s.get("until") and s["at"] == rep.get("at")), REST_MIN_DEFAULT)
                end = st.parse_iso(v.get("finished_at")) or now
                rep["next_at"] = (end + datetime.timedelta(minutes=rest)).isoformat(timespec="seconds")
            else:
                rep["stopped"] = {"at": stamp, "reason": stop_reason(v)}
            st.write_settings(cfg)

    def mark_repeat(self, **fields):
        with _settings_lock:
            cfg = st.read_settings()
            rep = cfg["schedule"].get("repeat")
            if isinstance(rep, dict):
                rep.update(fields)
                st.write_settings(cfg)

    def launch(self, slot):
        launch_slot(slot)


SCHEDULER = Scheduler()


def schedule_view():
    sch = st.read_settings()["schedule"]
    now = NOW()
    nxt = st.parse_iso(sch.get("next_run_at")) if sch.get("enabled") else None
    slots = sorted_slots(sch)
    return {
        "version": st.SCHEDULE_VERSION,
        "enabled": bool(sch.get("enabled")),
        "days": list(sch.get("days") or []),
        "slots": slots,
        "times": [s["at"] for s in slots if not s.get("until")],   # 옛 8765 화면 (dashboard.html) 은 시각 목록만 안다
        "label": schedule_label(sch),
        "next_run_at": nxt.isoformat(timespec="seconds") if nxt else None,
        "next_slot": sch.get("next_slot") if nxt else None,
        "next_run_in_sec": max(0, int((nxt - now).total_seconds())) if nxt else None,
        "policy": sch.get("policy"),
        "repeat": sch.get("repeat"),
        "last_launch_at": sch.get("last_launch_at"),
        "last_launch_by": sch.get("last_launch_by"),
        "last_error": sch.get("last_error"),
        "waiting_reason": SCHEDULER.waiting_reason,
        "last_launch_target": sch.get("last_launch_target"),
        "launch": launch_state(),            # 대시보드가 띄운 실행이 살아 있으면 {target, by, sec}
        "launching_sec": launching_sec(),    # 살아 있는데 아직 기록이 없으면 몇 초째
    }


def apply_schedule(payload):
    """'적용'. 요일·줄을 검증해 저장하고, 바뀐 것이 있으면 다음 시각을 다시 잡는다.
    payload: {enabled, days, slots} - 옛 화면(8765·옛 웹)이 보내는 {enabled, days, times} 도 받는다 (모두 '전체' 줄).
    끌 때는 요일·줄이 비어도 된다."""
    if not isinstance(payload, dict):
        raise ValueError("잘못된 요청입니다")
    enabled = payload.get("enabled")
    if not isinstance(enabled, bool):
        raise ValueError("enabled 는 true/false 여야 합니다")
    raw_days = payload.get("days")
    days = [] if not enabled and raw_days in (None, []) else normalize_days(raw_days)
    raw = payload.get("slots") if "slots" in payload else payload.get("times")
    if not enabled and raw in (None, []):
        slots = []
    elif "slots" in payload:
        slots = normalize_slots(raw)
    else:
        slots = [{"at": t} for t in normalize_times(raw)]
    with _settings_lock:
        cfg = st.read_settings()
        sch = cfg["schedule"]
        changed = bool(sch.get("enabled")) != enabled or sch.get("days") != days or sch.get("slots") != slots
        sch.pop("interval_min", None)   # 예전 '실행 주기' 방식의 값
        sch.update(enabled=enabled, days=days, slots=slots)
        if changed:
            sch["last_error"] = None
            advance(sch, NOW())
        if not st.write_settings(cfg):
            raise RuntimeError("설정 파일을 쓰지 못했습니다")
    return changed


def routine_modules_view():
    """환경설정 화면의 '실행 모듈'. 사용자 설정(RPA_UserConfig.json)의 Routine 섹션만 읽는다.

    그 파일에는 ERPia 비밀번호가 있다. 여기서 나가는 것은 모듈 켬/끔뿐이어야 한다.
    enabled 가 None 이면 파일의 값이 Y/N 이 아니라는 뜻 (루틴은 그런 값이면 돌지 않는다).
    """
    selected, problems = st.read_routine_modules()
    return {"items": [{"key": k, "label": label, "enabled": selected.get(k)}
                      for k, label in st.ROUTINE_CONFIG_MODULES],
            "problems": problems,
            "file": os.path.basename(st.user_config_path())}


def _wanted_routine_modules(payload, before):
    """지금 값(before) 위에 요청(payload)을 얹은 최종 {키: bool}. 빠진 키는 지금 값(잘못된 값이면 켬)."""
    keys = [k for k, _ in st.ROUTINE_CONFIG_MODULES]
    wanted = {}
    for k in keys:
        cur = before.get(k)
        wanted[k] = bool(payload.get(k, True if cur is None else cur))
    return wanted


def validate_routine_modules(payload):
    """실행 모듈 요청을 검증만 한다 (파일은 안 건드린다). 자동 실행 저장 **앞에** 불러 반쪽 저장을 막는다."""
    if not isinstance(payload, dict):
        raise ValueError("실행 모듈 값이 잘못되었습니다")
    keys = [k for k, _ in st.ROUTINE_CONFIG_MODULES]
    unknown = sorted(set(payload) - set(keys))
    if unknown:
        raise ValueError(f"모르는 모듈: {', '.join(unknown)}")
    for k, v in payload.items():
        if not isinstance(v, bool):
            raise ValueError(f"{k} 는 true/false 여야 합니다")
    before, _ = st.read_routine_modules()
    if not any(_wanted_routine_modules(payload, before).values()):
        raise ValueError("최소 한 모듈은 켜야 합니다")
    return payload


def apply_routine_modules(payload):
    """환경설정 화면의 '적용' - 실행 모듈. {설정 키: true/false} 를 검증해 사용자 설정에 쓴다.

    바뀐 것이 있으면 True. 빠진 키는 지금 값(잘못된 값이면 켬)을 유지한다. 전부 끄는 것은 거절한다.
    파일을 못 쓰면 RuntimeError - 메시지에 파일 내용은 절대 싣지 않는다.
    """
    validate_routine_modules(payload)
    keys = [k for k, _ in st.ROUTINE_CONFIG_MODULES]
    with _settings_lock:
        before, _ = st.read_routine_modules()
        wanted = _wanted_routine_modules(payload, before)
        if not any(wanted.values()):
            raise ValueError("최소 한 모듈은 켜야 합니다")
        changed = any(before.get(k) != wanted[k] for k in keys)
        if changed:
            try:
                st.write_routine_modules(wanted)
            except Exception as e:
                raise RuntimeError(f"실행 모듈 설정을 쓰지 못했습니다 ({type(e).__name__})") from e
    return changed


def stop_erpia():
    """ERPia 를 종료한다 (ERPia 는 종료가 곧 로그아웃). RPA 가 도는 중이면 거절한다."""
    running = any_rpa_running()
    if running:
        names = ", ".join(st.PROGRAMS.get(p, p) for p in running)
        return 409, {"ok": False, "error": f"{names} 가 진행 중입니다. 끝난 뒤에 다시 하세요."}
    if launch_state():
        return 409, {"ok": False, "error": "대시보드가 띄운 실행이 아직 진행 중입니다. 끝난 뒤에 다시 하세요."}
    pids = find_pids(ERPIA_EXE)
    if not pids:
        return 200, {"ok": True, "killed": 0, "message": "ERPia 가 이미 꺼져 있습니다."}
    errors = [e for e in (terminate_pid(p) for p in pids) if e]
    if errors:
        return 500, {"ok": False, "error": errors[0]}
    return 200, {"ok": True, "killed": len(pids), "message": f"ERPia 를 종료했습니다 ({len(pids)}개)."}


# ---------------------------------------------------------------------------
# 이력 요약
# ---------------------------------------------------------------------------
def run_summary(rec):
    """이력 목록용 요약. 로그와 단계 목록은 빼서 가볍게 보낸다."""
    steps = rec.get("steps") or []
    last = next((s for s in reversed(steps)
                 if s.get("state") in ("running", "stopped", "failed", "done")), None)
    out = {k: rec.get(k) for k in ("run_id", "program", "program_label", "host", "account", "state",
                                   "reason", "started_at", "finished_at", "duration_sec",
                                   "metrics")}
    # 설정에서 끈 모듈의 단계는 '할 일' 이 아니다 (현황 링과 같은 계산 - rpa_status.decorate)
    counted = [s for s in steps if not (s.get("state") == "skipped" and s.get("note") in st.OFF_NOTES)]
    out["steps_total"] = len(counted)
    out["steps_done"] = sum(1 for s in counted if s.get("state") in ("done", "skipped"))
    out["last_step"] = last.get("label") if last else None
    out["module_flags"] = rec.get("module_flags")
    out["modules"] = [{"key": m.get("key"), "state": m.get("state")}
                      for m in rec.get("modules") or [] if isinstance(m, dict)]
    return out


def history_stats(rows):
    """실행 횟수, 결과별 횟수, 프로그램별 평균 소요.

    평균 소요는 반드시 프로그램별로 따로 낸다. 프리페어(수십 초)와 루틴(수 분)을
    섞어 평균을 내면 어느 쪽에도 맞지 않는 숫자가 된다.
    """
    counts = {"success": 0, "stopped": 0, "crashed": 0}
    durations = {}
    for r in rows:
        state = r.get("state")
        if state in counts:
            counts[state] += 1
        if state == "success" and isinstance(r.get("duration_sec"), (int, float)):
            # 모듈을 끈 실행은 소요가 다르므로 평균에서 뺀다 (모듈 기록이 없는 옛 이력은 전체 실행으로 본다)
            partial = any(isinstance(m, dict) and m.get("state") == "off" for m in r.get("modules") or [])
            if not partial:
                durations.setdefault(r.get("program"), []).append(r["duration_sec"])
    return {
        "total": len(rows),
        **counts,
        "avg_success_sec": {p: int(sum(v) / len(v)) for p, v in durations.items()},
    }


def _int_arg(query, name, default, low, high):
    try:
        return max(low, min(high, int(query.get(name, [default])[0])))
    except (TypeError, ValueError):
        return default


_account_cache = {"at": 0.0, "value": None}


def erpia_account_view():
    """RPA 가 ERPia 에 로그인할 때 쓰는 계정 (사용자 설정의 LogIn, 비밀번호 제외)."""
    now = time.time()
    if now - _account_cache["at"] > ACCOUNT_CACHE_SEC:
        _account_cache["value"] = st.read_account()
        _account_cache["at"] = now
    return _account_cache["value"]


def me_view(session):
    return {"user_id": session["user_id"], "role": session["role"],
            "role_label": ROLE_LABEL.get(session["role"], session["role"]),
            "admin_code": session["admin_code"], "is_admin": session["role"] == "admin"}


def status_view():
    snap = st.dashboard_snapshot()
    snap["erpia_account"] = erpia_account_view()
    snap["erpia_running"] = erpia_running()
    snap["is_admin"] = is_admin()
    snap["schedule"] = schedule_view()
    snap["page_version"] = page_html()[1]
    return snap


def settings_view(session):
    bat = run_command_path()
    acc = find_account(session["user_id"]) or {}
    return {
        "schedule": schedule_view(),
        "run_command": bat,
        "run_command_exists": os.path.isfile(bat),
        "targets": {k: {"label": v[0], "file": v[1], "exists": os.path.isfile(target_path(k))} for k, v in TARGETS.items()},
        "is_admin": is_admin(),
        "erpia_running": erpia_running(),
        "rpa_running": any_rpa_running(),
        "erpia_account": erpia_account_view(),
        "me": dict(me_view(session), default_password=bool(acc.get("default_password"))),
        "schedule_limits": {"max_times": st.SCHEDULE_MAX_SLOTS, "minute_step": st.SCHEDULE_MINUTE_STEP},
        "routine_modules": routine_modules_view(),
    }


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "RPA-Dashboard/1.2"
    sys_version = ""

    def log_message(self, fmt, *args):
        return   # 폴링 요청이 2초마다 오므로 창을 어지럽히지 않는다

    def _send(self, code, body, ctype, extra=None):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _json(self, obj, code=200, extra=None):
        self._send(code, json.dumps(obj, ensure_ascii=False),
                   "application/json; charset=utf-8", extra)

    def _cookie_token(self):
        raw = self.headers.get("Cookie")
        if not raw:
            return None
        try:
            c = http.cookies.SimpleCookie()
            c.load(raw)
            return c[SESSION_COOKIE].value if SESSION_COOKIE in c else None
        except Exception:
            return None

    @staticmethod
    def _set_cookie(token, clear=False):
        base = f"{SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict"
        return {"Set-Cookie": base + ("; Max-Age=0" if clear else "")}

    def _session(self):
        return SESSIONS.get(self._cookie_token())

    def _require(self, admin=False):
        """로그인(및 관리자) 확인. 통과하면 세션, 아니면 응답을 보내고 None."""
        s = self._session()
        if s is None:
            self._json({"ok": False, "error": "로그인이 필요합니다", "login": True}, 401)
            return None
        if admin and s["role"] != "admin":
            self._json({"ok": False, "error": "관리자만 할 수 있습니다"}, 403)
            return None
        return s

    def _read_body(self):
        """화면의 fetch 만 받는다. 머리글이 없거나 JSON 이 아니면 거절한다."""
        if self.headers.get(ACTION_HEADER) != "1":
            return None, (403, {"ok": False, "error": "허용되지 않은 요청입니다"})
        length = int(self.headers.get("Content-Length") or 0)
        if length < 0 or length > MAX_BODY:
            return None, (413, {"ok": False, "error": "요청이 너무 큽니다"})
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except ValueError:
            return None, (400, {"ok": False, "error": "JSON 이 아닙니다"})
        if not isinstance(body, dict):
            return None, (400, {"ok": False, "error": "JSON 객체가 아닙니다"})
        return body, None

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        try:
            parts = urllib.parse.urlsplit(self.path)
            query = urllib.parse.parse_qs(parts.query)
            path = parts.path

            if path in ("/", "/index.html"):
                html, _ = page_html()
                self._send(200, html, "text/html; charset=utf-8",
                           {"Content-Security-Policy": HTML_CSP})
                return
            if path == "/healthz":
                self._send(200, SIGNATURE, "text/plain; charset=utf-8")
                return

            if path == "/api/me":
                s = self._session()
                if s is None:
                    self._json({"ok": False, "login": True}, 401)
                else:
                    self._json(dict(me_view(s), ok=True))
                return

            s = self._require()
            if s is None:
                return

            if path == "/api/status":
                self._json(status_view())

            elif path == "/api/settings":
                self._json(settings_view(s))

            elif path == "/api/history":
                program = query.get("program", [None])[0]
                if program not in st.PROGRAMS:
                    program = None
                period = query.get("period", ["7"])[0]
                if period not in PERIODS:
                    period = "7"
                limit = _int_arg(query, "limit", 300, 1, 2000)
                rows = st.read_history(program=program, since=period_since(period))
                self._json({"summary": history_stats(rows),
                            "runs": [run_summary(r) for r in rows[:limit]]})

            elif path.startswith("/api/history/"):
                run_id = urllib.parse.unquote(path[len("/api/history/"):])
                rec = next((r for r in st.read_history() if r.get("run_id") == run_id), None)
                if rec is None:
                    self._json({"error": "not found"}, 404)
                else:
                    self._json(rec)

            else:
                self._send(404, "not found", "text/plain; charset=utf-8")

        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass   # 휴대폰이 화면을 끄는 등 받는 쪽이 먼저 끊은 경우
        except Exception as e:
            try:
                self._json({"error": type(e).__name__}, 500)
            except Exception:
                pass

    def do_POST(self):
        try:
            path = urllib.parse.urlsplit(self.path).path
            body, err = self._read_body()
            if err:
                self._json(err[1], err[0])
                return
            addr = self.client_address[0]

            if path == "/api/login":
                left = SESSIONS.locked_for(addr)
                if left:
                    self._json({"ok": False, "error": f"너무 많이 틀렸습니다. {left}초 뒤에 다시 하세요."}, 429)
                    return
                user_id = str(body.get("user_id") or "").strip()
                admin_code = str(body.get("admin_code") or "").strip()[:40]
                password = str(body.get("password") or "")
                acc = find_account(user_id)
                if not user_id or not admin_code or acc is None or not verify_password(acc, password):
                    SESSIONS.note_fail(addr)
                    time.sleep(0.4)   # 무차별 시도를 느리게
                    self._json({"ok": False, "error": "업체코드, 아이디 또는 비밀번호가 맞지 않습니다"}, 401)
                    return
                SESSIONS.note_ok(addr)
                token = SESSIONS.create(user_id, acc["role"], admin_code)
                s = SESSIONS.get(token)
                self._json(dict(me_view(s), ok=True, default_password=bool(acc.get("default_password"))),
                           200, self._set_cookie(token))
                return

            if path == "/api/logout":
                SESSIONS.drop(self._cookie_token())
                self._json({"ok": True}, 200, self._set_cookie("", clear=True))
                return

            s = self._require()
            if s is None:
                return

            if path == "/api/password":
                try:
                    change_password(s["user_id"], body.get("current"), body.get("new"))
                except ValueError as e:
                    self._json({"ok": False, "error": str(e)}, 400)
                    return
                except PermissionError as e:
                    self._json({"ok": False, "error": str(e)}, 403)
                    return
                SESSIONS.drop_user(s["user_id"])
                token = SESSIONS.create(s["user_id"], s["role"], s["admin_code"])   # 이 브라우저는 유지
                self._json({"ok": True, "message": "비밀번호를 바꿨습니다. 다른 기기는 다시 로그인해야 합니다."},
                           200, self._set_cookie(token))
                return

            # 여기부터는 관리자만
            if self._require(admin=True) is None:
                return

            if path == "/api/settings":
                changed = modules_changed = False
                try:
                    # 모듈 요청을 먼저 검증한다 - 자동 실행이 저장된 뒤에 모듈이 거절되는 반쪽 저장을 막기 위해
                    modules = validate_routine_modules(body["modules"]) if "modules" in body else None
                    changed = apply_schedule(body.get("schedule"))
                    modules_changed = apply_routine_modules(modules) if modules is not None else False
                except ValueError as e:
                    self._json({"ok": False, "error": str(e), "changed": changed, "modules_changed": False}, 400)
                    return
                except RuntimeError as e:
                    self._json({"ok": False, "error": str(e), "changed": changed, "modules_changed": False}, 500)
                    return
                view = settings_view(s)
                view.update(ok=True, changed=changed, modules_changed=modules_changed)
                self._json(view)

            elif path == "/api/run":
                target = body.get("target", "all")
                try:
                    cmd = launch(target, f"manual:{s['user_id']}")
                except ValueError as e:
                    self._json({"ok": False, "error": str(e)}, 400)
                    return
                except RuntimeError as e:
                    self._json({"ok": False, "error": str(e)}, 409)
                    return
                except FileNotFoundError as e:
                    self._json({"ok": False, "error": str(e)}, 500)
                    return
                self._json({"ok": True, "message": f"{TARGETS[target][0]} 을(를) 띄웠습니다. 잠시 뒤 현황에 나타납니다.",
                            "command": cmd, "schedule": schedule_view()})

            elif path == "/api/erpia/stop":
                code, result = stop_erpia()
                result["erpia_running"] = erpia_running()
                self._json(result, code)

            else:
                self._json({"ok": False, "error": "not found"}, 404)

        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except Exception as e:
            try:
                self._json({"ok": False, "error": type(e).__name__}, 500)
            except Exception:
                pass


class DashboardServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    # 윈도우에서 SO_REUSEADDR 를 켜면 같은 포트에 두 번째 서버가 '성공적으로' 떠 버린다.
    # 끄고, 독점 사용(SO_EXCLUSIVEADDRUSE)으로 중복 실행을 확실히 막는다.
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        # HTTPServer.server_bind 는 getfqdn 을 불러 망에 따라 수 초씩 멈추므로 쓰지 않는다.
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = host
        self.server_port = port


def lan_addresses():
    """다른 PC/휴대폰에서 칠 주소. 실제로 밖으로 나가는 주소를 맨 앞에 둔다."""
    primary = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("10.255.255.255", 1))   # 패킷은 나가지 않는다. 경로만 고른다.
            primary = s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        pass
    found = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.add(info[4][0])
    except OSError:
        pass
    ordered = [primary] if primary else []
    ordered += sorted(found - {primary})
    return [ip for ip in ordered if ip and not ip.startswith("127.")]


def already_running(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2) as r:
            return r.read().decode("utf-8", "replace").strip() == SIGNATURE
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser(description="ERPia RPA 현황 대시보드")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help="포트 (기본 8765)")
    ap.add_argument("--host", default="0.0.0.0",
                    help="0.0.0.0 = 사내망에서 접속 허용(기본), 127.0.0.1 = 이 PC 에서만")
    ap.add_argument("--status-dir", help="(점검용) 기록 폴더를 직접 지정")
    ap.add_argument("--no-scheduler", action="store_true", help="(점검용) 자동 실행을 돌리지 않는다")
    args = ap.parse_args()

    if args.status_dir:
        os.environ["RPA_STATUS_DIR"] = os.path.abspath(args.status_dir)

    if already_running(args.port):
        print(f"대시보드가 이미 실행 중입니다: http://localhost:{args.port}")
        return 0

    try:
        httpd = DashboardServer((args.host, args.port), Handler)
    except OSError as e:
        print(f"포트 {args.port} 을(를) 열 수 없습니다: {e}")
        print("다른 프로그램이 이 포트를 쓰고 있으면 --port 로 다른 번호를 주세요.")
        return 2

    made_default = ensure_accounts()
    if not args.no_scheduler:
        SCHEDULER.resync()
        SCHEDULER.start()

    sch = st.read_settings()["schedule"]
    line = "=" * 60
    print(line)
    print(" ERPia RPA 현황 대시보드")
    print(line)
    print(f"  이 PC       : http://localhost:{args.port}")
    if args.host in ("0.0.0.0", ""):
        for ip in lan_addresses():
            print(f"  사내 PC/폰  : http://{ip}:{args.port}")
    else:
        print(f"  (--host {args.host} 로 떠서 다른 PC 에서는 볼 수 없습니다)")
    print(f"  기록 폴더   : {st.status_dir()}")
    print(f"  설정 파일   : {st.user_config_path()}"
          + (" (환경변수 - 시험용)" if os.environ.get("RPA_USER_CONFIG") or os.environ.get("RPA_CRED_FILE") else ""))
    print("  로그인      : 관리자 admin / 일반 user" + (" (기본 계정을 새로 만들었습니다)" if made_default else ""))
    print(f"  관리자 권한 : {'예' if is_admin() else '아니오 (지금 실행·자동 실행·ERPia 종료가 ERPia 를 다루지 못할 수 있습니다)'}")
    if args.no_scheduler:
        print("  자동 실행   : 꺼짐 (--no-scheduler)")
    elif sch.get("enabled"):
        print(f"  자동 실행   : {schedule_label(sch)}, 다음 {sch.get('next_run_at') or '(곧 계산)'}")
        if SCHEDULER.skipped_at:
            print(f"                (꺼져 있던 동안 지난 {SCHEDULER.skipped_at:%m-%d %H:%M} 예약은 건너뛰었습니다)")
    else:
        print("  자동 실행   : 꺼짐 (환경설정 화면에서 켤 수 있습니다)")
    if DRY_RUN:
        print("  ** 시험 모드: Run_All.bat 을 실제로 띄우지 않습니다 **")
    print("  이 창을 닫으면 대시보드와 자동 실행만 꺼집니다. 돌고 있는 RPA 에는 영향이 없습니다.")
    print(line, flush=True)

    try:
        httpd.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        SCHEDULER.stop.set()
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
