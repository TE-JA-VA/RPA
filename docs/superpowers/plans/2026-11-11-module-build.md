# 조각 컴파일 빌드 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 우리 `.py` 를 파일마다 `.pyd` 로 컴파일하고 라이브러리는 묶음 하나로 실어, 파일 하나를 고친 뒤의 빌드를 30초 안쪽으로 줄인다. 옛 onefile 빌드는 그대로 남긴다.

**Architecture:** exe 셋은 내장 Python(`python\python314.dll`)을 같은 프로세스에서 켜는 작은 C 시작 파일이 된다. 시작 파일은 `app\_start.py` 를 실행하고, 이것이 `lib\`(라이브러리)와 `app\`(우리 `.pyd`)을 찾는 길에 넣은 뒤 exe 이름에 맞는 모듈의 `run_main()` 을 부른다. 라이브러리는 `lib.zip` 하나로 버전 목록에 들어가고 설치 마무리(`rpa_settings --after-install`)가 `lib\` 에 푼다.

**Tech Stack:** Python 3.14.7, Nuitka 4.2.2 (`--module`), Nuitka 가 받아 둔 zig (C 컴파일), Inno Setup 6, 윈도우 샌드박스.

**Spec:** [docs/superpowers/specs/2026-11-11-module-build-design.md](../specs/2026-11-11-module-build-design.md)

## Global Constraints

- 기본 빌드는 옛 방식 그대로다. 조각 방식은 `build_release.py --modules` 로만 켠다. `--onefile` 은 옛 방식을 뜻하는 이름으로 받아 준다 (지금 기본과 같다).
- `build/exe_cache` 와 옛 onefile 코드(`build_exes`·`nuitka_command`·`NUITKA_*`)를 지우거나 동작을 바꾸지 않는다.
- Python·Nuitka·라이브러리 버전을 올리지 않는다 (Nuitka 4.2.2, python 3.14.7).
- exe 이름 셋(`ERPia_RPA.exe`·`Prepare_RPA.exe`·`Prepare_Observer.exe`)·아이콘 파일 이름·시작 메뉴·`Run_All.bat`·설정 파일 자리는 그대로다.
- 조각 컴파일에도 `LDFLAGS=-march=x86_64` (`build_release.NUITKA_ENV`). 시작 파일도 일반 x86-64 로 만든다.
- 조각을 동시에 컴파일하지 않는다.
- 화면·기록에 보이는 글은 '버전' 이라 쓴다 ('판' 금지). 업무 서식 말투.
- 시험은 이 저장소 방식대로: `check(조건, "글")` 을 쓰는 스크립트, 끝에 `실패: 없음`. pytest 는 없다.
- 작업 폴더에 다른 세션의 미커밋 변경이 있다. 커밋에는 이 계획에서 고친 파일만 넣는다 (`git add <파일>` 로 하나씩).
- 버전 내보내기·hosting 배포·push 는 이 계획에 없다. 사용자가 말할 때만.
- `firebase/admin/update_signing_key.txt`·`serviceAccountKey.json` 은 읽지 않는다. 개발 PC 에 설치 파일을 돌리지 않는다 (샌드박스만).

## Review Focus

1. **`lib.zip` 안의 경로가 `lib\` 밖을 가리킨다** (`..\`·절대 경로) → 풀지 않고 실패로 끝난다. 밖에 파일이 생기지 않는다. (Task 4)
2. **풀다가 끊겼다** (전원·백신) → 표시 파일이 없으므로 다음 설치 마무리가 처음부터 다시 푼다. 반쯤 풀린 `lib\` 로 '다 됐다' 고 하지 않는다. (Task 4)
3. **`lib\` 가 없거나 조각이 빠진 채 exe 를 켠다** (백신 격리, 묶음을 못 푼 PC) → 파이썬 오류 추적 대신 한 줄 안내와 0 이 아닌 종료 코드. (Task 2)
4. **설치 경로의 공백·한글, 인자의 공백·따옴표** (`C:\Program Files\AFTER MARKET\RPA`, `--preset "① 지마켓"`) → 인자와 종료 코드가 그대로 전달된다. (Task 2)
5. **조각 버전에서 옛 버전으로 되돌린 뒤** `app\`·`lib\` 가 남아 있어도 옛 onefile exe 가 그대로 돈다. (Task 6 샌드박스)

---

## 파일 지도

| 파일 | 할 일 |
|---|---|
| `rpa_status.py` | `compiled_dir()` 더하고 `program_dir()` 가 쓴다 |
| `web_replay.py` | node 찾기가 `app\` 한 단계 위를 본다 |
| `run_routine.py`·`web_runner.py`·`rpa_observer.py` | 맨 아래 실행 부분을 `run_main()` 으로 |
| `app_start.py` (새 파일, 배포본에서는 `app\_start.py`) | 길 잡기 + exe 이름 → 모듈 `run_main()` |
| `tools/launcher.c` (새 파일) | 시작 파일 원본 |
| `rpa_settings.py` | `unpack_lib()`, `--after-install` 에서 부른다 |
| `tools/build_release.py` | `build_launchers`·`build_modules`·`build_lib_zip`·`--modules` |
| `tests/test_module_build.py` (새 파일) | 위 것들의 시험 |
| `tests/test_layout.py`·`tests/test_settings.py`·`tests/test_build_release.py` | 항목 더하기 |
| `tools/sandbox_inner.ps1` | 조각 버전일 때의 검사 |

---

### Task 1: 경로와 시작 함수

**Files:**
- Modify: `rpa_status.py:240-270`, `web_replay.py:52-54`, `run_routine.py` 맨 아래, `web_runner.py` 맨 아래, `rpa_observer.py` 맨 아래
- Test: `tests/test_layout.py`

**Interfaces:**
- Produces: `rpa_status.compiled_dir(compiled=None) -> str | None`, `run_routine.run_main() -> int | None`, `web_runner.run_main() -> int`, `rpa_observer.run_main() -> int`

- [ ] **Step 1: 실패하는 시험을 쓴다** (`tests/test_layout.py` 끝, 결과 줄 앞)

```python
class _C:                       # __compiled__ 흉내
    def __init__(self, d): self.containing_dir = d
