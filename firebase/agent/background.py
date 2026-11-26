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
if os.path.abspath(os.path.join(HERE, "..", "..")) not in sys.path:     # 저장소·배포 폴더 뿌리 (server_info 자리)
    sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..")))
import server_info  # noqa: E402  서버 주소 한 곳 (2026-10-21)
# 다시 켜지 않는 에이전트 종료 코드 (agent.main 의 약속). 그 밖(오류 1, 강제 종료 등)은 다시 켠다
STOP_CODES = {
    0: "정상으로 끝났습니다",
    2: "설정이 없거나 깨졌습니다. '오토파일럿 설정' 에서 설정을 마치세요",
    3: "로그인이 막혔습니다 (에이전트 계정 비밀번호가 바뀌었거나 계정이 사용중지됨). '오토파일럿 설정' 에서 비밀번호를 다시 넣으세요",
    4: "이 PC 에서 에이전트가 이미 돌고 있습니다",
    # 사내 서버 (사내 서버 ⑤ - agent.LAN_DISABLED_CODE·LAN_REMOVED_CODE)
    6: "사내 서버 관리자가 이 PC 를 사용 중지했습니다. 다시 사용하려면 업체 웹에서 사용을 재개한 뒤 '오토파일럿 설정' 에서 [저장] 을 눌러 주십시오",
    7: "사내 서버에서 이 PC 를 지웠습니다. '오토파일럿 설정' 에서 사내 서버에 다시 등록하여 주십시오",
}
BACKOFF = (10, 30, 60, 120, 300)     # 다시 켜기 전 기다림(초). 잇따라 죽을수록 길게
RETRY_LATER_CODE = 5                  # 로그인 일시 차단 (agent.RETRY_LATER_CODE) - 차단이 풀리게 오래 기다렸다 다시 켠다 (BugBuster M2)
RETRY_LATER_SEC = 600                 # Identity Toolkit 안내 '약 10분 후' - 짧게 두드리면 차단이 길어진다
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


def _dev_env(name):
    """시험용 RPA_* 환경 변수 - 설치본은 무시한다 (rpa_status.dev_env, 보안 진단 2026-11-23 E-1)."""
    root = os.path.abspath(os.path.join(HERE, "..", ".."))
    if root not in sys.path:
        sys.path.insert(0, root)
    import rpa_status
    return rpa_status.dev_env(name)


def log_dir():
    """에이전트 기록과 같은 폴더 (agent._data_dir 와 같은 규칙, 시험은 RPA_AGENT_QUEUE 의 폴더). 못 정하면 이 파일 옆."""
    queue = _dev_env("RPA_AGENT_QUEUE")
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
    # -E -s: 관리자 권한 에이전트가 사용자 쪽 파이썬 설정(PYTHON* 환경 변수·사용자 site 의 .pth)을 따르지 않게, UTF-8 은 -X 로
    # (보안 진단 2026-11-23 C-02 - 같은 계정의 일반 권한 프로그램이 파일 하나로 다음 로그인 때 관리자 권한 코드를 돌릴 수 있었다)
    flags = ["-E", "-s", "-X", "utf8"]
    for name in (AGENT_EXE, "python.exe"):
        py = os.path.join(exe_dir, name)
        if os.path.isfile(py):
            return [py, *flags, os.path.join(HERE, "agent.py")]
    return [sys.executable, *flags, os.path.join(HERE, "agent.py")]


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
ROOT_WARM_URLS = tuple([f"https://{h}/" for h in (server_info.AUTH_HOST, server_info.TOKEN_HOST, server_info.FIRESTORE_HOST) if h]
                       + ([server_info.DATABASE_URL + "/.json"] if server_info.DATABASE_URL else [])
                       # 업데이트 주소도 - 회사 서버 인증서는 Google 과 루트가 다를 수 있다 (2026-10-21)
                       + [u.rstrip("/") + "/" for u in (server_info.UPDATE_BASE_URL, *server_info.UPDATE_FALLBACK_URLS) if u])
# 스탠드얼론 설치본(빈 server_info)에서는 빈 튜플이다


