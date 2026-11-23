# 스탠드얼론 ② 업체 웹 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 스탠드얼론 PC 의 브라우저(`http://127.0.0.1:8781/`)에서 지금 업체 웹 화면 그대로 로그인·현황·실행·환경설정·기록을 쓰고, 그 화면이 이 PC 밖으로 아무것도 부르지 않는다.

**Architecture:** 업체 웹(`firebase/web`)의 Firebase SDK 호출을 `data.js` 한 곳으로 모으고 구현을 둘로 둔다 - `data-firebase.js`(지금 동작 그대로)와 `data-local.js`(fetch + 스트림 하나). 로컬 서버에 새 파일 `local_web.py` 가 계정·탭 단위 세션·`/api/*`·웹 파일 내주기를 맡는다. 어느 구현을 쓸지는 서버가 내주는 `edition.js` 가 정한다.

**Tech Stack:** 브라우저 ES 모듈(빌드 도구 없음), Python 표준 라이브러리(hashlib.pbkdf2_hmac·secrets·http.server), 화면 시험은 Playwright(.venv, 깔린 Edge - 지금 `firebase/tests/check_web.py` 와 같은 방식).

**Spec:** `docs/superpowers/specs/2026-11-23-standalone-local-server-design.md` (6.3·6.5·8절). 앞 계획 ① `2026-11-23-standalone-1-server-core.md` 의 이름을 쓴다.

## Global Constraints

- 일반(cloud) 버전의 화면 동작·글·오류 문구는 바뀌지 않는다. Task 1 뒤 `firebase/tests/check_web.py` 가 에뮬레이터에서 그대로 통과해야 다음으로 간다 (지금 578건). `tests/test_server_info.py`·`firebase/tests/check_indexes.py` 도 통과.
- 스탠드얼론 웹은 `127.0.0.1` 밖으로 요청하지 않는다 (글꼴·SDK 포함). 스탠드얼론 서버는 `firebase-config.js`·`data-firebase.js` 를 내주지 않는다 (404).
- 오류 `code` 문자열은 지금 화면이 견주는 값 그대로 쓴다: `PERMISSION_DENIED`(RTDB 꼴 자리·명령), `permission-denied`(실행 기록), `auth/invalid-credential`·`auth/wrong-password`·`auth/weak-password`·`auth/user-disabled`·`auth/too-many-requests`. 화면 쪽 문구 코드는 손대지 않는다.
- 웹 역할은 `admin`(관리자)·`viewer`(유저) 둘. 명령·계정 관리는 `admin` 만.
- 로그인은 **탭 단위** (지금 웹과 같다 - 탭을 닫으면 끝, 30분 미사용 로그아웃): 세션 토큰을 쿠키가 아니라 탭 저장소(sessionStorage)에 두고 `Authorization: Bearer` 로 보낸다. 쿠키를 쓰지 않으므로 다른 사이트가 이 PC 주소로 요청을 보내도 로그인이 따라가지 않는다. (설계 6.2 의 '쿠키 + X-RPA-Action' 에서 바꿈 - Ruling: 탭 단위 규칙을 지키고 CSRF 길을 없애려고. 비용: 스트림을 EventSource 대신 fetch 로 읽어야 한다.)
- 비밀번호는 `hashlib.pbkdf2_hmac("sha256", …, 310000)` + 계정마다 소금 16바이트. 비밀번호·세션 토큰·열쇠는 기록에 싣지 않는다.
- 서버 응답 보안 머리글 (웹 파일·`/api`): `Content-Security-Policy: default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Cache-Control: no-store`(api) / `no-cache`(파일), `Referrer-Policy: no-referrer`.
- 새 화면 요소(계정 칸)는 지금 카드·표·단추 모양을 그대로 따른다. 다 만든 뒤 사용자에게 화면을 보여 준다.
- 파이썬 실행은 `D:/AX/RPA/.venv/Scripts/python.exe` (워크트리에 .venv 없음). 패치는 Write 도구 파일로. 커밋 글은 파일로(`git commit -F`), 끝에 `Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>`. push 는 사용자 지시가 있을 때만.

## Review Focus

