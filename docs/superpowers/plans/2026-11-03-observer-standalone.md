# 옵저버 단독 버전 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ERPia 없이 옵저버(기록) + ACTOR(재생)만 쓰는 설치 파일과, 그 PC 에서만 여는 로컬 관제 화면(프리셋 지정 예약·수동 실행)을 만든다.

**Architecture:** 같은 저장소의 공용 코드에 '단독' 표시 하나(`rpa_status.standalone()`)를 두고, 켜졌을 때만 폴더·잠금·예약 줄·인증 처리를 단독용으로 바꾼다. 관제 서버 `observer_hub.py` 는 `rpa_dashboard.py` 의 예약기·띄우기·기록 함수를 import 해서 쓰고 화면과 API 만 새로 둔다. 빌드는 같은 exe 로 설치 파일을 하나 더 만든다.

**Tech Stack:** Python 3.14 (내장 런타임), Playwright(깔린 Edge), http.server, tkinter(옵저버), Inno Setup 6, 순수 html/js/css.

**Spec:** docs/superpowers/specs/2026-11-03-observer-standalone-design.md

## Global Constraints

- 단독 표시가 꺼져 있으면 오토파일럿 동작은 한 글자도 바뀌지 않는다 - 기존 시험(`tests/test_*.py`, `firebase/tests/check_web.py`) 그대로 통과.
- 단독 표시: 설치 폴더(`program_dir()`)에 `OBSERVER_STANDALONE` 파일이 있거나 환경 변수 `RPA_STANDALONE=1` (시험용).
- 단독 폴더: `%ProgramData%\AFTER MARKET\Observer` (config·data), 설치 `Program Files\AFTER MARKET\Observer`.
- 관제 서버: `127.0.0.1` 에만, 기본 포트 `8775`, 쓰고 있으면 `8776`~`8784` 중 빈 것. 로그인 없음. 쓰기 요청은 Host 가 `127.0.0.1:<포트>`/`localhost:<포트>` 이고 Origin 이 없거나 같은 주소일 때만.
- 사람 인증 대기 `OTP_MANUAL_WAIT = 300` 초, 인증 한 번에. 재생기는 문자를 다시 보내지 않는다.
- 받은 파일 폴더 기본 `바탕화면\AI` (사용자가 관제 화면에서 바꾼다), 파일 이름 `(사이트코드)원래이름` 그대로.
- 단독 프리셋 수 한도 = `PRESET_MAX`(40), 동시 실행 창 한도 = `PARALLEL_MAX` - 업체 정책을 적어 줄 에이전트가 없다 (Claude 판단).
- 화면 글은 docs/ui-wording.md 업무 서식 말투. '판' 이 아니라 '버전'.
- 한글 .bat 는 CP949+CRLF. 파이썬 파일은 기존 줄 끝(CRLF) 유지.
- 시험은 `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe tests/<파일>.py` 꼴 단순 스크립트 (pytest 아님). 창을 띄우는 시험은 사용자에게 먼저 알린다.
- 설계서 4.2 의 `Observer_Hub.exe` 는 새 Nuitka exe 가 아니라 내장 `pythonw.exe` 를 그 이름으로 브랜딩한 사본(`BRANDED`)이 `observer_hub.py` 를 돌린다 (Claude 판단 - exe 를 하나 덜 빌드).

## Review Focus

1. 오토파일럿과 단독을 한 PC 에 깔았을 때 - 단독 예약이 오토파일럿 settings.json·프리셋·잠금을 읽거나 쓰면 안 된다 → Task 1 시험 `two_products_apart`.
2. 예약 줄에 고른 프리셋이 나중에 꺼졌거나(Stts 9) 지워졌을 때 - 그 프리셋만 빠지고 나머지는 돈다, 모두 빠지면 기록에 '돌릴 프리셋이 없습니다' → Task 5 시험 `slot_presets_gone`.
3. 다른 웹 페이지(브라우저의 아무 사이트)가 `http://127.0.0.1:8775/api/run` 으로 POST - 거절(403) → Task 6 시험 `foreign_origin_rejected`.
4. 사람 인증 대기 중 [중지] - 5분을 다 기다리지 않고 '사용자 중단' 으로 끝난다 → Task 3 시험 `manual_otp_cancel`.
5. 받은 파일 폴더를 없는 경로·쓸 수 없는 경로로 바꿈 - 저장 때 거절(글), 실행 중 못 만들면 그 실행만 실패로 기록 → Task 2·6 시험 `download_dir_bad`.