check(st.compiled_dir(_C(r"C:\P\RPA")) == r"C:\P\RPA", "onefile: 조각 폴더가 곧 프로그램 폴더")
check(st.compiled_dir(_C(r"C:\P\RPA\app")) == r"C:\P\RPA", "조각 방식: app 의 한 단계 위")
check(st.compiled_dir(_C(r"C:\P\RPA\APP")) == r"C:\P\RPA", "폴더 이름 대소문자를 가리지 않는다")
check(st.compiled_dir(_C(r"C:\P\app\RPA")) == r"C:\P\app\RPA", "끝 폴더가 app 일 때만")
for mod in ("run_routine", "web_runner", "rpa_observer"):
    src = open(os.path.join(REPO, mod + ".py"), encoding="utf-8").read()
    check("\ndef run_main(" in src and src.rstrip().endswith("sys.exit(run_main())"), f"{mod}: run_main() 이 있고 직접 실행도 그것을 부른다")
```

- [ ] **Step 2: 돌려서 실패를 확인한다**

Run: `.venv\Scripts\python.exe tests\test_layout.py`
Expected: 위 항목들이 `실패` (`compiled_dir` 없음).

- [ ] **Step 3: `rpa_status.compiled_dir(compiled=None)` 을 만들고 `program_dir()` 의 Nuitka 가지가 쓴다**

`compiled` 가 없으면 `_nuitka()`. 컴파일된 것이 아니면 `None`. `containing_dir` 이 없으면 지금처럼 `sys.argv[0]` 의 폴더. 끝 폴더 이름이 `app` 이면 (대소문자 무시) 그 위 폴더.

- [ ] **Step 4: `web_replay.py:52-54` 가 같은 규칙을 쓴다**

`web_replay` 가 이미 `rpa_status` 를 import 하면 `compiled_dir()` 을 부른다. 아니면 그 자리에 같은 규칙 한 줄 (import 를 새로 더하지 않는다 - exe 재료가 바뀐다).

- [ ] **Step 5: 세 파일의 `if __name__ == "__main__":` 안을 `run_main()` 으로 옮긴다**

지금 그 안의 줄을 그대로 함수로 옮기고 종료 코드를 돌려준다 (예외를 다시 던지는 것도 그대로). 아래는 `if __name__ == "__main__":` + `sys.exit(run_main())` 두 줄만 남긴다. 동작은 바뀌지 않는다.

- [ ] **Step 6: 시험을 돌린다**

Run: `.venv\Scripts\python.exe tests\test_layout.py` → `실패: 없음`
Run: `.venv\Scripts\python.exe web_runner.py --check` → 끝 줄 `쓸 수 있는 Action`
Run: `.venv\Scripts\python.exe rpa_observer.py --check` → 끝 줄 `옵저버 점검 끝`

- [ ] **Step 7: 커밋** - `rpa_status.py web_replay.py run_routine.py web_runner.py rpa_observer.py tests/test_layout.py`, 글: `조각 빌드 준비 - 프로그램 폴더 찾기가 app 한 단계 위를 보고, 실행 부분을 run_main() 으로`

---

### Task 2: 시작 파일

**Files:**
- Create: `tools/launcher.c`, `app_start.py`, `tests/test_module_build.py`
- Modify: `tools/build_release.py`

**Interfaces:**
- Consumes: `run_main()` (Task 1), `build_release.icon_resources(ico_path)`
- Produces:
  - `build_release.START_MODULES = {"ERPia_RPA.exe": "run_routine", "Prepare_RPA.exe": "web_runner", "Prepare_Observer.exe": "rpa_observer"}` (`EXES` 에서 만든다)
  - `build_release.zig_exe() -> str` (없으면 `RuntimeError`)
  - `build_release.build_launchers(work_dir: str, cache: str = LAUNCHER_CACHE) -> None` - `work_dir` 에 exe 셋을 둔다
  - `app_start.main(argv=None) -> int`, 상수 `app_start.START` (소문자 exe 이름 → 모듈 이름)

**정한 것**
- `tools/launcher.c` 하나를 두 번 컴파일한다: 콘솔용, 창 프로그램용(`-DWINDOWED`, 윈도우 서브시스템). `Prepare_Observer.exe` 만 창 프로그램용.
- 시작 파일이 하는 일: 자기 폴더 `D` 를 구한다 → 환경 변수 `PYTHONHOME=D\python` → `D\python\python314.dll` 을 `LoadLibraryExW(..., LOAD_WITH_ALTERED_SEARCH_PATH)` 로 올린다 → `Py_Main(argc, argv)` 를 `GetProcAddress` 로 찾아 부르고 그 값을 종료 코드로 돌려준다. `Python.h` 를 쓰지 않는다 (내장 Python 에 헤더가 없다).
- `Py_Main` 에 넘기는 인자: `[exe 전체 경로, "-s", "D\app\_start.py", 사용자 인자...]`. 스크립트로 돌리므로 `sys.path[0]` 이 `D\app` 이 된다 (현재 폴더는 안 들어간다 - 프로그램 폴더의 `rpa_status.py` 가 조각보다 먼저 잡히면 안 된다).
- dll 을 못 올리거나 `_start.py` 가 없으면 `오토파일럿을 시작하지 못했습니다. 다시 설치하여 주십시오. (<없는 파일 경로>)` 를 stderr 에 쓰고 (창 프로그램은 `MessageBoxW`, 단 인자에 `--check` 가 있으면 창 없이) 종료 코드 `2`.
- `app_start.main()`: `PYTHONHOME` 을 환경에서 지운다 (자식 프로세스에 안 물려주게) → `sys.argv[0] = sys.executable` → `D\lib` 가 있으면 `site.addsitedir` → exe 이름으로 모듈을 골라 `run_main()`. `lib` 가 없으면 위와 같은 안내 글과 종료 코드 `2`. 모르는 exe 이름이면 `2`.
- zig: `%LOCALAPPDATA%\Nuitka\Nuitka\Cache\downloads\pip\*\Lib\site-packages\ziglang\zig.exe` 가운데 하나. 명령은 `zig cc tools/launcher.c -o <exe> -target x86_64-windows-gnu -mcpu=x86_64 -O2 -municode` (+ 창 프로그램용 `-DWINDOWED -Wl,--subsystem,windows`). 옵션이 이 zig 에서 안 먹으면 같은 뜻의 것으로 바꾼다.
- 아이콘·설명: 만든 exe 에 `UpdateResource` 로 아이콘(`ICON_PROCESS`·`ICON_ACTOR`·`ICON_PREPARE`)과 버전 정보(FileDescription `PROCESS 오토파일럿`·`ACTOR 오토파일럿`·`옵저버`, 버전 `BRAND_VERSION`)를 넣는다. `brand_exe` 는 원래 버전 자원이 있는 exe 를 전제하므로, 필요하면 언어 `0x409` 로 새로 넣는 가지를 더한다.
- 보관: `build/launcher_cache/<exe>` + `.inputs` (재료 = `launcher.c` 내용 + 아이콘 파일 내용 + 설명 + zig 버전). 같으면 그대로 쓴다 - 시작 파일은 버전이 바뀌어도 같은 파일이어야 한다 (PC 가 다시 받지 않는다).

- [ ] **Step 1: 실패하는 시험을 쓴다** (`tests/test_module_build.py` 새로, `tests/test_build_release.py` 의 머리·`check` 모양을 따른다)

가짜 배포본을 임시 폴더 `공백 한글 폴더\RPA` 에 만든다: `python\` 은 `br.RUNTIME_ROOT\python` 을 통째로 복사, `app\_start.py` 는 저장소 `app_start.py`, `app\web_runner.py`·`app\rpa_observer.py`·`app\run_routine.py` 는 아래 가짜, `lib\` 는 빈 폴더, 프로그램 폴더에는 함정 `web_runner.py` (`raise SystemExit(99)`).

```python
FAKE = 'import sys, os, json\ndef run_main():\n    print(json.dumps({"argv": sys.argv, "exe": sys.executable, "home": os.environ.get("PYTHONHOME"), "path0": sys.path[0]}))\n    return 7\n'
br.build_launchers(top, cache=os.path.join(tmp, "lc"))
r = subprocess.run([os.path.join(top, "Prepare_RPA.exe"), "--preset", "① 지마켓", 'a "b" c'], capture_output=True, cwd=top, timeout=60)
got = json.loads(r.stdout.decode("utf-8"))
exe = os.path.join(top, "Prepare_RPA.exe")
check(r.returncode == 7, f"종료 코드가 그대로 나온다 ({r.returncode})")
check(got["argv"] == [exe, "--preset", "① 지마켓", 'a "b" c'], f"인자가 그대로, argv[0] 은 exe ({got['argv']})")
check(got["exe"] == exe and got["home"] is None, "sys.executable 은 exe, PYTHONHOME 은 물려주지 않는다")
check(os.path.normcase(got["path0"]) == os.path.normcase(os.path.join(top, "app")), "프로그램 폴더의 함정 .py 가 아니라 app 의 것을 쓴다")
check(subprocess.run([os.path.join(top, "ERPia_RPA.exe")], capture_output=True, cwd=top, timeout=60).returncode == 7, "PROCESS 시작 파일")
check(subprocess.run([os.path.join(top, "Prepare_Observer.exe"), "--check"], capture_output=True, cwd=top, timeout=60).returncode == 7, "옵저버 시작 파일 (창 프로그램, 출력은 부른 쪽이 받는다)")
# Review Focus 3: lib 가 없다 / _start.py 가 없다
shutil.rmtree(os.path.join(top, "lib"))
r = subprocess.run([exe, "--check"], capture_output=True, cwd=top, timeout=60)
check(r.returncode == 2 and "다시 설치하여 주십시오".encode("utf-8") in r.stdout + r.stderr and b"Traceback" not in r.stderr, "lib 가 없으면 한 줄 안내와 코드 2")
os.remove(os.path.join(top, "app", "_start.py"))
r = subprocess.run([exe, "--check"], capture_output=True, cwd=top, timeout=60)
check(r.returncode == 2, "_start.py 가 없으면 코드 2")
# 보관: 다시 만들어도 같은 파일
before = {e: open(os.path.join(top, e), "rb").read() for e in br.EXES}
br.build_launchers(top, cache=os.path.join(tmp, "lc"))
check(all(open(os.path.join(top, e), "rb").read() == before[e] for e in br.EXES), "재료가 같으면 시작 파일이 한 바이트도 안 바뀐다")
check(all(win32api_icon_count(os.path.join(top, e)) == 9 for e in br.EXES), "exe 마다 아이콘 9장")
```

`win32api_icon_count(path)` 는 시험 파일 안의 작은 도우미 (`EnumResourceNames(RT_ICON)` 개수).

- [ ] **Step 2: 돌려서 실패를 확인한다** - `.venv\Scripts\python.exe tests\test_module_build.py` → `build_launchers` 없음.
- [ ] **Step 3: `app_start.py` 를 쓴다** (위 '정한 것' 대로, 40줄 안쪽)
- [ ] **Step 4: `tools/launcher.c` 를 쓴다** (위 '정한 것' 대로. 긴 경로를 위해 버퍼는 32768 글자)
- [ ] **Step 5: `build_release.zig_exe()`·`build_launchers()` 를 쓴다**
- [ ] **Step 6: 시험을 돌린다** - `tests\test_module_build.py` → `실패: 없음`
- [ ] **Step 7: 커밋** - `tools/launcher.c app_start.py tools/build_release.py tests/test_module_build.py`, 글: `조각 빌드 - 내장 Python 을 같은 프로세스에서 켜는 시작 파일 (이름·아이콘 그대로)`

---

### Task 3: 조각 컴파일과 보관

**Files:**
- Modify: `tools/build_release.py`
- Test: `tests/test_module_build.py`

**Interfaces:**
- Consumes: `exe_sources(exe)`, `NUITKA_ENV`
- Produces:
  - `build_release.MODULE_CACHE = build\pyd_cache`
  - `build_release.module_sources() -> list[str]` - `EXES` 전체의 `exe_sources` 합집합, 정렬 (지금 17개 안팎)
  - `build_release.module_fingerprint(src: str, tool: str) -> str`
  - `build_release.build_modules(work_dir: str, cache: str = MODULE_CACHE, force: bool = False, compile=compile_module) -> str` - `work_dir\app\<이름>.cp314-win_amd64.pyd` 들을 두고 builder 글자 (`"nuitka 4.2.2 · python 3.14.7 (조각 새로 1: web_replay, 그대로 16)"`) 를 돌려준다
  - `build_release.compile_module(src: str, out_dir: str) -> str` - 만든 `.pyd` 경로

**정한 것**
- 한 파일의 재료 지문 = 그 파일 내용 + `tool` 글자 + Nuitka 옵션 + `NUITKA_ENV`. 다른 우리 파일·깔린 패키지 목록은 넣지 않는다.
- Nuitka 명령: `python -m nuitka --module --assume-yes-for-downloads --remove-output --no-pyi-file --output-dir=<임시> <src>`, `cwd=REPO`, 환경은 `NUITKA_ENV` + `PYTHONPATH=AGENT_DIR`.
- 보관은 `build_exes` 와 같은 모양: `<cache>\<이름>.pyd` + `.inputs` (지문 + 보관 파일 sha256). 보관한 파일이 깨졌으면 다시 만든다.
- `.pyd` 이름의 꼬리는 `importlib.machinery.EXTENSION_SUFFIXES[0]` 에서 얻는다.
- 소스에 없는 모듈의 옛 `.pyd` 는 `work_dir\app` 에 남기지 않는다.

- [ ] **Step 1: 실패하는 시험을 쓴다** - 가짜 `compile` (부른 소스 이름을 목록에 적고 내용이 소스 지문인 파일을 쓴다) 로:

```python
calls = []
out1 = br.build_modules(work, cache=cache, compile=fake)
check(sorted(calls) == sorted(os.path.basename(s) for s in br.module_sources()), "처음에는 모두 컴파일한다")
check({os.path.splitext(os.path.basename(s))[0] for s in br.module_sources()} >= {"run_routine", "web_runner", "rpa_observer", "rpa_status", "web_replay", "fb", "secret"}, "exe 셋의 우리 파일을 모두 모은다")
calls.clear(); out2 = br.build_modules(work, cache=cache, compile=fake)
check(calls == [] and "그대로" in out2, "재료가 같으면 하나도 다시 만들지 않는다")
# 파일 하나만 바꾼 것처럼: 지문 함수를 바꿔치기
calls.clear(); br.build_modules(work, cache=cache, compile=fake, force=True)
check(len(calls) == len(br.module_sources()), "force 면 모두 새로")
open(os.path.join(cache, "rpa_status" + SUFFIX), "wb").write(b"broken")
calls.clear(); br.build_modules(work, cache=cache, compile=fake)
check(calls == ["rpa_status.py"], "보관한 조각이 깨졌으면 그것만 다시 만든다")
check(br.module_fingerprint(a, "t") != br.module_fingerprint(b, "t") and br.module_fingerprint(a, "t") == br.module_fingerprint(a, "t") and br.module_fingerprint(a, "t") != br.module_fingerprint(a, "t2"), "지문은 그 파일 내용과 도구 버전만 본다")
open(os.path.join(work, "app", "gone" + SUFFIX), "wb").write(b"x"); br.build_modules(work, cache=cache, compile=fake)
check(not os.path.exists(os.path.join(work, "app", "gone" + SUFFIX)), "소스에 없는 옛 조각은 남기지 않는다")
```

- [ ] **Step 2: 실패 확인** → **Step 3: 구현** → **Step 4: 시험 통과** (`tests\test_module_build.py`)
- [ ] **Step 5: 진짜 컴파일 한 번** - `.venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'tools'); import build_release as br, tempfile; print(br.build_modules(tempfile.mkdtemp(), cache=tempfile.mkdtemp()))"` → 오류 없이 끝나고 걸린 시간을 적어 둔다 (약 4~5분 예상). 같은 `cache` 로 한 번 더 돌리면 몇 초.
- [ ] **Step 6: 커밋** - 글: `조각 빌드 - 우리 파일을 하나씩 .pyd 로, 재료가 같은 조각은 보관한 것을 쓴다`

