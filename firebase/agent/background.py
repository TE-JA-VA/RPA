"""에이전트 감독 (배포판 구조 2부 5절 - docs/superpowers/specs/2026-09-29-installer-design.md).

설치 마법사가 등록한 작업(AFTER MARKET\\RPA Agent)이 윈도우 로그인 때 pythonw 로 띄운다 - 창이 없다.
에이전트(agent.py)를 창 없는 python.exe 로 띄우고, 오류로 죽으면 잠시 뒤 다시 켠다. 사람이 고쳐야 하는 멈춤
(설정 없음·인증 멈춤·이미 돌고 있음)은 다시 켜지 않고 같이 끝난다 - 다음 윈도우 로그인이나 'RPA 설정' 저장 때 다시 켜진다.

에이전트는 이 프로세스의 잡(job)에 넣는다. 감독이 죽으면(작업 끝내기 포함) 에이전트도 같이 죽고, 에이전트가 띄운
RPA 는 잡에서 빠져 끝까지 간다 (2026-09-29 실제 작업으로 확인 - 설계 5절). 에이전트 코드는 불러오지 않는다 -
에이전트 파일이 깨져도 감독은 살아서 까닭을 남긴다. 시험: tests/test_background.py
"""
import ctypes
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
# 다시 켜지 않는 에이전트 종료 코드 (agent.main 의 약속). 그 밖(오류 1, 강제 종료 등)은 다시 켠다
STOP_CODES = {
    0: "정상으로 끝났습니다",
    2: "설정이 없거나 깨졌습니다. 'RPA 설정' 에서 설정을 마치세요",
    3: "로그인이 막혔습니다 (기계 계정 비밀번호가 바뀌었거나 계정이 막힘). 'RPA 설정' 에서 비밀번호를 다시 넣으세요",
    4: "이 PC 에서 에이전트가 이미 돌고 있습니다",
}
BACKOFF = (10, 30, 60, 120, 300)     # 다시 켜기 전 기다림(초). 잇따라 죽을수록 길게
HEALTHY_SEC = 600                     # 이만큼 넘게 돌다 죽었으면 처음 기다림부터
LOG_NAME = "에이전트_기록.txt"          # agent.log 와 같은 파일
ERR_NAME = "에이전트_오류.txt"          # 에이전트의 오류 출력 (죽은 까닭)
ERR_MAX = 1024 * 1024
STOP_NAME = "에이전트_멈춤.json"        # 다시 켜지 않고 끝난 까닭 {code, reason, at} - 설정 창이 보여 준다. 켤 때 지운다
CREATE_NO_WINDOW = 0x08000000
JOB_LIMITS = 0x2000 | 0x1000           # KILL_ON_JOB_CLOSE | SILENT_BREAKAWAY_OK
JOB_EXTENDED_LIMIT_INFORMATION = 9


class _Basic(ctypes.Structure):          # JOBOBJECT_BASIC_LIMIT_INFORMATION
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", ctypes.c_uint32), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", ctypes.c_uint32),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", ctypes.c_uint32), ("SchedulingClass", ctypes.c_uint32)]


class _Extended(ctypes.Structure):       # JOBOBJECT_EXTENDED_LIMIT_INFORMATION
    _fields_ = [("Basic", _Basic), ("IoInfo", ctypes.c_uint64 * 6), ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t)]


def _k32():
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateJobObjectW.restype = ctypes.c_void_p
    k.CreateJobObjectW.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p)
    k.SetInformationJobObject.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32)
    k.AssignProcessToJobObject.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
    return k


def make_job():
    """감독이 닫히면 안의 프로세스를 끝내고, 안의 프로세스가 띄우는 자식은 빼 주는 잡. 못 만들면 None
    (그래도 감독은 돈다 - 작업을 끝낼 때 에이전트가 남을 수 있을 뿐)."""
    try:
        k = _k32()
        job = k.CreateJobObjectW(None, None)
        if not job:
            return None
        info = _Extended()
        info.Basic.LimitFlags = JOB_LIMITS
        if not k.SetInformationJobObject(job, JOB_EXTENDED_LIMIT_INFORMATION, ctypes.byref(info), ctypes.sizeof(info)):
            return None
        return job
    except Exception:
        return None


def put_in_job(job, proc):
    """에이전트 프로세스를 잡에 넣는다. 넣었으면 True."""
    try:
        return bool(job) and bool(_k32().AssignProcessToJobObject(job, int(proc._handle)))
    except Exception:
        return False


def log_dir():
    """에이전트 기록과 같은 폴더 (agent._data_dir 와 같은 규칙, 시험은 RPA_AGENT_QUEUE 의 폴더). 못 정하면 이 파일 옆."""
    queue = os.environ.get("RPA_AGENT_QUEUE")
    if queue:
        return os.path.dirname(queue)
    try:
        root = os.path.abspath(os.path.join(HERE, "..", ".."))
        if root not in sys.path:
            sys.path.insert(0, root)
        import rpa_status as st
        return st.data_dir() if st.new_layout() else HERE
    except Exception:
        return HERE


def log(folder, text):
    """에이전트 기록 파일에 '감독:' 줄을 덧붙인다. 실패해도 멈추지 않는다 (pythonw 라 찍을 곳이 없다)."""
    try:
        with open(os.path.join(folder, LOG_NAME), "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  감독: {text}\n")
    except Exception:
        pass


# 설치 판의 내장 파이썬 사본 (tools/build_release.py 가 만든다) - 작업 관리자에 'Python' 대신 AFTER MARKET 으로 보인다
SUPERVISOR_EXE = "AFTER_MARKET_RPA_Supervisor.exe"   # pythonw 사본 (창 없음) - 작업이 이것으로 이 파일을 띄운다
AGENT_EXE = "AFTER_MARKET_RPA_Agent.exe"             # python 사본 (콘솔 프로그램)


