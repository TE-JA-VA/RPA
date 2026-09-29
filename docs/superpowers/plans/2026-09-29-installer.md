# 배포판 구조 2부 (설치 마법사) 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 고객 업체 직원이나 우리 쪽 사람이 `setup.exe` 하나로 RPA 를 1부의 새 자리(`Program Files`·`ProgramData`)에 설치하고, 설정 창에서 기계 계정·ERPia 로그인 등을 넣으면, 에이전트가 윈도우 로그인 때마다 창 없이 켜지고 오류로 죽으면 다시 켜진다. 옛 구조 PC 는 설정을 가져와 옮긴다.

**Architecture:** 설치·제거·바로 가기·폴더 권한은 Inno Setup(`release/installer.iss`)이, 입력·로그인 확인·비밀번호 잠금·작업 등록·에이전트 켜고 끄기는 파이썬 설정 창(`rpa_settings.py`, tkinter)이 맡는다. 작업 스케줄러가 로그인 때 감독(`firebase/agent/background.py`)을 `pythonw` 로 띄우고, 감독은 에이전트를 창 없이 띄워 자기 잡(job)에 넣고 종료 코드에 따라 다시 켜거나 같이 끝난다. 에이전트는 이름 있는 잠금으로 한 PC 에 하나만 돈다.

**Tech Stack:** Python 3.14.7 (`.venv`, 내장 python 같은 판 + tkinter/Tcl·Tk 9), Inno Setup 6.7.3 (`%LOCALAPPDATA%\Programs\Inno Setup 6`), 작업 스케줄러 XML(`schtasks`), Win32 API(ctypes: 잡·뮤텍스·DPAPI·WTS·EnumPrinters), 윈도우 샌드박스(마지막 시험)

**Spec:** `docs/superpowers/specs/2026-09-29-installer-design.md` (1부: `docs/superpowers/specs/2026-09-29-release-layout-design.md`)

## Global Constraints

- 프로그램 `C:\Program Files\AFTER MARKET\RPA\` (Inno `{commonpf64}\AFTER MARKET\RPA`), 설정 `C:\ProgramData\AFTER MARKET\RPA\config\`, 기록 `...\data\`. `config` 폴더가 있으면 새 구조 (1부 3절)
- **이 개발 PC 에 설치하지 않는다.** `setup.exe` 를 여기서 돌리지 않고, 진짜 `C:\ProgramData\AFTER MARKET\RPA\config` 를 만들지 않는다. 시험은 언제나 `RPA_PROGRAMDATA` 임시 폴더
- 시험용 환경변수(먼저 본다): `RPA_PROGRAMDATA`, `RPA_AGENT_QUEUE`, `RPA_AGENT_CONFIG`, `RPA_USER_CONFIG`, 새로 `RPA_AGENT_MUTEX` (기본 `Local\AFTER_MARKET_RPA_AGENT`)
- 작업 이름 `AFTER MARKET\RPA Agent`, 빈 틀 설치 이름 `RPA_UserConfig.template.json`, 설치 파일 이름 `AFTER_MARKET_RPA_Setup_<판>.exe`, `VersionInfoVersion` = `2026.9.29.5` 꼴
- 설정 창 모드 `--after-install`, `--after-install --no-window`, `--stop`, `--remove-task`. 종료 코드 0 됨 / 5 RPA 가 돌고 있음 / 6 에이전트가 안 멈춤
- 에이전트 종료 코드 0 정상 / 2 설정 문제 / 3 인증 멈춤 / 4 이미 돌고 있음 → 감독은 이 넷이면 같이 끝나고, 그 밖은 10·30·60·120·300초 뒤 다시 켠다 (10분 넘게 돌았으면 10초부터)
- 작업 XML: 로그온 트리거(그 계정), `InteractiveToken`, `HighestAvailable`, `IgnoreNew`, 배터리 두 칸 `false`, `PT0S`, 우선순위 `5`
- 권한: `icacls "…\AFTER MARKET\RPA" /inheritance:r /grant:r *S-1-5-32-544:(OI)(CI)F *S-1-5-18:(OI)(CI)F`
- 비밀번호는 잠근 뒤에만 파일에 쓴다. 창의 다른 곳·기록·오류 글·커밋에 싣지 않는다. `setup.js user/agent/passwd` 는 Claude 도구로 돌리지 않는다
- `rpa_status.py`·`run_routine.py`·`web_runner.py` 는 고치지 않는다 (exe 가 컴파일해 담는다 - 고치면 exe 를 다시 만들어야 한다)
- `.bat` 는 CP949+CRLF 그대로. 새로 만드는 `.iss`·`.ps1` 은 BOM 있는 UTF-8 (Write 도구는 BOM 없이 쓰므로 쓴 뒤 BOM 을 붙인다. 파일을 다 읽은 뒤에 쓰기로 연다)
- 파이썬 패치를 bash heredoc 으로 쓰지 않는다 - Edit/Write 도구를 쓴다
- 이 Claude 셸은 관리자 권한이 아니다. 관리자 권한이 필요한 것(샌드박스 기능 켜기)은 사용자에게 묻는다
- 커밋은 모든 작업·검증이 끝난 뒤 develop 에 한 번 (사용자 승인). push 는 사용자가 말할 때만. `--no-verify` 금지
- 코드를 고친 작업 끝에 `graphify update .`
- 문서·주석은 한국어, 주변 코드 말투(`~다`)와 같게

## Review Focus

1. **빈칸·한글이 든 자리** (`C:\Program Files\AFTER MARKET\RPA`, 옛 폴더 `D:\AX\배포_2026.09.29-4`, 한글 프린터 이름): 명령줄 따옴표, XML 이스케이프, PowerShell 출력 인코딩에서 깨지지 않아야 한다 → Task 3 시험 (`paths_in` 의 `설치 폴더`, 한글 옛 폴더, `&` 가 든 계정 이름, 진짜 작업 스케줄러 등록)
2. **설정을 다시 열어 비밀번호 칸을 비운 채 저장**: 저장된 비밀번호를 그대로 두고, 인터넷 없이도 되고(다시 로그인하지 않음), 에이전트를 다시 켜지 않는다 → Task 3 `5. 저장` 둘째 저장
3. **저장하는 순간 인터넷이 끊김**: 사람 문장("인터넷에 연결하지 못해…")으로 알리고 아무 파일도 반쯤 쓰지 않는다 → Task 3 `5. 저장`(로그인 거부 시 파일 없음)·`6. 오류 문장`
4. **다른 PC·윈도우 계정에서 잠근 설정을 가져옴**: 그 칸만 "다시 넣으세요" 로 필수가 되고, 비운 채 저장은 거절 → Task 3 `1. 칸 확인`·`11. 가져오기`, Task 4 창 시험
5. **설치하지 않은 곳에서 열거나 다른 관리자 계정 비밀번호로 권한만 올림**: 창을 띄우기 전에 무엇을 해야 하는지 알리고 멈춘다 → Task 3 `12. 계정·설치 확인`

---

## 파일 지도

| 파일 | 하는 일 | 작업 |
|---|---|---|
| `firebase/agent/agent.py` | `single_instance()` 잠금, `main()` 이 이미 돌면 4 | 1 |
| `firebase/agent/background.py` (새) | 감독: 창 없이 띄우기, 잡, 종료 코드별 다시 켜기, 기록 | 2 |
| `rpa_settings.py` (새) | 설정 창 전부: 자리·계정 확인, 프로세스·잠금, 작업 XML·schtasks, 설정 확인·합치기·저장, 가져오기, 프린터 목록, tkinter 창, 모드 | 3, 4 |
| `release/installer.iss` (새) | Inno Setup 설치 파일 | 5 |
| `tools/build_release.py` | 새 파일 두 개를 판에, tkinter 확인, `--exes-from`, `setup.exe` 컴파일, `--no-setup` | 5 |
| `D:\AX\runtime\python\Lib\tkinter` (저장소 밖) | 내장 파이썬에 tkinter 넣기 (한 번) | 5 |
| `tools/sandbox_test.py`, `tools/sandbox_inner.ps1` (새) | 윈도우 샌드박스에서 설치 파일 시험 | 7 |
| `tests/test_settings.py` (새) | 설정 창의 창 없는 부분 | 3 |
| `tests/check_settings_ui.py` (새) | 설정 창을 진짜로 띄워 보기 + 화면 사진 | 4 |
| `tests/test_background.py` (새) | 감독 | 2 |
| `firebase/tests/test_agent.py` | 11절 하나만 돌기 | 1 |
| `firebase/tests/integration.js` | `RPA_AGENT_MUTEX` | 1 |
| `tests/test_build_release.py` | 6절 설치 파일 | 5 |
| `tests/test_encoding.py` | 4절 `.iss`·`.ps1` BOM | 5, 7 |
| `release/배포안내.txt`, `release/클라우드_안내.txt` | 설치 파일로 설치하기, 설치한 PC 의 에이전트 | 8 |
| `docs/firebase-architecture.md`, 설계 문서 | 파일 지도·새 PC 붙이기·시험 표, 상태 "구현됨" | 8 |

## 시험 돌리는 법

```powershell
cd D:\AX\RPA
.venv\Scripts\python.exe tests\test_settings.py          # Task 3 에서 생김
.venv\Scripts\python.exe tests\check_settings_ui.py C:\Users\202512~1\AppData\Local\Temp\claude\d--AX-RPA\7867a5f6-6024-4100-8af7-b0f18f099fe7\scratchpad\settings.png   # Task 4
.venv\Scripts\python.exe tests\test_background.py        # Task 2
.venv\Scripts\python.exe tests\test_build_release.py     # 기존 21 + Task 5
.venv\Scripts\python.exe tests\test_encoding.py          # 기존 13 + Task 5·7
.venv\Scripts\python.exe tests\test_layout.py            # 기존 45 (바뀌면 안 된다)
cd D:\AX\RPA\firebase
python tests\test_agent.py                               # 기존 126 + Task 1
. .\emu_env.ps1; cd tests
firebase emulators:exec --config ../firebase.json --only auth,database,firestore --project rpa-test-f02e0 "node integration.js"
```
모든 시험 파일은 끝에 `실패: 없음` 또는 `N/N 통과` 를 찍는다.

## 걸리는 시간 (어림)

| 작업 | 시간 |
|---|---|
| 1 에이전트 하나만 | 20분 |
| 2 감독 | 40분 |
| 3 설정 창 (창 없는 부분) | 1시간 20분 |
| 4 설정 창 (창) | 1시간 |
| 5 빌드·설치 파일 | 1시간 |
| 6 판 만들기 | 50분 (Nuitka 두 개 30분 + 설치 파일 압축) |
| 7 샌드박스 시험 | 1시간 (+ 사용자 재부팅) |
| 8 문서·검토·커밋 | 1시간 |
| 합계 | 약 7시간 |

---

### Task 1: 에이전트 하나만 (잠금)

설계 5절 '에이전트 하나만'. 설정 창의 "돌고 있음" 표시와 `--stop` 이 이 잠금을 본다.

**Files:**
- Modify: `firebase/agent/agent.py` (`ask_setup` 과 `main` 사이에 잠금, `main` 첫머리)
- Modify: `firebase/tests/test_agent.py` (10절 뒤, 끝 합계 앞에 11절)
- Modify: `firebase/tests/integration.js` (에이전트 env)

**Interfaces:**
- Produces: `agent.MUTEX_NAME: str`, `agent.ERROR_ACCESS_DENIED = 5`, `agent.single_instance(name: str | None = None) -> bool`, `agent.main()` 이 이미 돌면 `4`

- [ ] **Step 1: 실패하는 시험 (test_agent.py 11절)**

`print(f"\n{COUNT - len(FAIL)}/{COUNT} 통과")` 바로 앞에 넣는다:
```python
print("\n11절 에이전트 하나만 (설치 마법사 2부)")
import ctypes  # noqa: E402
import agent  # noqa: E402

lock = rf"Local\AFTER_MARKET_RPA_AGENT_TEST_{os.getpid()}"
check(agent.single_instance(lock) is True, "처음 잡으면 True")
check(agent.single_instance(lock) is True, "같은 프로세스가 다시 부르면 그대로 True (이미 잡았다)")
child = f"import sys; sys.path.insert(0, {AGENT_DIR!r}); import agent; print(agent.single_instance({lock!r}))"
r = subprocess.run([sys.executable, "-c", child], cwd=AGENT_DIR, capture_output=True, text=True, encoding="utf-8",
                   timeout=60, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
check(r.stdout.strip().splitlines()[-1:] == ["False"], f"다른 프로세스는 못 잡는다 {r.stdout[-200:]} {r.stderr[-200:]}")
held = rf"Local\AFTER_MARKET_RPA_AGENT_HELD_{os.getpid()}"
k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.CreateMutexW.restype = ctypes.c_void_p
k32.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p)
held_handle = k32.CreateMutexW(None, False, held)       # '다른 에이전트' 가 잡은 잠금 흉내
old_name = agent.MUTEX_NAME
agent.MUTEX_NAME = held
try:
    check(agent.main() == 4, "이미 돌고 있으면 main() 은 설정을 읽기 전에 4 로 끝난다")
finally:
    agent.MUTEX_NAME = old_name
check(agent.MUTEX_NAME == (os.environ.get("RPA_AGENT_MUTEX") or r"Local\AFTER_MARKET_RPA_AGENT"),
      "기본 이름 Local\\AFTER_MARKET_RPA_AGENT (시험은 RPA_AGENT_MUTEX)")
```

- [ ] **Step 2: 실패 확인**

Run: `cd D:\AX\RPA\firebase; python tests\test_agent.py`
Expected: `AttributeError: module 'agent' has no attribute 'single_instance'` 로 멈춤

- [ ] **Step 3: 잠금 구현 (agent.py)**

`def main():` 바로 위에 넣는다:
```python
# ---------------------------------------------------------------------------
# 에이전트 하나만 (설치 마법사 2부 5절). 설정 창(rpa_settings)이 같은 이름으로 '돌고 있음' 을 본다
# ---------------------------------------------------------------------------
MUTEX_NAME = os.environ.get("RPA_AGENT_MUTEX") or r"Local\AFTER_MARKET_RPA_AGENT"   # 시험은 RPA_AGENT_MUTEX 로 따로
ERROR_ACCESS_DENIED = 5
ERROR_ALREADY_EXISTS = 183
_MUTEX = {}        # 이름 → 이 프로세스가 잡은 잠금. 프로세스가 끝나면 윈도우가 푼다


def single_instance(name=None):
    """이 윈도우 로그인에서 에이전트가 하나만 돌게 이름 있는 잠금(뮤텍스)을 잡는다. 이미 있으면 False.
    다른 권한(관리자)으로 만든 잠금이라 못 여는 것(접근 거부)도 '있다' 다. 그 밖의 까닭으로 못 만들면 막지 않는다
    (잠금 때문에 에이전트가 안 뜨면 안 된다). 같은 프로세스가 다시 부르면 True."""
    import ctypes
    name = name or MUTEX_NAME
    if name in _MUTEX:
        return True
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateMutexW.restype = ctypes.c_void_p
    k.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p)
    k.CloseHandle.argtypes = (ctypes.c_void_p,)
    ctypes.set_last_error(0)
    h = k.CreateMutexW(None, False, name)
    err = ctypes.get_last_error()
    if not h:
        return err != ERROR_ACCESS_DENIED
    if err == ERROR_ALREADY_EXISTS:
        k.CloseHandle(h)
        return False
    _MUTEX[name] = h
    return True
```
`main()` 의 docstring 끝 문장과 첫머리를 바꾼다:
```python
def main():
    """감독자. 설정을 읽거나 처음 물어 만들고 run() 을 돈다. 인증이 죽어 run() 이 멈추면 이유를 찍고 (창이 있으면)
    비밀번호를 다시 물어 다시 돈다. 종료 코드: 0 정상, 2 설정 문제, 3 인증이 죽었는데 창이 없어 다시 물을 수 없음,
    4 이 PC 에서 에이전트가 이미 돌고 있음 (background.py 가 이 코드들을 보고 다시 켤지 정한다)."""
    import secret

    if not single_instance():
        log("이 PC 에서 에이전트가 이미 돌고 있습니다 (창 없이 도는 에이전트일 수 있습니다). 이 창은 닫아도 됩니다")
        return 4
    try:
        cfg = secret.load_config()
```

- [ ] **Step 4: 통합 시험이 진짜 에이전트 잠금과 부딪히지 않게 (integration.js)**

`// --- 4. 에이전트 띄우기` 의 env 에 한 줄:
```js
  PYTHONIOENCODING: "utf-8",
  RPA_AGENT_MUTEX: `Local\\AFTER_MARKET_RPA_AGENT_IT_${process.pid}`,   // 개발 PC 에서 도는 진짜 에이전트의 잠금과 따로
};
```

- [ ] **Step 5: 시험 통과 확인**

Run: `cd D:\AX\RPA\firebase; python tests\test_agent.py`
Expected: `N/N 통과` (126 + 5)
Run (에뮬레이터): `. .\emu_env.ps1; cd tests; firebase emulators:exec --config ../firebase.json --only auth,database,firestore --project rpa-test-f02e0 "node integration.js"`
Expected: `32/32` 그대로

- [ ] **Step 6: 그래프 갱신** - `graphify update .` (커밋은 Task 8 에서 한 번)

---

### Task 2: 감독 `background.py`

설계 5절 '감독'. 작업 스케줄러 잡 동작은 설계 중에 실제 작업으로 확인했다 (`KILL_ON_JOB_CLOSE | SILENT_BREAKAWAY_OK`).

**Files:**
- Create: `firebase/agent/background.py`
- Create: `tests/test_background.py`

**Interfaces:**
- Consumes: 에이전트 종료 코드 0·2·3·4 (Task 1)
- Produces: `background.main(cmd=None, backoff=BACKOFF, healthy_sec=HEALTHY_SEC, sleep=time.sleep) -> int`, `STOP_CODES: dict`, `BACKOFF`, `HEALTHY_SEC`, `LOG_NAME = "에이전트_기록.txt"`, `ERR_NAME = "에이전트_오류.txt"`, `make_job()`, `agent_command() -> list[str]`. 작업 XML(Task 3)의 동작은 `{app}\python\pythonw.exe "{app}\firebase\agent\background.py"`

- [ ] **Step 1: 실패하는 시험 (tests/test_background.py)**

```python
"""감독(firebase/agent/background.py) 시험 - 가짜 에이전트로 종료 코드별 동작, 기다림, 창 없는 입출력, 잡(job).

    .venv\\Scripts\\python.exe tests\\test_background.py

가짜 에이전트는 진짜 파이썬(sys._base_executable)으로 띄운다. .venv 의 python.exe 는 진짜 파이썬을 자식으로 한 번
더 띄우는 껍데기라, 잡 시험에서 엉뚱한 프로세스(껍데기)를 보게 된다.
"""
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
check("에이전트 명령: pythonw 옆 python.exe 와 agent.py",
      os.path.basename(cmd[0]).lower() == "python.exe" and cmd[-1] == os.path.join(AGENT_DIR, "agent.py"), cmd)

shutil.rmtree(TMP, ignore_errors=True)
print()
print(f"실패: {'없음' if not fails else fails}")
sys.exit(1 if fails else 0)
```

