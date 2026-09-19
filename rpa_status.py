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
import ctypes
import datetime
import functools
import json
import os
import re
import socket
import threading
import time
import traceback
from collections import deque

try:
    import winreg
except ImportError:  # 윈도우가 아닌 곳에서 대시보드 화면만 시험할 때
    winreg = None

PROGRAMS = {"prepare": "프리페어 RPA", "routine": "루틴 RPA"}

AI_DIR_NAME = "ERPIA_AI"
STATUS_DIR_NAME = "RPA_STATUS"
HISTORY_NAME = "history.jsonl"
HISTORY_OLD_NAME = "history.1.jsonl"
HISTORY_MAX_BYTES = 5 * 1024 * 1024
SETTINGS_NAME = "settings.json"      # 대시보드 환경설정 (자동 실행 주기 등)
CRED_FILE_NAME = "ERPIA_AI.txt"      # 업체코드/아이디만 읽는다. 비밀번호는 절대 읽어 돌려주지 않는다.
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


def _decode_any(raw):
    """바이트를 utf-8-sig -> cp949 -> utf-16 순서로 풀어 본다. 못 풀면 None."""
    for encoding in ("utf-8-sig", "cp949", "utf-16"):
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return None


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
    """ERPIA_AI.txt 의 업체코드(AdminCode)와 아이디(ID)만 읽는다.

    비밀번호는 읽지 않는다. 대시보드는 로그인 없이 사내망 누구나 보는 화면이라
    이 함수가 돌려주는 값은 그대로 화면에 나간다고 생각해야 한다.
    """
    path = cred_file_path()
    if os.path.isfile(path):
        try:
            text = _read_text_any(path)
            top = _flatten(json.loads(text)) if text else {}
            login = _flatten(top.get("LogIn")) if isinstance(top.get("LogIn"), (dict, list)) else {}
            for k, v in top.items():
                if not isinstance(v, (dict, list)):
                    login.setdefault(k, v)   # 섹션 없이 키가 바로 있던 옛 형태
            return {"admin_code": str(login.get("AdminCode") or ""),
                    "user_id": str(login.get("ID") or "")}
        except Exception:
            return None
    return None



# ---------------------------------------------------------------------------
# 루틴 RPA 의 실행 모듈 설정 (ERPIA_AI.txt 의 "Routine" 섹션)
#
# 대시보드 환경설정에서 관리자가 켜고 끈다. 이 파일에는 ERPia 비밀번호가 평문으로 들어 있으므로
#   - 읽을 때는 Routine 섹션의 값만 꺼내고 나머지는 절대 밖으로 내보내지 않는다
#   - 쓸 때는 파일 전체를 읽어 Routine 항목만 제자리에서 바꾸고, 나머지(비밀번호 포함)는 그대로 둔다
#   - 쓰기 전에 같은 폴더에 .bak 을 남기고, 임시 파일에 다 쓴 뒤 바꿔치기한다 (반쯤 쓴 파일이 남지 않게)
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


def _routine_section(data):
    """파일 JSON 에서 Routine 섹션 값을 찾는다. (담고 있는 dict, 없으면 None)"""
    if isinstance(data, dict):
        return data if ROUTINE_SECTION in data else None
    if isinstance(data, list):
        found = None
        for item in data:
            if isinstance(item, dict) and ROUTINE_SECTION in item:
                found = item      # 여럿이면 마지막 것 (루틴의 _flatten 도 뒤의 것이 이긴다)
        return found
    return None


def _merge_routine_section(existing, final):
    """기존 Routine 섹션에서 아는 키만 Y/N 으로 바꾸고, 모르는 키는 그대로 둔다. 없던 키는 뒤에 붙인다.

    모르는 키를 지우지 않는 이유: 루틴이 '모르는 키' 경고를 내 주는데, 대시보드가 조용히 지워 버리면
    사용자가 오타를 알 길이 없어진다. 형식(단일 키 dict 목록 / dict)은 있던 대로 유지한다.
    """
    known = {k: ("Y" if final[k] else "N") for k in final}
    if isinstance(existing, dict):
        out = dict(existing)
        out.update(known)
        return out
    items = []
    seen = set()
    for item in (existing if isinstance(existing, list) else []):
        if isinstance(item, dict):
            new = {}
            for k, v in item.items():
                new[k] = known.get(k, v)
                if k in known:
                    seen.add(k)
            items.append(new)
        else:
            items.append(item)
    for k in final:
        if k not in seen:
            items.append({k: known[k]})
    return items