---

### Task 1: 단독 표시와 단독 폴더·잠금 (rpa_status)

**Files:**
- Modify: `rpa_status.py` (`install_root` 271, `status_dir` 134, `OBSERVER_LOCK` 1433, `preset_limit`, `parallel_limit`, `DEFAULT_SETTINGS`)
- Test: `tests/test_standalone.py` (새)

**Interfaces:**
- Produces: `standalone() -> bool`; `STANDALONE_FLAG = "OBSERVER_STANDALONE"`; `STANDALONE_DIRS = ("AFTER MARKET", "Observer")`;
  `download_dir_choice() -> str` (settings `prepare.download_dir`, 없으면 `os.path.join(find_desktop_dir(), "AI")`);
  `observer_lock_name() -> str` (단독이면 `r"Local\AFTER_MARKET_OBSERVER_SA"`, 아니면 지금 `OBSERVER_LOCK`).
- 단독이면: `install_root()` 는 `STANDALONE_DIRS` 아래, `status_dir()` 는 `os.path.join(data_dir(), "status")` (바탕화면 ERPIA_AI 를 안 쓴다),
  `preset_limit()` = `PRESET_MAX`, `parallel_limit()` = `PARALLEL_MAX`, `observer_open()` 은 `observer_lock_name()` 을 본다.
  `RPA_PROGRAMDATA`·`RPA_STATUS_DIR`·`RPA_OBSERVER_LOCK` 시험 환경 변수는 지금처럼 우선한다.

- [ ] **Step 1: 실패하는 시험** - `tests/test_standalone.py` (임시 폴더를 `RPA_PROGRAMDATA` 로, 환경 변수로 켜고 끈다)
  - `flag_off_same`: `RPA_STANDALONE` 없음·표시 파일 없음 → `standalone() is False`, `install_root()` 가 `...\AFTER MARKET\RPA` 로 끝남(RPA_PROGRAMDATA 없이 계산), `preset_limit()` == `PRESET_DEFAULT`.
  - `flag_on`: `RPA_STANDALONE=1` → `standalone()`, `install_root()` 가 `...\AFTER MARKET\Observer` 로 끝남, `status_dir()` == `os.path.join(data_dir(), "status")`, `preset_limit() == PRESET_MAX`, `observer_lock_name() == r"Local\AFTER_MARKET_OBSERVER_SA"`.
  - `flag_file`: `program_dir()` 를 임시 폴더로 바꾼 상태에서 그 안에 `OBSERVER_STANDALONE` 파일 → `standalone()`.
  - `download_default`: 설정에 값이 없으면 `download_dir_choice()` == 바탕화면\AI, 값이 있으면 그 값.
  - `no_tamper_block`: 단독이고 판 목록·서명이 없는 설치 폴더면 `install_block_reason()` 이 None (예약·실행이 '파일 변조' 로 막히지 않는다).
  - `two_products_apart` (Review Focus 1): `RPA_PROGRAMDATA` 없이 켬/끔 두 경우의 `config_dir()`·`settings_path()` 가 서로 다르다.
- [ ] **Step 2:** `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe tests/test_standalone.py` → 실패 (`standalone` 없음).
- [ ] **Step 3:** 위 Interfaces 대로 구현. `standalone()` 은 매번 계산(캐시 안 함 - 시험이 환경 변수를 바꾼다).
- [ ] **Step 4:** 새 시험 통과 + `tests/test_settings.py`, `tests/test_presets.py`, `tests/test_user_config.py`(있으면) 그대로 통과.
- [ ] **Step 5: Commit** `옵저버 단독 1 - 단독 표시·단독 폴더·잠금 (rpa_status)`

