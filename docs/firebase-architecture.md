# AFTER MARKET 구조 (지금 돌아가는 것)

**갱신:** 2026-09-22. 이 문서는 **실제로 도는 것**을 적는다. 왜 그렇게 정했는지와 확정 이력은 `docs/superpowers/specs/2026-09-19-firebase-design.md` 에 있다.

**한 줄:** Firebase 는 화면·저장소·로그인을 맡고, 각 PC 의 에이전트가 RPA 를 띄우고 설정 파일을 쓴다. 서버 코드는 없고 **보안은 DB 규칙이 전담한다**.

AFTER MARKET 은 플랫폼 이름이고 RPA 는 그 안의 앱 하나다. 데이터는 `apps/rpa/…`, 화면은 껍데기 + 앱 모듈로 나뉜다. 앱이 하나뿐이라 지금은 앱 고르기가 숨어 있다.

---

## 1. 전체 그림

```
   고객 PC (회사마다, PC 마다)                Firebase (rpa-test-f02e0)            사람 (어디서든)
 ┌────────────────────────────┐          ┌──────────────────────────┐        ┌──────────────────┐
 │ Prepare_RPA.exe            │          │ Realtime DB (싱가포르)    │        │ 브라우저          │
 │ ERPia_RPA.exe              │          │   meta/companies/{회사}   │        │  rpa-test-f02e0  │
 │        │ 상태 파일           │  상태·이력 │   apps/rpa/live/…        │ 구독    │      .web.app    │
 │        ▼                   │ ───────▶ │   apps/rpa/settings/…    │ ◀─────▶│                  │
 │ 에이전트 (python, 콘솔 창)   │          │   apps/rpa/commands/…    │        │  Auth            │
 │   · 5초 heartbeat          │  명령 SSE  │ Firestore (서울)          │  조회   │  (이메일+비밀번호) │
 │   · exe 실행 / ERPia 종료   │ ◀─────── │   runs/{회사}/items/…     │ ◀──────│                  │
 │   · 사용자 설정 쓰기         │          │   users/{uid}            │        └──────────────────┘
 │   · 자동 실행 예약           │          │ Hosting (정적 화면)        │
 └────────────────────────────┘          └──────────────────────────┘
```

에이전트가 꺼져 있으면 화면에서 아무것도 시킬 수 없다. 명령은 10분 뒤 만료된다. 이력은 Firestore 에 남아 PC 를 꺼도 보인다.

## 2. 파일 지도

```
firebase/
  web/       화면 (Hosting 에 그대로 올라간다)
    index.html         껍데기 HTML + 모든 CSS(색 토큰, 밝음/어두움)
    app.js             로그인, 사이드바, 회사·PC 고르기, 앱 mount/unmount
    rpa.js             RPA 앱 화면 (현황/기록 탭, 실행 단추·이번 달 사용량·반복 다시 시작)
    rpa-settings.js    RPA 의 환경설정 (실행 모듈·쇼핑몰 프리셋·자동 실행 - 관리 > 환경설정 이 붙인다)
    rpa-common.js      RPA 화면 둘이 같이 쓰는 것 (경로·모듈 표·명령 보내기)
    settings.js        관리 > 환경설정 껍데기 (앱마다 설정 화면, 관리자만)
    account.js         계정 페이지 (비밀번호 바꾸기, 강조색)
    theme.js           밝음/어두움 + 강조색 (localStorage)
    firebase-config.js 공개 설정값 + HEARTBEAT_STALE_SEC, COMMAND_TTL_SEC
  agent/     고객 PC 에 들고 가는 것
    agent.py           본체 (상태 올리기, 명령 처리, 이력 업로드, 예약기 기동)
    fb.py              Auth·RTDB·Firestore REST 와 SSE (표준 라이브러리만)
    secret.py          설정 파일 + DPAPI 로 비밀번호 잠그기
    에이전트_시작.bat    관리자 권한 확인 후 agent.py 실행
    background.py      감독 (설치한 PC: 작업 스케줄러 → 창 없이 에이전트, 오류로 죽으면 다시 켬)
  rules/     database.rules.json, firestore.rules, firestore.indexes.json
  admin/     우리 PC 전용. ops.js(일) · setup.js(터미널) · admin.js + AFTERMARKET_SETUP.html/.bat(관리 화면) + serviceAccountKey.json (고객 PC 에 절대 금지)
  tests/     rules.test.js, test_agent.py, integration.js, check_web.py, check_setup.py, check_admin.py
  design/    시안 (배포 안 함)
  firebase.json, .firebaserc, emu_env.ps1
```

에이전트는 저장소 루트의 **`rpa_status.py` 와 `rpa_dashboard.py` 를 import 해서 쓴다**(복사하지 않는다). `launch`, `stop_erpia`, `apply_schedule`, `SCHEDULER`, `write_routine_modules` 가 전부 거기 있던 것이다. 그래서 배포 폴더에도 이 두 파일이 같이 간다.

저장소 루트의 `rpa_settings.py` 는 설치한 PC 의 **설정 창**이다 (에이전트 계정·ERPia 로그인·물류 처리 옵션(출력 방식·택배사·박스·운임·프린터) 입력, 자동 시작 작업 등록, 에이전트 켜고 끄기, 옛 폴더에서 설정값 가져오기. 메일은 2026-09-30 부터 다른 프로그램이 맡는다). 설치 파일은 `release/installer.iss`(Inno Setup) 이고, `tools/build_release.py` 가 zip 과 설치 파일을 함께 만든다. 설계: `docs/superpowers/specs/2026-09-29-installer-design.md`.

쇼핑몰 엑셀 받기 (2026-10-01, 설계 `docs/superpowers/specs/2026-09-30-shop-record-replay-design.md`): `web_replay.py` 는 사이트를 가리지 않는 조작 기록·재생 엔진, `rpa_observer.py` → `Prepare_Observer.exe` 는 **옵저버** (시작 메뉴 'RPA 옵저버', 주황 A, 콘솔 없음, 켤 때 관리자 권한) - 사람이 한 번 해 보인 '로그인 ~ 엑셀 받기' 를 프리셋 ①~⑩ 으로 기록한다. 기록은 설정 폴더의 `RPA_Presets.json` (비밀 없음), 아이디·잠근 비밀번호는 사용자 설정 `Sites.PRESETn` (처음엔 `Stts` 9 = 꺼짐). 프리페어(`web_runner.py`)의 할 일 `replay` 가 켜진 프리셋을 재생해 `(사이트코드)원래이름` 으로 `ERPIA_AI_EXCEL` 에 받고, 루틴의 엑셀업로드가 그대로 올린다. 브라우저는 2026-10-06 부터 PC 에 깔린 Edge 를 빈 프로필로 띄운다 (`web_replay.edge`, 같이 싣던 Chromium `ms-playwright` 713MB 를 뺐다).