---

### Task 4: 라이브러리 묶음과 풀기

**Files:**
- Modify: `tools/build_release.py`, `rpa_settings.py`
- Test: `tests/test_module_build.py`, `tests/test_settings.py`

**Interfaces:**
- Produces:
  - `build_release.LIB_NAMES` - `.venv\Lib\site-packages` 에서 실을 맨 위 이름들
  - `build_release.build_lib_zip(zip_path: str, site_packages: str = SITE_PACKAGES) -> None`
  - `rpa_settings.LIB_ZIP = "lib.zip"`, `rpa_settings.LIB_MARK = ".unpacked"` (`lib\` 안, 내용 = `lib.zip` 의 sha256)
  - `rpa_settings.unpack_lib(program_dir: str) -> bool` - 풀었으면 `True`, 이미 맞으면 `False`, `lib.zip` 이 없으면 (옛 방식 버전) `False`. 실패는 `RuntimeError("프로그램 구성 요소를 준비하지 못했습니다. (<까닭>)")`

**정한 것**
- `LIB_NAMES`: `playwright`, `pywinauto`, `comtypes`, `win32`, `win32com`, `win32comext`, `pythonwin`, `pywin32_system32`, `pywin32.pth`, `pywin32.version.txt`, `greenlet`, `pyee`, `typing_extensions.py`, `PIL`, `six.py` + 각각의 `*.dist-info` 는 넣지 않는다. Task 5 의 `--check` 에서 빠진 것이 드러나면 여기에 더한다 (옛 exe 가 싣는 것과 같아야 한다).
- 넣지 않는 것: `__pycache__`, `playwright\driver\node.exe` (프로그램 폴더 `playwright\node.exe` 한 벌을 쓴다), `comtypes\test`.
- 고쳐 넣는 것: `comtypes\_tlib_version_checker.py` 의 `if not hasattr(sys, "frozen"):` → `if False:` (`tools/nuitka-package.config.yml` 과 같은 바꿈. 글자가 없으면 빌드를 멈춘다). `MFC_DLL` 을 `pythonwin\mfc140u.dll` 로.
- 묶음은 같은 재료에서 늘 같은 바이트여야 한다 (라이브러리가 그대로면 PC 가 다시 받지 않는다): 이름 정렬, 파일 시각 고정 `(2026, 1, 1, 0, 0, 0)`, `ZIP_DEFLATED`.
- `unpack_lib`: `lib.zip` 의 sha256 이 `lib\.unpacked` 와 같으면 아무것도 안 한다. 다르면 `lib.new\` 에 풀고 → 옛 `lib\` 를 지우고 → `lib.new` 를 `lib` 로 바꾸고 → `compileall` (실패해도 넘어간다) → 맨 끝에 표시 파일을 쓴다. 풀기 전에 모든 이름을 검사한다: 절대 경로·드라이브 글자·`..` 조각이 있으면 풀지 않고 `RuntimeError`.
- `rpa_settings.main()`: `--after-install` 이고 관리자면, `start_problem()` 검사 다음·`configured()` 가지 앞에서 `unpack_lib(paths["program_dir"])`. `RuntimeError` 는 `finish_upgrade` 실패와 같게 처리한다 (`crash_log`, 조용하지 않으면 오류 창, 종료 코드 `1` - 업데이트 도우미가 되돌린다).

- [ ] **Step 1: 실패하는 시험을 쓴다**

`tests/test_settings.py` 에 (작은 가짜 `lib.zip` 으로):

```python
check(rs.unpack_lib(root) is False, "lib.zip 이 없으면 (옛 방식 버전) 아무것도 안 한다")
make_zip(root, {"pkg/__init__.py": "X = 1\n", "one.py": "Y = 2\n"})
check(rs.unpack_lib(root) is True and open(os.path.join(root, "lib", "pkg", "__init__.py")).read() == "X = 1\n", "처음에는 푼다")
check(open(os.path.join(root, "lib", rs.LIB_MARK)).read().strip() == sha(os.path.join(root, rs.LIB_ZIP)), "표시 = 묶음의 지문")
check(rs.unpack_lib(root) is False, "묶음이 그대로면 다시 풀지 않는다")
make_zip(root, {"pkg/__init__.py": "X = 2\n"})
check(rs.unpack_lib(root) is True and not os.path.exists(os.path.join(root, "lib", "one.py")), "묶음이 바뀌면 옛 것을 지우고 새로 푼다")
# Review Focus 2: 풀다 끊긴 자리 (표시 없음)
os.remove(os.path.join(root, "lib", rs.LIB_MARK)); os.remove(os.path.join(root, "lib", "pkg", "__init__.py"))
check(rs.unpack_lib(root) is True and os.path.isfile(os.path.join(root, "lib", "pkg", "__init__.py")), "표시가 없으면 처음부터 다시 푼다")
# Review Focus 1: 밖을 가리키는 경로
for bad in ("../evil.py", "..\\evil.py", "C:/evil.py", "/evil.py", "a/../../evil.py"):
    make_zip(root, {bad: "x"})
    try: rs.unpack_lib(root); ok = False
    except RuntimeError: ok = True
    check(ok and not os.path.exists(os.path.join(os.path.dirname(root), "evil.py")), f"밖을 가리키는 이름은 풀지 않는다 ({bad})")
make_broken_zip(root)
try: rs.unpack_lib(root); ok = False
except RuntimeError as e: ok = "프로그램 구성 요소를 준비하지 못했습니다" in str(e)
check(ok, "깨진 묶음은 까닭과 함께 실패")
```

`tests/test_module_build.py` 에:

```python
br.build_lib_zip(z1); br.build_lib_zip(z2)
names = zipfile.ZipFile(z1).namelist()
check(open(z1, "rb").read() == open(z2, "rb").read(), "같은 재료면 묶음이 한 바이트도 안 다르다")
check("playwright/__init__.py" in names and "pywinauto/__init__.py" in names and "pythonwin/mfc140u.dll" in names and "pywin32.pth" in names, "실을 것이 들어 있다")
check(not any("__pycache__" in n or n.endswith("driver/node.exe") or n.startswith("comtypes/test/") for n in names), "뺄 것은 빠졌다")
check(b'if not hasattr(sys, "frozen"):' not in zipfile.ZipFile(z1).read("comtypes/_tlib_version_checker.py"), "comtypes 시각 검사를 껐다")
check(any(n.startswith("comtypes/gen/") for n in names), "빌드 PC 의 comtypes gen 을 같이 싣는다")
check(os.path.getsize(z1) < 60 * 2 ** 20, f"묶음 크기 ({os.path.getsize(z1) // 2 ** 20}MB)")
```

- [ ] **Step 2: 실패 확인** → **Step 3: `build_lib_zip` 구현** → **Step 4: `unpack_lib` 구현과 `main()` 에 넣기** → **Step 5: 두 시험 통과**
- [ ] **Step 6: 커밋** - 글: `조각 빌드 - 라이브러리는 묶음 하나(lib.zip)로 싣고 설치 마무리가 lib 에 푼다`

---

### Task 5: `--modules` 로 배포본 만들기

**Files:**
- Modify: `tools/build_release.py` (`main`·`collect`·`smoke_check`), `tests/test_build_release.py`

**Interfaces:**
- Consumes: `build_launchers`, `build_modules`, `build_lib_zip`, `rpa_settings.unpack_lib`
- Produces: `build_release.py --modules` → `D:\AX\배포_<버전>` 이 설계 4절 모양. `collect(..., modules=False)` 에 인자 하나.

**정한 것**
- `--modules` 일 때 `work` 에 시작 파일 셋·`app\*.pyd`·`lib.zip` 을 만든다. `collect(modules=True)` 가 그것들과 `app\_start.py` (저장소 `app_start.py`) 를 넣고, 버전 목록(`program`)에 모두 올린다. 나머지 (`PROGRAM_FILES`·`python\`·감독 사본)는 지금 그대로.
- `--modules` 와 `--exes-from` 은 함께 쓸 수 없다 (문제로 끝낸다). `--onefile` 은 기본과 같다.
- `write_manifest` 의 `builder` 칸은 `build_modules` 가 돌려준 글자.
- `smoke_check`: 압축을 푼 뒤 `lib.zip` 이 있으면 `rpa_settings.unpack_lib(top)` 을 먼저 부른다 (설치 마무리가 하는 일). 그 뒤 `--check` 셋은 지금 그대로 (옵저버의 `브라우저: Microsoft Edge` 확인 포함).
- `verify_zip` 의 금지 목록은 그대로 통과해야 한다 (`app\` 에 `__pycache__`·`.pyc` 없음).
- `--to-dist` 는 `--modules` 에서 쓰지 않는다 (문제로 끝낸다 - 개발 PC 의 dist 는 옛 방식).

- [ ] **Step 1: 실패하는 시험을 쓴다** (`tests/test_build_release.py`, 가짜 `work` 폴더로 `collect(modules=True)`)

```python
program = br.collect(out, work, repo=repo, runtime_root=rt, modules=True)
check({"app/_start.py", "lib.zip", "ERPia_RPA.exe", "Prepare_RPA.exe", "Prepare_Observer.exe"} <= set(program) and any(p.startswith("app/") and p.endswith(".pyd") for p in program), "조각 방식: 시작 파일·조각·묶음이 버전 목록에 들어간다")
check(not os.path.exists(os.path.join(out, "lib")), "lib 폴더는 싣지 않는다 (PC 에서 푼다)")
check(br.main(["--modules", "--exes-from", "x"]) == 1 and br.main(["--modules", "--to-dist"]) == 1, "함께 못 쓰는 옵션은 문제로 끝난다")
```

- [ ] **Step 2: 실패 확인** → **Step 3: 구현** → **Step 4: `tests\test_build_release.py`·`tests\test_module_build.py` → `실패: 없음`**
- [ ] **Step 5: 진짜로 만든다**

Run: `.venv\Scripts\python.exe tools\build_release.py --modules`
Expected: `배포판에 문제` 없이 끝나고 설치 파일이 생긴다. `--check` 에서 `ModuleNotFoundError` 가 나오면 그 패키지를 `LIB_NAMES` 에 더하고 다시.
적어 둘 것: 전체 시간, `lib.zip` 크기, `app\` 크기, 설치 파일 크기.

- [ ] **Step 6: 고친 뒤 빌드 시간을 잰다** - `web_replay.py` 끝에 빈 줄 하나를 더하고 `build_release.py --modules --no-setup` 을 돌려 '조각 새로 1' 과 걸린 시간을 적는다. 빈 줄을 되돌리고, 그때 생긴 `D:\AX\배포_*` 는 지운다 (방금 만든 것만).
- [ ] **Step 7: 옛 방식이 그대로인지** - `.venv\Scripts\python.exe tools\build_release.py --no-setup` → exe 셋 `재료가 지난번과 같아 그대로 씁니다` 가 아니면 (Task 1 로 소스가 바뀌었으니 새로 만든다) 끝까지 통과하는지만 본다. 생긴 폴더는 지운다.
- [ ] **Step 8: 커밋** - 글: `조각 빌드 - build_release --modules (기본은 옛 방식 그대로)`

---

### Task 6: 샌드박스

**Files:**
- Modify: `tools/sandbox_inner.ps1`, 필요하면 `tools/sandbox_test.py`

**정한 것**
- `sandbox_inner.ps1` 은 설치된 폴더에 `lib.zip` 이 있으면 조각 버전으로 보고 아래를 더 본다. 없으면 지금 검사 그대로.
  - `lib\.unpacked` 가 있고 내용이 `lib.zip` 의 지문과 같다
  - `app\` 에 `.py` 는 `_start.py` 하나뿐이다 (우리 소스가 안 실렸다)
  - 프로그램 폴더 전체에 `run_routine.py`·`web_runner.py`·`web_replay.py`·`rpa_observer.py`·`wellife.py` 가 없다
  - exe 셋 `--check` 가 끝 줄까지 (설치된 자리에서, 일반 사용자 권한으로)
  - 제거 뒤 `lib\`·`app\` 가 남지 않는다
- 지금 있는 'exe 다섯의 아이콘' 검사가 시작 파일에서도 통과해야 한다.

- [ ] **Step 1: 검사를 더한다**
- [ ] **Step 2: 새 설치 + 업데이트·되돌리기** - `.venv\Scripts\python.exe tools\sandbox_test.py --update D:\AX\AUTOPILOT_Setup_<조각 버전>.exe` → `실패: 0`
- [ ] **Step 3: 옛 버전 → 조각 버전 → 되돌리기 (Review Focus 5)** - `.venv\Scripts\python.exe tools\sandbox_test.py --from D:\AX\AUTOPILOT_Setup_<지금 최신 옛 방식 버전>.exe D:\AX\AUTOPILOT_Setup_<조각 버전>.exe` → `실패: 0`. 되돌린 뒤 옛 exe 의 `--check` 가 통과하는지 결과에서 확인한다 (검사가 없으면 더한다).
- [ ] **Step 4: 실패가 있으면** 원인을 고치고 Task 5 Step 5 부터 다시. 샌드박스는 한 번에 하나만 띄운다.
- [ ] **Step 5: 커밋** - 글: `샌드박스 - 조각 버전 검사 (라이브러리 풀림·소스 없음·옛 버전과 오가기)`

---

### Task 7: 마무리

**Files:**
- Modify: `docs/TODO.md`, `docs/superpowers/specs/2026-11-11-module-build-design.md` (3절 표에 실측 값), `tools/build_release.py` 맨 위 설명글

- [ ] **Step 1:** `build_release.py` 맨 위 설명글에 `--modules`·`--onefile` 과 보관 폴더 셋(`exe_cache`·`pyd_cache`·`launcher_cache` - 지우지 말 것)을 적는다.
- [ ] **Step 2:** 설계서 3절에 실측을 더한다: 전체 처음 빌드 시간, 파일 하나 고친 뒤 시간, `lib.zip`·설치 파일 크기, 샌드박스 결과.
- [ ] **Step 3:** `docs/TODO.md` 의 '조각 컴파일 빌드' 줄을 남은 일로 바꾼다: 실기 한 대 확인(사용자) → 기본값 바꾸기 → 2단계(에이전트 쪽 파일). 이 파일의 다른 줄은 건드리지 않는다.
- [ ] **Step 4:** `graphify update .`
- [ ] **Step 5: 커밋** 뒤 사용자에게 보고: 실측 값, 샌드박스 결과, 사용자가 할 일 (조각 버전을 '시험용' 메모로 내보낼지, 시험 PC 한 대에 [업데이트], 실제 수집·ERPia 처리 확인).

---

## 이 계획에 없는 것

- 조각 방식을 기본값으로 바꾸기, 버전 내보내기 - 실기 확인 뒤 사용자가 말하면.
- 에이전트·대시보드·설정 창·업데이트 파일의 컴파일 (설계 8절 2단계).
- 조각 동시 컴파일.