- [ ] **Step 2: 실패 확인**

Run: `.venv\Scripts\python.exe tests\test_background.py`
Expected: `ModuleNotFoundError: No module named 'background'`

- [ ] **Step 3: 감독 구현 (firebase/agent/background.py)**

```python
"""에이전트 감독 (배포판 구조 2부 5절 - docs/superpowers/specs/2026-09-29-installer-design.md).

설치 마법사가 등록한 작업(AFTER MARKET\\RPA Agent)이 윈도우 로그인 때 pythonw 로 띄운다 - 창이 없다.
에이전트(agent.py)를 창 없는 python.exe 로 띄우고, 오류로 죽으면 잠시 뒤 다시 켠다. 사람이 고쳐야 하는 멈춤
(설정 없음·인증 멈춤·이미 돌고 있음)은 다시 켜지 않고 같이 끝난다 - 다음 윈도우 로그인이나 'RPA 설정' 저장 때 다시 켜진다.

에이전트는 이 프로세스의 잡(job)에 넣는다. 감독이 죽으면(작업 끝내기 포함) 에이전트도 같이 죽고, 에이전트가 띄운
RPA 는 잡에서 빠져 끝까지 간다 (2026-09-29 실제 작업으로 확인 - 설계 5절). 에이전트 코드는 불러오지 않는다 -
에이전트 파일이 깨져도 감독은 살아서 까닭을 남긴다. 시험: tests/test_background.py
"""
import ctypes
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


def agent_command():
    """창 없이 띄울 에이전트 명령. pythonw 옆 python.exe (둘 다 내장 파이썬) - 콘솔 프로그램이라 입출력이 있다."""
    py = os.path.join(os.path.dirname(sys.executable), "python.exe")
    return [py if os.path.isfile(py) else sys.executable, os.path.join(HERE, "agent.py")]


def start_agent(cmd, folder):
    """에이전트를 창 없이 띄운다. 입력 없음(사람에게 묻지 않는다), 출력 UTF-8 (파일로 돌리면 CP949 로 찍다 못 찍는
    글자에서 죽는다), 오류 출력은 파일에 덧붙인다."""
    err_path = os.path.join(folder, ERR_NAME)
    try:
        if os.path.getsize(err_path) > ERR_MAX:
            os.replace(err_path, err_path + ".1")
    except OSError:
        pass
    with open(err_path, "ab") as err:
        return subprocess.Popen(cmd, cwd=HERE, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=err,
                                env=dict(os.environ, PYTHONUTF8="1"), creationflags=CREATE_NO_WINDOW)


def main(cmd=None, backoff=BACKOFF, healthy_sec=HEALTHY_SEC, sleep=time.sleep):
    """에이전트를 띄우고 지킨다. 다시 켜지 않는 코드(STOP_CODES)로 끝나면 그 코드를 돌려주고 같이 끝난다.
    cmd·backoff·healthy_sec·sleep 은 시험용 (가짜 에이전트, 짧은 기다림)."""
    folder = log_dir()
    cmd = cmd or agent_command()
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
            return code
        fails = 1 if time.monotonic() - started >= healthy_sec else fails + 1
        wait = backoff[min(fails, len(backoff)) - 1]
        log(folder, f"에이전트가 멈췄습니다 (코드 {code}). {wait}초 뒤 다시 켭니다")
        sleep(wait)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 통과 확인**

Run: `.venv\Scripts\python.exe tests\test_background.py`
Expected: `실패: 없음` (19건쯤)

- [ ] **Step 5: 그래프 갱신** - `graphify update .`

---

### Task 3: 설정 창 - 창 없는 부분 (`rpa_settings.py`)

설계 4절(시작 점검·칸·저장·가져오기·창 없는 모드)과 5절(작업). 창(tkinter)과 `main` 은 Task 4.

**Files:**
- Create: `rpa_settings.py` (이 작업은 '창' 절 앞까지)
- Create: `tests/test_settings.py`

**Interfaces:**
- Consumes: `agent.MUTEX_NAME`, `agent.ERROR_ACCESS_DENIED`, `agent.single_instance`, `agent.first_run(path, cid, pc_id, password)`, `agent.auth_message(code)`, `agent.email_for`, `fb.AuthError(status, code)`, `secret.PUBLIC`, `secret.write_config`, `secret.load_config`, `secret.unprotect`, `secret.protect`, `secret.CONFIG_PATH`, `rpa_status` 의 `read_user_config(path)`, `write_user_config(data, path)`, `seal`, `unseal`, `_erpia_file`, `_erpia_install_dirs`, `new_layout`, `install_root`, `program_dir`, `config_dir`, `user_config_path`, `check_install`, `LOGIN_SECTION`·`SITES_SECTION`·`ERPIA_SECTION`·`USER_CONFIG_NAME`·`ERPIA_EXE_NAME`
- Produces (Task 4·5 가 쓴다): `TASK_NAME`, `TEMPLATE_NAME`, `AGENT_CONFIG_NAME`, `EXIT_RPA_RUNNING = 5`, `EXIT_STOP_FAILED = 6`, `FORM_KEYS`, `PASSWORD_KEYS`, `default_paths() -> dict` (키 `program_dir`·`config_dir`·`user_config`·`agent_config`·`template`·`agent_py`), `is_admin()`, `relaunch_as_admin(args)`, `process_user()`, `session_user()`, `same_account(a, b)`, `start_problem(session=None, me=None) -> str | None`, `run_quiet(args, timeout=60) -> (int, str)`, `list_processes() -> [(pid, name, exe, cmdline)]`, `old_agents(procs, agent_py)`, `rpa_running(procs)`, `agent_running(name=None)`, `task_xml(user, program_dir)`, `register_task(xml_text, folder, run)`, `start_task(run)`, `end_task(run)`, `delete_task(run)`, `stop_agent(procs=None, run, running, wait, sleep) -> int`, `restart_agent(run, running, wait, sleep)`, `pw_state(value, unseal)`, `mail_site(data)`, `load_state(paths) -> (form, state)`, `needs_agent_login(form, state)`, `validate(form, state) -> [str]`, `merge_user_config(base, form)`, `agent_login(path, cid, pc_id, password)`, `save(form, paths, login, run, running, user) -> [str]`, `configured(paths)`, `finish_upgrade(paths, run, running, user)`, `import_old(folder, config_dir, overwrite=False) -> [str]`, `retire_old_folder(folder) -> str`, `list_printers() -> [str]`

- [ ] **Step 1: 실패하는 시험 (tests/test_settings.py)**

```python
"""설정 창(rpa_settings.py)의 창 없는 부분 시험 - 칸 확인·설정 합치기·저장·작업 XML·옛 에이전트·멈추기·가져오기.

    .venv\\Scripts\\python.exe tests\\test_settings.py

새 구조 자리는 RPA_PROGRAMDATA 임시 폴더다 (이 PC 에 진짜 ProgramData\\AFTER MARKET\\RPA\\config 를 만들지 않는다).
로그인·작업 명령(schtasks)은 가짜로 바꿔 끼운다. 작업 XML 만은 관리자 권한 없이 되는 모양(LeastPrivilege)으로
진짜 작업 스케줄러에 한 번 등록해 보고 곧바로 지운다.
"""
import os
import shutil
import sys
import tempfile
import time
import urllib.error
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = tempfile.mkdtemp(prefix="rpa_settings_")
PD = os.path.join(TMP, "programdata", "AFTER MARKET", "RPA")
os.makedirs(os.path.join(PD, "config"))
os.makedirs(os.path.join(TMP, "agentdata"))
for _k in ("RPA_USER_CONFIG", "RPA_CRED_FILE", "RPA_AGENT_CONFIG"):
    os.environ.pop(_k, None)
os.environ["RPA_PROGRAMDATA"] = PD
os.environ["RPA_AGENT_QUEUE"] = os.path.join(TMP, "agentdata", "queue.jsonl")
os.environ["RPA_AGENT_MUTEX"] = rf"Local\AFTER_MARKET_RPA_AGENT_SETTINGS_TEST_{os.getpid()}"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "firebase" / "agent"))
sys.stdout.reconfigure(encoding="utf-8")

import agent  # noqa: E402
import fb  # noqa: E402
import rpa_settings as rs  # noqa: E402
import rpa_status as st  # noqa: E402
import secret  # noqa: E402

fails = []
_no = [0]


