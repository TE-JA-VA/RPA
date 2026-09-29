# 배포판 구조 1부 (판 구조) 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** RPA 파일을 프로그램·설정·기록으로 나누는 규칙을 코드에 넣고, 판 번호·판 목록(manifest.json)으로 PC 마다 어느 판인지 알아보게 하고, 노하우가 든 두 exe 를 Nuitka 로 만든다. 지금 도는 PC 는 하나도 멈추지 않는다.

**Architecture:** 자리 찾기는 `rpa_status` 한 곳(`program_dir`·`install_root`·`new_layout`·`config_dir`·`data_dir`)으로 모으고 exe 쪽 네 파일과 에이전트가 그것만 쓴다. 새 구조는 `%ProgramData%\AFTER MARKET\RPA\config` 폴더가 있을 때만 켜지고(2부 설치 마법사가 만든다), 없으면 지금과 똑같이 exe 옆을 쓴다. 판 점검(`check_install`)은 에이전트가 켤 때 한 번 돌아 `live.version` 으로 올라가고, 화면 상태 카드에 "판" 칸으로 보인다. 배포판은 `tools/build_release.py` 가 정해 둔 파일만 모아 만든다.

**Tech Stack:** Python 3.14.7 (`.venv`, 내장 python 같은 판), Nuitka 4.2.2 (실패하면 PyInstaller 6.22.2), Firebase RTDB·Hosting, Playwright(화면 시험)

**Spec:** `docs/superpowers/specs/2026-09-29-release-layout-design.md`

## Global Constraints

- 프로그램 `C:\Program Files\AFTER MARKET\RPA\`, 설정 `C:\ProgramData\AFTER MARKET\RPA\config\`, 기록 `C:\ProgramData\AFTER MARKET\RPA\data\`. 바탕화면 `ERPIA_AI` 는 그대로
- 새 구조 판정 = `install_root()\config` **폴더가 있다**. 시험은 언제나 `RPA_PROGRAMDATA` 로 임시 폴더를 가리킨다. **이 개발 PC 에 진짜 `C:\ProgramData\AFTER MARKET\RPA\config` 를 만들지 않는다** (이 PC 가 새 구조로 넘어간다)
- 옛 구조 동작은 바뀌지 않는다: 설정·기록 = `program_dir()` (exe 옆, 개발 PC 는 `dist`), 에이전트 파일 = `firebase\agent\` (agent.py 옆 - 개발 PC 도 dist 가 아니다)
- 먼저 보는 환경변수(지금 그대로): `RPA_USER_CONFIG`, `RPA_CRED_FILE`, `RPA_STATUS_DIR`, `RPA_AGENT_CONFIG`, `RPA_AGENT_QUEUE`. 새로 하나: `RPA_PROGRAMDATA`
- 판 번호 `YYYY.MM.DD-N`, `manifest.json` 의 `"format": 1`, `files` 에는 지문 대상(exe 둘, `Run_All.bat`, `rpa_status.py`, `rpa_dashboard.py`, `firebase/agent/` 넷)만, python·브라우저는 `runtime` 이름표만. 경로는 `/` 구분
- 판 점검 상태는 `ok` / `mixed` / `none` / `error` 넷. 점검은 예외를 내보내지 않는다. 사고 확인용이지 변조 방어가 아니다
- 비밀번호·로그인 쿠키·서비스 계정 키는 배포판·기록·응답·커밋에 절대 싣지 않는다. `setup.js user/agent/passwd` 는 Claude 도구로 돌리지 않는다
- **커밋은 사용자가 허락했을 때만** (develop). main push 는 사용자가 "메인 push" 라고 할 때만. `--no-verify` 금지
- 파이썬 패치를 bash heredoc 으로 쓰지 않는다 (백슬래시가 깨진다) - Edit/Write 도구를 쓴다
- 배포판의 `.bat`·`.txt` 는 CP949. PowerShell 스크립트 파일을 만들면 UTF-8 BOM 으로 저장한다 (5.1 이 BOM 없는 파일을 ANSI 로 읽어 한글 경로가 깨진다)
- 이 Claude 셸은 관리자 권한이 아니다. ERPia 를 실제로 다루는 실행(`--uiacheck`, 로그인 실행)은 사용자가 관리자 PowerShell 에서 한다
- 코드를 고친 작업의 끝에 `graphify update .` 를 돌린다 (저장소 CLAUDE.md 규칙)
- 문서·주석은 한국어, 주변 코드 말투(`~다`)와 같게

## Review Focus

1. **한글 파일 이름** (`firebase/agent/에이전트_시작.bat`, `배포안내.txt`, `클라우드_안내.txt`): 판 목록·지문·압축에서 깨지지 않고 그대로 맞아야 한다 → Task 3(판 점검)·Task 8(압축) 시험
2. **개발 PC 의 에이전트 파일 자리**: 이 PC 는 `dist\Run_All.bat` 이 있어 `program_dir()` 이 `dist` 다. 에이전트 큐·설정이 `dist\firebase\agent` 로 새면 안 되고 지금 자리(`firebase\agent`)여야 한다 → Task 5 시험
3. **판 목록이 깨졌거나 밖을 가리킴** (`..`, 절대 경로, 드라이브 문자, 역슬래시, 형식 번호 다름, 항목이 dict 아님): `error` 로 올리고 에이전트는 계속 돈다. 밖의 파일은 읽지 않는다 → Task 3 시험
4. **옛 에이전트(노트북 pc_a)는 `version` 을 안 올린다 / 값이 이상하다** (없음, 필드 빠짐, HTML 이 든 이름): 화면은 `없음`·글자 그대로 보여 주고 오류가 없다 → Task 7 시험
5. **exe 콘솔 출력 인코딩** (PyInstaller exe 는 CP949, Nuitka 는 다를 수 있음): 빌드 스크립트의 `--check` 확인이 끝 줄 표지를 둘 다로 찾아야 한다 → Task 8 시험 (`found_marker`)

---

## 파일 지도

| 파일 | 하는 일 | 작업 |
|---|---|---|
| `rpa_status.py` | 자리 찾기(`packaged`·`run_kind`·`program_dir`·`install_root`·`new_layout`·`config_dir`·`data_dir`), 사용자 설정 자리, 판 점검(`file_digest`·`manifest_path_ok`·`check_install`) | 2, 3 |
| `run_routine.py`, `web_runner.py`, `sms_watch.py`, `perform_login.py` | 각자의 `app_base_dir()` 를 지우고 `BASE_DIR = data_dir()`. 브라우저 자리는 `program_dir()` | 4 |
| `firebase/agent/secret.py` | `agent_config.json` 기본 자리 (새 구조면 `config_dir()`) | 5 |
| `firebase/agent/agent.py` | 큐·위치·기록 기본 자리 (새 구조면 `data_dir()`), 켤 때 판 점검 → `live.version` | 5, 6 |
| `firebase/web/rpa.js` | 상태 카드 "판" 칸 (`verStat`) | 7 |
| `tools/build_release.py` (새) | 배포판 만들기: exe 빌드 → 모으기 → 판 목록 → 압축 → 스스로 확인 | 8 |
| `release/RPA_UserConfig.template.json`, `release/배포안내.txt`, `release/클라우드_안내.txt` (새) | 배포판에 들어가는 빈 틀·안내 문서 (지금은 배포 폴더에만 있다) | 8, 9 |
| `tests/test_layout.py` (새) | 자리 찾기·판 점검·exe 쪽 모듈 자리 | 2, 3, 4 |
| `tests/test_build_release.py` (새) | 빌드 스크립트 (exe 는 안 만들고 가짜 입력으로) | 8 |
| `firebase/tests/test_agent.py` | 10절 에이전트 파일 자리 | 5 |
| `firebase/tests/integration.js` | 켤 때 `live.version` 이 올라오는지 | 6 |
| `firebase/tests/check_web.py` | 10절 판 표시 | 7 |
| `docs/firebase-architecture.md`, 설계 문서 | 배치·판·배포판 만들기, Nuitka 시험 결과 | 1, 9 |

## 시험 돌리는 법 (모든 작업 공통)

```powershell
cd D:\AX\RPA
.venv\Scripts\python.exe tests\test_layout.py            # Task 2~4 에서 생김
.venv\Scripts\python.exe tests\test_build_release.py     # Task 8 에서 생김
.venv\Scripts\python.exe tests\test_dashboard_modules.py # 기존 100
.venv\Scripts\python.exe tests\test_routine_modules.py   # 기존 107
cd D:\AX\RPA\firebase
python tests\test_agent.py                               # 기존 123
. .\emu_env.ps1; cd tests
firebase emulators:exec --config ../firebase.json --only auth,database,firestore --project rpa-test-f02e0 "node integration.js"
firebase emulators:exec --config ../firebase.json --only auth,database,firestore,hosting --project rpa-test-f02e0 "D:\AX\RPA\.venv\Scripts\python.exe check_web.py"
```
모든 시험 파일은 끝에 `실패: 없음` 또는 `N/N 통과` 를 찍는다.

---

### Task 1: Nuitka 작은 시험 (반나절 안)

설계 7절. 결과만 남기는 시험이다 - 여기서 만든 exe 는 버린다. 결론(Nuitka 를 쓸지, 쓴다면 옵션)이 Task 8 의 빌드 옵션이 된다.

**Files:**
- Create (버림, gitignore 된 `build\` 안): `build\nuitka_probe\where.py`
- Modify: `docs/superpowers/specs/2026-09-29-release-layout-design.md` (7절 끝에 시험 결과)

**Interfaces:**
- Produces: Task 8 이 쓸 Nuitka 옵션 목록 (`NUITKA_COMMON`, `NUITKA_EXTRA`) 과 결론 `nuitka` | `pyinstaller`. Task 2 가 쓸 사실 "onefile 에서 `__compiled__.containing_dir` 가 exe 가 놓인 폴더다" (아니면 `sys.argv[0]`)

- [ ] **Step 1: Nuitka 설치 (우리 PC 의 .venv 에만)**

```powershell
cd D:\AX\RPA
.venv\Scripts\python.exe -m pip install nuitka==4.2.2 zstandard
.venv\Scripts\python.exe -m nuitka --version
```
기대: 첫 줄 `4.2.2`. (`zstandard` 는 onefile 압축용이다. 없으면 exe 가 크게 나온다)

- [ ] **Step 2: exe 자리 알아내는 작은 exe**

`build\nuitka_probe\where.py` 를 Write 로 만든다:
```python
import os
import sys

