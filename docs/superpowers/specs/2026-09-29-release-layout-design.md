# 배포판 구조 설계 - 1부: 판 구조

**날짜:** 2026-09-29
**상태:** 구현됨 (2026-09-29, 첫 판 2026.09.29-1). 설계는 같은 날 사용자 승인
**이 문서는 결정 기록이다.** 무엇을 왜 그렇게 정했는지 남긴다. 구현하며 바뀌면 여기에 날짜와 함께 고쳐 적는다.

전체 작업은 세 부분이고, 이 문서는 그 첫째다.

| 부 | 하는 일 | 문서 |
|---|---|---|
| **1부 판 구조** | 파일을 프로그램·설정·기록으로 나누고, 판 번호와 판 목록을 만들고, 두 exe 를 Nuitka 로 만든다 | 이 문서 |
| 2부 설치 마법사 | 새 PC 에 이 구조대로 설치하고 설정을 입력받는다. 기존 PC 를 새 자리로 옮긴다 | 나중에 |
| 3부 자동 업데이트 | 에이전트가 새 판을 받아 프로그램 파일만 바꾼다 | 나중에 |

2·3부가 이 구조에 무엇을 기대는지는 10절에 적었다.

## 0. 왜 하나

- 새 PC 마다 사람이 직접 설치한다 (압축 풀기, `RPA_UserConfig.json` 고치기, 에이전트 첫 실행). 판을 고칠 때마다 PC 에 파일을 손으로 넘긴다. 담당자가 없으면 둘 다 멈춘다.
- 지금 배포 폴더는 프로그램·설정·기록이 한 폴더에 섞여 있다. 그래서 자동 업데이트가 무엇을 바꾸고 무엇을 둬야 하는지 가를 수 없다.
- 배포 파일로 소스가 샌다. `.py` 다섯 개(약 3,600줄)가 평문으로 가고, 두 exe 속 코드(`run_routine` 5,900줄 등)도 PyInstaller 자체 도구(`pyi-archive_viewer`)로 목록이 나오며 무료 도구로 대부분 되살릴 수 있다 (2026-09-29 확인). 비밀번호·서비스 계정 키·다른 업체 자료는 새지 않는다 - 새는 것은 ERPia 를 다루는 노하우다.
- 부수 문제: 지금 배포판을 손으로 조립하다 `__pycache__`·기록 파일이 압축에 섞인 적이 있고 (2026-09-28), 배포 틀 `RPA_UserConfig.json` 에 우리 업체 ERPia 로그인이 평문으로 들어 있었다.

## 1. 확정한 결정