### Task 2: ACTOR 단독 실행 (web_runner)

**Files:**
- Modify: `web_runner.py` (`download_dir` 923, `_replay_problems` 382, 프리셋 실행 1430 근처, `main` 1893)
- Test: `tests/test_standalone.py` 에 더함

**Interfaces:**
- Consumes: Task 1 `standalone()`, `download_dir_choice()`.
- Produces: `RUN_PRESETS_ENV = "RPA_RUN_PRESETS"` - 값 `"1,3"` (프리셋 번호, 쉼표). `run_targets(all_flag: bool, sites: list|None, env: dict) -> list|None` - `--all` 이고 env 에 값이 있으면 `[status.preset_site_key(n) ...]`, 아니면 `sites` 그대로. 숫자가 아닌 값은 `ValueError`.
  Task 3 의 `Replayer.otp_manual` 에 넘길 콜백 `manual_otp_note(page, waiting: bool) -> None` (status.note 로 `"인증번호 입력 대기 - <프리셋 이름>"` / 대기 끝나면 `""`, 그리고 `page.bring_to_front()`).

- [ ] **Step 1: 실패하는 시험**
  - `run_targets_env`: `run_targets(True, None, {"RPA_RUN_PRESETS": "3,1"})` == `[preset_site_key(3), preset_site_key(1)]` 순서 그대로; env 없음 → `None`; `"a"` → ValueError.
  - `download_dir_standalone`: 단독이면 `download_dir()` == `download_dir_choice()`; 꺼지면 지금 값(ERPIA_AI_EXCEL).
  - `download_dir_bad` (Review Focus 5, 실행 쪽): 단독이고 설정 값이 만들 수 없는 경로(`"Q:\\없는드라이브\\x"`) → `download_dir()` 이 `RuntimeError("받은 파일 폴더를 만들 수 없습니다: …")`.
  - `no_phone_needed`: 단독이면 문자 인증 단계가 있고 휴대폰이 없는 사이트도 `_replay_problems` 가 휴대폰 문제를 내지 않는다; 꺼지면 지금 글 그대로.
- [ ] **Step 2:** 시험 실행 → 실패.
- [ ] **Step 3:** 구현.
  - `main`: `args.all` 일 때 `run_targets` 결과가 있으면 그 사이트만 `cmd_run` 에 넘긴다 (꺼진 프리셋은 지금처럼 cmd_run 이 막는다 - 아래 Task 5 가 미리 거른다).
  - 단독이면 문자 인증 사이트에 `otp_relay` 를 import 하지 않고 `rp.otp_manual = manual_otp_note` 로 둔다. 인증 차례 잠금 키는 휴대폰이 없으므로 `f"manual:{p['no']}"`.
  - 단독이면 `start_routine_together` 를 부르지 않는다 (지금도 ALL_RUN_ENV 가 없으면 안 부르지만 명시).
- [ ] **Step 4:** 새 시험 통과 + `tests/test_web_runner*.py`, `tests/test_parallel_collect.py`, `tests/test_otp_replay.py` 그대로 통과.
- [ ] **Step 5: Commit** `옵저버 단독 2 - ACTOR 프리셋 지정·받은 파일 폴더·휴대폰 없는 인증`

### Task 3: 재생기 사람 인증 (web_replay)

**Files:**
- Modify: `web_replay.py` (`Replayer.__init__` 1366, `_run_steps` 2182~2230, 상수 318 근처)
- Test: `tests/test_otp_manual.py` (새) - 가짜 사이트는 `tests/test_otp_replay.py` 가 쓰는 가짜 인증 사이트를 그대로 쓴다