1. 로그인한 탭을 30분 두었다가 누름 → 서버도 그 세션을 받지 않는다 (화면만 지키지 않는다) - Task 2 시험.
2. 비밀번호를 여섯 번 틀림 → 60초 잠금, 맞는 비밀번호도 그동안 거절, 잠금이 풀리면 로그인 - Task 2 시험.
3. 유저(viewer)가 화면을 우회해 `POST /api/commands`·계정 창구를 직접 부름 → 403 - Task 2 시험.
4. 서버(에이전트)가 다시 켜져 스트림이 끊김 → 화면이 스스로 다시 붙고 현황이 이어진다, 세션이 사라졌으면 로그인 화면 - Task 3·5 시험.
5. `/..%2f` 같은 주소로 웹 폴더 밖 파일(열쇠·라이선스·계정 파일)을 달라고 함 → 404 - Task 2 시험.

---

### Task 1: 웹 데이터 자리 모으기 (일반 버전 동작 그대로)

**Files:**
- Create: `firebase/web/config.js`, `firebase/web/edition.js`, `firebase/web/data.js`, `firebase/web/data-firebase.js`
- Modify: `firebase/web/app.js`, `rpa.js`, `rpa-common.js`, `rpa-settings.js`, `account.js`, `firebase-config.js`, `tests/test_server_info.py`, (필요하면) `firebase/tests/check_web.py` 의 import 경로
- Test: `firebase/tests/check_web.py` (에뮬레이터), `tests/test_server_info.py`, `firebase/tests/check_indexes.py`

**Interfaces:**
- Produces (`data.js` - `edition.js` 의 `EDITION` 을 보고 구현 하나를 **동적 import** 해 같은 이름으로 다시 내보낸다. 정적 import 금지 - 스탠드얼론 웹에 gstatic·프로젝트 주소가 실리면 안 된다):
  - `EDITION: "cloud" | "standalone"` (`edition.js` 는 저장소에 `export const EDITION = "cloud";` 한 줄)
  - `init(): Promise<void>` - cloud: initializeApp(기본 앱 그대로)·`setPersistence(browserSessionPersistence)`·에뮬레이터 연결(`?emu=1`, Firestore 포함)·`#t=` 열쇠 넘겨받기까지.
  - `onSession(cb)` - `cb(null)` 로그아웃, `cb({uid, email, cid, role, consoleLeftMs?})` 로그인(토큰 claims 를 새로 받은 뒤), `cb({error: "network"})` 토큰을 못 받음. `consoleLeftMs` 는 uid 가 관리 화면 열쇠 계정일 때만.
  - `signIn(cid, id, password): Promise<void>` (실패는 `e.code`), `signOut(): Promise<void>`, `signedIn(): boolean`(동기), `sessionUid(): string|null`(동기), `handoffFailed(): boolean`(init 에서 `#t=` 가 거절됐나)
  - `changePassword(current, next): Promise<void>`
  - `emailFor(cid, id): string` (cloud 전용 - local 은 `undefined`)
  - `getCompany(cid): Promise<{name, stts, pcs, apps}>` (못 읽으면 `{}`)
  - `watch(path, cb(value), onError?(e)): unsubscribe` - RTDB 꼴 자리 글 그대로 (`apps/rpa/live/…`, `meta/companies/<cid>/apps/rpa/limits/schedule` …)
  - `skewReady(): Promise<void>`, `skewMs(): number` (서버 시각 - 브라우저 시각)
  - `pushCommand(cid, pcId, command): Promise<string>` (명령 키) - command 는 지금 모양 `{type, args, by, created_at, expires_at, state}`
  - `saveSettings(cid, pcId, part, value): Promise<void>` (`apps/rpa/settings/<cid>/<pc>/<part>`)
  - `listRuns(cid, {pcId, date, limit}): Promise<object[]>`, `getWallet(cid): Promise<{granted, since}|null>`, `watchWallet(cid, cb): unsubscribe`, `sumRuns(cid, field, {from, to}): Promise<number>`
- `config.js`: `HEARTBEAT_EVERY_DEFAULT`, `HEARTBEAT_MISS`, `COMMAND_TTL_SEC` (firebase-config.js 에서 옮김 - 그 파일에는 `firebaseConfig` 만 남긴다)
- `app.js` 의 `ctx()`: `db`·`auth` 를 빼고 `edition: EDITION` 을 더한다. `emailFor`·`IDLE_MIN` 등 export 는 app.js 에 남긴다 (`export const emailFor = data.emailFor` 꼴 - check_web 이 app.js 에서 가져온다).