def check(name, cond, detail=""):
    _no[0] += 1
    mark = "통과" if cond else "실패"
    print(f"  {_no[0]:2d}. [{mark}] {name}" + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(f"{_no[0]}. {name} {detail}")


TEMPLATE = ROOT / "release" / "RPA_UserConfig.template.json"
ERP_PW, MAIL_PW, AGENT_PW = "Erp-Pw-1234!", "Mail-Pw-9876!", "Agent-Pw-5555!"


def paths_in(name):
    """시험용 자리. 설치 폴더 이름에 한글과 빈칸을 넣는다 (Program Files 처럼)."""
    d = os.path.join(TMP, name)
    cfg, prog = os.path.join(d, "config"), os.path.join(d, "설치 폴더")
    os.makedirs(cfg)
    os.makedirs(os.path.join(prog, "firebase", "agent"))
    shutil.copyfile(TEMPLATE, os.path.join(prog, rs.TEMPLATE_NAME))
    return {"program_dir": prog, "config_dir": cfg, "user_config": os.path.join(cfg, st.USER_CONFIG_NAME),
            "agent_config": os.path.join(cfg, rs.AGENT_CONFIG_NAME), "template": os.path.join(prog, rs.TEMPLATE_NAME),
            "agent_py": os.path.join(prog, "firebase", "agent", "agent.py")}


def good_form(**kw):
    f = dict(cid="net", pc_id="test", agent_pw=AGENT_PW, admin_code="AM001", erp_id="rpa", erp_pw=ERP_PW,
             erpia_path="", mail_id="mail@x.com", mail_pw=MAIL_PW, printer="사무실 프린터")
    f.update(kw)
    return f


class Recorder:
    """가짜 명령 실행기: schtasks 인수를 모은다."""

    def __init__(self, code=0):
        self.calls, self.code = [], code

    def __call__(self, args, timeout=60):
        self.calls.append(list(args))
        return self.code, ""

    def verbs(self):
        return [a[1] for a in self.calls]


class Running:
    """가짜 잠금: 처음엔 on, 작업을 끝내면(/End) off. sticky 면 끝까지 안 풀린다."""

    def __init__(self, on, rec=None, sticky=False):
        self.on, self.rec, self.sticky = on, rec, sticky

    def __call__(self):
        if self.on and not self.sticky and self.rec is not None and "/End" in self.rec.verbs():
            self.on = False
        return self.on


logins = []


def fake_login(path, cid, pc_id, password):
    logins.append((cid, pc_id))
    secret.write_config(path, dict(secret.PUBLIC, email=agent.email_for(cid, pc_id), cid=cid, pc_id=pc_id), password)


NONE_STATE = {"agent_pw": "none", "erp_pw": "none", "mail_pw": "none", "mail_site": "SITE1", "saved": (None, None)}
OK_STATE = {"agent_pw": "ok", "erp_pw": "ok", "mail_pw": "ok", "mail_site": "SITE1", "saved": ("net", "test")}

print("=== 1. 칸 확인 ===")
p = rs.validate({k: "" for k in rs.FORM_KEYS}, NONE_STATE)
check("빈 칸은 모두 알린다", all(any(w in x for x in p) for w in (
    "업체코드를 넣으세요", "PC코드를 넣으세요", "처음 설정이라 기계 계정 비밀번호", "ERPia 관리자코드", "ERPia 아이디",
    "ERPia 비밀번호")), p)
check("업체코드 대문자는 안 된다", any("소문자" in x for x in rs.validate(good_form(cid="Net"), NONE_STATE)))
check("다 채우면 통과", rs.validate(good_form(), NONE_STATE) == [])
f = good_form(agent_pw="", erp_pw="", mail_pw="")
check("저장된 값이 있으면 비밀번호 칸을 비워도 된다 (로그인도 다시 안 한다)",
      rs.validate(f, OK_STATE) == [] and not rs.needs_agent_login(f, OK_STATE))
f = good_form(cid="net2", agent_pw="")
check("코드를 바꾸면 기계 계정 비밀번호가 필요하다",
      rs.needs_agent_login(f, OK_STATE) and any("바꿔서" in x for x in rs.validate(f, OK_STATE)))
p = rs.validate(good_form(agent_pw="", erp_pw=""), dict(OK_STATE, agent_pw="bad", erp_pw="bad"))
check("못 푸는 저장값이면 다시 넣게 한다", any("풀 수 없어" in x for x in p) and any("ERPia 비밀번호" in x for x in p), p)
fake_exe = os.path.join(TMP, "erp", st.ERPIA_EXE_NAME)
os.makedirs(os.path.dirname(fake_exe))
open(fake_exe, "wb").close()
check("ERPia 위치: 다른 파일이면 알린다",
      any("ERPia 위치" in x for x in rs.validate(good_form(erpia_path=sys.executable), NONE_STATE)))
check("ERPia 위치: ERPiaMain.exe 나 그 폴더면 통과", rs.validate(good_form(erpia_path=fake_exe), NONE_STATE) == []
      and rs.validate(good_form(erpia_path=os.path.dirname(fake_exe)), NONE_STATE) == [])
check("메일 아이디만 있고 비밀번호가 없으면 알린다",
      any("메일 비밀번호" in x for x in rs.validate(good_form(mail_pw=""), NONE_STATE)))
check("메일 사이트가 없으면 메일 칸은 안 본다", rs.validate(good_form(mail_pw=""), dict(NONE_STATE, mail_site=None)) == [])

print("=== 2. 설정 합치기 ===")
base = st.read_user_config(str(TEMPLATE))
merged = rs.merge_user_config(base, good_form(erpia_path=os.path.dirname(fake_exe)))
check("ERPia 로그인 칸", merged["LogIn"] == {"AdminCode": "AM001", "ID": "rpa", "PW": ERP_PW}, merged["LogIn"])
check("실행 모듈은 빈 틀 그대로 (로그인만 Y)", merged["Routine"] == base["Routine"]
      and merged["Routine"]["Login"] == "Y" and merged["Routine"]["Sales"] == "N")
check("메일 사이트(SITE1) 아이디·비밀번호", merged["Sites"]["SITE1"]["ID"] == "mail@x.com"
      and merged["Sites"]["SITE1"]["PW"] == MAIL_PW)
check("다른 사이트·주석은 그대로", merged["Sites"]["SITE2"] == base["Sites"]["SITE2"]
      and merged["Sites"]["_주석"] == base["Sites"]["_주석"])
check("프린터만 바꾸고 물류 나머지는 그대로", merged["Logistic"]["Printer"] == "사무실 프린터" and
      {k: v for k, v in merged["Logistic"].items() if k != "Printer"} ==
      {k: v for k, v in base["Logistic"].items() if k != "Printer"})
check("ERPia 위치는 폴더를 줘도 exe 경로로, / 로", merged["ERPia"]["ExePath"] == fake_exe.replace("\\", "/"))
check("받은 dict 는 그대로 (사본에 쓴다)", base["LogIn"]["PW"] == "")
kept = rs.merge_user_config(dict(base, LogIn={"AdminCode": "a", "ID": "b", "PW": "dpapi:old"},
                                 ERPia={"ExePath": "C:/x/ERPiaMain.exe"}), good_form(erp_pw="", mail_pw="", erpia_path=""))
check("비밀번호 칸이 비면 저장된 값을 둔다", kept["LogIn"]["PW"] == "dpapi:old"
      and kept["Sites"]["SITE1"]["PW"] == base["Sites"]["SITE1"]["PW"])
check("ERPia 위치 칸이 비면 저장된 값을 둔다", kept["ERPia"]["ExePath"] == "C:/x/ERPiaMain.exe")

print("=== 3. 메일 사이트 고르기 ===")
check("빈 틀은 SITE1", rs.mail_site(base) == "SITE1")
check("Action 이 글자 하나여도, '_' 주석은 건너뛴다", rs.mail_site({"Sites": {
    "_x": {"Action": "mail_download"}, "A": {"Action": "login"}, "B": {"Action": "mail_download"}}}) == "B")
check("없으면 None", rs.mail_site({"Sites": {"A": {"Action": ["login", "sms_2fa"]}}}) is None and rs.mail_site({}) is None)

print("=== 4. 비밀번호 칸 상태 ===")
check("없음", rs.pw_state("", st.unseal) == "none" and rs.pw_state(None, st.unseal) == "none")
check("이 PC 에서 잠근 값은 ok", rs.pw_state(st.seal("abc"), st.unseal) == "ok"
      and rs.pw_state(secret.protect("abc"), secret.unprotect) == "ok")
check("못 푸는 값은 bad", rs.pw_state("dpapi:AAAA", st.unseal) == "bad" and rs.pw_state("AAAA", secret.unprotect) == "bad")
check("평문(손으로 적은 값)은 ok - 저장할 때 잠근다", rs.pw_state("plain", st.unseal) == "ok")

print("=== 5. 저장 ===")
P = paths_in("save")
rec = Recorder()
done = rs.save(good_form(), P, login=fake_login, run=rec, running=Running(False), user="PC\\me")
raw = Path(P["user_config"]).read_bytes()
check("처음 저장: 로그인·설정·에이전트 켜기", logins == [("net", "test")] and "에이전트를 켰습니다" in done, done)
check("비밀번호 평문이 파일에 없다", all(pw.encode() not in raw for pw in (ERP_PW, MAIL_PW))
      and AGENT_PW.encode() not in Path(P["agent_config"]).read_bytes())
cfg = st.read_user_config(P["user_config"])
check("잠가서 저장 (dpapi:)", cfg["LogIn"]["PW"].startswith("dpapi:") and st.unseal(cfg["LogIn"]["PW"]) == ERP_PW
      and st.unseal(cfg["Sites"]["SITE1"]["PW"]) == MAIL_PW)
check("작업 등록 뒤 켜기", rec.verbs() == ["/Create", "/Run"] and rec.calls[0][2:4] == ["/TN", rs.TASK_NAME], rec.calls)
check("작업 XML 은 잠깐 썼다 지운다", not os.path.exists(os.path.join(P["config_dir"], "agent_task.xml")))
first_pw = cfg["LogIn"]["PW"]
rec = Recorder()
done = rs.save(good_form(agent_pw="", erp_pw="", mail_pw="", printer="다른 프린터"), P, login=fake_login, run=rec,
               running=Running(True), user="PC\\me")
cfg = st.read_user_config(P["user_config"])
check("비밀번호를 비우고 프린터만 바꾸면 로그인·다시 켜기 없이 저장", len(logins) == 1 and rec.verbs() == ["/Create"]
      and "에이전트를 켰습니다" not in done, (logins, rec.verbs(), done))
check("비운 비밀번호 칸은 저장된 값 그대로", cfg["LogIn"]["PW"] == first_pw and cfg["Logistic"]["Printer"] == "다른 프린터")
rec = Recorder()
rs.save(good_form(agent_pw="new-agent-pw", erp_pw=""), P, login=fake_login, run=rec, running=Running(True, rec),
        user="PC\\me")
check("기계 계정을 다시 넣으면 멈췄다가 켠다", rec.verbs() == ["/Create", "/End", "/Run"] and len(logins) == 2, rec.verbs())
try:
    rs.save(good_form(cid="other", agent_pw="", erp_pw=""), P, login=fake_login, run=Recorder(), running=Running(False),
            user="PC\\me")
    check("코드만 바꾸고 비밀번호 없이 저장은 거절", False)
except ValueError as e:
    check("코드만 바꾸고 비밀번호 없이 저장은 거절", "바꿔서" in str(e), str(e))
P2 = paths_in("loginfail")


def refuse(*a):
    raise ValueError("기계 계정 로그인이 안 됩니다: 비밀번호가 맞지 않습니다")


try:
    rs.save(good_form(), P2, login=refuse, run=Recorder(), running=Running(False), user="PC\\me")
    check("로그인이 안 되면 아무것도 쓰지 않는다", False)
except ValueError:
    check("로그인이 안 되면 아무것도 쓰지 않는다", not os.path.exists(P2["user_config"])
          and not os.path.exists(P2["agent_config"]))
P3 = paths_in("notemplate")
os.remove(P3["template"])
try:
    rs.save(good_form(), P3, login=fake_login, run=Recorder(), running=Running(False), user="PC\\me")
    check("빈 틀이 없으면 멈춘다 (실행 모듈이 다 켜진 설정을 만들지 않게)", False)
except RuntimeError as e:
    check("빈 틀이 없으면 멈춘다 (실행 모듈이 다 켜진 설정을 만들지 않게)", "빈 틀" in str(e) and len(logins) == 2, str(e))
try:
    rs.save(good_form(agent_pw="", erp_pw=""), P, login=fake_login, run=Recorder(code=1), running=Running(False),
            user="PC\\me")
    check("작업 등록이 안 되면 알린다", False)
except RuntimeError as e:
    check("작업 등록이 안 되면 알린다", "자동 시작 작업을 등록하지 못했습니다" in str(e), str(e))

print("=== 6. 기계 계정 로그인 오류 문장 ===")
orig_first_run = agent.first_run
try:
    for exc, want in ((fb.AuthError(400, "INVALID_LOGIN_CREDENTIALS"), "비밀번호가 맞지 않습니다"),
                      (ValueError("기계 계정(agent-…)이 아닙니다"), "기계 계정(agent-…)이 아닙니다"),
                      (urllib.error.URLError("down"), "인터넷에 연결하지 못해")):
        def boom(*a, _e=exc, **k):
            raise _e
        agent.first_run = boom
        try:
            rs.agent_login("x.json", "net", "test", "pw")
            check(f"{type(exc).__name__} → 사람 문장", False)
        except ValueError as e:
            check(f"{type(exc).__name__} → 사람 문장", want in str(e), str(e))
finally:
    agent.first_run = orig_first_run

print("=== 7. 작업 XML ===")
prog = r"C:\Program Files\AFTER MARKET\RPA"
ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
x = ET.fromstring(rs.task_xml("PC\\me & you", prog).encode("utf-16"))


def val(path):
    e = x.find(path, ns)
    return e.text if e is not None else None


check("로그온 트리거와 계정 (& 도 이스케이프)", val("t:Triggers/t:LogonTrigger/t:UserId") == "PC\\me & you"
      and val("t:Principals/t:Principal/t:UserId") == "PC\\me & you")
check("로그온했을 때만, 가장 높은 권한", val("t:Principals/t:Principal/t:LogonType") == "InteractiveToken"
      and val("t:Principals/t:Principal/t:RunLevel") == "HighestAvailable")
check("이미 돌면 새로 안 띄움", val("t:Settings/t:MultipleInstancesPolicy") == "IgnoreNew")
check("배터리여도 켜고 안 멈춤 (노트북)", val("t:Settings/t:DisallowStartIfOnBatteries") == "false"
      and val("t:Settings/t:StopIfGoingOnBatteries") == "false")
check("실행 시간 제한 없음 (기본 3일)", val("t:Settings/t:ExecutionTimeLimit") == "PT0S")
check("우선순위 5 (기본 7 은 낮음)", val("t:Settings/t:Priority") == "5")
check("동작: 내장 pythonw 로 background.py", val("t:Actions/t:Exec/t:Command") == prog + r"\python\pythonw.exe"
      and val("t:Actions/t:Exec/t:Arguments") == f'"{prog}\\firebase\\agent\\background.py"'
      and val("t:Actions/t:Exec/t:WorkingDirectory") == prog + r"\firebase\agent")
name = f"RPA_settings_selftest_{os.getpid()}"
xf = os.path.join(TMP, "selftest.xml")
with open(xf, "w", encoding="utf-16") as f:
    f.write(rs.task_xml(rs.process_user(), prog).replace("HighestAvailable", "LeastPrivilege"))
try:
    code, out = rs.run_quiet(["schtasks", "/Create", "/TN", name, "/XML", xf, "/F"])
    qcode, q = rs.run_quiet(["schtasks", "/Query", "/TN", name, "/XML"])
    check("진짜 작업 스케줄러가 XML 을 받는다 (관리자 권한 없이 되는 LeastPrivilege 로 등록 → 조회)",
          code == 0 and qcode == 0 and "<Priority>5</Priority>" in q and "<ExecutionTimeLimit>PT0S</ExecutionTimeLimit>" in q,
          out[-300:])
finally:
    rs.run_quiet(["schtasks", "/Delete", "/TN", name, "/F"])
check("시험 작업은 지웠다", rs.run_quiet(["schtasks", "/Query", "/TN", name])[0] != 0)

print("=== 8. 옛 에이전트·도는 RPA ===")
ours = r"C:\Program Files\AFTER MARKET\RPA\firebase\agent\agent.py"
procs = [
    (11, "python.exe", r"C:\Program Files\AFTER MARKET\RPA\python\python.exe",
     rf'"C:\Program Files\AFTER MARKET\RPA\python\python.exe" "{ours}"'),
    (12, "python.exe", r"D:\AX\배포_2026.09.29-4\python\python.exe",
     r'"D:\AX\배포_2026.09.29-4\firebase\agent\..\..\python\python.exe"  agent.py'),
    (13, "pythonw.exe", r"C:\Program Files\AFTER MARKET\RPA\python\pythonw.exe",
     r'"C:\Program Files\AFTER MARKET\RPA\python\pythonw.exe" "C:\Program Files\AFTER MARKET\RPA\firebase\agent\background.py"'),
    (14, "python.exe", r"C:\Python\python.exe", "python useragent.py"),
    (15, "ERPia_RPA.exe", r"C:\Program Files\AFTER MARKET\RPA\ERPia_RPA.exe", ""),
    (16, "pythonw.exe", r"D:\old\python\pythonw.exe", r"pythonw D:\old\firebase\agent\agent.py"),
]
check("옛 에이전트만 가린다 (상대 경로·다른 폴더)", [p[0] for p in rs.old_agents(procs, ours)] == [12, 16],
      rs.old_agents(procs, ours))
check("도는 RPA", rs.rpa_running(procs) == ["ERPia_RPA.exe"] and rs.rpa_running([]) == [])
mine = [p for p in rs.list_processes() if p[0] == os.getpid()]
check("진짜 프로세스 목록에 이 시험 프로세스 (명령줄 포함)", len(mine) == 1 and "test_settings.py" in mine[0][3], mine)

print("=== 9. 멈추기·켜기 ===")
rec = Recorder()
check("RPA 가 돌면 5 (작업은 건드리지 않는다)", rs.stop_agent(procs=[(15, "ERPia_RPA.exe", "", "")], run=rec,
                                                  running=Running(True)) == rs.EXIT_RPA_RUNNING and rec.calls == [])
rec = Recorder()
check("끝내고 잠금이 풀리면 0", rs.stop_agent(procs=[], run=rec, running=Running(True, rec)) == 0
      and rec.verbs() == ["/End"])
rec = Recorder()
check("잠금이 안 풀리면 6", rs.stop_agent(procs=[], run=rec, running=Running(True, rec, sticky=True), wait=0.3,
                                      sleep=lambda s: time.sleep(0.05)) == rs.EXIT_STOP_FAILED)
rec = Recorder()
rs.restart_agent(run=rec, running=Running(False))
check("꺼져 있으면 켜기만", rec.verbs() == ["/Run"])
try:
    rs.restart_agent(run=Recorder(), running=Running(True, sticky=True), wait=0.3, sleep=lambda s: time.sleep(0.05))
    check("안 멈추면 알린다", False)
except RuntimeError as e:
    check("안 멈추면 알린다", "멈추지 않습니다" in str(e))
try:
    rs.start_task(run=Recorder(code=1))
    check("켜기가 안 되면 알린다", False)
except RuntimeError as e:
    check("켜기가 안 되면 알린다", "켜지 못했습니다" in str(e))

print("=== 10. 에이전트 잠금 ===")
check("잠금이 없으면 꺼져 있음", rs.agent_running() is False)
check("에이전트가 잠그면 돌고 있음", agent.single_instance() is True and rs.agent_running() is True)

print("=== 11. 옛 폴더에서 가져오기 ===")
old = os.path.join(TMP, "배포_2026.09.29-4")
os.makedirs(os.path.join(old, "firebase", "agent"))
old_cfg = st.read_user_config(str(TEMPLATE))
old_cfg["LogIn"].update(AdminCode="OLD", ID="old", PW="dpapi:AAAA")     # 다른 PC 에서 잠근 값 흉내
st.write_user_config(old_cfg, os.path.join(old, st.USER_CONFIG_NAME))
secret.write_config(os.path.join(old, "firebase", "agent", rs.AGENT_CONFIG_NAME),
                    dict(secret.PUBLIC, email=agent.email_for("net", "test"), cid="net", pc_id="test"), AGENT_PW)
Q = paths_in("import")
check("두 파일을 가져온다", rs.import_old(old, Q["config_dir"]) == [st.USER_CONFIG_NAME, rs.AGENT_CONFIG_NAME])
form, state = rs.load_state(Q)
check("가져온 값으로 칸을 채운다 (비밀번호 칸은 비움)", form["cid"] == "net" and form["admin_code"] == "OLD"
      and form["agent_pw"] == "" and state["saved"] == ("net", "test"), (form, state))
check("이 PC 에서 잠근 기계 계정은 ok, 못 푸는 ERPia 비밀번호는 bad", state["agent_pw"] == "ok" and state["erp_pw"] == "bad")
try:
    rs.import_old(old, Q["config_dir"])
    check("이미 있으면 묻는다 (FileExistsError)", False)
except FileExistsError as e:
    check("이미 있으면 묻는다 (FileExistsError)", st.USER_CONFIG_NAME in str(e))
check("덮어쓰기", rs.import_old(old, Q["config_dir"], overwrite=True) == [st.USER_CONFIG_NAME, rs.AGENT_CONFIG_NAME])
only = os.path.join(TMP, "only_user")
os.makedirs(only)
shutil.copyfile(os.path.join(old, st.USER_CONFIG_NAME), os.path.join(only, st.USER_CONFIG_NAME))
check("하나만 있으면 그것만", rs.import_old(only, paths_in("import2")["config_dir"]) == [st.USER_CONFIG_NAME])
try:
    rs.import_old(os.path.join(TMP, "erp"), paths_in("import3")["config_dir"])
    check("설정 파일이 없는 폴더는 FileNotFoundError", False)
except FileNotFoundError:
    check("설정 파일이 없는 폴더는 FileNotFoundError", True)
new = rs.retire_old_folder(old)
check("옛 폴더 이름 바꾸기 → _옮김", new == old + "_옮김" and os.path.isdir(new) and not os.path.exists(old))
os.makedirs(old)
check("또 바꾸면 _옮김2", rs.retire_old_folder(old) == old + "_옮김2")

print("=== 12. 계정·설치 확인 ===")
check("계정 비교는 대소문자 무시", rs.same_account("PC\\Me", "pc\\me") and not rs.same_account("PC\\a", None)
      and not rs.same_account("", ""))
p = rs.start_problem(session="PC\\staff", me="PC\\admin")
check("다른 계정의 권한으로 뜨면 멈춘다", p is not None and "PC\\staff" in p and "PC\\admin" in p, p)
check("같은 계정이면 통과", rs.start_problem(session="PC\\me", me="pc\\ME") is None)
check("세션 계정을 못 알아내면 막지 않는다", rs.start_problem(session="", me="PC\\me") is None)
os.environ["RPA_PROGRAMDATA"] = os.path.join(TMP, "no_install")
try:
    p = rs.start_problem(session="PC\\me", me="PC\\me")
    check("설치 마법사로 설치한 PC 가 아니면 멈춘다", p is not None and "설치 마법사" in p, p)
finally:
    os.environ["RPA_PROGRAMDATA"] = PD
check("이 PC: 이 시험 프로세스의 계정 = 로그인한 계정", rs.same_account(rs.process_user(), rs.session_user()),
      (rs.process_user(), rs.session_user()))

print("=== 13. 판 올림 (--after-install) ===")
check("설정을 마친 PC 는 판 올림으로 본다", rs.configured(P))
check("처음 설치는 아니다", not rs.configured(paths_in("fresh")))
R = paths_in("badagent")
shutil.copyfile(P["user_config"], R["user_config"])
with open(R["agent_config"], "w", encoding="utf-8") as f:
    f.write('{"project_id": "p", "api_key": "k", "database_url": "u", "cid": "net", "pc_id": "test", '
            '"email": "e", "password_dpapi": "AAAA"}')
check("기계 계정 비밀번호가 안 풀리면 판 올림이 아니다 (창을 띄운다)", not rs.configured(R))
rec = Recorder()
rs.finish_upgrade(P, run=rec, running=Running(False), user="PC\\me")
check("판 올림: 작업 다시 등록 → 켜기", rec.verbs() == ["/Create", "/Run"])

print("=== 14. 그 밖 ===")
check("프린터 목록은 글자 목록", isinstance(rs.list_printers(), list) and all(isinstance(n, str) for n in rs.list_printers()))

shutil.rmtree(TMP, ignore_errors=True)
print()
print(f"실패: {'없음' if not fails else fails}")
sys.exit(1 if fails else 0)
```

- [ ] **Step 2: 실패 확인**

Run: `.venv\Scripts\python.exe tests\test_settings.py`
Expected: `ModuleNotFoundError: No module named 'rpa_settings'`

- [ ] **Step 3: 구현 (rpa_settings.py - '창' 절 앞까지)**

```python
r"""RPA 설정 창 (배포판 구조 2부 4절 - docs/superpowers/specs/2026-09-29-installer-design.md).

설치 마법사(AFTER_MARKET_RPA_Setup_<판>.exe)로 설치한 PC 에서만 돈다. 설치 마지막에 한 번 뜨고, 그 뒤로는 시작 메뉴
'RPA 설정' 으로 연다.

    {설치 폴더}\python\pythonw.exe {설치 폴더}\rpa_settings.py [--after-install [--no-window] | --stop | --remove-task]

창: 기계 계정(업체코드·PC코드·비밀번호), ERPia 로그인·위치, 메일 사이트, 프린터를 받아 저장하고, 윈도우 로그인 때
에이전트를 창 없이 켜는 작업(AFTER MARKET\RPA Agent)을 등록하고 에이전트를 켠다. 옛 배포 폴더에서 설정을 가져온다.
창 없는 모드는 설치 파일(release/installer.iss)이 부른다. 종료 코드: 0 됨, 5 RPA 가 돌고 있음, 6 에이전트가 안 멈춤.

비밀번호는 잠근 뒤에만 파일에 쓰고(rpa_status.write_user_config, secret.write_config), 창의 다른 곳·기록·오류 글에
싣지 않는다. 시험: tests/test_settings.py (창 없이), tests/check_settings_ui.py (진짜 창).
"""
import base64
import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from xml.sax.saxutils import escape

HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (HERE, os.path.join(HERE, "firebase", "agent")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import rpa_status as st  # noqa: E402

TASK_NAME = r"AFTER MARKET\RPA Agent"
TEMPLATE_NAME = "RPA_UserConfig.template.json"   # 설치 파일이 빈 틀 RPA_UserConfig.json 을 이 이름으로 넣는다
AGENT_CONFIG_NAME = "agent_config.json"
LOGISTIC_SECTION = "Logistic"
KEY_RE = re.compile(r"[a-z0-9_]+")               # 업체코드·PC코드 (agent.ask_key 와 같은 규칙)
AGENT_PY_RE = re.compile(r"""(^|[\\/\s"'])agent\.py\b""", re.IGNORECASE)
RPA_EXES = ("ERPia_RPA.exe", "Prepare_RPA.exe")
EXIT_RPA_RUNNING = 5
EXIT_STOP_FAILED = 6
STOP_WAIT_SEC = 15
CREATE_NO_WINDOW = 0x08000000
FORM_KEYS = ("cid", "pc_id", "agent_pw", "admin_code", "erp_id", "erp_pw", "erpia_path", "mail_id", "mail_pw", "printer")
PASSWORD_KEYS = ("agent_pw", "erp_pw", "mail_pw")


# ---------------------------------------------------------------------------
# 자리와 계정 (설계 4절 시작 점검)
# ---------------------------------------------------------------------------
def default_paths():
    """이 PC 의 자리: 설치 폴더(program_dir)와 새 구조 config. 시험은 같은 모양의 dict 를 직접 만든다."""
    import secret
    prog = st.program_dir()
    return {"program_dir": prog, "config_dir": st.config_dir(), "user_config": st.user_config_path(),
            "agent_config": secret.CONFIG_PATH, "template": os.path.join(prog, TEMPLATE_NAME),
            "agent_py": os.path.join(prog, "firebase", "agent", "agent.py")}


def is_admin():
    try:
        return bool(ctypes.WinDLL("shell32").IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin(args):
    """관리자 권한으로 자기를 다시 띄운다 (UAC 요청). 띄웠으면 True, 사용자가 거절하면 False."""
    sh = ctypes.WinDLL("shell32")
    sh.ShellExecuteW.restype = ctypes.c_void_p
    sh.ShellExecuteW.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_wchar_p,
                                 ctypes.c_wchar_p, ctypes.c_int)
    params = subprocess.list2cmdline([os.path.abspath(__file__), *args])
    return (sh.ShellExecuteW(None, "runas", sys.executable, params, HERE, 1) or 0) > 32


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


def start_problem(session=None, me=None):
    """창을 띄우기 전 확인 (설계 4절 시작 점검 2·3). 사람에게 보일 문장, 문제가 없으면 None.
    session·me 는 시험용 (안 주면 이 PC 에서 알아낸다. session 이 빈 글자면 '못 알아냄' 으로 본다)."""
    if not st.new_layout():
        return (f"설치 마법사로 설치한 PC 가 아닙니다 ({os.path.join(st.install_root(), 'config')} 이 없습니다).\n"
                "AFTER_MARKET_RPA_Setup 으로 설치한 뒤 시작 메뉴의 'RPA 설정' 을 여세요.")
    me = me or process_user()
    session = session_user() if session is None else session
    if session and not same_account(me, session):
        return (f"이 PC 에 로그인한 윈도우 계정({session})이 아니라 다른 계정({me})의 관리자 권한으로 이 창이 떴습니다.\n"
                f"RPA 는 로그인한 계정으로 돕니다. {session} 계정을 관리자로 바꾼 뒤 그 계정으로 다시 설치하거나 "
                "'RPA 설정' 을 여세요.")
    return None


# ---------------------------------------------------------------------------
# 프로세스와 에이전트 잠금
# ---------------------------------------------------------------------------
def run_quiet(args, timeout=60):
    """창 없이 명령을 돌린다. (종료 코드, 출력 글자). 콘솔 명령은 OEM 코드 페이지로 찍는다."""
    r = subprocess.run(args, capture_output=True, timeout=timeout, creationflags=CREATE_NO_WINDOW)
    return r.returncode, (r.stdout + r.stderr).decode("oem", "replace")


def list_processes():
    """[(pid, 이름, 실행 파일, 명령줄)] - python 과 RPA exe 만. 관리자 권한이어야 관리자로 뜬 프로세스의 명령줄도 보인다.
    PowerShell 명령은 인코딩해서 넘긴다 (따옴표가 명령줄에서 깨지지 않게)."""
    names = " or ".join(f"Name='{n}'" for n in ("python.exe", "pythonw.exe") + RPA_EXES)
    script = ("[Console]::OutputEncoding = [Text.Encoding]::UTF8; ConvertTo-Json -Compress -InputObject @("
              f"Get-CimInstance Win32_Process -Filter \"{names}\" | Select-Object ProcessId,Name,ExecutablePath,CommandLine)")
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand",
                        base64.b64encode(script.encode("utf-16-le")).decode("ascii")],
                       capture_output=True, timeout=60, creationflags=CREATE_NO_WINDOW)
    text = r.stdout.decode("utf-8-sig", "replace").strip()
    data = json.loads(text) if text else []
    if isinstance(data, dict):
        data = [data]
    return [(int(p.get("ProcessId") or 0), p.get("Name") or "", p.get("ExecutablePath") or "",
             p.get("CommandLine") or "") for p in data if isinstance(p, dict)]


