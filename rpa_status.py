# -*- coding: utf-8 -*-
r"""RPA 진행 현황 기록. 대시보드(rpa_dashboard.py)가 이 기록을 읽어 웹으로 보여준다.

지키는 것
- 여기 있는 기록 함수는 어떤 경우에도 예외를 밖으로 내보내지 않는다.
  현황 기록이 실패했다고 업무 루틴이 멈추면 안 되기 때문이다.
- 표준 라이브러리만 쓴다. 대시보드도 이 모듈을 쓰는데, 거기에 pywinauto 같은
  무거운 패키지를 끌어들이지 않기 위해서다.
- start() 를 부르기 전에는 모든 기록 함수가 아무 일도 하지 않는다.
  그래서 --check 같은 점검 모드에서는 기록이 남지 않는다.

기록 위치: 바탕화면\ERPIA_AI\RPA_STATUS  (환경변수 RPA_STATUS_DIR 로 바꿀 수 있다)
  status_prepare.json   프리페어 RPA 의 지금(또는 마지막) 실행 상태. 계속 덮어쓴다.
  status_routine.json   루틴 RPA 의 지금(또는 마지막) 실행 상태.
  history.jsonl         실행이 끝날 때마다 한 줄씩 덧붙는다. 커지면 history.1.jsonl 로 넘긴다.

실행 결과(state)
  running   진행 중
  success   끝까지 마쳤다
  stopped   도중에 멈췄다 (업무 규칙에 따른 중단, 설정 오류, Ctrl+C 등). reason 에 사유
  crashed   프로그램 오류로 죽었거나, 강제 종료되어 기록 없이 사라졌다
"""
import atexit
import base64
import ctypes
import datetime
import functools
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import traceback
from collections import deque

try:
    import winreg
except ImportError:  # 윈도우가 아닌 곳에서 대시보드 화면만 시험할 때
    winreg = None

PROGRAMS = {"prepare": "프리페어 RPA", "routine": "루틴 RPA"}
# 이력(대시보드 '기록' 표)에만 남는 프로그램. 현황 카드·실행 단추·날짜별 도넛은 PROGRAMS 만 본다 (2026-09-30 옵저버 미리보기)
HISTORY_ONLY = {"observer": "옵저버"}
LABELS = {**PROGRAMS, **HISTORY_ONLY}

AI_DIR_NAME = "ERPIA_AI"
STATUS_DIR_NAME = "RPA_STATUS"
HISTORY_NAME = "history.jsonl"
HISTORY_OLD_NAME = "history.1.jsonl"
HISTORY_MAX_BYTES = 5 * 1024 * 1024
SETTINGS_NAME = "settings.json"      # 대시보드 환경설정 (자동 실행 주기 등)
CRED_FILE_NAME = "ERPIA_AI.txt"      # 옛 자격증명 파일 (바탕화면). RPA_UserConfig.json 으로 옮겨 온다
WEB_CONFIG_NAME = "WebManageConfig.json"   # 옛 사이트 설정 (exe 옆). RPA_UserConfig.json 의 Sites 로 옮겨 온다
LOGIN_MANAGER_NAME = "login_manager_config.json"   # 옛 ERPia 위치 파일 (exe 옆). RPA_UserConfig.json 의 ERPia 로 옮겨 온다
USER_CONFIG_NAME = "RPA_UserConfig.json"   # 사용자 설정 한 파일 (배포 폴더 루트, exe 옆). 아래 '사용자 설정' 절
LOGIN_SECTION = "LogIn"
SITES_SECTION = "Sites"
ERPIA_SECTION = "ERPia"              # {"ExePath": "C:/…/ERPiaMain.exe"}. 아래 'ERPia 프로그램 위치' 절
ERPIA_EXE_NAME = "ERPiaMain.exe"
SEALED_PREFIX = "dpapi:"             # 잠근 비밀번호 앞에 붙는다
# 자동 실행 예약: 요일(월=0 … 일=6) + 시각("HH:MM", 5분 단위, 여러 개)
SCHEDULE_MINUTE_STEP = 5
SCHEDULE_MAX_TIMES = 3      # 하루에 넣을 수 있는 실행 시각 개수
DEFAULT_SETTINGS = {
    "schedule": {
        "enabled": False,
        "days": [0, 1, 2, 3, 4],    # 평일
        "times": ["09:00"],
        "next_run_at": None,
        "last_launch_at": None,
        "last_launch_by": None,     # "auto" / "manual:<아이디>"
        "last_error": None,
    },
    # 대시보드 로그인 계정. 비밀번호는 해시로만 저장한다 (대시보드가 처음 뜰 때 기본 계정을 만든다).
    "accounts": {},
}

LOG_TAIL_LINES = 200       # 상태 파일에 들고 있는 최근 로그 줄 수
HISTORY_LOG_LINES = 80     # 이력 한 건에 남기는 로그 줄 수
HEARTBEAT_SECONDS = 2.0    # 변화가 없어도 이 간격으로 '살아 있음'을 적는다
MIN_WRITE_GAP = 0.5        # 잇따른 변경은 이 간격으로 묶어서 쓴다

# 중단 사유를 따로 받지 못했을 때 로그에서 사유로 삼을 줄의 표지
PROBLEM_WORDS = ("중단", "실패", "오류", "못했", "초과", "종료합니다", "않습니다")
_TIME_PREFIX = re.compile(r"^\s*\[\d{2}:\d{2}:\d{2}\]\s*")

VANISHED_REASON = ("프로그램이 도중에 꺼졌습니다 (강제 종료되었거나 오류로 멈췄습니다). "
                   "마지막 로그를 확인하세요.")


# ---------------------------------------------------------------------------
# 경로
# ---------------------------------------------------------------------------
def find_desktop_dir():
    """현재 사용자의 실제 바탕화면 폴더.

    회사 PC 는 OneDrive 등으로 바탕화면이 옮겨져 있는 경우가 흔해
    '~/Desktop' 으로 단정하면 안 된다. 윈도우에 등록된 경로를 먼저 읽는다.
    """
    if winreg is not None:
        try:
            key = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
                path = os.path.expandvars(winreg.QueryValueEx(k, "Desktop")[0])
                if os.path.isdir(path):
                    return path
        except Exception:
            pass
    return os.path.join(os.path.expanduser("~"), "Desktop")


def status_dir(create=True):
    path = os.environ.get("RPA_STATUS_DIR") or os.path.join(
        find_desktop_dir(), AI_DIR_NAME, STATUS_DIR_NAME)
    if create:
        try:
            os.makedirs(path, exist_ok=True)
        except Exception:
            pass
    return path


def status_path(program):
    return os.path.join(status_dir(), f"status_{program}.json")


def settings_path():
    return os.path.join(status_dir(), SETTINGS_NAME)


def read_settings():
    """대시보드 환경설정. 없거나 깨졌으면 기본값으로 채운다."""
    data = read_json(settings_path())
    out = json.loads(json.dumps(DEFAULT_SETTINGS))
    if isinstance(data, dict):
        for section, values in data.items():
            if isinstance(values, dict) and isinstance(out.get(section), dict):
                out[section].update(values)
    return out


def write_settings(data):
    return write_json_atomic(settings_path(), data)


def _read_text_any(path):
    for encoding in ("utf-8-sig", "cp949", "utf-16"):
        try:
            with open(path, "r", encoding=encoding) as f:
                return f.read()
        except (UnicodeDecodeError, UnicodeError):
            continue
    return None


def _flatten(value):
    out = {}
    if isinstance(value, dict):
        out.update(value)
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                out.update(item)
    return out


def read_account():
    """사용자 설정의 업체코드(AdminCode)와 아이디(ID)만 읽는다.

    비밀번호는 읽지 않는다. 대시보드는 로그인 없이 사내망 누구나 보는 화면이라
    이 함수가 돌려주는 값은 그대로 화면에 나간다고 생각해야 한다.
    """
    try:
        login = read_user_config().get(LOGIN_SECTION)
    except Exception:
        return None
    if not isinstance(login, dict):
        return None
    return {"admin_code": str(login.get("AdminCode") or ""),
            "user_id": str(login.get("ID") or "")}


# ---------------------------------------------------------------------------
# 사용자 설정: RPA_UserConfig.json (배포 폴더 루트, exe 옆) 한 파일
#
#   {"LogIn":    {"AdminCode": …, "ID": …, "PW": …},
#    "Routine":  {"Login": "Y", "Sales": "Y", "Hold": "N", …},
#    "Logistic": {"cboBS_Auto_YN": …, "Printer": …, …},
#    "Sites":    {"SITE1": {"URL": …, "ID": …, "PW": …, "Action": […], "Stts": 0, …}, …},
#    "ERPia":    {"ExePath": "C:/Program Files (x86)/OneZeroSoft/ERPiaNet/ERPiaMain.exe"}}
#
# 예전의 ERPIA_AI.txt(바탕화면, LogIn·Logistic·Routine), WebManageConfig.json(exe 옆, 사이트),
# login_manager_config.json(exe 옆, ERPia 위치 exe_path)을 합친 것이다.
#   - 비밀번호(PW)는 DPAPI(이 PC·이 윈도우 계정에서만 풀림)로 잠가 "dpapi:…" 로 넣는다. 평문으로 적어 두어도
#     읽히고, 이 파일을 쓸 때(에이전트가 켤 때 포함) 잠긴다. 읽기 함수는 잠긴 채 돌려주고 로그인하는 곳만 unseal 한다.
#   - 이 파일이 없으면 옛 파일들을 읽는다 (에이전트가 아직 옮기기 전인 PC). 처음 쓸 때 합쳐 만들고 옛 파일은 .old 로.
#   - 시험은 RPA_USER_CONFIG(또는 옛 RPA_CRED_FILE)로 임시 폴더를 가리킨다. 그러면 새 파일·옛 파일 모두 그 폴더만 본다.
# ---------------------------------------------------------------------------
PRODUCT_DIRS = ("AFTER MARKET", "RPA")   # 새 구조 폴더: Program Files\AFTER MARKET\RPA, ProgramData\AFTER MARKET\RPA