c = globals().get("__compiled__")
print("containing_dir=", getattr(c, "containing_dir", None))
print("argv0=", os.path.abspath(sys.argv[0]))
print("executable=", sys.executable)
print("file=", __file__)
print("frozen=", getattr(sys, "frozen", None))
```
빌드하고, 다른 폴더로 옮겨 실행한다:
```powershell
cd D:\AX\RPA
.venv\Scripts\python.exe -m nuitka --onefile --assume-yes-for-downloads --output-dir=build\nuitka_probe build\nuitka_probe\where.py
New-Item -ItemType Directory -Force build\nuitka_probe\moved | Out-Null
Copy-Item build\nuitka_probe\where.exe build\nuitka_probe\moved\where.exe -Force
build\nuitka_probe\moved\where.exe
```
기대: `containing_dir=` 가 `...\build\nuitka_probe\moved` 이고, `file=` 은 임시 폴더다. `containing_dir=None` 이면 `argv0=` 이 moved 폴더인지 본다 (Task 2 의 뒤쪽 규칙).
- 처음 빌드는 C 컴파일러를 받아 온다. **Nuitka 가 Visual Studio(MSVC) 를 설치하라고 하면 멈추고 사용자에게 묻는다** (수 GB, 관리자 권한).

- [ ] **Step 3: 두 exe 를 Nuitka 로 빌드**

지금 PyInstaller spec 이 모으는 것과 같은 것을 넣는다 (`comtypes`·`pywinauto`·`win32timezone`, 프리페어는 `playwright`). 한 줄씩:
```powershell
cd D:\AX\RPA
.venv\Scripts\python.exe -m nuitka --onefile --assume-yes-for-downloads --windows-console-mode=force --include-package=comtypes --include-package=pywinauto --include-module=win32timezone --nofollow-import-to=numpy --nofollow-import-to=yaml --nofollow-import-to=scipy --nofollow-import-to=pandas --nofollow-import-to=torch --nofollow-import-to=cv2 --nofollow-import-to=matplotlib --nofollow-import-to=networkx --nofollow-import-to=graphify --remove-output --output-dir=build\nuitka --output-filename=ERPia_RPA.exe run_routine.py
.venv\Scripts\python.exe -m nuitka --onefile --assume-yes-for-downloads --windows-console-mode=force --include-package=comtypes --include-package=pywinauto --include-module=win32timezone --include-package=playwright --include-package-data=playwright --nofollow-import-to=numpy --nofollow-import-to=yaml --nofollow-import-to=scipy --nofollow-import-to=pandas --nofollow-import-to=torch --nofollow-import-to=cv2 --nofollow-import-to=matplotlib --nofollow-import-to=networkx --nofollow-import-to=graphify --remove-output --output-dir=build\nuitka --output-filename=Prepare_RPA.exe web_runner.py
Get-ChildItem build\nuitka\*.exe | Select-Object Name, Length
```
기대: 두 exe 가 생긴다. 빌드 경고에 playwright 플러그인이 나오면 둘째 줄에 `--enable-plugin=playwright` 를 더해 다시 한다. 바꾼 옵션은 모두 적어 둔다 (Step 8).

- [ ] **Step 4: `--check` 를 지금 exe 와 비교**

지금 exe 는 결과 로그를 exe 옆에 쓴다. `dist` 에서 그대로 돌리면 이 PC 의 마지막 실제 실행 로그를 덮으므로, **사본을 `build\nuitka\pyi\` 에 두고 거기서** 돌린다. 두 쪽 모두 같은 설정(이 PC 의 실제 설정, `--check` 는 읽기만 한다)과 임시 상태 폴더로 돌린다.
```powershell
cd D:\AX\RPA
New-Item -ItemType Directory -Force build\nuitka\pyi | Out-Null
Copy-Item dist\ERPia_RPA.exe, dist\Prepare_RPA.exe build\nuitka\pyi\ -Force
$env:RPA_USER_CONFIG = "D:\AX\RPA\dist\RPA_UserConfig.json"
$env:RPA_STATUS_DIR = "$env:TEMP\rpa_probe_status"
foreach ($pair in @(@("build\nuitka\pyi\ERPia_RPA.exe","pyi_routine"), @("build\nuitka\ERPia_RPA.exe","nk_routine"), @("build\nuitka\pyi\Prepare_RPA.exe","pyi_prepare"), @("build\nuitka\Prepare_RPA.exe","nk_prepare"))) {
  $p = Start-Process -FilePath (Resolve-Path $pair[0]) -ArgumentList "--check" -NoNewWindow -Wait -PassThru -RedirectStandardOutput "build\nuitka\$($pair[1]).txt"
  "$($pair[1]) exit=$($p.ExitCode)"
}
Remove-Item Env:RPA_USER_CONFIG, Env:RPA_STATUS_DIR
```
비교 스크립트 `build\nuitka\compare.py` 를 Write 로 만든다 (경로·실행 형태 줄과 시각은 빼고 줄을 맞춘다. exe 출력은 CP949):
```python
import re

SKIP = re.compile(r"실행 형태|기준 폴더|===|^\s*$")


def lines(name):
    text = open(f"build/nuitka/{name}.txt", encoding="cp949", errors="replace").read()
    return [l for l in text.splitlines() if not SKIP.search(l)]


for k in ("routine", "prepare"):
    a, b = lines(f"pyi_{k}"), lines(f"nk_{k}")
    print(k, "SAME" if a == b else "DIFF")
    for x, y in zip(a, b):
        if x != y:
            print("  pyi:", x)
            print("  nk :", y)
```
```powershell
.venv\Scripts\python.exe build\nuitka\compare.py
```
기대: `routine SAME`, `prepare SAME`. DIFF 면 찍힌 줄을 본다. 경로 줄이 다른 건 Task 2 전이라 당연할 수 있다 - 설정·물류·모듈·사이트·프로그램 줄이 같으면 통과로 본다.

- [ ] **Step 5: 화면 조회(UIA) 확인 - 사용자가 관리자 PowerShell 에서**

ERPia 를 켜고 로그인해 둔 상태에서 사용자에게 부탁한다 (이 셸은 관리자가 아니라 ERPia 창을 못 읽는다):
```powershell
cd D:\AX\RPA
build\nuitka\ERPia_RPA.exe --uiacheck
```
기대: 지금 exe(`dist\ERPia_RPA.exe --uiacheck`)와 같이 메뉴·요소가 읽힌다. comtypes 가 만드는 모듈 자리 문제가 있으면 여기서 '창은 찾는데 안이 안 보이는' 상태로 드러난다.

- [ ] **Step 6: 로그인만 켜서 실제로 한 번 - 사용자가 관리자 PowerShell 에서**

먼저 사용자에게 알린다: ERPia 화면을 잡으니 PC 를 만지지 말 것, 자동 실행 시각을 피할 것, 그동안 웹에서 실행을 누르지 말 것. 실제 설정은 건드리지 않게 "로그인만" 사본을 만든다 (잠긴 비밀번호는 같은 PC·같은 계정이라 사본에서도 풀린다):
```powershell
cd D:\AX\RPA
.venv\Scripts\python.exe -c "import json,os; d=json.load(open(r'dist\RPA_UserConfig.json',encoding='utf-8')); d['Routine']={'Login':'Y','Sales':'N','Hold':'N','Logistics':'N','Output':'N'}; p=os.path.join(os.environ['TEMP'],'rpa_probe_login.json'); json.dump(d,open(p,'w',encoding='utf-8'),ensure_ascii=False,indent=2); print(p)"
```
사용자가 관리자 PowerShell 에서:
```powershell
$env:RPA_USER_CONFIG = "$env:TEMP\rpa_probe_login.json"; $env:RPA_STATUS_DIR = "$env:TEMP\rpa_probe_status"
D:\AX\RPA\build\nuitka\ERPia_RPA.exe
```
기대: 마지막 줄 `=== 루틴 종료 … (성공) ===`. 끝나면 사본을 지운다: `Remove-Item $env:TEMP\rpa_probe_login.json`.

- [ ] **Step 7: 윈도우 보안(Defender) 검사**

```powershell
& "$env:ProgramFiles\Windows Defender\MpCmdRun.exe" -Scan -ScanType 3 -File "D:\AX\RPA\build\nuitka\ERPia_RPA.exe" -DisableRemediation
& "$env:ProgramFiles\Windows Defender\MpCmdRun.exe" -Scan -ScanType 3 -File "D:\AX\RPA\build\nuitka\Prepare_RPA.exe" -DisableRemediation
```
기대: 둘 다 종료 코드 0, `found no threats`.

- [ ] **Step 8: 결론을 설계 문서에 적는다**

`docs/superpowers/specs/2026-09-29-release-layout-design.md` 7절 끝에 이 절을 붙인다 (값은 실제 결과로):
```markdown
**1단계 시험 결과 (2026-09-XX)**
- 결론: Nuitka 사용 | PyInstaller 유지 (이유: …)
- exe 자리: `__compiled__.containing_dir` = exe 가 놓인 폴더 (확인함) | 없음 → `sys.argv[0]`
- 크기: ERPia_RPA.exe … MB (PyInstaller 21MB), Prepare_RPA.exe … MB (PyInstaller 61MB). 빌드 시간 …분
- `--check` 비교: 같음 | 다른 줄: …
- `--uiacheck`, 로그인 실행: 성공 | 실패 (…)
- Defender: 통과 | …
- 쓴 옵션: (Step 3 의 두 줄, 바꾼 것이 있으면 바꾼 대로)
```
**넷 중 하나라도 반나절 안에 안 풀리면**: 결론을 "PyInstaller 유지" 로 적고 사용자에게 알린다. Task 2~9 는 그대로 진행하고, Task 8 의 `--builder` 기본값만 `pyinstaller` 로 한다.

- [ ] **Step 9: 커밋 (사용자가 허락했을 때만)**

```powershell
git add docs/superpowers/specs/2026-09-29-release-layout-design.md
git commit -m "설계: Nuitka 1단계 시험 결과" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: `rpa_status` 자리 찾기

설계 3절. 옛 구조 동작은 그대로 두고, 새 구조와 Nuitka 를 알아보게 한다.

**Files:**
- Modify: `rpa_status.py:198-217` (`program_dir`, `user_config_path`) - 그 앞에 새 함수들
- Create: `tests/test_layout.py`

**Interfaces:**
- Produces (모두 `rpa_status`):
  - `PRODUCT_DIRS = ("AFTER MARKET", "RPA")`
  - `packaged() -> bool` - Nuitka 또는 PyInstaller 로 묶여 돈다
  - `run_kind() -> str` - `"exe(Nuitka)"` | `"exe(PyInstaller)"` | `"파이썬 스크립트"`
  - `program_dir() -> str` - Nuitka: `__compiled__.containing_dir` (없으면 `sys.argv[0]` 의 폴더) / PyInstaller: `sys.executable` 의 폴더 / 소스: 이 파일 옆, 옆 `dist\Run_All.bat` 이 있으면 `dist`
  - `install_root() -> str` - `RPA_PROGRAMDATA` 또는 `%ProgramData%\AFTER MARKET\RPA`
  - `new_layout() -> bool` - `install_root()\config` 폴더가 있다
  - `config_dir() -> str` - 새 구조 `install_root()\config`, 아니면 `program_dir()`
  - `data_dir() -> str` - 새 구조 `install_root()\data` (없으면 만든다, 못 만들어도 예외 없음), 아니면 `program_dir()`
  - `user_config_path()` - 환경변수 다음은 `config_dir()\RPA_UserConfig.json`

- [ ] **Step 1: 실패하는 시험을 쓴다**