조사에서 나온 주의점 (이대로 지킨다):
- SDK 를 부르는 곳은 app.js 19·rpa-common.js 3·rpa-settings.js 10(구독 5 + 설정 쓰기 5)·rpa.js 8·**account.js 1**(재인증 + 비밀번호 변경). 옮긴 뒤 `firebase/web` 에서 `gstatic.com` 문자열은 `data-firebase.js` 에만 있어야 한다.
- 기본 앱(`initializeApp(firebaseConfig)`, 이름 없음)을 유지한다 - check_web 이 gstatic 모듈에서 `getApp()`·`getAuth()` 로 같은 앱을 잡는다. 탭 저장소 열쇠(`firebase:authUser:`)도 그대로여야 한다.
- 로그인·로그아웃·새로고침 복원은 지금 `onAuthStateChanged` 한 콜백이 다 맡는다 - `onSession` 이 그 순서(먼저 `getIdTokenResult(true)`, 실패하면 network)를 그대로 옮긴다. 미사용 로그아웃·콘솔 1시간·에이전트 계정 거절·중지 업체 처리는 app.js 에 남는다.
- features 구독이 `c.policy` 를 바꿔 쓰는 부작용(rpa-settings.js:188)은 화면 쪽에 그대로 둔다.
- `.info/serverTimeOffset` 구독은 `skewReady/skewMs` 뒤로. Firestore 에뮬레이터 연결(rpa.js:150)은 `init()` 으로.
- 실행 기록 오류 code 는 소문자 `permission-denied`, RTDB 는 대문자 `PERMISSION_DENIED` - 그대로 올라오게 한다.
- `tests/test_server_info.py:44` 는 `app.js` 에 `${firebaseConfig.authDomain}` 글자가 있는지 본다 → `data-firebase.js` 를 보게 고친다. 프로젝트 이름은 `firebase-config.js` 밖 새 파일에 박지 않는다 (52-59 목록).
- `firebase/tests/check_indexes.py` 가 `rpa-common.js` 의 `MODULES`·`WELLIFE_MODULES` 배열을 정규식으로 읽는다 - 이름·모양 유지.

- [ ] **Step 1: 기준 재기** - 고치기 전에 에뮬레이터에서 check_web 을 돌려 통과 수를 적는다 (firebase/tests 에서, JDK 25 를 PATH 앞에: `export PATH="/c/Users/20251216-003/.jdks/openjdk-25.0.2/bin:$PATH"; firebase emulators:exec --config ../firebase.json --only auth,database,firestore,hosting --project rpa-test-f02e0 "D:/AX/RPA/.venv/Scripts/python.exe check_web.py"`). 에뮬레이터에만 붙는다 - 실서버 금지.
- [ ] **Step 2: `config.js`·`edition.js`·`data-firebase.js`·`data.js` 를 만들고 다섯 파일의 SDK 호출을 `data.*` 로 바꾼다.** 화면 코드의 흐름·문구는 건드리지 않는다.
- [ ] **Step 3: `tests/test_server_info.py` 를 고치고 돌린다** → 통과. `grep -rn "gstatic.com" firebase/web` 은 `data-firebase.js`(와 index.html 의 글꼴 줄 - Task 3 이 없앤다)만.
- [ ] **Step 4: check_web 다시** → Step 1 과 같은 수, 실패 0. `check_indexes.py` 통과.
- [ ] **Step 5: 커밋** - "스탠드얼론 ② Task 1 - 업체 웹의 Firebase 호출을 data.js 한 곳으로 (일반 버전 동작 그대로)".

### Task 2: 로컬 서버의 웹 창구 (`local_web.py`)

**Files:**
- Create: `firebase/agent/local_web.py`
- Modify: `firebase/agent/local_server.py` (`Handler._route` 가 `/api/`·그 밖의 GET 을 `local_web` 로 넘김, `make_server` 가 `srv.web = local_web.Web(...)` 을 단다, 보안 머리글)
- Test: `tests/test_local_web_api.py`