def _nuitka():
    """Nuitka 로 컴파일된 모듈이면 __compiled__ 가 있다 (PyInstaller·소스에는 없다)."""
    return globals().get("__compiled__")


def packaged():
    """exe 로 묶여 도는가 (Nuitka 또는 PyInstaller)."""
    return _nuitka() is not None or bool(getattr(sys, "frozen", False))


def run_kind():
    """--check 에 찍는 실행 형태."""
    if _nuitka() is not None:
        return "exe(Nuitka)"
    return "exe(PyInstaller)" if packaged() else "파이썬 스크립트"


def program_dir():
    """RPA exe 가 있는 폴더 (배포 폴더 루트, 새 구조면 Program Files\\AFTER MARKET\\RPA).
    Nuitka onefile 은 풀린 임시 폴더가 아니라 exe 가 놓인 폴더, PyInstaller 는 exe 옆, 소스면 이 파일 옆.
    개발 PC 처럼 옆 dist 에 Run_All.bat 이 있으면 dist - 대시보드가 띄우는 exe 와 같은 설정을 본다
    (rpa_dashboard.run_command_path 와 같은 규칙)."""
    compiled = _nuitka()
    if compiled is not None:
        return getattr(compiled, "containing_dir", None) or os.path.dirname(os.path.abspath(sys.argv[0]))
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    here = os.path.dirname(os.path.abspath(__file__))
    dist = os.path.join(here, "dist")
    return dist if os.path.isfile(os.path.join(dist, "Run_All.bat")) else here


def install_root():
    """새 구조의 설정·기록 뿌리 %ProgramData%\\AFTER MARKET\\RPA. 시험용 RPA_PROGRAMDATA 가 있으면 그 폴더."""
    return os.environ.get("RPA_PROGRAMDATA") or os.path.join(
        os.environ.get("ProgramData") or r"C:\ProgramData", *PRODUCT_DIRS)


def new_layout():
    """설치 마법사(2부)가 install_root()\\config 를 만든 PC 인가. 아니면 옛 구조 (설정·기록 = exe 옆)."""
    return os.path.isdir(os.path.join(install_root(), "config"))


def config_dir():
    """사용자 설정(RPA_UserConfig.json)을 둘 폴더."""
    return os.path.join(install_root(), "config") if new_layout() else program_dir()


def data_dir():
    """기록(결과 로그·화면 사진·세션)을 둘 폴더. 새 구조면 없을 때 만든다 - 못 만들어도 예외는 내지 않는다
    (기록 때문에 RPA 가 멈추면 안 된다. 쓰는 쪽이 실패를 삼킨다)."""
    if not new_layout():
        return program_dir()
    path = os.path.join(install_root(), "data")
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        pass
    return path


def user_config_path():
    """RPA_UserConfig.json 위치. 시험용 RPA_USER_CONFIG 가 있으면 그 파일, RPA_CRED_FILE 만 있으면 그 옆.
    아니면 config_dir() (옛 구조는 exe 옆 그대로)."""
    override = os.environ.get("RPA_USER_CONFIG")
    if override:
        return override
    cred = os.environ.get("RPA_CRED_FILE")
    if cred:
        return os.path.join(os.path.dirname(cred), USER_CONFIG_NAME)
    return os.path.join(config_dir(), USER_CONFIG_NAME)


# ---------------------------------------------------------------------------
# 판 (배포판 구조 1부, docs/superpowers/specs/2026-09-29-release-layout-design.md 4·5절)
# 프로그램 폴더의 manifest.json 에 판 번호와 우리 파일의 지문(SHA-256)을 적는다. tools/build_release.py 가 쓰고,
# 에이전트가 켤 때 check_install() 로 맞춰 본다. 사고(섞임) 확인용이지 변조 방어가 아니다 - 서명은 3부.
# ---------------------------------------------------------------------------
MANIFEST_NAME = "manifest.json"
MANIFEST_FORMAT = 1
CHANGED_MAX = 10          # 화면에 보낼 다른 파일 이름 수 (전체 개수는 changed_count)