## 3. 데이터 경로

Realtime DB
```
meta/companies/{cid}                    { name, stts, pcs: { pcId: { label } } }   stts 0(없음도) 사용 · 9 삭제(비활성)
meta/companies/{cid}/apps/rpa/limits/schedule   자동 실행 개수 (0~12, 없으면 2) - 총괄·관리 도구만
apps/rpa/live/{cid}/{pcId}              에이전트가 PATCH 로 올리는 현재 상태
                                        { programs, modules, presets, schedule, recent[20], heartbeat, host, server_time, version, tokens }
                                        tokens = { balance, cost: { routine, prepare, all } } (통장이 없는 업체는 없음)
                                        presets = [{ no, name, code, steps, saved_at, has_login, on }] (기록 내용·아이디·비밀번호 없음)
                                        schedule = { version 2, enabled, days, slots, next_run_at, next_slot, policy{limit, off},
                                                     repeat{date, at, until, runs, done, stopped, pending, next_at}, last_* } (version 이 없으면 옛 판 PC - times 만)
                                        tokens.cost.next = 다음 예약 줄이 '고르기' 면 그 줄의 토큰
apps/rpa/settings/{cid}/{pcId}          화면이 요청한 값 { modules, presets: {"PRESET1": true, …}, schedule {enabled, days, slots: [{at, run?, until?, rest_min?}]} }
apps/rpa/commands/{cid}/{pcId}/{cmdId}  { type, args, by, created_at, expires_at, state, result, … }
```
Firestore
```
runs/{cid}/items/{runId}   실행 이력 한 건 (조회용 필드 + 쓴 것 used·쓴 토큰 cost + payload JSON)
meta/prices                토큰 배율 { default: 1, login: 0, … } - 우리 PC(관리 화면·setup.js, Admin SDK)만 쓴다
wallet/{cid}               토큰 통장 { granted } + grants/{id} 넣은 내역 - 우리 PC(관리 화면·setup.js, Admin SDK)만 쓴다
users/{uid}                { cid, role, name } - 표시용. 권한 근거는 custom claim 이다
```

**토큰** (2026-10-06, 설계 `docs/superpowers/specs/2026-10-06-tokens-design.md`): 업체가 산 만큼 우리가 넣고, 모듈을 쓸 때마다 빠진다.
에이전트가 기록 한 장을 올릴 때 `used`(모듈별 횟수 map - 루틴은 완료인 모듈 (2026-10-07 부터 대상 없음은 안 셈), 프리페어는 단계가 모두 완료인 사이트 수
`sites`, 옵저버 미리보기는 안 셈)와 `cost`(횟수 × 토큰 배율, 토큰 배율에 없는 새 모듈은 default)를 적는다. 남은 토큰 = `granted` - 그 회사
기록들의 `cost` 합 (Firestore 가 서버에서 더한다, `agent.balance`). 기록은 만들기만 되고 이름이 run_id 라 두 번 빠지지 않는다.
통장이 없는 업체는 토큰 제도 밖 (세기만 한다).
**막기** (2부): 실행 단추·예약은 모두 `rpa_dashboard.launch` 를 지나고, 에이전트가 단 확인(`dash.TOKEN_GATE = agent.Tokens.gate`)이
띄우기 직전에 남은 토큰을 다시 본다 - 0 이하면 "토큰이 없습니다 (남은 N개). 충전한 뒤 실행하세요" 로 거절 (실행 명령은 그 글로 실패,
예약은 그 글을 `last_error` 로 남기고 다음 예약으로). 1 이상이면 끝까지 (마이너스 가능). 못 확인하면 마지막으로 확인한 값, 한 번도
못 했으면 막지 않는다. 에이전트는 기록을 올린 뒤·10분마다 다시 보고 `live.tokens` 로 올린다 → 화면은 실행 단추 아래 한 줄 (회색 평소,
노랑 '마이너스로 떨어질 수 있습니다', 빨강 0 이하 + 실행 단추 셋 잠김)과 예약 칸. 손으로 켠 exe 는 못 막고 기록이 올라갈 때 빠진다.
**넣기·보기** (3부): 토큰은 우리 PC 에서만 넣는다 - 관리 화면(업체 → 토큰 [넣기]) 또는 `setup.js tokens` (처음 넣으면 통장을 만들고 시작 시각 `since` 를 적는다 - 남은
토큰은 since 뒤에 시작한 기록만 뺀다, 그 전에 쓴 것은 안 뺀다. 유효기간·자동 체험분 없음). 넣은 내역 `grants` 는 업체가 못 본다.
업체 화면은 관리자에게만 (오른쪽 열) '이번 달 사용량' 카드 - 이달 1일과 since 중 늦은 때부터 업체 전체의 모듈별 횟수·합계·오늘을
서버가 더한다 (칸마다 질의 하나 - 한 질의에 여러 칸을 더하면 그 칸이 모두 있는 기록만 센다). 거르기+합은 복합 색인
(`rules/firestore.indexes.json` 의 started_at·cost, started_at·used.<모듈>) - **새 모듈을 더하면 여기와 rpa.js USAGE_KEYS 에도**.

`version` 은 에이전트가 켤 때 잰 판이다 (`rpa_status.check_install()`: 판 목록 `manifest.json` 과 파일 지문을 맞춰 `ok`·`mixed`·`none`·`error`). 화면은 RPA 현황·기록 탭 줄 오른쪽에 `버전 2026.09.29-2` 처럼 보여 준다 (섞임·확인 실패는 노란 글씨, 목록이 없으면 숨김). 설계: `docs/superpowers/specs/2026-09-29-release-layout-design.md`.

기준값은 항상 `live` 다. `settings` 는 "이렇게 해 달라" 는 요청이고, PC 가 실제로 반영한 결과가 `live.modules` 와 `live.schedule` 로 돌아온다.

명령 종류는 `launch`, `stop_erpia`, `set_modules`, `set_schedule`, `set_presets`, `resume_repeat`(반복 다시 시작) 여섯이다 (`set_presets` 는 에이전트가 `Sites.PRESETn.Stts` 를 0/9 로 - 키가 `PRESET1` 인 것은 숫자 키를 Realtime DB 가 배열로 바꿔 읽기 때문). 상태는 `queued → running → done|failed`, 늦게 받으면 `expired`.

