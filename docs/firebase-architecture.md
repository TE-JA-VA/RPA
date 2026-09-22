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
 │   · ERPIA_AI.txt 쓰기       │          │   users/{uid}            │        └──────────────────┘
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
    rpa.js             RPA 앱 화면 (현황/기록 탭, 실행·모듈·자동 실행)
    account.js         계정 페이지 (비밀번호 바꾸기, 강조색)
    theme.js           밝음/어두움 + 강조색 (localStorage)
    firebase-config.js 공개 설정값 + HEARTBEAT_STALE_SEC, COMMAND_TTL_SEC
  agent/     고객 PC 에 들고 가는 것
    agent.py           본체 (상태 올리기, 명령 처리, 이력 업로드, 예약기 기동)
    fb.py              Auth·RTDB·Firestore REST 와 SSE (표준 라이브러리만)
    secret.py          설정 파일 + DPAPI 로 비밀번호 잠그기
    에이전트_시작.bat    관리자 권한 확인 후 agent.py 실행
  rules/     database.rules.json, firestore.rules, firestore.indexes.json
  admin/     우리 PC 전용. setup.js + serviceAccountKey.json (고객 PC 에 절대 금지)
  tests/     rules.test.js, test_agent.py, integration.js, check_web.py
  design/    시안 (배포 안 함)
  firebase.json, .firebaserc, emu_env.ps1
```

에이전트는 저장소 루트의 **`rpa_status.py` 와 `rpa_dashboard.py` 를 import 해서 쓴다**(복사하지 않는다). `launch`, `stop_erpia`, `apply_schedule`, `SCHEDULER`, `write_routine_modules` 가 전부 거기 있던 것이다. 그래서 배포 폴더에도 이 두 파일이 같이 간다.

## 3. 데이터 경로

Realtime DB
```
meta/companies/{cid}                    { name, pcs: { pcId: { label } } }
apps/rpa/live/{cid}/{pcId}              에이전트가 PATCH 로 올리는 현재 상태
                                        { programs, modules, schedule, recent[20], heartbeat, host, server_time }