`tests/test_layout.py` 를 Write 로 만든다:
```python
"""배포판 구조 시험 - rpa_status 의 자리 찾기(프로그램·설정·기록)와 판 점검(manifest.json),
exe 쪽 모듈이 그 자리를 쓰는지. 설계: docs/superpowers/specs/2026-09-29-release-layout-design.md

실제 C:\\ProgramData 는 건드리지 않는다. 새 구조는 RPA_PROGRAMDATA 로 임시 폴더를 가리켜 흉내 낸다.

    .venv\\Scripts\\python.exe tests\\test_layout.py
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _k in ("RPA_PROGRAMDATA", "RPA_USER_CONFIG", "RPA_CRED_FILE", "RPA_AGENT_CONFIG", "RPA_AGENT_QUEUE"):
    os.environ.pop(_k, None)
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

import rpa_status as st  # noqa: E402

fails = []
_no = [0]


def check(name, cond, detail=""):
    _no[0] += 1
    mark = "통과" if cond else "실패"
    print(f"  {_no[0]:2d}. [{mark}] {name}" + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(f"{_no[0]}. {name} {detail}")


def finish():
    print()
    print(f"실패: {'없음' if not fails else fails}")
    sys.exit(1 if fails else 0)


tmp = tempfile.mkdtemp(prefix="rpa_layout_")

# ---------------------------------------------------------------------------
print("=== 1. 옛 구조 (새 자리에 config 폴더가 없다) ===")
empty_root = os.path.join(tmp, "empty_root")
os.environ["RPA_PROGRAMDATA"] = empty_root
check("config 폴더가 없으면 옛 구조", st.new_layout() is False)
check("옛 구조의 설정 자리는 프로그램 폴더", st.config_dir() == st.program_dir())
check("옛 구조의 기록 자리도 프로그램 폴더", st.data_dir() == st.program_dir())
check("옛 구조의 사용자 설정은 지금 자리 그대로",
      st.user_config_path() == os.path.join(st.program_dir(), st.USER_CONFIG_NAME))
check("옛 구조에서는 새 자리 폴더를 만들지 않는다", not os.path.exists(empty_root))

# ---------------------------------------------------------------------------
print("=== 2. 새 구조 (RPA_PROGRAMDATA 에 config 폴더) ===")
new_root = os.path.join(tmp, "AFTER MARKET", "RPA")
os.makedirs(os.path.join(new_root, "config"))
os.environ["RPA_PROGRAMDATA"] = new_root
check("config 폴더가 있으면 새 구조", st.new_layout() is True)
check("새 구조의 설정 자리는 config", st.config_dir() == os.path.join(new_root, "config"))
data = st.data_dir()
check("새 구조의 기록 자리는 data, 없으면 만든다", data == os.path.join(new_root, "data") and os.path.isdir(data))
check("새 구조의 사용자 설정은 config 안",
      st.user_config_path() == os.path.join(new_root, "config", st.USER_CONFIG_NAME))
os.environ["RPA_USER_CONFIG"] = os.path.join(tmp, "x.json")
check("시험용 RPA_USER_CONFIG 가 새 구조보다 앞선다", st.user_config_path() == os.path.join(tmp, "x.json"))
del os.environ["RPA_USER_CONFIG"]

# ---------------------------------------------------------------------------
print("=== 3. 기본 뿌리 ===")
del os.environ["RPA_PROGRAMDATA"]
check("기본 뿌리는 %ProgramData%\\AFTER MARKET\\RPA",
      st.install_root() == os.path.join(os.environ.get("ProgramData") or r"C:\ProgramData", "AFTER MARKET", "RPA"))
check("이 개발 PC 에는 진짜 새 자리가 없다 (있으면 이 PC 가 새 구조로 넘어간다 - 만들지 말 것)", st.new_layout() is False)

# ---------------------------------------------------------------------------
print("=== 4. 프로그램 폴더: 소스·PyInstaller·Nuitka ===")
here = str(ROOT)
expected = os.path.join(here, "dist") if os.path.isfile(os.path.join(here, "dist", "Run_All.bat")) else here
check("소스는 저장소 폴더 (옆 dist 에 Run_All.bat 이 있으면 dist)", st.program_dir() == expected, st.program_dir())
check("소스는 묶인 exe 가 아니다", st.packaged() is False and st.run_kind() == "파이썬 스크립트")

real_exe, had_frozen = sys.executable, hasattr(sys, "frozen")
sys.frozen = True
sys.executable = os.path.join(tmp, "pyi", "ERPia_RPA.exe")
try:
    check("PyInstaller exe 는 exe 옆", st.program_dir() == os.path.join(tmp, "pyi"))
    check("실행 형태 이름 (PyInstaller)", st.packaged() is True and st.run_kind() == "exe(PyInstaller)")
finally:
    sys.executable = real_exe
    if not had_frozen:
        del sys.frozen

st.__compiled__ = types.SimpleNamespace(containing_dir=os.path.join(tmp, "nk"))
try:
    check("Nuitka exe 는 exe 가 놓인 폴더 (__compiled__.containing_dir, 풀린 임시 폴더가 아니다)",
          st.program_dir() == os.path.join(tmp, "nk"))
    check("실행 형태 이름 (Nuitka)", st.packaged() is True and st.run_kind() == "exe(Nuitka)")
finally:
    del st.__compiled__
st.__compiled__ = types.SimpleNamespace()
real_argv0 = sys.argv[0]
sys.argv[0] = os.path.join(tmp, "nk2", "ERPia_RPA.exe")
try:
    check("containing_dir 가 없으면 sys.argv[0] 의 폴더", st.program_dir() == os.path.join(tmp, "nk2"))
finally:
    sys.argv[0] = real_argv0
    del st.__compiled__

# ---------------------------------------------------------------------------
print("=== 5. 기록 폴더를 만들 수 없어도 예외를 내지 않는다 ===")
bad_root = os.path.join(tmp, "bad")
os.makedirs(os.path.join(bad_root, "config"))
open(os.path.join(bad_root, "data"), "w").close()      # data 자리에 파일이 있어 폴더를 못 만든다
os.environ["RPA_PROGRAMDATA"] = bad_root
try:
    got = st.data_dir()
    ok = got == os.path.join(bad_root, "data")
except Exception as e:  # noqa: BLE001
    ok, got = False, repr(e)
check("data 폴더를 못 만들어도 경로만 돌려준다 (기록 때문에 RPA 가 멈추면 안 된다)", ok, str(got))
del os.environ["RPA_PROGRAMDATA"]

finish()
```

- [ ] **Step 2: 시험이 실패하는지 본다**

Run: `.venv\Scripts\python.exe tests\test_layout.py`
Expected: `AttributeError: module 'rpa_status' has no attribute 'new_layout'` 로 멈춘다.

- [ ] **Step 3: 구현**

`rpa_status.py` 의 `program_dir()`·`user_config_path()` (지금 198~217줄) 를 Edit 로 아래로 바꾼다. 앞의 주석 덩어리(사용자 설정 절 설명)는 그대로 둔다.
```python
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
```

- [ ] **Step 4: 시험이 통과하는지 본다**

Run: `.venv\Scripts\python.exe tests\test_layout.py` → Expected: `실패: 없음`
Run: `.venv\Scripts\python.exe tests\test_dashboard_modules.py` → Expected: `실패: 없음` (기존 100, 사용자 설정 자리가 그대로인지)

- [ ] **Step 5: 그래프 갱신, 커밋 (사용자가 허락했을 때만)**

```powershell
graphify update .
git add rpa_status.py tests/test_layout.py
git commit -m "구조: rpa_status 자리 찾기 (새 구조·Nuitka), 옛 구조는 그대로" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: `rpa_status` 판 점검

설계 4·5절.

**Files:**
- Modify: `rpa_status.py` - 맨 위 import 에 `hashlib`, Task 2 의 `user_config_path()` 바로 뒤에 '판' 절
- Modify: `tests/test_layout.py` - 6절 (마지막 `finish()` 앞)

**Interfaces:**
- Consumes: `program_dir()` (Task 2)
- Produces (모두 `rpa_status`):
  - `MANIFEST_NAME = "manifest.json"`, `MANIFEST_FORMAT = 1`, `CHANGED_MAX = 10`
  - `file_digest(path) -> {"sha256": str, "size": int}`
  - `manifest_path_ok(rel) -> bool`
  - `check_install(root=None) -> {"version": str | None, "state": "ok"|"mixed"|"none"|"error", "changed": [str], "changed_count": int, "checked_at": "YYYY-MM-DDTHH:MM:SS", "error": str (error 일 때만)}` - 예외를 내보내지 않는다

- [ ] **Step 1: 실패하는 시험을 쓴다**

`tests/test_layout.py` 의 마지막 `finish()` 바로 앞에 넣는다:
```python
# ---------------------------------------------------------------------------
print("=== 6. 판 점검 (manifest.json) ===")
prog = os.path.join(tmp, "prog")
os.makedirs(os.path.join(prog, "firebase", "agent"))
files = {
    "ERPia_RPA.exe": b"exe-1",
    "rpa_status.py": b"print(1)\n",
    "firebase/agent/에이전트_시작.bat": "@echo off\r\n".encode("cp949"),
}
for rel, body in files.items():
    with open(os.path.join(prog, *rel.split("/")), "wb") as f:
        f.write(body)


def write_manifest(entries, version="2026.09.29-1", fmt=1):
    with open(os.path.join(prog, st.MANIFEST_NAME), "w", encoding="utf-8") as f:
        json.dump({"format": fmt, "version": version, "files": entries}, f, ensure_ascii=False)


entries = {rel: st.file_digest(os.path.join(prog, *rel.split("/"))) for rel in files}
check("지문은 SHA-256 과 크기",
      entries["ERPia_RPA.exe"] == {"sha256": hashlib.sha256(b"exe-1").hexdigest(), "size": 5})
r = st.check_install(prog)
check("목록이 없으면 none", r["state"] == "none" and r["version"] is None and r["changed"] == [], str(r))
check("점검 시각을 남긴다", isinstance(r["checked_at"], str) and len(r["checked_at"]) == 19, str(r))
write_manifest(entries)
r = st.check_install(prog)
check("모두 같으면 ok", r["state"] == "ok" and r["version"] == "2026.09.29-1" and r["changed_count"] == 0, str(r))
os.makedirs(os.path.join(prog, "__pycache__"))
open(os.path.join(prog, "__pycache__", "rpa_status.cpython-314.pyc"), "wb").close()
check("목록에 없는 파일(__pycache__)은 무시한다", st.check_install(prog)["state"] == "ok")
with open(os.path.join(prog, "rpa_status.py"), "wb") as f:
    f.write(b"print(2)\n")
r = st.check_install(prog)
check("지문이 다르면 mixed, 그 파일 이름", r["state"] == "mixed" and r["changed"] == ["rpa_status.py"]
      and r["changed_count"] == 1, str(r))
os.remove(os.path.join(prog, "firebase", "agent", "에이전트_시작.bat"))
r = st.check_install(prog)
check("없는 파일도 mixed (한글 이름 그대로)", r["state"] == "mixed" and r["changed_count"] == 2
      and "firebase/agent/에이전트_시작.bat" in r["changed"], str(r))
write_manifest({f"f{i}.txt": {"sha256": "0" * 64, "size": 1} for i in range(15)})
r = st.check_install(prog)
check("다른 파일 이름은 10개까지, 개수는 따로", r["state"] == "mixed" and len(r["changed"]) == 10
      and r["changed_count"] == 15, str(r))
with open(os.path.join(prog, st.MANIFEST_NAME), "w", encoding="utf-8") as f:
    f.write("{깨짐")
r = st.check_install(prog)
check("목록이 깨지면 error (예외를 내보내지 않는다)", r["state"] == "error" and r.get("error"), str(r))
write_manifest(entries, fmt=2)
check("형식 번호가 다르면 error", st.check_install(prog)["state"] == "error")
write_manifest({"x.txt": "문자열"})
check("항목이 dict 가 아니면 error", st.check_install(prog)["state"] == "error")
outside = os.path.join(tmp, "outside.txt")
with open(outside, "w") as f:
    f.write("밖")
for bad in ("../outside.txt", "/abs.txt", "C:/Windows/win.ini", "a/../../outside.txt", "sub\\x.txt", "", "./x.txt"):
    write_manifest({bad: {"sha256": "0" * 64, "size": 1}})
    check(f"밖을 가리키거나 이상한 경로는 error ({bad!r})", st.check_install(prog)["state"] == "error")
check("manifest_path_ok: 안쪽 상대 경로만", st.manifest_path_ok("firebase/agent/agent.py")
      and not st.manifest_path_ok(None) and not st.manifest_path_ok("a//b"))
```

- [ ] **Step 2: 시험이 실패하는지 본다**

Run: `.venv\Scripts\python.exe tests\test_layout.py`
Expected: `AttributeError: module 'rpa_status' has no attribute 'MANIFEST_NAME'` (또는 `file_digest`)

- [ ] **Step 3: 구현**

`rpa_status.py` 맨 위 import 에 `import hashlib` 를 `import functools` 다음 줄에 더한다. Task 2 의 `user_config_path()` 바로 뒤에 넣는다:
```python
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
```

- [ ] **Step 4: 시험이 통과하는지 본다**

Run: `.venv\Scripts\python.exe tests\test_layout.py` → Expected: `실패: 없음`

- [ ] **Step 5: 그래프 갱신, 커밋 (사용자가 허락했을 때만)**

```powershell
graphify update .
git add rpa_status.py tests/test_layout.py
git commit -m "구조: 판 목록(manifest.json) 지문과 판 점검" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: exe 쪽 네 파일이 `rpa_status` 의 자리를 쓴다

설계 3절 "exe 쪽 네 파일". 옛 구조에서 exe 는 지금과 같은 폴더(exe 옆)에 쓴다. **소스로 돌릴 때 개발 PC 에서는 `dist` 에 쓰게 된다** (`program_dir()` 규칙 - 대시보드가 띄우는 exe 와 같은 자리). 시험·코드 어디도 저장소 뿌리의 결과 파일을 읽지 않는 것을 확인했다 (2026-09-29).

**Files:**
- Modify: `run_routine.py:120-133` (`app_base_dir` 지움, `BASE_DIR`), `run_routine.py:5326-5327` (점검 줄), `run_uia_check` 의 `실행 형태` 줄
- Modify: `web_runner.py:30-58` (`_setup_playwright_browsers`), `web_runner.py:119-126` (`app_base_dir` 지움, `BASE_DIR`)
- Modify: `sms_watch.py` (import, `app_base_dir` 지움, `BASE_DIR`, `cmd_check` 두 줄)
- Modify: `perform_login.py:34-38` (`app_base_dir` 지움), `perform_login.py:60` (`BASE_DIR`)
- Modify: `tests/test_layout.py` - 7절