def warm_windows_roots(urls=ROOT_WARM_URLS, timeout=10, run=subprocess.run):
    """윈도우가 Firebase 주소의 루트 인증서를 받아 두게 한다. 응답(404·401 등)은 보지 않는다. 못 해도 조용히 넘어간다
    (인터넷이 없으면 에이전트가 원래대로 다시 붙으려 한다). 주소가 없으면 아무것도 띄우지 않는다."""
    if not urls:
        return
    # 3072 = TLS 1.2 (옛 Windows 10 의 PowerShell 5.1 은 기본이 TLS 1.0 이라 Google 에 못 붙는다)
    script = "[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor 3072; " + "; ".join(
        f"try {{ Invoke-WebRequest -Uri '{u}' -UseBasicParsing -TimeoutSec {timeout} | Out-Null }} catch {{ }}" for u in urls)
    try:
        run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout * len(urls) + 20,
            creationflags=CREATE_NO_WINDOW)
    except Exception:
        pass


def _standalone():
    """스탠드얼론 버전인가 (로컬 서버를 함께 띄운다, Google 주소를 건드리지 않는다)."""
    try:
        import edition
        return edition.is_standalone()
    except Exception:
        return False


def _lan():
    """스탠드얼론이고 사내 서버 연결인가 (연결 파일만 있다 - license_check.mode). 그러면 로컬 서버를 띄우지 않고 에이전트만 지킨다
    (설계 6.1, 사내 서버 ⑤). 판정이 예외를 내면 (둘 다 있음 등) 거짓 - 지금 길 (로컬 서버가 라이선스 문제로 2 로 끝난다)."""
    if not _standalone():
        return False
    try:
        import license_check
        return license_check.mode() == license_check.MODE_LAN
    except Exception:
        return False


def run():
    """작업이 띄울 때: 인증서를 채우고 감독을 시작한다. 스탠드얼론은 Google·업데이트 주소에 닿지 않으므로 채우지 않는다."""
    if not _standalone():
        warm_windows_roots()
    return main()


SERVER_BACKOFF = (2, 5, 15, 30)       # 로컬 서버가 죽었을 때 다시 켜기 전 기다림(초)
SERVER_STOP_CODES = (2,)              # 라이선스가 없거나 맞지 않음 (local_server.main) - 다시 켜도 같다
SERVER_PORT_CODE = 3                  # 포트를 못 엶 (다른 프로그램이 쓰는 중) - 풀릴 수 있으니 계속 다시 켜되, 그동안 에이전트는 가짜 서버를 믿지 않는다
SERVER_LOG_EVERY = 20                 # 같은 코드로 잇따라 죽을 때 기록은 이 횟수마다
KEYS_WAIT_SEC = 15                    # 처음 켤 때 서버가 열쇠 파일을 만들기를 기다리는 시간


def server_command(exe_dir=None):
    """창 없이 띄울 로컬 서버 명령 - 에이전트와 같은 파이썬·같은 깃발."""
    return agent_command(exe_dir)[:-1] + [os.path.join(HERE, "local_server.py")]


def watch_server(cmd, folder, job, stop, backoff=SERVER_BACKOFF):
    """스탠드얼론: 로컬 서버를 띄우고 죽으면 다시 켠다 (스레드로 돈다). stop 이 켜지면 서버를 끝내고 나온다."""
    fails, last = 0, object()
    while not stop.is_set():
        started = time.monotonic()
        try:
            proc = start_agent(cmd, folder)
        except OSError as e:
            log(folder, f"로컬 서버를 띄우지 못했습니다 ({type(e).__name__}: {e})")
            code = None
        else:
            put_in_job(job, proc)
            while proc.poll() is None and not stop.wait(0.2):
                pass
            if stop.is_set():
                try:
                    proc.terminate()
                except OSError:
                    pass
                return
            code = proc.returncode
        if code in SERVER_STOP_CODES:
            log(folder, f"로컬 서버가 끝났습니다 (코드 {code}) - 라이선스를 확인하여 주십시오. 다시 켜지 않습니다")
            return
        fails = 1 if time.monotonic() - started >= HEALTHY_SEC else fails + 1
        wait = backoff[min(fails, len(backoff)) - 1]
        if code != last or fails % SERVER_LOG_EVERY == 0:      # 같은 까닭으로 잇따라 죽으면 기록을 가끔만 (30초마다 한 줄씩 끝없이 쌓이지 않게)
            why = " - 포트를 다른 프로그램이 쓰고 있습니다. 그 프로그램을 끝내야 합니다" if code == SERVER_PORT_CODE else ""
            log(folder, f"로컬 서버가 멈췄습니다 (코드 {code}){why}. {wait}초 뒤 다시 켭니다" + (f" ({fails}번째)" if fails > 1 else ""))
        last = code
        stop.wait(wait)