def old_agents(procs, agent_py):
    """설치 폴더 밖의(또는 작업 밖에서 띄운) 에이전트 [(pid, 실행 파일, 명령줄)]: 명령줄에 agent.py 가 있는데 설치 폴더
    agent.py 의 절대 경로가 아닌 python. 옛 에이전트_시작.bat 은 'python agent.py' 로(상대 경로) 띄운다."""
    ours = os.path.normcase(os.path.abspath(agent_py))
    return [(pid, exe, cmd) for pid, name, exe, cmd in procs
            if name.lower() in ("python.exe", "pythonw.exe") and AGENT_PY_RE.search(cmd)
            and ours not in os.path.normcase(cmd)]


def rpa_running(procs):
    """도는 RPA exe 이름 (정렬)."""
    wanted = {n.lower(): n for n in RPA_EXES}
    return sorted({wanted[name.lower()] for _, name, _, _ in procs if name.lower() in wanted})


def agent_running(name=None):
    """에이전트 잠금이 있나 (agent.single_instance 가 잡는다). 권한 때문에 못 여는 것도 '있다'."""
    import agent
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenMutexW.restype = ctypes.c_void_p
    k.OpenMutexW.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p)
    k.CloseHandle.argtypes = (ctypes.c_void_p,)
    h = k.OpenMutexW(0x00100000, False, name or agent.MUTEX_NAME)          # SYNCHRONIZE
    if h:
        k.CloseHandle(h)
        return True
    return ctypes.get_last_error() == agent.ERROR_ACCESS_DENIED


# ---------------------------------------------------------------------------
# 자동 시작 작업 (설계 5절)
# ---------------------------------------------------------------------------
def task_xml(user, program_dir):
    """작업 스케줄러 XML. 기본값(3일 제한·배터리면 멈춤·낮은 우선순위)을 믿지 않고 모두 적는다."""
    py = os.path.join(program_dir, "python", "pythonw.exe")
    agent_dir = os.path.join(program_dir, "firebase", "agent")
    script = os.path.join(agent_dir, "background.py")
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>AFTER MARKET RPA 에이전트 - 윈도우 로그인 때 창 없이 켠다 (설치 마법사가 등록)</Description></RegistrationInfo>
  <Triggers><LogonTrigger><Enabled>true</Enabled><UserId>{escape(user)}</UserId></LogonTrigger></Triggers>
  <Principals>
    <Principal id="Author"><UserId>{escape(user)}</UserId><LogonType>InteractiveToken</LogonType><RunLevel>HighestAvailable</RunLevel></Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>false</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>5</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec><Command>{escape(py)}</Command><Arguments>"{escape(script)}"</Arguments><WorkingDirectory>{escape(agent_dir)}</WorkingDirectory></Exec>
  </Actions>
</Task>
"""


def register_task(xml_text, folder, run=run_quiet):
    """작업을 등록한다 (같은 이름이면 덮는다). XML 은 folder 에 잠깐 썼다 지운다. 안 되면 RuntimeError."""
    path = os.path.join(folder, "agent_task.xml")
    with open(path, "w", encoding="utf-16") as f:
        f.write(xml_text)
    try:
        code, out = run(["schtasks", "/Create", "/TN", TASK_NAME, "/XML", path, "/F"])
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    if code != 0:
        raise RuntimeError(f"자동 시작 작업을 등록하지 못했습니다: {out.strip()[-300:]}")


def start_task(run=run_quiet):
    code, out = run(["schtasks", "/Run", "/TN", TASK_NAME])
    if code != 0:
        raise RuntimeError(f"에이전트를 켜지 못했습니다: {out.strip()[-300:]}")


def end_task(run=run_quiet):
    """작업을 끝낸다 - 감독이 죽으면 잡이 에이전트도 끝낸다. 작업이 없거나 안 돌고 있어도 괜찮다."""
    run(["schtasks", "/End", "/TN", TASK_NAME])


def delete_task(run=run_quiet):
    run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"])


def wait_released(running, wait=STOP_WAIT_SEC, sleep=time.sleep):
    """에이전트 잠금이 풀릴 때까지 기다린다. 풀렸으면 True."""
    until = time.monotonic() + wait
    while running():
        if time.monotonic() >= until:
            return False
        sleep(0.5)
    return True


def stop_agent(procs=None, run=run_quiet, running=None, wait=STOP_WAIT_SEC, sleep=time.sleep):
    """--stop (설치 파일이 판을 올리거나 지우기 전에 부른다). RPA 가 돌면 5 - 도는 exe 는 덮어쓸 수 없다.
    작업을 끝내고 잠금이 풀리면 0, 안 풀리면 6 (작업 밖에서 띄운 에이전트 창)."""
    procs = list_processes() if procs is None else procs
    if rpa_running(procs):
        return EXIT_RPA_RUNNING
    end_task(run)
    return 0 if wait_released(running or agent_running, wait, sleep) else EXIT_STOP_FAILED


def restart_agent(run=run_quiet, running=None, wait=STOP_WAIT_SEC, sleep=time.sleep):
    """에이전트를 켠다. 돌고 있으면 끝내고 잠금이 풀린 뒤 켠다 (도는 RPA 는 잡에서 빠져 있어 끝까지 간다)."""
    running = running or agent_running
    if running():
        end_task(run)
        if not wait_released(running, wait, sleep):
            raise RuntimeError("에이전트가 멈추지 않습니다. 에이전트 창(에이전트_시작.bat)이 열려 있으면 닫고 다시 저장하세요")
    start_task(run)


# ---------------------------------------------------------------------------
# 설정 읽기·확인·합치기·저장 (설계 4절 '칸'·'저장')
# ---------------------------------------------------------------------------
def read_agent_raw(path):
    """agent_config.json 을 비밀번호를 풀지 않고 읽는다. 없거나 깨졌으면 {}."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def pw_state(value, unseal):
    """저장된 비밀번호 칸: 'none' 없음 / 'ok' 풀림 / 'bad' 못 풂 (다른 PC·계정에서 잠근 값)."""
    if not value:
        return "none"
    try:
        unseal(value)
        return "ok"
    except Exception:
        return "bad"


def mail_site(data):
    """메일 칸이 고치는 사이트 이름: Action 에 mail_download 가 든 첫 사이트. 없으면 None."""
    sites = data.get(st.SITES_SECTION)
    if not isinstance(sites, dict):
        return None
    for name, site in sites.items():
        if name.startswith("_") or not isinstance(site, dict):
            continue
        actions = site.get("Action") if isinstance(site.get("Action"), list) else [site.get("Action")]
        if "mail_download" in actions:
            return name
    return None


def _section(data, name):
    value = data.get(name)
    return value if isinstance(value, dict) else {}


def load_state(paths):
    """창에 채울 값과 비밀번호 칸 상태 (form, state). form 의 비밀번호 칸은 늘 비어 있다.
    state: agent_pw·erp_pw·mail_pw 는 'none'|'ok'|'bad', mail_site 는 사이트 이름|None, saved 는 저장된 (cid, pc_id)."""
    import secret
    raw = read_agent_raw(paths["agent_config"])
    path = paths["user_config"] if os.path.isfile(paths["user_config"]) else paths["template"]
    data = st.read_user_config(path) if os.path.isfile(path) else {}
    login, erpia, logistic = _section(data, st.LOGIN_SECTION), _section(data, st.ERPIA_SECTION), _section(data, LOGISTIC_SECTION)
    site_name = mail_site(data)
    site = data[st.SITES_SECTION][site_name] if site_name else {}
    exe = st._erpia_file(erpia.get("ExePath")) or next(
        (found for found in (st._erpia_file(d) for d in st._erpia_install_dirs()) if found), "")
    form = {k: "" for k in FORM_KEYS}
    form.update(cid=str(raw.get("cid") or ""), pc_id=str(raw.get("pc_id") or ""),
                admin_code=str(login.get("AdminCode") or ""), erp_id=str(login.get("ID") or ""),
                erpia_path=exe.replace("\\", "/"), mail_id=str(site.get("ID") or ""),
                printer=str(logistic.get("Printer") or ""))
    state = {"agent_pw": pw_state(raw.get("password_dpapi"), secret.unprotect),
             "erp_pw": pw_state(login.get("PW"), st.unseal),
             "mail_pw": pw_state(site.get("PW"), st.unseal) if site_name else "none",
             "mail_site": site_name, "saved": (raw.get("cid"), raw.get("pc_id"))}
    return form, state


def needs_agent_login(form, state):
    """기계 계정 로그인을 다시 해야 하나: 비밀번호를 넣었거나, 코드가 바뀌었거나, 저장된 비밀번호가 없거나 안 풀린다."""
    return (bool(form["agent_pw"]) or state["agent_pw"] != "ok"
            or (form["cid"], form["pc_id"]) != tuple(state["saved"]))


def validate(form, state):
    """칸 확인 (설계 4절 표). 사람에게 보일 문장 목록 - 비면 통과."""
    out = []
    for key, label in (("cid", "업체코드"), ("pc_id", "PC코드")):
        if not form[key]:
            out.append(f"{label}를 넣으세요")
        elif not KEY_RE.fullmatch(form[key]):
            out.append(f"{label}는 영어 소문자·숫자·밑줄(_)만 쓸 수 있습니다")
    if needs_agent_login(form, state) and not form["agent_pw"]:
        why = {"none": "처음 설정이라", "bad": "저장된 비밀번호를 이 PC 에서 풀 수 없어"}.get(
            state["agent_pw"], "업체코드나 PC코드를 바꿔서")
        out.append(f"{why} 기계 계정 비밀번호를 넣어야 합니다")
    if not form["admin_code"]:
        out.append("ERPia 관리자코드를 넣으세요")
    if not form["erp_id"]:
        out.append("ERPia 아이디를 넣으세요")
    if not form["erp_pw"] and state["erp_pw"] != "ok":
        out.append("ERPia 비밀번호를 넣으세요" + (" (저장된 값을 이 PC 에서 풀 수 없습니다)" if state["erp_pw"] == "bad" else ""))
    if form["erpia_path"] and not st._erpia_file(form["erpia_path"]):
        out.append(f"ERPia 위치에 {st.ERPIA_EXE_NAME} 가 없습니다. [찾기] 로 고르거나 비워 두세요")
    if state["mail_site"] and form["mail_id"] and not form["mail_pw"] and state["mail_pw"] != "ok":
        out.append("메일 비밀번호를 넣으세요" + (" (저장된 값을 이 PC 에서 풀 수 없습니다)" if state["mail_pw"] == "bad" else ""))
    return out


def merge_user_config(base, form):
    """칸 값을 사용자 설정({섹션: {키: 값}})에 넣은 사본. 비밀번호·ERPia 위치 칸이 비었으면 저장된 값을 그대로 둔다.
    다른 섹션·키·주석은 건드리지 않는다. 비밀번호 잠그기는 write_user_config 가 한다."""
    data = json.loads(json.dumps(base, ensure_ascii=False))
    login = data[st.LOGIN_SECTION] = _section(data, st.LOGIN_SECTION)
    login["AdminCode"], login["ID"] = form["admin_code"], form["erp_id"]
    if form["erp_pw"]:
        login["PW"] = form["erp_pw"]
    exe = st._erpia_file(form["erpia_path"]) if form["erpia_path"] else None
    if exe:
        data[st.ERPIA_SECTION] = dict(_section(data, st.ERPIA_SECTION), ExePath=exe.replace("\\", "/"))
    site_name = mail_site(data)
    if site_name:
        site = data[st.SITES_SECTION][site_name]
        site["ID"] = form["mail_id"]
        if form["mail_pw"]:
            site["PW"] = form["mail_pw"]
    data[LOGISTIC_SECTION] = dict(_section(data, LOGISTIC_SECTION), Printer=form["printer"])
    return data


def agent_login(path, cid, pc_id, password):
    """기계 계정으로 실제 로그인해 보고 agent_config.json 을 쓴다 (agent.first_run). 안 되면 ValueError(사람 문장)."""
    import agent
    import fb
    try:
        agent.first_run(path, cid, pc_id, password)
    except fb.AuthError as e:
        raise ValueError(f"기계 계정 로그인이 안 됩니다: {agent.auth_message(e.code)}") from None
    except ValueError as e:
        raise ValueError(f"기계 계정 로그인이 안 됩니다: {e}") from None
    except OSError as e:
        raise ValueError(f"인터넷에 연결하지 못해 기계 계정을 확인하지 못했습니다 ({type(e).__name__}). "
                         "연결을 확인하고 다시 저장하세요") from None


def save(form, paths, login=agent_login, run=run_quiet, running=None, user=None):
    """저장 (설계 4절 '저장' 1~5). 한 일 문장 목록. 칸이 틀리거나 로그인이 안 되면 ValueError, 빈 틀이 없거나
    작업 등록·켜기가 안 되면 RuntimeError (둘 다 사람에게 보일 문장). 로그인이 안 되면 아무 파일도 쓰지 않는다."""
    _, state = load_state(paths)
    problems = validate(form, state)
    if problems:
        raise ValueError("\n".join(problems))
    base_path = paths["user_config"] if os.path.isfile(paths["user_config"]) else paths["template"]
    if not os.path.isfile(base_path):
        raise RuntimeError(f"빈 틀({TEMPLATE_NAME})이 없습니다. 설치 파일로 다시 설치하세요")
    done = []
    relogin = needs_agent_login(form, state)
    if relogin:
        login(paths["agent_config"], form["cid"], form["pc_id"], form["agent_pw"])
        done.append("기계 계정 로그인을 확인했습니다.")
    st.write_user_config(merge_user_config(st.read_user_config(base_path), form), paths["user_config"])
    done.append("설정을 저장했습니다.")
    register_task(task_xml(user or process_user(), paths["program_dir"]), paths["config_dir"], run)
    running = running or agent_running
    if relogin or not running():
        restart_agent(run, running)
        done.append("에이전트를 켰습니다.")
    return done


def configured(paths):
    """두 설정 파일이 다 있고 읽히나 - 기계 계정 비밀번호까지 풀려야 한다 (판을 올린 설치면 참)."""
    import secret
    if not os.path.isfile(paths["user_config"]):
        return False
    try:
        secret.load_config(paths["agent_config"])
        st.read_user_config(paths["user_config"])
        return True
    except Exception:
        return False


def finish_upgrade(paths, run=run_quiet, running=None, user=None):
    """판 올림 (--after-install 인데 설정이 이미 있다): 창 없이 작업을 다시 등록하고 에이전트를 켠다."""
    register_task(task_xml(user or process_user(), paths["program_dir"]), paths["config_dir"], run)
    restart_agent(run, running)


# ---------------------------------------------------------------------------
# 옛 배포 폴더에서 가져오기 (설계 4절)
# ---------------------------------------------------------------------------
def find_old_files(folder):
    """옛 배포 폴더의 설정 파일 [RPA_UserConfig.json, firebase\\agent\\agent_config.json] 중 있는 것."""
    return [p for p in (os.path.join(folder, st.USER_CONFIG_NAME),
                        os.path.join(folder, "firebase", "agent", AGENT_CONFIG_NAME)) if os.path.isfile(p)]


def import_old(folder, config_dir, overwrite=False):
    """옛 폴더의 설정 파일을 config_dir 로 복사한다. 복사한 이름 목록. 둘 다 없으면 FileNotFoundError,
    config_dir 에 이미 있는데 overwrite 가 아니면 FileExistsError(겹치는 이름)."""
    found = find_old_files(folder)
    if not found:
        raise FileNotFoundError(folder)
    pairs = [(src, os.path.join(config_dir, os.path.basename(src))) for src in found]
    clash = [os.path.basename(dst) for _, dst in pairs if os.path.exists(dst)]
    if clash and not overwrite:
        raise FileExistsError(", ".join(clash))
    for src, dst in pairs:
        shutil.copyfile(src, dst)          # 내용만 - 권한은 config 폴더 것을 물려받는다
    return [os.path.basename(dst) for _, dst in pairs]


def retire_old_folder(folder):
    """옛 폴더 이름을 <이름>_옮김 (있으면 _옮김2 …) 으로 바꾼다. 새 이름. 안 되면 OSError."""
    base = os.path.normpath(folder) + "_옮김"
    target, n = base, 2
    while os.path.exists(target):
        target, n = f"{base}{n}", n + 1
    os.rename(folder, target)
    return target


