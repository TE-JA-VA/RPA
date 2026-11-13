# 자동 실행 [지금 실행]·수집 사이트 [+ 추가]·시각 입력·프리셋 찾기 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 자동 실행 시각 줄을 그 설정 그대로 한 번 돌리는 [지금 실행]을 넣고, 수집 사이트·시각 입력·쇼핑몰 프리셋 목록을 사이트가 많은 업체도 쓰기 쉽게 바꾼다.

**Architecture:**
- PC 쪽은 두 곳만 바꾼다.
  - 에이전트 `do_launch` 가 `target: "slot"` 을 받는다. 받은 줄을 `normalize_slots` 로 검사하고 `launch_slot` 으로 띄운다.
  - `SCHEDULE_VERSION` 을 10 으로 올린다.
- 웹은 `firebase/web/rpa-settings.js` 한 파일과 `index.html` 의 스타일만 바꾼다.
- 시안의 동작을 그대로 옮긴다:
  - `mock/body.html` → 자동 실행
  - `mock/preset_body.html` → 쇼핑몰 프리셋

**Tech Stack:** Python 3.14 (에이전트·PC), 바닐라 JS ES 모듈 (웹), Playwright + Firebase 에뮬레이터 (화면 시험)

**Spec:** docs/superpowers/specs/2026-11-13-schedule-row-run-design.md

## Global Constraints

- 데이터베이스 규칙은 바꾸지 않는다. 명령은 `launch` 하나에 `{target: "slot", slot}` 로 싣는다.
- 웹은 `live.schedule.version >= 10` 인 PC 에만 [지금 실행]을 보인다 (`isV10`).
- 수집 사이트를 비우면 `sites` 를 보내지 않는다 (판 9 저장 모양 그대로).
- 화면 글 (시안 그대로):
  - `지금 실행`, `+ 추가`, `켠 사이트 전체 (N개)`
  - `엑셀 비밀번호 설정`, `취소`
  - `프리셋 N개`, `N개 중 M개 표시`
  - `이름·코드·번호로 찾기`, `사이트 이름·코드로 찾기`
  - `시각을 확인하여 주십시오. (예: 09:30)`
