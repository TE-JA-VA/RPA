# 스탠드얼론 ③ 설치·빌드 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `tools/build_release.py --edition standalone` 한 번으로 `AUTOPILOT_Standalone_Setup_<버전>.exe` 가 나오고, 그 설치 파일을 새 PC 에 깔면 라이선스 고르기 → 설정 → 관리자 계정 만들기까지 끝나 Firebase 없이 돈다. 구매하지 않은 PC·고친 파일에서는 PROCESS·ACTOR·옵저버가 켜지지 않는다.

**Architecture:** 스탠드얼론 빌드는 지금 배포에 쓰는 조각 방식(`--modules`: 우리 코드는 `app\*.pyd`, 라이브러리는 `lib.zip`)에 '버전 종류' 한 겹을 얹는다 - 재료 목록(프로그램 파일·조각·라이브러리)을 버전 종류로 고르고, `server_info.py` 는 빈 값 사본을, 웹 파일·`edition.json`·`manifest.sig` 를 더 싣는다. 라이선스·변조 확인은 새 조각 `ap_guard` 가 exe 셋의 첫머리에서 한다 (컴파일된 코드가 컴파일된 코드를 부른다). 설치 파일은 `release/installer.iss` 하나를 `/DEdition=standalone` 으로 가르고, 라이선스·관리자 계정 단계는 설치 끝에 뜨는 설정 창(`rpa_settings.py`)이 맡는다.

**Tech Stack:** Python 3.14 (Nuitka `--module`, zig 시작 파일 - 지금 것 그대로), Inno Setup 6, tkinter, icacls, 윈도우 샌드박스. 시험은 저장소 관례대로 `check()` 를 쓰는 스크립트 - `D:/AX/RPA/.venv/Scripts/python.exe tests/<파일>` (실패가 있으면 종료 코드 1).

**Spec:** `docs/superpowers/specs/2026-11-23-standalone-local-server-design.md` (6.1·6.4·6.5·6.6·8·9·11절). 앞 계획 ① `…-1-server-core.md`, ② `…-2-web.md` 의 이름을 쓴다 (`edition`·`license_check`·`local_server.data_dir/ensure_keys`·`local_store.keys_dir`·`local_web.Accounts/web_dir`·`rpa_update.SHIPPED_SIG_NAME`).

## 읽으면서 확인한 사실 (계획의 바탕)