def list_printers():
    """이 PC 의 프린터 이름 (로컬과 연결된 네트워크 프린터, 정렬). 못 읽으면 []."""
    class Info4(ctypes.Structure):                      # PRINTER_INFO_4W
        _fields_ = [("pPrinterName", ctypes.c_wchar_p), ("pServerName", ctypes.c_wchar_p),
                    ("Attributes", ctypes.c_uint32)]
    try:
        w = ctypes.WinDLL("winspool.drv")
        w.EnumPrintersW.argtypes = (ctypes.c_uint32, ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_void_p,
                                    ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_uint32))
        flags = 0x2 | 0x4                                 # PRINTER_ENUM_LOCAL | PRINTER_ENUM_CONNECTIONS
        need, count = ctypes.c_uint32(), ctypes.c_uint32()
        w.EnumPrintersW(flags, None, 4, None, 0, ctypes.byref(need), ctypes.byref(count))
        if not need.value:
            return []
        buf = ctypes.create_string_buffer(need.value)
        if not w.EnumPrintersW(flags, None, 4, buf, need.value, ctypes.byref(need), ctypes.byref(count)):
            return []
        items = ctypes.cast(buf, ctypes.POINTER(Info4))
        return sorted({items[i].pPrinterName for i in range(count.value) if items[i].pPrinterName})
    except Exception:
        return []
```

- [ ] **Step 4: 통과 확인**

Run: `.venv\Scripts\python.exe tests\test_settings.py`
Expected: `실패: 없음` (60건쯤). 7절 진짜 작업 등록이 관리자 권한 없이 거부되면(로그온 트리거 때문일 수 있다) 원인을 보고 시험 XML 에서 트리거만 빼서 등록한다 - 이 시험은 Settings·Principal 모양을 작업 스케줄러가 받는지 보는 것이다.

- [ ] **Step 5: 그래프 갱신** - `graphify update .`

---

### Task 4: 설정 창 - 창과 모드 (`rpa_settings.py`)

설계 4절 화면·시작 점검·창 없는 모드. 칸은 한 줄에 '이름 | 입력 | 안내' (세로가 짧아야 768 높이 노트북에 들어간다).

**Files:**
- Modify: `rpa_settings.py` (끝에 '창' 절과 `main`)
- Create: `tests/check_settings_ui.py`

**Interfaces:**
- Consumes: Task 3 전부
- Produces: `SettingsWindow(root, paths, after_install=False, login=agent_login, run=run_quiet, running=None, procs=list_processes, printers=None, dialogs=None)` - 속성 `vars`, `entries`, `hints[key] = (label, 기본 안내)`, `status`, `msg`, `msg_label`, `saved`, `busy_now`, `imported_from`, `state`, 메서드 `reload()`, `on_save()`, `on_import()`, `on_browse()`, `on_close()`, `check_old_agents()`, `startup()`; `Dialogs` (info·error·yesno·retry·folder·exe), `PW_HINTS`, `RED`·`GREEN`·`GRAY`·`AMBER`, `dpi_aware()`, `run_window(paths, after_install=False)`, `show_error_box(text)`, `main(argv=None) -> int`

- [ ] **Step 1: 실패하는 확인 (tests/check_settings_ui.py)**

```python
"""설정 창(rpa_settings.SettingsWindow)을 진짜로 띄워 본다 - 첫 모습, 빈 칸 저장의 빨간 안내, 채워서 저장,
옛 폴더 가져오기 → 저장 → 이름 바꾸기, 없는 프린터, 옛 에이전트. 저장 뒤 화면 사진을 남긴다.

    .venv\\Scripts\\python.exe tests\\check_settings_ui.py [사진.png]

로그인·작업 등록·알림 창은 가짜라 관리자 권한도 인터넷도 필요 없다. 창이 몇 초 동안 화면에 뜬다.
새 구조 자리는 RPA_PROGRAMDATA 임시 폴더다.
"""
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = tempfile.mkdtemp(prefix="rpa_settings_ui_")
PD = os.path.join(TMP, "programdata", "AFTER MARKET", "RPA")
os.makedirs(os.path.join(PD, "config"))
os.makedirs(os.path.join(TMP, "agentdata"))
for _k in ("RPA_USER_CONFIG", "RPA_CRED_FILE", "RPA_AGENT_CONFIG"):
    os.environ.pop(_k, None)
os.environ["RPA_PROGRAMDATA"] = PD
os.environ["RPA_AGENT_QUEUE"] = os.path.join(TMP, "agentdata", "queue.jsonl")
os.environ["RPA_AGENT_MUTEX"] = rf"Local\AFTER_MARKET_RPA_AGENT_UI_TEST_{os.getpid()}"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "firebase" / "agent"))
sys.stdout.reconfigure(encoding="utf-8")

import tkinter as tk  # noqa: E402
from PIL import ImageGrab  # noqa: E402
import agent  # noqa: E402
import rpa_settings as rs  # noqa: E402
import rpa_status as st  # noqa: E402
import secret  # noqa: E402

SHOT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(TMP, "settings.png")
fails = []
_no = [0]


def check(name, cond, detail=""):
    _no[0] += 1
    mark = "통과" if cond else "실패"
    print(f"  {_no[0]:2d}. [{mark}] {name}" + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(f"{_no[0]}. {name} {detail}")


class FakeDialogs:
    def __init__(self):
        self.said, self.folder_result = [], None

    def info(self, text):
        self.said.append(("info", text))

    def error(self, text):
        self.said.append(("error", text))

    def yesno(self, text):
        self.said.append(("yesno", text))
        return True

    def retry(self, text):
        self.said.append(("retry", text))
        return False

    def folder(self, title):
        return self.folder_result

    def exe(self, start):
        return None


def fake_login(path, cid, pc_id, password):
    secret.write_config(path, dict(secret.PUBLIC, email=agent.email_for(cid, pc_id), cid=cid, pc_id=pc_id), password)


calls = []


def fake_run(args, timeout=60):
    calls.append(args[1])
    return 0, ""


prog = os.path.join(TMP, "설치 폴더")
os.makedirs(os.path.join(prog, "firebase", "agent"))
shutil.copyfile(ROOT / "release" / "RPA_UserConfig.template.json", os.path.join(prog, rs.TEMPLATE_NAME))
cfg = os.path.join(PD, "config")
paths = {"program_dir": prog, "config_dir": cfg, "user_config": os.path.join(cfg, st.USER_CONFIG_NAME),
         "agent_config": os.path.join(cfg, rs.AGENT_CONFIG_NAME), "template": os.path.join(prog, rs.TEMPLATE_NAME),
         "agent_py": os.path.join(prog, "firebase", "agent", "agent.py")}


def wait_idle(sec=15):
    end = time.time() + sec
    while time.time() < end:
        root.update()
        if not win.busy_now:
            return True
        time.sleep(0.05)
    return False


rs.dpi_aware()
root = tk.Tk()
dlg = FakeDialogs()
win = rs.SettingsWindow(root, paths, login=fake_login, run=fake_run, running=lambda: False, procs=lambda: [],
                        printers=["사무실 프린터", "Microsoft Print to PDF"], dialogs=dlg)
root.update()

print("=== 1. 첫 모습 ===")
check("비밀번호 칸 안내: 처음", all(win.hints[k][0].cget("text") == rs.PW_HINTS["none"] for k in rs.PASSWORD_KEYS))
check("상태 줄: 버전 없음·에이전트 꺼짐", "버전 없음" in win.status.get() and "꺼져 있음" in win.status.get(), win.status.get())
check("메일 칸이 켜져 있다 (빈 틀에 SITE1)", str(win.entries["mail_id"].cget("state")) == "normal")
check("프린터 목록", list(win.entries["printer"].cget("values")) == ["", "사무실 프린터", "Microsoft Print to PDF"],
      win.entries["printer"].cget("values"))

print("=== 2. 빈 칸으로 저장 ===")
win.on_save()
wait_idle()
check("빨간 글씨로 무엇이 틀렸는지", "업체코드를 넣으세요" in win.msg.get() and win.msg_label.cget("fg") == rs.RED, win.msg.get())
check("저장 안 됨", not win.saved and not os.path.exists(paths["user_config"]))

print("=== 3. 채우고 저장 ===")
for k, v in dict(cid="net", pc_id="test", agent_pw="Agent-Pw-5555!", admin_code="AM001", erp_id="rpa",
                 erp_pw="Erp-Pw-1234!", mail_id="mail@x.com", mail_pw="Mail-Pw-9876!", printer="사무실 프린터").items():
    win.vars[k].set(v)
win.on_save()
ok = wait_idle()
check("저장됨 (초록 안내)", ok and win.saved and "에이전트를 켰습니다" in win.msg.get() and win.msg_label.cget("fg") == rs.GREEN,
      win.msg.get())
check("설정 파일 두 개", os.path.isfile(paths["user_config"]) and os.path.isfile(paths["agent_config"]))
check("작업 등록 → 켜기", calls == ["/Create", "/Run"], calls)
check("저장 뒤 비밀번호 칸은 비고 안내는 '저장됨'", all(win.vars[k].get() == "" for k in rs.PASSWORD_KEYS)
      and all(win.hints[k][0].cget("text") == rs.PW_HINTS["ok"] for k in rs.PASSWORD_KEYS))
root.update()
time.sleep(0.3)
root.update()
x, y, w, h = root.winfo_rootx(), root.winfo_rooty(), root.winfo_width(), root.winfo_height()
ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True).save(SHOT)
check(f"화면 사진 {SHOT} ({w}x{h})", os.path.isfile(SHOT))

print("=== 4. 옛 폴더 가져오기 → 저장 → 이름 바꾸기 ===")
old = os.path.join(TMP, "배포_옛")
os.makedirs(os.path.join(old, "firebase", "agent"))
shutil.copyfile(paths["user_config"], os.path.join(old, st.USER_CONFIG_NAME))
shutil.copyfile(paths["agent_config"], os.path.join(old, "firebase", "agent", rs.AGENT_CONFIG_NAME))
dlg.folder_result = old
win.on_import()
root.update()
check("이미 있으면 바꿀지 묻고 가져온다", any(k == "yesno" and "바꿀까요" in t for k, t in dlg.said)
      and "가져왔습니다" in win.msg.get(), win.msg.get())
win.on_save()
wait_idle()
check("저장 뒤 옛 폴더 이름을 바꾼다", os.path.isdir(old + "_옮김") and not os.path.exists(old), dlg.said[-2:])

print("=== 5. 없는 프린터 ===")
data = st.read_user_config(paths["user_config"])
data["Logistic"]["Printer"] = "없는 프린터"
st.write_user_config(data, paths["user_config"])
win.reload()
root.update()
check("이 PC 에 없는 프린터면 알리고 목록에 넣어 둔다", "이 PC 에 없는 프린터" in win.hints["printer"][0].cget("text")
      and "없는 프린터" in list(win.entries["printer"].cget("values")))

print("=== 6. 옛 에이전트 ===")
win.procs = lambda: [(9, "python.exe", r"D:\old\python\python.exe", "python agent.py")]
check("옛 에이전트가 돌면 닫으라고 하고, 그만두면 저장하지 않는다", win.check_old_agents() is False and dlg.said[-1][0] == "retry")

root.destroy()
if len(sys.argv) > 1:
    shutil.rmtree(TMP, ignore_errors=True)
print()
print(f"실패: {'없음' if not fails else fails}")
sys.exit(1 if fails else 0)
```

- [ ] **Step 2: 실패 확인**

Run: `.venv\Scripts\python.exe tests\check_settings_ui.py C:\Users\202512~1\AppData\Local\Temp\claude\d--AX-RPA\7867a5f6-6024-4100-8af7-b0f18f099fe7\scratchpad\settings.png`
Expected: `AttributeError: module 'rpa_settings' has no attribute 'dpi_aware'`

- [ ] **Step 3: 창과 모드 구현 (rpa_settings.py 끝에)**

```python
# ---------------------------------------------------------------------------
# 창 (tkinter). 칸은 한 줄에 '이름 | 입력 | 안내' - 세로가 짧아야 768 높이 노트북에 들어간다
# ---------------------------------------------------------------------------
ROWS = (
    ("대시보드 연결", (
        ("cid", "업체코드", "영어 소문자·숫자·밑줄 (예: net)", "text"),
        ("pc_id", "PC코드", "이 PC 의 코드 (예: test)", "text"),
        ("agent_pw", "기계 계정 비밀번호", "", "password"),
    )),
    ("ERPia 로그인", (
        ("admin_code", "관리자코드", "ERPia 로그인 화면의 관리자코드", "text"),
        ("erp_id", "아이디", "", "text"),
        ("erp_pw", "비밀번호", "", "password"),
        ("erpia_path", "ERPia 위치", "비우면 설치된 곳을 찾아 씁니다", "path"),
    )),
    ("메일 - 첨부파일을 받을 때만 (프리페어)", (
        ("mail_id", "아이디", "", "text"),
        ("mail_pw", "비밀번호", "", "password"),
    )),
    ("프린터 - 운송장을 출력할 때만", (
        ("printer", "프린터", "이 PC 의 프린터에서 고릅니다", "printer"),
    )),
)
PW_HINTS = {"none": "처음이라 꼭 넣습니다", "ok": "저장됨 - 바꿀 때만 넣습니다", "bad": "저장된 값이 안 풀립니다 - 다시 넣으세요"}
INTRO = ("관리자가 알려 준 업체코드·PC코드·기계 계정 비밀번호와 이 PC 의 ERPia 로그인을 넣고 [저장] 을 누르세요.\n"
         "저장할 때 기계 계정으로 실제 로그인해 보고, 윈도우 로그인 때 에이전트가 창 없이 켜지게 합니다.")
GRAY, RED, GREEN, AMBER = "#6b7280", "#dc2626", "#15803d", "#b45309"


def dpi_aware():
    """고해상도 화면에서 창이 흐릿하지 않게 한다 (Tk 를 만들기 전에)."""
    try:
        ctypes.WinDLL("shcore").SetProcessDpiAwareness(1)
    except Exception:
        pass


class Dialogs:
    """알림·고르기 창. 시험은 같은 이름의 가짜로 바꾼다."""

    def __init__(self, parent):
        from tkinter import filedialog, messagebox
        self._m, self._f, self._p = messagebox, filedialog, parent

    def info(self, text):
        self._m.showinfo("RPA 설정", text, parent=self._p)

    def error(self, text):
        self._m.showerror("RPA 설정", text, parent=self._p)

    def yesno(self, text):
        return self._m.askyesno("RPA 설정", text, parent=self._p)

    def retry(self, text):
        return self._m.askretrycancel("RPA 설정", text, parent=self._p)

    def folder(self, title):
        return self._f.askdirectory(title=title, mustexist=True, parent=self._p)

    def exe(self, start):
        return self._f.askopenfilename(title=f"ERPia 프로그램({st.ERPIA_EXE_NAME})을 고르세요", initialdir=start,
                                       filetypes=[("ERPia 프로그램", st.ERPIA_EXE_NAME)], parent=self._p)