**Interfaces:**
- Consumes: `rpa_status.data_dir()`, `program_dir()`, `packaged()`, `run_kind()`, `new_layout()` (Task 2)
- Produces: 모듈 상수 이름은 그대로 - `run_routine.RESULT_PATH`, `web_runner.RESULT_PATH`, `web_runner.SESSION_DIR`, `sms_watch.LOG_PATH`, `perform_login.OUT_FILE` (값만 `data_dir()` 기준)

- [ ] **Step 1: 실패하는 시험을 쓴다**

`tests/test_layout.py` 의 마지막 `finish()` 바로 앞에 넣는다:
```python
# ---------------------------------------------------------------------------
print("=== 7. exe 쪽 모듈은 rpa_status 의 기록 자리를 쓴다 ===")
NAMES = ["run_routine_result.txt", "prepare_result.txt", "sessions", "sms_watch_log.txt", "perform_login_result.txt"]
PROBE = (f"import sys; sys.path.insert(0, {str(ROOT)!r}); import json, run_routine as rr, web_runner as wr, "
         "sms_watch as sw, perform_login as pl; "
         "print(json.dumps([rr.RESULT_PATH, wr.RESULT_PATH, wr.SESSION_DIR, sw.LOG_PATH, pl.OUT_FILE]))")


def module_paths(programdata):
    """네 모듈을 새 프로세스에서 불러와 결과 파일 자리를 받는다 (모듈 상수라 import 할 때 정해진다)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("RPA_")}
    env.update(RPA_PROGRAMDATA=programdata, RPA_STATUS_DIR=os.path.join(tmp, "status"), PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, "-c", PROBE], cwd=str(ROOT), env=env, capture_output=True,
                       text=True, encoding="utf-8", timeout=180)
    if r.returncode != 0:
        return r.stderr[-500:]
    return json.loads(r.stdout.strip().splitlines()[-1])


got = module_paths(new_root)          # 2절에서 만든 새 구조 뿌리 (config 있음)
check("새 구조면 결과 로그·세션이 모두 data 에", got == [os.path.join(new_root, "data", n) for n in NAMES], str(got))
got = module_paths(os.path.join(tmp, "empty_root2"))
check("옛 구조면 지금처럼 프로그램 폴더 (exe 옆, 개발 PC 는 dist)",
      got == [os.path.join(st.program_dir(), n) for n in NAMES], str(got))
for name in ("run_routine.py", "web_runner.py", "sms_watch.py", "perform_login.py"):
    src = open(ROOT / name, encoding="utf-8").read()
    check(f"{name} 에 각자 exe 옆을 계산하던 app_base_dir 이 없다", "def app_base_dir" not in src)
```

- [ ] **Step 2: 시험이 실패하는지 본다**

Run: `.venv\Scripts\python.exe tests\test_layout.py`
Expected: 7절의 "새 구조면 결과 로그·세션이 모두 data 에" 와 `app_base_dir` 넷이 `실패` (지금은 소스 폴더를 가리킨다).

- [ ] **Step 3: `run_routine.py`**

`app_base_dir()` 함수와 그 아래 두 줄(지금 120~133줄):
```python
def app_base_dir():
    """설정 파일과 로그를 둘 폴더.
    ...
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


# 경로는 이 스크립트(또는 exe)가 있는 폴더 기준으로 잡는다
BASE_DIR = app_base_dir()
RESULT_PATH = os.path.join(BASE_DIR, "run_routine_result.txt")
```
을 아래로 바꾼다:
```python
# 결과 로그를 둘 폴더. 옛 구조는 exe 옆, 새 구조는 ProgramData\AFTER MARKET\RPA\data (rpa_status 가 정한다)
BASE_DIR = status.data_dir()
RESULT_PATH = os.path.join(BASE_DIR, "run_routine_result.txt")
```
`run_self_check()` 의 두 줄:
```python
    log(f"실행 형태   : {'exe(패키징됨)' if getattr(sys, 'frozen', False) else '파이썬 스크립트'}")
    log(f"기준 폴더   : {BASE_DIR}")
```
을 바꾼다:
```python
    log(f"실행 형태   : {status.run_kind()}")
    log(f"프로그램 폴더: {status.program_dir()}")
    log(f"기록 폴더   : {BASE_DIR}{'  (새 구조)' if status.new_layout() else ''}")
```
`run_uia_check()` 의 한 줄:
```python
    log(f"실행 형태: {'exe(패키징됨)' if getattr(sys, 'frozen', False) else '파이썬 스크립트'}")
```
을 `    log(f"실행 형태: {status.run_kind()}")` 로 바꾼다.

- [ ] **Step 4: `web_runner.py`**

`_setup_playwright_browsers()` 안의
```python
    here = (os.path.dirname(os.path.abspath(sys.executable))
            if getattr(sys, "frozen", False)
            else os.path.dirname(os.path.abspath(__file__)))
```
를 `    here = status.program_dir()` 로, 같은 함수 뒤쪽의 `    if getattr(sys, "frozen", False):` 를 `    if status.packaged():` 로 바꾼다 (Nuitka 도 exe 라 기본 자리를 알려 줘야 한다). 그리고
```python
def app_base_dir():
    """PyInstaller 로 묶이면 __file__ 이 임시폴더를 가리키므로 exe 위치를 쓴다."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


BASE_DIR = app_base_dir()
```
를 아래로 바꾼다:
```python
# 결과 로그·화면 사진·세션을 둘 폴더. 옛 구조는 exe 옆, 새 구조는 ProgramData\AFTER MARKET\RPA\data
BASE_DIR = status.data_dir()
```

- [ ] **Step 5: `sms_watch.py`**

import 덩어리 끝 `from pywinauto import Application` 다음에 빈 줄 하나와 `import rpa_status` 를 더한다. 그리고
```python
def app_base_dir():
    """PyInstaller 로 묶이면 __file__ 이 임시폴더를 가리키므로 exe 위치를 쓴다."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


BASE_DIR = app_base_dir()
```
를 아래로 바꾼다:
```python
# 점검 기록을 둘 폴더. 옛 구조는 exe 옆, 새 구조는 ProgramData\AFTER MARKET\RPA\data
BASE_DIR = rpa_status.data_dir()
```
`cmd_check()` 의 두 줄:
```python
    log(f"  실행 형태: {'exe(패키징됨)' if getattr(sys, 'frozen', False) else '파이썬 스크립트'}")
    log(f"  기준 폴더: {BASE_DIR}")
```
을 바꾼다:
```python
    log(f"  실행 형태: {rpa_status.run_kind()}")
    log(f"  기록 폴더: {BASE_DIR}")
```

- [ ] **Step 6: `perform_login.py`**

```python
def app_base_dir():
    """로그를 둘 폴더. PyInstaller 로 묶인 상태에서는 exe 위치를 쓴다."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


```
(함수와 뒤 빈 줄 둘)을 지우고, `BASE_DIR = app_base_dir()` 를 `BASE_DIR = rpa_status.data_dir()   # 옛 구조는 exe 옆, 새 구조는 ProgramData\AFTER MARKET\RPA\data` 로 바꾼다. `sys` 는 이 함수에서만 썼으므로 (2026-09-29 확인) 맨 위 `import sys` 도 지운다.

- [ ] **Step 7: 시험이 통과하는지 본다**

Run: `.venv\Scripts\python.exe tests\test_layout.py` → Expected: `실패: 없음`
Run: `.venv\Scripts\python.exe tests\test_routine_modules.py` → Expected: `실패: 없음` (기존 107)
Run: `.venv\Scripts\python.exe tests\test_dashboard_modules.py` → Expected: `실패: 없음` (기존 100)
점검 줄도 눈으로 본다. `dist` 의 실제 결과 로그를 덮지 않게 임시 새 구조로 돌린다:
```powershell
cd D:\AX\RPA
$env:RPA_PROGRAMDATA = "$env:TEMP\rpa_layout_try"; New-Item -ItemType Directory -Force "$env:RPA_PROGRAMDATA\config" | Out-Null
$env:RPA_USER_CONFIG = "D:\AX\RPA\dist\RPA_UserConfig.json"
.venv\Scripts\python.exe run_routine.py --check
Remove-Item Env:RPA_PROGRAMDATA, Env:RPA_USER_CONFIG; Remove-Item -Recurse -Force "$env:TEMP\rpa_layout_try"
```
Expected: `실행 형태   : 파이썬 스크립트`, `기록 폴더   : …\rpa_layout_try\data  (새 구조)`, 마지막 `=== 점검 끝 (루틴은 실행하지 않았습니다) ===`

- [ ] **Step 8: 그래프 갱신, 커밋 (사용자가 허락했을 때만)**

```powershell
graphify update .
git add run_routine.py web_runner.py sms_watch.py perform_login.py tests/test_layout.py
git commit -m "구조: exe 쪽 네 파일은 rpa_status 의 기록 자리를 쓴다" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: 에이전트 파일 자리

설계 3절 표. 옛 구조의 자리는 **agent.py·secret.py 옆** (개발 PC 도 `dist\firebase\agent` 가 아니다 - Review Focus 2).

**Files:**
- Modify: `firebase/agent/secret.py:13-15` (`CONFIG_PATH`), import 에 `sys`
- Modify: `firebase/agent/agent.py:50-51` (`QUEUE_PATH`)
- Modify: `firebase/tests/test_agent.py` - 10절 (끝의 합계 출력 앞)

**Interfaces:**
- Consumes: `rpa_status.new_layout()`, `config_dir()`, `data_dir()` (Task 2)
- Produces: `secret.CONFIG_PATH`, `agent.QUEUE_PATH`, `agent.HISTORY_POS_PATH` (이름 그대로, 값만 새 규칙). `agent.log()` 의 기록 파일은 `QUEUE_PATH` 옆 그대로

- [ ] **Step 1: 실패하는 시험을 쓴다**

`firebase/tests/test_agent.py` 의 끝 `print(f"\n{COUNT - len(FAIL)}/{COUNT} 통과")` 바로 앞에 넣는다:
```python
print("\n10절 에이전트 파일 자리 (배포판 구조 1부)")
import subprocess  # noqa: E402

AGENT_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "agent"))
WHERE = "import json, agent, secret; print(json.dumps([agent.QUEUE_PATH, agent.HISTORY_POS_PATH, secret.CONFIG_PATH]))"


def where(extra):
    """새 프로세스에서 agent·secret 을 불러와 기본 자리를 받는다 (모듈 상수라 import 할 때 정해진다)."""
    env = {k: v for k, v in os.environ.items() if k not in ("RPA_AGENT_QUEUE", "RPA_AGENT_CONFIG", "RPA_PROGRAMDATA")}
    env.update(extra, PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, "-c", WHERE], cwd=AGENT_DIR, env=env, capture_output=True,
                       text=True, encoding="utf-8", timeout=60)
    if r.returncode != 0:
        return r.stderr[-300:]
    return [os.path.normpath(p) for p in json.loads(r.stdout.strip().splitlines()[-1])]


with tempfile.TemporaryDirectory() as d:
    got = where({"RPA_PROGRAMDATA": os.path.join(d, "none")})
    check(got == [os.path.join(AGENT_DIR, n) for n in ("queue.jsonl", "history_pos.txt", "agent_config.json")],
          f"옛 구조는 지금 자리 (에이전트 폴더, 개발 PC 도 dist 가 아니다) {got}")
    root = os.path.join(d, "AFTER MARKET", "RPA")
    os.makedirs(os.path.join(root, "config"))
    got = where({"RPA_PROGRAMDATA": root})
    check(got == [os.path.join(root, "data", "queue.jsonl"), os.path.join(root, "data", "history_pos.txt"),
                  os.path.join(root, "config", "agent_config.json")], f"새 구조는 data·config {got}")
    got = where({"RPA_PROGRAMDATA": root, "RPA_AGENT_QUEUE": os.path.join(d, "q", "queue.jsonl"),
                 "RPA_AGENT_CONFIG": os.path.join(d, "c.json")})
    check(got == [os.path.join(d, "q", "queue.jsonl"), os.path.join(d, "q", "history_pos.txt"),
                  os.path.join(d, "c.json")], f"시험용 환경변수가 새 구조보다 앞선다 {got}")