| 값 | 지금 |
|---|---|
| heartbeat 주기 | 5초 |
| 연결 끊김 판정 | 신호 주기 × 3 + 5초 (새 에이전트 20초, `every` 를 안 올리는 옛 에이전트 95초) |
| 명령 만료 | 600초 |
| 최근 요약 | 20일 |
| 로그 꼬리 | 80줄 |
| 오프라인 큐 | 500건 |

## 4. 로그인과 권한

custom claim 세 가지가 전부다.

| claim | 누구 | 할 수 있는 것 |
|---|---|---|
| `{cid, role:"admin"}` | 회사 관리자 | 자기 회사 보기 + 실행·종료·설정 |
| `{cid, role:"viewer"}` | 열람자 | 자기 회사 보기만 |
| `{cid, pcId, role:"agent"}` | PC 에이전트 | 그 PC 의 live 쓰기, 명령 상태 갱신, 이력 올리기 |
| `{role:"super"}` | 우리 | 전 회사 |

계정은 우리 PC 에서만 만든다. 자가 가입은 없다. **관리 화면** (바탕화면 'AFTER MARKET 관리' → `firebase/admin/AFTERMARKET_SETUP.bat` →
`node admin.js`) 이 먼저고, 터미널 `firebase/admin/setup.js` 도 그대로 있다 - 둘 다 같은 `ops.js` 를 쓴다. 관리 화면은 127.0.0.1 에서만
듣고, 켤 때마다 새 비밀 값을 연 주소(`?k=`)에만 실어 `/api` 요청마다 `X-Admin-Key` 로 확인하며, `Host` 가 `127.0.0.1:<포트>` 가 아니면
거절한다. 고치는 요청은 하나씩 처리한다 ([만들기] 를 두 번 눌러도 토큰은 한 번, [끄기] 는 하던 일을 끝낸 뒤). 이미 있는 업체코드는 이름이 같을 때만 이어서 한다. 신규 업체는 한 흐름(업체 → PC → 관리자·유저 →
에이전트 계정 → 물류대기 관리 메뉴 사용 여부 → 최초 토큰량)으로 만들고, 끝에 '고객에게 보낼 정보' 를 복사한다 - 중간에 멈추면 다시 눌러 남은 것만.
한 일은 `firebase/admin/관리_기록.txt` 에 한 줄씩 (비밀번호 없이, gitignore). 바로 가기를 다시 만들려면 `node admin.js --shortcut`.

```
node setup.js company c_demo 테스트업체
node setup.js pc      c_demo pc_a A 컴퓨터
node setup.js user    c_demo <아이디> admin <이름>     # 비밀번호는 무작위로 만들어 한 번만 찍는다
node setup.js agent   c_demo pc_a                    # 회사 코드·PC 이름·비밀번호 세 값이 나온다
node setup.js passwd  c_demo <아이디>                  # 새 비밀번호. disable / enable / show / list 도 있다
node setup.js remove  c_demo                         # 업체 비활성화: stts=9 + 그 업체 계정 전부 사용중지. 데이터는 남는다
node setup.js restore c_demo                         # 다시 활성화: stts=0 + 계정 다시 사용
node setup.js tokens  c_demo +1000 "10월 결제"         # 토큰 넣기 (처음이면 토큰 정보를 만든다 - 그때부터 0 이하면 막힌다), -50 은 빼기
node setup.js tokens  c_demo                         # 넣은 합계·쓴 합계·남은 토큰·넣은 내역 10줄
node setup.js price   logistics 2                    # 토큰 배율 (인자 없으면 보기)
node setup.js usage                                  # 업체마다 남은 토큰·이번 달 쓴 토큰
```

삭제된 업체(stts=9)에는 pc·user·agent 를 만들 수 없고, 남은 토큰으로 화면에 들어와도 "사용이 중지된 업체입니다" 로 내보낸다. 에이전트는 계정이 막혀 1시간 안에 멈춘다.

이메일은 `<아이디>@<회사 코드>.rpa-test-f02e0.firebaseapp.com` 으로 조립한다(밑줄은 하이픈, 에이전트 계정은 `agent-<pcId>`). 같은 규칙이 `agent.py`, `app.js`, `ops.js` 에 한 줄씩 있다.

**서버 코드가 없으므로 규칙이 유일한 방어선이다.** 규칙을 고치면 `tests/rules.test.js` 를 반드시 돌린다. 화면 코드에서 버튼을 숨기는 것은 편의일 뿐 보안이 아니다.

## 5. 에이전트가 하는 일