class SettingsWindow:
    """설정 창 (설계 4절). 시험은 login·run·running·procs·printers·dialogs 를 가짜로 넣는다."""

    def __init__(self, root, paths, after_install=False, login=agent_login, run=run_quiet, running=None,
                 procs=list_processes, printers=None, dialogs=None):
        import tkinter as tk
        from tkinter import font, ttk
        self.root, self.paths, self.after_install = root, paths, after_install
        self.login, self.run, self.running, self.procs = login, run, running or agent_running, procs
        self.dialogs = dialogs or Dialogs(root)
        self.saved, self.imported_from, self.busy_now, self._result = False, None, False, None
        self.printers = list_printers() if printers is None else list(printers)
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkCaptionFont"):
            font.nametofont(name).configure(family="Malgun Gothic", size=10)
        root.title("AFTER MARKET RPA 설정")
        root.resizable(False, False)
        self.vars = {k: tk.StringVar(master=root) for k in FORM_KEYS}
        self.status, self.msg = tk.StringVar(master=root), tk.StringVar(master=root)
        self.entries, self.hints = {}, {}
        frame = ttk.Frame(root, padding=14)
        frame.grid(sticky="nsew")
        top = ttk.Frame(frame)
        top.grid(row=0, column=0, sticky="ew")
        ttk.Label(top, textvariable=self.status).pack(side="left")
        self.import_btn = ttk.Button(top, text="기존 폴더에서 가져오기", command=self.on_import)
        self.import_btn.pack(side="right")
        ttk.Label(frame, text=INTRO, foreground=GRAY, justify="left").grid(row=1, column=0, sticky="w", pady=(6, 2))
        for n, (title, fields) in enumerate(ROWS):
            box = ttk.LabelFrame(frame, text=title, padding=(10, 2, 10, 4))
            box.grid(row=2 + n, column=0, sticky="ew", pady=3)
            for i, (key, label, hint, kind) in enumerate(fields):
                ttk.Label(box, text=label, width=15).grid(row=i, column=0, sticky="w", pady=2)
                if kind == "printer":
                    w = ttk.Combobox(box, textvariable=self.vars[key], width=31, state="readonly")
                else:
                    w = ttk.Entry(box, textvariable=self.vars[key], width=33, show="•" if kind == "password" else "")
                w.grid(row=i, column=1, sticky="w", pady=2)
                self.entries[key] = w
                col = 2
                if kind == "path":
                    ttk.Button(box, text="찾기", width=5, command=self.on_browse).grid(row=i, column=2, padx=(4, 0))
                    col = 3
                h = ttk.Label(box, text=hint, foreground=GRAY)
                h.grid(row=i, column=col, columnspan=4 - col, sticky="w", padx=(8, 0))
                self.hints[key] = (h, hint)
        bottom = ttk.Frame(frame)
        bottom.grid(row=2 + len(ROWS), column=0, sticky="ew", pady=(8, 0))
        self.close_btn = ttk.Button(bottom, text="닫기", command=self.on_close)
        self.close_btn.pack(side="right")
        self.save_btn = ttk.Button(bottom, text="저장", command=self.on_save)
        self.save_btn.pack(side="right", padx=(0, 6))
        self.msg_label = tk.Label(bottom, textvariable=self.msg, fg=RED, wraplength=560, justify="left", anchor="w")
        self.msg_label.pack(side="left", fill="x", expand=True)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.reload()

    # --- 채우기 -----------------------------------------------------------
    def reload(self):
        """파일에서 칸을 다시 채운다 (처음, 가져오기·저장 뒤). 비밀번호 칸은 비운다."""
        form, self.state = load_state(self.paths)
        for k in FORM_KEYS:
            self.vars[k].set(form[k])
        for label, hint in self.hints.values():
            label.configure(text=hint, foreground=GRAY)
        for key in PASSWORD_KEYS:
            self.hints[key][0].configure(text=PW_HINTS[self.state[key]],
                                         foreground=AMBER if self.state[key] == "bad" else GRAY)
        mail_on = "normal" if self.state["mail_site"] else "disabled"
        for key in ("mail_id", "mail_pw"):
            self.entries[key].configure(state=mail_on)
        if not self.state["mail_site"]:
            self.hints["mail_pw"][0].configure(text="설정에 메일 사이트가 없습니다")
        values = [""] + self.printers
        if form["printer"] and form["printer"] not in self.printers:
            values.append(form["printer"])
            self.hints["printer"][0].configure(text="이 PC 에 없는 프린터입니다 - 다시 고르세요", foreground=AMBER)
        self.entries["printer"].configure(values=values)
        version = st.check_install(self.paths["program_dir"]).get("version") or "없음"
        self.status.set(f"버전 {version}   ·   에이전트: {'돌고 있음' if self.running() else '꺼져 있음'}")

    def say(self, text, color=RED):
        self.msg_label.configure(fg=color)
        self.msg.set(text)

    def busy(self, on):
        self.busy_now = on
        for b in (self.save_btn, self.close_btn, self.import_btn):
            b.state(["disabled"] if on else ["!disabled"])
        if on:
            self.say("확인하는 중입니다… (기계 계정 로그인·자동 시작 등록)", GRAY)

    def form(self):
        out = {k: self.vars[k].get() for k in FORM_KEYS}
        return {k: (v if k in PASSWORD_KEYS else v.strip()) for k, v in out.items()}

    # --- 옛 에이전트 ------------------------------------------------------
    def startup(self):
        """창이 뜬 직후: 옛 에이전트가 돌면 닫게 하고, 그만두면 창을 닫는다."""
        if not self.check_old_agents():
            self.root.destroy()

    def check_old_agents(self):
        """옛 에이전트가 돌면 닫으라고 한다. 다 닫혔으면 True, 사용자가 그만두면 False."""
        while True:
            try:
                olds = old_agents(self.procs(), self.paths["agent_py"])
            except Exception:
                return True                        # 프로세스를 못 읽으면 막지 않는다
            if not olds:
                return True
            lines = "\n".join(f"    {exe or '?'}" for _, exe, _ in olds[:5])
            if not self.dialogs.retry("옛 에이전트가 켜져 있습니다. 그 창(ERPia RPA 클라우드 에이전트)을 닫은 뒤 "
                                      f"[다시 시도] 를 누르세요.\n\n{lines}\n\n"
                                      "같이 켜 두면 에이전트 둘이 같은 PC 로 돌아 자동 실행이 두 번 될 수 있습니다."):
                return False

    # --- 단추 -------------------------------------------------------------
    def on_browse(self):
        cur = self.vars["erpia_path"].get()
        start = os.path.dirname(cur) if cur else (os.environ.get("ProgramFiles(x86)") or "C:\\")
        path = self.dialogs.exe(start)
        if not path:
            return
        found = st._erpia_file(path)
        if found:
            self.vars["erpia_path"].set(found.replace("\\", "/"))
            self.say("")
        else:
            self.say(f"{st.ERPIA_EXE_NAME} 가 아닙니다. ERPia 설치 폴더의 {st.ERPIA_EXE_NAME} 를 고르세요")

    def on_save(self):
        if self.busy_now or not self.check_old_agents():
            return
        form = self.form()
        self.busy(True)
        self._result = None
        threading.Thread(target=self._save_worker, args=(form,), daemon=True).start()
        self.root.after(100, self._poll)

    def _save_worker(self, form):
        """저장은 로그인(인터넷)·작업 등록이 있어 따로 돌린다 - 창이 굳지 않게. 창은 _poll 이 만진다."""
        try:
            self._result = ("ok", save(form, self.paths, login=self.login, run=self.run, running=self.running))
        except (ValueError, RuntimeError) as e:
            self._result = ("error", str(e))
        except Exception as e:
            self._result = ("error", f"저장하지 못했습니다 ({type(e).__name__}: {e})")

    def _poll(self):
        if self._result is None:
            self.root.after(100, self._poll)
            return
        kind, value = self._result
        self.busy(False)
        if kind == "error":
            self.say(value)
            return
        self.saved = True
        self.reload()
        self.say(" ".join(value), GREEN)
        self.after_saved()

    def after_saved(self):
        if self.imported_from:
            folder, self.imported_from = self.imported_from, None
            if self.dialogs.yesno(f"옛 에이전트가 다시 켜지지 않게 옛 폴더 이름을 바꿀까요?\n\n{folder}\n→ {folder}_옮김\n\n"
                                  "파일은 그대로 남습니다. 옛 바로 가기로 옛 에이전트를 켜면 에이전트 둘이 같이 돌아 "
                                  "자동 실행이 두 번 될 수 있습니다."):
                try:
                    self.dialogs.info(f"이름을 바꿨습니다: {retire_old_folder(folder)}")
                except OSError as e:
                    self.dialogs.error(f"이름을 바꾸지 못했습니다 ({e.strerror or e}). 옛 에이전트 창이 열려 있지 않은지 "
                                       "보고 직접 바꾸거나 지우세요")
        if self.after_install:
            self.dialogs.info("설정을 마쳤습니다. 에이전트는 윈도우에 로그인할 때마다 창 없이 켜집니다.\n"
                              "설정을 바꿀 때는 시작 메뉴의 'RPA 설정' 을 여세요.")
            self.root.destroy()

    def on_import(self):
        folder = self.dialogs.folder("옛 배포 폴더(Run_All.bat 이 있는 폴더)를 고르세요")
        if not folder:
            return
        folder = os.path.normpath(folder)
        try:
            try:
                names = import_old(folder, self.paths["config_dir"])
            except FileExistsError as e:
                if not self.dialogs.yesno(f"지금 설정({e})을 옛 폴더의 것으로 바꿀까요?"):
                    return
                names = import_old(folder, self.paths["config_dir"], overwrite=True)
        except FileNotFoundError:
            self.say("그 폴더에서 설정 파일(RPA_UserConfig.json, firebase\\agent\\agent_config.json)을 찾지 못했습니다. "
                     "옛 배포 폴더(Run_All.bat 이 있는 폴더)를 고르세요")
            return
        except OSError as e:
            self.say(f"가져오지 못했습니다 ({e.strerror or e})")
            return
        self.imported_from = folder
        self.reload()
        bad = [label for key, label in (("agent_pw", "기계 계정"), ("erp_pw", "ERPia"), ("mail_pw", "메일"))
               if self.state[key] == "bad"]
        self.say(f"가져왔습니다 ({', '.join(names)}). "
                 + (f"다른 PC·계정에서 잠근 비밀번호라 다시 넣어야 합니다: {', '.join(bad)}. " if bad else "")
                 + "확인한 뒤 [저장] 을 누르세요.", GREEN)

    def on_close(self):
        if self.busy_now:
            return                                  # 저장하는 중
        if not self.saved and not configured(self.paths):
            if not self.dialogs.yesno("설정을 마치지 않으면 에이전트가 켜지지 않습니다.\n"
                                      "시작 메뉴의 'RPA 설정' 에서 이어서 할 수 있습니다. 닫을까요?"):
                return
        self.root.destroy()


def run_window(paths, after_install=False):
    """창을 띄우고 닫힐 때까지 돈다. 창이 뜨면 옛 에이전트부터 본다."""
    import tkinter as tk
    dpi_aware()
    root = tk.Tk()
    win = SettingsWindow(root, paths, after_install=after_install)
    root.after(200, win.startup)
    root.mainloop()
    return 0


def show_error_box(text):
    import tkinter as tk
    from tkinter import messagebox
    dpi_aware()
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror("RPA 설정", text, parent=root)
    root.destroy()


def main(argv=None):
    """모드: (없음) 창 / --after-install 설치 마지막 (판 올림이면 창 없이) / --no-window 창을 절대 안 띄움 /
    --stop·--remove-task 설치 파일이 부르는 멈추기 (0·5·6)."""
    args = list(sys.argv[1:] if argv is None else argv)
    if "--stop" in args:
        return stop_agent()
    if "--remove-task" in args:
        code = stop_agent()
        delete_task()
        return code
    after, quiet = "--after-install" in args, "--no-window" in args
    if not is_admin():
        if not quiet:
            relaunch_as_admin(args)
        return 0
    paths = default_paths()
    problem = start_problem()
    if problem:
        if not quiet:
            show_error_box(problem)
        return 1
    if after and configured(paths):
        try:
            finish_upgrade(paths)
        except RuntimeError as e:
            if not quiet:
                show_error_box(str(e))
            return 1
        return 0
    if quiet:
        return 0
    return run_window(paths, after_install=after)


if __name__ == "__main__":
    sys.exit(main())
```

그리고 tests/test_settings.py 14절에 한 줄 더:
```python
check("관리자가 아니면 --after-install --no-window 는 아무것도 안 하고 0",
      not rs.is_admin() and rs.main(["--after-install", "--no-window"]) == 0)
```

- [ ] **Step 4: 통과 확인과 화면 보기**

Run: `.venv\Scripts\python.exe tests\check_settings_ui.py C:\Users\202512~1\AppData\Local\Temp\claude\d--AX-RPA\7867a5f6-6024-4100-8af7-b0f18f099fe7\scratchpad\settings.png`
Expected: `실패: 없음`. 사진을 Read 로 열어 본다: 글자가 잘리거나 겹치지 않는지, 한 화면(세로 700px 안, 125% 배율이면 560px 안쪽)에 들어오는지. 넘치면 INTRO 를 한 줄로 줄이거나 `pady` 를 줄이고 다시 찍는다.
Run: `.venv\Scripts\python.exe tests\test_settings.py` → `실패: 없음`

- [ ] **Step 5: 그래프 갱신** - `graphify update .`

---

### Task 5: 빌드 - 내장 파이썬 tkinter, 설치 파일 스크립트, build_release

설계 3절·6절.

**Files:**
- Modify (저장소 밖, 한 번): `D:\AX\runtime\python\Lib\tkinter`
- Create: `release/installer.iss` (BOM 있는 UTF-8)
- Modify: `tools/build_release.py`
- Modify: `tests/test_build_release.py` (6절), `tests/test_encoding.py` (4절)

**Interfaces:**
- Consumes: `rpa_settings.TEMPLATE_NAME`, `EXIT_RPA_RUNNING`, `EXIT_STOP_FAILED` (Task 3), `st.PRODUCT_DIRS`
- Produces: `build_release.ISS_PATH`, `ISCC_DIRS`, `find_iscc(dirs=ISCC_DIRS)`, `num_version(v)`, `setup_name(v)`, `iscc_command(iscc, out_dir, version, out_root=OUT_ROOT, iss=ISS_PATH)`, `build_setup(out_dir, version, out_root=OUT_ROOT) -> str`, `runtime_has_tkinter(root) -> bool`, `reuse_exes(src_dir, work_dir) -> str`, 새 인수 `--exes-from`, `--no-setup`

- [ ] **Step 1: 내장 파이썬에 tkinter 넣기 (한 번)**

같은 3.14.7 의 `Lib\tkinter` 를 `__pycache__` 없이 복사하고 창을 띄워 본다:
```powershell
D:\AX\RPA\.venv\Scripts\python.exe -c "import shutil; shutil.copytree(r'C:\Users\20251216-003\AppData\Local\Python\pythoncore-3.14-64\Lib\tkinter', r'D:\AX\runtime\python\Lib\tkinter', ignore=shutil.ignore_patterns('__pycache__'))"
D:\AX\runtime\python\python.exe -c "import platform, tkinter; r = tkinter.Tk(); print(platform.python_version(), tkinter.TkVersion); r.destroy()"
```
Expected: `3.14.7 9.0`

- [ ] **Step 2: 실패하는 시험 (test_build_release.py 6절, test_encoding.py 4절)**

test_build_release.py 의 마지막 `finish()` 바로 앞:
```python
print("=== 6. 설치 파일 (2부) ===")
import subprocess  # noqa: E402
import rpa_settings as rs  # noqa: E402

check("판 목록에 설정 창·감독", {"rpa_settings.py", "firebase/agent/background.py"} <= {rel for rel, _ in br.PROGRAM_FILES})
check("파일 속성용 판 번호", br.num_version("2026.09.29-5") == "2026.9.29.5" and br.num_version("2026.10.01-12") == "2026.10.1.12")
check("설치 파일 이름", br.setup_name("2026.09.29-5") == "AFTER_MARKET_RPA_Setup_2026.09.29-5.exe")
with tempfile.TemporaryDirectory() as d:
    a, b = os.path.join(d, "a"), os.path.join(d, "b")
    os.makedirs(a)
    os.makedirs(b)
    open(os.path.join(b, "ISCC.exe"), "wb").close()
    check("ISCC 찾기: 있는 첫 자리, 없으면 None", br.find_iscc([a, b]) == os.path.join(b, "ISCC.exe") and br.find_iscc([a]) is None)
cmd = br.iscc_command("ISCC.exe", r"D:\AX\배포_2026.09.29-5", "2026.09.29-5", out_root=r"D:\AX")
check("ISCC 명령", cmd[0] == "ISCC.exe" and "/DAppVersion=2026.09.29-5" in cmd and "/DNumVersion=2026.9.29.5" in cmd
      and r"/DSourceDir=D:\AX\배포_2026.09.29-5" in cmd and r"/OD:\AX" in cmd
      and "/FAFTER_MARKET_RPA_Setup_2026.09.29-5" in cmd and cmd[-1] == br.ISS_PATH, cmd)
iss = Path(br.ISS_PATH).read_bytes().decode("utf-8-sig")
root_rel = "\\".join(st.PRODUCT_DIRS)
check("설치 자리 = 1부 자리 규칙", f"DefaultDirName={{commonpf64}}\\{root_rel}" in iss)
check("새 자리 config·data", all(f"{{commonappdata}}\\{root_rel}\\{d}" in iss for d in ("config", "data")))
check("빈 틀 이름 바꾸기 = 설정 창이 찾는 이름", f'DestName: "{rs.TEMPLATE_NAME}"' in iss)
check("안내 문서·빈 틀은 통째 복사에서 뺀다", all(f"\\{n}" in iss for n in ("RPA_UserConfig.json", "배포안내.txt", "클라우드_안내.txt")))
check("권한은 SID 로 (관리자·SYSTEM), 상속 끊기", "*S-1-5-32-544:(OI)(CI)F" in iss and "*S-1-5-18:(OI)(CI)F" in iss
      and "/inheritance:r" in iss)
check("설정 창 모드 이름", all(m in iss for m in ("--after-install", "--no-window", "--stop", "--remove-task")))
check("종료 코드 = 설정 창과 같다", f"EXIT_RPA_RUNNING = {rs.EXIT_RPA_RUNNING};" in iss
      and f"EXIT_STOP_FAILED = {rs.EXIT_STOP_FAILED};" in iss)
check("내장 파이썬에 tkinter (D:\\AX\\runtime)", br.runtime_has_tkinter(br.RUNTIME_ROOT))
with tempfile.TemporaryDirectory() as d:
    src = os.path.join(d, "src")
    for rel in ("ERPia_RPA.exe", "Prepare_RPA.exe"):
        write(os.path.join(src, rel), rel.encode())
    write(os.path.join(src, st.MANIFEST_NAME), json.dumps({"version": "2026.09.29-4", "builder": "nuitka 4.2.2 · python 3.14.7"}).encode())
    label = br.reuse_exes(src, os.path.join(d, "work"))
    check("--exes-from: 두 exe 를 가져오고 builder 칸에 적는다", label == "nuitka 4.2.2 · python 3.14.7 (판 2026.09.29-4 에서 가져옴)"
          and all(os.path.isfile(os.path.join(d, "work", n)) for n in br.EXES), label)
iscc = br.find_iscc()
check("이 PC 에 Inno Setup (ISCC.exe)", iscc is not None)
if iscc:
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "배포_시험")                       # 한글 판 폴더 이름
        for rel in ("RPA_UserConfig.json", "배포안내.txt", "클라우드_안내.txt", "rpa_settings.py", "manifest.json",
                    "python/python.exe", "python/pythonw.exe", "firebase/agent/background.py"):
            write(os.path.join(src, *rel.split("/")), b"x")
        r = subprocess.run(br.iscc_command(iscc, src, "2026.09.29-99", out_root=d), capture_output=True, timeout=300)
        out = os.path.join(d, br.setup_name("2026.09.29-99"))
        check("installer.iss 가 컴파일된다 (가짜 판 폴더)", r.returncode == 0 and os.path.isfile(out),
              (r.stdout + r.stderr)[-600:].decode("utf-8", "replace"))
```
(`write(path, data)` 는 이 파일 위쪽에 이미 있는 도우미다 - 폴더를 만들고 bytes 를 쓴다. 쓰기 전에 그 정의를 확인한다.)

test_encoding.py 의 끝 `print()` 바로 앞:
```python
print("=== 4. 설치 파일 스크립트는 BOM 있는 UTF-8 ===")
for s in (ROOT / "release" / "installer.iss", ROOT / "tools" / "sandbox_inner.ps1"):
    if s.exists():
        b = s.read_bytes()
        check(f"{s.name} 는 BOM 있는 UTF-8 (Inno Setup·PowerShell 5.1 이 한글을 그렇게 읽는다)",
              b.startswith(b"\xef\xbb\xbf") and decodes(b[3:], "utf-8"))
```

- [ ] **Step 3: 실패 확인**

Run: `.venv\Scripts\python.exe tests\test_build_release.py`
Expected: `AttributeError: module 'build_release' has no attribute 'num_version'` 로 멈춤 (1~5절은 통과)

- [ ] **Step 4: 설치 파일 스크립트 (release/installer.iss)**

Write 로 쓰고 Step 5 에서 BOM 을 붙인다:
```iss
; AFTER MARKET RPA 설치 파일 (배포판 구조 2부 3절 - docs/superpowers/specs/2026-09-29-installer-design.md)
; tools/build_release.py 가 판 폴더에 대고 컴파일한다:
;   ISCC.exe /DAppVersion=2026.09.29-5 /DNumVersion=2026.9.29.5 /DSourceDir=D:\AX\배포_2026.09.29-5 /OD:\AX /F... installer.iss
; 설치·제거·바로 가기·폴더 권한만 여기서 한다. 입력·로그인 확인·작업 등록·에이전트 켜고 끄기는 rpa_settings.py.
; 이 파일은 BOM 있는 UTF-8 로 저장한다 (Inno Setup 이 한글을 그렇게 읽는다. tests/test_encoding.py 가 본다).

#ifndef AppVersion
  #error AppVersion 이 없습니다 - tools/build_release.py 로 컴파일하세요
#endif
#ifndef NumVersion
  #error NumVersion 이 없습니다 - tools/build_release.py 로 컴파일하세요
#endif
#ifndef SourceDir
  #error SourceDir 이 없습니다 - tools/build_release.py 로 컴파일하세요
#endif