def _server_ready():
    """로컬 서버가 열쇠 파일을 만들었고 포트를 듣고 있나 - 그 뒤에 에이전트를 띄워야 켤 때 한 번 하는 정리(끝나지 못한 명령 닫기 등)가
    연결 거부로 건너뛰지 않는다 (검토 2026-11-23 8번). 듣는 쪽이 진짜 서버인지는 에이전트가 응답 서명으로 본다."""
    import socket
    try:
        import local_store
        import rpa_status
        if not os.path.isfile(os.path.join(local_store.keys_dir(), "agent.key")):
            return False
        try:
            port = int(rpa_status.dev_env("RPA_LOCAL_PORT") or local_store.PORT)
        except ValueError:
            port = local_store.PORT
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except Exception:
        return False


def main(cmd=None, backoff=BACKOFF, healthy_sec=HEALTHY_SEC, sleep=time.sleep, later_sec=RETRY_LATER_SEC,
         server_cmd=None, server_backoff=SERVER_BACKOFF, keys_wait=KEYS_WAIT_SEC):
    """감독. 일반 버전은 에이전트만, 스탠드얼론은 로컬 서버를 먼저 띄워 함께 지킨다 (서버가 죽으면 다시 켠다).
    에이전트가 다시 켜지 않는 코드로 끝나 감독이 끝나면 서버도 끝낸다. server_cmd·server_backoff·keys_wait 는 시험용."""
    if not _standalone() or _lan():           # 일반 버전·사내 서버 연결: 에이전트만 (사내 서버는 서버 쪽에 있다)
        return supervise(cmd, backoff, healthy_sec, sleep, later_sec)
    import threading
    folder = log_dir()
    stop = threading.Event()
    server_job = make_job()
    watcher = threading.Thread(target=watch_server, args=(server_cmd or server_command(), folder, server_job, stop, server_backoff),
                               daemon=True, name="local-server")
    watcher.start()
    end = time.monotonic() + keys_wait        # 처음 켤 때: 서버가 열쇠 파일을 만든 뒤에 에이전트를 띄운다 (없으면 에이전트가 1 로 끝나 다시 켜진다)
    while time.monotonic() < end and not _server_ready():
        time.sleep(0.1)
    try:
        return supervise(cmd, backoff, healthy_sec, sleep, later_sec)
    finally:
        stop.set()
        watcher.join(5)


def supervise(cmd=None, backoff=BACKOFF, healthy_sec=HEALTHY_SEC, sleep=time.sleep, later_sec=RETRY_LATER_SEC):
    """에이전트를 띄우고 지킨다. 다시 켜지 않는 코드(STOP_CODES)로 끝나면 그 코드를 돌려주고 같이 끝난다.
    로그인 일시 차단(RETRY_LATER_CODE)이면 later_sec 기다렸다 다시 켠다.
    cmd·backoff·healthy_sec·sleep·later_sec 은 시험용 (가짜 에이전트, 짧은 기다림)."""
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
        if code == RETRY_LATER_CODE:
            wait = later_sec
            log(folder, f"로그인이 잠시 차단되었습니다 (코드 {code}). {wait}초 뒤 다시 켭니다")
            sleep(wait)
            continue
        fails = 1 if time.monotonic() - started >= healthy_sec else fails + 1
        wait = backoff[min(fails, len(backoff)) - 1]
        log(folder, f"에이전트가 멈췄습니다 (코드 {code}). {wait}초 뒤 다시 켭니다")
        sleep(wait)


if __name__ == "__main__":
    sys.exit(run())