**Interfaces:**
- Produces: `OTP_MANUAL_WAIT = 300`; `Replayer.otp_manual = None` (콜백 `(page, waiting: bool) -> None`);
  `Replayer._otp_by_hand(i: int, steps: list) -> int` - 사람이 넘기면 이어 갈 단계 번호(1부터)를 돌려준다.
  실패 글 `OTP_MANUAL_TIMEOUT = "인증번호 입력을 5분 동안 기다렸으나 다음 화면으로 넘어가지 않았습니다."`.
- 동작 (설계 4.4): `self.otp is None and self.otp_manual` 이고 `otp` 단계(source≠copy)에 닿으면 - 칸을 채우지 않고 콜백(waiting=True) → 0.5초마다
  `self._check_cancel()` 하며 '넘어감'(그 frame 주소 경로가 기록의 `url` 과 다르거나 인증번호 칸이 안 보임 - `_otp_rejected` 의 마지막 판정과 같은 기준)을 본다.
  넘어가면 콜백(waiting=False), 인증번호 단계와 바로 뒤 누르기 단계([확인], `otp_check` 로 쓰던 그 단계)를 `("ok", "사람이 입력")` 로 적고 그 다음부터.
  `OTP_MANUAL_WAIT` 를 넘으면 그 단계 실패(`OTP_MANUAL_TIMEOUT`), 다시 시도(OtpRetry) 없음. `otpSend` 단계는 지금처럼 기록대로 누른다(중계 열기만 안 함).

- [ ] **Step 1: 실패하는 시험** (headless Edge - 창 없음)
  - `manual_otp_pass`: `otp_manual` 콜백이 waiting=True 때 그 page 의 인증번호 칸에 맞는 번호를 넣고 [확인]을 누른다 → 재생 성공, 결과에 `"사람이 입력"` 두 줄, 콜백 호출 순서 `[True, False]`.
  - `manual_otp_timeout`: 콜백이 아무것도 안 하고 `OTP_MANUAL_WAIT` 를 시험에서 2초로 → 실패 글이 `OTP_MANUAL_TIMEOUT`, 가짜 사이트의 문자 발송 횟수 1 (다시 안 보냄).
  - `manual_otp_cancel` (Review Focus 4): 대기 중 `cancel` 이벤트를 켬 → 2초 안에 끝나고 결과 글이 `STOPPED`.
  - `relay_unchanged`: `otp` 중계 객체를 준 재생은 지금 결과와 같다 (`tests/test_otp_replay.py` 가 통과하는 것으로 갈음).
- [ ] **Step 2:** 실행 → 실패.
- [ ] **Step 3:** `_run_steps` 의 `elif s["kind"] == ...` 갈래 앞에 사람 인증 갈래를 둔다 (`how`·결과 적기는 갈래 안에서, 이어 갈 `i` 를 돌려받아 `continue`).
- [ ] **Step 4:** 새 시험 + `tests/test_otp_replay.py`, `tests/test_mail_otp_replay.py`, `tests/test_web_replay.py` 통과.
- [ ] **Step 5: Commit** `옵저버 단독 3 - 재생기 사람 인증 (5분, 다시 보내지 않음)`

### Task 4: 옵저버 단독 (rpa_observer)

**Files:**
- Modify: `rpa_observer.py` (`validate_presets` 693, 저장 화면 휴대폰 칸 792~817·`_load_phones` 948·`_fill_phone_box` 955, 안내 글 944)
- Test: `tests/test_presets.py` 에 단독 블록 더함

**Interfaces:**
- Consumes: Task 1 `standalone()`, `observer_lock_name()` (옵저버가 켤 때 잡는 잠금 이름).