- 지금 내보내는 일반 버전은 조각 방식이다 (`D:\AX\배포_2026.11.23-2` 에 `lib.zip`·`app\` 조각 18개). 코드의 기본값만 옛 방식이다.
- 내장 파이썬 `D:\AX\runtime\python` 에는 `site-packages` 가 없다. `anthropic` 은 `lib.zip`(`LIB_NAMES`)으로만 실린다 → **스탠드얼론용 내장 파이썬 사본은 만들지 않는다**, 라이브러리 목록에서 뺀다 (설계 8절의 '사본' 은 필요 없음).
- 우리 코드에 바깥 주소 글자가 있는 곳: `server_info.py`, `firebase/agent/fb.py`(51·56·279행 googleapis 셋), `background.py`(162-163행), `ai_rescue.py`, 웹의 `firebase-config.js`·`data-firebase.js`·`index.html`(글꼴 - 계획 ② Task 3 이 없앤다).
- `web_replay.py:20`·`web_runner.py:35` 가 `ai_rescue` 를 맨 위에서 불러온다 - 파일을 빼면 ACTOR·옵저버가 켜지지 않는다.
- `rpa_settings.lock_data_acl()` 은 설치·업데이트마다 설정 폴더 아래를 `/reset /T` 한다 - 파일에 따로 붙인 권한은 그때마다 지워진다.
- 옵저버는 켤 때 관리자 권한으로 다시 뜨고(`rpa_observer.py:2119`), ACTOR 는 관리자 전용 `config` 폴더의 설정을 읽는다 - 지금 둘 다 관리자 권한으로만 돈다.
- `tests/test_build_release.py` 404행(69번째 검사)은 `<저장소>\.venv\…\node.exe` 가 진짜로 있는지 본다 - 워크트리에는 `.venv` 가 없어 실패한다. `build\*_cache` 는 저장소 폴더 아래라 워크트리는 자기 것을 새로 갖는다.
- `prune_local()` 은 `D:\AX` 의 일반 버전 폴더를 최신 4개만 남기고 지운다 - 워크트리에서 일반 버전을 그대로 빌드하면 다른 세션의 버전 번호를 쓰고 옛 폴더를 지운다.

## Global Constraints

- 일반(cloud) 버전의 빌드 결과·설치·동작은 바뀌지 않는다. 버전 종류 인자의 기본값은 모두 `"cloud"` 이고 그때 재료 목록·명령 줄·파일 이름이 지금과 **같은 값**이어야 한다 (Task 1 시험이 못박는다). 각 Task 끝에 `tests/test_build_release.py`·`test_module_build.py`·`test_settings.py`·`test_encoding.py`·`test_rpa_update.py`·`test_background.py`·`test_server_info.py`·`test_fb_backoff.py`·`test_cloud_scrub.py`·`test_dev_env.py`·`firebase/tests/test_agent.py` 와 계획 ①·② 의 스탠드얼론 시험이 통과해야 한다 (`tests/test_import_step.py` 는 실제 ERPia 를 누른다 - 돌리지 않는다).
- **Task 1~5 는 빌드·설치 파일·샌드박스를 돌리지 않는다** (단위 시험만). 실제 빌드와 샌드박스는 Task 6 에서만, 시작 전에 걸리는 시간을 사용자에게 알린다.
- 빌드·설치·샌드박스 파일(`tools/build_release.py`·`release/installer.iss`·`tools/sandbox_test.py`·`rpa_settings.py`)을 고치는 Task 는 시작 전에 '고치는 파일' 을 사용자에게 알린다.
- 서명 열쇠 파일(`firebase/admin/update_signing_key.txt`·`license_signing_key.txt`)은 Claude 가 읽지 않는다. **진짜 열쇠로 하는 빌드는 사용자가 돌린다** - Claude 가 돌리는 빌드는 `--test-build` 뿐이다.
- `D:\AX\RPA`(다른 세션)와 그 `build\` 는 고치지 않는다. 워크트리의 `build\exe_cache`·`pyd_cache`·`launcher_cache` 는 지우지 않는다. 개발 PC 의 `.venv` 패키지를 바꾸지 않는다. 개발 PC 에 설치 파일을 돌리지 않는다.
- 스탠드얼론 설치본은 Firebase·Google·Anthropic·업데이트 사이트에 연결을 **시도하지 않는다**. 실서버(rpa-test-f02e0)에 아무것도 보내지 않는다.
- bat 는 CP949+CRLF, 괄호 블록 안에 `echo` 를 두지 않는다, 만들면 실행해 본다. `installer.iss`·`*.ps1` 은 BOM 있는 UTF-8. 파이썬 패치는 Write 도구 파일로.
- 글은 한국어 ("…하여 주십시오"). 화면·문서에 '버전' 을 쓴다. 비밀번호·열쇠·세션 값은 기록·오류 글에 싣지 않는다.
- 커밋은 Task 마다 (`git commit -F`), 끝에 `Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>`. push 는 사용자 지시가 있을 때만.

## Review Focus

1. 일반 버전이 그대로인가 - 기본 인자의 재료 목록·`iscc_command`·`setup_name`·`next_version` 이 지금 값, `prune_local` 이 다른 버전 종류의 폴더를 지우지 않는다 (Task 1). Task 6 의 일반 버전 확인 빌드는 `--out-root` 로 `D:\AX` 밖에.
2. 시험용 빌드가 고객에게 나감 - 파일·폴더 이름에 `TEST`, 설치·설정 창·웹에 '시험용' 표시, 진짜 라이선스는 시험용 빌드에서 '서명이 맞지 않습니다'. 진짜 빌드는 라이선스 공개 열쇠가 비면 멈춘다 (Task 3).
3. `.py` 를 고치거나 끼워 확인을 지움 - `rpa_dashboard.py` 한 바이트 고침, `app\` 에 `license_check.py` 끼움, `manifest.sig` 지움 → exe 셋이 종료 코드 2 (Task 3·6).
4. 덮어 설치 - 도는 로컬 서버까지 멈춘 뒤 덮고, 라이선스·계정·기록·설정이 남고, 권한 다시 잠근 뒤에도 서버가 열쇠를 읽는다 (Task 4·6).
5. 다른 버전 종류가 깔린 PC - 두 설치 파일 모두 시작 전에 멈추고 깔려 있던 것은 그대로다 (Task 5·6).
6. 막은 주소로 '시도' 가 있었나 - 샌드박스에서 주소를 덫(127.0.0.2 듣기)으로 돌려 연결 수 0 을 센다 (Task 6).

---

### Task 1: 빌드 도구의 버전 종류 - 재료 목록 · 이름 · 워크트리

**Files:**
- Modify: `tools/build_release.py`, `tests/test_build_release.py` (404행 한 곳 - `.venv` 자리)
- Test: `tests/test_build_edition.py` (새로)

**Interfaces:**
- Produces (`build_release`, 인자 `edition` 의 기본은 모두 `"cloud"`):
  - `EDITIONS = ("cloud", "standalone")`, CLI `--edition {cloud,standalone}`, `--out-root <폴더>`(기본 `D:\AX`), `--test-build`(Task 3 이 채운다). `--edition standalone` 은 조각 방식만: `--onefile`·`--exes-from`·`--to-dist` 와 같이 주면 `문제: 스탠드얼론은 조각 방식으로만 만듭니다` 를 찍고 1 (빌드 전에).
  - `venv_root() -> str` - `REPO\.venv` 가 있으면 그것, 없으면 가상 환경으로 돌 때의 `sys.prefix`, 둘 다 아니면 `RuntimeError(".venv 를 찾지 못했습니다 - D:\\AX\\RPA\\.venv\\Scripts\\python.exe 로 돌리십시오")`. `site_packages() -> str` = `venv_root()\Lib\site-packages` (`build_lib_zip` 기본값이 쓴다). `_src_path(repo, src) -> str` - `src` 가 `.venv/` 로 시작하고 `repo` 아래에 없으면 `venv_root()` 아래. 모듈을 불러오는 것만으로는 예외가 나지 않는다. **(Claude 판단: 접합(junction)을 만들지 않는다 - `git clean`·워크트리 지우기가 접합을 타고 진짜 `.venv` 를 지울 수 있다. 빌드는 `D:/AX/RPA/.venv/Scripts/python.exe` 로 돌린다.)**
  - `program_files(edition) -> [(rel, src)]` - cloud 는 `PROGRAM_FILES` 그대로. standalone 은 거기서 `update_helper.py`·`license_check.py`(Task 3: 조각으로만 싣는다)를 빼고 `("firebase/agent/local_web.py", …)` 와 `web_files()` 를 더한다. `server_info.py` 는 `GENERATED = {"server_info.py": blank_server_info}` 로 원본 대신 만든 글을 쓴다.
  - `web_files(repo=REPO) -> [(rel, src)]` - `firebase/web` 아래 모든 파일(`fonts/`·`img/` 포함, 이름순), `WEB_SKIP = ("firebase-config.js", "data-firebase.js", "edition.js")` 는 뺀다 (`edition.js` 는 서버가 늘 만들어 내준다 - `local_web` 이 파일 없이 내주는지 시험으로 확인, 아니면 목록에 둔다).
  - `other_files(edition)` - cloud 는 `OTHER_FILES`. standalone 은 `배포안내_스탠드얼론.txt`·`PC번호_확인.bat`(둘 다 `release/` - Task 5 가 만든다)·`RPA_UserConfig.json`. `클라우드_안내.txt` 없음.
  - `LIB_NAMES_AI` (지금 `LIB_NAMES` 의 `anthropic` 부터 `annotated_types` 까지 18개) 를 갈라 둔다. `lib_names(edition)` - cloud 는 지금 `LIB_NAMES` 와 같은 목록, standalone 은 `LIB_NAMES_AI` 를 뺀 것.
  - `MODULE_SKIP = {"standalone": ("ai_rescue",)}`, `module_sources(edition="cloud")` - standalone 은 그 이름의 파일을 뺀다. `server_info` 조각은 `blank_server_info` 로 만든 임시 사본을 컴파일한다.
  - `blank_server_info(text) -> str` - 맨 위 대입문 이름마다 `이름 = ""` (튜플은 `()`), 첫 줄 `# 스탠드얼론 - 바깥 서버 주소가 없다 (tools/build_release.py 가 만든다)`. 대입문·문서 글 말고 다른 실행 코드가 있으면 `RuntimeError`. **(Claude 판단: 손으로 쓴 두 번째 파일 대신 만들어 낸다 - 이름이 늘어도 어긋나지 않는다.)**
  - `release_prefix(edition, test=False)` → `"배포_"` / `"배포_SA_"` / `"배포_SA_TEST_"`. `setup_name(version, edition="cloud", test=False)` → `AUTOPILOT_Setup_<v>.exe` / `AUTOPILOT_Standalone_Setup_<v>.exe` / `AUTOPILOT_Standalone_TEST_Setup_<v>.exe`. `next_version(out_root, today, prefix="배포_")`, `prune_local(out_root, keep, protect, edition="cloud", test=False)` 는 자기 접두사의 폴더·압축·설치 파일만 세고 지운다.
  - `collect(..., edition="cloud", test=False)` - standalone 은 `edition.json` = `{"edition": "standalone"}` (시험용이면 `"test_build": true` 도)을 쓰고 목록에 넣는다. `STANDALONE_FORBIDDEN = ["ai_rescue*", "update_helper.py", "firebase-config.js", "data-firebase.js", "license_check.py", "anthropic", "*signing_key*", "*.testkey.txt"]` - `verify_zip(..., edition)` 이 내장 파이썬 밖에서 찾으면 `들어가면 안 되는 파일`. `manifest.sig` 는 '모은 목록에 없는 파일' 에서 봐준다.
  - `iscc_command(iscc, out_dir, version, out_root=OUT_ROOT, iss=ISS_PATH, edition="cloud", test=False)` - cloud 는 지금 리스트 그대로. standalone 은 `/DDashboardURL=http://127.0.0.1:8781/`, `/DEdition=standalone`, 시험용이면 `/DTestBuild=1` 을 더하고 `/F` 는 `setup_name(...)`.

- [ ] **Step 1: 실패하는 시험** `tests/test_build_edition.py` (가짜 저장소 폴더 - `test_build_release.py` 2절과 같은 방식). 검사:
  - 일반 버전 그대로: `program_files("cloud") == PROGRAM_FILES`, `lib_names("cloud") == LIB_NAMES`, `module_sources() == module_sources("cloud")` 이고 `ai_rescue.py` 가 있다, `setup_name("2026.11.24-1") == "AUTOPILOT_Setup_2026.11.24-1.exe"`, `iscc_command("I", "D", "2026.11.24-1")` 이 지금 코드가 내는 리스트와 같다(시험에 리스트를 적는다), `next_version` 이 `배포_SA_2026.11.24-3` 을 세지 않는다, `prune_local` 일반이 `배포_SA_*`·`AUTOPILOT_Standalone_*` 를 남기고 그 반대도.
  - 스탠드얼론 목록: `update_helper.py`·`license_check.py`·`firebase-config.js`·`data-firebase.js` 없음, `firebase/agent/local_web.py`·`firebase/web/index.html`·`firebase/web/fonts/PretendardVariable.woff2`·`firebase/web/img/login.webp` 있음, `lib_names("standalone")` 에 `anthropic`·`httpx2`·`pydantic` 없고 `playwright`·`pywinauto`·`msoffcrypto`·`cryptography`·`typing_extensions.py` 있음, `module_sources("standalone")` 에 `ai_rescue.py` 없음.
  - `blank_server_info(진짜 server_info.py)` 를 실행하면 진짜와 같은 이름이 모두 있고 값은 `""`·`()` 뿐, 글에 `http`·`AIza` 없음. 함수 정의가 든 글은 `RuntimeError`.
  - `collect(edition="standalone")`: `edition.json` 내용, `server_info.py` 가 빈 값 사본, 웹 파일이 `firebase/web/` 에, `verify_zip` 통과. `ai_rescue.py` 를 끼우면 `들어가면 안 되는 파일`.
  - `venv_root()` - `.venv` 없는 가짜 `REPO` 에서 `sys.prefix`. `main(["--edition", "standalone", "--onefile"]) == 1`.
- [ ] **Step 2: 실패 확인** → `AttributeError: program_files`.
- [ ] **Step 3: 구현.** `main()` 은 버전 종류로 목록·이름·`OUT_ROOT` 를 골라 지금 함수들에 넘긴다 (일반 경로의 호출 인자는 그대로). `test_build_release.py` 404행은 `br._src_path(str(ROOT), node)` 로.
- [ ] **Step 4: 통과 확인** - 새 시험 + `test_build_release.py`(워크트리에서 69번째 검사 통과) + `test_module_build.py`.
- [ ] **Step 5: 커밋** - "스탠드얼론 ③ Task 1 - 빌드 도구의 버전 종류 (재료 목록·이름·워크트리의 .venv), 일반 버전 값은 그대로".

### Task 2: 주소는 `server_info` 한 곳 · AI 는 없으면 끔 · 바깥 연결 0 시험

**Files:**
- Modify: `server_info.py`, `firebase/agent/fb.py`, `firebase/agent/background.py`, `rpa_update.py`, `web_replay.py`, `web_runner.py`, `tools/build_release.py`(`standalone_materials` 하나), `tests/test_server_info.py`
- Test: `tests/test_standalone_offline.py` (새로)

**Interfaces:**
- Consumes: Task 1 `program_files`·`module_sources`·`web_files`·`blank_server_info`.
- Produces:
  - `server_info.AUTH_HOST = "identitytoolkit.googleapis.com"`, `TOKEN_HOST = "securetoken.googleapis.com"`, `FIRESTORE_HOST = "firestore.googleapis.com"` - `fb.py` 의 세 곳과 `background.ROOT_WARM_URLS` 가 이 값으로 조립한다 (일반 버전의 주소는 글자 하나 바뀌지 않는다).
  - 빈 `server_info` 일 때: `fb.Client(cfg)` 는 `RuntimeError("스탠드얼론 버전에서는 Firebase 에 연결하지 않습니다.")`, `background.ROOT_WARM_URLS == ()` 이고 `warm_windows_roots(urls=())` 는 `run` 을 부르지 않는다, `rpa_update.update_urls() == ()` 이고 `fetch_release` 는 `UpdateError("스탠드얼론 버전은 새 설치 파일로 업데이트합니다.")`.
  - `web_replay.ai` - `ai_rescue` 를 못 불러오면 `None`, 그때 `_ai_ok()` 는 `False` (다른 줄은 `self.ai is None` 에서 먼저 끝난다). `web_runner.ai_rescue` 도 `None` 이면 `rp.ai = None`, `--check` 는 `AI 어시스트: 이 버전에는 없습니다` 한 줄.
  - `build_release.standalone_materials() -> [(rel, bytes)]` - 스탠드얼론 설치본에 실리는 우리 코드·웹 파일의 내용 (만든 `server_info` 적용, 내장 파이썬·남의 라이브러리 제외).
  - `tests/test_standalone_offline.py` 의 `BLOCKED = ("googleapis.com", "gstatic.com", "firebaseio.com", "firebasedatabase.app", "firebaseapp.com", ".web.app", "anthropic", "jsdelivr", "rpa-test-f02e0", "AIzaSy")`. 인자 없이 돌리면 ①② , `--release <배포 폴더>` 면 만든 폴더의 바이트를 본다 (Task 6).

- [ ] **Step 1: 실패하는 시험.** 검사:
  - ① `standalone_materials()` 의 어느 파일에도 `BLOCKED` 가 없다 (걸리면 파일 이름·글자를 찍는다). 견줌: 진짜 `server_info.py` 와 `ai_rescue.py` 를 넣으면 걸린다 (찾는 도구가 도는지).
  - ② 하위 프로세스(`RPA_EDITION=standalone`, 임시 `RPA_PROGRAMDATA`, `sys.modules["server_info"]` = 빈 값 모듈, `sys.modules["ai_rescue"] = None`)에서 `socket.socket.connect`·`socket.create_connection`·`socket.getaddrinfo`·`subprocess.run/Popen` 을 감싸고: `agent`·`background`·`secret`·`rpa_update`·`rpa_settings`·`local_server`·`local_web`·`otp_relay`·`web_replay`·`web_runner` 를 불러온다(예외 없음) → 계획 ① e2e 와 같은 구성으로 서버+에이전트를 10초 돌린다 → `background.run()` 을 가짜 `main` 으로 → 모은 대상이 `{"127.0.0.1", "localhost"}` 안, `powershell` 을 띄운 적 없음.
  - `web_replay.ai is None`·`web_runner.ai_rescue is None` 일 때 재생기 하나를 만들어 `_ai_ok(...)` 가 `False`, `--check` 출력에 위 한 줄.
  - 일반 버전: `ROOT_WARM_URLS` 가 고치기 전과 같은 튜플 (시험에 지금 값 다섯을 `server_info` 로 조립해 견준다), `fb` 의 주소 함수 셋이 지금과 같은 글.
- [ ] **Step 2: 실패 확인** → `standalone_materials` 없음, 그다음 ① 이 `fb.py`·`background.py` 를 찍는다.
- [ ] **Step 3: 구현.** `fb.py` 는 `secret.py` 처럼 저장소 뿌리를 `sys.path` 에 넣고 `server_info` 를 불러온다. `tests/test_server_info.py` 에 새 상수 셋 검사를 더한다.
- [ ] **Step 4: 통과 확인** + `test_fb_backoff.py`·`test_cloud_scrub.py`·`firebase/tests/test_agent.py`·`test_ai_rescue.py`·`test_rpa_update.py`·`test_background.py`. `index.html` 이 걸리면 계획 ② Task 3 (로컬 글꼴)이 아직 안 끝난 것 - 거기서 고친다.
- [ ] **Step 5: 커밋** - "스탠드얼론 ③ Task 2 - 바깥 주소는 server_info 한 곳(스탠드얼론은 빈 값), AI 는 없으면 끔, 바깥 연결 0 시험".

### Task 3: 복사 막기 - 가드 조각 · exe 셋의 확인 · 열쇠와 서명 · 시험용 빌드

**Files:**
- Create: `ap_guard.py`, `tests/test_ap_guard.py`
- Modify: `run_routine.py`(`main`), `web_runner.py`(`main`), `rpa_observer.py`(`main`), `rpa_status.py`(`tamper_text` 의 끝 문장), `edition.py`, `tools/build_release.py`, `firebase/agent/local_web.py`(`EDITION_JS`)·`firebase/web/app.js`(시험용 띠), `tests/test_build_edition.py`

**Interfaces:**
- Consumes: 계획 ① `license_check.load/LicenseError`·`edition.is_standalone`·`rpa_update.SHIPPED_SIG_NAME`("manifest.sig"), `rpa_status.check_install/tamper_text/shipped/program_dir`, `update_sign.verify/public_key`.
- Produces (`ap_guard` - 조각으로만 실린다, 일반 버전에서는 첫 줄에서 `None`):
  - `EXIT_BLOCKED = 2`
  - `manifest_signed(root) -> bool` - `root\manifest.sig`(16진수)가 `manifest.json` 바이트에 대한 맞는 서명인가.
  - `loose_sources(root) -> [str]` - `root\app` 에서 `_start.py` 말고 있는 `.py`·`.pyc`, 그리고 `GUARD_PIECES = ("license_check", "ap_guard", "rpa_status", "update_sign", "edition")` 가운데 불러온 파일이 `.pyd` 가 아닌 것.
  - `startup_problem() -> str | None` - 일반 버전은 `None`. 스탠드얼론: ① `license_check.load()` 가 `LicenseError` 면 그 글 (예: `이 PC 의 라이선스가 아닙니다. (PC 번호 …) 이 PC 번호로 라이선스를 다시 받아 주십시오.`) ② 설치본(`rpa_status.shipped()`)이면 `manifest_signed` 가 거짓 → `프로그램 파일의 서명을 확인하지 못했습니다. 같은 버전 설치 파일로 다시 설치하여 주십시오.`, `check_install()` 이 `tampered` → `tamper_text(...)`, `error` → 서명 글과 같은 글, `loose_sources` 가 있으면 `프로그램 파일이 설치된 버전과 달라 실행하지 않습니다. (app\<이름>) 같은 버전 설치 파일로 다시 설치하여 주십시오.`
  - `check_line() -> str` - `--check` 에 찍는 줄: `라이선스: 확인됨 (<업체 이름>, PC 번호 <…>)` 또는 `라이선스: <문제 글>`, 일반 버전은 `""`(찍지 않는다).
  - 부르는 자리: `run_routine.main()` 과 `web_runner.main()` 은 `--check`(와 `--selftest`·`--uiacheck`)가 아니면 맨 먼저 `startup_problem()` - 글이 있으면 기록에 남기고 현황을 `stopped`(사유 = 그 글)로 닫은 뒤 `EXIT_BLOCKED`. `rpa_observer.main()` 은 관리자 권한으로 다시 뜬 뒤·`setup_problem()` 앞에서 - 글이 있으면 `show_error(글)` 뒤 `EXIT_BLOCKED`. `--check` 는 막지 않고 `check_line()` 을 찍는다 (라이선스 없는 빌드 점검이 돈다).
  - `rpa_status.tamper_text` - 스탠드얼론이면 끝 문장이 `같은 버전 설치 파일로 다시 설치하여 주십시오.` (일반은 지금 문장 그대로).
  - `edition.test_build() -> bool` - `edition.json` 의 `test_build` 가 `true` 인가 (일반 버전은 `False`).
- Produces (`build_release`):
  - `swap_key(text, name, hex) -> str` - `^<name> = "…"` 줄이 정확히 하나일 때만 바꾼다, 아니면 `RuntimeError`.
  - `license_key_problem(test) -> str | None` - 시험용이 아니고 `license_check.LICENSE_PUBLIC_KEY_HEX` 가 비면 `라이선스 공개 열쇠(license_check.LICENSE_PUBLIC_KEY_HEX)가 비어 있습니다 - tools/make_license.py --keygen 이 알려 준 값을 넣으십시오 (시험용이면 --test-build)`. `main` 이 빌드 전에 찍고 1.
  - `--sign-key <파일>`(기본 `publish_release.KEY_PATH`) - 진짜 스탠드얼론 빌드가 버전 목록을 서명하는 열쇠. 없으면 `업데이트 서명 열쇠 파일이 없습니다 (<경로>) - 스탠드얼론은 버전 목록의 서명을 설치 파일에 싣습니다` 를 찍고 1. `sign_manifest(out_dir, secret) -> str` - `manifest.sig` 를 쓴다 (버전 목록의 `files` 에는 넣지 않는다).
  - `--test-build`: 그 자리에서 열쇠 두 쌍을 만든다 (`update_sign.keygen()`). `license_check`·`update_sign` 조각과 뿌리의 `update_sign.py` 는 공개 열쇠를 바꿔 끼운 임시 사본으로 만들고 (보관 폴더에 넣지 않는다 - 매번 새로), 버전 목록은 시험용 열쇠로 서명하고, 시험용 **라이선스** 비밀 열쇠만 `<out-root>\배포_SA_TEST_<v>.testkey.txt` 에 남긴다 (`make_license.py --key` 가 읽는 꼴). 진짜 열쇠 파일은 열지 않는다.
  - 뿌리의 가드: 스탠드얼론은 `app\license_check<조각 확장자>` 를 프로그램 폴더 뿌리에도 한 벌 싣는다 (에이전트·로컬 서버가 부른다 - `.py` 는 없다).
  - `smoke_check(zip_path, edition)` - 스탠드얼론이면 exe 셋의 `--check` 출력에 `라이선스:` 줄이 있고, 푼 폴더의 내장 파이썬으로 `import agent, local_server, local_web` 이 되고 `lib` 를 길에 넣어도 `import anthropic` 이 `ModuleNotFoundError`.
- 시험용 빌드가 고객에게 나가지 않게 (Claude 판단 - 다섯 겹): ① 파일·폴더 이름의 `TEST` ② 설치 파일의 제품 이름 `오토파일럿 스탠드얼론 (시험용)` 과 설치 시작 알림(Task 5) ③ 설정 창 제목 `오토파일럿 설정 (시험용 빌드)`(Task 4) ④ 웹 맨 위 띠 `시험용 빌드 - 고객 배포 금지` (`/edition.js` 가 `export const TEST_BUILD = true;` 를 더 낸다) ⑤ 열쇠가 달라 진짜 라이선스가 통하지 않고, 시험용 열쇠로 만든 라이선스는 진짜 빌드에서 통하지 않는다.
- 두 번째 묶기 (Claude 추천: **이번 버전은 MachineGuid 하나만**): 메인보드 UUID 를 더 묶으면 레지스트리 값 바꾸기·디스크 복제를 막지만, 설치 전 bat 과 프로그램이 같은 값을 읽어야 하고 값이 없는 PC 처리(잠김 / 그냥 통과)가 생긴다. 라이선스 본문은 서명만 맞으면 모르는 칸을 그냥 두므로 나중에 `hw` 칸을 더해도 이미 준 라이선스는 산다 - 시험 한 줄로 못박는다.
- 한계 (보안 자료에 그대로 적는다): 가드 조각 자체를 직접 컴파일한 가짜로 바꾸는 것까지는 막지 못한다 - `.py` 한 줄 고치기를 막는 단계다.

- [ ] **Step 1: 실패하는 시험** `tests/test_ap_guard.py` (설치본 흉내는 임시 프로그램 폴더 + `rpa_status.program_dir`·`license_check.machine_guid`·`update_sign.PUBLIC_KEY_HEX` 바꿔 끼우기). 검사:
  - 일반 버전: `startup_problem() is None` 이고 `license_check.load` 가 불리지 않는다. `check_line() == ""`.
  - 스탠드얼론(소스): 라이선스 없음 → `라이선스 파일이 없습니다`, 다른 PC → `이 PC 의 라이선스가 아닙니다. (PC 번호 `, 본문 고침 → `라이선스 서명이 맞지 않습니다`, 맞으면 `None`. 모르는 칸 `hw` 가 든 라이선스도 통과.
  - 스탠드얼론(설치본 흉내): 서명 맞음 → `None`; `manifest.sig` 없음·틀림 → 서명 글; 목록의 파일 한 바이트 고침 → `바뀐 파일:` 과 `같은 버전 설치 파일로 다시 설치`; `app\license_check.py` 를 끼움 → `app\license_check.py` 가 든 글; 빠진 파일만 있으면(mixed) 막지 않는다.
  - 부르는 자리: 가짜 현황 기록으로 `run_routine.main()`·`web_runner.main()` 이 2 를 돌려주고 `stopped` 사유가 그 글, ERPia·브라우저를 건드리지 않는다. `rpa_observer.main(["--check"])` 출력에 `라이선스:` 줄. 일반 버전에서 세 `main` 의 흐름은 그대로 (`startup_problem` 이 `None`).
  - `tests/test_build_edition.py` 에 더하기: `swap_key` (줄이 없거나 둘이면 `RuntimeError`), 열쇠가 빈 채 `main(["--edition", "standalone"]) == 1` 이고 안내 글, `--test-build` 는 그 검사를 넘어간다(컴파일은 가짜 `compile` 로), `sign_manifest` 가 쓴 서명이 `update_sign.verify` 를 통과, `module_sources("standalone")` 에 `ap_guard.py` 가 있다, `edition.test_build()`.
- [ ] **Step 2: 실패 확인** → `ModuleNotFoundError: ap_guard`.
- [ ] **Step 3: 구현.** `ap_guard` 는 맨 위에서 `edition` 만 불러오고 나머지는 함수 안에서 (일반 버전의 켜는 시간에 영향 없음).
- [ ] **Step 4: 통과 확인** + 계획 ①·② 시험 + `test_build_release.py`·`test_module_build.py`.
- [ ] **Step 5: 커밋** - "스탠드얼론 ③ Task 3 - 복사 막기 (가드 조각, exe 셋이 켤 때 라이선스·변조 확인, 열쇠 빈 빌드 멈춤, 시험용 빌드)".

### Task 4: 설정 창 · 설치 마무리 (라이선스 · 관리자 계정 · 열쇠 권한)

**Files:**
- Modify: `rpa_settings.py`, `firebase/agent/local_server.py`(`ensure_keys` 끝에 권한 잠그기 한 줄)
- Test: `tests/test_settings_standalone.py` (새로, 창 없이), `tests/check_settings_ui.py` (진짜 창 - 스탠드얼론 경우 더하기)

**Interfaces:**
- Consumes: `edition.is_standalone/test_build`, `license_check.load/machine_guid/license_path/FILE_NAME`, `local_store.keys_dir`, `local_web.Accounts`(`add`·`set`·`list`·`disable`)·`ACCOUNTS_NAME`.
- Produces (`rpa_settings`, 일반 버전에서는 지금 동작 그대로):
  - `default_paths()` 에 `"license"`(= `license_check.license_path()`), `"accounts"`(= `keys_dir()\accounts.json`).
  - `rows(standalone) -> tuple` - 스탠드얼론은 `ROWS` 에서 `대시보드 연결` 을 뺀 것. `validate(form, state, standalone=False)` 는 그때 업체코드·PC코드·에이전트 비밀번호를 보지 않는다.
  - `license_state(paths) -> {"ok": bool, "text": str, "pc_id": str, "company": str | None, "issued": str | None}` - `text` 는 `LicenseError` 글 그대로.
  - `install_license(src, paths) -> dict` - `license_check.load(path=src)` 를 통과한 파일만 `paths["license"]` 로 옮긴다 (임시 파일 → `os.replace`). 아니면 `LicenseError` 가 그대로 나가고 있던 라이선스는 남는다.
  - `admin_exists(paths) -> bool` (사용 중지가 아닌 `admin` 이 하나 이상), `create_admin(paths, id, pw, pw2) -> str` - 두 값이 다르면 `ValueError("비밀번호가 서로 다릅니다.")`, `Accounts.add(id, pw, "admin", must_change=True)` (기본 비밀번호 없음 - 설치하는 사람이 정하고 첫 로그인에 바꾼다).
  - `reset_admin_password(paths, id, pw, pw2) -> str` - 윈도우 관리자 권한이 아니면 `PermissionError("윈도우 관리자 권한으로 실행하여 주십시오.")`, 그 아이디가 `admin` 이 아니면 `ValueError`, `Accounts.set(id, pw, "admin", must_change=True)` 뒤 사용 중지였으면 푼다. 서버는 계정 파일이 바뀐 것을 스스로 알아채 그 계정의 열린 세션을 닫는다 (`local_web` 의 `rev`).
  - `save(..., standalone=None)` - 스탠드얼론이면 `warm_roots()`·`login(...)` 을 부르지 않는다. 라이선스가 맞지 않거나 관리자 계정이 없으면 `ValueError`(각각 `license_state` 글 / `업체 웹 관리자 계정을 만들어 주십시오.`). 그 뒤는 같다 (설정 쓰기 → 작업 등록 → 에이전트 켜기).
  - `configured(paths, updating=False)` - 스탠드얼론: 사용자 설정이 읽히고 `license_state(paths)["ok"]` 이고 `admin_exists(paths)`. `agent_config.json`·멈춤 코드 3 은 보지 않는다.
  - `SERVER_PY_RE` - `stop_agent()` 가 작업을 끝낸 뒤에도 남은 `local_server.py` 프로세스(설치 폴더의 것)를 끝낸다 - 도는 `python\*.exe` 는 덮어쓸 수 없다. 남으면 `EXIT_STOP_FAILED`.
  - `_main`: 스탠드얼론의 `--after-install` 은 `lock_data_acl()` 뒤에 `local_server.lock_key_files(keys_dir())` 를 부른다.
- Produces (`local_server`): `lock_key_files(folder, readers=(), run=None) -> [int]` - `agent.key`·`relay.key`·`accounts.json` 에 따로 붙은 권한을 지우고 관리자(S-1-5-32-544)·SYSTEM(S-1-5-18)만 남긴다. `readers`(계정 이름)가 있으면 `relay.key` 에만 읽기를 더한다. `ensure_keys` 가 켤 때마다 부른다 (`/reset /T` 뒤에도 같은 상태로). 실패해도 서버는 켜진다.
  - **Claude 판단 - `readers` 의 기본은 빈 값 (relay.key 도 관리자·SYSTEM 만):** 옵저버·ACTOR 는 지금 관리자 권한으로만 돈다 (위 '확인한 사실'). 일반 사용자에게 열면 같은 PC 의 다른 프로그램이 인증번호 창구 열쇠를 읽는다. 일반 권한으로 돌려야 하는 길이 확인되면 작업을 등록한 윈도우 계정 하나를 `readers` 에 넣는다 (모든 사용자에게는 열지 않는다).
- 창 (스탠드얼론일 때만 달라진다 - 지금 창의 칸·테두리 모양 그대로):
  - 맨 위 `라이선스` 칸: 맞으면 `업체 <이름> · 발급일 <날짜>` 와 `PC 번호 <…>`, 단추 `라이선스 파일 선택`. 없거나 틀리면 붉은 글 `라이선스 파일이 없습니다. 아래 PC 번호를 공급사에 보내 라이선스 파일(license.json)을 받은 뒤 [라이선스 파일 선택]을 눌러 주십시오.`(틀리면 `LicenseError` 글), `PC 번호 <…>`, 단추 `PC 번호 복사`(tkinter 클립보드)·`라이선스 파일 선택`.
  - `업체 웹 관리자 계정` 칸: 계정이 없으면 `아이디`·`비밀번호`·`비밀번호 확인` 과 안내 `업체 웹에 로그인할 관리자 계정입니다. 처음 로그인하면 비밀번호를 바꾸게 됩니다.` [저장] 은 이 칸이 차 있으면 `create_admin` 을 먼저 부른다. 있으면 `관리자 계정: <아이디>` 와 단추 `관리자 비밀번호 다시 정하기` → 작은 창(관리자 아이디 고르기·새 비밀번호·확인) → `관리자 비밀번호를 다시 정하였습니다. 다음 로그인 때 새 비밀번호로 바꾸게 됩니다.`
  - `대시보드 연결` 칸 없음. 시험용 빌드면 창 제목 `오토파일럿 설정 (시험용 빌드)`.

- [ ] **Step 1: 실패하는 시험** `tests/test_settings_standalone.py` (`RPA_EDITION=standalone`, 임시 `RPA_PROGRAMDATA`, 시험 열쇠로 만든 라이선스, 가짜 `run`·`login`). 검사:
  - `license_state`: 없음·다른 PC·맞음 (글·`pc_id`·`company`). `install_license`: 맞는 파일은 옮겨지고, 다른 PC 의 파일은 `LicenseError` + 있던 라이선스 그대로.
  - `create_admin`: 만든 계정이 `Accounts.verify` 로 맞고 `must_change`, 비밀번호 다름·7자·같은 아이디 두 번은 `ValueError`. `reset_admin_password`: 옛 비밀번호 틀림·새 비밀번호 맞음·`must_change`, 관리자 권한 아님(가짜 `is_admin`) → `PermissionError`, 유저 계정 → `ValueError`.
  - `save` 스탠드얼론: `login` 이 불리면 실패, `warm_roots` 가 불리면 실패, 라이선스 없음·계정 없음은 `ValueError` 이고 파일을 쓰지 않는다, 맞으면 설정 쓰기·작업 등록·에이전트 켜기. `validate` 가 업체코드 빈 값을 문제 삼지 않는다.
  - `configured`: 라이선스·계정·설정 셋 중 하나라도 없으면 `False`, `agent_config.json` 이 없어도 `True`.
  - `stop_agent`: 가짜 프로세스 목록에 설치 폴더의 `local_server.py` 가 남아 있으면 끝내기를 부르고, 끝내 남으면 6.
  - `lock_key_files`: 가짜 `run` 이 받은 icacls 인자 (세 파일, 관리자·SYSTEM SID, `readers` 가 있을 때 `relay.key` 에만 `:R`). 진짜 임시 폴더에서 한 번 돌려 `icacls` 출력에 `Users`·`Everyone` 이 없다.
  - 일반 버전: `rows(False) is ROWS`, `test_settings.py` 그대로 통과.
- [ ] **Step 2: 실패 확인.**
- [ ] **Step 3: 구현.** 일반 경로의 줄은 옮기지 않고 스탠드얼론 가지만 더한다. 옵저버·ACTOR 가 일반 권한으로 도는 길이 있는지 한 번 더 확인하고 (`rpa_observer.main`, `web_runner.load_config` 가 읽는 폴더) 결과를 커밋 글에 적는다.
- [ ] **Step 4: 통과 확인** + `check_settings_ui.py`. 스탠드얼론 창 사진(라이선스 없음 / 설정 끝)을 찍어 사용자에게 보인다 (사진은 스크래치 폴더 - 뒤에 열린 창이 찍히지 않게).
- [ ] **Step 5: 커밋** - "스탠드얼론 ③ Task 4 - 설정 창 (라이선스 고르기·관리자 계정·비밀번호 다시 정하기), 설치 마무리, 열쇠 파일 권한".

### Task 5: 설치 파일 · PC 번호 확인 · 안내 파일

**Files:**
- Modify: `release/installer.iss`, `tests/test_encoding.py` (bat 목록)
- Create: `release/PC번호_확인.bat`, `release/배포안내_스탠드얼론.txt`
- Test: `tests/test_installer_edition.py` (새로 - 글자 검사), `tests/test_encoding.py`

**Interfaces:**
- Produces (`installer.iss` - `/DEdition` 이 없으면 `cloud` 이고 그때 지금 설치 파일과 같다):
  - 스탠드얼론 `AppId={{7D2E9A61-3B4F-4C8D-A5E2-91F0C6B3D7A4}` (이 값으로 못박는다 - 바꾸면 덮어 설치가 다른 제품이 된다), `AppName`·`UninstallDisplayName` = `오토파일럿 스탠드얼론` (`/DTestBuild=1` 이면 뒤에 ` (시험용)`). 설치 폴더·설정 폴더·시작 메뉴 이름은 일반 버전과 같다 (설계 6.1).
  - `[Dirs]` 에 `{commonappdata}\AFTER MARKET\RPA\standalone` (지울 때 남김). `[Files]` 의 `Excludes` 는 `\RPA_UserConfig.json,\배포안내_스탠드얼론.txt,\PC번호_확인.bat`. 대시보드 바로 가기 주소는 `/DDashboardURL`(= `http://127.0.0.1:8781/`).
  - `InitializeSetup()` (두 버전 종류 모두): 다른 버전 종류가 깔려 있으면 알리고 `False` (설치 파일의 종료 코드 1). 가리는 법 = 상대 `AppId` 의 제거 등록 키(`…\Uninstall\{<AppId>}_is1`, 64비트 보기)가 있거나, 프로그램 폴더에 `manifest.json` 이 있는데 `edition.json` 이 (스탠드얼론 설치 파일이면) 없다 / (일반 설치 파일이면) 있다.
    - 스탠드얼론 설치 파일: `이 PC 에는 오토파일럿 일반 버전이 설치되어 있습니다. 스탠드얼론 버전은 일반 버전이 없는 PC 에만 설치할 수 있습니다.`
    - 일반 설치 파일: `이 PC 에는 오토파일럿 스탠드얼론 버전이 설치되어 있습니다. 일반 버전은 스탠드얼론 버전이 없는 PC 에만 설치할 수 있습니다.`
    - 시험용이고 조용한 설치가 아니면 먼저 `시험용 빌드입니다. 고객 PC 에 설치하지 마십시오. 계속하시겠습니까?` ([아니요] 면 그만둔다).
  - 지울 때 묻는 글 (스탠드얼론): `지우면 저장된 비밀번호·프리셋·실행 기록·라이선스·웹 계정이 모두 없어집니다. 다시 설치해서 계속 쓰려면 [아니요] 를 누르세요.`
  - `[Run]` 은 그대로 (`rpa_settings.py --after-install` - 처음이면 Task 4 의 창, 덮어 설치면 창 없이). 에이전트 계정 입력 단계는 없다.
- `release/PC번호_확인.bat` - 원격 브랜치 `observer-standalone` 의 같은 파일을 되살린다 (`git show origin/observer-standalone:release/PC번호_확인.bat` 의 바이트 그대로, 설명 줄만 고친다). 관리자 권한 없이 `reg query … MachineGuid /reg:64` → `이 PC 의 번호: <값>` → 클립보드 → `번호를 클립보드에 복사하였습니다. 이 번호를 담당자에게 보내 주십시오.` 못 읽으면 `PC 번호를 읽지 못했습니다. 담당자에게 문의하여 주십시오.` 와 종료 코드 1. 괄호 블록 없음.
- `release/배포안내_스탠드얼론.txt` (UTF-8, 우리 쪽 담당자용): ① PC 번호 받기(bat 또는 설치 끝 창) → `tools/make_license.py` 로 발급 ② 설치 차례 (라이선스 → 설정 → 관리자 계정) ③ 업데이트는 새 설치 파일을 그대로 덮어 설치 - 설정·기록·라이선스·계정은 남는다 ④ `프로그램 파일이 설치된 버전과 달라…` 가 뜨면 같은 버전 설치 파일로 다시 설치 ⑤ 윈도우를 다시 깔면 PC 번호가 바뀐다 - 라이선스 다시 발급 ⑥ 관리자 비밀번호를 잊으면 '오토파일럿 설정' 의 [관리자 비밀번호 다시 정하기] ⑦ 일반 버전과 같은 PC 에 깔 수 없다 ⑧ 파일 이름에 `TEST` 가 든 설치 파일은 고객에게 보내지 않는다.

- [ ] **Step 1: 실패하는 시험** `tests/test_installer_edition.py`: `installer.iss` 가 BOM 있는 UTF-8, 두 `AppId` 가 서로 다르고 일반 것은 지금 값(`C3F7A2B4-…`), `Edition` 이 없을 때의 기본이 `cloud`, 위 알림 글 셋·지울 때 글이 있다, 스탠드얼론 가지에만 `standalone` 폴더, `[Run]` 두 줄이 가지 밖에 한 벌. `build_release.other_files("standalone")` 의 원본 둘이 저장소에 있다. `tests/test_encoding.py` 의 `BATS` 에 새 bat 을 넣고 (CP949·CRLF), 클립보드 줄을 뺀 사본을 `cmd /c` 로 돌려 `이 PC 의 번호:` 뒤 값이 `license_check.machine_guid()` 와 같다 (대소문자 무시).
- [ ] **Step 2: 실패 확인.**
- [ ] **Step 3: 구현.** `installer.iss` 는 `#if Edition == "standalone"` 가지로 (파일을 둘로 나누지 않는다 - `[Code]` 고침이 두 설치 파일에 같이 간다).
- [ ] **Step 4: 통과 확인** + `test_build_edition.py`·`test_build_release.py`.
- [ ] **Step 5: 커밋** - "스탠드얼론 ③ Task 5 - 설치 파일의 버전 종류 (다른 AppId, 다른 버전 종류가 깔린 PC 에서 멈춤), PC 번호 확인, 배포 안내".

### Task 6: 실제 빌드 · 샌드박스 `--standalone` · 일반 버전 확인

**Files:**
- Modify: `tools/sandbox_test.py`, `docs/superpowers/plans/2026-11-23-standalone-index.md` (상태)
- Create: `tools/sandbox_inner_standalone.ps1` (일반 버전의 `sandbox_inner.ps1` 은 고치지 않는다)
- Test: `tests/test_sandbox_standalone.py` (새로 - 준비 단계만), 실제 빌드, 샌드박스

**Interfaces:**
- Consumes: 위 모두, `tools/make_license.build_body`·`license_check.sign_body`.
- Produces (`sandbox_test`):
  - `SANDBOX_GUID = "5a17db0c-0000-4000-8000-000000000001"`, `BLOCK_HOSTS(server_info) -> [str]` - `server_info` 값으로 만든다: RTDB 주소의 호스트, `AUTH_HOST`·`TOKEN_HOST`·`FIRESTORE_HOST`, `<PROJECT_ID>.web.app`·`<PROJECT_ID>-releases.web.app`·`<PROJECT_ID>.firebaseapp.com`, `api.anthropic.com`, `fonts.googleapis.com`, `cdn.jsdelivr.net`.
  - `prepare_standalone(setup, work, cloud_setup=None, over_cloud=None)` - 작업 폴더에 `setup.exe`·`inner.ps1`·`license.json`(시험용 열쇠로 `SANDBOX_GUID`, 업체 `샌드박스상사`·`c_sbx`, 자동 실행 3줄)·`license_other.json`(다른 PC 번호)·`hosts_block.txt`·`trap.py`·`check_standalone.py` 를 둔다. 시험용 열쇠 파일 자체는 넣지 않는다.
  - CLI `sandbox_test.py --standalone [--cloud-setup <일반 설치 파일>] [--over-cloud <일반 설치 파일>] <AUTOPILOT_Standalone_TEST_Setup_<v>.exe>`. 이름에 `TEST` 가 없거나 옆에 `배포_SA_TEST_<v>.testkey.txt` 가 없으면 `시험용 빌드(--test-build)로 만든 설치 파일만 시험합니다` 를 찍고 2. 기다림 30분. 샌드박스는 한 번에 하나만 뜬다 - Step 6 의 넷은 차례로 따로 띄운다.
  - 배포 폴더 찾기 (지금 인자 `--update`·`--from` 도): 설치 파일이 있는 폴더의 `배포_<v>`(스탠드얼론은 `배포_SA_TEST_<v>`)를 먼저 보고, 없으면 지금처럼 `D:\AX` - `--out-root` 로 만든 일반 버전 확인 빌드를 시험할 수 있게.
- `sandbox_inner_standalone.ps1` 이 보는 것 (결과는 지금처럼 `out\results.txt`, 끝 줄 `실패: N`):
  0. 관리자 권한, 레지스트리 `MachineGuid` 를 `SANDBOX_GUID` 로 바꿈 (안 되면 그 자리에서 실패로 끝낸다), hosts 에 막을 주소 → `127.0.0.2`, 덫(`trap.py` - 127.0.0.2 의 80·443 을 듣고 붙을 때마다 한 줄) 띄움, 견줌으로 막은 주소 하나를 일부러 불러 덫이 1 을 세는지 본 뒤 0 으로.
  1. 조용한 설치 (코드 0). 있는 것: `edition.json`·`manifest.sig`·`firebase\web\index.html`·`fonts`·`app\license_check*.pyd`·뿌리의 `license_check*.pyd`·`firebase\agent\local_web.py`. 없는 것: `ai_rescue*`·`lib\anthropic`·`update_helper.py`·`firebase-config.js`·`data-firebase.js`·`license_check.py`·`클라우드_안내.txt`. `check_install` 이 `ok`, 앱 및 기능 이름 `오토파일럿 스탠드얼론 (시험용)`, 대시보드 바로 가기 주소 `http://127.0.0.1:8781/`.
  2. 라이선스 없음: exe 셋 `--check` 가 끝까지 가고 `라이선스: 라이선스 파일이 없습니다`, `ERPia_RPA.exe`·`Prepare_RPA.exe` 는 종료 코드 2. `license_other.json` 을 넣으면 2 와 `이 PC 의 라이선스가 아닙니다`. 맞는 `license.json` 을 넣는다.
  3. 설정 (창 없이): 사용자 설정 쓰기 + `rpa_settings.create_admin` → `--after-install --no-window` (코드 0) → 작업 등록, 감독 아래 로컬 서버·에이전트가 뜨고 8781 이 열린다, 에이전트 기록에 Firebase 로그인 시도가 없다.
  4. 권한: `standalone\agent.key`·`relay.key`·`accounts.json`·`license.json` 의 SID 가 관리자·SYSTEM 뿐.
  5. `check_standalone.py` (내장 파이썬, 127.0.0.1 만): `/` 200·CSP 머리글 → 로그인(`mustChange`) → 비밀번호 바꾸기 → 다시 로그인 → `/api/stream` 의 첫 `live` 에 `heartbeat` → `set_schedule` 명령이 `done` → `launch` 명령이 끝나고(샌드박스에는 ERPia 가 없어 PROCESS 는 곧 '중단') `/api/runs` 에 그 실행 한 줄.
  6. 변조: `rpa_dashboard.py` 끝에 한 바이트 → `Prepare_RPA.exe` 가 2 와 `프로그램 파일이 설치된 버전과 달라`. `app\license_check.py` 를 끼워도 2.
  7. 덮어 설치 (같은 설치 파일): 설치 기록에 `--stop -> 0`, 덮기 전 `local_server.py` 프로세스 없음, 끝난 뒤 변조가 풀려 `ok`, 5 에서 바꾼 비밀번호로 로그인되고 실행 기록·라이선스·자동 실행 설정이 남아 있다, 4 의 권한 그대로.
  8. `--cloud-setup` 을 줬으면: 그 일반 설치 파일을 조용히 돌려 코드 1, `edition.json`·로컬 서버가 그대로.
  9. 조용한 제거: 프로그램 폴더·작업 없음, 설정 폴더는 남음.
  10. 덫에 걸린 연결 0.
  - `--over-cloud` 일 때는 0 → 일반 설치 파일 설치 → 스탠드얼론 설치 파일이 코드 1 → 일반 설치가 그대로(`edition.json` 없음) → 10 만 본다.

- [ ] **Step 1: 실패하는 시험** `tests/test_sandbox_standalone.py`: `BLOCK_HOSTS` 가 `server_info` 로 만들어지고 `gstatic` 을 넣지 않는다, `prepare_standalone` 이 만든 `license.json` 이 그 빌드의 시험용 공개 열쇠·`SANDBOX_GUID` 로 `license_check.load` 를 통과하고 `license_other.json` 은 `이 PC 의 라이선스가 아닙니다`, 작업 폴더에 열쇠 파일이 없다, `TEST` 가 아닌 이름·열쇠 파일 없음은 2, 지금 인자(`--update`·`--from`·`--runtime`)의 동작은 그대로 (`test_sandbox_site.py` 통과). → 구현 → 통과. **여기까지는 샌드박스를 띄우지 않는다.**
- [ ] **Step 2: 사용자에게 알린다** - 고친 빌드·설치·샌드박스 파일 목록, 이제 할 일(빌드 둘·샌드박스 넷)과 어림 시간, 개발 PC 에는 설치하지 않는다는 것.
- [ ] **Step 3: 보관 폴더 채우기** - 워크트리에 `build\pyd_cache`·`build\launcher_cache` 가 없으면 `D:\AX\RPA\build` 의 같은 폴더를 **복사**한다 (원본은 읽기만). 조각의 재료 지문은 파일 내용·도구 버전만 보므로 안 바뀐 조각은 그대로 쓰인다.
- [ ] **Step 4: 시험용 빌드** - `D:/AX/RPA/.venv/Scripts/python.exe tools/build_release.py --edition standalone --test-build` → `D:\AX\배포_SA_TEST_<v>\`·`.zip`·`AUTOPILOT_Standalone_TEST_Setup_<v>.exe`. 이어서 `tests/test_standalone_offline.py --release D:\AX\배포_SA_TEST_<v>` (만든 폴더의 우리 파일·조각 바이트에 `BLOCKED` 없음, `lib.zip` 에 `anthropic/` 없음).
- [ ] **Step 5: 일반 버전 확인 빌드** - `… tools/build_release.py --modules --out-root D:\AX\SA_build_check` (`D:\AX` 의 버전 번호·옛 폴더를 건드리지 않는다). 버전 목록의 파일 이름을 `D:\AX\배포_2026.11.23-2\manifest.json` 과 견준다 - 더해진 것은 계획 ① 이 일반 목록에 넣은 파일(`local_store`·`local_server`·`edition`·`license_check`)과 그 조각, `app\ap_guard` 조각뿐, 빠진 것 없음, `lib.zip` 지문이 같다.
- [ ] **Step 6: 샌드박스 (차례로 하나씩)** - ① `sandbox_test.py --standalone --cloud-setup <Step 5 의 설치 파일> <Step 4 의 설치 파일>` ② `sandbox_test.py --standalone --over-cloud D:\AX\AUTOPILOT_Setup_2026.11.23-2.exe <Step 4 의 설치 파일>` ③ `sandbox_test.py --update <Step 5 의 설치 파일>` ④ `sandbox_test.py --from D:\AX\AUTOPILOT_Setup_2026.11.23-2.exe <Step 5 의 설치 파일>`. 모두 `실패: 0`. 실패는 원인을 찾아 해당 Task 의 파일을 고친다 (시험을 고치지 않는다).
- [ ] **Step 7: 끝 정리** - 스탠드얼론 시험 모두 + 일반 버전 시험, 계획 목록의 ③ 상태를 고친다. `D:\AX\SA_build_check` 는 사용자에게 물어 지운다.
- [ ] **Step 8: 커밋** - "스탠드얼론 ③ Task 6 - 샌드박스 --standalone (설치·라이선스·로그인·명령·기록·변조·덮어 설치·막은 주소 시도 0), 시험용 빌드 확인".

---

## 범위 밖

- 인증번호 2분 만료의 서버 쪽 지우기, 휴대폰 포트·방화벽 규칙·자체 서명 인증서 - 계획 ④.
- `runs.db` 보관 기간 - 사용자 확인 뒤 정한다 (계획 ⑤ 보안 자료의 '보관 기간' 과 같은 값으로).
- 사용설명서·보안 자료 - 계획 ⑤. 실제 PC 한 대 설치 확인 - 진짜 열쇠 빌드 뒤 사용자와.

## 사용자 확인 (기다리지 않고 기본값으로 진행한다)

| # | 정할 것 | 기본값 |
|---|---|---|
| 1 | 진짜 빌드 - `tools/make_license.py --keygen` 뒤 공개 열쇠를 `license_check.LICENSE_PUBLIC_KEY_HEX` 에 넣고, `build_release.py --edition standalone` 을 돌린다 (두 열쇠 파일을 읽는다) | 사용자가 돌린다. 그 전까지 Claude 는 `--test-build` 만 |
| 2 | 빌드·설치·샌드박스 파일 고침 (`tools/build_release.py`·`release/installer.iss`·`tools/sandbox_test.py`·새 `sandbox_inner_standalone.ps1`·`rpa_settings.py`) | Task 시작 때 목록을 알리고 진행 |
| 3 | PC 를 하나 더 묶기 (메인보드 UUID) | 이번 버전은 넣지 않는다 (Task 3 의 추천) |
| 4 | `relay.key` 를 일반 사용자에게 열기 | 열지 않는다 (관리자·SYSTEM 만) |
| 5 | 일반 버전에도 닿는 고침(`server_info` 의 주소 셋, `fb.py`·`background.py`, AI 없으면 끔, `ap_guard` 부르는 줄, 일반 설치 파일의 '스탠드얼론이 깔린 PC' 멈춤)을 develop 에도 옮길지 | StandAlone 에만 둔다 |
| 6 | 앱 및 기능에 보이는 이름 | `오토파일럿 스탠드얼론` |
| 7 | 관리자 계정의 아이디·첫 비밀번호 | 설치하는 사람이 정하고 첫 로그인에 바꾼다 |
| 8 | Task 6 에 드는 것 - 빌드 둘, 샌드박스 넷 (한 번에 하나) | 시작 전에 어림 시간을 알리고 진행 |