- 키보드로 치는 시각은 1분 단위다. ↑ ↓ 는 5분 칸에 맞춰 움직인다. 시계 목록의 분은 00~55 를 5분 단위로 보인다.
- 커밋은 사용자가 시킬 때만 한다. 끝에 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` 를 붙인다.

## Review Focus

1. 5초마다 오는 live 갱신(heartbeat)이 시각 칸이나 사이트 찾기 칸에 치는 중인 글을 지우면 안 된다. 칸에 초점이 있으면 줄을 다시 그리지 않는다. Task 3 시험: 칸에 쓰는 중에 live 를 갱신해도 값과 초점이 남는다.
2. `paintScheduleMeta` 의 '모든 단추 잠그기/풀기' 고리가 목록 상자 안의 꺼진 사이트 체크를 다시 켜면 안 된다. Task 3 시험: 꺼진 프리셋 체크는 비활성인 채로 남는다.
3. 프리셋에서 꺼져 저장 줄에만 남은 사이트 번호는 꼬리표로 보여야 한다. 빼기도 되어야 하고, 기존 '하나 이상 선택' 막기는 그대로다. Task 3 시험.
4. [지금 실행]에 반복 시간대 줄이나 잘못된 줄이 오면 PC 가 거절하고 아무것도 띄우지 않는다. Task 1 시험.
5. 찾기·거르기로 숨은 프리셋도 [적용] 값에 들어가야 한다. Task 4 시험: 걸러진 상태에서 적용해도 숨은 줄의 켬·끔이 보내진다.

---

### Task 1: PC - `launch` 의 `target: "slot"`, 예약 판 10

**Files:**
- Modify: `firebase/agent/agent.py` (`real_actions` 의 `do_launch`)
- Modify: `rpa_status.py:77` (`SCHEDULE_VERSION = 10`, 주석 맨 앞에 `10: [지금 실행] - launch {target: slot} (2026-11-13).`)
- Modify: `tests/test_schedule_slots.py:79` (`== 9` → `== 10`, 글 '판 10')
- Test: `firebase/tests/test_agent.py` (끝에 덧붙임)

**Interfaces:**
- Produces:
  - 명령 `launch` 의 args 가 `{"target": "slot", "slot": {at, run?, days?, sites?, inv?, xl?}}` 이면, 그 줄을 `rpa_dashboard.launch_slot(slot, by="cloud", trigger="manual")` 로 띄운다.
  - 결과 글은 `f"{dash.slot_text(slot)} 을(를) 지금 실행합니다."` 이다. 조사는 `st.josa` 로 붙인다.
  - `live.schedule.version == 10`.

- [ ] **Step 1: 실패하는 시험.** `rpa_dashboard.launch_slot` 을 가짜로 바꿔 받은 인자를 적어 둔다. 확인할 것:
  - `acts["launch"]({"target": "slot", "slot": {"at": "09:00", "run": ["Prepare", "Excel"], "days": [0,1,2,3,4], "sites": [2, 1]}})` → 가짜가 한 번 불린다. `by == "cloud"`, `trigger == "manual"`, `slot["sites"] == [1, 2]` 다 (`normalize_slots` 를 지났다는 표시).
  - `{"target": "slot", "slot": {"at": "10:00", "until": "11:00", "rest_min": 2, "run": ["Sales"]}}` → `RuntimeError`, 메시지에 `반복 시간대`. 가짜는 불리지 않는다.
  - `{"target": "slot", "slot": "x"}` 와 `{"target": "slot"}` → `RuntimeError`. 가짜는 불리지 않는다.
  - `launch_slot` 이 `RuntimeError(dash.UNUSED_ONLY)` 를 던지면 그대로 올라온다.
- [ ] **Step 2:** `python firebase/tests/test_agent.py` 를 돌려 새 확인이 FAIL 하는지 본다.
- [ ] **Step 3: `do_launch` 구현.**
  - `target == "slot"` 이면:
    1. `slot` 이 dict 가 아니면 `"실행할 줄을 읽지 못했습니다."` 로 거절한다.
    2. `"until" in slot` 이면 `"반복 시간대 줄은 지금 실행할 수 없습니다."` 로 거절한다.
    3. `dash.normalize_slots([slot])[0]` 로 검사한다. `ValueError` 는 `RuntimeError(str(e))` 로 바꾼다.
    4. `dash.launch_slot(...)` 로 띄운다.
  - 나머지 target 은 지금과 같다.
- [ ] **Step 4:** 아래 셋을 돌린다. 기대: 실패 0.
  - `python firebase/tests/test_agent.py`
  - `python tests/test_schedule_slots.py`
  - `python tests/test_schedule_holidays.py`

### Task 2: 웹 - 시각 칸 (글자 + 시계)

**Files:**
- Modify: `firebase/web/rpa-settings.js` (`timeInput` 을 바꿈. 상태 `openClock` 추가)
- Modify: `firebase/web/index.html` 스타일. 시안의 `.tm-box`, `.tm`, `.tm-err`, `.clk`, `.clock` 를 `.times` 범위로 옮긴다.
- Test: `firebase/tests/check_web.py`
  - 바꿀 곳: `input[type=time]` 을 쓰는 1330·1445·1450·1572~1589행을 `input.tm` + `fill` + `blur` 로 바꾼다.
  - 덧붙일 확인:
    - `930` 을 치면 09:30 이 된다.
    - 09:32 에서 ↑ 는 09:35 다.
    - 시계에서 14 와 45 를 누르면 14:45 가 되고 목록이 닫힌다.
    - `ab` 를 치면 칸이 `.bad` 가 되고 [적용]이 꺼진다.

**Interfaces:**
- Produces: `timeInput(slot, key, label)` → `HTMLElement`. 값은 `slot[key]` 에 바로 쓰고 `paintScheduleMeta()` 를 부른다. 줄 다시 그리기는 칸에서 초점이 떠날 때만 한다.
- 시각 읽기 `parseTime(raw) -> "HH:MM" | null` 는 시안의 함수를 그대로 쓴다. 못 읽는 값은 `slot[key]` 에 `raw` 를 그대로 둔다. 그러면 지금의 `scheduleProblems` '시간을 확인하여 주십시오.' 가 [적용]을 막는다.

- [ ] Step 1: check_web 확인을 고치고 덧붙인다.
- [ ] Step 2: 구현한다.
  - `openClock = {i, key}` 는 모듈 상태로 둔다. live 가 다시 그려도 열린 목록이 남아야 한다.
  - `paintTimes` 맨 앞에 지킴을 둔다: `#sch-times` 안의 `.tm` 이나 `.pick-q` 에 초점이 있으면 다시 그리지 않고 돌아간다 (Review Focus 1).
- [ ] Step 3: Task 5 에서 화면 시험을 한꺼번에 돌린다.

### Task 3: 웹 - 수집 사이트 [+ 추가]와 [지금 실행]

**Files:**
- Modify: `firebase/web/rpa-settings.js`
  - `siteChips` 를 바꾼다: 꼬리표 + `sitePicker`.
  - `payloadOf` 의 줄 변환을 `slotPayload(s)` 로 빼낸다.
  - `isV10` 을 더한다.
  - `paintTimes` 머리 줄에 `.now` 단추를 단다.
  - `paintScheduleMeta` 의 잠금 고리가 `.picker` 안과 `.now` 를 건너뛰게 한다.
- Modify: `firebase/web/index.html` 스타일. `.tags`, `.tag`, `.all-sites`, `.add-site`, `.pick-anchor`, `.picker`, `.now`.
- Test: `firebase/tests/check_web.py:1656-1680`
  - `.site-chips` 시험을 꼬리표와 목록 상자 시험으로 바꾼다.
  - [지금 실행] 시험을 덧붙인다.