| 항목 | 결정 |
|---|---|
| 소스 보호 | **핵심만 단단히.** 노하우가 든 `ERPia_RPA.exe`·`Prepare_RPA.exe` 를 Nuitka(파이썬 → C → 기계어) 로 만든다. 에이전트 같은 연결 코드(`.py`)는 그대로 두어 업데이트를 작게 유지한다. 기술 보호와 별도로 계약서에 복제·역분석·재배포 금지 조항을 두길 권한다 |
| 설치 위치 | 프로그램 `C:\Program Files\AFTER MARKET\RPA\`, 설정 `C:\ProgramData\AFTER MARKET\RPA\config\`, 기록 `C:\ProgramData\AFTER MARKET\RPA\data\`. 바탕화면 `ERPIA_AI` 는 그대로 |
| 권한 | `C:\ProgramData\AFTER MARKET\RPA` 는 Administrators·SYSTEM 만 읽고 쓴다. 거는 것은 2부 설치 마법사 |
| 판 교체 방식 | **A안 제자리 교체.** 프로그램 폴더는 하나, 바뀐 파일만 덮어쓴다 |
| 판 번호 | `YYYY.MM.DD-N` (그날 N 번째 판) |
| 판 목록 | 프로그램 폴더의 `manifest.json`. 우리가 고치는 파일마다 SHA-256 지문, python·브라우저는 이름표만 |
| 손으로 넣기 | 언제나 된다. 파일을 덮어쓰고 에이전트를 다시 켠다. `manifest.json` 도 같이 넣으면 새 판으로 알아본다. 자동 업데이트가 망가졌을 때의 마지막 복구 수단이라 없애지 않는다 |
| 기존 PC | 새 자리에 `config` 폴더가 없으면 지금 구조 그대로 돈다. 옮기는 것은 2부 |
| 판 표시 | 에이전트가 켤 때 점검해 PC 현황에 올리고, 화면 상태 카드에 한 줄 보인다 |

**고르지 않은 것**
- 판마다 폴더(B안, `versions\<판>\` + "지금 판" 표시): 한 번에 넘어가고 되돌리기 쉽지만, 에이전트를 띄워 주는 시작 프로그램이 따로 필요하고 손으로 넣기가 지금보다 복잡해진다. A안의 켤 때 점검 + 백업(3부)으로 거의 같은 효과를 낸다.
- 에이전트까지 전부 Nuitka: 가장 단단하지만 고칠 때마다 PC 마다 수십 MB 를 받아야 한다. 무료 요금제 Hosting 전송량은 하루 360MB 다.
- 한 폴더(`C:\AX_RPA\`)나 설치 때 고르기: 일반 사용자가 쓸 수 있는 폴더라, 그 PC 의 누구든 파일 하나를 바꿔 관리자 권한으로 실행시킬 수 있다. 설치 때 고르면 업데이트·원격 지원도 PC 마다 달라진다.

## 2. 파일 배치

### 프로그램 `C:\Program Files\AFTER MARKET\RPA\`

| 파일 | 판 목록 |
|---|---|
| `ERPia_RPA.exe`, `Prepare_RPA.exe` (Nuitka) | 지문 |
| `Run_All.bat` | 지문 |
| `rpa_status.py`, `rpa_dashboard.py` | 지문 |
| `firebase\agent\agent.py`, `fb.py`, `secret.py`, `에이전트_시작.bat` | 지문 |
| `python\` (내장 파이썬), `ms-playwright\` (브라우저) | 이름표만 (`runtime`) |
| `manifest.json` | 목록 자신 |
| `배포안내.txt`, `클라우드_안내.txt` | 넣지 않음 (문서) |
| `RPA_UserConfig.json` (빈 배포 틀) | 넣지 않음 (설정. 옛 구조로 손으로 설치할 때 채워 쓰는 틀) |

`firebase\agent\` 는 지금 모양 그대로 둔다. `에이전트_시작.bat` 이 두 단계 위 `python\` 을 찾는 규칙도 그대로다.

### 설정 `C:\ProgramData\AFTER MARKET\RPA\config\`
- `RPA_UserConfig.json` - ERPia 로그인·물류·실행 모듈·프리페어 사이트·ERPia 위치. 비밀번호는 DPAPI 로 잠김
- `agent_config.json` - 기계 계정. 비밀번호는 DPAPI 로 잠김

### 기록 `C:\ProgramData\AFTER MARKET\RPA\data\`
- 에이전트: `queue.jsonl`, `history_pos.txt`, `에이전트_기록.txt`
- RPA: `run_routine_result.txt`, `prepare_result.txt`, `perform_login_result.txt`, `sms_watch_log.txt`, 화면 사진 `web_*.png`
- `sessions\` - 프리페어가 남기는 비즈메카 로그인 세션(쿠키, **평문**)

### 그대로 두는 것
바탕화면 `ERPIA_AI\` (`ERPIA_AI_EXCEL\`, `ERPIA_AI_JOBS\`, `RPA_STATUS\`, 로그인 실패 기록). 사람이 여는 폴더라 옮기지 않는다.

### 지금 자리와의 대응

| 지금 (배포 폴더 = exe 옆) | 새 구조 |
|---|---|
| `RPA_UserConfig.json` | `config\` |
| `firebase\agent\agent_config.json` | `config\` |
| `firebase\agent\queue.jsonl`·`history_pos.txt`·`에이전트_기록.txt` | `data\` |
| `*_result.txt`, `sms_watch_log.txt`, `web_*.png`, `sessions\` | `data\` |

### 권한을 막는 이유
- `sessions\` 의 쿠키는 평문이다. 지금은 exe 옆이라 그 PC 의 누구나 읽는다.
- 설정의 `ERPia.ExePath` 를 바꿔치기하면 루틴이 관리자 권한으로 그 exe 를 띄운다.
- `C:\ProgramData` 는 기본값이 "모든 사용자 읽기" 라서 따로 막아야 한다 (2부). RPA·에이전트는 원래 관리자 권한으로 돌아서 막히는 것이 없다.
- 옛 구조의 PC 는 옮기기 전까지 이 위험이 그대로 남는다.

## 3. 자리 찾기 규칙 (`rpa_status` 한 곳)

지금은 `run_routine`, `web_runner`, `sms_watch`, `perform_login`, `rpa_status` 다섯 파일이 "exe 옆" 을 각자 계산한다. Nuitka 는 exe 위치를 알려 주는 방식이 PyInstaller 와 달라, 그대로 두면 다섯 곳이 한꺼번에 틀어진다. 그래서 `rpa_status` 에 넷을 두고 모두 이것만 쓴다.

**`program_dir()`** - 프로그램 폴더
1. Nuitka 로 컴파일됨 (모듈에 `__compiled__` 가 있음) → onefile exe 가 놓인 폴더. `__compiled__.containing_dir`, 없으면 `sys.argv[0]` 의 폴더 (1단계 시험에서 확인)
2. PyInstaller (`sys.frozen`) → `sys.executable` 의 폴더
3. 소스 → 이 파일의 폴더. 옆 `dist\Run_All.bat` 이 있으면 `dist` (개발 PC, 지금 규칙 그대로)

에이전트는 `rpa_status.py` 를 소스로 불러오므로 3번이고, 새 구조에서는 `Program Files\AFTER MARKET\RPA` 가 된다.

**`install_root()`** - 시험용 환경변수 `RPA_PROGRAMDATA` 가 있으면 그 폴더, 없으면 `%ProgramData%\AFTER MARKET\RPA`

**새 구조인가** = `install_root()\config` 폴더가 있는가. 이 폴더는 2부 설치 마법사만 만든다.

**`config_dir()`** - 새 구조면 `install_root()\config`, 아니면 `program_dir()`
**`data_dir()`** - 새 구조면 `install_root()\data` (없으면 만든다), 아니면 `program_dir()`

에이전트 파일은 옛 구조일 때 지금 자리(`firebase\agent\`)를 그대로 쓴다.

| 파일 | 새 구조 | 옛 구조 |
|---|---|---|
| `agent_config.json` | `config_dir()` | `firebase\agent\` |
| 큐·위치·에이전트 기록 | `data_dir()` | `firebase\agent\` |

**먼저 보는 환경변수** (지금 그대로, 규칙보다 앞선다): `RPA_USER_CONFIG`, `RPA_CRED_FILE`, `RPA_STATUS_DIR`, `RPA_AGENT_CONFIG`, `RPA_AGENT_QUEUE`.

**exe 쪽 네 파일** - 기록 파일·화면 사진·세션을 쓰던 각자의 `BASE_DIR` 을 지우고 `rpa_status.data_dir()` 을 쓴다. `web_runner` 가 exe 옆 `ms-playwright` 를 찾는 곳은 `program_dir()` 을 쓴다. 옛 구조에서는 둘 다 지금과 같은 폴더(exe 옆)라 동작이 바뀌지 않는다.

**`rpa_dashboard`** - 에이전트 안에서 소스로만 돈다 (옛 대시보드 exe 는 배포하지 않는다). 그래서 `app_dir()`·`run_command_path()` 는 그대로 둔다.

**주의** - 개발 PC 에 진짜 `C:\ProgramData\AFTER MARKET\RPA\config` 를 만들면 그 PC 가 새 구조로 넘어가 버린다. 새 구조 시험은 언제나 `RPA_PROGRAMDATA` 로 임시 폴더를 가리킨다.

## 4. 판 목록 `manifest.json`

```json
{
  "format": 1,
  "version": "2026.09.29-1",
  "built_at": "2026-09-29T15:00:00+09:00",
  "builder": "nuitka 4.2.2",
  "runtime": {"python": "3.14.7", "ms-playwright": ["chromium-1234", "chromium_headless_shell-1234", "ffmpeg-1011", "winldd-1007"]},
  "files": {
    "ERPia_RPA.exe": {"sha256": "…", "size": 21758227},
    "firebase/agent/agent.py": {"sha256": "…", "size": 31670}
  }
}
```
- 경로는 프로그램 폴더 기준, `/` 로 적는다.
- `files` 에는 2절 표의 "지문" 파일만 넣는다. 설정·기록·문서·배포 틀은 넣지 않는다 - 업데이트가 건드리면 안 되는 것들이다.
- `runtime` 은 이름표다. python·브라우저(약 700MB)는 거의 안 바뀌고, 켤 때마다 지문을 재면 느리다.
- `builder` 는 Nuitka 시험이 실패해 PyInstaller 로 돌아간 판을 알아보려고 적는다.
- 서명(`manifest.sig`)은 3부에서 붙인다. 이 형식은 서명을 위해 바꿀 것이 없다.

## 5. 판 점검

에이전트가 켤 때 한 번 `rpa_status.check_install()` 을 돈다. 프로그램 파일은 업데이트나 손으로 넣을 때만 바뀌고, 둘 다 에이전트를 다시 켜므로 켤 때 한 번이면 된다.

| 상태 | 조건 | 화면 |
|---|---|---|
| `ok` | 목록의 모든 파일이 있고 지문이 같다 | `2026.09.29-1` |
| `mixed` | 없거나 지문이 다른 파일이 있다 (몇 개만 손으로 넣음, 덮어쓰다 끊김) | `2026.09.29-1 · 다른 파일 2` |
| `none` | 목록이 없다 (옛 배포 폴더, 개발 PC) | `없음` |
| `error` | 점검 자체가 실패 (목록이 깨짐 등) | `확인 실패` |

- 목록에 없는 파일(`__pycache__` 등)은 무시한다.
- 결과: `{version, state, changed: [최대 10개], changed_count, checked_at}`, `error` 면 이유 `error` 도 (200자까지). `changed_count` 는 다른 파일의 전체 개수 - 화면의 "다른 파일 N" 에 쓴다 (2026-09-29 구현하며 더함). 에이전트가 PC 현황 `apps/rpa/live/{cid}/{pcId}/version` 에 PATCH 로 올린다. 그 자리는 이미 그 PC 에이전트만 쓸 수 있어 규칙은 바꾸지 않는다.
- 점검이 무슨 이유로든 실패해도 에이전트는 멈추지 않는다 (`error` 로 올리고 기록에 한 줄).
- **판 점검은 사고(섞임) 확인용이지 변조 방어가 아니다.** 파일과 목록을 같이 바꾸면 `ok` 가 나온다. 변조 방어는 3부의 서명이 맡는다.

## 6. 화면

RPA 화면 상태 카드 오른쪽(`#hero-side`)의 "연결"·"다음 자동 실행" 옆에 **"판"** 칸을 하나 더 둔다.
- 값은 5절 표의 화면 글자. `mixed` 면 다른 파일 이름을 칸의 `title`(마우스를 올리면 보이는 글)로 보여 준다.
- 상태 카드는 상태색으로 채워지고 글자색이 그 색을 따르므로, `mixed` 를 색으로 가르지 않고 글자로 알린다.
- 옛 에이전트는 `version` 을 올리지 않는다. 값이 없으면 `없음` 이다.