- [ ] **Step 1: 실패하는 시험** - 단독이면 문자 인증 단계가 있고 휴대폰·발신번호가 빈 프리셋도 `validate_presets` 가 통과; 꺼지면 지금 글(`인증 휴대폰과 발신번호를 정해 주십시오`) 그대로. 옵저버가 잡는 잠금 이름이 `observer_lock_name()`.
- [ ] **Step 2:** 실행 → 실패.
- [ ] **Step 3:** 단독이면 휴대폰 칸 두 줄(인증 휴대폰·발신번호, 라벨 포함)을 grid 에 올리지 않고 `_load_phones` 스레드를 띄우지 않는다. 안내 글에서 휴대폰 문장을 뺀다. 저장 때 `phones` 는 넘기지 않는다.
- [ ] **Step 4:** `tests/test_presets.py`, `tests/test_observer_edit.py` 통과. (화면 확인은 Task 9 샌드박스·사용자 실화면)
- [ ] **Step 5: Commit** `옵저버 단독 4 - 저장 화면 휴대폰 칸 숨김·검사 끔`

### Task 5: 예약 줄에 프리셋 (rpa_dashboard)

**Files:**
- Modify: `rpa_dashboard.py` (`TARGETS` 390, `launch` 465, `normalize_slots` 636, `slot_target` 867, `launch_slot` 930, `schedule_view`)
- Test: `tests/test_standalone_schedule.py` (새, `DRY_RUN` 과 `LAUNCHED_ENV` 를 쓴다 - `tests/test_schedule_slots.py` 방식)

**Interfaces:**
- Consumes: Task 1, Task 2 `RUN_PRESETS_ENV`.
- Produces: 단독 줄 모양 `{at, days?, until?, rest_min?, presets?: [int]}` - `presets` 없으면 켠 프리셋 모두. `run`·`inv_sites` 는 단독이면 거절(`ValueError("옵저버 단독 버전에서는 모듈을 고를 수 없습니다.")`).
  `slot_presets(slot) -> list[int] | None` - 지금 켜져 있고 한도 안인 번호만 남김 (`st.preset_summary()` 의 `on`·`no`), `None` 이면 '모두'.
  `launch(target, by, env=None)` 는 단독이면 `"prepare"` 만 받는다 (`all`·`routine` → `ValueError`).

- [ ] **Step 1: 실패하는 시험**
  - `slot_presets_ok`: 단독, `presets: [3, 1, 3]` → 저장 값 `[1, 3]`; `[]`·`[0]`·`[41]`·`["1"]` → ValueError.
  - `slot_run_rejected`: 단독에서 `run` 이 있으면 ValueError (글 위와 같음). 꺼지면 지금 규칙 그대로(`test_schedule_slots.py` 통과).
  - `repeat_without_run`: 단독에서 `until` 줄은 `run` 없이 저장된다.
  - `launch_env`: 단독, 줄 `presets: [1, 3]` 로 `launch_slot` → `LAUNCHED == ["prepare:auto"]`, env 에 `RPA_RUN_PRESETS == "1,3"`; `presets` 없음 → env 에 그 키 없음.
  - `slot_presets_gone` (Review Focus 2): 프리셋 3 이 꺼짐 → env `"1"`; 모두 꺼짐 → `launch_slot` 이 `RuntimeError("돌릴 프리셋이 없습니다. 예약 줄의 프리셋을 확인하여 주십시오.")`, 예약기는 지금 `UNUSED_ONLY` 처럼 기록하고 다음 예약으로.
- [ ] **Step 2:** 실행 → 실패.
- [ ] **Step 3:** 구현 (단독 갈래는 함수 첫머리 `if st.standalone():` 한 곳씩). `TARGETS["prepare"]` 인자는 그대로 (`--all --no-keep-open`, 고른 프리셋은 env).
- [ ] **Step 4:** 새 시험 + `tests/test_schedule_slots.py`, `tests/test_dashboard*.py` 통과.
- [ ] **Step 5: Commit** `옵저버 단독 5 - 예약 줄에 프리셋, 단독은 ACTOR 만 띄움`

### Task 6: 관제 서버 (observer_hub.py)

**Files:**
- Create: `observer_hub.py`
- Test: `tests/test_observer_hub.py` (새 - 임시 `RPA_PROGRAMDATA`, `RPA_STANDALONE=1`, `rpa_dashboard.DRY_RUN = True`, 빈 포트)