```

- [ ] **Step 2: 시험이 실패하는지 본다**

Run (`D:\AX\RPA\firebase` 에서): `python tests\test_agent.py`
Expected: 10절의 "새 구조는 data·config" 가 `실패` (지금은 에이전트 폴더를 가리킨다). 앞의 123건은 통과.

- [ ] **Step 3: `secret.py`**

import 에 `import sys` 를 `import os` 다음 줄에 더하고,
```python
# RPA_AGENT_CONFIG 는 시험용 - 통합 시험이 실제 설정을 덮어쓰지 않게 다른 파일을 가리킨다
CONFIG_PATH = os.environ.get("RPA_AGENT_CONFIG") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "agent_config.json")
```
를 아래로 바꾼다:
```python
_HERE = os.path.dirname(os.path.abspath(__file__))


def _default_config_path():
    """새 구조(설치 마법사가 %ProgramData%\\AFTER MARKET\\RPA\\config 를 만든 PC)면 거기, 아니면 이 파일 옆 (옛 자리).
    rpa_status 는 두 단계 위(저장소·배포 폴더 뿌리)에 있다 - agent.py 의 RPA_DIR 과 같은 자리. 단위 시험처럼
    agent.py 보다 먼저 불려도 찾게 여기서도 sys.path 에 넣는다."""
    root = os.path.abspath(os.path.join(_HERE, "..", ".."))
    if root not in sys.path:
        sys.path.insert(0, root)
    import rpa_status
    return os.path.join(rpa_status.config_dir() if rpa_status.new_layout() else _HERE, "agent_config.json")


# RPA_AGENT_CONFIG 는 시험용 - 통합 시험이 실제 설정을 덮어쓰지 않게 다른 파일을 가리킨다
CONFIG_PATH = os.environ.get("RPA_AGENT_CONFIG") or _default_config_path()
```

- [ ] **Step 4: `agent.py`**

```python
QUEUE_PATH = os.environ.get("RPA_AGENT_QUEUE") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "queue.jsonl")
```
를 아래로 바꾼다:
```python
def _data_dir():
    """에이전트 큐·위치·기록을 둘 폴더. 새 구조면 %ProgramData%\\AFTER MARKET\\RPA\\data, 아니면 이 파일 옆 (옛 자리).
    옛 구조에서 rpa_status.data_dir() 을 쓰지 않는 까닭: 개발 PC 는 그 값이 dist 라 큐가 엉뚱한 곳에 생긴다."""
    import rpa_status as st
    return st.data_dir() if st.new_layout() else os.path.dirname(os.path.abspath(__file__))


QUEUE_PATH = os.environ.get("RPA_AGENT_QUEUE") or os.path.join(_data_dir(), "queue.jsonl")
```

- [ ] **Step 5: 시험이 통과하는지 본다**

Run (`D:\AX\RPA\firebase` 에서): `python tests\test_agent.py` → Expected: `126/126 통과`

- [ ] **Step 6: 그래프 갱신, 커밋 (사용자가 허락했을 때만)**

```powershell
cd D:\AX\RPA
graphify update .
git add firebase/agent/secret.py firebase/agent/agent.py firebase/tests/test_agent.py
git commit -m "구조: 에이전트 설정·큐는 새 구조면 ProgramData, 옛 구조는 그대로" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: 에이전트가 켤 때 판을 점검해 올린다

설계 5절.

**Files:**
- Modify: `firebase/agent/agent.py` - `run()` 의 ERPia 위치 확인 덩어리 뒤, `pump()` 안
- Modify: `firebase/tests/integration.js` - heartbeat 확인 뒤

**Interfaces:**
- Consumes: `rpa_status.check_install()` (Task 3)
- Produces: RTDB `apps/rpa/live/{cid}/{pcId}/version` = `check_install()` 결과. 빈 목록·None 은 `clean_for_rtdb` 가 떼어 내므로 **`none` 이면 `version`·`changed` 필드가 없다** (Task 7 이 이걸 받는다). 에이전트 기록에 `판: …` 한 줄

- [ ] **Step 1: 실패하는 시험을 쓴다**

`firebase/tests/integration.js` 의 `check(typeof live?.launching === "boolean", …);` 줄 바로 뒤에 넣는다:
```js
const ver = live?.version;
check(ver && ["none", "ok", "mixed"].includes(ver.state) && typeof ver.checked_at === "string",
  `켤 때 판을 점검해 올린다 (${JSON.stringify(ver)})`);
check(/판: /.test(agentOut), "에이전트 기록에 판 줄이 남는다");
```

- [ ] **Step 2: 시험이 실패하는지 본다**

Run (`D:\AX\RPA\firebase\tests`, emu_env 를 읽은 창):
`firebase emulators:exec --config ../firebase.json --only auth,database,firestore --project rpa-test-f02e0 "node integration.js"`
Expected: 새 두 줄이 `실패`, 나머지 30건 통과.

- [ ] **Step 3: 구현**

`run()` 에서 ERPia 위치를 확인하는 `try: … except Exception as e: log(f"ERPia 위치를 확인하지 못했습니다 ({type(e).__name__})")` 덩어리 바로 뒤에 넣는다:
```python
    # 판: 프로그램 폴더를 판 목록(manifest.json)과 맞춰 PC 현황에 올린다 (배포판 구조 1부 5절).
    # 파일은 업데이트나 손으로 넣을 때만 바뀌고 둘 다 에이전트를 다시 켜므로 켤 때 한 번이면 된다. 예외를 내지 않는다
    install = st.check_install()
    detail = {"mixed": f", 다른 파일 {install['changed_count']}개: {', '.join(install['changed'])}",
              "error": f", {install.get('error')}"}.get(install["state"], "")
    log(f"판: {install['version'] or '없음'} ({install['state']}{detail})")
```
`pump()` 안의 `snap["launching"] = bool(dash.launch_state())` 줄 바로 뒤에 넣는다:
```python
                snap["version"] = install      # 켤 때 한 번 잰 판 (바뀌지 않으니 비교 body 에는 안 넣는다)
```

- [ ] **Step 4: 시험이 통과하는지 본다**

Run: 위와 같은 `integration.js` → Expected: 끝 줄 `통합 시험 32/32 통과`
Run (`D:\AX\RPA\firebase` 에서): `python tests\test_agent.py` → Expected: `126/126 통과`

- [ ] **Step 5: 그래프 갱신, 커밋 (사용자가 허락했을 때만)**

```powershell
cd D:\AX\RPA
graphify update .
git add firebase/agent/agent.py firebase/tests/integration.js
git commit -m "에이전트: 켤 때 판을 점검해 live.version 으로 올린다" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: 화면 "판" 칸

설계 6절. 상태 카드는 상태색으로 채워지고 글자색이 그 색을 따르므로, 섞임은 색이 아니라 글자로 알린다.

**Files:**
- Modify: `firebase/web/rpa.js:341-351` (`paintTiles` 의 `hero-side`), 그 앞에 `verStat()`
- Modify: `firebase/tests/check_web.py` - 10절 (끝의 `check(not errors, …)` 앞)

**Interfaces:**
- Consumes: `live.version` (Task 6) - `{version?, state, changed?, changed_count, checked_at, error?}`. 옛 에이전트는 없다
- Produces: `#hero-side` 안 세 번째 칸, 값 `#ver`, 마우스 글은 그 칸(`.stat`)의 `title`

- [ ] **Step 1: 실패하는 시험을 쓴다**

`firebase/tests/check_web.py` 의 `check(not errors, f"페이지 오류 없음 {errors[:2]}")` 바로 앞(9절 끝의 로그아웃 다음)에 넣는다:
```python
    print("10절 판 표시")
    login(page, "admin@t.local")
    page.wait_for_selector("#ver")
    check(page.text_content("#ver").strip() == "없음" and page.query_selector("#hero .stats #ver") is not None,
          "판 정보가 없으면 (옛 에이전트) 없음, 자리는 상태 띠 오른쪽")

    def show_ver(v, want):
        db_patch(LIVE, {"version": v})
        page.wait_for_function(f"document.getElementById('ver')?.textContent.trim() === {json.dumps(want)}",
                               timeout=5000)
        return page.eval_on_selector("#ver", "e => e.closest('.stat').title")

    t = show_ver({"version": "2026.09.29-1", "state": "ok", "changed_count": 0, "checked_at": "2026-09-29T10:00:00"},
                 "2026.09.29-1")
    check(t == "", "맞음이면 판 번호만")
    t = show_ver({"version": "2026.09.29-1", "state": "mixed", "changed": ["rpa_status.py", "firebase/agent/agent.py"],
                  "changed_count": 2, "checked_at": "2026-09-29T10:00:00"}, "2026.09.29-1 · 다른 파일 2")
    check("rpa_status.py" in t and "firebase/agent/agent.py" in t, f"섞임이면 다른 파일을 마우스 글로 ({t})")
    t = show_ver({"version": "2026.09.29-1", "state": "mixed", "changed": [f"f{i}.txt" for i in range(10)],
                  "changed_count": 15, "checked_at": "2026-09-29T10:00:00"}, "2026.09.29-1 · 다른 파일 15")
    check("외 5개" in t, f"이름을 다 못 보냈으면 나머지 개수 ({t})")
    t = show_ver({"state": "error", "error": "ValueError: 판 목록 형식이 다릅니다", "changed_count": 0,
                  "checked_at": "2026-09-29T10:00:00"}, "확인 실패")
    check("형식" in t, f"확인 실패면 이유를 마우스 글로 ({t})")
    show_ver({"state": "none", "changed_count": 0, "checked_at": "2026-09-29T10:00:00"}, "없음")
    check(page.text_content("#ver").strip() == "없음", "목록이 없으면 없음")
    show_ver({"version": "<b>x</b>", "state": "mixed", "changed": ["<img src=x onerror=alert(1)>"], "changed_count": 1,
              "checked_at": "2026-09-29T10:00:00"}, "<b>x</b> · 다른 파일 1")
    check(page.locator("#hero-side img, #hero-side b").count() == 0, "판 이름·파일 이름은 글자로만 (이스케이프)")
    t = show_ver("이상한 값", "없음")
    check(page.text_content("#ver").strip() == "없음" and t == "", "version 이 객체가 아니어도 없음")
    db_patch(LIVE, {"version": None})
    page.wait_for_function("document.getElementById('ver')?.textContent.trim() === '없음'", timeout=5000)
    if os.environ.get("SHOT_DIR"):
        show_ver({"version": "2026.09.29-1", "state": "mixed", "changed": ["rpa_status.py"], "changed_count": 1,
                  "checked_at": "2026-09-29T10:00:00"}, "2026.09.29-1 · 다른 파일 1")
        for w in (1280, 400):
            page.set_viewport_size({"width": w, "height": 900}); page.wait_for_timeout(300)
            page.locator("#hero").screenshot(path=os.path.join(os.environ["SHOT_DIR"], f"hero_ver_{w}.png"))
        page.set_viewport_size({"width": 1280, "height": 720}); page.wait_for_timeout(300)
        db_patch(LIVE, {"version": None})
    page.click("#logout-btn"); page.wait_for_selector("#login:not(.hide)")
```

- [ ] **Step 2: 시험이 실패하는지 본다**

Run (`D:\AX\RPA\firebase\tests`, emu_env 를 읽은 창):
`firebase emulators:exec --config ../firebase.json --only auth,database,firestore,hosting --project rpa-test-f02e0 "D:\AX\RPA\.venv\Scripts\python.exe check_web.py"`
Expected: 10절에서 `#ver` 를 기다리다 시간 초과로 멈춘다.

- [ ] **Step 3: 구현**