**Interfaces:**
- Consumes: 계획 ① `Store`·`Runs`·`classify`·`log`·`data_dir`·라이선스 dict(`cid`·`pc_id`·`company`·`modules`·`features`·`limits`).
- Produces (`local_web`):
  - `class Accounts(path)` - `accounts.json`. `set(id, password, role, must_change=False)`(만들기·비밀번호 다시 정하기 - 설치 마법사·설정 창이 부른다, 계획 ③), `verify(id, password) -> dict|None`, `list() -> [{id, role, disabled, must_change}]`, `disable(id, on)`, `remove(id)`, `change_password(id, current, new)`. id 는 `^[a-z0-9_.-]{2,32}$`(소문자로 바꿔 견준다), 비밀번호 8자 이상. 마지막 `admin` 은 지우거나 중지할 수 없다 (`ValueError` 사람 말).
  - `class Sessions(idle_sec=1800, max_sec=43200, clock=time.time)` - `open(account) -> token`(secrets.token_urlsafe(32)), `get(token, touch=False) -> dict|None`(idle·max 넘으면 지우고 None), `close(token)`, `close_account(id)`. 메모리에만 (서버를 다시 켜면 모두 풀린다).
  - `class Lockout(limit=5, lock_sec=60, clock=time.time)` - 계정마다 연속 실패 5번이면 60초 잠금. `locked(id) -> bool`, `fail(id)`, `ok(id)`.
  - `class Web(store, runs, lic, folder, web_dir, clock=time.time)` - `handle(handler, method, path, query) -> bool`(처리했으면 True).
  - `web_dir() -> str` - 웹 파일 폴더: `rpa_status.program_dir()\firebase\web` 가 있으면 그것, 없으면 소스의 `firebase/web`.
  - 명령 만료: `QUICK_TTL = 90`(launch·stop_erpia·stop_rpa), `COMMAND_TTL = 600`. 웹이 보낼 수 있는 종류 `WEB_TYPES = (launch, stop_erpia, stop_rpa, set_modules, set_schedule, set_presets, set_parallel, set_together, resume_repeat)` - 프리셋 옮기기 셋·update·rollback 은 없다.
- 창구 (`/api/*` 는 JSON, 오류는 `{"code": "...", "message": "사람 말"}`):

| 주소 | 누가 | 하는 일 |
|---|---|---|
| `POST /api/login` `{id, password}` | 누구나 | 성공 `{token, session}`. 틀림 401 `auth/invalid-credential`, 잠김 429 `auth/too-many-requests`, 중지 403 `auth/user-disabled`. 없는 아이디도 같은 시간이 걸리게 가짜 해시를 한 번 계산한다 |
| `GET /api/session` | 로그인 | `{session: {uid, id, email, cid, role, mustChange}, now_ms}` (`uid` = `email` = 아이디). `?touch=1` 이면 미사용 시계를 다시 0 으로 |
| `POST /api/logout` | 로그인 | 세션 닫기 |
| `POST /api/password` `{current, next}` | 로그인 | 틀리면 `auth/wrong-password`, 8자 미만 `auth/weak-password`. 성공하면 `must_change` 를 끄고 그 계정의 다른 세션을 닫는다 |
| `GET /api/company` | 로그인 | `{name: lic.company, stts: 0, pcs: {<pc_id>: {label: 컴퓨터 이름}}, apps: {rpa: {modules, limits, features}}, cid, pcId}` |
| `GET /api/stream` | 로그인 | SSE: `event: live` data = 현황 전체 (붙을 때 한 번 + 바뀔 때마다), `event: command` data = `{key, value}` (바뀐 명령 하나), 30초마다 `event: keep-alive`. 세션이 끝나면 `event: gone` 을 보내고 닫는다 |
| `POST /api/commands` `{type, args}` | admin | 서버가 `by`=아이디·`created_at`=지금(초)·`expires_at`=지금+TTL·`state:"queued"` 로 만들어 `{key, value}`. 종류가 `WEB_TYPES` 밖 400, `args` 가 null·dict 아님 400, `args` 에 `excel_pw` 칸 400, viewer 403 `PERMISSION_DENIED`. 키는 `f"{ms:013d}{secrets.token_hex(4)}"` (만든 순서로 줄 선다) |
| `GET /api/commands/<key>` | 로그인 | 명령 하나 (없으면 null) |
| `GET /api/runs?date=YYYY-MM-DD&limit=N` | 로그인 | `Runs.query("runs/<cid>", "items", pc_id, date, limit)` (limit 1~200, 기본 100). 다른 PC·업체 값은 받지 않는다 |
| `GET /api/accounts` · `POST /api/accounts` `{id, password, role}` · `POST /api/accounts/<id>` `{disabled?, password?}` · `DELETE /api/accounts/<id>` | admin | 계정 목록·추가(`viewer`·`admin`)·사용 중지·비밀번호 다시 정하기(그 계정은 `must_change`)·지우기. 자기 자신 중지·지우기와 마지막 admin 은 400. 바뀐 계정의 세션을 닫는다 |
| `GET /`·`/index.html`·`/<파일>` | 누구나 | 웹 파일. `/edition.js` 는 늘 `export const EDITION = "standalone";`. `firebase-config.js`·`data-firebase.js` 는 404. 확장자 허용 목록(html·js·css·png·webp·svg·ico·woff2·json)만, 조각에 `..`·`\`·`:` 가 있거나 폴더 밖이면 404. `index.html` 은 `google-site-verification` 줄을 빼고 낸다 |

  - 모든 `/api` 요청: Host 검사(계획 ① 과 같다) + `Origin` 머리글이 있으면 `http://127.0.0.1:<포트>`·`http://localhost:<포트>` 만 (다르면 403). 세션은 `Authorization: Bearer <토큰>` - 에이전트 열쇠(`/db`·`/fs`)와 세션 토큰은 서로의 창구에서 통하지 않는다.
  - 본문은 64KB 까지 (`/api`).
  - 로그인 성공·실패·잠금, 계정 바꿈은 `local_server.log` 에 아이디만 남긴다 (비밀번호·토큰 없음).