**Interfaces:**
- Consumes: `rpa_dashboard` 의 `SCHEDULER`, `apply_schedule`, `schedule_view`, `launch`, `stop_rpa`, `any_rpa_running`, `launch_state`, `run_summary`, `history_stats`, `period_since`, `PERIODS`; `st.dashboard_snapshot`, `st.preset_summary`, `st.read_history`, `st.observer_open`, `st.read_settings`/`write_settings`.
- Produces (API, JSON):
  - `GET /` `/hub.js` `/hub.css` - `hub/` 폴더의 파일 (Task 7).
  - `GET /api/state` → `{snapshot, schedule, presets, running, observer_open, settings: {download_dir, parallel}, limits: {presets, parallel_max}}`
  - `GET /api/history?period=7|30|90` → `{summary, runs}` (rpa_dashboard 와 같은 모양), `GET /api/history/<run_id>` → 기록 하나
  - `POST /api/run {presets: [int] | null}` → `launch("prepare", "manual", env)`; 고른 번호 검사는 Task 5 `normalize`·`slot_presets` 와 같은 규칙
  - `POST /api/stop` → `stop_rpa()`
  - `POST /api/schedule` → `apply_schedule(body)`
  - `POST /api/settings {download_dir?, parallel?}` - 폴더는 만들어 보고 못 만들면 400 `"받은 파일 폴더를 만들 수 없습니다: <경로>"`
  - `POST /api/observer` → 설치 폴더의 `Prepare_Observer.exe` 를 띄운다 (이미 떠 있으면 409 `"옵저버가 이미 실행 중입니다."`)
  - `POST /api/open {run_id}` → 그 기록의 화면 사진 폴더를 탐색기로 연다 (경로는 기록에서만 - 요청 본문의 경로는 받지 않는다)
- 실행: `observer_hub.py [--port N] [--open] [--install-task | --remove-task]`. 뜰 때 실제 포트를 `data_dir()\hub_port.txt` 에 적는다.
  `--open`: hub_port.txt 의 주소를 기본 브라우저로 연다 (서버가 없으면 띄운 뒤 연다). `--install-task`: 작업 스케줄러 `오토파일럿 옵저버 관제` 를 로그온 시·현재 사용자·`InteractiveToken`·`HighestAvailable` 로 등록 (`rpa_settings.task_xml`/`register_task` 와 같은 XML 모양, 실행 파일은 설치 폴더 `Observer_Hub.exe observer_hub.py`).
- 보안: `HTTPServer(("127.0.0.1", port))`. 모든 POST 와 `/api/` GET 은 Host 검사, POST 는 Origin 검사 (Global Constraints). 본문 64KB 넘으면 413.

- [ ] **Step 1: 실패하는 시험**
  - `binds_loopback`: 서버 소켓 주소가 `127.0.0.1`.
  - `port_fallback`: 8775 를 미리 잡아 두면 8776 으로 뜨고 hub_port.txt 가 8776.
  - `foreign_origin_rejected` (Review Focus 3): `Origin: http://evil.example` POST `/api/run` → 403, `LAUNCHED` 비어 있음; Host `192.168.0.5:8775` → 403.
  - `run_presets`: `POST /api/run {"presets":[2]}` → 200, `LAUNCHED_ENV[-1]["RPA_RUN_PRESETS"] == "2"`; 옵저버 잠금을 잡은 상태 → 409 `"옵저버가 실행 중입니다. 옵저버를 종료한 뒤 실행하여 주십시오."`.
  - `schedule_roundtrip`: `POST /api/schedule` 줄 하나(presets [1]) → `GET /api/state` 의 schedule 에 그대로.
  - `download_dir_bad` (Review Focus 5, 저장 쪽): 만들 수 없는 경로 → 400 그 글, 설정 안 바뀜.