def read_routine_modules(path=None):
    """Routine 섹션을 {설정 키: True/False/None} 으로 읽는다. (선택, 문제 목록)

    키가 없으면 True(켬). 값이 Y/N 이 아니면 None 으로 두고 문제 목록에 적는다
    (루틴은 그런 값이면 돌지 않는다 - 화면에서 '잘못됨' 으로 보여 주기 위해).
    파일이 없거나 못 읽으면 전부 None 과 문제 한 줄.
    """
    path = path or cred_file_path()
    keys = [k for k, _ in ROUTINE_CONFIG_MODULES]
    try:
        text = _read_text_any(path)
        data = json.loads(text) if text else None
    except Exception as e:
        return {k: None for k in keys}, [f"{os.path.basename(path)} 을(를) 읽지 못했습니다: {type(e).__name__}"]
    if data is None:
        return {k: None for k in keys}, [f"{os.path.basename(path)} 이(가) 없거나 비어 있습니다"]
    holder = _routine_section(data)
    raw_section = holder.get(ROUTINE_SECTION) if holder else None
    if holder and not isinstance(raw_section, (dict, list)):
        # {"Routine": "Y"} 처럼 섹션이 아니라 값으로 쓴 경우. 루틴은 이 파일로 돌지 않는다.
        return ({k: None for k in keys},
                [f"'{ROUTINE_SECTION}' 은 값이 아니라 섹션이어야 합니다 (예: [{{\"Login\": \"Y\"}}, ...])"])
    section = _flatten(raw_section) if holder else {}
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
    """Routine 섹션만 바꿔 쓴다. 나머지(비밀번호 포함)는 손대지 않는다. 새로 쓴 {키: True/False} 를 돌려준다.

    selected: {설정 키: True/False}. 모르는 키는 ValueError. 빠진 키는 켬(Y)으로 쓴다.
    파일 형식: 최상위가 [{"LogIn": [...]}, {"Logistic": [...]}, ...] 목록이면 Routine 항목을 제자리에서
    바꾸거나 끝에 붙이고, 최상위가 dict 면 키를 바꾼다. 그 밖의 형식은 ValueError.
    """
    keys = [k for k, _ in ROUTINE_CONFIG_MODULES]
    unknown = sorted(set(selected) - set(keys))
    if unknown:
        raise ValueError(f"모르는 모듈 키: {', '.join(unknown)}")
    final = {k: bool(selected.get(k, True)) for k in keys}
    section = [{k: ("Y" if final[k] else "N")} for k in keys]

    path = path or cred_file_path()
    raw = open(path, "rb").read()          # 한 번만 읽는다 (.bak 도 이 바이트 그대로). 없으면 FileNotFoundError
    text = _decode_any(raw)
    if text is None:
        raise ValueError(f"{os.path.basename(path)} 의 인코딩을 알 수 없습니다")
    data = json.loads(text)

    if isinstance(data, list):
        holder = _routine_section(data)
        if holder is None:
            data.append({ROUTINE_SECTION: section})
        else:
            holder[ROUTINE_SECTION] = _merge_routine_section(holder.get(ROUTINE_SECTION), final)
    elif isinstance(data, dict):
        data[ROUTINE_SECTION] = _merge_routine_section(data.get(ROUTINE_SECTION), final)
    else:
        raise ValueError(f"{os.path.basename(path)} 의 JSON 최상위가 객체도 배열도 아닙니다")

    with open(path + ".bak", "wb") as f:
        f.write(raw)
    # 임시 파일에도 비밀번호가 들어가므로, 바꿔치기가 실패하면 반드시 지운다.
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        # 메모장 기본(BOM 없는 UTF-8)으로 쓴다. 루틴은 utf-8-sig 로 먼저 읽으므로 BOM 이 없어도 읽는다.
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(data, ensure_ascii=False, indent=2))
            f.write("\n")
        last = None
        for _ in range(5):
            try:
                os.replace(tmp, path)
                last = None
                break
            except PermissionError as e:   # 루틴이나 메모장이 막 읽고 있는 순간
                last = e
                time.sleep(0.1)
        if last is not None:
            raise last
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
    return final

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
            "program_label": PROGRAMS.get(program, program),
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
