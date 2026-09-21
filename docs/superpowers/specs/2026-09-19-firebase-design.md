# Firebase 다회사 대시보드 설계 (확정본)

**날짜:** 2026-09-19
**바탕:** `docs/firebase-architecture.md` (초안). 이 문서는 초안에서 미뤄 둔 결정을 확정하고 1차 범위를 못 박는다. 초안과 다르면 이 문서가 우선한다.

## 0. 확정한 결정

| 항목 | 결정 |
|---|---|
| 방식 | **A안. 서버 코드 없음.** 화면(정적, Hosting) ↔ Firebase ↔ PC 에이전트. 보안은 DB 규칙이 전담 |
| 프로젝트 소유 | **hjjang96@gmail.com**. 프로젝트 ID `rpa-test-f02e0`. 나중에 회사 계정을 소유자로 추가해 이관 |
| 리전 | Firestore = asia-northeast3(서울). **RTDB = asia-southeast1(싱가포르)** - RTDB 는 서울 리전이 없다 |
| 올리는 데이터 | 지금 대시보드가 보여 주는 것 그대로: 단계·결과·건수·중단 사유·로그 꼬리 80줄. **ERPia 비밀번호·`ERPIA_AI.txt`·`WebManageConfig.json` 은 절대 안 올린다** |
| 살아 있는 상태·명령·설정 | Realtime DB (RTDB) |
| 실행 이력 | **Firestore** (`runs`). PC 의 `history.jsonl` 도 그대로 남긴다(이중) |
| 사용자 로그인 | Firebase Auth **이메일+비밀번호**. 자가 가입 없음. 우리가 발급, 첫 로그인 때 비밀번호 변경 강제 |
| PC 에이전트 인증 | PC 마다 기계 계정(이메일+비밀번호) 하나. custom claim `{cid, pcId, role:"agent"}`. **서비스 계정 키는 고객 PC 에 두지 않는다** |
| 명령 만료 | 기본 10분 (`expires_at`). 화면에서 명령별로 바꿀 수 있다 |
| 요금 | Spark(무료). Cloud Functions 없음 |
| 플랫폼 이름 | **AFTER MARKET** (2026-09-21, 바뀔 수 있음). RPA 는 그 안의 앱 하나. 데이터는 `apps/rpa/…` |
| 파일 위치 | `D:\AX\RPA\firebase\` 하위에 새 파일만. **`firebase\` 밖 기존 파일은 수정하지 않는다** (시연 보호) |

## 1. 구성요소

```
firebase/
  web/            화면. dashboard.html 을 복사해 데이터 층만 교체 (index.html, app.js, firebase-config.js)
  agent/          PC 에이전트 (agent.py, agent_config.json, 에이전트_시작.bat)
  rules/          database.rules.json, firestore.rules, firestore.indexes.json
  admin/          우리 PC 전용 관리 스크립트 (회사·사용자·PC 등록, claim 부여) - Admin SDK, 서비스 계정 키는 여기만
  tests/          규칙 시험(에뮬레이터), 에이전트 단위·통합 시험
  firebase.json, .firebaserc
```

- 에이전트는 `D:\AX\RPA` 의 `rpa_status`(상태 파일 읽기, `write_routine_modules`)와 `rpa_dashboard`(`launch`, `launch_state`, `any_rpa_running`, ERPia 종료)를 **import** 한다. 복사하지 않는다.
- 화면은 Firebase JS SDK(v10 모듈, CDN)를 쓴다. 다른 라이브러리 없음. 지금 `dashboard.html` 의 화면 코드(카드·링·탭·설정 폼)는 유지하고 `pollStatus/api 호출` 부분만 바꾼다.

## 2. 데이터 구조

### Realtime DB (2026-09-21 개정: 플랫폼 **AFTER MARKET** 은 여러 앱을 담는다. 앱 데이터는 `apps/<앱>/` 아래, 회사·PC 는 앱 밖)
```
meta/companies/{cid}                    ← { name, pcs: { pcId: { label } } }        (앱 공통)
apps/rpa/live/{cid}/{pcId}              ← { programs: {routine, prepare}, modules, heartbeat: {at, host, rpa_running}, host, server_time }
                                           (rpa_status.dashboard_snapshot() 통째 + PC 의 실제 실행 모듈. 로그는 80줄. PATCH 로 올린다)
apps/rpa/commands/{cid}/{pcId}/{cmdId}  ← { type, args, by, created_at, expires_at,
                                            state: queued|running|done|failed|expired, result, started_at, ended_at }