apps/rpa/settings/{cid}/{pcId}          화면이 요청한 값 { modules, schedule }
apps/rpa/commands/{cid}/{pcId}/{cmdId}  { type, args, by, created_at, expires_at, state, result, … }
```
Firestore
```
runs/{cid}/items/{runId}   실행 이력 한 건 (조회용 필드 + payload JSON)
users/{uid}                { cid, role, name } - 표시용. 권한 근거는 custom claim 이다
```

기준값은 항상 `live` 다. `settings` 는 "이렇게 해 달라" 는 요청이고, PC 가 실제로 반영한 결과가 `live.modules` 와 `live.schedule` 로 돌아온다.

명령 종류는 `launch`, `stop_erpia`, `set_modules`, `set_schedule` 넷이다. 상태는 `queued → running → done|failed`, 늦게 받으면 `expired`.

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

계정은 `firebase/admin/setup.js` 로 우리 PC 에서만 만든다. 자가 가입은 없다.

```
node setup.js company c_demo 테스트업체
node setup.js pc      c_demo pc_a A 컴퓨터
node setup.js user    <이메일> <비밀번호> c_demo admin <이름>
node setup.js agent   <이메일> <비밀번호> c_demo pc_a
node setup.js show    <이메일>
```

**서버 코드가 없으므로 규칙이 유일한 방어선이다.** 규칙을 고치면 `tests/rules.test.js` 를 반드시 돌린다. 화면 코드에서 버튼을 숨기는 것은 편의일 뿐 보안이 아니다.

## 5. 에이전트가 하는 일

- 1초마다 `rpa_status` 상태 파일을 보고 바뀌었을 때만 `live` 를 PATCH 한다.
- 5초마다 heartbeat. 신호에 주기(`every`)를 같이 올리고, 화면은 그 값으로 끊김 기준을 잡는다. 그래서 아직 안 고친 PC 가 30초마다 보내도 깜빡이지 않는다.
- `history.jsonl` 에 새 줄이 생기면 Firestore 에 올린다. 어디까지 올렸는지는 `history_pos.txt` 에 바이트 위치로 남겨 다시 켜도 이어서 간다.
- 명령은 SSE 로 받는다. 끊기면 1초부터 60초까지 늘려 가며 다시 붙는다.
- 못 올린 것은 `queue.jsonl` 에 쌓고 연결되면 순서대로 보낸다. 규칙이 거부한 것은 버린다. 기록 실패가 RPA 를 막는 일은 없다.
- **자동 실행 예약기를 에이전트가 띄운다.** 그래서 옛 8765 대시보드(`RPA_Dashboard.exe`, `대시보드_시작.bat`)와 같이 띄우면 예약이 두 번 돈다. 배포 폴더에서 옛 대시보드를 빼 둔 이유가 이것이다.
- 로그인 모듈은 항상 켬으로 고정한다. 화면에서도 잠겨 있고 에이전트도 `Login=Y` 로 덮어쓴다.

첫 실행에는 설정 파일이 없으므로 기계 계정 이메일과 비밀번호를 묻는다. 로그인해 보고 회사·PC 를 토큰에서 읽어 `agent_config.json` 을 만든다. 비밀번호는 DPAPI 로 그 PC, 그 윈도우 계정에서만 풀리게 잠긴다. 사람 계정으로는 거부한다.

## 6. 화면

- `app.js` 가 껍데기다. 로그인, 사이드바, 회사 이름, PC 고르기, 앱 mount 를 맡는다.
- 앱 모듈은 `key/label/icon/perPc/mount(root, ctx)/unmount()` 를 내보낸다. 새 앱을 붙이려면 파일 하나를 만들고 `APPS` 에 넣으면 된다.
- 관리자가 아니면 오른쪽 열이 통째로 빠지고 본문이 그 폭을 쓴다.
- 색은 `index.html` 의 토큰 한 곳에서 정한다. 상태색은 성공 초록, 진행 파랑, 실패 빨강, 오류 노랑이다. 강조색은 사용자가 계정 페이지에서 고른다.
- 배포 뒤 옛 화면이 남지 않게 js·html 에 `Cache-Control: no-cache` 를 걸어 두었다.

## 7. 새 PC 붙이기

1. 우리 PC 에서 `setup.js pc` 와 `setup.js agent` 로 PC 와 기계 계정을 만든다.
2. 배포 폴더(`D:\AX\배포_A_20260921` 이 본)를 통째로 복사한다. 옛 대시보드는 넣지 않는다.
3. 바탕화면 `ERPIA_AI\ERPIA_AI.txt`, `WebManageConfig.json`, `login_manager_config.json` 을 그 업체 값으로 맞춘다.
4. `firebase\agent\에이전트_시작.bat` 을 실행하고 기계 계정을 넣는다.
5. 대시보드에서 그 PC 를 고른다. PC 가 둘 이상이면 제목 옆에 고르는 칸이 생긴다.

자세한 절차는 배포 폴더의 `클라우드_안내.txt` 에 있다.

## 8. 고치고 시험하기

에뮬레이터는 Java 21 이 필요하다. 창마다 `. .\emu_env.ps1` 로 그 창에서만 앞세운다. 시스템 Java 8 은 건드리지 않는다.

```powershell
cd D:\AX\RPA\firebase; . .\emu_env.ps1
python tests\test_agent.py                      # 에이전트 단위 (Firebase 없이)
cd tests; npm test                              # 규칙
firebase emulators:exec --config ../firebase.json --only auth,database,firestore          --project rpa-test-f02e0 "node integration.js"
firebase emulators:exec --config ../firebase.json --only auth,database,firestore,hosting  --project rpa-test-f02e0 "python check_web.py"
cd ..; firebase deploy --only hosting --config firebase.json
```

| 시험 | 건수 | 보는 것 |
|---|---|---|
| 규칙 | 22 | 다른 회사·열람자·위조 거부 |
| 에이전트 단위 | 81 | 큐, 토큰, 명령 전이, 첫 실행 설정 |
| 통합 | 20 | 에뮬레이터에 에이전트를 붙여 명령 왕복 |
| 화면 | 114 | Playwright. 대비 4.5:1, 띠, 기록 탭, 권한별 화면 |

에뮬레이터 명령에는 항상 `--config ../firebase.json` 이 붙는다. 화면을 에뮬레이터로 볼 때는 주소 뒤에 `?emu=1` 을 붙인다.

## 9. 비밀 취급

- `ERPIA_AI.txt`, `WebManageConfig.json` 에는 평문 비밀번호가 있다. **PC 밖으로 나가지 않는다.** 클라우드에는 모듈 켬/끔 값만 오간다.
- `serviceAccountKey.json` 은 규칙을 우회하는 만능 열쇠다. `firebase/admin/` 에만 두고 고객 PC 에 복사하지 않는다.
- `agent_config.json`, `queue.jsonl`, `history_pos.txt`, 에이전트 기록은 모두 gitignore 다.
- 계정을 만들 때 비밀번호가 명령 이력에 남으므로 뒤에 `Clear-History` 로 지운다.

## 10. 아직 안 한 것

- 첫 로그인 때 비밀번호 변경 강제 (`must_change_password` 는 자리만 있다)
- 총괄(super)의 회사 목록 화면. 지금은 회사가 하나라 안 쓴다
- 실패했을 때 알림
- 배송장 생성·주문 수집 건수 정확히 세기 (루틴 RPA 수정 + exe 재빌드 필요)
- 옛 `rpa_dashboard.py` 8765 대시보드를 언제 접을지