계획 ① 검토(2026-11-23) 뒤 바뀐 것 - 이 작업이 맞춰야 한다 (`local_server.py` 를 읽고 시작):
- `/db`·`/fs` 는 이제 열쇠를 보내지 않고 요청 서명으로 확인한다 (`Handler._route` 가 본문을 읽고 `_role(method, digest)` 로 서명을 본 뒤 길을 고른다, 응답에도 서명). `/api/*` 와 웹 파일은 **서명 확인 앞에서** 갈라 `local_web` 로 넘긴다 - 세션 토큰(브라우저)과 서명(에이전트)은 서로의 창구에서 통하지 않는다. Host 검사·본문 읽기(`_read`)·연결 상한·읽기 15초 제한은 같이 쓴다.
- `Store.put/patch/delete(..., guard=)` - 잠금 안에서 확인하고 쓴다 (`Refused`). 웹의 명령 만들기는 `guard=lambda get: get(path) is None` 로 (같은 키를 덮지 않게).
- 현황(`apps/rpa/live`)은 파일에 남지 않는다 - 서버를 다시 켠 직후 `live` 가 비어 있을 수 있다 (`event: live` data = null). 화면은 그때 '연결 끊김' 모양이면 된다.
- 주소 조각은 `Handler._parts` 처럼 풀었을 때 `/`·`\` 가 있으면 거절한다 (`%2F`).
- `/api/stream` 의 구독도 `q.overflow` 를 보고 끊는다.

- [ ] **Step 1: 실패하는 시험** `tests/test_local_web_api.py` - 임시 폴더에 서버를 띄우고(`make_server(..., port=0)`), `Accounts.set("boss", "pw-12345678", "admin")`·`set("staff", …, "viewer")` 뒤 urllib 로. 넣을 검사 (각각 이름 붙은 check):
  - 로그인: 맞음 → 토큰·`session.role == "admin"`; 틀림 401 `auth/invalid-credential`; 없는 아이디도 401 같은 code; 대문자 아이디 `BOSS` 도 로그인; 중지 계정 403.
  - 잠금 (Review Focus 2): 가짜 시계로 5번 틀린 뒤 맞는 비밀번호 429, 61초 뒤 로그인, 성공하면 실패 수가 0.
  - 세션 (Review Focus 1): 토큰 없이 `/api/session` 401; 가짜 시계 1801초 뒤 401; `?touch=1` 이 시계를 되돌림; 12시간 넘으면 touch 해도 401; 로그아웃 뒤 401; 에이전트 열쇠로 `/api/session` 401, 세션 토큰으로 `/db/...` 401.
  - 명령 (Review Focus 3): admin `launch` → 저장소에 `{state: "queued", type, args, by: "boss", expires_at - created_at == 90}`; `set_schedule` 은 600; viewer 403 `PERMISSION_DENIED`; `update`·`export_preset` 400; `args` 에 `excel_pw` 400; `args` 문자열 400; 만든 명령을 에이전트 열쇠가 `running` 으로 옮길 수 있다 (계획 ① 검사와 맞물림); `GET /api/commands/<key>`.
  - 스트림: 붙으면 `live` 한 번; `store.put(live…)` 뒤 `live` 다시; 명령 상태를 바꾸면 `command` `{key, value}`; 세션을 닫으면 `gone` 뒤 끝; 토큰 없으면 401.
  - 기록: `runs.create` 두 건 뒤 최근 순·`date` 거르기·`limit`.
  - 계정: admin 이 viewer 추가·목록·중지(그 계정 로그인 403·열린 세션 401)·비밀번호 다시 정하기(`mustChange`)·지우기; viewer 는 403; 자기 자신 지우기·마지막 admin 중지 400; 아이디 꼴·짧은 비밀번호 400.
  - 비밀번호 바꾸기: 틀린 현재 비밀번호 `auth/wrong-password`; 7자 `auth/weak-password`; 성공 뒤 옛 비밀번호 로그인 실패·`mustChange` 꺼짐.
  - 파일 (Review Focus 5): `/` 200 html + CSP 머리글; `/edition.js` 본문에 `standalone`; `/firebase-config.js`·`/data-firebase.js` 404; `/..%2fstandalone%2fagent.key`·`/%2e%2e/license.json`·`/app.js%00.png`·`/C:%5CWindows%5Cwin.ini` 404; `.webp` 는 `image/webp`; `index.html` 에 `google-site-verification` 없음.
  - Origin: `Origin: http://evil.example` 인 `POST /api/login` 403; Origin 없는 요청(주소창)은 통과.
  - 기록 파일에 비밀번호·토큰이 없다.