- 1초마다 `rpa_status` 상태 파일을 보고 바뀌었을 때만 `live` 를 PATCH 한다.
- 5초마다 heartbeat. 신호에 주기(`every`)를 같이 올리고, 화면은 그 값으로 끊김 기준을 잡는다. 그래서 아직 안 고친 PC 가 30초마다 보내도 깜빡이지 않는다.
- `history.jsonl` 에 새 줄이 생기면 Firestore 에 올린다. 어디까지 올렸는지는 `history_pos.txt` 에 바이트 위치로 남겨 다시 켜도 이어서 간다. 올릴 때 쓴 것·쓴 토큰을 같이 적는다 (토큰 배율 `meta/prices` 는 10분마다 다시 읽고, 못 읽으면 처음 토큰 배율).
- 명령은 SSE 로 받는다. 끊기면 1초부터 60초까지 늘려 가며 다시 붙는다. 로그인 토큰이 1시간마다 만료되면 Firebase 가 `auth_revoked` 를 보내고, 그러면 토큰을 새로 받아 바로 다시 붙는다. 90초 넘게 아무것도(keep-alive 포함) 안 오면 죽은 연결로 보고 다시 붙는다.
- 못 올린 것은 `queue.jsonl` 에 쌓고 연결되면 순서대로 보낸다. 규칙이 거부한 것은 버린다. 기록 실패가 RPA 를 막는 일은 없다.
- **자동 실행 예약기를 에이전트가 띄운다.** 그래서 옛 8765 대시보드(`RPA_Dashboard.exe`, `대시보드_시작.bat`)와 같이 띄우면 예약이 두 번 돈다. 배포 폴더에서 옛 대시보드를 빼 둔 이유가 이것이다.
- 로그인 모듈은 항상 켬으로 고정한다. 화면에서도 잠겨 있고 에이전트도 `Login=Y` 로 덮어쓴다.
- 업체 정책(자동 실행 개수·안 쓰는 모듈)을 10분마다 읽어 settings.json schedule.policy 에 적는다 - 예약기가 줄을 자르고 모듈을 뺀다. `set_schedule` 도 한도를 넘으면 저장 전에 거절한다.
- 웰라이프 관문 (설계 `docs/superpowers/specs/2026-10-07-wellife-gate-design.md`): 업체코드에 `wellife` (대소문자 무관) 또는 관리 화면에서 연 업체(`meta/companies/{cid}/apps/rpa/features/wellife`)만. 에이전트가 정책에 `wellife` 를 적고 물류관리·운송장 출력을 안 쓰는 모듈에 더한다, 처음 열리면 `Wellife` 섹션(로그인·주문매핑 매출처리만 켬)을 쓴다, `set_modules` 는 `Wellife` 섹션에, 자동 실행은 '전체' 줄만. 루틴은 정책 켬+섹션 → 웰라이프, 정책 끔+섹션 없음 → 지금 루틴, 둘이 어긋나면 멈춤. 같은 규칙을 관리 화면(ops.js)·업체 웹(rpa-common.js)도 쓴다.
- 예약 줄의 모듈은 띄울 때 `RPA_RUN_MODULES`, 띄운 까닭은 `RPA_RUN_TRIGGER`(auto·repeat). 반복 시간대는 예약기가 회차마다 루틴을 새로 띄우고 `status_routine.json` 으로 센다 (실패·토큰 없음이면 그 시간대 멈춤). 처리한 게 없는 반복 회차는 이력에 안 남긴다. 설계: `docs/superpowers/specs/2026-10-06-settings-schedule-design.md`.
- 옵저버가 저장한 쇼핑몰 프리셋 요약(`rpa_status.preset_summary`: 이름·코드·단계 수·저장 시각·아이디 유무·켬)을 `live.presets` 로 올리고, `set_presets` 로 켬/끔을 받는다. 기록 내용·아이디·비밀번호는 안 올린다. 옵저버 미리보기는 이력('기록' 표의 '옵저버')에만 남고 날짜별 도넛은 프리페어·루틴만 센다.
- 켤 때 사용자 설정을 한 파일로 옮긴다. 아래 '사용자 설정' 참고.
- **자동 업데이트**: 관리 화면 → 명령 update/rollback → 에이전트가 받기·대기(RPA 가 바쁘면 기다림) → 도우미(`update\runner`)가 파일을 바꿈 → 3분 점검 → 실패하면 되돌리기. 판은 업데이트 전용 호스팅 `rpa-test-f02e0-releases` 에서 받고(`firebase/releases.json`), 목록의 서명을 공개 열쇠로 확인한다. 설계서 `docs/superpowers/specs/2026-10-07-auto-update-design.md`. **버전 내보내기(`tools/publish_release.py`)는 저장소 관리자만** - 서명 비밀 열쇠 `firebase/admin/update_signing_key.txt` 는 저장소 관리자 PC 에만 있다 (README 참고).
- **설치한 PC** 에서는 작업 스케줄러 작업 `AFTER MARKET\RPA Agent` 가 윈도우 로그인 때 `background.py` 를 창 없이(`pythonw`) 띄우고, 감독이 에이전트를 창 없이 띄워 자기 잡(job)에 넣는다. 에이전트가 0·2·3·4(정상·설정 문제·인증 멈춤·이미 돌고 있음)로 끝나면 감독도 끝나고, 그 밖은 10·30·60·120·300초 뒤 다시 켠다. 감독이 죽으면 에이전트도 죽고, 에이전트가 띄운 RPA 는 잡에서 빠져 끝까지 간다. 에이전트의 입력은 닫힌 파이프다 (`DEVNULL` 은 윈도우에서 `isatty()` 가 참이라 쓰면 안 된다). 감독은 에이전트를 켜기 전에, 설정 창은 에이전트 계정 로그인 전에 PowerShell 로 Firebase 주소를 한 번씩 찔러 윈도우가 루트 인증서를 받아 두게 한다 - 갓 설치한 윈도우에서는 이게 없으면 파이썬이 `CERTIFICATE_VERIFY_FAILED` 로 못 붙는다.
- 에이전트는 이름 있는 잠금 `Local\AFTER_MARKET_RPA_AGENT` 로 한 PC 에 하나만 돈다. 이미 돌면 "이미 돌고 있습니다" 를 찍고 4 로 끝난다 (시험은 `RPA_AGENT_MUTEX` 로 다른 이름).
- 옵저버가 떠 있으면 (옵저버가 쥐는 잠금 `Local\AFTER_MARKET_RPA_OBSERVER`, `rpa_status.observer_open`) 자동 실행은 닫힐 때까지 기다리고 실행 명령은 "옵저버가 켜져 있습니다…" 로 거절한다 (시험은 `RPA_OBSERVER_LOCK`). 잠금 함수는 `rpa_status.hold_lock`·`lock_held` 하나를 에이전트·설정 창·옵저버가 같이 쓴다.

### 사용자 설정: `RPA_UserConfig.json`

업체마다 사람이 정하는 값은 배포 폴더 루트(exe 옆)의 이 파일 하나에 있다. 개발 PC 는 `dist\` 에 있다.

```json
{"LogIn":    {"AdminCode": "…", "ID": "…", "PW": "dpapi:…"},
 "Routine":  {"Login": "Y", "Sales": "Y", "Hold": "N", "Logistics": "Y", "Output": "Y"},
 "Logistic": {"cboBS_Auto_YN": "…", "Printer": "…", "cboTag": "…", "cboTagAmt": "…", "cboBeasong_Gu_Apply": "…"},
 "Sites":    {"SITE1": {"URL": "…", "ID": "…", "PW": "dpapi:…", "Action": ["…"], "Stts": 0, "…": "…"}},
 "ERPia":    {"ExePath": "C:/Program Files (x86)/OneZeroSoft/ERPiaNet/ERPiaMain.exe"}}
