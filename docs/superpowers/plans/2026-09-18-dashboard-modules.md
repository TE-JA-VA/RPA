# 대시보드 '실행 모듈' 선택 (Plan B) 설계·구현 기록

> **상태 (2026-09-19):** 구현 + 사후 검증 반영 완료. 실기: 실제 대시보드로 적용→파일→`--check`→복원 20건, Login 만 켠 exe 실행(설정→파일→루틴 사슬) 성공. 시험: `test_dashboard_modules.py` 49건, `check_modules_ui.py` 37건(Playwright), `test_routine_modules.py` 106건, 회귀 4개. 검증에서 반영한 것: `RPA_CRED_FILE` 루틴 쪽 통일, `.tmp` 정리·재시도, 모듈 검증을 일정 저장 앞에, 전부 끔 거부, 스칼라 Routine 판정, 모르는 키 보존, 화면 포커스·repair 분리·바뀐 키만 전송·로그아웃 초기화·aria-label, 평균 소요는 전체 실행만, 붙기 실패 단계 표시.

**날짜:** 2026-09-18 (Plan A 루틴 모듈화 완료 직후, 실기 1회 확인 뒤)
**요청:** 환경설정 탭에서 **관리자만** 어떤 모듈을 쓸지 고르고, 대시보드가 `ERPIA_AI.txt` 의 `Routine` 섹션을 쓴다. 현황·이력에 모듈 상태를 보여준다.

## 결정

| 항목 | 결정 | 이유 |
|---|---|---|
| 저장 위치 | `ERPIA_AI.txt` 의 `Routine` 섹션만 read-modify-write | 루틴이 읽는 곳이 거기다(Plan A 결정 A2). settings.json 에 따로 두면 두 곳이 어긋난다 |
| 비밀번호 | 서버 응답·로그·오류 메시지에 절대 싣지 않는다. 헬퍼는 값만 꺼내고 나머지는 객체 그대로 다시 쓴다 | 파일에 ERPia PW 가 평문이다 |
| 쓰기 안전 | 쓰기 전 같은 폴더 `.bak`, 임시 파일에 다 쓴 뒤 `os.replace`, BOM 없는 UTF-8 | 반쯤 쓴 파일이 남지 않게. 메모장 기본 인코딩과 같게 |
| API | 기존 `POST /api/settings` 에 `modules: {키: bool}` 을 얹는다 (관리자 게이트, `X-RPA-Action`) | 화면의 '적용' 버튼 하나가 폼 전체를 대표하는 기존 규약 |
| 응답 | `settings_view` 에 `routine_modules: {items[{key,label,enabled(bool|None)}], problems[], file}` 추가, POST 응답에 `modules_changed` | 기존 키는 없애지 않는다 (열린 옛 탭 호환) |
| 화면 | 환경설정에 '실행 모듈' 카드(스위치 5개, **라벨만**, 설명 없음). 현황 카드에 '모듈' 5줄. 이력 상세에 모듈 목록 + 모듈 비트 | 사용자는 설명 문구를 싫어한다 (메모리) |
| 링 분모 | '설정에서 끔' 단계는 현황 링·이력 '단계' 열의 분모/분자에서 뺀다. 기준 문자열은 `rpa_status.OFF_NOTE` 하나 | 끈 실행이 '전체 성공 14/14' 로 보이던 문제 |
| 모듈 목록 상수 | `rpa_status.ROUTINE_CONFIG_MODULES` (대시보드는 pywinauto 를 못 들여와 run_routine 을 import 못 함). `run_routine.ROUTINE_MODULES` 와 시험으로 대조 | 단일 원천은 못 만들지만 어긋나면 시험이 잡는다 |
| 시험 격리 | `RPA_CRED_FILE` 환경변수로 `cred_file_path()`/`read_account()` 를 가짜 파일로 돌린다 | 시험이 실제 자격증명 파일에 쓰는 사고 방지 |
| 반영 시점 | 다음 실행부터 (루틴은 시작할 때 한 번 읽는다). 실행 중 변경을 막지 않는다 | 단순함 |

## 바뀌는 파일

- `rpa_status.py` — `OFF_NOTE`, `cred_file_path()` 의 `RPA_CRED_FILE`, `read_account()` 가 `cred_file_path()` 사용, `decorate()` 끈 단계 제외(steps_total/steps_done/current_index). (`ROUTINE_CONFIG_MODULES`, `read/write_routine_modules` 는 앞서 추가됨, 시험 23건)
- `rpa_dashboard.py` — `routine_modules_view()`, `apply_routine_modules()`, `/api/settings` POST 에 modules, `settings_view` 키, `run_summary` 끈 단계 제외 + `module_flags`/`modules`, 헤더 주석
- `run_routine.py` — `"설정에서 끔"` 리터럴 4곳 → `status.OFF_NOTE`
- `dashboard.html` — CSS `.st-no_target/.st-off`, 실행 모듈 카드, `MODULE_META`, `moduleItem`, `paintModules/moduleValues`, `isDirty/loadForm/applySettings/renderMe` 확장, `ensureCard/updateCard/openDetail` 모듈 표시, 권한 문구
- `tests/test_dashboard_modules.py` — 4절(서버 함수) 추가
- `tests/check_modules_ui.py` — 신규 Playwright 화면 시험 (8766, 가짜 자격증명 파일)

## 배포 주의

- 대시보드는 소스로 돈다(`대시보드_시작.bat`). exe 는 SentinelOne 이 망가뜨려 못 쓴다. **떠 있는 대시보드는 재시작**해야 새 `rpa_status`/서버 코드가 실린다. HTML 만 바뀌면 열린 탭에 '새로고침' 띠가 뜬다.
- 시연 배포 폴더(`D:\AX\배포_시연_20260918`)의 `rpa_dashboard.py / rpa_status.py / dashboard.html` 은 사용자가 말하기 전엔 바꾸지 않는다.