- [ ] **Step 2: 실패 확인** → `ModuleNotFoundError: local_web`.
- [ ] **Step 3: 구현.** `accounts.json` 은 임시 파일 → `os.replace`. 비밀번호 견주기는 `hmac.compare_digest`. 스트림은 계획 ① `_stream` 처럼 `Store.subscribe` 큐를 0.5초씩 기다리며 `srv.stopping` 과 세션을 본다.
- [ ] **Step 4: 통과 확인** + 계획 ① 시험 여섯 파일.
- [ ] **Step 5: 커밋** - "스탠드얼론 ② Task 2 - 로컬 서버의 웹 창구 (계정·탭 단위 세션·/api·웹 파일)".

### Task 3: `data-local.js` · 스탠드얼론에서 숨길 것 · 로컬 글꼴

**Files:**
- Create: `firebase/web/data-local.js`, `firebase/web/fonts/` (Pretendard Variable woff2 한 파일, JetBrains Mono 400·500 woff2, `fonts.css`, 각 글꼴의 OFL 라이선스 글)
- Modify: `firebase/web/index.html` (10·11행의 CDN 글꼴 → `fonts/fonts.css`), `app.js`·`rpa.js`·`rpa-settings.js`·`account.js` (edition 조건)
- Test: `tests/check_web_local.py` (Playwright, 새로)