- [ ] **Step 2:** 실행 → 실패.
- [ ] **Step 3:** 구현. 서버 클래스는 `rpa_dashboard.DashboardServer` 처럼 `server_bind` 의 getfqdn 을 피한다.
- [ ] **Step 4:** 통과.
- [ ] **Step 5: Commit** `옵저버 단독 6 - 관제 서버 (127.0.0.1, 예약·실행·기록 API)`

### Task 7: 관제 화면 (hub/)

**Files:**
- Create: `hub/index.html`, `hub/hub.js`, `hub/hub.css`
- Test: `tests/check_hub_web.py` (새, Playwright headless - 창 없음. Task 6 서버를 DRY_RUN 으로 띄우고 가짜 프리셋·기록 파일을 둔다)

**Interfaces:**
- Consumes: Task 6 API 만 (Firebase 없음, 외부 스크립트·글꼴 없음 - 오프라인에서도 뜬다).
- 디자인: `firebase/web/index.html` 의 색 토큰(:root 변수)·카드·표·상태 알약·스위치·사이드 메뉴 CSS 를 옮겨 쓴다. 메뉴 다섯: 현황·프리셋·예약·기록·설정.
- 화면 글 (업무 서식): 제목 '옵저버 관제', 단추 [지금 실행]·[중지]·[옵저버 열기]·[적용], 사람 인증 대기 띠 `인증번호 입력 대기 - <프리셋 이름>. 열린 브라우저 창에 번호를 넣고 [확인]을 눌러 주십시오. (5분)`,
  예약 줄의 프리셋 고르기 '모든 켠 프리셋' / '고른 프리셋만' + 프리셋 칩, 예약 줄 문구는 `rpa-common.js` 의 `slotText` 처럼 `'09:00 프리셋 1·3'`.
- 3초마다 `/api/state` 를 다시 읽는다. 적용 안 한 예약 변경이 있으면 다시 읽어도 폼을 덮지 않는다 (`firebase/web/rpa-settings.js` 의 `scheduleDirty` 방식).

- [ ] **Step 1: 실패하는 시험** - `check_hub_web.py`:
  - 다섯 메뉴가 보이고 페이지 오류 없음.
  - 프리셋 표에 가짜 프리셋 2개(이름·사이트코드·켬/끔), 하나 고르고 [지금 실행] → `LAUNCHED_ENV` 에 그 번호.
  - 예약: 줄 추가 → '고른 프리셋만' → 칩 1 → [적용] → 서버 설정에 `presets: [1]`; 다시 읽어도 바뀜 없음으로 [적용] 비활성.
  - 상태 note 가 `인증번호 입력 대기 - …` 이면 띠가 보인다.
  - 받은 파일 폴더 저장, 잘못된 경로면 빨간 글.
  - 폰 폭(390px)에서 가로 스크롤 없음.
- [ ] **Step 2:** 실행 → 실패.
- [ ] **Step 3:** 구현.
- [ ] **Step 4:** 통과.
- [ ] **Step 5: Commit** `옵저버 단독 7 - 관제 화면 (오토파일럿 홈 디자인)`

### Task 8: 빌드·설치 파일 (build_release, release/observer.iss)

**Files:**
- Modify: `tools/build_release.py` (`BRANDED` 93, `collect` 218, `main` 563, `prune_local` 148)
- Create: `release/observer.iss`, `release/OBSERVER_STANDALONE` (빈 표시 파일), `release/옵저버_안내.txt`
- Test: `tests/test_build_release.py` 에 더함