apps/rpa/settings/{cid}/{pcId}          ← { modules: {Login:true,...}, updated_by, updated_at }   (화면이 요청한 값. 기준값은 live.modules)
```
새 앱은 `apps/<앱>/` 아래에 같은 모양(live·commands·settings)을 만들고, 규칙 파일의 `apps.rpa` 블록을 복사해 이름만 바꾼다.
화면은 껍데기(`app.js`: 로그인·회사·PC·앱 고르기)와 앱 모듈(`rpa.js`: `mount(root, ctx)` / `unmount()`)로 나뉜다. 앱이 하나면 앱 고르기는 숨긴다.
- `type` ∈ `launch` | `stop_erpia` | `set_modules` | `set_schedule`. `launch` 는 인자 없음(모듈은 `settings` 기준). `set_modules.args = {Login:bool,...}`.
- `cmdId` 는 push key(시간순 정렬).

### Firestore
```
runs/{cid}/items/{runId}      ← history_record 그대로 + { cid, pcId, uploaded_at }
users/{uid}                   ← { cid, role: admin|viewer|super, name, must_change_password }
```
- 역할 판정은 **custom claim** 으로 한다. `users` 문서는 화면 표시용이고 권한 근거가 아니다.

## 3. 인증·규칙

- claim: 사람 `{cid, role}` (super 는 cid 없음), 에이전트 `{cid, pcId, role:"agent"}`.
- RTDB 규칙
  - `live/{cid}/{pcId}`: 읽기 = 같은 cid 또는 super. 쓰기 = agent 이고 claim 의 cid·pcId 일치.
  - `commands/{cid}/{pcId}`: 읽기 = 같은 cid 또는 super. 새 명령 쓰기 = 같은 cid 의 admin 또는 super, `state == "queued"`, `by == auth.uid`. `state/result/started_at/ended_at` 갱신 = 그 PC 의 agent 만.
  - `settings/{cid}/{pcId}`: 읽기 = 같은 cid 또는 super, 그 PC 의 agent. 쓰기 = admin 또는 super.
  - `meta/companies/{cid}`: 읽기 = 같은 cid 또는 super. 쓰기 = super 만.
- Firestore 규칙
  - `runs/{cid}/items/*`: 읽기 = 같은 cid 또는 super. 생성 = 그 cid 의 agent (문서의 pcId 가 claim 과 일치). 수정·삭제 없음.
  - `users/{uid}`: 읽기 = 본인 또는 super. 쓰기 = super 만(관리 스크립트).
- 규칙 시험(에뮬레이터)에 반드시 넣는 것: 다른 회사 읽기 거부, viewer 의 명령 쓰기 거부, admin 이 `state` 를 직접 `done` 으로 쓰기 거부, agent 가 다른 pcId 에 쓰기 거부, `by` 를 남의 uid 로 위조 거부.

## 4. 에이전트 동작

- **시작**: `agent_config.json` 에서 `{cid, pcId, email, password_dpapi, project}` 읽기. 비밀번호는 DPAPI(`CryptProtectData`, 현재 사용자)로 암호화 저장. Auth REST 로 ID 토큰 받기, refresh token 으로 만료 전 갱신. 관리자 권한으로 실행(지금 대시보드와 같음).
- **상태 올리기**: `rpa_status` 상태 파일을 1초 간격으로 mtime 확인 → 바뀌면 `live/.../routine|prepare` PUT. heartbeat 30초. 실행이 끝난 것을 감지하면(`history.jsonl` 새 줄) Firestore `runs` 에 문서 추가.
- **오프라인**: 올리기 실패분은 로컬 큐(`firebase/agent/queue.jsonl`)에 쌓고 연결되면 순서대로 재전송. RPA 는 절대 막지 않는다(기록 실패는 조용히 큐로).
- **명령 구독**: RTDB SSE(`commands/{cid}/{pcId}.json?orderBy="state"&equalTo="queued"`) 로 대기. 끊기면 지수 백오프(1→2→4→…→60초) 재접속.
- **명령 처리** (한 번에 하나, 순서대로)
  1. `expires_at < now` → `expired`.
  2. `launch`: `any_rpa_running()` 이면 `rejected("이미 실행 중")`, 아니면 지금 `launch()` 호출 → `running` → 프로세스 종료 시 `done|failed`(종료 코드).
  3. `stop_erpia`: 지금 대시보드의 ERPia 종료 함수 → `done|failed`.
  4. `set_modules`: `write_routine_modules(args)` → `done`, 실패 사유는 `result`. 전부 끔은 지금처럼 거부.
  5. `set_schedule`: `settings.schedule` 은 화면이 직접 쓰고, 에이전트는 `settings` 를 구독해 예약기(지금 `Scheduler`)에 반영.
- **1PC 1프로그램**: 지금 `launch()` 의 잠금·중복 방지를 그대로 쓴다.
- **배포**: 소스 + `python\` 폴더 (exe 는 SentinelOne 문제로 안 만든다). `에이전트_시작.bat` 은 `대시보드_시작.bat` 과 같은 관리자 확인·기록 방식.

## 5. 화면

- 로그인 화면(이메일/비밀번호). `must_change_password` 면 비밀번호 변경 화면으로.
- super: 회사 선택 → PC 선택. admin/viewer: 자기 회사, PC 가 둘 이상이면 선택.
- 탭은 지금과 같이 현황 / 이력 / 환경설정. 데이터 층만 바뀐다:
  - 현황: `live/{cid}/{pcId}` 구독. heartbeat 가 2분 넘게 없으면 "PC 연결 끊김".
  - 실행·종료 버튼(admin): `commands` 에 push. 그 명령의 `state` 를 구독해 결과 표시. 만료 기본 10분.
  - 환경설정(admin): 모듈 스위치 = `settings.modules` 쓰기 + `set_modules` 명령 push(에이전트가 파일에 반영). 자동 예약 = `settings.schedule` 쓰기.
  - 이력: Firestore `runs/{cid}/items` 를 최근순으로 읽기. (2차)
- 화면의 Firebase 설정값(apiKey 등)은 공개돼도 된다. 보안은 규칙이 한다.

## 6. 오류 처리

- 에이전트: 토큰 만료·네트워크 오류·SSE 끊김은 전부 재시도. 파일 쓰기 실패(`write_routine_modules`)는 명령 `failed` + 사유. 처리 중 예외는 명령 `failed` 로 닫고 에이전트는 계속 돈다. 기록은 `firebase/agent/에이전트_기록.txt`(회전 1MB).
- 화면: 권한 거부(규칙)는 "권한 없음" 으로, 명령이 10분 안에 `running` 이 안 되면 "PC 가 응답하지 않습니다".
- 어느 쪽도 비밀번호를 기록·응답에 싣지 않는다.

## 7. 시험

- 규칙: Firebase 에뮬레이터 + `@firebase/rules-unit-testing` (Node). 3절의 거부 케이스 전부.
- 에이전트 단위: `urllib` 를 가짜로 바꿔 명령 상태 전이·만료·오프라인 큐·토큰 갱신을 시험(파이썬, `firebase/tests/test_agent.py`).
- 통합: 에뮬레이터(RTDB·Firestore·Auth)에 에이전트를 붙여 `launch`(DRY_RUN) → `done` 까지.
- 실기: 사내 PC 1대, erpiatest2. Login 만 켠 실행부터.

## 8. 1차 범위와 그 뒤

**1차(첫 계획서):** 사전 준비(Node, CLI, 프로젝트 생성, Auth·RTDB·Firestore 생성) → 규칙 + 규칙 시험 → 관리 스크립트(회사 1, PC 1, super 1, admin 1, agent 1 등록) → 에이전트(상태 올리기·heartbeat·launch·stop_erpia·set_modules·오프라인 큐) → 화면(로그인·현황·실행/종료·모듈 스위치) → 사내 PC 1대 실기.

**2차:** 이력 탭(Firestore), 자동 예약(`set_schedule`), super 의 회사 선택, 두 번째 회사 등록 리허설.

**그 뒤:** 알림(실패 시 이메일, 여기서 Functions 가 필요해질 수 있음), 옛 `rpa_dashboard.py` 정리 시점 결정.

## 9. 콘솔 준비 (2026-09-21 완료)

| 항목 | 값 |
|---|---|
| 소유 계정 | hjjang96@gmail.com |
| 프로젝트 ID | `rpa-test-f02e0` |
| RTDB | `https://rpa-test-f02e0-default-rtdb.asia-southeast1.firebasedatabase.app` (싱가포르, 잠금 모드) |
| Firestore | asia-northeast3(서울), 프로덕션 모드 |
| Auth | 이메일/비밀번호 켬 |
| 웹 앱 | 닉네임 `dashboard` |
| 서비스 계정 키 | `firebase/admin/serviceAccountKey.json` (gitignore 됨, 고객 PC 에 절대 복사 금지) |

화면이 쓸 설정값(공개돼도 되는 값 - 보안은 규칙이 한다):

```js
const firebaseConfig = {
  apiKey: "AIzaSyCFbHQjWVxzi38IAYIhQX9wyiGIs1VcZuA",
  authDomain: "rpa-test-f02e0.firebaseapp.com",
  databaseURL: "https://rpa-test-f02e0-default-rtdb.asia-southeast1.firebasedatabase.app",
  projectId: "rpa-test-f02e0",
  storageBucket: "rpa-test-f02e0.firebasestorage.app",
  messagingSenderId: "420865367421",
  appId: "1:420865367421:web:14b9e1e10c5fadc7e04014"
};
```

남은 사용자 작업: `firebase login` (브라우저 인증, CLI 설치 뒤).
