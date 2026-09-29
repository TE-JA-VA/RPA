"""감독(firebase/agent/background.py) 시험 - 가짜 에이전트로 종료 코드별 동작, 기다림, 창 없는 입출력, 잡(job).

    .venv\\Scripts\\python.exe tests\\test_background.py

가짜 에이전트는 진짜 파이썬(sys._base_executable)으로 띄운다. .venv 의 python.exe 는 진짜 파이썬을 자식으로 한 번
더 띄우는 껍데기라, 잡 시험에서 엉뚱한 프로세스(껍데기)를 보게 된다.
"""
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENT_DIR = str(ROOT / "firebase" / "agent")
TMP = tempfile.mkdtemp(prefix="rpa_bg_")
os.environ["RPA_AGENT_QUEUE"] = os.path.join(TMP, "queue.jsonl")      # 감독 기록이 이 폴더로
sys.path.insert(0, str(ROOT))
sys.path.insert(0, AGENT_DIR)
sys.stdout.reconfigure(encoding="utf-8")

import background as bg  # noqa: E402
import rpa_status as st  # noqa: E402

PY = getattr(sys, "_base_executable", None) or sys.executable
FAKE = os.path.join(TMP, "fake_agent.py")
Path(FAKE).write_text('''import os, subprocess, sys, time
d, mode = sys.argv[1], sys.argv[2]
runs = os.path.join(d, "runs.txt")
n = int(open(runs).read()) if os.path.exists(runs) else 0
open(runs, "w").write(str(n + 1))
if mode == "codes":
    codes = [int(c) for c in sys.argv[3].split(",")]
    sys.exit(codes[min(n, len(codes) - 1)])
if mode == "env":
    with open(os.path.join(d, "env.txt"), "w", encoding="utf-8") as f:
        f.write(f"{os.environ.get('PYTHONUTF8')}|{sys.stdin.isatty()}|{sys.stdout.encoding}")
    print("한글 출력 · 화살표 →", flush=True)
    sys.stderr.write("가짜 오류 추적\\n")
    sys.exit(3)
if mode == "sleep":
    g = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"], creationflags=0x08000000)
    with open(os.path.join(d, "pids.txt"), "w") as f:
        f.write(f"{os.getpid()} {g.pid}")
    time.sleep(120)
''', encoding="utf-8")

fails = []
_no = [0]