```

- 예전의 `ERPIA_AI.txt`(바탕화면, 로그인·물류·모듈), `WebManageConfig.json`(exe 옆, 사이트), `login_manager_config.json`(exe 옆, ERPia 위치 `exe_path`)을 합친 것이다. 에이전트가 켤 때 이 파일이 없으면 옛 파일들을 합쳐 만들고 옛 파일은 `.old` 로 바꾼다. `.old` 에는 평문 비밀번호가 있으니 RPA 가 잘 도는 것을 본 뒤 지운다.
- 비밀번호(`PW`)는 DPAPI 로 잠가 `dpapi:…` 로 넣는다. 그 PC·그 윈도우 계정에서만 풀린다. 평문으로 적어도 읽히고, 에이전트가 켤 때 잠근다. 다른 PC 에서 잠근 값은 못 푸니 파일째 옮기지 말고 평문으로 다시 적는다.
- 읽는 곳은 `rpa_status` 한 곳이다(`read_user_config`). 이 파일이 없으면 옛 파일들을 읽으므로 exe 만 먼저 바꿔도 돈다. 비밀번호는 로그인하는 곳(`perform_login.load_credentials`, `web_runner.load_config`)에서만 푼다.
- **ERPia 위치(`ERPia.ExePath`)** 는 적힌 값이 틀리면 설치 기록(제어판 '프로그램 제거' 목록의 설치 폴더)과 기본 설치 폴더에서 `ERPiaMain.exe` 를 찾아 고쳐 적는다. 그래도 없으면 **사람이 있을 때만** 파일 고르는 창을 띄운다: 에이전트 창을 켤 때, 또는 루틴을 직접 실행할 때. 대시보드·에이전트·예약이 띄운 실행은 `RPA_UNATTENDED=1` 이 붙어 창을 띄우지 않고 바로 멈춘다(아무도 없는 PC 에서 창 앞에 멈추면 안 된다). ERPia 가 이미 떠 있으면 위치는 보지 않는다.

첫 실행에는 설정 파일이 없으므로 회사 코드·PC 이름·비밀번호를 묻고(`setup.js agent` 가 찍어 준 세 값) 이메일은 프로그램이 조립한다. 로그인해 보고 토큰의 회사·PC 가 친 값과 같아야 `agent_config.json` 을 만든다. 돌다가 인증이 죽으면(비밀번호 교체·계정 막힘) 멈추고 이유를 찍은 뒤 창에서 새 비밀번호를 다시 묻는다. 비밀번호는 DPAPI 로 그 PC, 그 윈도우 계정에서만 풀리게 잠긴다. 사람 계정으로는 거부한다.

## 6. 화면

- `app.js` 가 껍데기다. 로그인, 사이드바, 회사 이름, PC 고르기, 앱 mount 를 맡는다.
- 앱 모듈은 `key/label/icon/perPc/mount(root, ctx)/unmount()` 를 내보낸다. 새 앱을 붙이려면 파일 하나를 만들고 `APPS` 에 넣으면 된다.
- 관리자가 아니면 오른쪽 열이 통째로 빠지고 본문이 그 폭을 쓴다.
- 설정(실행 모듈·쇼핑몰 프리셋·자동 실행)은 '관리 > 환경설정' 한 곳 (관리자만, PC 마다). 앱 모듈이 `settings` 를 내보내면 붙는다. 적용 안 한 변경이 있으면 떠날 때 묻는다.
- 색은 `index.html` 의 토큰 한 곳에서 정한다. 상태색은 성공 초록, 진행 파랑, 실패 빨강, 오류 노랑이다. 강조색은 사용자가 계정 페이지에서 고른다.
- 상태 이름은 세 가지뿐이다. **성공**(success), **실패**(stopped·failed: 단계 검사에서 스스로 멈춤, 사용자 중지 포함), **오류**(crashed: 프로그램이 죽음). 상태 카드, 도넛 범례, 기록 표가 모두 같은 말을 쓴다. 실패는 데이터를 보고, 오류는 PC 를 본다.
- 배포 뒤 옛 화면이 남지 않게 js·html 에 `Cache-Control: no-cache` 를 걸어 두었다.

## 7. 새 PC 붙이기

1. 우리 PC 에서 PC 와 에이전트 계정을 만든다 - 관리 화면의 업체 → [PC 추가] (에이전트 계정도 만들기), 또는 `setup.js pc` 와 `setup.js agent`.
2. 우리 PC 에서 `.venv\Scripts\python.exe tools\build_release.py` 로 판을 만든다. `D:\AX\배포_<판 번호>` (+ 같은 이름의 zip) 와 설치 파일 `D:\AX\AFTER_MARKET_RPA_Setup_<판 번호>.exe` 가 생긴다. 정해 둔 파일만 담고 스스로 검사하며, 설치 파일은 검사를 통과한 판 폴더로만 만든다 (Inno Setup 이 있어야 한다. 없으면 `--no-setup`).
3. 설치 파일과 1번의 세 값(회사 코드·PC 이름·에이전트 계정 비밀번호)을 설치할 사람에게 넘긴다.
4. 그 PC 에서 설치 파일을 실행한다. 설치 끝에 뜨는 설정 창에 세 값과 ERPia 로그인·물류 값(그 업체가 ERPia 에 등록한 택배사·박스·운임과 글자 그대로)을 넣고 저장하면, 에이전트 계정으로 로그인해 보고 윈도우 로그인 때 에이전트가 창 없이 켜지게 등록한 뒤 켠다. 옛 구조 PC 는 설정 창의 [기존 설정값 가져오기] 로 옮긴다 (옛 에이전트는 닫게 하고, 저장 뒤 옛 폴더 이름을 `_옮김` 으로 바꿀지 묻는다).
5. 대시보드에서 그 PC 를 고른다. PC 가 둘 이상이면 제목 옆에 고르는 칸이 생긴다.

손으로 넘기는 대비책: zip 을 풀고 `RPA_UserConfig.json` 을 채운 뒤 `firebase\agent\에이전트_시작.bat` 을 실행한다 (옛 구조로 돈다). 파일 몇 개만 넘길 때는 `manifest.json` 도 같이 넘긴다. 자세한 절차는 배포 폴더의 `배포안내.txt` (0번이 설치 파일) 와 `클라우드_안내.txt` 에 있다.

## 8. 고치고 시험하기

에뮬레이터는 Java 21 이 필요하다. 창마다 `. .\emu_env.ps1` 로 그 창에서만 앞세운다. 시스템 Java 8 은 건드리지 않는다.

```powershell
cd D:\AX\RPA
.venv\Scripts\python.exe tests\test_layout.py         # 배치·판 (자리 찾기, 판 점검)
.venv\Scripts\python.exe tests\test_build_release.py  # 빌드 스크립트 (exe 는 안 만든다, installer.iss 는 가짜 판으로 컴파일)
.venv\Scripts\python.exe tests\test_settings.py       # 설정 창 (창 없는 부분)
.venv\Scripts\python.exe tests\check_settings_ui.py   # 설정 창을 진짜로 띄워 본다 (몇 초 뜬다, 인수로 사진 경로)
.venv\Scripts\python.exe tests\test_background.py     # 에이전트 감독
.venv\Scripts\python.exe tests\test_start_failure.py  # 띄운 RPA 가 기록도 못 남기고 죽으면 '시작하지 못함' 이력
.venv\Scripts\python.exe tests\test_schedule_slots.py    # 자동 실행 예약 (줄마다 모듈·업체 한도), RPA·옵저버가 떠 있으면 기다림
.venv\Scripts\python.exe tests\test_schedule_repeat.py   # 시간대 반복 (가짜 시계)
.venv\Scripts\python.exe tests\test_encoding.py       # .bat 는 CP949, 안내 문서·설치 스크립트는 BOM 있는 UTF-8
.venv\Scripts\python.exe tests\test_edge.py           # 깔린 Edge (같이 싣는 브라우저 없이), 옵저버 Edge 명령줄·프로필, Edge 없는 PC
.venv\Scripts\python.exe tools\sandbox_test.py D:\AX\AFTER_MARKET_RPA_Setup_<판>.exe   # 윈도우 샌드박스에서 설치 파일
.venv\Scripts\python.exe tools\sandbox_test.py --update D:\AX\AFTER_MARKET_RPA_Setup_<판>.exe   # 위에 더해 자동 업데이트 (최대 45분)
cd D:\AX\RPA\firebase; . .\emu_env.ps1
python tests\test_agent.py                      # 에이전트 단위 (Firebase 없이)
cd tests; npm test                              # 규칙
firebase emulators:exec --config ../firebase.json --only auth,database,firestore          --project rpa-test-f02e0 "node integration.js"
firebase emulators:exec --config ../firebase.json --only auth,database,firestore,hosting  --project rpa-test-f02e0 "python check_web.py"
firebase emulators:exec --config ../firebase.json --only auth,database,firestore          --project rpa-test-f02e0 "python check_setup.py"
firebase emulators:exec --config ../firebase.json --only auth,database,firestore          --project rpa-test-f02e0 "python check_admin.py"
cd ..; firebase deploy --only hosting --config firebase.json
```

| 시험 | 건수 | 보는 것 |
|---|---|---|
| 규칙 | 30 | 다른 회사·열람자·위조 거부, 명령 상태 전이, 명령 set_presets·resume_repeat, 기록의 쓴 토큰(0 이상 정수)·쓴 것(map), 자기 회사 쓴 토큰 합, 토큰 배율·통장은 아무도 못 씀 |
| 관리 도구 | 48 | `tests/check_setup.py` (에뮬레이터): 업체 등록·비활성화·다시 활성화, 거절은 '오류: …' 한 줄, 도움말·출력도 관리 화면과 같은 이름(사용중지·업체 비활성화·토큰 정보·업체코드/PC코드), 없는 업체엔 모듈 정책 거절, 토큰 넣기·빼기·통장 시작 시각·넣은 내역·잘못된 수 거절, 토큰 배율, usage, 자동 실행 개수(slots, 0~12) |
| 관리 화면 | 64 | `tests/check_admin.py` (에뮬레이터 + Playwright): 비밀 값·Host 검사, 못 읽는 요청 줄(`GET //[`)에도 서버가 산다, 신규 업체 한 흐름(계정은 줄마다 관리자/유저, 잘못된 내용은 만들기 전에 거절·동시에 두 번 눌러도 토큰 한 번·다시 누르면 남은 것만, 이미 있는 계정은 건너뛰고 재발급 안내, 이미 있는 업체코드를 다른 이름으로 치면 거절), 업체 표·상세(토큰 넣기·재발급·사용중지/사용·모듈 정책·자동 실행 개수·비활성화는 업체코드를 쳐야·다시 활성화), 화면 이름(사용자가 고른 이름만·옛 이름 없음), 토큰 배율·통계, 화면(업체 이름 속 HTML 은 글자로·물류대기를 안 고르면 거절·고객에게 보낼 정보·옛 주소는 '다시 켜세요'), [끄기] 는 하던 일을 끝낸 뒤, 관리_기록.txt·서버 출력에 비밀번호 없음 |
| 에이전트 단위 | 182 | 큐, 로그인 토큰, 인증 거부·망 오류 구분, 명령 선점, 세 칸 첫 실행, 에이전트 파일 자리, 하나만 돌기, 쇼핑몰 프리셋 요약·set_presets·도넛에서 옵저버 빼기, 토큰(쓴 것·쓴 토큰·토큰 배율 읽기·남은 토큰, 막기: 0 이하 거절·통장 없음 통과·확인 실패는 지난 값·실행 1번에 드는 토큰, '완료' 만 셈), 업체 정책(자동 실행 개수 읽기·PC 에 적기·한도 넘는 set_schedule 거절·끄기는 통과·다음 줄 토큰(물류관리가 빠지면 운송장도)), resume_repeat |
| 통합 | 42 | 에뮬레이터에 에이전트를 붙여 명령 왕복, 사용자 설정 옮기기·잠금·모듈 쓰기·ERPia 위치, 켤 때 판 올리기, 기록마다 서버 토큰 배율로 센 쓴 토큰, 남은 토큰(통장 없음 null), 토큰이 없으면 실행 명령이 그 까닭으로 실패·현황 tokens, 통장 시작 뒤 기록만 뺀다, 옛 모양·줄 모양 set_schedule |
| 화면 | 302 | Playwright. 관리 > 환경설정(떠날 때 확인 - 메뉴·PC·로그아웃·탭 닫기, 적용 뒤 응답 전엔 안 물음·PC 마다·업체 한도 바로 따라감), 자동 실행 줄(전체/고르기·업체 한도 N/M·한도 넘는 줄 '미실행 (한도초과)'·끄기는 적용됨·옛 판 PC 는 시각만·줄 0개도 새 판), 반복 시간대(겹침 거절·오늘 N회·멈춤 까닭·[반복 다시 시작]·기록 '루틴 · 반복'), 대비 4.5:1, 띠, 기록 탭, 권한별 화면, 세 칸 로그인, 이스케이프, 삭제된 업체·막힌 계정 안내, 두 칸 로그인·저장 체크박스, 판 칸, '쇼핑몰 프리셋' 스위치(잠김·까닭·적용·꺾쇠), 기록 표 '옵저버', 실행 단추 '… 실행중'(끝나면 돌아옴), 잠긴 까닭은 줄 아래 글(휴대폰), 토큰 줄(통장 없음 숨김·회색·노랑·빨강+실행 단추 잠금)·예약 칸 토큰 글, 이번 달 사용량 카드(모듈별 횟수·합계·오늘, 통장이 없으면 숨김, 이달 중간에 만든 토큰 정보는 '…일 토큰 정보 생성부터'), 역할 이름 '유저'(전 '열람'), 에이전트 계정 안내 |
| 배치·판 | 45 | 자리 찾기(새·옛 구조, PyInstaller·Nuitka), 판 점검, exe 쪽 모듈 자리 |
| 빌드 스크립트 | 58 | 판 번호·모으기(브라우저 폴더는 runtime 에 남아 있어도 판에 없다 - Edge)·압축·찌꺼기·빈 틀(비밀·우리 물류 값)·exe 출력 표지, Nuitka 링크도 일반 x86-64 CPU(LDFLAGS - 빌드 PC 의 AVX-512 가 인텔 노트북에서 0xC000001D), 설치 파일(ISCC 명령·installer.iss 와 자리 규칙·제거 순서·권한·옵저버가 켜져 있으면 멈춤·가짜 판 컴파일)·tkinter·exe 가져오기, mfc140u.dll·comtypes 시각 비교 끄기, AFTER MARKET 파이썬 사본(설명 칸·아이콘 한 벌), exe 별 아이콘(루틴 크림 A·프리페어 주황 A), exe 셋(옵저버 콘솔 attach·tk-inter·Tcl/Tk 꺼내기·옛 판 가져오기 거부·Nuitka 만) |
| 설정 창 | 108 | 칸 확인(대시보드·ERPia 업체코드 따로), 설정 합치기(잠금·비운 칸은 그대로, Sites 는 안 건드림), 물류 칸(출력 방식 A·Y=자동, 빈 틀 수동, 가져오기), 메일 칸 없음, 저장 순서(인증서 채우기 → 로그인), 멈춘 까닭, ERPia 못 찾음, 작업 XML(진짜 작업 스케줄러 등록, AFTER MARKET 감독 사본), 옛 에이전트, 멈추기 0·5·6·확인만, 가져오기(Run_All.bat)·이름 바꾸기, 계정·설치 폴더 확인, 오류 가드 |
| 설정 창 화면 | 40 | 진짜 tkinter 창: 첫 모습(단추 이름·맨 위 한 줄), 빈 칸 안 흐린 안내(보이고 사라짐·칸 안에 들어감·값이 아님), '(기본 프린터)', 창 폭(≤520)·높이(≤690)·긴 까닭 줄바꿈, 출력 방식·물류 경고 줄, 수동이면 프린터 칸 꺼짐·없는 프린터 줄 숨김, ERPia 못 찾음, 빈 칸의 빨간 안내, 저장·'켜는 중', 가져오기, 없는 프린터, 멈춘 까닭, 옛 에이전트, 이름 잘림, 단추 오류 |
| 감독 | 28 | 종료 코드별 다시 켜기, 멈춘 까닭 파일, 기다림, 창 없는 입출력(닫힌 파이프·UTF-8), 잡(감독이 죽으면 에이전트도, RPA 는 남음), 윈도우 인증서 채우기, AFTER MARKET 에이전트 사본 |
| 시간대 반복 | 44 | `tests/test_schedule_repeat.py` (가짜 시계): 반복 줄 검사(겹침·전체·쇼핑몰 받기·자정), 첫 회차·쉬는 시간(누가 띄웠든 마지막 끝난 때부터)·처리 센다, 실패·토큰 없음이면 멈춤·다시 시작, 끝 시각 뒤 새 회차 없음, 시간대 중 고치기·지우기, 정책 쓰기가 반복 상태를 안 지움, 자정 넘긴 회차 |
| 시작하지 못함 | 10 | 띄운 RPA 가 기록도 못 남기고 끝나면 '시작하지 못함' 이력 한 건 (오류 출력 마지막 줄·종료 코드, 전체 실행은 둘 다) |
| 웰라이프 관문 | 23 | `tests/test_wellife_gate.py`: Wellife 섹션 읽기·쓰기(처음은 로그인·매출처리만·빠진 키는 끔·모르는 키 거절), 정책 값 wellife, 루틴 갈래 네 칸·main 이 정책 켬+섹션 없음이면 멈춤 / `tests/test_login_flow.py`: 재시도 때 숨은 로그인 창은 안 누름, 같은 ERPia 의 보이는 메인 창만 성공 (가짜 창) |
| 자동 실행 | 107 | 요일·시간 예약 계산, 줄마다 모듈(전체/루틴만/프리페어만, RPA_RUN_MODULES)·옛 모양 {days, times} 바꾸기·업체 한도(앞 N줄만, 안 쓰는 모듈만 남으면 건너뜀), 예약기 (RPA 가 돌거나 옵저버가 떠 있으면 기다림·실행 단추 거절·잠금 쥔 옵저버가 죽으면 풀림), 다시 켤 때 건너뛰기, 토큰 확인(TOKEN_GATE)이 거절하면 실행 단추는 그 글로·예약은 까닭을 남기고 다음으로 |
| 기록·재생 엔진 | 56 | `tests/test_web_replay.py` (같이 싣는 브라우저 없이 - 깔린 Edge): 가짜 쇼핑몰을 기록해 다음 날·모레·기다림 없이·예상 밖 공지·느린 목록·단계 뺀 기록으로 재생, 마우스 올리기 메뉴, 주소줄 단계, 창 크기, 값 없는 설명, 모르는 형식, 받기 시간 초과, 멈춤(단계 앞·찾는 중), 일시정지, 팝업이 내려 주는 파일. 부하는 `tests/stress_web_replay.py` (22번) |
| 프리셋 | 68 | `tests/test_presets.py` (깔린 Edge): 프리셋 파일·Sites 칸(잠김·Stts 9)·요약·켬끔, 옵저버 미리보기는 이력에만, 관리자·계정 확인, 프리페어 replay 로 `(012)…` 받기·알림창은 재생기 하나만(글 20자), 옵저버 저장 전 확인·잠금, 바뀐 프리셋만 저장 날짜, 남은 프로필 지우기, 콘솔 없이 켜진 exe 처럼 표준 핸들이 못 쓰는 값이어도 Playwright 드라이버가 뜸 |
| 브라우저 (Edge) | 11 | `tests/test_edge.py`: 같이 싣는 브라우저 없이 기록·재생·프리페어 자체 시험이 깔린 Edge 로, 옵저버 Edge 명령줄(`--no-sandbox`·`--enable-automation` 없음)·다운로드 창을 끈 프로필·`--check` 의 Edge 판, Edge 다운로드 창(`edge://downloads-hub`)과 늦게 주소가 붙는 새 탭은 사이트가 연 창이 아니다, 사람이 연 Edge 새 탭(MSN 새 탭 주소 `ntp.msn.com/edge/ntp` - 바로 생김·나중에 붙음)은 '새 탭' 단계, Edge 가 없으면 "Microsoft Edge 가 없습니다" |
| 옵저버 화면 | 21 | `tests/check_observer_ui.py`: 진짜 창으로 주소 치기 → 기록 → 끄기·지우기 → 미리보기 → 저장, 기록 중 저장 잠김·저장 안 한 기록 묻기, 안내 한 줄(프리셋을 바꾸면 비움·남은 단계가 없으면 그렇다고), 미리보기 [Ⅱ 일시정지]·[■ 중단]·도는 중 닫기 거절·브라우저 못 띄움·일시정지 중 닫기, 다시 저장해도 날짜 그대로, 사진 다섯 (3~4분 마우스·키보드를 쓴다) |
| 인코딩 | 17 | .bat CP949·CRLF 와 실제 실행, 관리 화면 bat 은 영문만·CRLF, 안내 문서·installer.iss·sandbox_inner.ps1 BOM UTF-8 |
| 자동 업데이트 서명 | 14 | `tests/test_update_sign.py`: 서명 만들기·확인, 위조·다른 열쇠·빈 열쇠 거부 |
| 자동 업데이트 받기 | 50 | `tests/test_rpa_update.py`: 판 목록·서명 확인, 바뀐 파일만 받기, 지문·크기 틀리면 버림, 바쁨 검사, 상태 파일 |
| 업데이트 도우미 | 40 | `tests/test_update_helper.py`: 파일 바꾸기·보관본·3분 점검·되돌리기, 바꾸는 도중 끊김 복구 (가짜 시계) |
| 판 내보내기 | 17 | `tests/test_publish_release.py`: 서명·사이트 폴더·최근 5개+안정본 남기기·쓰지 않는 blob 지우기 |
| 샌드박스 (자동 업데이트) | 8 | `tools/sandbox_test.py --update`: 시험용 열쇠(서명 뒤 지움)로 서명한 판 B(파일 하나 바뀜)·판 C(켜지지 않는 에이전트)를 샌드박스 안 가짜 호스팅(127.0.0.1:8799)에서 받아 판 B 업데이트(done·제거 목록 판 번호·도우미 작업 지움) → [이전 판으로 되돌리기] → 판 C 3분 점검 실패로 되돌림 → 바꾸는 도중 도우미를 죽이고 다시 돌리면 되돌림. 진짜 열쇠·호스팅은 안 쓴다 |
| 샌드박스 | 38 | 깨끗한 윈도우: 조용한 설치·파일(같이 싣던 브라우저 ms-playwright 없음)·판 점검·권한·바로 가기·제거 목록·아이콘(바로 가기 둘·제거 목록)·시작 메뉴 'RPA 옵저버'·tkinter → 설치된 exe 셋 --check(UIAutomationCore.dll 시각을 바꿔 다른 윈도우 흉내)·프리페어 --selftest --headless·옵저버 --check 가 깔린 Edge 를 띄움 → 옵저버를 붙을 콘솔 없이 (시작 메뉴처럼) 켜면 Playwright 드라이버가 깔린 Edge 창을 띄움(사진 observer.png) → 작업 등록(AFTER MARKET 사본, exe 다섯의 아이콘 - 프리페어·옵저버만 주황 A) → 감독·에이전트(인터넷 있으면 로그인 거부 3 에 같이 끝남) → 옵저버가 켜진 채 다시 설치는 시작 전에 멈춤(코드 7, --stop 안 부름) → 다시 설치(--stop, 옛 판의 ms-playwright 폴더를 지움) → 설정 창 사진 → 조용한 제거 (판 2026.10.07-6, 자동 업데이트 8 줄과 함께 46/46) |