`rpa.js` 의 `paintTiles()` 끝부분
```js
  $("hero-side").replaceChildren(...[
    ["연결", conn ? "정상" : (off == null ? "없음" : `끊김 ${ago(off)}`), "conn"],
    ["다음 자동 실행", sch?.enabled && sch.next_run_at ? when(sch.next_run_at) : "꺼짐", ""],
  ].map(([k, v, id]) => {
    const d = document.createElement("div"); d.className = "stat";
    d.innerHTML = `<span class="k">${k}</span><span class="v num"${id ? ` id="${id}"` : ""}>${esc(v)}</span>`;
    return d;
  }));
```
을 아래로 바꾼다:
```js
  const ver = verStat(live?.version);
  $("hero-side").replaceChildren(...[
    ["연결", conn ? "정상" : (off == null ? "없음" : `끊김 ${ago(off)}`), "conn", ""],
    ["다음 자동 실행", sch?.enabled && sch.next_run_at ? when(sch.next_run_at) : "꺼짐", "", ""],
    ["판", ver.text, "ver", ver.title],
  ].map(([k, v, id, title]) => {
    const d = document.createElement("div"); d.className = "stat";
    if (title) d.title = title;     // 속성으로 넣는다 (innerHTML 이 아니라 이스케이프가 필요 없다)
    d.innerHTML = `<span class="k">${k}</span><span class="v num"${id ? ` id="${id}"` : ""}>${esc(v)}</span>`;
    return d;
  }));
```
`paintTiles()` 바로 앞에 넣는다:
```js
// live.version → 상태 카드 "판" 칸 글자와 마우스를 올리면 보이는 글 (배포판 구조 1부 6절).
// 옛 에이전트는 version 을 안 올리고, 목록이 없는 판(none)은 version·changed 필드가 빠진 채 온다
function verStat(v) {
  if (!v || typeof v !== "object") return { text: "없음", title: "" };
  const name = typeof v.version === "string" ? v.version : "";
  if (v.state === "ok" && name) return { text: name, title: "" };
  if (v.state === "mixed") {
    const list = Array.isArray(v.changed) ? v.changed.filter((x) => typeof x === "string") : [];
    const n = Number(v.changed_count) || list.length;
    const more = n > list.length ? ` 외 ${n - list.length}개` : "";
    return { text: `${name || "?"} · 다른 파일 ${n}`, title: list.length ? `판 목록과 다른 파일: ${list.join(", ")}${more}` : "" };
  }
  if (v.state === "error") return { text: "확인 실패", title: typeof v.error === "string" ? v.error : "" };
  return { text: "없음", title: "" };
}
```

- [ ] **Step 4: 시험이 통과하는지 본다**

Run: Step 2 와 같은 `check_web.py` (앞에 `$env:SHOT_DIR = "$env:TEMP\claude\hero_shot"; New-Item -ItemType Directory -Force $env:SHOT_DIR | Out-Null`)
Expected: `236/236 통과` (기존 228 + 10절 8건). 그리고 `hero_ver_1280.png`·`hero_ver_400.png` 를 Read 로 열어 세 칸이 겹치거나 넘치지 않는지 눈으로 본다. 400px 에서 줄이 바뀌는 건 괜찮고, 글자가 잘리거나 카드 밖으로 나가면 고친다.

- [ ] **Step 5: 올리기 - 사용자에게 묻고 나서**

옛 에이전트는 `version` 이 없어 `없음` 으로 보일 뿐이라 언제 올려도 된다. 사용자가 좋다고 하면:
```powershell
cd D:\AX\RPA\firebase
firebase deploy --only hosting --config firebase.json
```

- [ ] **Step 6: 그래프 갱신, 커밋 (사용자가 허락했을 때만)**

```powershell
cd D:\AX\RPA
graphify update .
git add firebase/web/rpa.js firebase/tests/check_web.py
git commit -m "화면: 상태 카드에 판 칸 (섞임은 글자·마우스 글로)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: 배포판 입력과 빌드 스크립트

설계 8절.

**Files:**
- Create: `release/RPA_UserConfig.template.json`, `release/배포안내.txt`, `release/클라우드_안내.txt`
- Create (저장소 밖, 한 번만): `D:\AX\runtime\python\`, `D:\AX\runtime\ms-playwright\`
- Create: `tools/build_release.py`, `tests/test_build_release.py`

**Interfaces:**
- Consumes: `rpa_status.MANIFEST_NAME`, `MANIFEST_FORMAT`, `file_digest`, `check_install` (Task 3). Nuitka 옵션·결론 (Task 1)
- Produces (`tools/build_release.py`): `next_version(out_root, today) -> str`, `collect(out_dir, exe_dir, repo=REPO, runtime_root=RUNTIME_ROOT) -> list[str]` (판 목록 대상 상대 경로), `write_manifest(out_dir, version, builder, program) -> dict`, `make_zip(out_dir, zip_path) -> None`, `template_problems(cfg) -> list[str]`, `verify_zip(zip_path, man, program, others) -> list[str]`, `found_marker(out: bytes, marker: str) -> bool`, `smoke_check(zip_path, timeout=180) -> list[str]`, `build_exes(builder, work_dir) -> str`, `main(argv=None) -> int`. 상수 `EXES`, `PROGRAM_FILES`, `OTHER_FILES`, `RUNTIME_DIRS`, `FORBIDDEN`, `MARKERS`, `NUITKA_COMMON`, `NUITKA_EXTRA`

- [ ] **Step 1: 배포판 입력을 저장소·런타임 폴더로 옮긴다**

빈 배포 틀은 2026-09-28 에 만든 새 업체용 압축 안의 것을 그대로 쓴다 (이미 비어 있다). 꺼내면서 비었는지 확인한다:
```powershell
cd D:\AX\RPA
New-Item -ItemType Directory -Force release | Out-Null
.venv\Scripts\python.exe -c "import json,zipfile; z=zipfile.ZipFile(r'D:\AX\배포_20260928_3_새업체.zip'); b=z.read('배포_20260928_3/RPA_UserConfig.json'); d=json.loads(b.decode('utf-8')); assert d['LogIn']=={'AdminCode':'','ID':'','PW':''}; assert all(s.get('ID','')=='' and s.get('PW','')=='' for s in d['Sites'].values() if isinstance(s,dict)); assert b'dpapi:' not in b; open(r'release\RPA_UserConfig.template.json','wb').write(b); print('ok', len(b))"
Copy-Item "D:\AX\배포_20260928_3\배포안내.txt" release\ -Force
Copy-Item "D:\AX\배포_20260928_3\클라우드_안내.txt" release\ -Force
robocopy "D:\AX\배포_20260928_3\python" "D:\AX\runtime\python" /E /NFL /NDL /NJH /NJS
robocopy "D:\AX\배포_20260928_3\ms-playwright" "D:\AX\runtime\ms-playwright" /E /NFL /NDL /NJH /NJS
D:\AX\runtime\python\python.exe --version
```
기대: `ok 3xxx`, robocopy 종료 코드 0~7 (복사 성공), `Python 3.14.7`. 두 안내 문서는 CP949 그대로 둔다.

- [ ] **Step 2: 실패하는 시험을 쓴다**

`tests/test_build_release.py` 를 Write 로 만든다:
```python
"""빌드 스크립트 시험 - exe 는 만들지 않고 가짜 입력으로 판 번호·모으기·판 목록·압축·검사를 돌린다.

    .venv\\Scripts\\python.exe tests\\test_build_release.py
"""
import datetime
import hashlib
import json
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.stdout.reconfigure(encoding="utf-8")

import build_release as br  # noqa: E402
import rpa_status as st  # noqa: E402

fails = []
_no = [0]


def check(name, cond, detail=""):
    _no[0] += 1
    mark = "통과" if cond else "실패"
    print(f"  {_no[0]:2d}. [{mark}] {name}" + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(f"{_no[0]}. {name} {detail}")


def finish():
    print()
    print(f"실패: {'없음' if not fails else fails}")
    sys.exit(1 if fails else 0)


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data if isinstance(data, bytes) else data.encode("utf-8"))


tmp = tempfile.mkdtemp(prefix="rpa_build_")
repo, runtime = os.path.join(tmp, "repo"), os.path.join(tmp, "runtime")
exe_dir, out_root = os.path.join(tmp, "exe"), os.path.join(tmp, "out")
BLANK = {"LogIn": {"AdminCode": "", "ID": "", "PW": ""}, "Sites": {"SITE1": {"URL": "https://x", "ID": "", "PW": ""}}}
for rel, src in br.PROGRAM_FILES + br.OTHER_FILES:
    body = json.dumps(BLANK) if src.endswith(".json") else f"{rel} 내용\r\n".encode("cp949")
    write(os.path.join(repo, *src.split("/")), body)
for exe in br.EXES:
    write(os.path.join(exe_dir, exe), b"MZ fake " + exe.encode())
write(os.path.join(runtime, "python", "Lib", "__pycache__", "os.cpython-314.pyc"), b"pyc")   # 내장 파이썬엔 원래 있다
write(os.path.join(runtime, "ms-playwright", "chromium-1234", "chrome.exe"), b"chrome")
others = [rel for rel, _ in br.OTHER_FILES]

# ---------------------------------------------------------------------------
print("=== 1. 판 번호 ===")
day = datetime.date(2026, 9, 29)
check("첫 판은 -1", br.next_version(out_root, day) == "2026.09.29-1")
os.makedirs(os.path.join(out_root, "배포_2026.09.29-1"))
write(os.path.join(out_root, "배포_2026.09.29-2.zip"), b"")
check("그날 있는 폴더·압축의 다음 번호", br.next_version(out_root, day) == "2026.09.29-3")
check("날이 바뀌면 다시 1", br.next_version(out_root, datetime.date(2026, 9, 30)) == "2026.09.30-1")

# ---------------------------------------------------------------------------
print("=== 2. 모으기와 판 목록 ===")
out_dir = os.path.join(out_root, "배포_2026.09.29-3")
program = br.collect(out_dir, exe_dir, repo=repo, runtime_root=runtime)
check("판 목록 대상은 exe 둘과 프로그램 파일",
      set(program) == set(br.EXES) | {rel for rel, _ in br.PROGRAM_FILES}, str(program))
man = br.write_manifest(out_dir, "2026.09.29-3", "nuitka 4.2.2 · python 3.14.7", program)
check("형식·판 번호·빌더", man["format"] == st.MANIFEST_FORMAT and man["version"] == "2026.09.29-3"
      and man["builder"] == "nuitka 4.2.2 · python 3.14.7")
check("문서·배포 틀은 판 목록에 없다", not set(others) & set(man["files"]))
bat = "firebase/agent/에이전트_시작.bat"
check("한글 파일 이름도 지문", man["files"][bat]["sha256"]
      == hashlib.sha256(f"{bat} 내용\r\n".encode("cp949")).hexdigest())
check("런타임은 이름표만", man["runtime"]["ms-playwright"] == ["chromium-1234"] and "python" in man["runtime"])
check("만든 판은 에이전트의 판 점검에서 ok", st.check_install(out_dir)["state"] == "ok", str(st.check_install(out_dir)))
try:
    br.collect(out_dir, exe_dir, repo=repo, runtime_root=runtime)
    ok = False
except FileExistsError:
    ok = True
check("이미 있는 판 폴더는 덮어쓰지 않는다", ok)

# ---------------------------------------------------------------------------
print("=== 3. 압축과 검사 ===")
zip_path = out_dir + ".zip"
br.make_zip(out_dir, zip_path)
with zipfile.ZipFile(zip_path) as z:
    names = z.namelist()
check("압축 맨 위 폴더는 판 폴더 이름", all(n.startswith("배포_2026.09.29-3/") for n in names))
check("한글 이름이 압축에서 깨지지 않는다", f"배포_2026.09.29-3/{bat}" in names)
check("깨끗한 판은 문제 없음 (런타임 안 __pycache__ 는 괜찮다)", br.verify_zip(zip_path, man, program, others) == [],
      str(br.verify_zip(zip_path, man, program, others)))


def variant(name, change):
    """out_dir 사본을 고쳐 압축하고 검사 결과를 돌려준다."""
    d = os.path.join(out_root, name)
    shutil.copytree(out_dir, d)
    change(d)
    br.make_zip(d, d + ".zip")
    return br.verify_zip(d + ".zip", man, program, others)


p = variant("배포_junk", lambda d: [write(os.path.join(d, "firebase", "agent", "queue.jsonl"), b""),
                                     write(os.path.join(d, "__pycache__", "rpa_status.cpython-314.pyc"), b""),
                                     write(os.path.join(d, "run_routine_result.txt"), b""),
                                     write(os.path.join(d, "sessions", "SITE1.json"), b"{}")])
check("찌꺼기(큐·__pycache__·결과 로그·세션)는 문제로 잡는다",
      all(any(k in x for x in p) for k in ("queue.jsonl", "__pycache__", "run_routine_result.txt", "sessions")), str(p))
p = variant("배포_leak", lambda d: write(os.path.join(d, "RPA_UserConfig.json"),
                                          json.dumps({"LogIn": {"AdminCode": "a", "ID": "b", "PW": "진짜비번"}})))
check("로그인이 든 배포 틀은 문제로 잡고, 값은 찍지 않는다",
      any("LogIn.PW" in x for x in p) and not any("진짜비번" in x for x in p), str(p))