**Interfaces:**
- Consumes: Task 1 의 명령 모양.
- Produces:
  - `slotPayload(s) -> object`: `payloadOf` 가 지금 줄마다 만드는 것과 같은 값.
  - `openPicker = {i, chosen: Set<number>, q: string} | null`: 모듈 상태.

- [ ] Step 1: check_web 확인. 저장 줄 `sites:[1]`, 켠 프리셋 ①②, 꺼진 ③ 으로 꾸민다.
  - 꼬리표가 `① ` 하나다.
  - [+ 추가]를 누르면 `.picker` 가 뜬다. ③ 체크는 비활성이다 (Review Focus 2).
  - ② 를 체크하고 [적용]하면 꼬리표가 둘이 되고, 보내는 `set_schedule` 의 `sites` 는 `[1,2]` 다.
  - × 로 둘 다 빼면 `켠 사이트 전체 (2개)` 가 보이고, 보내는 줄에 `sites` 가 없다.
  - Esc 를 누르면 목록이 바뀐 것 없이 닫힌다.
  - 저장 줄 `sites:[3]` 이면 꼬리표 `③` 이 보이고 '하나 이상 선택' 막기가 걸린다. × 로 뺄 수 있다 (Review Focus 3).
  - 판 10 PC 는 시각 줄에 `.now` 가 있고, 반복 줄에는 없다. 판 9 PC 에는 없다.
  - `.now` 를 누르고 확인하면 `launch` 명령이 들어간다. args 는 `{target:"slot", slot}` 이고, `slot` 은 `slotPayload` 와 같다.
  - live 를 갱신해도 찾기 칸에 친 글이 남는다 (Review Focus 1).
- [ ] Step 2: 구현한다. 확인 창 글은 `` `${s.at} 줄을 지금 한 번 실행하시겠습니까?\n\n${slotText(slotPayload(s))}` `` 이다. 보낼 때는 `send("launch", …, "지금 실행")` 을 쓴다.

### Task 4: 웹 - 쇼핑몰 프리셋 찾기·거르기·10개 스크롤·엑셀 비밀번호 접기

**Files:**
- Modify: `firebase/web/rpa-settings.js`
  - `HTML` 의 `#shop-card` 에 `.shop-tools` (찾기 칸·거르기)와 `#shop-count` 를 넣는다.
  - `paintShops` 에 거르기·10개 높이·`xlOpen` 을 넣는다.
  - `xlPwRow` 에 [취소]를 넣는다.
  - `applyShops` 가 끝나면 `xlOpen.clear()` 한다.
- Modify: `firebase/web/index.html` 스타일. 시안의 `.shop-tools`, `#shop-list` 스크롤, `.shop-count`, `.shop-empty`, `mark`, `.xl-open`, `.xl-cancel`.
- Test: `firebase/tests/check_web.py:936-954` (엑셀 비밀번호. 먼저 `.xl-open` 을 누른다). 프리셋 찾기 확인도 덧붙인다.

**Interfaces:**
- Produces: 모듈 상태 `shopQ: string`, `shopFilter: "all"|"on"|"off"|"need"`, `xlOpen: Set<number>`. mount 때 초기화한다.

- [ ] Step 1: check_web 확인.
  - 값이 없는 프리셋은 `.xl-pw` 가 없고 `.xl-open` 이 있다.
  - `.xl-open` 을 누르면 칸이 펼쳐지고 초점이 간다. [취소]를 누르면 다시 접힌다.
  - 값을 넣고 적용하면 지금처럼 `excel_pw` 를 보낸다.
  - 찾기 칸에 이름을 치면 맞는 줄만 남는다.
  - '끔' 거르기에서 숨은 켠 프리셋도 적용 값에 그대로 들어간다 (Review Focus 5).
  - 프리셋 12개를 시드하면 `#shop-list` 의 `scrollHeight > clientHeight` 다.
- [ ] Step 2: 구현한다.
  - '입력 필요' 조건은 `!shopReady(p)` 이다.
  - 찾기 대상: 이름은 부분 일치, 코드는 앞부분 일치, 번호는 일치. ①~⑳ 를 쳐도 번호로 읽는다.
  - 칸에 치는 중일 때 다시 그리지 않는 지킴은 지금 `.xl-pw` 와 같은 방식으로 `.shop-tools` 까지 넓힌다.

### Task 5: 확인·문서

- [ ] 화면 시험을 돌린다 (firebase/tests 에서, emu_env.ps1 을 읽은 창). 기대: 실패 0.
  `firebase emulators:exec --config ../firebase.json --only auth,database,firestore,hosting --project rpa-test-f02e0 "python check_web.py"`
- [ ] 단위 시험 일괄을 돌린다 (`tests/test_import_step.py` 는 뺀다).
- [ ] `docs/ui-wording.md` 에 새 글을 덧붙이고, `graphify update .` 를 돌린다.
- [ ] 사용자에게 보고하고, 커밋·버전 내보내기·hosting 배포는 지시를 기다린다.