**고침 (2026-09-29, 사용자 요청)**: 칸을 넣으니 상태 카드가 너무 높아져서 위 배치를 바꿨다.
- 이름은 "판" 대신 **"버전"**. 사람이 보는 글(화면, 에이전트 기록의 `버전:` 줄, 안내 문서) 모두 같다. 코드·이 문서의 용어는 판 그대로
- 자리는 상태 카드가 아니라 **RPA 현황·기록 탭 줄 오른쪽 끝** (`#ver`). `ok` 는 `버전 2026.09.29-2` 회색, `mixed` 는 `버전 … · 다른 파일 N` 노란 글씨(마우스 글에 파일 이름), `error` 는 `버전 확인 실패` 노란 글씨. **`none`·값 없음은 아무것도 안 보인다** (위 5절 표의 `없음` 대신)
- 상태 카드는 "연결"·"다음 자동 실행" 두 칸으로 돌아가고, 폰 폭(640px 이하)에서는 두 칸을 상태 글 아래 한 줄로 왼쪽부터 놓는다
- "최신 버전입니다 / 업데이트가 있습니다" 문구는 3부에서 붙인다. 화면이 "내보낸 최신판" 을 알아야 하는데 그 번호를 올리는 곳이 3부에서 생긴다 (빌드했다고 곧 배포한 것은 아니다)