p = variant("배포_tamper", lambda d: write(os.path.join(d, "rpa_status.py"), b"changed"))
check("지문이 다른 파일은 문제로 잡는다", any("지문 다름: rpa_status.py" in x for x in p), str(p))
p = variant("배포_extra", lambda d: write(os.path.join(d, "memo.txt"), b"x"))
check("모은 목록에 없는 파일은 문제로 잡는다", any("memo.txt" in x for x in p), str(p))

# ---------------------------------------------------------------------------
print("=== 4. exe 출력의 끝 줄 표지 ===")
check("UTF-8 출력에서 찾는다", br.found_marker("… === 점검 끝 (루틴은 …) ===\n".encode("utf-8"), "=== 점검 끝"))
check("CP949 출력에서 찾는다", br.found_marker("  쓸 수 있는 Action: login\r\n".encode("cp949"), "쓸 수 있는 Action"))
check("없으면 못 찾는다", not br.found_marker(b"Traceback ...", "=== 점검 끝"))

finish()
```

- [ ] **Step 3: 시험이 실패하는지 본다**

Run: `.venv\Scripts\python.exe tests\test_build_release.py`
Expected: `ModuleNotFoundError: No module named 'build_release'`

- [ ] **Step 4: 구현**

`tools/build_release.py` 를 Write 로 만든다. `NUITKA_COMMON`·`NUITKA_EXTRA` 는 Task 1 Step 8 에 적은 옵션으로 맞춘다 (아래는 Task 1 Step 3 그대로). Task 1 결론이 PyInstaller 면 `--builder` 기본값을 `"pyinstaller"` 로 한다.
```python
r"""배포판을 만든다 (배포판 구조 1부 8절, docs/superpowers/specs/2026-09-29-release-layout-design.md).

    .venv\Scripts\python.exe tools\build_release.py [--builder nuitka|pyinstaller] [--to-dist]

1. 두 exe 를 만든다 (build\release 에)
2. 정해 둔 파일만 D:\AX\배포_<판 번호>\ 에 모은다
3. 판 목록(manifest.json)을 쓴다
4. D:\AX\배포_<판 번호>.zip 으로 압축한다 (맨 위 폴더도 같은 이름 - D:\AX 에 풀면 바로 가기가 맞는다)
5. 스스로 확인한다: 압축 목록·지문·들어가면 안 되는 파일·빈 배포 틀, 풀어서 두 exe --check
비밀번호·쿠키·서비스 계정 키는 어떤 경우에도 배포판에 들어가지 않는다 (5번이 막는다).
"""
import argparse
import datetime
import fnmatch
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)
import rpa_status as st  # noqa: E402

OUT_ROOT = r"D:\AX"
RUNTIME_ROOT = r"D:\AX\runtime"           # python\·ms-playwright\ (처음 한 번 배포_20260928_3 에서 복사)
RUNTIME_DIRS = ("python", "ms-playwright")
EXES = {"ERPia_RPA.exe": "run_routine.py", "Prepare_RPA.exe": "web_runner.py"}
# (배포판 안 자리, 저장소 안 원본). exe 와 함께 판 목록에 지문으로 들어간다
PROGRAM_FILES = [
    ("Run_All.bat", "Run_All.bat"),
    ("rpa_status.py", "rpa_status.py"),
    ("rpa_dashboard.py", "rpa_dashboard.py"),
    ("firebase/agent/agent.py", "firebase/agent/agent.py"),
    ("firebase/agent/fb.py", "firebase/agent/fb.py"),
    ("firebase/agent/secret.py", "firebase/agent/secret.py"),
    ("firebase/agent/에이전트_시작.bat", "firebase/agent/에이전트_시작.bat"),
]
# 판 목록에 넣지 않는 것 (문서·빈 배포 틀). 업데이트가 건드리지 않는다
OTHER_FILES = [
    ("배포안내.txt", "release/배포안내.txt"),
    ("클라우드_안내.txt", "release/클라우드_안내.txt"),
    ("RPA_UserConfig.json", "release/RPA_UserConfig.template.json"),
]
# 런타임 폴더 밖에서 나오면 안 되는 것 (경로 조각마다 맞춰 본다). 내장 파이썬 안의 __pycache__ 는 원래 있다
FORBIDDEN = ["__pycache__", "*.pyc", "*_result.txt", "sms_watch_log.txt", "web_*.png", "sessions",
             "agent_config.json", "queue.jsonl", "history_pos.txt", "에이전트_기록.txt", "*.old", "*.bak",
             "serviceAccountKey.json"]
MARKERS = {"ERPia_RPA.exe": "=== 점검 끝", "Prepare_RPA.exe": "쓸 수 있는 Action"}   # --check 의 끝 줄
EXCLUDE = ["numpy", "yaml", "scipy", "pandas", "torch", "cv2", "matplotlib", "networkx", "graphify"]
NUITKA_COMMON = (["--onefile", "--assume-yes-for-downloads", "--windows-console-mode=force", "--remove-output",
                  "--include-package=comtypes", "--include-package=pywinauto", "--include-module=win32timezone"]
                 + [f"--nofollow-import-to={m}" for m in EXCLUDE])
NUITKA_EXTRA = {"ERPia_RPA.exe": [], "Prepare_RPA.exe": ["--include-package=playwright", "--include-package-data=playwright"]}


def next_version(out_root, today):
    """YYYY.MM.DD-N. 그날 이미 있는 배포_<날짜>-N 폴더·압축의 다음 번호."""
    day = today.strftime("%Y.%m.%d")
    used = [int(m.group(1)) for name in (os.listdir(out_root) if os.path.isdir(out_root) else [])
            if (m := re.fullmatch(rf"배포_{re.escape(day)}-(\d+)(\.zip)?", name))]
    return f"{day}-{max(used, default=0) + 1}"


def _copy(src, out_dir, rel):
    dst = os.path.join(out_dir, *rel.split("/"))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)


def collect(out_dir, exe_dir, repo=REPO, runtime_root=RUNTIME_ROOT):
    """배포판 폴더를 모은다. 판 목록에 들어갈 상대 경로('/')를 돌려준다. 이미 있으면 멈춘다 (덮어쓰지 않는다)."""
    if os.path.exists(out_dir):
        raise FileExistsError(out_dir)
    os.makedirs(out_dir)
    program = []
    for name in EXES:
        _copy(os.path.join(exe_dir, name), out_dir, name)
        program.append(name)
    for rel, src in PROGRAM_FILES:
        _copy(os.path.join(repo, *src.split("/")), out_dir, rel)
        program.append(rel)
    for rel, src in OTHER_FILES:
        _copy(os.path.join(repo, *src.split("/")), out_dir, rel)
    for d in RUNTIME_DIRS:
        shutil.copytree(os.path.join(runtime_root, d), os.path.join(out_dir, d))
    return program


def _runtime_python(out_dir):
    """배포판 내장 파이썬 판 ("3.14.7"). 못 알아내면 "?"."""
    try:
        r = subprocess.run([os.path.join(out_dir, "python", "python.exe"), "-c",
                            "import platform; print(platform.python_version())"],
                           capture_output=True, text=True, timeout=30)
        return r.stdout.strip() or "?"
    except Exception:
        return "?"