**Interfaces:**
- Consumes: Task 1 `data.js` 의 이름 전부, Task 2 `/api/*`.
- Produces: `data-local.js` 가 Task 1 의 이름을 모두 내보낸다.
  - 세션 토큰은 `sessionStorage["ap.session"]`. `init()` 은 토큰이 있으면 `GET /api/session` 으로 되살린다 (401 이면 지움).
  - `onSession` 의 값 `{uid, email, cid, role, mustChange}`. `signIn` 은 `cid` 를 보내지 않는다 (PC 하나에 업체 하나).
  - `watch(path, cb)`: **스트림 하나**(`fetch("/api/stream")` 을 ReadableStream 으로 읽는다 - EventSource 는 머리글을 못 싣고, 브라우저는 한 주소에 연결 6개까지만 연다)에서 받은 현황·명령을 기억해 두고 자리 글에 맞춰 나눠 준다: `apps/rpa/live/<cid>/<pc>`(와 그 아래) → 현황, `apps/rpa/commands/<cid>/<pc>/<key>` → 그 명령(스트림이 다시 붙으면 `GET /api/commands/<key>` 로 한 번 채운다), `meta/companies/<cid>/apps/rpa/...` → `getCompany` 값에서 한 번, 다른 PC 자리 → 한 번 `null`. 스트림이 끊기면 1·2·4…30초 물러서며 다시 붙고, 401·`gone` 이면 세션을 지우고 `onSession(null)`.
  - `pushCommand` 는 `{type, args}` 만 보낸다 (by·시각은 서버가 정한다). `saveSettings` 는 아무것도 하지 않고 성공. `getWallet` → `null`, `watchWallet` → 아무것도 안 부르는 해제 함수, `sumRuns` → `0`. `skewMs` 는 `/api/session` 의 `now_ms` 로.
  - 미사용 시계: app.js 가 입력을 적을 때(5초에 한 번) `data.touch?.()` 를 부른다 - local 은 60초에 한 번 `GET /api/session?touch=1` (cloud 는 없음).
- 스탠드얼론에서 숨기거나 바꾸는 것 (`c.edition === "standalone"` / `EDITION`):
  - 로그인 화면의 업체코드 칸 (PC 하나에 업체 하나), `#super-bar`·`?cid=` 띠·`#t=` 처리.
  - `#ai-card` (rpa-settings.js - 지금은 조건 없이 보인다), 기록 표의 '토큰 사용량' 열 (머리·칸), 토큰 카드·사용량 카드는 `live.tokens` 가 없어 저절로 숨는다 (그래도 조건을 건다).
  - 글: rpa.js NO_PC 의 '에이전트 계정을 연결하면' → '오토파일럿 설정을 마치면', 변조 안내의 '같은 버전으로 다시 업데이트하면' → '같은 버전 설치 파일로 다시 설치하면', account.js 성공 글의 '다른 기기는' → '다른 탭은'. '새 버전으로 업데이트' 안내 넷은 '새 버전 설치 파일로 설치' 로.
  - `mustChange` 인 계정은 계정 화면만 보이고 (메뉴 잠금), 비밀번호를 바꾸면 풀린다.
  - `auth/too-many-requests` → "로그인 시도가 많아 잠시 잠겼습니다. 1분 뒤 다시 시도하여 주십시오." (두 버전 공통 - 지금은 code 가 그대로 보인다).
- 글꼴: Pretendard 는 가변 글꼴 한 파일(`PretendardVariable.woff2`, 글꼴 이름 `"Pretendard Variable"`, weight 45 920), JetBrains Mono 는 400·500 (latin). 두 버전 공통으로 로컬 사본을 쓴다 (index.html 하나, CSP 가 단순해진다).

- [ ] **Step 1: 실패하는 화면 시험** `tests/check_web_local.py` - 임시 폴더·시험 라이선스로 서버를 같은 프로세스 스레드로 띄우고 (그래서 PC 쪽은 `store.put/patch` 로 흉내 낸다), `Accounts.set` 으로 admin·viewer, Playwright 로:
  - 로그인 화면에 업체코드 칸이 없다, 틀린 비밀번호 문구, 로그인 → 업체 이름·'(관리자)'.
  - 현황: `store.put(live)` 한 값(heartbeat·programs·schedule)이 화면에 뜬다, 바꾸면 따라 바뀐다.
  - [실행] → 저장소에 `launch` 명령(`by` = 아이디, 90초), `store.patch(state: "running")`·`done` 에 따라 토스트.
  - 환경설정: 모듈 [적용] → `set_modules` 명령 하나, 자동 실행 [적용] → `set_schedule`.
  - 기록 탭: `runs.create` 한 두 건이 뜨고 '토큰 사용량' 열이 없다.
  - 안 보이는 것: `#token-card`·`#usage-card`·`#ai-card`·`#copy-card`·`#pc-pick`·`#super-bar`.
  - viewer: [실행]·환경설정 메뉴가 없다.
  - 비밀번호 바꾸기 → 다시 로그인. `mustChange` 계정은 계정 화면만.
  - 탭 단위: 새 탭(같은 브라우저 컨텍스트)은 로그인 화면, 새로고침은 로그인 유지.
  - 서버 다시 켜기 (Review Focus 4): `srv.shutdown()` 뒤 같은 포트로 다시 → 세션이 사라졌으므로 로그인 화면으로; (세션을 살려 둔 경우) 스트림만 끊겼다 붙으면 현황이 이어진다 - 뒤쪽은 `Web` 을 그대로 두고 서버만 다시 만들어 확인.
  - **바깥 요청 0**: `page.on("request")` 로 모은 주소가 모두 `http://127.0.0.1:<포트>/`.
  - 콘솔 오류 0 (CSP 위반 포함).