## 7. Nuitka 로 두 exe 만들기

- **도구**: Nuitka 4.2.2, 우리 PC 의 `.venv`(Python 3.14.7) 에만 넣는다. C 컴파일러는 Nuitka 가 처음 한 번 받아 온다. 고객 PC 에는 아무것도 깔리지 않는다.
- **모양**: onefile (exe 파일 하나), 콘솔 창. 지금처럼 켤 때 임시 폴더에 풀어서 돈다.
- **포함**: 지금 PyInstaller spec 이 모으는 것과 같다. 두 exe 모두 `comtypes`·`pywinauto`·`win32timezone`, 프리페어는 `playwright`(드라이버 포함)도.
- **확인할 함정**: pywinauto 의 UIA 는 `comtypes` 가 실행 중에 만드는 모듈을 쓴다. 컴파일된 exe 에서 그 모듈을 둘 자리가 있는지 1단계에서 본다.
- **빌드 시간**: 수 분~수십 분 예상. 판을 낼 때만 한다.

**1단계 작은 시험** (구현 계획의 첫 단계, 반나절 안)
1. 두 exe 가 만들어진다.
2. 두 exe 의 `--check` 결과가 지금(PyInstaller) exe 와 같다.
3. 루틴을 로그인만 켜서 실제로 한 번 돌려 성공한다.
4. Windows Defender 가 새 exe 를 막지 않는다.