def write_manifest(out_dir, version, builder, program):
    """manifest.json 을 쓰고 그 내용을 돌려준다."""
    man = {
        "format": st.MANIFEST_FORMAT,
        "version": version,
        "built_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "builder": builder,
        "runtime": {"python": _runtime_python(out_dir),
                    "ms-playwright": sorted(os.listdir(os.path.join(out_dir, "ms-playwright")))},
        "files": {rel: st.file_digest(os.path.join(out_dir, *rel.split("/"))) for rel in program},
    }
    with open(os.path.join(out_dir, st.MANIFEST_NAME), "w", encoding="utf-8", newline="\n") as f:
        json.dump(man, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return man


def make_zip(out_dir, zip_path):
    """out_dir 를 압축한다. 맨 위 폴더는 out_dir 이름. 한글 이름은 UTF-8 표시로 들어간다 (zipfile 이 알아서)."""
    top = os.path.basename(os.path.normpath(out_dir))
    tmp = zip_path + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for base, dirs, files in os.walk(out_dir):
            dirs.sort()
            for name in sorted(files):
                full = os.path.join(base, name)
                z.write(full, f"{top}/{os.path.relpath(full, out_dir).replace(os.sep, '/')}")
    os.replace(tmp, zip_path)


def template_problems(cfg):
    """배포 틀에 비밀이 있으면 문제. 로그인(AdminCode·ID·PW)과 사이트 ID·PW 는 비어야 한다. 값은 찍지 않는다."""
    out = []
    login = cfg.get("LogIn") if isinstance(cfg.get("LogIn"), dict) else {}
    out += [f"배포 틀의 LogIn.{k} 가 비어 있지 않습니다" for k in ("AdminCode", "ID", "PW") if login.get(k)]
    for name, site in (cfg.get("Sites") or {}).items():
        if isinstance(site, dict):
            out += [f"배포 틀의 Sites.{name}.{k} 가 비어 있지 않습니다" for k in ("ID", "PW") if site.get(k)]
    return out


def verify_zip(zip_path, man, program, others):
    """압축 자체를 본다. 문제 목록 (빈 목록이면 통과)."""
    problems = []
    with zipfile.ZipFile(zip_path) as z:
        names = [n for n in z.namelist() if not n.endswith("/")]
        top = names[0].split("/", 1)[0] if names else ""
        inside = {n.split("/", 1)[1] for n in names if "/" in n}
        for rel in program:
            if rel not in inside:
                problems.append(f"없음: {rel}")
            elif hashlib.sha256(z.read(f"{top}/{rel}")).hexdigest() != man["files"][rel]["sha256"]:
                problems.append(f"지문 다름: {rel}")
        ours = {rel for rel in inside if rel.split("/")[0] not in RUNTIME_DIRS}
        for rel in sorted(ours):
            if any(fnmatch.fnmatch(part, pat) for part in rel.split("/") for pat in FORBIDDEN):
                problems.append(f"들어가면 안 되는 파일: {rel}")
        extra = ours - set(program) - set(others) - {st.MANIFEST_NAME}
        problems += [f"모은 목록에 없는 파일: {rel}" for rel in sorted(extra)]
        if "RPA_UserConfig.json" in inside:
            problems += template_problems(json.loads(z.read(f"{top}/RPA_UserConfig.json").decode("utf-8-sig")))
        else:
            problems.append("없음: RPA_UserConfig.json")
    return problems


def found_marker(out, marker):
    """exe 출력(bytes)에 끝 줄 표지가 있나. PyInstaller exe 는 CP949 로 찍고 Nuitka 는 다를 수 있어 둘 다 본다."""
    return marker.encode("utf-8") in out or marker.encode("cp949") in out


def smoke_check(zip_path, timeout=180):
    """압축을 임시 폴더에 풀고 두 exe 를 임시 설정으로 --check 한다. 끝 줄이 찍히면 통과
    (빈 설정이라 나오는 '문제' 줄과 종료 코드는 보지 않는다)."""
    problems = []
    with tempfile.TemporaryDirectory(prefix="rpa_release_", ignore_cleanup_errors=True) as tmp:
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(tmp)
        top = os.path.join(tmp, os.listdir(tmp)[0])
        cfg = os.path.join(tmp, "cfg", "RPA_UserConfig.json")
        os.makedirs(os.path.dirname(cfg))
        shutil.copy2(os.path.join(top, "RPA_UserConfig.json"), cfg)
        env = dict(os.environ, RPA_USER_CONFIG=cfg, RPA_PROGRAMDATA=os.path.join(tmp, "programdata"),
                   RPA_STATUS_DIR=os.path.join(tmp, "status"), RPA_UNATTENDED="1")
        for exe, marker in MARKERS.items():
            try:
                r = subprocess.run([os.path.join(top, exe), "--check"], cwd=top, env=env,
                                   capture_output=True, timeout=timeout)
                out = r.stdout + r.stderr
                if not found_marker(out, marker):
                    problems.append(f"{exe} --check 가 끝까지 가지 않았습니다: {out[-300:].decode('cp949', 'replace')}")
            except subprocess.TimeoutExpired:
                problems.append(f"{exe} --check 가 {timeout}초 안에 끝나지 않았습니다")
    return problems


def build_exes(builder, work_dir):
    """두 exe 를 work_dir 에 만든다. 판 목록의 builder 칸 글자를 돌려준다 ("nuitka 4.2.2 · python 3.14.7")."""
    os.makedirs(work_dir, exist_ok=True)
    py = sys.executable
    if builder == "nuitka":
        for exe, entry in EXES.items():
            subprocess.run([py, "-m", "nuitka", *NUITKA_COMMON, *NUITKA_EXTRA[exe], f"--output-dir={work_dir}",
                            f"--output-filename={exe}", os.path.join(REPO, entry)], cwd=REPO, check=True)
        ver = subprocess.run([py, "-m", "nuitka", "--version"], capture_output=True, text=True,
                             check=True).stdout.split()[0]
    else:
        for spec in ("ERPia_RPA.spec", "Prepare_RPA.spec"):
            subprocess.run([py, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", work_dir,
                            "--workpath", os.path.join(work_dir, "pyi_work"), spec], cwd=REPO, check=True)
        ver = importlib.metadata.version("pyinstaller")
    return f"{builder} {ver} · python {platform.python_version()}"


def main(argv=None):
    ap = argparse.ArgumentParser(description="배포판을 만든다")
    ap.add_argument("--builder", choices=("nuitka", "pyinstaller"), default="nuitka")
    ap.add_argument("--to-dist", action="store_true",
                    help="두 exe 를 이 PC 의 dist 에도 복사한다 (설정 파일은 건드리지 않는다)")
    args = ap.parse_args(argv)
    version = next_version(OUT_ROOT, datetime.date.today())
    work = os.path.join(REPO, "build", "release")
    print(f"판 {version} 을 만듭니다 ({args.builder})")
    builder = build_exes(args.builder, work)
    out_dir = os.path.join(OUT_ROOT, f"배포_{version}")
    program = collect(out_dir, work)
    man = write_manifest(out_dir, version, builder, program)
    zip_path = out_dir + ".zip"
    make_zip(out_dir, zip_path)
    problems = verify_zip(zip_path, man, program, [rel for rel, _ in OTHER_FILES]) + smoke_check(zip_path)
    for p in problems:
        print("  문제:", p)
    if problems:
        print(f"배포판에 문제가 {len(problems)}건 있습니다. {zip_path} 를 쓰지 마세요")
        return 1
    if args.to_dist:
        for exe in EXES:
            shutil.copy2(os.path.join(out_dir, exe), os.path.join(REPO, "dist", exe))
        print("  dist 에 두 exe 를 복사했습니다 (설정 파일은 그대로)")
    print(f"판 {version}  {zip_path}  ({os.path.getsize(zip_path) // 2 ** 20}MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: 시험이 통과하는지 본다**

Run: `.venv\Scripts\python.exe tests\test_build_release.py` → Expected: `실패: 없음`

- [ ] **Step 6: 그래프 갱신, 커밋 (사용자가 허락했을 때만)**

커밋 전에 틀에 비밀이 없는지 한 번 더 본다: `git diff --cached release/RPA_UserConfig.template.json` 에서 `"PW": ""`, `"ID": ""`, `"AdminCode": ""` 만 보이는지.
```powershell
graphify update .
git add release tools/build_release.py tests/test_build_release.py
git commit -m "배포: 빌드 스크립트와 배포판 입력 (빈 틀·안내 문서)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: 첫 판 내기, 문서, 전달

설계 9절.

**Files:**
- Modify: `release/클라우드_안내.txt`, `release/배포안내.txt` (CP949 그대로)
- Modify: `docs/firebase-architecture.md`, `docs/superpowers/specs/2026-09-29-release-layout-design.md` (상태 줄)
- 메모리: `next-steps.md` 의 노트북 전달 목록

**Interfaces:**
- Consumes: Task 1~8 전부

- [ ] **Step 1: 안내 문서에 판을 적는다 (CP949 로 읽고 쓴다)**

`release/클라우드_안내.txt` 의 `■ 문제가 생기면` 바로 앞에 이 절을 넣는다:
```
■ 판 (배포판마다 번호가 있다)
    배포 폴더의 manifest.json 에 판 번호(예: 2026.09.29-1)와 프로그램 파일 목록이 있다.
    에이전트가 켤 때 이 목록과 실제 파일을 맞춰 보고, 대시보드 상태 카드의 '판' 칸에 보여 준다.
      판 번호만 보이면     파일이 모두 그 판이다
      '다른 파일 N'        몇 개가 다르다 (마우스를 올리면 파일 이름). 손으로 몇 개만 넣었거나 덮어쓰다 끊긴 것
      '없음'               manifest.json 이 없다 (옛 배포판)
    파일을 손으로 넘길 때는 manifest.json 도 같이 넘기고 에이전트를 다시 켠다.


```
`release/배포안내.txt` 의 `■ 1. 프로그램 폴더` 목록에서 `RPA_UserConfig.json` 줄 바로 뒤에 한 줄을 넣는다:
```
        manifest.json              판 번호와 프로그램 파일 목록 (지우지 말 것)
```
Edit 도구는 CP949 파일을 못 다루므로 파이썬으로 한다. 두 문서 모두 줄 끝이 CRLF 이고, 아래 두 기준 글은 각 문서에 한 번씩만 나온다 (2026-09-29 확인). Write 로 `build\edit_guides.py` 를 만든다:
```python
"""배포판 안내 문서(CP949, CRLF)에 판 설명을 넣는다. 두 번 돌리면 멈춘다 (같은 글이 이미 있으면)."""
NL = "\r\n"


def insert(path, anchor, text, after):
    s = open(path, encoding="cp949", newline="").read()
    assert s.count(anchor) == 1, (path, "기준 글이 한 번이 아니다")
    assert text.strip() not in s, (path, "이미 들어 있다")
    i = s.index(anchor) + (len(anchor) if after else 0)
    open(path, "w", encoding="cp949", newline="").write(s[:i] + text + s[i:])


insert(r"release\클라우드_안내.txt", "■ 문제가 생기면", NL.join([
    "■ 판 (배포판마다 번호가 있다)",
    "    배포 폴더의 manifest.json 에 판 번호(예: 2026.09.29-1)와 프로그램 파일 목록이 있다.",
    "    에이전트가 켤 때 이 목록과 실제 파일을 맞춰 보고, 대시보드 상태 카드의 '판' 칸에 보여 준다.",
    "      판 번호만 보이면     파일이 모두 그 판이다",
    "      '다른 파일 N'        몇 개가 다르다 (마우스를 올리면 파일 이름). 손으로 몇 개만 넣었거나 덮어쓰다 끊긴 것",
    "      '없음'               manifest.json 이 없다 (옛 배포판)",
    "    파일을 손으로 넘길 때는 manifest.json 도 같이 넘기고 에이전트를 다시 켠다.",
]) + NL * 3, after=False)
insert(r"release\배포안내.txt",
       "        RPA_UserConfig.json        사용자 설정 한 파일 (ERPia 로그인 · 물류 · 실행 모듈 · 프리페어 사이트 · ERPia 위치)" + NL,
       "        manifest.json              판 번호와 프로그램 파일 목록 (지우지 말 것)" + NL, after=True)
print("ok")
```
```powershell
cd D:\AX\RPA
.venv\Scripts\python.exe build\edit_guides.py
.venv\Scripts\python.exe -c "print(open(r'release\배포안내.txt',encoding='cp949').read().count('manifest.json'), open(r'release\클라우드_안내.txt',encoding='cp949').read().count('manifest.json'))"
```
Expected: `ok`, 그다음 `1 3`.

- [ ] **Step 2: 첫 판을 만든다**

```powershell
cd D:\AX\RPA
.venv\Scripts\python.exe tools\build_release.py
```
(Task 1 결론이 PyInstaller 면 `--builder pyinstaller`)
Expected: 마지막 줄 `판 2026.MM.DD-1  D:\AX\배포_2026.MM.DD-1.zip  (…MB)`, 종료 코드 0. `문제:` 줄이 하나라도 있으면 그 압축은 쓰지 않고 원인을 고친다.

- [ ] **Step 3: 실기 - 사용자가 관리자 PowerShell 에서**

압축을 임시 폴더에 풀고, 옛 구조로 로그인만 한 번 돌린다 (Task 1 Step 6 과 같은 "로그인만" 사본 설정):
```powershell
Expand-Archive "D:\AX\배포_<판 번호>.zip" "$env:TEMP\rpa_release_try" -Force
$env:RPA_USER_CONFIG = "$env:TEMP\rpa_probe_login.json"; $env:RPA_STATUS_DIR = "$env:TEMP\rpa_probe_status"
& "$env:TEMP\rpa_release_try\배포_<판 번호>\ERPia_RPA.exe"
```
기대: 로그인 성공, `run_routine_result.txt` 가 exe 옆(옛 구조)에 생긴다. 끝나면 `Remove-Item -Recurse $env:TEMP\rpa_release_try, $env:TEMP\rpa_probe_login.json`.

- [ ] **Step 4: 구조 문서**

`docs/firebase-architecture.md`:
- 3절 데이터 경로의 `apps/rpa/live/{cid}/{pcId}` 설명 `{ programs, modules, schedule, recent[20], heartbeat, host, server_time }` 에 `version` 을 더하고, 표 아래에 한 줄: "`version` 은 에이전트가 켤 때 잰 판 (`rpa_status.check_install()`, 배포판 구조 1부)."
- 7절(새 PC 이식)의 "지금 배포판은 `D:\AX\배포_20260928_3`" 을 "배포판은 `tools\build_release.py` 로 만든다 (`D:\AX\배포_<판 번호>`). 손으로 넘길 때는 `manifest.json` 도 같이" 로 바꾼다.
- 8절 시험 명령 덩어리에 `.venv\Scripts\python.exe tests\test_layout.py` 와 `.venv\Scripts\python.exe tests\test_build_release.py` 두 줄을 더하고, 시험 표에 두 줄: `| 배치·판 | 45 | 자리 찾기(새·옛 구조, PyInstaller·Nuitka), 판 점검, exe 쪽 모듈 자리 |`, `| 빌드 스크립트 | 20 | 판 번호·모으기·압축·찌꺼기·빈 틀·exe 출력 표지 |`. 에이전트 단위 123→126, 통합 30→32, 화면 228→236 으로 고친다 (실제로 돌린 건수와 다르면 실제 건수로).
설계 문서 맨 위 `**상태:**` 줄을 `**상태:** 구현됨 (2026-09-XX, 첫 판 2026.MM.DD-1)` 로 바꾼다.

- [ ] **Step 5: 이 PC 반영 - 사용자에게 묻고 나서**

RPA 가 돌고 있지 않을 때, 사용자가 좋다고 하면:
```powershell
Copy-Item "D:\AX\배포_<판 번호>\ERPia_RPA.exe", "D:\AX\배포_<판 번호>\Prepare_RPA.exe" D:\AX\RPA\dist\ -Force
```
그리고 사용자가 이 PC 의 에이전트를 다시 켠다 (agent.py·secret.py 를 새로 읽게). 대시보드 이 PC 의 판 칸은 `없음` 이 맞다 (개발 PC 는 판 목록이 없다).

- [ ] **Step 6: 노트북 전달 목록 고치기 (메모리)**

`C:\Users\20251216-003\.claude\projects\d--AX-RPA\memory\next-steps.md` 2번 항목의 파일 목록을 새 판 기준으로 바꾼다: `D:\AX\배포_<판 번호>\` 의 `ERPia_RPA.exe`, `Prepare_RPA.exe`, `Run_All.bat`, `rpa_status.py`, `rpa_dashboard.py`, `manifest.json` + `firebase\agent\` 의 `agent.py`, `fb.py`, `secret.py`, `에이전트_시작.bat` (10개). 넘기고 에이전트를 다시 켜면 대시보드에 판 번호가 보여야 한다.

- [ ] **Step 7: 전체 시험 한 바퀴**

"시험 돌리는 법" 의 명령을 모두 돌린다. Expected: 모두 `실패: 없음` / `N/N 통과`.

- [ ] **Step 8: 그래프 갱신, 커밋 (사용자가 허락했을 때만)**

```powershell
graphify update .
git add release docs/firebase-architecture.md docs/superpowers/specs/2026-09-29-release-layout-design.md
git commit -m "배포: 첫 판, 안내 문서에 판, 구조 문서" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