- [ ] **Step 2: 실패 확인.**
- [ ] **Step 3: 글꼴 파일 넣기·`data-local.js`·edition 조건.**
- [ ] **Step 4: 통과 확인** + 에뮬레이터 check_web(일반 버전) 다시 → Task 1 과 같은 수 (글꼴·문구 조건이 일반 버전을 건드리지 않았는지).
- [ ] **Step 5: 커밋** - "스탠드얼론 ② Task 3 - 로컬 서버를 읽는 웹(data-local)·스탠드얼론에서 숨길 것·로컬 글꼴".

### Task 4: 계정 칸 (관리자)

**Files:**
- Modify: `firebase/web/account.js` (스탠드얼론·관리자일 때 '계정 관리' 카드), `firebase/web/data-local.js` (`listAccounts`·`addAccount`·`updateAccount`·`removeAccount`), `tests/check_web_local.py`

**Interfaces:**
- Consumes: Task 2 `/api/accounts*`.
- Produces: 계정 화면 아래 카드 - 표(아이디·권한·상태) + 줄마다 [비밀번호 다시 정하기]·[사용 중지/다시 사용]·[삭제], 아래에 추가 줄(아이디·비밀번호·권한 고르기·[추가]). 지금 카드·표·단추 class 를 그대로 쓴다. 자기 줄에는 [삭제]·[사용 중지] 가 없다. 삭제는 확인 창.

- [ ] **Step 1: 화면 시험에 더하기** - 추가한 유저로 로그인된다, 사용 중지하면 그 계정 로그인 문구 '사용이 중지된 계정입니다.', 다시 정한 비밀번호로 로그인하면 계정 화면만(mustChange), viewer 에게는 카드가 없다, 서버 거절 글이 토스트로.
- [ ] **Step 2: 실패 확인 → 구현 → 통과.**
- [ ] **Step 3: 화면 사진을 찍어 사용자에게 보인다** (`tests/shots/` 는 커밋 금지 목록 - 사진은 스크래치 폴더에).
- [ ] **Step 4: 커밋** - "스탠드얼론 ② Task 4 - 계정 관리 칸 (관리자)".

### Task 5: 끝에서 끝까지 · 정리

**Files:**
- Modify: `tests/test_standalone_e2e.py` (웹 창구로 명령 넣기), `docs/superpowers/plans/2026-11-23-standalone-index.md` (상태)
- Test: 위 + 모든 스탠드얼론 시험·일반 버전 시험

- [ ] **Step 1: e2e 에 더하기** - 진짜 에이전트가 도는 동안 `POST /api/login` → `POST /api/commands {type: "set_schedule", …}` → 에이전트가 처리해 `done` → `/api/stream` 으로 그 결과가 온다. 바깥 연결 0 은 그대로.
- [ ] **Step 2: 전체 시험** - 스탠드얼론 시험 모두, 일반 버전 시험(`test_agent`·`test_fb_backoff`·`test_cloud_scrub`·`test_dev_env`·`test_background`·`test_rpa_update`·`test_otp_replay`·`test_server_info`), 에뮬레이터 check_web. `graphify update .`.
- [ ] **Step 3: 커밋** - "스탠드얼론 ② Task 5 - 웹까지 끝에서 끝까지".