def file_digest(path):
    """판 목록의 한 줄 {"sha256", "size"}."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return {"sha256": h.hexdigest(), "size": os.path.getsize(path)}


def manifest_path_ok(rel):
    """판 목록의 경로는 프로그램 폴더 안의 상대 경로('/' 구분)만 받는다. 3부 업데이트가 이 경로에 쓰므로
    밖(.., 절대 경로, 드라이브)을 못 가리키게 한다."""
    return (isinstance(rel, str) and rel != "" and not rel.startswith("/") and "\\" not in rel and ":" not in rel
            and all(part not in ("", ".", "..") for part in rel.split("/")))


def check_install(root=None):
    """프로그램 폴더를 판 목록과 맞춰 본다. 예외를 내보내지 않는다 (에이전트가 켤 때 부른다).

    ok     목록의 모든 파일이 있고 지문이 같다
    mixed  없거나 지문이 다른 파일이 있다 (몇 개만 손으로 넣었거나 덮어쓰다 끊김)
    none   목록이 없다 (옛 배포 폴더, 개발 PC)
    error  목록을 못 믿는다 (깨짐, 형식 번호가 다름, 밖을 가리키는 경로)
    """
    out = {"version": None, "state": "none", "changed": [], "changed_count": 0,
           "checked_at": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")}
    try:
        root = root or program_dir()
        path = os.path.join(root, MANIFEST_NAME)
        if not os.path.isfile(path):
            return out
        with open(path, encoding="utf-8") as f:
            man = json.load(f)
        files = man.get("files") if isinstance(man, dict) else None
        if man.get("format") != MANIFEST_FORMAT or not isinstance(files, dict):
            raise ValueError("판 목록 형식이 다릅니다")
        out["version"] = str(man.get("version") or "") or None
        changed = []
        for rel, want in files.items():
            if not manifest_path_ok(rel) or not isinstance(want, dict):
                raise ValueError(f"판 목록의 경로가 잘못되었습니다: {rel!r}")
            full = os.path.join(root, *rel.split("/"))
            if not os.path.isfile(full) or file_digest(full)["sha256"] != want.get("sha256"):
                changed.append(rel)
        out.update(state="mixed" if changed else "ok", changed=changed[:CHANGED_MAX], changed_count=len(changed))
    except Exception as e:
        out.update(state="error", changed=[], changed_count=0, error=f"{type(e).__name__}: {e}"[:200])
    return out


def _old_config_paths():
    """옮겨 올 옛 파일 (ERPIA_AI.txt, WebManageConfig.json, login_manager_config.json). 시험용 환경변수가 있으면
    그 폴더만 본다."""
    base = os.path.dirname(user_config_path())
    only_new = os.environ.get("RPA_USER_CONFIG") and not os.environ.get("RPA_CRED_FILE")
    return (os.path.join(base, CRED_FILE_NAME) if only_new else cred_file_path(),
            os.path.join(base, WEB_CONFIG_NAME),
            os.path.join(base, LOGIN_MANAGER_NAME))


def _old_exe_path(path):
    """옛 login_manager_config.json 의 exe_path (업체코드·아이디도 있었지만 쓰는 곳이 없어 버린다)."""
    data = _read_json(path)
    return data.get("exe_path") if isinstance(data, dict) else None


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


_DPAPI = None


def _dpapi(protect, data):
    """DPAPI(현재 사용자 범위)로 감싸거나 푼다. crypt32·kernel32 은 이 모듈 전용 인스턴스에만 원형을 붙인다
    (_k32 와 같은 이유 - 같은 프로세스의 pywinauto 호출과 섞이지 않게)."""
    global _DPAPI
    if _DPAPI is None:
        c = ctypes.WinDLL("crypt32")
        tail = (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(_Blob))
        c.CryptProtectData.argtypes = (ctypes.POINTER(_Blob), ctypes.c_wchar_p) + tail
        c.CryptUnprotectData.argtypes = (ctypes.POINTER(_Blob), ctypes.c_void_p) + tail
        c.CryptProtectData.restype = c.CryptUnprotectData.restype = ctypes.c_int
        k = ctypes.WinDLL("kernel32")
        k.LocalFree.argtypes = (ctypes.c_void_p,)
        k.LocalFree.restype = ctypes.c_void_p
        _DPAPI = (c, k)
    c, k = _DPAPI
    buf = ctypes.create_string_buffer(data, len(data))
    src, out = _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), _Blob()
    if protect:
        ok = c.CryptProtectData(ctypes.byref(src), "rpa-user-config", None, None, None, 0, ctypes.byref(out))
    else:
        ok = c.CryptUnprotectData(ctypes.byref(src), None, None, None, None, 0, ctypes.byref(out))
    if not ok:
        raise OSError("DPAPI 실패")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        k.LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))


def seal(text):
    """비밀번호를 잠근 "dpapi:…". 비었거나 이미 잠겼으면 그대로."""
    if not isinstance(text, str) or not text or text.startswith(SEALED_PREFIX):
        return text
    return SEALED_PREFIX + base64.b64encode(_dpapi(True, text.encode("utf-8"))).decode("ascii")


def unseal(value):
    """잠긴 비밀번호를 푼다. 평문이면 그대로 (사람이 파일에 적은 값 - 다음에 파일을 쓸 때 잠긴다)."""
    if not isinstance(value, str) or not value.startswith(SEALED_PREFIX):
        return value
    try:
        return _dpapi(False, base64.b64decode(value[len(SEALED_PREFIX):])).decode("utf-8")
    except Exception:
        raise RuntimeError(
            f"{USER_CONFIG_NAME} 의 비밀번호를 풀지 못했습니다. 다른 PC 나 다른 윈도우 계정에서 잠근 값입니다. "
            "이 PC 에서 비밀번호를 다시 넣으세요 (파일에 평문으로 적으면 에이전트가 켤 때 잠급니다)") from None


def _pw_slots(data):
    """비밀번호 자리 (담은 dict, 키): LogIn.PW 와 사이트마다 PW."""
    login = data.get(LOGIN_SECTION)
    if isinstance(login, dict) and "PW" in login:
        yield login, "PW"
    sites = data.get(SITES_SECTION)
    for site in (sites.values() if isinstance(sites, dict) else ()):
        if isinstance(site, dict) and "PW" in site:
            yield site, "PW"


def _read_json(path):
    """인코딩을 가리지 않고 JSON 을 읽는다. 깨졌으면 ValueError - 메시지에 파일 내용은 싣지 않는다."""
    text = _read_text_any(path)
    if text is None:
        raise ValueError(f"{os.path.basename(path)} 의 인코딩을 알 수 없습니다")
    try:
        return json.loads(text)
    except ValueError:
        raise ValueError(f"{os.path.basename(path)} 이(가) JSON 형식이 아닙니다") from None


def _sections(data, name):
    """설정 JSON 을 {섹션: {키: 값}} 으로 푼다. ERPIA_AI.txt 의 옛 형식(단일 키 dict 목록)도 받는다.
    섹션 없이 바로 있는 값은 LogIn 에 넣는다 (가장 옛 형식). 단 Routine 을 값으로 잘못 쓴 것은 그대로 둬서
    읽는 쪽이 '잘못됨' 으로 알린다. '_' 로 시작하는 키는 사람이 적는 주석이라 손대지 않고 둔다."""
    if not isinstance(data, (dict, list)):
        raise ValueError(f"{name} 의 JSON 최상위가 객체도 배열도 아닙니다")
    out, loose = {}, {}
    for key, value in _flatten(data).items():
        if key.startswith("_") or (key == ROUTINE_SECTION and not isinstance(value, (dict, list))):
            out[key] = value
        elif isinstance(value, (dict, list)):
            out[key] = _flatten(value)
        else:
            loose[key] = value
    if loose:
        out.setdefault(LOGIN_SECTION, {}).update(loose)
    return out


def read_user_config(path=None):
    """사용자 설정을 {섹션: {키: 값}} 으로 읽는다. 비밀번호는 잠긴 채 (로그인하는 곳에서 unseal).

    path 를 주면 그 파일만 본다. 안 주면 RPA_UserConfig.json, 그게 없으면 옛 파일들을 합쳐 읽는다.
    아무것도 없으면 {}. 깨졌으면 ValueError.
    """
    if path or os.path.isfile(user_config_path()):
        path = path or user_config_path()
        return _sections(_read_json(path), os.path.basename(path)) if os.path.isfile(path) else {}
    cred, web, lm = _old_config_paths()
    out = _sections(_read_json(cred), CRED_FILE_NAME) if os.path.isfile(cred) else {}
    if os.path.isfile(web):
        sites = _read_json(web)
        if isinstance(sites, dict):
            out[SITES_SECTION] = sites
    if os.path.isfile(lm) and _old_exe_path(lm):
        out[ERPIA_SECTION] = {"ExePath": _old_exe_path(lm)}
    return out


def _replace_retry(tmp, target):
    """tmp 를 target 으로 바꿔치기. 다른 프로그램(루틴·메모장·에이전트)이 막 읽고 있는 순간이면 몇 번 다시 한다."""
    for i in range(5):
        try:
            return os.replace(tmp, target)
        except PermissionError:
            if i == 4:
                raise
            time.sleep(0.1)


def write_user_config(data, path=None):
    """사용자 설정을 쓴다. 평문 비밀번호는 잠가서 넣는다. 임시 파일에 다 쓴 뒤 바꿔치기한다 (반쯤 쓴 파일이 남지 않게).
    평문이 남는 사본(.bak)은 만들지 않는다. 기본 자리에 쓰면 옛 파일들을 .old 로 바꾸고 그 목록을 돌려준다
    (이제 안 읽는다는 표시. 평문 비밀번호가 들어 있으니 RPA 가 잘 도는 것을 본 뒤 지운다)."""
    target = path or user_config_path()
    data = json.loads(json.dumps(data, ensure_ascii=False))   # 사본 - 부른 쪽 dict 에 잠근 값이 섞이지 않게
    for holder, key in _pw_slots(data):
        holder[key] = seal(holder[key])
    # 임시 파일에도 설정이 통째로 들어가므로, 바꿔치기가 실패하면 반드시 지운다.
    tmp = f"{target}.{os.getpid()}.tmp"
    try:
        # 메모장 기본(BOM 없는 UTF-8)으로 쓴다. 읽는 쪽은 utf-8-sig 로 먼저 읽으므로 BOM 이 없어도 읽는다.
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(data, ensure_ascii=False, indent=2))
            f.write("\n")
        _replace_retry(tmp, target)
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
    if path:
        return []
    moved = []
    for old in _old_config_paths():
        if os.path.isfile(old):
            try:
                os.replace(old, old + ".old")
                moved.append(old)
            except OSError:
                pass        # 다른 프로그램이 잡고 있으면 둔다 - 새 파일이 있으면 어차피 안 읽는다
    return moved


def migrate_user_config():
    """에이전트가 켤 때 부른다. RPA_UserConfig.json 이 없으면 옛 파일들을 합쳐 만들고, 있으면 평문 비밀번호를 잠그고
    아직 남은 login_manager_config.json 의 ERPia 위치를 가져온다 (그 파일보다 먼저 옮긴 PC).
    한 일을 한 문장으로 돌려준다 (할 일이 없으면 None). 실패하면 예외 - 부른 쪽이 기록만 하고 넘어간다
    (RPA 는 옛 파일이나 평문으로도 돈다)."""
    existed = os.path.isfile(user_config_path())
    data = read_user_config()
    if not data:
        return None
    parts = []
    plain = sum(1 for h, k in _pw_slots(data)
                if isinstance(h[k], str) and h[k] and not h[k].startswith(SEALED_PREFIX))
    if plain:
        parts.append(f"평문 비밀번호 {plain}개를 잠갔습니다")
    lm = _old_config_paths()[2]
    erpia = data.get(ERPIA_SECTION)
    if existed and os.path.isfile(lm) and not (isinstance(erpia, dict) and erpia.get("ExePath")) and _old_exe_path(lm):
        data[ERPIA_SECTION] = dict(erpia if isinstance(erpia, dict) else {}, ExePath=_old_exe_path(lm))
        parts.append("ERPia 위치를 옮겨 왔습니다")
    if existed and not parts:
        return None
    moved = write_user_config(data)
    if moved:
        parts.append(f"옛 파일 {' · '.join(os.path.basename(p) for p in moved)} 은 .old 로 바꿨습니다 - "
                     "평문 비밀번호가 들어 있으니 RPA 가 잘 돌면 지우세요")
    head = USER_CONFIG_NAME if existed else f"{USER_CONFIG_NAME} 을 만들었습니다"
    return f"{head} ({', '.join(parts)})" if parts else head


# ---------------------------------------------------------------------------
# ERPia 프로그램 위치 (사용자 설정의 "ERPia": {"ExePath": …})
#
# 적힌 값이 맞으면 그대로. 틀렸거나 없으면 설치 기록(제어판 '프로그램 제거' 목록의 설치 폴더)과 기본 설치 폴더에서
# ERPiaMain.exe 를 찾아 고쳐 적는다. 그래도 없으면 사람이 있을 때만 파일 고르는 창을 띄운다 - 대시보드·예약이
# 띄운 무인 실행이 창 앞에서 기다리며 멈추면 안 되기 때문이다 (그때는 바로 멈추고 사유를 남긴다).
# 이름이 ERPiaMain.exe 인 파일만 받는다 - 같은 회사의 다른 프로그램(ERPia_Login.exe 등)으로는 루틴이 돌지 않는다.
# ---------------------------------------------------------------------------
def _erpia_file(path):
    """path 가 실제로 있는 ERPiaMain.exe 면 정리한 경로, 아니면 None. 폴더를 주면 그 안의 ERPiaMain.exe 를 본다."""
    if not path or not isinstance(path, str):
        return None
    if not path.lower().endswith(".exe"):
        path = os.path.join(path, ERPIA_EXE_NAME)
    path = os.path.normpath(path)
    return path if os.path.basename(path).lower() == ERPIA_EXE_NAME.lower() and os.path.isfile(path) else None


def _erpia_install_dirs():
    """ERPiaMain.exe 가 있을 만한 폴더: 설치 기록(레지스트리)의 설치 폴더들, 그다음 기본 설치 폴더."""
    dirs = []
    if winreg is not None:
        for root, sub in ((winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
                          (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
                          (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall")):
            try:
                with winreg.OpenKey(root, sub) as k:
                    for i in range(winreg.QueryInfoKey(k)[0]):
                        try:
                            with winreg.OpenKey(k, winreg.EnumKey(k, i)) as app:
                                dirs.append(winreg.QueryValueEx(app, "InstallLocation")[0])
                        except OSError:
                            continue
            except OSError:
                continue
    for env, default in (("ProgramFiles(x86)", r"C:\Program Files (x86)"), ("ProgramFiles", r"C:\Program Files")):
        dirs.append(os.path.join(os.environ.get(env) or default, "OneZeroSoft", "ERPiaNet"))
    return dirs


def find_erpia_exe():
    """(찾은 ERPiaMain.exe 또는 None, 설정에 적힌 값). 찾기만 하고 아무것도 쓰지 않는다 (점검 모드도 쓴다)."""
    try:
        section = read_user_config().get(ERPIA_SECTION)
    except Exception:
        section = None           # 설정이 깨졌어도 ERPia 는 찾는다 (깨진 설정은 로그인 정보를 읽을 때 알린다)
    configured = section.get("ExePath") if isinstance(section, dict) else None
    found = _erpia_file(configured)
    if not found:
        for folder in _erpia_install_dirs():
            found = _erpia_file(folder)
            if found:
                break
    return found, configured


def set_erpia_exe(path):
    """ERPia 위치를 사용자 설정에 적는다. 사람이 고쳐 적기 쉽게 / 로 적는다 (JSON 에서 \\ 는 두 번 써야 한다)."""
    data = read_user_config()
    section = data.get(ERPIA_SECTION)
    data[ERPIA_SECTION] = dict(section if isinstance(section, dict) else {}, ExePath=path.replace("\\", "/"))
    write_user_config(data)


def pick_erpia_exe():
    """ERPiaMain.exe 를 고르는 창을 띄운다 - 사람이 있을 때만 부를 것. 고른 경로, 취소면 None.
    다른 이름의 파일을 고르면 다시 묻는다. 창은 새 스레드(STA)에서 띄운다 - 부른 쪽 스레드의 COM 상태와 섞이지 않게."""
    result = []
    worker = threading.Thread(target=lambda: result.append(_pick_erpia_exe_sta()), daemon=True)
    worker.start()
    worker.join()
    return result[0] if result else None


def _pick_erpia_exe_sta():
    from ctypes import wintypes

    class OFN(ctypes.Structure):          # OPENFILENAMEW
        _fields_ = [("lStructSize", wintypes.DWORD), ("hwndOwner", wintypes.HWND), ("hInstance", wintypes.HINSTANCE),
                    ("lpstrFilter", wintypes.LPCWSTR), ("lpstrCustomFilter", wintypes.LPWSTR),
                    ("nMaxCustFilter", wintypes.DWORD), ("nFilterIndex", wintypes.DWORD),
                    ("lpstrFile", wintypes.LPWSTR), ("nMaxFile", wintypes.DWORD),
                    ("lpstrFileTitle", wintypes.LPWSTR), ("nMaxFileTitle", wintypes.DWORD),
                    ("lpstrInitialDir", wintypes.LPCWSTR), ("lpstrTitle", wintypes.LPCWSTR), ("Flags", wintypes.DWORD),
                    ("nFileOffset", wintypes.WORD), ("nFileExtension", wintypes.WORD), ("lpstrDefExt", wintypes.LPCWSTR),
                    ("lCustData", wintypes.LPARAM), ("lpfnHook", ctypes.c_void_p), ("lpTemplateName", wintypes.LPCWSTR),
                    ("pvReserved", ctypes.c_void_p), ("dwReserved", wintypes.DWORD), ("FlagsEx", wintypes.DWORD)]

    ole32 = ctypes.WinDLL("ole32")
    ole32.CoInitializeEx.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
    ole32.CoInitializeEx.restype = ctypes.c_long
    hr = ole32.CoInitializeEx(None, 0x2)                # COINIT_APARTMENTTHREADED
    try:
        dlg = ctypes.WinDLL("comdlg32")
        dlg.GetOpenFileNameW.argtypes = (ctypes.POINTER(OFN),)
        dlg.GetOpenFileNameW.restype = wintypes.BOOL
        k = ctypes.WinDLL("kernel32")
        k.GetConsoleWindow.restype = wintypes.HWND
        filt = ctypes.create_unicode_buffer(f"ERPia 프로그램 ({ERPIA_EXE_NAME})\0{ERPIA_EXE_NAME}\0\0")
        start = os.environ.get("ProgramFiles(x86)") or os.environ.get("ProgramFiles") or "C:\\"
        title = f"ERPia 프로그램({ERPIA_EXE_NAME})이 어디 있는지 골라 주세요"
        for _ in range(3):
            buf = ctypes.create_unicode_buffer(1024)
            ofn = OFN()
            ofn.lStructSize = ctypes.sizeof(OFN)
            ofn.hwndOwner = k.GetConsoleWindow()
            ofn.lpstrFilter = ctypes.cast(filt, wintypes.LPCWSTR)
            ofn.nFilterIndex = 1
            ofn.lpstrFile = ctypes.cast(buf, wintypes.LPWSTR)
            ofn.nMaxFile = len(buf)
            ofn.lpstrInitialDir = start
            ofn.lpstrTitle = title
            # OFN_EXPLORER | FILEMUSTEXIST | PATHMUSTEXIST | NOCHANGEDIR | HIDEREADONLY | DONTADDTORECENT
            ofn.Flags = 0x00080000 | 0x00001000 | 0x00000800 | 0x00000008 | 0x00000004 | 0x02000000
            if not dlg.GetOpenFileNameW(ctypes.byref(ofn)):
                return None                             # 취소
            found = _erpia_file(buf.value)
            if found:
                return found
            title = f"{ERPIA_EXE_NAME} 가 아닙니다. ERPia 설치 폴더의 {ERPIA_EXE_NAME} 를 골라 주세요"
            start = os.path.dirname(buf.value) or start
        return None
    finally:
        if hr >= 0:
            ole32.CoUninitialize()


def erpia_exe(ask=False):
    """ERPiaMain.exe 경로. 적힌 값이 틀렸으면 찾아서 고쳐 적고, 그래도 없으면 ask 일 때만 고르는 창을 띄운다.
    끝내 없으면 None. 고쳐 적기가 실패해도(쓰기 권한 등) 찾은 경로는 돌려준다 - 이번 실행은 돌게."""
    found, configured = find_erpia_exe()
    if not found and ask:
        found = pick_erpia_exe()
    if found and found != _erpia_file(configured):
        try:
            set_erpia_exe(found)
        except Exception:
            pass
    return found


# ---------------------------------------------------------------------------
# 루틴 RPA 의 실행 모듈 설정 (사용자 설정의 "Routine" 섹션)
#
# 대시보드 환경설정에서 관리자가 켜고 끈다. 이 파일에는 ERPia 비밀번호가 들어 있으므로
#   - 읽을 때는 Routine 섹션의 값만 꺼내고 나머지는 절대 밖으로 내보내지 않는다
#   - 쓸 때는 파일 전체를 읽어 Routine 항목만 바꾸고, 나머지(비밀번호 포함)는 그대로 둔다
# 모듈 목록은 run_routine.ROUTINE_MODULES 와 같아야 한다 (시험이 대조한다). 대시보드는 pywinauto 를
# 들여올 수 없어 run_routine 을 import 하지 못하므로 여기에 따로 둔다.
# ---------------------------------------------------------------------------
ROUTINE_SECTION = "Routine"
# 설정에서 끈 모듈의 단계에 붙는 note. 루틴(run_routine)이 이 값으로 skip 을 찍고,
# 현황 링·이력의 단계 수 계산은 이 note 가 붙은 단계를 '할 일' 에서 뺀다.
OFF_NOTE = "설정에서 끔"
ROUTINE_CONFIG_MODULES = (
    ("Login", "로그인"),
    ("Sales", "주문매핑 매출처리"),
    ("Hold", "물류대기 관리"),
    ("Logistics", "물류관리"),
    ("Output", "운송장 출력 / 엑셀 생성"),
)


def cred_file_path():
    """ERPIA_AI.txt 위치. 새 자리(바탕화면\\ERPIA_AI)에 없으면 예전 자리(바탕화면)도 본다. 둘 다 없으면 새 자리 경로.

    환경변수 RPA_CRED_FILE 이 있으면 그 파일을 쓴다 - 시험이 실제 자격증명 파일을 건드리지 않게 하기 위한 것.
    """
    override = os.environ.get("RPA_CRED_FILE")
    if override:
        return override
    desktop = find_desktop_dir()
    for folder in (os.path.join(desktop, AI_DIR_NAME), desktop):
        path = os.path.join(folder, CRED_FILE_NAME)
        if os.path.isfile(path):
            return path
    return os.path.join(desktop, AI_DIR_NAME, CRED_FILE_NAME)


def _merge_routine_section(existing, final):
    """기존 Routine 섹션에서 아는 키만 Y/N 으로 바꾸고, 모르는 키는 그대로 둔다. 없던 키는 뒤에 붙인다.

    모르는 키를 지우지 않는 이유: 루틴이 '모르는 키' 경고를 내 주는데, 대시보드가 조용히 지워 버리면
    사용자가 오타를 알 길이 없어진다.
    """
    out = dict(existing) if isinstance(existing, dict) else {}
    out.update({k: ("Y" if final[k] else "N") for k in final})
    return out


def read_routine_modules(path=None):
    """Routine 섹션을 {설정 키: True/False/None} 으로 읽는다. (선택, 문제 목록)

    키가 없으면 True(켬). 값이 Y/N 이 아니면 None 으로 두고 문제 목록에 적는다
    (루틴은 그런 값이면 돌지 않는다 - 화면에서 '잘못됨' 으로 보여 주기 위해).
    파일이 없거나 못 읽으면 전부 None 과 문제 한 줄. path 를 안 주면 사용자 설정 (없으면 옛 파일).
    """
    name = os.path.basename(path or user_config_path())
    keys = [k for k, _ in ROUTINE_CONFIG_MODULES]
    try:
        data = read_user_config(path)
    except Exception as e:
        return {k: None for k in keys}, [f"{name} 을(를) 읽지 못했습니다: {type(e).__name__}"]
    if not data:
        return {k: None for k in keys}, [f"{name} 이(가) 없거나 비어 있습니다"]
    section = data.get(ROUTINE_SECTION, {})
    if not isinstance(section, dict):
        # {"Routine": "Y"} 처럼 섹션이 아니라 값으로 쓴 경우. 루틴은 이 파일로 돌지 않는다.
        return ({k: None for k in keys},
                [f"'{ROUTINE_SECTION}' 은 값이 아니라 섹션이어야 합니다 (예: {{\"Login\": \"Y\", ...}})"])
    selected = {}
    problems = []
    for k in keys:
        raw = section.get(k)
        if raw is None:
            selected[k] = True
            continue
        v = str(raw).strip().upper()
        if v in ("Y", "N"):
            selected[k] = v == "Y"
        else:
            selected[k] = None
            problems.append(f"{k} 값이 Y/N 이 아닙니다 ({raw!r})")
    return selected, problems


def write_routine_modules(selected, path=None):
    """Routine 섹션만 바꿔 쓴다. 나머지(비밀번호 포함)는 그대로 둔다. 새로 쓴 {키: True/False} 를 돌려준다.

    selected: {설정 키: True/False}. 모르는 키는 ValueError. 빠진 키는 켬(Y)으로 쓴다.
    path 를 안 주면 사용자 설정에 쓴다 - 아직 옛 파일뿐이면 이때 합쳐 만든다 (write_user_config).
    읽을 설정이 아무것도 없으면 FileNotFoundError (자격증명 없는 파일을 새로 만들지 않는다).
    """
    keys = [k for k, _ in ROUTINE_CONFIG_MODULES]
    unknown = sorted(set(selected) - set(keys))
    if unknown:
        raise ValueError(f"모르는 모듈 키: {', '.join(unknown)}")
    final = {k: bool(selected.get(k, True)) for k in keys}
    data = read_user_config(path)
    if not data:
        raise FileNotFoundError(path or user_config_path())
    data[ROUTINE_SECTION] = _merge_routine_section(data.get(ROUTINE_SECTION), final)
    write_user_config(data, path)
    return final

# ---------------------------------------------------------------------------
# 쇼핑몰 프리셋 (옵저버가 쓰고, 프리페어가 재생하고, 대시보드가 켠다 - 2026-09-30 설계 5절)
# ---------------------------------------------------------------------------
PRESETS_NAME = "RPA_Presets.json"
PRESET_MIN, PRESET_MAX = 2, 10
REPLAY_ACTION = "replay"                  # web_runner 의 Action 이름
_PRESET_KEY = re.compile(r"(?:PRESET)?(\d+)")


def presets_path():
    """프리셋 파일 자리 - 사용자 설정과 같은 폴더 (시험은 RPA_USER_CONFIG 를 따라온다)."""
    return os.path.join(os.path.dirname(user_config_path()), PRESETS_NAME)


def blank_preset(no):
    return {"no": no, "name": f"프리셋 {no}", "code": "", "saved_at": None, "record": None}


def read_presets():
    """[{no, name, code, saved_at, record}] - 번호는 1부터 빈틈없이, 최소 PRESET_MIN 개. 파일이 없으면 빈 프리셋 둘.
    깨졌으면 ValueError (옵저버가 덮어쓰지 않게 - 사람이 고쳐야 한다)."""
    path = presets_path()
    if not os.path.isfile(path):
        return [blank_preset(i + 1) for i in range(PRESET_MIN)]
    data = _read_json(path)
    if not isinstance(data, list):
        raise ValueError(f"{PRESETS_NAME} 가 목록이 아닙니다")
    if len(data) > PRESET_MAX:
        raise ValueError(f"{PRESETS_NAME} 에 프리셋이 {len(data)}개 있습니다 (최대 {PRESET_MAX})")
    out, codes = [], {}
    for i, d in enumerate(data, 1):
        # 손으로 고친 파일을 고쳐 읽지 않는다: 번호가 밀리면 다른 쇼핑몰의 Sites.PRESETn 계정과 엮인다 (2026-10-01 검토)
        if not isinstance(d, dict) or d.get("no") != i:
            raise ValueError(f"{PRESETS_NAME} 의 {i}번째가 프리셋 {i} 이 아닙니다 (번호가 빠졌거나 바뀌었습니다)")
        r = d.get("record")
        if r is not None and not (isinstance(r, dict) and isinstance(r.get("steps"), list)):
            raise ValueError(f"{PRESETS_NAME} 의 프리셋 {i} 기록 모양이 틀렸습니다")
        if d.get("saved_at") is not None and not isinstance(d.get("saved_at"), str):
            raise ValueError(f"{PRESETS_NAME} 의 프리셋 {i} 저장 시각이 틀렸습니다")
        p = blank_preset(i)
        p.update(name=str(d.get("name") or p["name"]), code=str(d.get("code") or ""), saved_at=d.get("saved_at"), record=r)
        if r and p["code"] in codes:
            raise ValueError(f"{PRESETS_NAME} 의 프리셋 {codes[p['code']]} 와 {i} 이 같은 사이트코드 {p['code']} 입니다")
        codes[p["code"]] = i
        out.append(p)
    while len(out) < PRESET_MIN:
        out.append(blank_preset(len(out) + 1))
    return out


def write_presets(presets):
    """프리셋 목록을 통째로 쓴다 (번호는 순서대로 다시 매긴다). PRESET_MIN~PRESET_MAX 개가 아니면 ValueError.
    임시 파일에 다 쓴 뒤 바꿔치기한다 (반쯤 쓴 파일이 남지 않게). 쓴 목록을 돌려준다."""
    if not PRESET_MIN <= len(presets) <= PRESET_MAX:
        raise ValueError(f"프리셋은 {PRESET_MIN}~{PRESET_MAX}개입니다 ({len(presets)}개)")
    data = [{"no": i, "name": str(p.get("name") or f"프리셋 {i}"), "code": str(p.get("code") or ""),
             "saved_at": p.get("saved_at"), "record": p.get("record")} for i, p in enumerate(presets, 1)]
    path = presets_path()
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(data, ensure_ascii=False, indent=1))
        _replace_retry(tmp, path)            # 에이전트가 1초마다 읽는다
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return data


def preset_site_key(no):
    """사용자 설정 Sites 에서 프리셋 no 의 칸 이름."""
    return f"PRESET{no}"


def save_preset_sites(presets, logins, fresh=()):
    """Sites 의 PRESETn 칸을 프리셋에 맞춘다. 다른 섹션·다른 사이트는 그대로 (설정 창·에이전트가 쓴 것).
    presets: read_presets 모양. logins: {번호: (아이디, 비밀번호 또는 None = 저장된 것 그대로)}.
    기록이 있는 프리셋만 칸을 둔다 - 새 칸과 fresh (이번에 다시 기록한 번호) 는 꺼짐(Stts 9), 나머지 있던 칸의 켬/끔은 그대로
    (확인 안 한 기록이 다음 자동 실행에 끼지 않게 - 2026-10-01 검토). 기록이 없거나 빠진 번호의 칸은 지운다.
    사용자 설정이 아예 없으면 FileNotFoundError (자격증명 없는 설정을 새로 만들지 않는다 - write_routine_modules 와 같다)."""
    data = read_user_config()
    if not data:
        raise FileNotFoundError(user_config_path())
    sites = data.get(SITES_SECTION) if isinstance(data.get(SITES_SECTION), dict) else {}
    others = {k: v for k, v in sites.items() if not re.fullmatch(r"PRESET\d+", k)}
    mine = {}
    for p in presets:
        if not p.get("record"):
            continue
        key = preset_site_key(p["no"])
        old = sites.get(key) if isinstance(sites.get(key), dict) else {}
        login_id, pw = logins.get(p["no"], (old.get("ID", ""), None))
        mine[key] = {"URL": p["record"].get("start_url") or old.get("URL", ""), "ID": (login_id or "").strip(),
                     "PW": pw or old.get("PW", ""), "Action": [REPLAY_ACTION],
                     "Stts": 9 if (not old or p["no"] in fresh) else old.get("Stts", 9), "Preset": p["no"], "note": p["name"]}
    data[SITES_SECTION] = {**others, **mine}       # 프리페어는 이 순서로 돈다 (번호 순)
    write_user_config(data)


def preset_summary():
    """대시보드용 [{no, name, code, steps, saved_at, has_login, on}] - 기록 내용·아이디·비밀번호는 싣지 않는다.
    사용자 설정이 없거나 프리셋 파일이 깨졌으면 None (화면이 카드를 숨긴다 - 빈 목록으로 속이지 않는다)."""
    try:
        cfg = read_user_config()
        if not cfg:
            return None
        presets = read_presets()
    except (ValueError, OSError):
        return None
    sites = cfg.get(SITES_SECTION) if isinstance(cfg.get(SITES_SECTION), dict) else {}
    out = []
    for p in presets:
        site = sites.get(preset_site_key(p["no"]))
        site = site if isinstance(site, dict) else {}
        out.append({"no": p["no"], "name": p["name"], "code": p["code"],
                    "steps": len((p["record"] or {}).get("steps") or []), "saved_at": p["saved_at"],
                    "has_login": bool(site.get("ID")) and bool(site.get("PW")),
                    "on": str(site.get("Stts", "")).strip() == "0"})
    return out


def set_preset_switches(wanted):
    """{키: 켬} 대로 Sites 의 PRESETn 을 켠다(Stts 0)·끈다(9). 키는 "PRESET1"·"1"·1 (대시보드는 "PRESET1" -
    숫자 키는 Realtime DB 가 배열로 바꿔 읽는다). 칸이 있는 번호만 다루고, 바꾼 {번호: 켬} 을 돌려준다.
    아는 번호가 하나도 없으면 ValueError. 켜기는 기록·아이디·비밀번호가 다 있는 것만 (아니면 ValueError, 아무것도 안 바꿈)."""
    data = read_user_config()
    if not data:
        raise FileNotFoundError(user_config_path())
    sites = data.get(SITES_SECTION) if isinstance(data.get(SITES_SECTION), dict) else {}
    final = {}
    for k, v in (wanted or {}).items():
        m = _PRESET_KEY.fullmatch(str(k))
        if m and isinstance(sites.get(preset_site_key(int(m.group(1)))), dict):
            final[int(m.group(1))] = bool(v)
    if not final:
        raise ValueError("아는 프리셋이 없습니다")
    ready = {s["no"] for s in (preset_summary() or []) if s["steps"] and s["has_login"]}
    blocked = sorted(no for no, on in final.items() if on and no not in ready)
    if blocked:
        raise ValueError(f"기록이나 아이디·비밀번호가 없어 켤 수 없습니다: {', '.join(str(n) for n in blocked)}번")
    for no, on in final.items():
        sites[preset_site_key(no)]["Stts"] = 0 if on else 9
    write_user_config(data)
    return final


# ---------------------------------------------------------------------------
# 관리자 권한과 윈도우 계정 (설정 창·옵저버가 같이 쓴다)
# ---------------------------------------------------------------------------
def is_admin():
    try:
        return bool(ctypes.WinDLL("shell32").IsUserAnAdmin())
    except Exception:
        return False


def run_as_admin(exe, args, cwd):
    """exe 를 관리자 권한으로 띄운다 (UAC 요청). 띄웠으면 True, 사용자가 거절하면 False."""
    sh = ctypes.WinDLL("shell32")
    sh.ShellExecuteW.restype = ctypes.c_void_p
    sh.ShellExecuteW.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_wchar_p,
                                 ctypes.c_wchar_p, ctypes.c_int)
    return (sh.ShellExecuteW(None, "runas", exe, subprocess.list2cmdline(list(args)), cwd, 1) or 0) > 32


def process_user():
    """이 프로세스의 윈도우 계정 'PC이름\\사용자' (다른 계정 비밀번호로 권한만 올렸으면 그 계정)."""
    secur = ctypes.WinDLL("secur32")
    secur.GetUserNameExW.argtypes = (ctypes.c_int, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_uint32))
    size = ctypes.c_uint32(512)
    buf = ctypes.create_unicode_buffer(size.value)
    if secur.GetUserNameExW(2, buf, ctypes.byref(size)):                  # NameSamCompatible
        return buf.value
    return f"{os.environ.get('USERDOMAIN', '')}\\{os.environ.get('USERNAME', '')}"


def session_user():
    """이 PC 화면(지금 세션)에 로그인한 계정 'PC이름\\사용자'. 못 알아내면 None."""
    try:
        wts = ctypes.WinDLL("wtsapi32")
        wts.WTSQuerySessionInformationW.argtypes = (ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int,
                                                    ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_uint32))
        wts.WTSFreeMemory.argtypes = (ctypes.c_void_p,)
        parts = []
        for info in (7, 5):                                   # WTSDomainName, WTSUserName
            buf, size = ctypes.c_void_p(), ctypes.c_uint32()
            # 0xFFFFFFFF = WTS_CURRENT_SESSION (이 프로세스의 세션)
            if not wts.WTSQuerySessionInformationW(None, 0xFFFFFFFF, info, ctypes.byref(buf), ctypes.byref(size)):
                return None
            try:
                parts.append(ctypes.wstring_at(buf.value))
            finally:
                wts.WTSFreeMemory(buf)
        return f"{parts[0]}\\{parts[1]}" if parts[1] else None
    except Exception:
        return None


def same_account(a, b):
    return bool(a) and bool(b) and a.casefold() == b.casefold()


# ---------------------------------------------------------------------------
# 프로세스가 살아 있는지 (강제 종료 감지용)
# ---------------------------------------------------------------------------
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
STILL_ACTIVE = 259
ERROR_ACCESS_DENIED = 5
_K32 = None


def _k32():
    """kernel32 를 따로 불러와 함수 원형을 정한다.

    전역 ctypes.windll.kernel32 의 원형을 바꾸면 같은 프로세스의 pywinauto 호출이
    엉뚱하게 깨질 수 있어서, 이 모듈 전용 인스턴스에만 원형을 붙인다.
    """
    global _K32
    if _K32 is None and os.name == "nt":
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.OpenProcess.restype = ctypes.c_void_p
        k.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
        k.CloseHandle.argtypes = (ctypes.c_void_p,)
        k.GetExitCodeProcess.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32))
        k.GetProcessTimes.argtypes = (ctypes.c_void_p,) + (ctypes.POINTER(ctypes.c_uint64),) * 4
        k.CreateMutexW.restype = ctypes.c_void_p
        k.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p)
        k.OpenMutexW.restype = ctypes.c_void_p
        k.OpenMutexW.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p)
        _K32 = k
    return _K32


def process_created(pid):
    """프로세스 생성 시각(FILETIME 정수). 번호가 재사용됐는지 가리는 데 쓴다."""
    try:
        k = _k32()
        if k is None or not pid:
            return None
        h = k.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, int(pid))
        if not h:
            return None
        try:
            t = [ctypes.c_uint64() for _ in range(4)]
            if k.GetProcessTimes(h, *(ctypes.byref(x) for x in t)):
                return int(t[0].value)
            return None
        finally:
            k.CloseHandle(h)
    except Exception:
        return None


def process_alive(pid, created=None):
    """그 프로세스가 아직 살아 있으면 True, 사라졌으면 False, 알 수 없으면 None."""
    try:
        k = _k32()
        if k is None or not pid:
            return None
        h = k.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, int(pid))
        if not h:
            # 접근 거부는 '있긴 한데 권한이 없다'는 뜻이다. 없는 번호면 다른 오류가 난다.
            return ctypes.get_last_error() == ERROR_ACCESS_DENIED
        try:
            code = ctypes.c_uint32()
            if not k.GetExitCodeProcess(h, ctypes.byref(code)):
                return None
            if code.value != STILL_ACTIVE:
                return False
        finally:
            k.CloseHandle(h)
        if created:
            now_created = process_created(pid)
            if now_created is not None and now_created != int(created):
                return False   # 같은 번호를 다른 프로세스가 물려받았다
        return True
    except Exception:
        return None


# 이름 있는 잠금 (뮤텍스): 에이전트·옵저버가 'PC 에 하나만' 과 '떠 있다' 를 알린다.
# 잡은 프로세스가 끝나면 (죽어도) 윈도우가 푼다.
SYNCHRONIZE = 0x00100000
ERROR_ALREADY_EXISTS = 183
OBSERVER_LOCK = os.environ.get("RPA_OBSERVER_LOCK") or r"Local\AFTER_MARKET_RPA_OBSERVER"   # 시험은 RPA_OBSERVER_LOCK 로 따로
_LOCKS = {}        # 이름 → 이 프로세스가 잡은 잠금


def hold_lock(name):
    """이름 있는 잠금을 잡는다. 다른 프로세스가 이미 잡았으면 False.
    다른 권한(관리자)으로 만든 잠금이라 못 여는 것(접근 거부)도 '있다' 다. 그 밖의 까닭으로 못 만들면 막지 않는다
    (잠금 때문에 프로그램이 안 뜨면 안 된다). 같은 프로세스가 다시 부르면 True."""
    if name in _LOCKS:
        return True
    k = _k32()
    if k is None:
        return True
    ctypes.set_last_error(0)
    h = k.CreateMutexW(None, False, name)
    err = ctypes.get_last_error()
    if not h:
        return err != ERROR_ACCESS_DENIED
    if err == ERROR_ALREADY_EXISTS:
        k.CloseHandle(h)
        return False
    _LOCKS[name] = h
    return True


def lock_held(name):
    """누가 그 잠금을 잡고 있나. 권한 때문에 못 여는 것(접근 거부)도 '있다'."""
    k = _k32()
    if k is None:
        return False
    h = k.OpenMutexW(SYNCHRONIZE, False, name)
    if h:
        k.CloseHandle(h)
        return True
    return ctypes.get_last_error() == ERROR_ACCESS_DENIED


def observer_open():
    """옵저버가 떠 있나 (옵저버가 켤 때 hold_lock(OBSERVER_LOCK) 을 잡는다). 떠 있는 동안 대시보드는 RPA 를
    띄우지 않는다 - RPA 가 화면·마우스를 잡으면 기록하던 사람과 부딪힌다."""
    return lock_held(OBSERVER_LOCK)


# ---------------------------------------------------------------------------
# 공용 도구
# ---------------------------------------------------------------------------
def now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def parse_iso(text):
    try:
        return datetime.datetime.fromisoformat(text) if text else None
    except Exception:
        return None


def _seconds(a, b):
    if a is None or b is None:
        return None
    return max(0, int((b - a).total_seconds()))


def read_json(path):
    """덮어쓰는 순간과 겹치면 잠깐 못 읽을 수 있어 몇 번 다시 시도한다."""
    for _ in range(6):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return None
        except (PermissionError, ValueError):
            time.sleep(0.05)
        except Exception:
            return None
    return None


def write_json_atomic(path, data):
    """임시 파일에 다 쓴 뒤 바꿔치기한다. 읽는 쪽이 반쯤 쓴 파일을 보지 않게 하기 위해서다."""
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False))
        for _ in range(20):
            try:
                os.replace(tmp, path)
                return True
            except PermissionError:   # 대시보드가 막 읽고 있는 순간
                time.sleep(0.05)
    except Exception:
        pass
    return False


def history_record(state):
    """이력 한 건. 상태에서 이력에 필요한 것만 추린다."""
    started = parse_iso(state.get("started_at"))
    finished = parse_iso(state.get("finished_at"))
    keys = ("key", "label", "state", "started_at", "finished_at", "note")
    mkeys = ("key", "label", "bit", "state", "started_at", "finished_at", "reason")
    modules = []
    for m in state.get("modules") or []:
        if not isinstance(m, dict):
            continue
        item = {k: m.get(k) for k in mkeys}
        p = m.get("progress")
        item["progress"] = {k: p.get(k) for k in ("value", "total", "pct")} if isinstance(p, dict) else None
        modules.append(item)
    return {
        "schema": 2,
        "run_id": state.get("run_id"),
        "program": state.get("program"),
        "program_label": state.get("program_label"),
        "host": state.get("host"),
        "account": state.get("account"),
        "state": state.get("state"),
        "reason": state.get("reason"),
        "started_at": state.get("started_at"),
        "finished_at": state.get("finished_at"),
        "duration_sec": _seconds(started, finished),
        "steps": [{k: s.get(k) for k in keys} for s in state.get("steps") or []],
        "metrics": state.get("metrics") or [],
        "modules": modules,
        "module_flags": int(state.get("module_flags") or 0),
        "log_tail": (state.get("log_tail") or [])[-HISTORY_LOG_LINES:],
    }


def append_history(record):
    try:
        folder = status_dir()
        path = os.path.join(folder, HISTORY_NAME)
        if os.path.exists(path) and os.path.getsize(path) > HISTORY_MAX_BYTES:
            os.replace(path, os.path.join(folder, HISTORY_OLD_NAME))
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return True
    except Exception:
        return False


def record_start_failure(program, started_at, reason, log_tail=()):
    """프로그램이 기록을 시작하기도 전에 끝났다 (띄운 쪽이 부른다). 이력만 남기고 상태 파일은 건드리지 않는다."""
    stamp = (parse_iso(started_at) or datetime.datetime.now()).strftime("%Y%m%d_%H%M%S")
    return append_history(history_record({
        "run_id": f"{program}_{stamp}_nostart", "program": program, "program_label": LABELS.get(program, program),
        "host": socket.gethostname(), "state": "crashed", "reason": reason,
        "started_at": started_at, "finished_at": now_iso(), "log_tail": list(log_tail),
    }))


def read_history(limit=0, program=None, since=None):
    """이력을 최신순으로 돌려준다. since 는 'YYYY-MM-DDTHH:MM:SS' 문자열."""
    folder = status_dir(create=False)
    rows = []
    for name in (HISTORY_OLD_NAME, HISTORY_NAME):
        try:
            with open(os.path.join(folder, name), "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rows.append(json.loads(line))
                    except ValueError:
                        continue   # 쓰다 만 줄은 건너뛴다
        except FileNotFoundError:
            continue
        except Exception:
            continue
    if program:
        rows = [r for r in rows if r.get("program") == program]
    if since:
        rows = [r for r in rows if (r.get("started_at") or "") >= since]
    rows.sort(key=lambda r: r.get("started_at") or "", reverse=True)
    return rows[:limit] if limit else rows


# ---------------------------------------------------------------------------
# 기록하는 쪽 (RPA 프로그램이 부른다)
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_state = None
_path = None
_tail = deque(maxlen=LOG_TAIL_LINES)
_dirty = False
_last_write = 0.0
_finished = True
_last_problem = None
_heart = None
_stop = threading.Event()


def _safe(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception:
            return None
    return wrapper


def _active():
    return _state is not None and not _finished


def _find_step(key):
    if _state is None or key is None:
        return None
    return next((s for s in _state["steps"] if s["key"] == key), None)


def _new_step(key, label):
    return {"key": str(key), "label": str(label), "state": "pending",
            "started_at": None, "finished_at": None, "note": None}


def _new_module(key, label, steps, bit):
    return {"key": str(key), "label": str(label), "bit": int(bit), "steps": [str(s) for s in steps],
            "state": "pending", "started_at": None, "finished_at": None, "reason": None, "progress": None}


def _find_module(key):
    if _state is None or key is None:
        return None
    return next((m for m in _state.get("modules") or [] if m["key"] == key), None)


def last_problem():
    """로그에서 마지막으로 잡힌 문제 문구 (중단 사유가 따로 없을 때 쓴다)."""
    return _last_problem


def _write_locked():
    global _dirty, _last_write
    if _state is None or _path is None:
        return
    _state["log_tail"] = list(_tail)
    if write_json_atomic(_path, _state):
        _dirty = False
        _last_write = time.time()


def _touch_locked(immediate=False, progress=True):
    global _dirty
    now = now_iso()
    _state["updated_at"] = now
    if progress:
        _state["progress_at"] = now
    _dirty = True
    if immediate or time.time() - _last_write >= MIN_WRITE_GAP:
        _write_locked()


def _heartbeat():
    while not _stop.wait(1.0):
        try:
            with _lock:
                if not _active():
                    continue
                if _dirty or time.time() - _last_write >= HEARTBEAT_SECONDS:
                    _state["updated_at"] = now_iso()
                    _write_locked()
        except Exception:
            pass


def _on_exit():
    # main() 이 중간에 return 해 버리면 finish 를 부르지 못한다. 그런 경우 '중단'으로 닫는다.
    if _active():
        finish("stopped")
    _stop.set()


@_safe
def start(program, steps=(), title=None):
    """실행 기록을 시작한다. 같은 프로그램의 이전 상태 파일은 덮어쓴다."""
    global _state, _path, _finished, _last_problem, _heart
    with _lock:
        now = now_iso()
        pid = os.getpid()
        _tail.clear()
        _last_problem = None
        _state = {
            "schema": 2,   # 2 = modules / module_flags 키가 있다 (빈 목록일 수 있음)
            "run_id": f"{program}_{datetime.datetime.now():%Y%m%d_%H%M%S}_{pid}",
            "program": program,
            "program_label": LABELS.get(program, program),
            "title": title,
            "state": "running",
            "reason": None,
            "host": socket.gethostname(),
            "account": None,
            "pid": pid,
            "pid_created": process_created(pid),
            "started_at": now,
            "updated_at": now,
            "progress_at": now,
            "finished_at": None,
            "current": None,
            "note": None,
            "steps": [],
            "metrics": [],
            "modules": [],
            "module_flags": 0,
            "current_module": None,
            "log_tail": [],
        }
        _state["steps"] = [_new_step(*_split_step(s)) for s in steps or ()]
        _path = status_path(program)
        _finished = False
        _write_locked()
    if _heart is None:
        _stop.clear()
        _heart = threading.Thread(target=_heartbeat, name="rpa-status", daemon=True)
        _heart.start()
        atexit.register(_on_exit)


def _split_step(s):
    if isinstance(s, (list, tuple)):
        return s[0], (s[1] if len(s) > 1 else s[0])
    return s, s


@_safe
def set_steps(steps):
    """단계 목록을 나중에 정한다 (설정을 읽어야 단계를 알 수 있는 경우)."""
    with _lock:
        if not _active():
            return
        _state["steps"] = [_new_step(*_split_step(s)) for s in steps or ()]
        _touch_locked(immediate=True)


# ---------------------------------------------------------------------------
# 모듈 (화면 단위 묶음). 단계(step)보다 큰 단위로 '어디까지 끝났는지' 를 남긴다.
#   modules[].state : pending / running / done / no_target / skipped / failed / stopped / off
#   module_flags    : 끝난 모듈의 비트를 OR 한 정수. 비트는 set_modules 에 넘긴 값 그대로다
#                     (루틴: login=1 sales=2 hold=4 logistics=8 output=16). 새 모듈은 다음 빈 비트를
#                     쓰고 기존 비트는 바꾸지 않는다 - 이력의 정수 의미가 바뀌면 안 된다.
#                     done·no_target·skipped 만 센다 (그 모듈은 더 할 일이 없다는 뜻).
#                     failed·stopped·off 는 세지 않는다.
#   progress        : 지금 도는 모듈 안의 진행 {value, total, pct} (건수가 있는 작업만)
# ---------------------------------------------------------------------------
MODULE_RESULTS = ("done", "no_target", "skipped", "failed", "stopped")
_MODULE_COMPLETE = ("done", "no_target", "skipped")
_MODULE_STEP_END = {"done": "done", "no_target": "done", "skipped": "skipped",
                    "failed": "failed", "stopped": "stopped"}


@_safe
def set_modules(modules):
    """모듈 목록 [(key, label, step_keys, bit), ...]."""
    with _lock:
        if not _active():
            return
        _state["modules"] = [_new_module(k, l, steps, bit) for k, l, steps, bit in modules or ()]
        _state["module_flags"] = 0
        _state["current_module"] = None
        _touch_locked(immediate=True)


@_safe
def module_start(key):
    global _last_problem
    with _lock:
        if not _active():
            return
        m = _find_module(key)
        if m is None:
            return
        _last_problem = None   # 앞 모듈에서 복구된 경고가 이 모듈의 사유로 붙지 않게
        m.update(state="running", started_at=now_iso(), finished_at=None, reason=None, progress=None)
        _state["current_module"] = key
        _touch_locked(immediate=True)


@_safe
def module_done(key, result, reason=None):
    """모듈을 닫는다. 지금 running 인 단계도 같은 결과로 닫는다.

    모듈의 마지막 단계는 다음 step() 이 불릴 때까지 running 으로 남기 때문에,
    여기서 닫지 않으면 '모듈은 끝났는데 단계는 진행 중' 인 상태가 된다.
    """
    with _lock:
        if not _active():
            return
        m = _find_module(key)
        if m is None:
            return
        if result not in MODULE_RESULTS:
            result = "failed"
        now = now_iso()
        m.update(state=result, finished_at=now, reason=reason)
        if result in _MODULE_COMPLETE:
            _state["module_flags"] = int(_state.get("module_flags") or 0) | int(m["bit"])
        end = _MODULE_STEP_END[result]
        for s in _state["steps"]:
            if s["state"] == "running":
                s["state"] = end
                s["finished_at"] = now
                if reason and end != "done":
                    s["note"] = reason
        if _state.get("current_module") == key:
            _state["current_module"] = None
        _touch_locked(immediate=True)


@_safe
def module_off(key, reason=None):
    """설정에서 꺼서 돌리지 않는 모듈. 비트는 세우지 않는다."""
    with _lock:
        if not _active():
            return
        m = _find_module(key)
        if m is None:
            return
        m.update(state="off", reason=reason, progress=None)
        _touch_locked(immediate=True)


@_safe
def progress(value, total, note=None):
    """지금 도는 모듈 안에서 얼마나 진행됐는지 (예: 재고검토 3/10)."""
    with _lock:
        if not _active():
            return
        m = _find_module(_state.get("current_module"))
        if m is None:
            return
        try:
            pct = max(0, min(100, int(round(100.0 * float(value) / float(total))))) if total else None
        except (TypeError, ValueError, ZeroDivisionError):
            pct = None
        m["progress"] = {"value": value, "total": total, "pct": pct, "note": note, "updated_at": now_iso()}
        _touch_locked()


@_safe
def step(key, note=None, label=None):
    """이 단계를 시작한다. 진행 중이던 단계는 완료로, 건너뛴 앞 단계는 '건너뜀'으로 표시한다."""
    with _lock:
        if not _active():
            return
        now = now_iso()
        steps = _state["steps"]
        target = _find_step(key)
        if target is None:
            target = _new_step(key, label or key)
            steps.append(target)
        index = steps.index(target)
        for i, s in enumerate(steps):
            if s is target:
                continue
            if s["state"] == "running":
                s["state"] = "done"
                s["finished_at"] = now
            if i < index and s["state"] == "pending":
                s["state"] = "skipped"
        target.update(state="running", started_at=now, finished_at=None, note=note)
        cur = _find_module(_state.get("current_module"))
        if cur is not None:
            cur["progress"] = None   # 단계가 바뀌면 이전 단계의 진행률은 뜻이 없다
        _state["current"] = target["key"]
        _state["note"] = note
        _touch_locked(immediate=True)


@_safe
def account(admin_code, user_id):
    """어느 계정으로 로그인하는지 알린다. 비밀번호는 절대 넘기지 말 것."""
    with _lock:
        if not _active():
            return
        _state["account"] = {"admin_code": str(admin_code or ""), "user_id": str(user_id or "")}
        _touch_locked(immediate=True, progress=False)


@_safe
def note(text):
    """지금 단계에서 무엇을 하고 있는지 한 줄로 알린다."""
    with _lock:
        if not _active():
            return
        _state["note"] = text
        current = _find_step(_state.get("current"))
        if current is not None:
            current["note"] = text
        _touch_locked()


@_safe
def skip(key, note=None):
    with _lock:
        if not _active():
            return
        s = _find_step(key)
        if s is not None and s["state"] == "pending":
            s["state"] = "skipped"
            s["note"] = note
            _touch_locked(immediate=True)


@_safe
def done_step():
    """지금 단계를 끝냈다 - 다음 단계 없이 끝나는 마지막 사이트처럼. 실행이 '중단' 으로 끝나도 이 단계는 완료로 남는다
    (전엔 finish 가 '중단' 으로 덮어 기록 탭에 실패로 보였고 토큰 셈에서도 빠졌다, 2026-10-06)."""
    with _lock:
        if not _active():
            return
        s = _find_step(_state.get("current"))
        if s is not None and s["state"] == "running":
            s.update(state="done", finished_at=now_iso())
        _touch_locked(immediate=True)


@_safe
def fail_step(note=None):
    """지금 단계가 실패했다 (프로그램은 계속 돈다)."""
    with _lock:
        if not _active():
            return
        s = _find_step(_state.get("current"))
        if s is not None and s["state"] == "running":
            s.update(state="failed", finished_at=now_iso(), note=note)
        _touch_locked(immediate=True)


@_safe
def metric(key, label, value, total=None, unit="건", note=None, approx=False):
    """처리 건수 같은 숫자를 알린다. 같은 key 로 다시 부르면 값만 바뀐다."""
    with _lock:
        if not _active():
            return
        m = next((x for x in _state["metrics"] if x.get("key") == key), None)
        if m is None:
            m = {"key": key, "step": _state.get("current")}
            _state["metrics"].append(m)
        m.update(label=label, value=value, total=total, unit=unit, note=note,
                 approx=bool(approx), updated_at=now_iso())
        _touch_locked()


@_safe
def log_line(line):
    """로그 한 줄. 최근 로그로 보여주고, 중단 사유를 짐작하는 데도 쓴다."""
    global _last_problem
    with _lock:
        if not _active():
            return
        text = str(line).rstrip()
        if not text.strip():
            return
        _tail.append(text)
        body = _TIME_PREFIX.sub("", text).strip()
        if not body.startswith("===") and any(w in body for w in PROBLEM_WORDS):
            _last_problem = body
        _touch_locked(progress=True)


@_safe
def finish(result, reason=None):
    """실행을 닫고 이력에 남긴다. result: success / stopped / crashed"""
    global _finished
    with _lock:
        if not _active():
            return
        if result not in ("success", "stopped", "crashed"):
            result = "stopped"
        now = now_iso()
        if reason is None and result != "success":
            reason = _last_problem or "끝까지 진행하지 못하고 종료되었습니다."
        end_state = {"success": "done", "stopped": "stopped", "crashed": "failed"}[result]
        for m in _state.get("modules") or []:
            if m["state"] == "running":
                m["state"] = end_state
                m["finished_at"] = now
                if end_state == "done":
                    _state["module_flags"] = int(_state.get("module_flags") or 0) | int(m["bit"])
                elif reason:
                    m["reason"] = reason
        _state["current_module"] = None
        for s in _state["steps"]:
            if s["state"] == "running":
                s["state"] = end_state
                s["finished_at"] = now
            elif result == "success" and s["state"] == "pending":
                s["state"] = "skipped"
        _state.update(state=result, reason=reason, finished_at=now, updated_at=now)
        if result == "success":
            _state["current"] = None
            _state["note"] = None
        _write_locked()
        append_history(history_record(_state))
        _finished = True


@_safe
def fail_exception(exc):
    """main() 밖으로 예외가 새어 나왔을 때 부른다."""
    if isinstance(exc, SystemExit):
        return
    if isinstance(exc, KeyboardInterrupt):
        finish("stopped", "사용자가 중지했습니다 (Ctrl+C)")
        return
    with _lock:
        if _active():
            lines = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            for ln in lines.strip().splitlines()[-12:]:
                _tail.append(ln)
    finish("crashed", f"프로그램 오류 - {type(exc).__name__}: {exc}")


@_safe
def flush():
    with _lock:
        if _active():
            _write_locked()


# ---------------------------------------------------------------------------
# 읽는 쪽 (대시보드가 부른다)
# ---------------------------------------------------------------------------
_reap_lock = threading.Lock()


def _mark_vanished(path, seen):
    """'진행 중'으로 남은 채 프로세스가 사라진 실행을 '비정상 종료'로 닫고 이력에 남긴다."""
    with _reap_lock:
        cur = read_json(path)
        if not cur or cur.get("run_id") != seen.get("run_id") or cur.get("state") != "running":
            return cur or seen
        if process_alive(cur.get("pid"), cur.get("pid_created")) is not False:
            return cur
        end = cur.get("updated_at") or now_iso()   # 마지막으로 살아 있던 시각
        for s in cur.get("steps") or []:
            if s.get("state") == "running":
                s["state"] = "failed"
                s["finished_at"] = end
                s["note"] = s.get("note") or "여기서 멈췄습니다"
        for m in cur.get("modules") or []:
            if m.get("state") == "running":
                m["state"] = "failed"
                m["finished_at"] = end
                m["reason"] = m.get("reason") or "여기서 멈췄습니다"
        cur.update(state="crashed", reason=VANISHED_REASON, finished_at=end, current_module=None)
        write_json_atomic(path, cur)
        append_history(history_record(cur))
        return cur


def decorate(state):
    """화면에 바로 쓸 수 있게 경과 시간 등을 계산해 붙인다. (시간대 차이를 없애려고 서버에서 계산)"""
    now = datetime.datetime.now()
    view = dict(state)
    started = parse_iso(state.get("started_at"))
    finished = parse_iso(state.get("finished_at"))
    running = state.get("state") == "running"
    view["elapsed_sec"] = _seconds(started, finished or now)
    view["age_sec"] = _seconds(parse_iso(state.get("updated_at")), now)
    view["idle_sec"] = _seconds(parse_iso(state.get("progress_at")), now) if running else None
    steps = []
    for s in state.get("steps") or []:
        item = dict(s)
        a = parse_iso(s.get("started_at"))
        b = parse_iso(s.get("finished_at"))
        item["duration_sec"] = _seconds(a, b or (now if s.get("state") == "running" else None))
        steps.append(item)
    view["steps"] = steps
    # 설정에서 끈 모듈의 단계는 '할 일' 이 아니므로 분모·분자 어느 쪽에도 넣지 않는다
    counted = [s for s in steps if not (s.get("state") == "skipped" and s.get("note") == OFF_NOTE)]
    view["steps_total"] = len(counted)
    view["steps_done"] = sum(1 for s in counted if s.get("state") in ("done", "skipped"))
    # 각 지표(metric)에 그 지표가 기록된 단계의 '경과 시간'을 붙인다.
    # (화면에서는 처리 건수 대신 이 경과 시간을 보여준다 - 건수는 '화면에 보이는 행' 이라 쓸모가 적다)
    stepdur = {s.get("key"): s.get("duration_sec") for s in steps}
    metrics = []
    for m in state.get("metrics") or []:
        mm = dict(m)
        mm["duration_sec"] = stepdur.get(m.get("step"))
        metrics.append(mm)
    view["metrics"] = metrics
    # 모듈별로 '몇 단계 중 몇 단계가 끝났는지' 와 퍼센트를 붙인다.
    #   끝난 모듈 = 100, 설정에서 끈 모듈 = None,
    #   도는 중이면 건수 진행(progress.pct)이 있으면 그것, 없으면 단계 수 비율.
    stepstate = {s.get("key"): s.get("state") for s in steps}
    modules = []
    for m in state.get("modules") or []:
        mm = dict(m)
        keys = m.get("steps") or []
        done = sum(1 for k in keys if stepstate.get(k) in ("done", "skipped"))
        mm["steps_total"] = len(keys)
        mm["steps_done"] = done
        p = m.get("progress") or {}
        if m.get("state") == "off":
            mm["pct"] = None
        elif m.get("state") in ("done", "no_target", "skipped"):
            mm["pct"] = 100
        elif p.get("pct") is not None:
            mm["pct"] = max(0, min(100, int(p["pct"])))
        else:
            mm["pct"] = int(round(100.0 * done / len(keys))) if keys else 0
        a = parse_iso(m.get("started_at"))
        b = parse_iso(m.get("finished_at"))
        mm["duration_sec"] = _seconds(a, b or (now if m.get("state") == "running" else None))
        modules.append(mm)
    view["modules"] = modules
    current = next((s for s in steps if s.get("key") == state.get("current")), None)
    view["current_label"] = current.get("label") if current else None
    view["current_index"] = counted.index(current) + 1 if current in counted else None
    return view


def dashboard_snapshot():
    programs = {}
    for program in PROGRAMS:
        path = status_path(program)
        state = read_json(path)
        alive = None
        if state and state.get("state") == "running":
            alive = process_alive(state.get("pid"), state.get("pid_created"))
            if alive is False:
                state = _mark_vanished(path, state)
        if state:
            view = decorate(state)
            view["alive"] = alive
            programs[program] = view
        else:
            programs[program] = None
    return {
        "server_time": now_iso(),
        "host": socket.gethostname(),
        "labels": PROGRAMS,
        "programs": programs,
    }


def running_programs(snapshot=None):
    """지금 도는 RPA (PROGRAMS 의 키) 목록. 대시보드 실행·자동 실행·옵저버가 본다."""
    snap = snapshot or dashboard_snapshot()
    return [p for p, v in snap["programs"].items() if v and v.get("state") == "running"]