[Setup]
AppId={{C3F7A2B4-5E81-4D2A-9B6C-7A1E0F3D8B52}
AppName=AFTER MARKET RPA
AppVersion={#AppVersion}
AppVerName=AFTER MARKET RPA {#AppVersion}
AppPublisher=AFTER MARKET
VersionInfoVersion={#NumVersion}
DefaultDirName={commonpf64}\AFTER MARKET\RPA
DisableDirPage=yes
DefaultGroupName=AFTER MARKET RPA
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupLogging=yes
CloseApplications=no
RestartApplications=no
UninstallDisplayName=AFTER MARKET RPA
UninstallDisplayIcon={app}\python\pythonw.exe
OutputDir=.
OutputBaseFilename=AFTER_MARKET_RPA_Setup_{#AppVersion}

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Dirs]
; 이 config 폴더가 생기면 그 PC 는 새 구조다 (1부 3절). 제거할 때 자동으로 지우지 않는다 (끝에 묻는다)
Name: "{commonappdata}\AFTER MARKET\RPA\config"; Flags: uninsneveruninstall
Name: "{commonappdata}\AFTER MARKET\RPA\data"; Flags: uninsneveruninstall
Name: "{group}"

[Files]
; 판 폴더 전부. 빈 틀은 template 이름으로 (프로그램 폴더에 진짜 설정처럼 보이는 파일을 두지 않는다), 안내 문서는 넣지 않는다
Source: "{#SourceDir}\*"; DestDir: "{app}"; Excludes: "\RPA_UserConfig.json,\배포안내.txt,\클라우드_안내.txt"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#SourceDir}\RPA_UserConfig.json"; DestDir: "{app}"; DestName: "RPA_UserConfig.template.json"; Flags: ignoreversion

[Icons]
Name: "{group}\RPA 설정"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\rpa_settings.py"""; WorkingDir: "{app}"; Comment: "RPA 설정 창 (관리자 권한 요청이 뜹니다)"

[INI]
Filename: "{group}\RPA 대시보드.url"; Section: "InternetShortcut"; Key: "URL"; String: "https://rpa-test-f02e0.web.app"

[Run]
; 상속을 끊고 Administrators(S-1-5-32-544)·SYSTEM(S-1-5-18) 만 남긴다. 한글 윈도우의 그룹 이름 차이에 흔들리지 않게 SID 로
Filename: "{sys}\icacls.exe"; Parameters: """{commonappdata}\AFTER MARKET\RPA"" /inheritance:r /grant:r *S-1-5-32-544:(OI)(CI)F *S-1-5-18:(OI)(CI)F"; Flags: runhidden waituntilterminated; StatusMsg: "설정 폴더를 관리자만 열 수 있게 막는 중..."
; 처음 설치면 설정 창, 판 올림이면 창 없이 작업 등록·에이전트 켜기. 조용한 설치에서는 창을 절대 띄우지 않는다 (기다리며 멈춘다)
Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\rpa_settings.py"" --after-install"; WorkingDir: "{app}"; Flags: waituntilterminated; StatusMsg: "설정 창에서 설정을 마치고 [저장] 을 누르세요..."; Check: not WizardSilent
Filename: "{app}\python\python.exe"; Parameters: """{app}\rpa_settings.py"" --after-install --no-window"; WorkingDir: "{app}"; Flags: runhidden waituntilterminated; Check: WizardSilent

[UninstallDelete]
Type: files; Name: "{group}\RPA 대시보드.url"
; 파이썬이 만든 __pycache__ 까지 남지 않게 프로그램 폴더를 통째로 (자리가 고정이라 안전하다)
Type: filesandordirs; Name: "{app}"
Type: dirifempty; Name: "{commonpf64}\AFTER MARKET"

[Code]
const
  EXIT_RPA_RUNNING = 5;
  EXIT_STOP_FAILED = 6;

// 설치돼 있는 rpa_settings.py 를 창 없이 돌린다. 처음 설치라 파일이 없으면 -1, 못 띄우면 -2
function RunSettings(const Args: String): Integer;
var
  Py, Script: String;
  Code: Integer;
begin
  Result := -1;
  Py := ExpandConstant('{app}\python\python.exe');
  Script := ExpandConstant('{app}\rpa_settings.py');
  if FileExists(Py) and FileExists(Script) then
  begin
    if Exec(Py, AddQuotes(Script) + ' ' + Args, ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, Code) then
      Result := Code
    else
      Result := -2;
  end;
  Log(Format('rpa_settings %s -> %d', [Args, Result]));
end;

// 판을 올릴 때: 파일을 덮기 전에 에이전트를 멈춘다. RPA 가 돌면 설치를 멈춘다 (도는 exe 는 덮어쓸 수 없다)
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Code: Integer;
begin
  Result := '';
  Code := RunSettings('--stop');
  if Code = EXIT_RPA_RUNNING then
    Result := 'RPA 가 돌고 있습니다. RPA 가 끝난 뒤 다시 설치하세요.'
  else if Code = EXIT_STOP_FAILED then
  begin
    if SuppressibleMsgBox('에이전트를 멈추지 못했습니다. 에이전트 창(에이전트_시작.bat)이 열려 있으면 닫고 [예] 를 누르세요.' + #13#10 +
                          '[아니요] 를 누르면 설치를 그만둡니다.', mbConfirmation, MB_YESNO, IDYES) = IDNO then
      Result := '에이전트를 멈추지 못해 설치를 그만뒀습니다.';
  end;
end;

// 지우기 전: RPA 가 돌면 그만둔다
function InitializeUninstall(): Boolean;
begin
  Result := True;
  if RunSettings('--stop') = EXIT_RPA_RUNNING then
  begin
    SuppressibleMsgBox('RPA 가 돌고 있습니다. RPA 가 끝난 뒤 다시 지우세요.', mbError, MB_OK, IDOK);
    Result := False;
  end;
end;

// 파일을 지우기 직전 작업을 지우고, 끝에 설정·기록을 지울지 묻는다 (기본 아니요 - 조용한 제거면 남긴다)
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Data: String;
begin
  if CurUninstallStep = usUninstall then
    RunSettings('--remove-task');
  if CurUninstallStep = usPostUninstall then
  begin
    Data := ExpandConstant('{commonappdata}\AFTER MARKET\RPA');
    if DirExists(Data) and (SuppressibleMsgBox('설정과 기록(' + Data + ')도 지울까요?' + #13#10 +
         '다시 설치해서 쓰려면 [아니요] 를 누르세요. 설정에는 잠근 비밀번호가 들어 있습니다.',
         mbConfirmation, MB_YESNO or MB_DEFBUTTON2, IDNO) = IDYES) then
    begin
      DelTree(Data, True, True, True);
      RemoveDir(ExpandConstant('{commonappdata}\AFTER MARKET'));
    end;
  end;
end;
```

- [ ] **Step 5: BOM 붙이기**

```powershell
D:\AX\RPA\.venv\Scripts\python.exe -c "p = r'D:\AX\RPA\release\installer.iss'; s = open(p, encoding='utf-8-sig').read(); open(p, 'w', encoding='utf-8-sig', newline='\r\n').write(s)"
```
(읽기를 끝낸 뒤에 쓰기로 연다 - 한 줄 안에서도 `s = …read()` 가 먼저 끝난다)

- [ ] **Step 6: build_release.py 고치기**

맨 위 docstring 을 바꾼다:
```python
r"""배포판을 만든다 (배포판 구조 1부 8절·2부 6절 - docs/superpowers/specs/2026-09-29-release-layout-design.md,
2026-09-29-installer-design.md).

    .venv\Scripts\python.exe tools\build_release.py [--builder nuitka|pyinstaller] [--exes-from <판 폴더>] [--no-setup] [--to-dist]

1. 두 exe 를 만든다 (build\release 에). --exes-from 이면 그 판 폴더의 exe 를 가져온다 (exe 소스가 안 바뀐 판)
2. 정해 둔 파일만 D:\AX\배포_<판 번호>\ 에 모은다
3. 판 목록(manifest.json)을 쓴다
4. D:\AX\배포_<판 번호>.zip 으로 압축한다 (맨 위 폴더도 같은 이름 - 손으로 넘기는 대비책)
5. 스스로 확인한다: 압축 목록·지문·들어가면 안 되는 파일·빈 배포 틀, 풀어서 두 exe --check, 내장 파이썬 tkinter
6. 설치 파일 D:\AX\AFTER_MARKET_RPA_Setup_<판 번호>.exe 를 만든다 (Inno Setup, release/installer.iss). --no-setup 이면 건너뛴다
비밀번호·쿠키·서비스 계정 키는 어떤 경우에도 배포판에 들어가지 않는다 (5번이 막는다. 설치 파일은 5번을 통과한 판 폴더로만 만든다).
"""
```
`PROGRAM_FILES` 에 두 줄:
```python
    ("rpa_settings.py", "rpa_settings.py"),                                   # 설정 창 (2부)
    ("firebase/agent/background.py", "firebase/agent/background.py"),         # 에이전트 감독 (2부)
```
`NUITKA_EXTRA` 줄 뒤에:
```python
ISS_PATH = os.path.join(REPO, "release", "installer.iss")
# Inno Setup 6 의 ISCC.exe 를 찾는 자리 (이 PC 는 winget 사용자 설치 → LOCALAPPDATA)
ISCC_DIRS = (os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Inno Setup 6"),
             os.path.join(os.environ.get("ProgramFiles(x86)") or r"C:\Program Files (x86)", "Inno Setup 6"),
             os.path.join(os.environ.get("ProgramFiles") or r"C:\Program Files", "Inno Setup 6"))
```
`build_exes` 뒤에:
```python
def reuse_exes(src_dir, work_dir):
    """두 exe 를 새로 만들지 않고 src_dir(판 폴더)에서 work_dir 로 복사한다. 판 목록 builder 칸 글자를 돌려준다."""
    os.makedirs(work_dir, exist_ok=True)
    for exe in EXES:
        shutil.copy2(os.path.join(src_dir, exe), os.path.join(work_dir, exe))
    try:
        with open(os.path.join(src_dir, st.MANIFEST_NAME), encoding="utf-8") as f:
            man = json.load(f)
        return f"{man.get('builder') or '?'} (판 {man.get('version') or '?'} 에서 가져옴)"
    except (OSError, ValueError):
        return f"? ({os.path.basename(os.path.normpath(src_dir))} 에서 가져옴)"


def runtime_has_tkinter(root):
    """root\\python 의 내장 파이썬이 tkinter 를 불러오나 (설정 창이 쓴다)."""
    try:
        r = subprocess.run([os.path.join(root, "python", "python.exe"), "-c", "import tkinter"],
                           capture_output=True, timeout=60)
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def find_iscc(dirs=ISCC_DIRS):
    """ISCC.exe 경로, 없으면 None."""
    for d in dirs:
        path = os.path.join(d, "ISCC.exe")
        if os.path.isfile(path):
            return path
    return None


def num_version(version):
    """파일 속성용 판 번호: 2026.09.29-5 → 2026.9.29.5 (숫자 넷)."""
    day, n = version.split("-")
    return ".".join(str(int(p)) for p in day.split(".") + [n])


def setup_name(version):
    return f"AFTER_MARKET_RPA_Setup_{version}.exe"


def iscc_command(iscc, out_dir, version, out_root=OUT_ROOT, iss=ISS_PATH):
    return [iscc, "/Qp", f"/DAppVersion={version}", f"/DNumVersion={num_version(version)}", f"/DSourceDir={out_dir}",
            f"/O{out_root}", f"/F{setup_name(version)[:-4]}", iss]


def build_setup(out_dir, version, out_root=OUT_ROOT):
    """판 폴더로 설치 파일을 만든다. 경로를 돌려준다. ISCC 가 없거나 컴파일이 안 되면 RuntimeError."""
    iscc = find_iscc()
    if not iscc:
        raise RuntimeError("Inno Setup(ISCC.exe) 이 없습니다. winget install JRSoftware.InnoSetup --scope user 로 설치하거나 "
                           "--no-setup 으로 건너뛰세요")
    r = subprocess.run(iscc_command(iscc, out_dir, version, out_root), capture_output=True)
    path = os.path.join(out_root, setup_name(version))
    if r.returncode != 0 or not os.path.isfile(path):
        raise RuntimeError(f"설치 파일을 만들지 못했습니다 (ISCC {r.returncode}): "
                           f"{(r.stdout + r.stderr)[-500:].decode('utf-8', 'replace')}")
    return path
```
`main` 에서:
```python
    ap.add_argument("--exes-from", metavar="판폴더", help="두 exe 를 만들지 않고 이 판 폴더에서 가져온다 (exe 소스가 안 바뀐 판)")
    ap.add_argument("--no-setup", action="store_true", help="설치 파일(setup.exe)을 만들지 않는다")
    args = ap.parse_args(argv)
    version = next_version(OUT_ROOT, datetime.date.today())
    work = os.path.join(REPO, "build", "release")
    print(f"판 {version} 을 만듭니다 ({f'exe 는 {args.exes_from} 에서' if args.exes_from else args.builder})")
    builder = reuse_exes(args.exes_from, work) if args.exes_from else build_exes(args.builder, work)
```
검사 줄 뒤:
```python
    problems = verify_zip(zip_path, man, program, [rel for rel, _ in OTHER_FILES]) + smoke_check(zip_path)
    if not runtime_has_tkinter(out_dir):
        problems.append("내장 파이썬에 tkinter 가 없습니다 - 설정 창이 뜨지 않습니다 (2부 6절)")
```
`if args.to_dist:` 앞에:
```python
    if not args.no_setup:
        try:
            setup = build_setup(out_dir, version)
        except RuntimeError as e:
            print("  문제:", e)
            return 1
        print(f"  설치 파일 {setup}  ({os.path.getsize(setup) // 2 ** 20}MB)")
```

- [ ] **Step 7: 통과 확인**

Run: `.venv\Scripts\python.exe tests\test_build_release.py` → `실패: 없음`
Run: `.venv\Scripts\python.exe tests\test_encoding.py` → `실패: 없음`
ISCC 컴파일이 실패하면 출력(마지막 600자)에 줄 번호와 까닭이 나온다 - `.iss` 를 고치고 Step 5(BOM) 를 다시 한다.

- [ ] **Step 8: 그래프 갱신** - `graphify update .`

---

### Task 6: 판 만들기

**Files:** 없음 (빌드 결과는 `D:\AX` 에)

- [ ] **Step 1: 판 만들기 (뒤에서, 30~50분)**

exe 소스(`run_routine.py`·`web_runner.py`·`rpa_status.py`…)는 2부에서 안 바뀌었지만, 배포하는 판은 표준 절차대로 새로 만든다:
```powershell
cd D:\AX\RPA
.venv\Scripts\python.exe tools\build_release.py *> "$env:TEMP\rpa_build5.log"
```
Expected 끝 줄: `  설치 파일 D:\AX\AFTER_MARKET_RPA_Setup_2026.09.29-5.exe  (…MB)` 와 `판 2026.09.29-5  D:\AX\배포_2026.09.29-5.zip  (…MB)`, `문제:` 줄 없음

- [ ] **Step 2: 판 폴더 확인**

```powershell
D:\AX\RPA\.venv\Scripts\python.exe -c "import sys; sys.path.insert(0, r'D:\AX\RPA'); import rpa_status as st; r = st.check_install(r'D:\AX\배포_2026.09.29-5'); print(r['version'], r['state'], r['changed_count'])"
```
Expected: `2026.09.29-5 ok 0`. 판 목록에 `rpa_settings.py`·`firebase/agent/background.py` 가 있는지도 본다.

- [ ] **Step 3: 앞 판 정리** - 사용자가 넘긴 판이 아니면 `-4` 는 샌드박스 시험(Task 7)이 끝난 뒤 지운다 (되돌리기용 `배포_20260928_3` 은 둔다)

---

### Task 7: 윈도우 샌드박스 시험

설계 9절. 이 PC 는 건드리지 않고 깨끗한 윈도우에서 조용한 설치 → 확인 → 가짜 설정으로 에이전트 → 다시 설치 → 설정 창 사진 → 조용한 제거.

**Files:**
- Create: `tools/sandbox_test.py`
- Create: `tools/sandbox_inner.ps1` (BOM 있는 UTF-8)

- [ ] **Step 1: 샌드박스 기능 확인 - 꺼져 있으면 사용자에게 묻는다**

`Test-Path C:\Windows\System32\WindowsSandbox.exe` 가 거짓이면 사용자에게: "관리자 PowerShell 에서 `Enable-WindowsOptionalFeature -Online -FeatureName Containers-DisposableClientVM -All` 을 돌리고 재부팅해 주실 수 있나요? (이 PC 의 에이전트도 재부팅 뒤 다시 켜야 합니다)". 사용자가 안 된다고 하면 Task 7 은 건너뛰고, 노트북을 옮길 때 같은 항목을 사람이 확인하는 목록으로 대신한다 (Task 8 보고에 적는다).

- [ ] **Step 2: 샌드박스 안에서 돌 스크립트 (tools/sandbox_inner.ps1)**

```powershell
# 윈도우 샌드박스 안에서 설치 파일을 시험한다 (tools/sandbox_test.py 가 C:\test 로 넣고 로그온 때 돌린다).
# 결과: C:\test\out\results.txt (통과/실패 줄, 끝에 '실패: N'), 설치 기록, 에이전트 기록, 설정 창 사진. 끝나면 샌드박스를 끈다.
# 이 파일은 BOM 있는 UTF-8 로 저장한다 (PowerShell 5.1 이 BOM 없는 파일을 ANSI 로 읽어 한글이 깨진다).
$ErrorActionPreference = "Continue"
$T = "C:\test"; $O = "$T\out"
New-Item -ItemType Directory -Force $O | Out-Null
$results = New-Object System.Collections.Generic.List[string]
$script:fails = 0
function Check($name, $ok, $detail = "") {
    if ($ok) { $results.Add("통과  $name") } else { $script:fails++; $results.Add("실패  $name  $detail") }
    $results | Set-Content "$O\results.txt" -Encoding UTF8
}
$App = "C:\Program Files\AFTER MARKET\RPA"
$PD = "C:\ProgramData\AFTER MARKET\RPA"
$Py = "$App\python\python.exe"
$SM = "C:\ProgramData\Microsoft\Windows\Start Menu\Programs\AFTER MARKET RPA"
$Task = "AFTER MARKET\RPA Agent"

# 1. 조용한 설치
$p = Start-Process "$T\setup.exe" -ArgumentList "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG=`"$O\setup1.log`"" -Wait -PassThru
Check "조용한 설치 (코드 0)" ($p.ExitCode -eq 0) "코드 $($p.ExitCode)"
Check "프로그램 파일" ((Test-Path "$App\rpa_settings.py") -and (Test-Path "$App\firebase\agent\background.py") -and (Test-Path "$App\python\pythonw.exe") -and (Test-Path "$App\ERPia_RPA.exe") -and (Test-Path "$App\ms-playwright") -and (Test-Path "$App\manifest.json"))
Check "빈 틀은 template 이름으로, 진짜 설정 이름·안내 문서는 없다" ((Test-Path "$App\RPA_UserConfig.template.json") -and -not (Test-Path "$App\RPA_UserConfig.json") -and -not (Test-Path "$App\배포안내.txt"))
$ver = & $Py -c "import sys; sys.path.insert(0, r'$App'); import rpa_status as st; r = st.check_install(r'$App'); print(r['state'], r['version'])"
Check "판 점검 ok" ("$ver" -like "ok *") "$ver"
Check "새 자리 config·data" ((Test-Path "$PD\config") -and (Test-Path "$PD\data"))
$acl = (icacls "$PD\config") -join "`n"
$acl | Set-Content "$O\acl.txt" -Encoding UTF8
Check "config 는 관리자·SYSTEM 만" (($acl -match "Administrators") -and ($acl -match "SYSTEM") -and -not ($acl -match "Users") -and -not ($acl -match "CREATOR OWNER")) $acl
Check "시작 메뉴 바로 가기 둘" ((Test-Path "$SM\RPA 설정.lnk") -and (Test-Path "$SM\RPA 대시보드.url"))
$un = Get-ChildItem "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall" | Where-Object { $_.GetValue("DisplayName") -eq "AFTER MARKET RPA" }
Check "앱 및 기능 목록" ($null -ne $un)
$tk = & $Py -c "import tkinter; r = tkinter.Tk(); r.destroy(); print('tk ok')"
Check "내장 파이썬 tkinter" ("$tk" -eq "tk ok") "$tk"

# 2. 가짜 설정 (로그인 없이 파일만) → --after-install --no-window → 작업 등록·에이전트 켜기
$cfg = @'
import os, sys
app = r"C:\Program Files\AFTER MARKET\RPA"
sys.path.insert(0, app); sys.path.insert(0, os.path.join(app, "firebase", "agent"))
import rpa_status as st, secret, agent
data = st.read_user_config(os.path.join(app, "RPA_UserConfig.template.json"))
data["LogIn"].update(AdminCode="sbx", ID="sbx", PW="sbx-pw")
st.write_user_config(data, st.user_config_path())
secret.write_config(secret.CONFIG_PATH, dict(secret.PUBLIC, email=agent.email_for("sbx", "sbx"), cid="sbx", pc_id="sbx"), "not-the-password")
print("cfg ok")
'@
[IO.File]::WriteAllText("$O\cfg.py", $cfg, (New-Object Text.UTF8Encoding($false)))
$c = & $Py "$O\cfg.py"
Check "가짜 설정을 썼다" ("$c" -eq "cfg ok") "$c"
$p = Start-Process $Py -ArgumentList "`"$App\rpa_settings.py`" --after-install --no-window" -Wait -PassThru -WindowStyle Hidden
Check "--after-install --no-window (코드 0)" ($p.ExitCode -eq 0) "코드 $($p.ExitCode)"
$q = (schtasks /Query /TN $Task /XML) -join "`n"
$q | Set-Content "$O\task.xml" -Encoding UTF8
Check "작업 등록 (가장 높은 권한·배터리·제한 없음·우선순위 5)" (($q -match "<RunLevel>HighestAvailable</RunLevel>") -and ($q -match "<DisallowStartIfOnBatteries>false") -and ($q -match "<StopIfGoingOnBatteries>false") -and ($q -match "<ExecutionTimeLimit>PT0S") -and ($q -match "<Priority>5</Priority>"))

# 3. 감독 → 에이전트: 가짜 비밀번호라 로그인이 거부되고(3) 감독도 같이 끝난다 (틀린 비밀번호로 되풀이하지 않는다)
$log = "$PD\data\에이전트_기록.txt"
$ok3 = $false
for ($i = 0; $i -lt 120; $i++) {
    Start-Sleep 1
    if ((Test-Path $log) -and ((Get-Content $log -Encoding UTF8 -Raw) -match "코드 3")) { $ok3 = $true; break }
}
Copy-Item $log "$O\agent_log1.txt" -ErrorAction SilentlyContinue
Copy-Item "$PD\data\에이전트_오류.txt" "$O\agent_err1.txt" -ErrorAction SilentlyContinue
Check "감독이 에이전트를 띄웠고, 로그인 거부(3)에 같이 끝났다" $ok3
Start-Sleep 2
$left = @(Get-CimInstance Win32_Process -Filter "Name='python.exe' or Name='pythonw.exe'" | Where-Object { $_.CommandLine -match "background\.py|agent\.py" })
Check "감독·에이전트가 남아 있지 않다" ($left.Count -eq 0) (($left | ForEach-Object { $_.CommandLine }) -join " | ")

# 4. 한 번 더 설치 (판 올림 흉내): 먼저 --stop, 끝나면 창 없이 작업 등록·켜기
$p = Start-Process "$T\setup.exe" -ArgumentList "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG=`"$O\setup2.log`"" -Wait -PassThru
Check "다시 설치 (코드 0)" ($p.ExitCode -eq 0) "코드 $($p.ExitCode)"
$l2 = Get-Content "$O\setup2.log" -Raw
Check "파일을 덮기 전에 --stop (0)" ($l2 -match "rpa_settings --stop -> 0")

# 5. 설정 창 사진 (이 샌드박스 계정은 관리자라 바로 뜬다)
$w = Start-Process "$App\python\pythonw.exe" -ArgumentList "`"$App\rpa_settings.py`"" -PassThru
Start-Sleep 10
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
$b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size)
$bmp.Save("$O\settings.png")
$g.Dispose(); $bmp.Dispose()
Check "설정 창이 떴다 (사진 settings.png)" (-not $w.HasExited)
Stop-Process -Id $w.Id -Force -ErrorAction SilentlyContinue

# 6. 조용한 제거: 작업·프로그램·시작 메뉴는 없어지고 설정·기록은 남는다 (조용한 제거의 기본)
Start-Process "$App\unins000.exe" -ArgumentList "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART" -Wait
for ($i = 0; ($i -lt 60) -and (Test-Path $App); $i++) { Start-Sleep 1 }
Check "제거: 프로그램 폴더가 없다" (-not (Test-Path $App))
schtasks /Query /TN $Task *> $null
Check "제거: 작업이 없다" ($LASTEXITCODE -ne 0)
Check "제거: 시작 메뉴가 없다" (-not (Test-Path $SM))
Check "제거: 설정·기록은 남는다" (Test-Path "$PD\config\agent_config.json")

$results.Add("실패: $script:fails")
$results | Set-Content "$O\results.txt" -Encoding UTF8
"done" | Set-Content "$T\done.txt"
shutdown /s /t 5
```

- [ ] **Step 3: 이 PC 쪽 (tools/sandbox_test.py)**

```python
r"""설치 파일을 윈도우 샌드박스에서 시험한다 (설계 9절). 이 PC 에는 설치하지 않는다.

    .venv\Scripts\python.exe tools\sandbox_test.py D:\AX\AFTER_MARKET_RPA_Setup_<판>.exe

윈도우 샌드박스 기능이 켜져 있어야 한다 (관리자 PowerShell: Enable-WindowsOptionalFeature -Online
-FeatureName Containers-DisposableClientVM -All, 재부팅). 샌드박스 안에서 tools\sandbox_inner.ps1 이 조용한 설치 →
확인 → 가짜 설정으로 에이전트 → 다시 설치 → 설정 창 사진 → 조용한 제거를 하고 결과를 적은 뒤 샌드박스를 끈다.
결과는 임시 폴더의 out\results.txt·settings.png·setup*.log·agent_log1.txt. 샌드박스 안의 인터넷을 쓴다
(에이전트가 가짜 기계 계정으로 로그인을 한 번 시도해 거부당한다).
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SANDBOX = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "WindowsSandbox.exe")
WSB = """<Configuration>
  <MappedFolders><MappedFolder><HostFolder>{work}</HostFolder><SandboxFolder>C:\\test</SandboxFolder><ReadOnly>false</ReadOnly></MappedFolder></MappedFolders>
  <LogonCommand><Command>powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\\test\\inner.ps1</Command></LogonCommand>
  <MemoryInMB>4096</MemoryInMB>
</Configuration>
"""


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1 or not os.path.isfile(args[0]):
        print(__doc__)
        return 2
    if not os.path.isfile(SANDBOX):
        print("윈도우 샌드박스가 꺼져 있습니다 (위 설명의 명령으로 켜고 재부팅)")
        return 2
    work = tempfile.mkdtemp(prefix="rpa_sbx_")          # 영문 경로 (샌드박스에 그대로 붙는다)
    shutil.copy2(args[0], os.path.join(work, "setup.exe"))
    shutil.copy2(os.path.join(HERE, "sandbox_inner.ps1"), os.path.join(work, "inner.ps1"))
    wsb = os.path.join(work, "test.wsb")
    with open(wsb, "w", encoding="utf-8") as f:
        f.write(WSB.format(work=work))
    print(f"샌드박스를 띄웁니다. 결과 폴더: {work}\\out (창을 건드리지 마세요, 끝나면 저절로 닫힙니다)")
    subprocess.Popen([SANDBOX, wsb])
    done = os.path.join(work, "done.txt")
    results = os.path.join(work, "out", "results.txt")
    until = time.time() + 30 * 60
    while time.time() < until and not os.path.exists(done):
        time.sleep(5)
    text = open(results, encoding="utf-8-sig").read() if os.path.exists(results) else "(결과 없음)"
    print(text)
    return 0 if os.path.exists(done) and text.rstrip().endswith("실패: 0") else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: BOM 붙이기, 인코딩 시험**

```powershell
D:\AX\RPA\.venv\Scripts\python.exe -c "p = r'D:\AX\RPA\tools\sandbox_inner.ps1'; s = open(p, encoding='utf-8-sig').read(); open(p, 'w', encoding='utf-8-sig', newline='\r\n').write(s)"
D:\AX\RPA\.venv\Scripts\python.exe D:\AX\RPA\tests\test_encoding.py
```
Expected: `실패: 없음` (4절에 `sandbox_inner.ps1` 한 줄이 더 생긴다)

- [ ] **Step 5: 샌드박스 시험**

Run: `.venv\Scripts\python.exe tools\sandbox_test.py D:\AX\AFTER_MARKET_RPA_Setup_2026.09.29-5.exe`
Expected: 결과 끝 줄 `실패: 0`. `out\settings.png` 를 Read 로 열어 본다 (깨끗한 윈도우의 글꼴·배율에서 칸이 잘리지 않는지). 실패가 있으면 `out` 의 기록(setup*.log, agent_log1.txt, acl.txt, task.xml)으로 원인을 찾아 고치고, `--exes-from D:\AX\배포_2026.09.29-5` 로 새 판을 만들어 다시 돌린다 (고친 판이 생기면 앞 판은 지운다).

- [ ] **Step 6: 그래프 갱신** - `graphify update .`

---

### Task 8: 문서, 전체 시험, 검토, 커밋

**Files:**
- Modify: `release/배포안내.txt`, `release/클라우드_안내.txt` (BOM 있는 UTF-8 그대로 - `tests/test_encoding.py` 가 본다)
- Modify: `docs/firebase-architecture.md` (2절 파일 지도, 5절, 7절 새 PC 붙이기, 8절 시험 표)
- Modify: `docs/superpowers/specs/2026-09-29-installer-design.md` (상태 "구현됨", 구현하며 바뀐 것)

- [ ] **Step 1: 배포안내.txt - 맨 위 제목 블록 바로 뒤에 새 절**

```
■ 0. 설치 파일로 설치하기 (2026-09-29 부터 이 방법을 쓴다. 아래 1~9 는 손으로 옮기는 대비책)
    준비물 (관리자에게 받는다)
        업체코드, PC코드, 기계 계정 비밀번호  (대시보드 로그인 계정과 다르다)
        이 PC 의 ERPia 관리자코드·아이디·비밀번호, 메일(비즈메카) 아이디·비밀번호
    그 PC 에 미리 있어야 하는 것: 4번 (ERPia 설치, 'PC와 연결' + 휴대폰 연결, 프린터)
    RPA 를 돌릴 윈도우 계정은 관리자여야 한다. 그 계정으로 로그인해서 설치한다.

    1) AFTER_MARKET_RPA_Setup_<버전>.exe 를 그 PC 로 옮겨 실행한다.
       인터넷·메신저로 받은 파일이면 'Windows의 PC 보호' 가 뜬다 → [추가 정보] → [실행].
       (USB 로 옮기면 뜨지 않는다. 서명하지 않은 우리 프로그램이라 뜨는 것이다)
    2) 관리자 권한 요청에 [예] → [설치].
    3) 설치 끝 무렵 'AFTER MARKET RPA 설정' 창이 뜬다. 칸을 채우고 [저장].
       - 저장할 때 기계 계정으로 실제로 로그인해 본다. 틀리면 저장 단추 옆에 빨간 글씨로 까닭이 나온다.
       - 예전에 압축 폴더로 쓰던 PC 면 [기존 폴더에서 가져오기] 로 옛 배포 폴더를 고른다.
         옛 에이전트 창이 켜져 있으면 닫으라고 한다. 저장 뒤 옛 폴더 이름을 '_옮김' 으로 바꿀지 묻는다 (예).
    4) 대시보드(https://rpa-test-f02e0.web.app)에서 이 PC 가 '연결' 로 보이고, 현황·기록 탭 오른쪽에
       '버전 …' 이 보이면 된 것이다.

    설치한 뒤
        - 에이전트는 윈도우에 로그인할 때마다 창 없이 켜진다. 오류로 죽으면 잠시 뒤 저절로 다시 켜진다.
        - 이 PC 는 늘 로그인된 상태로 둔다 (로그아웃·화면 잠금이면 RPA 가 ERPia 를 다룰 수 없다).
        - 설정을 바꿀 때: 시작 메뉴 → AFTER MARKET RPA → 'RPA 설정' (관리자 권한 요청이 뜬다).
          비밀번호 칸은 바꿀 때만 넣는다 (비우면 그대로).
        - 대시보드에 '연결 끊김' 이 계속 보이면 'RPA 설정' 을 연다. 기계 계정 비밀번호가 바뀌었으면
          새 비밀번호를 넣고 저장하면 에이전트가 다시 켜진다.
        - 설치 자리: 프로그램 C:\Program Files\AFTER MARKET\RPA
                     설정·기록 C:\ProgramData\AFTER MARKET\RPA (관리자만 열린다)
          기록(에이전트_기록.txt, *_result.txt 등)은 그 data 폴더에 있다.
        - 지우기: 설정 → 앱 → 'AFTER MARKET RPA' 제거. 설정·기록도 지울지 묻는다 (다시 설치할 거면 아니요).
        - 새 버전: 새 설치 파일을 그대로 실행하면 덮어 설치한다 (설정은 그대로). RPA 가 도는 중이면 끝난 뒤 하라고 한다.
```

- [ ] **Step 2: 클라우드_안내.txt - '■ 준비' 바로 앞에 새 절**

```
■ 설치 파일로 설치한 PC (2026-09-29 부터)
    배포안내.txt 0번대로 설치했으면 이 문서의 '준비'·'에이전트 띄우기' 는 하지 않는다.
    에이전트는 윈도우 로그인 때 창 없이 켜지고, 설정은 시작 메뉴 'RPA 설정' 에서 바꾼다.
    에이전트 기록은 C:\ProgramData\AFTER MARKET\RPA\data\에이전트_기록.txt (관리자만 열린다).
    firebase\agent\에이전트_시작.bat 을 눌러도 '이미 돌고 있습니다' 로 바로 끝난다 (에이전트는 하나만 돈다).
```

- [ ] **Step 3: docs/firebase-architecture.md**

2절 파일 지도 `agent/` 에 `background.py  감독 (설치한 PC: 작업 스케줄러 → 창 없이 에이전트, 죽으면 다시 켬)` 한 줄, 코드 블록 뒤에 "저장소 루트의 `rpa_settings.py` 는 설치한 PC 의 설정 창이다 (`release/installer.iss` 가 설치 파일, `tools/build_release.py` 가 둘을 만든다)" 한 문단. 5절 끝에 "설치한 PC 에서는 작업 스케줄러(`AFTER MARKET\RPA Agent`)가 윈도우 로그인 때 `background.py` 를 띄우고, 감독이 에이전트를 창 없이 띄워 잡에 넣는다 (종료 코드 0·2·3·4 면 같이 끝나고 그 밖은 다시 켠다). 에이전트는 `Local\AFTER_MARKET_RPA_AGENT` 잠금으로 한 PC 에 하나만 돈다." 7절을 설치 파일 순서로 바꾼다 (1. `setup.js pc`·`agent`, 2. `build_release.py` 가 zip 과 `AFTER_MARKET_RPA_Setup_<판>.exe`, 3. 설치 파일과 세 값을 넘긴다, 4. 설치 → 설정 창, 5. 대시보드. 손으로 넘기는 zip 은 대비책으로 한 문단). 8절 명령에 `test_settings.py`·`test_background.py`·`check_settings_ui.py`·`tools\sandbox_test.py` 를, 표에 건수와 한 줄 설명을 더하고 에이전트 단위·빌드 스크립트·인코딩 건수를 고친다.

- [ ] **Step 4: 설계 문서 상태** - `**상태:** 구현됨 (2026-09-29, 첫 판 2026.09.29-5). 설계는 같은 날 사용자 승인` 로, 구현하며 바뀐 것이 있으면 해당 절에 날짜와 함께.

- [ ] **Step 5: 전체 시험**

'시험 돌리는 법' 의 명령을 모두 돌린다. 모두 `실패: 없음` / `N/N 통과`. `tests/test_layout.py` 45 가 그대로인지(2부가 1부 자리 규칙을 안 건드렸는지) 본다.

- [ ] **Step 6: 마지막 검토 (새 에이전트 하나)** - 브랜치 전체 diff 를 설계·계획과 대 보게 한다 (Critical/Important 는 고치고 다시 시험, Minor 는 보고에 남긴다)

- [ ] **Step 7: 커밋 (develop, 한 번)**

커밋 전에 `git diff --cached --stat` 과 `git diff --cached release/` 로 비밀번호·쿠키가 없는지 본다.
```powershell
git add rpa_settings.py firebase/agent/background.py firebase/agent/agent.py release/installer.iss tools/build_release.py tools/sandbox_test.py tools/sandbox_inner.ps1 tests/test_settings.py tests/test_background.py tests/check_settings_ui.py tests/test_build_release.py tests/test_encoding.py firebase/tests/test_agent.py firebase/tests/integration.js release/배포안내.txt release/클라우드_안내.txt docs/firebase-architecture.md docs/superpowers/specs/2026-09-29-installer-design.md docs/superpowers/specs/2026-09-29-release-layout-design.md docs/superpowers/plans/2026-09-29-installer.md
git commit -m "배포: 판 구조 2부 - 설치 마법사(Inno Setup)·설정 창·에이전트 감독과 하나만 돌기" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 8: 그래프 갱신, 기억 갱신** - `graphify update .`, 메모리(`next-steps.md` 노트북 전달 항목을 설치 파일로, 새 메모리 `installer-part2.md`, `MEMORY.md` 한 줄)