하나라도 안 되면 **PyInstaller 를 유지한 채 1부의 나머지를 진행**하고, 보호 방법은 사용자와 다시 정한다. 3절의 자리 찾기 규칙은 둘 다 알아보므로 다시 고칠 것이 없다.

**1단계 시험 결과 (2026-09-29)**
- 결론: **Nuitka 사용.** 네 가지 모두 통과
- exe 자리: `__compiled__.containing_dir` = exe 가 놓인 폴더 (옮긴 폴더에서 실행해 확인). `sys.executable`·`__file__` 은 풀린 임시 폴더(`%TEMP%\onefile_*`), `sys.frozen` 은 없다 - PyInstaller 식으로 계산하면 틀린다
- 크기: ERPia_RPA.exe 16.8MB (PyInstaller 21MB), Prepare_RPA.exe 44.1MB (PyInstaller 61MB). 빌드 시간 약 6분·4분 (C 컴파일러 zig 0.16.0 을 Nuitka 가 처음 한 번 받아 옴, Visual Studio 는 필요 없음)
- `--check` 비교: 같음 (루틴 13줄, 프리페어 10줄. 실행 형태·기준 폴더 줄만 다름 - 2작업에서 고침)
- 로그인만 실행: 성공. 화면 조회(`--uiacheck`): PyInstaller exe 와 16줄 모두 같음 (comtypes 모듈 자리 문제 없음)
- Defender: 둘 다 위협 없음
- **새로 안 것**: Nuitka exe 는 출력을 파이프로 받으면 **UTF-8** 로 찍는다 (PyInstaller exe 는 CP949). 사람이 보는 콘솔 창은 둘 다 정상. 출력을 읽는 곳(빌드 스크립트의 `--check` 확인)은 두 인코딩을 다 본다
- 알림: Nuitka 가 "Windows Runtime DLL 을 넣지 못했다" 고 경고한다 - 받는 PC 에 UCRT 가 있어야 하는데 Windows 10·11 에는 기본으로 있다
- 쓴 옵션: 두 exe 모두 `--onefile --assume-yes-for-downloads --windows-console-mode=force --remove-output --include-package=comtypes --include-package=pywinauto --include-module=win32timezone` + 제외 목록(`--nofollow-import-to=` numpy·yaml·scipy·pandas·torch·cv2·matplotlib·networkx·graphify), 프리페어는 `--include-package=playwright --include-package-data=playwright` 를 더함