에뮬레이터 명령에는 항상 `--config ../firebase.json` 이 붙는다. 화면을 에뮬레이터로 볼 때는 주소 뒤에 `?emu=1` 을 붙인다.

## 9. 비밀 취급

- `RPA_UserConfig.json` 의 비밀번호는 DPAPI 로 잠겨 있지만 **PC 밖으로 내보내지 않는다.** 클라우드에는 모듈 켬/끔 값만 오간다. 옮기고 남은 `ERPIA_AI.txt.old`, `WebManageConfig.json.old` 에는 평문이 있으니 확인 뒤 지운다 (`login_manager_config.json.old` 는 ERPia 위치뿐).
- `serviceAccountKey.json` 은 규칙을 우회하는 만능 열쇠다. `firebase/admin/` 에만 두고 고객 PC 에 복사하지 않는다.
- 쇼핑몰 프리셋 파일 `RPA_Presets.json` 에는 비밀이 없다 (비밀번호 칸은 값 없이 기록, 아이디는 '설정의 아이디' 로). 그래도 사이트 메뉴·누른 글자가 있으니 PC 밖으로 보내지 않는다. 대시보드로는 이름·코드·단계 수·켬과, 칸에 친 값·주소 `?` 뒤를 뺀 미리보기·재생 로그만 간다.
- `agent_config.json`, `queue.jsonl`, `history_pos.txt`, 에이전트 기록은 모두 gitignore 다.
- 비밀번호는 `ops.js` 가 무작위로 만들어 한 번만 보여 준다 (터미널은 찍고, 관리 화면은 결과 칸에만 - 서버 콘솔·관리_기록.txt 에는 안 남는다). 명령줄에 없으니 이력에 남지 않는다. 예전 이력에 남은 것은 `Remove-Item (Get-PSReadLineOption).HistorySavePath` 로 저장 파일을 지운다 (`Clear-History` 는 세션 버퍼만 비운다).
- PC 를 빼거나 담당자가 바뀌면 사용중지 또는 비밀번호 재발급 (관리 화면, 또는 `setup.js disable`·`passwd`). 업체와 계약이 끝나면 업체 비활성화 (관리 화면에서 업체코드를 쳐야, 또는 `setup.js remove <cid>`) (계정 전부 막힘, 자료는 남음). 이미 받은 토큰은 최대 1시간 산다.

## 10. 아직 안 한 것

- 첫 로그인 때 비밀번호 변경 강제 (`must_change_password` 는 자리만 있다)
- 총괄(super)의 회사 목록 화면. 지금은 회사가 하나라 안 쓴다
- 실패했을 때 알림
- 배송장 생성·주문 수집 건수 정확히 세기 (루틴 RPA 수정 + exe 재빌드 필요)
- 옛 `rpa_dashboard.py` 8765 대시보드를 언제 접을지