def agent_command(exe_dir=None):
    """창 없이 띄울 에이전트 명령. 감독 옆 AFTER MARKET 사본, 없으면 python.exe (둘 다 내장 파이썬) - 콘솔 프로그램이라
    입출력이 있다."""
    exe_dir = exe_dir or os.path.dirname(sys.executable)
    for name in (AGENT_EXE, "python.exe"):
        py = os.path.join(exe_dir, name)
        if os.path.isfile(py):
            return [py, os.path.join(HERE, "agent.py")]
    return [sys.executable, os.path.join(HERE, "agent.py")]


def start_agent(cmd, folder):
    """에이전트를 창 없이 띄운다. 입력은 곧바로 닫는 파이프 - 사람에게 묻지 않는다 (DEVNULL 은 윈도우에서 문자 장치라
    isatty() 가 참이 되어, 에이전트가 사람이 있는 줄 알고 ERPia 고르기 창 같은 것을 보이지 않게 띄우고 멈춘다.
    2026-09-29 시험에서 잡음). 출력 UTF-8 (파일로 돌리면 CP949 로 찍다 못 찍는 글자에서 죽는다), 오류 출력은 파일에."""
    err_path = os.path.join(folder, ERR_NAME)
    try:
        if os.path.getsize(err_path) > ERR_MAX:
            os.replace(err_path, err_path + ".1")
    except OSError:
        pass
    with open(err_path, "ab") as err:
        proc = subprocess.Popen(cmd, cwd=HERE, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=err,
                                env=dict(os.environ, PYTHONUTF8="1"), creationflags=CREATE_NO_WINDOW)
    proc.stdin.close()
    return proc


# 윈도우 루트 인증서 채우기 (2026-09-29 샌드박스에서 찾음). 갓 설치한 윈도우는 루트 인증서를 다 갖고 있지 않고, 윈도우 자신의
# 통신(schannel)이 필요할 때 받아 온다. 파이썬(OpenSSL)은 저장소에 이미 있는 것만 봐서 Firebase 에 CERTIFICATE_VERIFY_FAILED
# 로 못 붙는다 - 그래서 파이썬이 처음 붙기 전에 PowerShell(schannel)로 한 번씩 찔러 윈도우가 받아 오게 한다.
# 파이썬 urllib 은 처음 붙을 때 읽은 인증서를 다시 안 읽으므로(3.12+) 에이전트를 켜기 전에 해야 한다.
ROOT_WARM_URLS = ("https://identitytoolkit.googleapis.com/", "https://securetoken.googleapis.com/",
                  "https://firestore.googleapis.com/",
                  "https://rpa-test-f02e0-default-rtdb.asia-southeast1.firebasedatabase.app/.json")


def warm_windows_roots(urls=ROOT_WARM_URLS, timeout=10, run=subprocess.run):
    """윈도우가 Firebase 주소의 루트 인증서를 받아 두게 한다. 응답(404·401 등)은 보지 않는다. 못 해도 조용히 넘어간다
    (인터넷이 없으면 에이전트가 원래대로 다시 붙으려 한다)."""
    # 3072 = TLS 1.2 (옛 Windows 10 의 PowerShell 5.1 은 기본이 TLS 1.0 이라 Google 에 못 붙는다)
    script = "[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor 3072; " + "; ".join(
        f"try {{ Invoke-WebRequest -Uri '{u}' -UseBasicParsing -TimeoutSec {timeout} | Out-Null }} catch {{ }}" for u in urls)
    try:
        run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout * len(urls) + 20,
            creationflags=CREATE_NO_WINDOW)
    except Exception:
        pass


def run():
    """작업이 띄울 때: 인증서를 채우고 감독을 시작한다."""
    warm_windows_roots()
    return main()


def main(cmd=None, backoff=BACKOFF, healthy_sec=HEALTHY_SEC, sleep=time.sleep):
    """에이전트를 띄우고 지킨다. 다시 켜지 않는 코드(STOP_CODES)로 끝나면 그 코드를 돌려주고 같이 끝난다.
    cmd·backoff·healthy_sec·sleep 은 시험용 (가짜 에이전트, 짧은 기다림)."""
    folder = log_dir()
    cmd = cmd or agent_command()
    stop_file = os.path.join(folder, STOP_NAME)
    try:
        os.remove(stop_file)                   # 앞선 멈춤의 까닭은 이제 옛말이다
    except OSError:
        pass
    job = make_job()
    log(folder, "시작합니다" + ("" if job else " (잡을 못 만들었습니다 - 작업을 끝내도 에이전트가 남을 수 있습니다)"))
    fails = 0
    while True:
        started = time.monotonic()
        try:
            proc = start_agent(cmd, folder)
        except OSError as e:
            log(folder, f"에이전트를 띄우지 못했습니다 ({type(e).__name__}: {e})")
            code = None
        else:
            put_in_job(job, proc)
            code = proc.wait()
        if code in STOP_CODES:
            log(folder, f"에이전트가 끝났습니다 (코드 {code}) - {STOP_CODES[code]}. 감독도 끝냅니다")
            try:
                with open(stop_file, "w", encoding="utf-8") as f:
                    json.dump({"code": code, "reason": STOP_CODES[code], "at": time.strftime("%Y-%m-%d %H:%M:%S")},
                              f, ensure_ascii=False)
            except OSError:
                pass
            return code
        fails = 1 if time.monotonic() - started >= healthy_sec else fails + 1
        wait = backoff[min(fails, len(backoff)) - 1]
        log(folder, f"에이전트가 멈췄습니다 (코드 {code}). {wait}초 뒤 다시 켭니다")
        sleep(wait)


if __name__ == "__main__":
    sys.exit(run())