def check(name, cond, detail=""):
    _no[0] += 1
    mark = "통과" if cond else "실패"
    print(f"  {_no[0]:2d}. [{mark}] {name}" + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(f"{_no[0]}. {name} {detail}")


def fresh(name):
    d = os.path.join(TMP, name)
    os.makedirs(d)
    return d


def runs(d):
    p = os.path.join(d, "runs.txt")
    return int(open(p).read()) if os.path.exists(p) else 0


def log_text():
    p = os.path.join(TMP, bg.LOG_NAME)
    return open(p, encoding="utf-8").read() if os.path.exists(p) else ""


print("=== 1. 종료 코드 ===")
d = fresh("c1")
waits = []
code = bg.main(cmd=[PY, FAKE, d, "codes", "1,1,3"], backoff=(0.01, 0.02, 0.03), healthy_sec=9999, sleep=waits.append)
check("오류(1) 두 번은 다시 켜고, 인증 멈춤(3)이면 같이 끝난다", code == 3 and runs(d) == 3 and waits == [0.01, 0.02],
      (code, runs(d), waits))
for c in (0, 2, 4):
    d = fresh(f"c{c}")
    waits = []
    got = bg.main(cmd=[PY, FAKE, d, "codes", str(c)], backoff=(0.01,), sleep=waits.append)
    check(f"코드 {c} 면 다시 켜지 않는다", got == c and runs(d) == 1 and waits == [], (got, runs(d), waits))
text = log_text()
check("기록: 시작·다시 켜기·끝내기", "감독: 시작합니다" in text and text.count("다시 켭니다") >= 2 and "코드 3" in text
      and "감독도 끝냅니다" in text, text[-300:])

stop_file = os.path.join(TMP, bg.STOP_NAME)
d = fresh("s3")
bg.main(cmd=[PY, FAKE, d, "codes", "3"], backoff=(0.01,), sleep=lambda s: None)
stopped = json.load(open(stop_file, encoding="utf-8"))
check("다시 켜지 않고 끝나면 까닭을 파일에 남긴다 (설정 창이 보여 준다)",
      stopped["code"] == 3 and stopped["reason"] == bg.STOP_CODES[3] and stopped["at"], stopped)
d = fresh("s1")


class Halt(Exception):
    pass


def halt(s):
    raise Halt


try:
    bg.main(cmd=[PY, FAKE, d, "codes", "1"], backoff=(0.01,), sleep=halt)     # 오류(1) 뒤 기다리는 동안 멈춰 본다
except Halt:
    pass
check("켤 때 앞선 까닭을 지우고, 다시 켜는 오류(1)는 남기지 않는다", not os.path.exists(stop_file))

print("=== 2. 기다림 ===")
d = fresh("w1")
waits = []
bg.main(cmd=[PY, FAKE, d, "codes", "1,1,1,1,4"], backoff=(0.01, 0.02), healthy_sec=9999, sleep=waits.append)
check("잇따라 죽으면 길게, 끝 값에서 멈춘다", waits == [0.01, 0.02, 0.02, 0.02], waits)
d = fresh("w2")
waits = []
bg.main(cmd=[PY, FAKE, d, "codes", "1,1,1,4"], backoff=(0.01, 0.02), healthy_sec=0, sleep=waits.append)
check("오래 돌다 죽었으면 처음 기다림부터", waits == [0.01, 0.01, 0.01], waits)
check("기본 기다림 10·30·60·120·300초, 10분", bg.BACKOFF == (10, 30, 60, 120, 300) and bg.HEALTHY_SEC == 600)

print("=== 3. 창 없는 에이전트의 입출력 ===")
d = fresh("env")
check("가짜 에이전트가 3 으로 끝난다", bg.main(cmd=[PY, FAKE, d, "env"], backoff=(0.01,), sleep=lambda s: None) == 3)
env = open(os.path.join(d, "env.txt"), encoding="utf-8").read()
check("PYTHONUTF8=1, 입력 없음(isatty 거짓), 출력 UTF-8", env == "1|False|utf-8", env)
err = open(os.path.join(TMP, bg.ERR_NAME), encoding="utf-8", errors="replace").read()
check("오류 출력은 에이전트_오류.txt 에 덧붙는다", "가짜 오류 추적" in err, err[-200:])

print("=== 4. 띄우지 못할 때 ===")


class Stop(Exception):
    pass


waits = []


def sleeper(s):
    waits.append(s)
    if len(waits) >= 2:
        raise Stop


try:
    bg.main(cmd=[os.path.join(TMP, "없는.exe")], backoff=(0.01,), sleep=sleeper)
except Stop:
    pass
check("못 띄우면 기록하고 기다렸다가 다시", len(waits) == 2 and "에이전트를 띄우지 못했습니다" in log_text())

print("=== 5. 잡: 감독이 죽으면 에이전트도 죽고, 에이전트가 띄운 RPA 는 남는다 ===")
check("잡을 만든다", bg.make_job() is not None)
d = fresh("job")
sup_code = (f"import sys; sys.path.insert(0, {AGENT_DIR!r}); import background as b; "
            f"b.main(cmd=[{PY!r}, {FAKE!r}, {d!r}, 'sleep'], backoff=(60,))")
sup = subprocess.Popen([PY, "-c", sup_code], env=dict(os.environ, RPA_AGENT_QUEUE=os.path.join(d, "queue.jsonl")),
                       creationflags=0x08000000)
pids_path = os.path.join(d, "pids.txt")
for _ in range(200):
    if os.path.exists(pids_path) and open(pids_path).read().strip():
        break
    time.sleep(0.1)
agent_pid, grand_pid = (int(x) for x in open(pids_path).read().split())
try:
    check("가짜 에이전트와 손자가 떴다", st.process_alive(agent_pid) and st.process_alive(grand_pid))
    sup.kill()
    sup.wait(timeout=10)
    for _ in range(50):
        if not st.process_alive(agent_pid):
            break
        time.sleep(0.1)
    check("감독이 죽으면 에이전트도 죽는다 (KILL_ON_JOB_CLOSE)", not st.process_alive(agent_pid))
    check("에이전트가 띄운 손자(RPA)는 산다 (SILENT_BREAKAWAY_OK)", st.process_alive(grand_pid))
finally:
    for pid in (agent_pid, grand_pid):
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass

print("=== 6. 약속 ===")
check("다시 켜지 않는 코드 = 0·2·3·4", set(bg.STOP_CODES) == {0, 2, 3, 4})
src = (ROOT / "firebase" / "agent" / "agent.py").read_text(encoding="utf-8")
check("agent.main 이 그 코드들을 쓴다", all(f"return {c}" in src for c in (2, 3, 4)))
cmd = bg.agent_command()
check("에이전트 명령: AFTER MARKET 사본이 없으면 pythonw 옆 python.exe 와 agent.py",
      os.path.basename(cmd[0]).lower() == "python.exe" and cmd[-1] == os.path.join(AGENT_DIR, "agent.py"), cmd)
with tempfile.TemporaryDirectory() as d:
    open(os.path.join(d, bg.AGENT_EXE), "wb").close()
    cmd = bg.agent_command(d)
    check("에이전트 명령: 설치 판에는 작업 관리자에 AFTER MARKET 으로 보이는 사본으로",
          cmd[0] == os.path.join(d, bg.AGENT_EXE) and bg.AGENT_EXE.startswith("AFTER_MARKET"), cmd)

print("=== 7. 윈도우 루트 인증서 채우기 (갓 설치한 윈도우) ===")
sys.path.insert(0, AGENT_DIR)
import secret  # noqa: E402
from urllib.parse import urlsplit  # noqa: E402

calls = []
bg.warm_windows_roots(run=lambda args, **kw: calls.append(args))
cmd_text = " ".join(calls[0]) if calls else ""
check("PowerShell(윈도우 자체 통신)로 Firebase 주소를 모두 찌른다", len(calls) == 1 and calls[0][0] == "powershell"
      and all(u in cmd_text for u in bg.ROOT_WARM_URLS) and "-UseBasicParsing" in cmd_text, calls)
check("TLS 1.2 를 켜고 찌른다 (옛 Windows 10 의 PowerShell 5.1 은 TLS 1.0 만 쓸 수 있다)", "3072" in cmd_text, cmd_text[:200])
check("찌르는 주소에 이 프로젝트의 RTDB 가 있다 (secret.PUBLIC 과 같은 곳)",
      any(urlsplit(u).hostname == urlsplit(secret.PUBLIC["database_url"]).hostname for u in bg.ROOT_WARM_URLS))


def boom_run(args, **kw):
    raise OSError("powershell 없음")


try:
    bg.warm_windows_roots(run=boom_run)
    check("못 해도 조용히 넘어간다 (인터넷이 없으면 에이전트가 원래대로 다시 붙는다)", True)
except Exception as e:
    check("못 해도 조용히 넘어간다 (인터넷이 없으면 에이전트가 원래대로 다시 붙는다)", False, repr(e))
order = []
saved = (bg.warm_windows_roots, bg.main)
try:
    bg.warm_windows_roots, bg.main = (lambda: order.append("warm")), (lambda: order.append("main") or 0)
    bg.run()
finally:
    bg.warm_windows_roots, bg.main = saved
check("작업이 띄우면 인증서부터 채우고 감독을 시작한다 (파이썬은 켤 때 읽은 인증서를 다시 안 읽는다)", order == ["warm", "main"], order)
t0 = time.monotonic()
bg.warm_windows_roots()
check("이 PC 에서 진짜로 돌려도 금방 끝난다", time.monotonic() - t0 < 60, time.monotonic() - t0)

shutil.rmtree(TMP, ignore_errors=True)
print()
print(f"실패: {'없음' if not fails else fails}")
sys.exit(1 if fails else 0)