**Interfaces:**
- Produces: `OBSERVER_EXES = ("Prepare_RPA.exe", "Prepare_Observer.exe")` (exe 는 Nuitka onefile 이라 제 import 를 안에 담는다);
  `OBSERVER_FILES` = `observer_hub.py` 와 그것이 import 하는 저장소 .py 전부 (`local_imports(observer_hub.py)` 로 구한다 - rpa_dashboard 가 rpa_update 를 부르므로 함께 들어간다), `hub/index.html`·`hub/hub.js`·`hub/hub.css`, `OBSERVER_STANDALONE`, `AFTER_MARKET_PREPARE.ico`, `AUTOPILOT_ACTOR.ico`, `playwright/node.exe`, 내장 `python/` + 브랜딩 `Observer_Hub.exe` (pythonw 사본, 설명 '오토파일럿 옵저버 관제').
  `collect_observer(out_dir, exe_dir, ...) -> list[str]`, `observer_setup_name(version) -> "AUTOPILOT_Observer_Setup_<ver>.exe"`, `build_observer_setup(out_dir, version) -> path`.
  판 목록(manifest)·서명·zip 은 만들지 않는다 (업데이트 없음).
- observer.iss: 설치 `{commonpf64}\AFTER MARKET\Observer`, `{commonappdata}\AFTER MARKET\Observer\config|data` (`uninsneveruninstall`, icacls 는 오토파일럿 iss 85~87 과 같게), 바로가기 '옵저버'·'옵저버 관제'(`Observer_Hub.exe observer_hub.py --open`), [Run] `--install-task` 후 작업 실행, [UninstallRun] `--remove-task`. 오토파일럿 iss 와 AppId 가 달라야 한다.

- [ ] **Step 1: 실패하는 시험** - 가짜 exe 폴더로 `collect_observer` → `ERPia_RPA.exe`·`firebase/agent`·`rpa_update.py`·`rpa_settings.py` 없음, `OBSERVER_STANDALONE`·`observer_hub.py`·`hub/index.html`·`python/Observer_Hub.exe` 있음; `observer.iss` 가 가짜 폴더로 컴파일된다(ISCC 있을 때); `prune_local` 이 옛 `AUTOPILOT_Observer_Setup_<옛 버전>.exe` 도 지운다.
- [ ] **Step 2:** 실행 → 실패.
- [ ] **Step 3:** 구현. `main` 은 오토파일럿 설치 파일 다음에 `배포_옵저버_<ver>` 폴더를 모아 단독 설치 파일을 만든다 (`--no-setup` 이면 둘 다 건너뜀).
- [ ] **Step 4:** `tests/test_build_release.py` 통과.
- [ ] **Step 5: Commit** `옵저버 단독 8 - 단독 설치 파일 (AUTOPILOT_Observer_Setup)`

### Task 9: 샌드박스 시험·문서

**Files:**
- Modify: `tools/sandbox_test.py` (`--observer <설치 파일>` 갈래), `docs/TODO.md`(남긴 것), `docs/ui-wording.md`(새 화면 글)
- Test: 샌드박스 실행

**Interfaces:**
- Consumes: Task 8 설치 파일.

- [ ] **Step 1:** `--observer` 갈래 - Windows Sandbox 안에서 조용히 설치 → 확인:
  `Program Files\AFTER MARKET\Observer\OBSERVER_STANDALONE` 있음, 작업 스케줄러 '오토파일럿 옵저버 관제' 등록, `hub_port.txt` 의 주소로 `/api/state` 200,
  샌드박스의 다른 IP 로는 연결 안 됨, `POST /api/schedule` 저장, `POST /api/run {presets:null}` → ACTOR 가 '프리셋 없음'으로 끝나고 기록 1줄,
  `ERPia_RPA.exe`·에이전트 파일 없음, 제거 뒤 시작 메뉴·작업 없음·`ProgramData\...\Observer\config` 남음.
- [ ] **Step 2:** `tools/build_release.py` 로 빌드 → `tools/sandbox_test.py --observer D:/AX/AUTOPILOT_Observer_Setup_<ver>.exe` 실패 0, 그리고 오토파일럿 `--update` 샌드박스도 실패 0 (Global Constraints 첫 줄).
- [ ] **Step 3:** 전체 단위 시험(`tests/test_*.py`, `test_import_step` 뺌)·`check_web.py`·`check_hub_web.py` 통과.
- [ ] **Step 4: Commit** `옵저버 단독 9 - 샌드박스 시험·문서`