## 8. 빌드 스크립트

우리 PC 에서 명령 하나로 판을 만든다.
```
.venv\Scripts\python.exe tools\build_release.py [--builder nuitka|pyinstaller] [--to-dist]
```
**입력**
- 저장소의 소스
- 런타임 폴더 `D:\AX\runtime\` (`python\`, `ms-playwright\`). 처음 한 번 지금 배포판 `D:\AX\배포_20260928_3` 에서 복사해 만든다
- 빈 배포 틀 `release\RPA_UserConfig.template.json` - 저장소에 넣는다. 로그인·아이디·비밀번호·프린터는 비우고, 실행 모듈은 로그인만 켠다 (2026-09-28 새 업체용 틀과 같은 값)
- 안내 문서 `release\배포안내.txt`·`클라우드_안내.txt` - **UTF-8 (BOM 포함)**, 윈도우 메모장과 Mac 모두 바로 읽는다 (2026-09-29 사용자 요청으로 CP949 에서 바꿈)
- **`.bat` 두 개(`Run_All.bat`, `에이전트_시작.bat`)는 CP949 그대로.** UTF-8 + `chcp 65001` 로 바꿔 실제로 돌려 보니, cmd 가 한글 줄 뒤의 줄 위치를 잘못 세어 다음 줄 앞부분을 건너뛰고 나머지 조각을 명령으로 실행했다 (2026-09-29). `tests\test_encoding.py` 가 인코딩과 실제 실행(명령 창 오류 0줄)을 지킨다

**순서**
1. 두 exe 를 만든다.
2. 2절 프로그램 폴더 표의 파일(프로그램·문서·빈 배포 틀)만 `D:\AX\배포_<판 번호>\` 에 모은다. 표에 없는 것은 넣지 않는다.
3. 지문을 재서 `manifest.json` 을 쓴다.
4. `D:\AX\배포_<판 번호>.zip` 으로 압축한다 (압축 안 맨 위 폴더 이름도 같다).
5. 스스로 확인한다. 앞의 셋은 압축 자체를, 마지막은 풀어 놓은 사본을 본다.
   - 압축 안의 파일이 모은 목록과 같고 지문이 맞는지
   - 들어가면 안 되는 것이 없는지: `__pycache__`, `*.pyc`, `*_result.txt`, `sms_watch_log.txt`, `web_*.png`, `sessions\`, `agent_config.json`, `queue.jsonl`, `history_pos.txt`, `에이전트_기록.txt`, `*.old`, `*.bak`, `serviceAccountKey.json`
   - 배포 틀의 로그인·아이디·비밀번호가 비었는지
   - 두 exe 가 뜨는지: 압축을 임시 폴더에 풀고, 임시 설정(`RPA_USER_CONFIG`, `RPA_PROGRAMDATA` 를 임시 폴더로)으로 `--check` 를 돌려 끝까지 가는지 본다. 빈 설정이라 나오는 '문제' 줄은 무시한다

- **판 번호의 N**: 그날 이미 있는 `배포_<날짜>-*` 다음 번호
- **`--to-dist`**: 두 exe 만 이 PC 의 `dist\` 에 복사한다. 이 PC 는 `dist` 의 exe 로 실제 업무를 돌리므로, 복사할지는 사람이 정한다. `dist\` 의 설정 파일은 건드리지 않는다

## 9. 옛 PC 와 올리는 순서

새 코드는 옛 구조에서 지금과 똑같이 돈다 (설정·기록 = exe 옆, 에이전트 파일 = `firebase\agent\`). 그래서 올려도 지금 PC 들(이 PC, 노트북 pc_a 등)은 멈추지 않는다.

1. Nuitka 1단계 시험
2. 코드 수정과 시험
3. 빌드 스크립트로 첫 판을 만든다. 노트북에는 지금처럼 손으로 넘기고, 넘기는 파일에 `manifest.json` 이 더해진다. **이 개발 PC 의 `dist` 에는 두 exe 만 넣고 `manifest.json` 은 넣지 않는다** (2026-09-29 검토에서 고침) - 이 PC 의 `.py` 와 에이전트는 `dist` 가 아니라 저장소에서 돌아서, 목록을 넣으면 없는 파일 5개 때문에 늘 `mixed` 로 보인다. 개발 PC 는 `없음` 이 맞다 (5절)
4. 대시보드에서 PC 마다 판이 보이는지 본다
5. 2부 설치 마법사 (기존 PC 를 새 자리로 옮기는 일 포함)

## 10. 2·3부가 이 구조에 기대는 것

**2부 설치 마법사**
- `install_root()\config` 를 만들어 새 구조로 넘긴다. `C:\ProgramData\AFTER MARKET\RPA` 권한을 Administrators·SYSTEM 으로 막는다.
- 압축 내용을 `Program Files\AFTER MARKET\RPA` 에 둔다.
- 기존 PC 의 `RPA_UserConfig.json`·`agent_config.json` 을 `config\` 로 옮긴다. DPAPI 로 잠근 값은 같은 PC·같은 윈도우 계정이면 옮겨도 풀린다.
- 실행 모듈·로그인 정보·사이트 정보 입력, 기계 계정 로그인 확인, 윈도우 로그인 때 에이전트 자동 시작, 바로 가기.

**3부 자동 업데이트**
- `manifest.json` 에 서명(`manifest.sig`)을 붙이고, 에이전트는 공개키로 확인된 목록만 믿는다.
- `files` 의 파일만 바꾼다. `config\`·`data\` 는 절대 건드리지 않는다.
- 바꾸기 전에 바뀔 파일을 `data\backup\<판>\` 에 남긴다. 켤 때 점검이 `mixed` 면 (덮어쓰다 끊김) 백업으로 되돌린다.
- 업체·PC 별로 끄는 스위치를 둔다.
- 받는 곳은 우리 에이전트만 받을 수 있어야 한다. 공개 Hosting 에 두면 누구나 받아 가 지금보다 새기 쉽다.

## 11. 시험

**새로**
- 자리 찾기: 환경변수 / 새 구조(`RPA_PROGRAMDATA` 임시 폴더) / 옛 구조 / 개발 PC(`dist`) / PyInstaller(`sys.frozen`) / Nuitka(`__compiled__`) 흉내
- 판 점검: `ok`·`mixed`(지문 다름, 파일 없음)·`none`·`error`, `__pycache__` 무시, `changed` 는 10개까지
- 에이전트가 켤 때 `live.version` 을 올린다 (에뮬레이터 통합)
- 화면 "판" 칸: 네 상태와 값 없음, `mixed` 의 `title`
- 빌드 스크립트: 작은 가짜 입력으로 목록·압축·금지 파일 검사가 도는지 (exe 빌드는 빼고)

**그대로 통과해야 하는 것**: 대시보드 모듈 100, 루틴 모듈 107, 모듈 화면 37, 에이전트 단위 123, 통합 30, 화면 228, 규칙 24, 관리 스크립트 23

**실기**: Nuitka exe 로 `--check` 와 로그인만 켠 루틴 한 번, 빌드 스크립트가 만든 압축을 임시 폴더에 풀어 옛 구조로 `--check`

## 12. 범위 밖

설치 마법사, 자동 업데이트·서명·받는 곳, 권한 걸기, 자동 시작, 기존 PC 옮기기 (모두 2·3부). 계약서 조항은 사용자가 정한다.

## 13. 위험

| 위험 | 대응 |
|---|---|
| Nuitka 가 우리 라이브러리·파이썬 3.14 와 안 맞음 | 1단계 시험, 반나절 넘으면 PyInstaller 유지 |
| 보안 프로그램이 새 exe 를 오진 | 1단계에서 Defender 확인. 고객 PC 의 SentinelOne 등은 예외 등록 요청 (지금 exe 도 같은 처지) |
| 개발 PC 가 실수로 새 구조로 넘어감 | 시험은 언제나 `RPA_PROGRAMDATA`. 진짜 `ProgramData` 폴더는 2부 설치 마법사만 만든다 |
| 옛 구조 PC 의 세션 쿠키가 누구에게나 읽힘 | 지금과 같은 상태. 2부로 옮기면 막힌다 |
