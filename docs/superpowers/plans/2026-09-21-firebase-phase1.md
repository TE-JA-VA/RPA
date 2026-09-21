# Firebase 다회사 대시보드 1차 구현 계획

> **진행 (2026-09-21):** Task 1~11 완료, 브랜치 `firebase-phase1`. JDK 는 21 (firebase-tools 15 요구). 규칙 22 · 에이전트 단위 54 · 통합 10 · 화면 28 전부 통과. Task 9 는 `integration.js` 가 자동으로 돌리고, Task 10·11 은 `check_web.py`(Playwright, `?emu=1`) 가 검사한다. Task 12 는 콘솔 Authentication 켜기·계정 등록·`firebase login` 뒤에.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 사내 PC 1대의 RPA 상태를 클라우드 화면에서 보고, 그 화면에서 실행·ERPia 종료·실행 모듈 변경을 시킬 수 있게 한다.

**Architecture:** 서버 코드 없음. 정적 화면(Firebase Hosting)이 Firebase JS SDK 로 Realtime DB 를 직접 읽고 쓰고, PC 에 상주하는 파이썬 에이전트가 표준 라이브러리만으로 REST/SSE 로 같은 DB 에 붙는다. 권한은 전부 DB 보안 규칙이 강제한다. 에이전트는 기존 `rpa_dashboard.py` 의 `launch()` / `stop_erpia()` / `st.write_routine_modules()` 를 **import 해서** 쓴다 (복사하지 않는다).

**Tech Stack:** Firebase Realtime Database / Firestore / Auth / Hosting, Firebase CLI 15.30.2, Node 24.19.0 (규칙 시험·관리 스크립트 전용), Python 3.14 표준 라이브러리 (에이전트), Firebase JS SDK v10 (CDN 모듈).

**Spec:** `docs/superpowers/specs/2026-09-19-firebase-design.md`

## Global Constraints

- **`firebase\` 밖의 기존 파일을 수정하지 않는다.** 시연용 `rpa_dashboard.py` / `dashboard.html` / `run_routine.py` 는 이 계획이 끝날 때까지 그대로 돌아가야 한다. 예외는 `.gitignore` 뿐이다.
- **비밀번호를 채팅·로그·응답·커밋에 싣지 않는다.** `firebase/admin/serviceAccountKey.json`, `firebase/agent/agent_config.json` 은 이미 `.gitignore` 에 있다. 새로 만드는 비밀 파일도 반드시 먼저 `.gitignore` 에 넣고 만든다.
- **`ERPIA_AI.txt` 와 `WebManageConfig.json` 의 내용은 어떤 경로로도 클라우드에 올리지 않는다.** 에이전트가 올리는 것은 `rpa_status.dashboard_snapshot()` 결과와 heartbeat 뿐이다.
- **`.venv` 에 아무것도 설치하지 않는다** (RPA 실행·exe 빌드 전용). 에이전트는 표준 라이브러리만 쓰므로 설치가 필요 없다. 관리 스크립트와 규칙 시험은 Node 를 쓴다.
- 프로젝트 ID `rpa-test-f02e0`, RTDB `https://rpa-test-f02e0-default-rtdb.asia-southeast1.firebasedatabase.app`, Firestore 리전 `asia-northeast3`, 소유 계정 `hjjang96@gmail.com`.
- 명령 만료 기본 **600초**. 로그 꼬리 **80줄**. heartbeat **30초**. 화면의 "연결 끊김" 판정 **120초**.
- 회사 키(`cid`), PC 키(`pcId`) 는 영문 소문자·숫자·밑줄만 쓴다 (RTDB 키 제약: `. $ # [ ] /` 금지).
- 커밋은 각 Task 끝에서 한다. **push 는 사용자가 시킬 때만 한다.**

## 스펙과 다른 점 (의도한 것)

스펙 `2026-09-19-firebase-design.md` 를 그대로 따르되 네 군데가 다르다. 구현하다 스펙과 어긋나 보이면 여기를 먼저 본다.

| 스펙 | 이 계획 | 이유 |
|---|---|---|
| `live/{cid}/{pcId}/routine` 과 `/prepare` 로 나눠 올린다 | `live/{cid}/{pcId}` 에 `rpa_status.dashboard_snapshot()` 을 통째로 올린다 (`programs.routine`, `programs.prepare`) | 지금 화면이 이미 이 모양을 먹는다. 에이전트가 쪼개면 화면이 다시 합쳐야 한다 |
| 명령 상태에 `rejected` 가 있다 | `failed` 하나로 닫고 사유를 `result` 에 쓴다 | `rejected` 를 만드는 자리가 없다. 화면에는 어차피 사유 문장이 보인다 |
| 에이전트가 실행 이력을 Firestore 에 올린다 | 1차에서는 올리지 않는다. 규칙과 규칙 시험만 만들어 둔다 | 스펙 8절이 이력 화면을 2차로 잡았다. 올리기만 있고 보는 곳이 없으면 확인할 수 없다 |
| `launch` 는 인자가 없다 | `args.target` 으로 `routine` / `all` / `prepare` 를 고른다 (없으면 `routine`) | 지금 대시보드에도 '전체 실행' 버튼이 있다. 실행 모듈과는 다른 축이다 |

## 파일 구조

| 파일 | 책임 |
|---|---|
| `firebase/.firebaserc`, `firebase/firebase.json` | 프로젝트 배선, 에뮬레이터 포트, Hosting 루트 |
| `firebase/rules/database.rules.json` | RTDB 권한 (live / commands / settings / meta) |
| `firebase/rules/firestore.rules` | Firestore 권한 (runs / users) |
| `firebase/tests/package.json`, `firebase/tests/rules.test.js` | 규칙 시험 (에뮬레이터, Node 내장 test runner) |
| `firebase/admin/package.json`, `firebase/admin/setup.js` | 우리 PC 전용 등록 스크립트 (회사·PC·사용자·에이전트 + custom claim) |
| `firebase/agent/fb.py` | Firebase REST 클라이언트: 토큰 발급·갱신, RTDB PUT/PATCH/GET, SSE 구독 |
| `firebase/agent/secret.py` | 설정 파일 읽기 + DPAPI 로 비밀번호 보관/복호 |
| `firebase/agent/agent.py` | 진입점: 상태 올리기, heartbeat, 오프라인 큐, 명령 처리 |
| `firebase/agent/에이전트_시작.bat` | 관리자 권한 확인 후 에이전트 실행 |
| `firebase/tests/test_agent.py` | 에이전트 단위 시험 (가짜 클라이언트) |
| `firebase/web/index.html`, `firebase/web/app.js`, `firebase/web/firebase-config.js` | 화면 |

---

### Task 1: 프로젝트 배선과 에뮬레이터

에뮬레이터가 뜨지 않으면 뒤의 모든 규칙 시험이 불가능하다. 이 PC 의 Java 는 1.8 이라 Firebase 에뮬레이터(firebase-tools 15 는 Java 21 이상 필요)가 돌지 않는다. 먼저 고친다.

**Files:**
- Create: `firebase/.firebaserc`, `firebase/firebase.json`, `firebase/rules/database.rules.json`, `firebase/rules/firestore.rules`, `firebase/rules/firestore.indexes.json`

**Interfaces:**
- Consumes: 없음
- Produces: `firebase/` 에서 `firebase emulators:exec` 가 도는 상태. 뒤의 Task 들은 `--only database,firestore,auth` 로 이 설정을 쓴다.

- [ ] **Step 1: JDK 21 압축본을 개발 도구 폴더에 풀기**

설치 프로그램은 PATH 와 JAVA_HOME 을 17 로 바꿔 놓아 Java 8 을 쓰는 다른 프로그램을 깨뜨릴 수 있다. 압축본을 `.devtools` 에 풀고 **에뮬레이터를 띄우는 창에서만** PATH 앞에 붙인다. 시스템 기본 Java 는 8 그대로다.

```powershell
$zip = "$env:TEMP\jdk21.zip"
Invoke-WebRequest -Uri "https://aka.ms/download-jdk/microsoft-jdk-21-windows-x64.zip" -OutFile $zip
Expand-Archive -Path $zip -DestinationPath "$env:USERPROFILE\.devtools\jdk-21-tmp" -Force
Move-Item "$env:USERPROFILE\.devtools\jdk-21-tmp\jdk-21*" "$env:USERPROFILE\.devtools\jdk-21"
Remove-Item "$env:USERPROFILE\.devtools\jdk-21-tmp", $zip -Recurse -Force
```

- [ ] **Step 2: 에뮬레이터용 PATH 도우미와 버전 확인**

`firebase/emu_env.ps1` (에뮬레이터를 쓰는 모든 명령 앞에 `. .\emu_env.ps1` 로 읽는다):

```powershell
# 이 창에서만 JDK 21 을 앞세운다. 시스템 PATH 는 건드리지 않는다.
$env:JAVA_HOME = "$env:USERPROFILE\.devtools\jdk-21"
$env:Path = "$env:JAVA_HOME\bin;" + $env:Path
```

확인:

```powershell
cd D:\AX\RPAirebase; . .\emu_env.ps1; java -version
```

Expected: `openjdk version "21.` 로 시작. 새 창에서 그냥 `java -version` 을 치면 여전히 `1.8` 이어야 한다 (전역이 안 바뀐 것).

- [ ] **Step 3: 배선 파일 작성**

`firebase/.firebaserc`:

```json
{
  "projects": {
    "default": "rpa-test-f02e0"
  }
}
```

`firebase/firebase.json`:

```json
{
  "database": {
    "rules": "rules/database.rules.json"
  },
  "firestore": {
    "rules": "rules/firestore.rules",
    "indexes": "rules/firestore.indexes.json"
  },
  "hosting": {
    "public": "web",
    "ignore": ["firebase.json", "**/.*", "**/node_modules/**"]
  },
  "emulators": {
    "auth": { "port": 9099 },
    "database": { "port": 9000 },
    "firestore": { "port": 8080 },
    "hosting": { "port": 5000 },
    "ui": { "enabled": true, "port": 4000 },
    "singleProjectMode": true
  }
}
```

`firebase/rules/firestore.indexes.json`:

```json
{
  "indexes": [],
  "fieldOverrides": []
}
```

`firebase/rules/database.rules.json` (이번 Task 에서는 전부 거부. Task 2 에서 채운다):

```json
{
  "rules": {
    ".read": false,
    ".write": false
  }
}
```

`firebase/rules/firestore.rules` (이번 Task 에서는 전부 거부. Task 3 에서 채운다):

```
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    match /{document=**} {
      allow read, write: if false;
    }
  }
}
```

- [ ] **Step 4: 에뮬레이터가 뜨는지 확인**

`firebase/` 에서:

```powershell
firebase emulators:exec --only database,firestore,auth --project rpa-test-f02e0 "node -e \"console.log('에뮬레이터 정상')\""
```

Expected: `에뮬레이터 정상` 이 찍히고 종료 코드 0. `Could not start Database Emulator` 가 나오면 Java 문제다 (Step 2 로).

- [ ] **Step 5: 커밋**

```bash
git add .gitignore firebase/.firebaserc firebase/firebase.json firebase/rules firebase/emu_env.ps1
git commit -m "firebase: 프로젝트 배선과 에뮬레이터 설정"
```

---

### Task 2: RTDB 보안 규칙과 규칙 시험

**Files:**
- Create: `firebase/tests/package.json`, `firebase/tests/rules.test.js`
- Modify: `firebase/rules/database.rules.json` (Task 1 의 전부 거부를 실제 규칙으로)

**Interfaces:**
- Consumes: Task 1 의 `firebase.json` 에뮬레이터 포트 (database 9000)
- Produces: RTDB 경로 규약. 뒤의 Task 들이 쓰는 경로와 claim 이름을 여기서 고정한다.
  - claim: 사람 `{cid: string, role: "admin"|"viewer"}`, 총괄 `{role: "super"}` (cid 없음), 에이전트 `{cid, pcId, role: "agent"}`
  - `live/{cid}/{pcId}` — 에이전트만 쓰기, 같은 회사·super 읽기
  - `commands/{cid}/{pcId}/{cmdId}` — admin/super 가 만들고(`state: "queued"`), 그 PC 의 agent 만 갱신.
    상태는 `queued → running → done|failed`, 또는 `queued → expired`
  - `settings/{cid}/{pcId}` — admin/super 쓰기, 같은 회사·그 PC 의 agent 읽기
  - `meta/companies/{cid}` — super 만 쓰기

- [ ] **Step 1: 시험 꾸러미 만들기**

`firebase/tests/package.json`:

```json
{
  "name": "rpa-firebase-tests",
  "private": true,
  "type": "module",
  "scripts": {
    "test": "firebase emulators:exec --config ../firebase.json --only database,firestore --project rpa-test-rules \"node --test\""
  },
  "devDependencies": {
    "@firebase/rules-unit-testing": "^4.0.1",
    "firebase": "^11.0.0"
  }
}
```

`firebase/tests/` 에서 설치:

```powershell
npm install
```

- [ ] **Step 2: 실패하는 규칙 시험 쓰기**

`firebase/tests/rules.test.js`:

```js
// RTDB 보안 규칙 시험. 에뮬레이터가 떠 있어야 한다 (npm test 가 띄운다).
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import test, { before, after, beforeEach } from "node:test";
import {
  initializeTestEnvironment, assertFails, assertSucceeds,
} from "@firebase/rules-unit-testing";
import { ref, set, update, get, child } from "firebase/database";

const rulesPath = fileURLToPath(new URL("../rules/database.rules.json", import.meta.url));
let env;

before(async () => {
  env = await initializeTestEnvironment({
    projectId: "rpa-test-rules",
    database: {
      host: "127.0.0.1",
      port: 9000,
      rules: readFileSync(rulesPath, "utf8"),
    },
  });
});

after(async () => { await env.cleanup(); });
beforeEach(async () => { await env.clearDatabase(); });

// 등장인물
const asAdminA = () => env.authenticatedContext("u_admin_a", { cid: "ca", role: "admin" }).database();
const asViewerA = () => env.authenticatedContext("u_view_a", { cid: "ca", role: "viewer" }).database();
const asAdminB = () => env.authenticatedContext("u_admin_b", { cid: "cb", role: "admin" }).database();
const asSuper = () => env.authenticatedContext("u_super", { role: "super" }).database();
const asAgentA1 = () => env.authenticatedContext("u_agent_a1", { cid: "ca", pcId: "pc1", role: "agent" }).database();
const asAgentA2 = () => env.authenticatedContext("u_agent_a2", { cid: "ca", pcId: "pc2", role: "agent" }).database();
const asAnon = () => env.unauthenticatedContext().database();

const cmd = (over = {}) => ({
  type: "launch",
  args: null,
  by: "u_admin_a",
  created_at: 1000,
  expires_at: 1600,
  state: "queued",
  ...over,
});

test("live: 에이전트는 자기 PC 에 쓸 수 있다", async () => {
  await assertSucceeds(set(ref(asAgentA1(), "live/ca/pc1"), { host: "PC1", programs: {} }));
});

test("live: 에이전트가 남의 PC 에 쓰면 거부", async () => {
  await assertFails(set(ref(asAgentA2(), "live/ca/pc1"), { host: "위조" }));
});

test("live: 관리자는 쓸 수 없다 (읽기 전용)", async () => {
  await assertFails(set(ref(asAdminA(), "live/ca/pc1"), { host: "위조" }));
});

test("live: 같은 회사는 읽고, 다른 회사는 거부, super 는 읽는다", async () => {
  await env.withSecurityRulesDisabled(async (c) => {
    await set(ref(c.database(), "live/ca/pc1"), { host: "PC1" });
  });
  await assertSucceeds(get(ref(asViewerA(), "live/ca/pc1")));
  await assertFails(get(ref(asAdminB(), "live/ca/pc1")));
  await assertSucceeds(get(ref(asSuper(), "live/ca/pc1")));
});

test("live: 로그인하지 않으면 읽기 거부", async () => {
  await assertFails(get(ref(asAnon(), "live/ca/pc1")));
});

test("commands: 관리자는 queued 명령을 만들 수 있다", async () => {
  await assertSucceeds(set(ref(asAdminA(), "commands/ca/pc1/c1"), cmd()));
});

test("commands: 열람자는 명령을 만들 수 없다", async () => {
  await assertFails(set(ref(asViewerA(), "commands/ca/pc1/c1"), cmd({ by: "u_view_a" })));
});

test("commands: 다른 회사 관리자는 거부", async () => {
  await assertFails(set(ref(asAdminB(), "commands/ca/pc1/c1"), cmd({ by: "u_admin_b" })));
});

test("commands: by 를 남의 uid 로 위조하면 거부", async () => {
  await assertFails(set(ref(asAdminA(), "commands/ca/pc1/c1"), cmd({ by: "u_super" })));
});

test("commands: 만들 때 state 가 queued 가 아니면 거부", async () => {
  await assertFails(set(ref(asAdminA(), "commands/ca/pc1/c1"), cmd({ state: "done" })));
});

test("commands: 모르는 type 은 거부", async () => {
  await assertFails(set(ref(asAdminA(), "commands/ca/pc1/c1"), cmd({ type: "rm_rf" })));
});

test("commands: 관리자가 state 를 직접 done 으로 바꾸면 거부", async () => {
  await assertSucceeds(set(ref(asAdminA(), "commands/ca/pc1/c1"), cmd()));
  await assertFails(update(ref(asAdminA(), "commands/ca/pc1/c1"), { state: "done" }));
});

test("commands: 그 PC 의 에이전트만 state 를 옮길 수 있다", async () => {
  await assertSucceeds(set(ref(asAdminA(), "commands/ca/pc1/c1"), cmd()));
  await assertFails(update(ref(asAgentA2(), "commands/ca/pc1/c1"), { state: "running" }));
  await assertSucceeds(update(ref(asAgentA1(), "commands/ca/pc1/c1"), { state: "running", started_at: 1100 }));
  await assertSucceeds(update(ref(asAgentA1(), "commands/ca/pc1/c1"), { state: "done", ended_at: 1200, result: "ok" }));
});

test("commands: 에이전트가 type 을 바꾸면 거부", async () => {
  await assertSucceeds(set(ref(asAdminA(), "commands/ca/pc1/c1"), cmd()));
  await assertFails(update(ref(asAgentA1(), "commands/ca/pc1/c1"), { type: "stop_erpia" }));
});

test("settings: 관리자는 쓰고, 열람자는 못 쓰고, 그 PC 의 에이전트는 읽는다", async () => {
  await assertSucceeds(set(ref(asAdminA(), "settings/ca/pc1"), {
    modules: { Login: true, Sales: false, Hold: true, Logistics: true, Output: true },
    updated_by: "u_admin_a", updated_at: 1000,
  }));
  await assertFails(set(ref(asViewerA(), "settings/ca/pc1"), { modules: { Login: false } }));
  await assertSucceeds(get(ref(asAgentA1(), "settings/ca/pc1")));
  await assertFails(get(ref(asAdminB(), "settings/ca/pc1")));
});

test("meta: super 만 쓴다", async () => {
  await assertFails(set(ref(asAdminA(), "meta/companies/ca"), { name: "위조" }));
  await assertSucceeds(set(ref(asSuper(), "meta/companies/ca"), { name: "테스트 회사" }));
});
```

- [ ] **Step 3: 시험이 실패하는지 확인**

`firebase/tests/` 에서:

```powershell
npm test
```

Expected: 전부 거부하는 규칙이라 `assertSucceeds` 가 기대되는 시험들이 FAIL 한다. `live: 에이전트는 자기 PC 에 쓸 수 있다` 가 실패 목록에 있으면 맞게 돌고 있는 것이다.

- [ ] **Step 4: 규칙 쓰기**

`firebase/rules/database.rules.json` 전체를 아래로 바꾼다:

```json
{
  "rules": {
    ".read": false,
    ".write": false,

    "live": {
      "$cid": {
        "$pcId": {
          ".read": "auth != null && (auth.token.cid === $cid || auth.token.role === 'super')",
          ".write": "auth != null && auth.token.role === 'agent' && auth.token.cid === $cid && auth.token.pcId === $pcId"
        }
      }
    },

    "settings": {
      "$cid": {
        "$pcId": {
          ".read": "auth != null && (auth.token.cid === $cid || auth.token.role === 'super')",
          ".write": "auth != null && ((auth.token.role === 'admin' && auth.token.cid === $cid) || auth.token.role === 'super')"
        }
      }
    },

    "meta": {
      "companies": {
        "$cid": {
          ".read": "auth != null && (auth.token.cid === $cid || auth.token.role === 'super')",
          ".write": "auth != null && auth.token.role === 'super'"
        }
      }
    },

    "commands": {
      "$cid": {
        "$pcId": {
          ".read": "auth != null && (auth.token.cid === $cid || auth.token.role === 'super')",
          ".indexOn": ["state"],

          "$cmdId": {
            ".write": "auth != null && ((!data.exists() && newData.exists() && ((auth.token.role === 'admin' && auth.token.cid === $cid) || auth.token.role === 'super')) || (data.exists() && auth.token.role === 'agent' && auth.token.cid === $cid && auth.token.pcId === $pcId))",
            ".validate": "newData.hasChildren(['type', 'by', 'created_at', 'expires_at', 'state'])",

            "type": {
              ".validate": "newData.isString() && (newData.val() === 'launch' || newData.val() === 'stop_erpia' || newData.val() === 'set_modules' || newData.val() === 'set_schedule') && (!data.exists() || data.val() === newData.val())"
            },
            "by": {
              ".validate": "newData.isString() && (data.exists() ? data.val() === newData.val() : newData.val() === auth.uid)"
            },
            "created_at": {
              ".validate": "newData.isNumber() && (!data.exists() || data.val() === newData.val())"
            },
            "expires_at": {
              ".validate": "newData.isNumber() && (!data.exists() || data.val() === newData.val())"
            },
            "state": {
              ".validate": "newData.isString() && (!data.exists() ? newData.val() === 'queued' : (auth.token.role === 'agent' && (newData.val() === 'running' || newData.val() === 'done' || newData.val() === 'failed' || newData.val() === 'expired')))"
            },
            "args": { ".validate": "!data.exists() || data.val() === newData.val()" },
            "result": { ".validate": "newData.isString() && auth.token.role === 'agent'" },
            "started_at": { ".validate": "newData.isNumber() && auth.token.role === 'agent'" },
            "ended_at": { ".validate": "newData.isNumber() && auth.token.role === 'agent'" },
            "$other": { ".validate": false }
          }
        }
      }
    }
  }
}
```

`$other: false` 는 모르는 필드를 막는다. `args` 는 `set_modules` 가 쓰는 객체라 통째로 값 비교만 한다 (만든 뒤 못 바꾼다).

- [ ] **Step 5: 시험이 통과하는지 확인**

```powershell
npm test
```

Expected: 16개 시험 전부 PASS.

- [ ] **Step 6: 커밋**

```bash
git add firebase/rules/database.rules.json firebase/tests/package.json firebase/tests/package-lock.json firebase/tests/rules.test.js
git commit -m "firebase: RTDB 보안 규칙과 규칙 시험 16건"
```

`firebase/tests/node_modules/` 가 잡히면 `.gitignore` 에 `firebase/tests/node_modules/` 와 `firebase/admin/node_modules/` 를 먼저 넣는다.

---

### Task 3: Firestore 보안 규칙과 규칙 시험

1차에서 Firestore 에 실제로 쓰지는 않는다 (이력 올리기는 2차). 하지만 잠금 모드로 열어 둔 채 두면 2차에서 잊는다. 규칙과 시험을 지금 못 박는다.

**Files:**
- Modify: `firebase/rules/firestore.rules`, `firebase/tests/rules.test.js` (절 추가)

**Interfaces:**
- Consumes: Task 2 의 claim 규약
- Produces: `runs/{cid}/items/{runId}` (에이전트만 생성, 수정·삭제 불가), `users/{uid}` (본인·super 읽기, 쓰기는 Admin SDK 만)

- [ ] **Step 1: 실패하는 시험 추가**

`firebase/tests/rules.test.js` 맨 아래에 붙인다. 맨 위 import 줄에 Firestore 함수를 더한다:

```js
import { doc, setDoc, getDoc, updateDoc, deleteDoc } from "firebase/firestore";
```

그리고 `initializeTestEnvironment` 의 인자에 `firestore` 를 더한다 (`database` 항목은 그대로 두고 형제로 추가):

```js
    firestore: {
      host: "127.0.0.1",
      port: 8080,
      rules: readFileSync(fileURLToPath(new URL("../rules/firestore.rules", import.meta.url)), "utf8"),
    },
```

`beforeEach` 도 Firestore 를 비우게 고친다:

```js
beforeEach(async () => { await env.clearDatabase(); await env.clearFirestore(); });
```

시험 본문:

```js
const fsAdminA = () => env.authenticatedContext("u_admin_a", { cid: "ca", role: "admin" }).firestore();
const fsAdminB = () => env.authenticatedContext("u_admin_b", { cid: "cb", role: "admin" }).firestore();
const fsSuper = () => env.authenticatedContext("u_super", { role: "super" }).firestore();
const fsAgentA1 = () => env.authenticatedContext("u_agent_a1", { cid: "ca", pcId: "pc1", role: "agent" }).firestore();
const fsAgentA2 = () => env.authenticatedContext("u_agent_a2", { cid: "ca", pcId: "pc2", role: "agent" }).firestore();

const run = (over = {}) => ({
  cid: "ca", pcId: "pc1", run_id: "r1", program: "routine",
  state: "success", started_at: "2026-09-21T09:00:00", duration_sec: 120,
  payload: "{}", ...over,
});

test("runs: 에이전트는 자기 PC 의 이력을 만들 수 있다", async () => {
  await assertSucceeds(setDoc(doc(fsAgentA1(), "runs/ca/items/r1"), run()));
});

test("runs: 에이전트가 남의 PC 이름으로 만들면 거부", async () => {
  await assertFails(setDoc(doc(fsAgentA2(), "runs/ca/items/r1"), run()));
});

test("runs: 관리자는 만들 수 없다", async () => {
  await assertFails(setDoc(doc(fsAdminA(), "runs/ca/items/r1"), run()));
});

test("runs: 같은 회사와 super 는 읽고 다른 회사는 거부", async () => {
  await env.withSecurityRulesDisabled(async (c) => {
    await setDoc(doc(c.firestore(), "runs/ca/items/r1"), run());
  });
  await assertSucceeds(getDoc(doc(fsAdminA(), "runs/ca/items/r1")));
  await assertSucceeds(getDoc(doc(fsSuper(), "runs/ca/items/r1")));
  await assertFails(getDoc(doc(fsAdminB(), "runs/ca/items/r1")));
});

test("runs: 만든 이력은 고치거나 지울 수 없다", async () => {
  await assertSucceeds(setDoc(doc(fsAgentA1(), "runs/ca/items/r1"), run()));
  await assertFails(updateDoc(doc(fsAgentA1(), "runs/ca/items/r1"), { state: "조작" }));
  await assertFails(deleteDoc(doc(fsAgentA1(), "runs/ca/items/r1")));
  await assertFails(deleteDoc(doc(fsSuper(), "runs/ca/items/r1")));
});

test("users: 본인과 super 만 읽고 아무도 못 쓴다", async () => {
  await env.withSecurityRulesDisabled(async (c) => {
    await setDoc(doc(c.firestore(), "users/u_admin_a"), { cid: "ca", role: "admin", name: "가나" });
  });
  await assertSucceeds(getDoc(doc(fsAdminA(), "users/u_admin_a")));
  await assertSucceeds(getDoc(doc(fsSuper(), "users/u_admin_a")));
  await assertFails(getDoc(doc(fsAdminB(), "users/u_admin_a")));
  await assertFails(setDoc(doc(fsAdminA(), "users/u_admin_a"), { role: "super" }));
});
```

- [ ] **Step 2: 시험이 실패하는지 확인**

```powershell
npm test
```

Expected: 새로 넣은 6건 중 `assertSucceeds` 쪽이 FAIL (지금 규칙은 전부 거부).

- [ ] **Step 3: 규칙 쓰기**

`firebase/rules/firestore.rules` 전체:

```
rules_version = '2';

service cloud.firestore {
  match /databases/{database}/documents {

    function claims() { return request.auth.token; }
    function signedIn() { return request.auth != null; }
    function sameCompany(cid) { return signedIn() && (claims().cid == cid || claims().role == 'super'); }

    // 실행 이력. 에이전트가 만들고 아무도 고치지 않는다.
    match /runs/{cid}/items/{runId} {
      allow read: if sameCompany(cid);
      allow create: if signedIn()
                    && claims().role == 'agent'
                    && claims().cid == cid
                    && request.resource.data.pcId == claims().pcId
                    && request.resource.data.cid == cid;
      allow update, delete: if false;
    }

    // 사용자 표시용. 권한 근거는 custom claim 이고 이 문서가 아니다.
    // 쓰기는 Admin SDK(관리 스크립트)만 - Admin SDK 는 규칙을 우회한다.
    match /users/{uid} {
      allow read: if signedIn() && (request.auth.uid == uid || claims().role == 'super');
      allow write: if false;
    }

    match /{document=**} {
      allow read, write: if false;
    }
  }
}
```

- [ ] **Step 4: 시험이 통과하는지 확인**

```powershell
npm test
```

Expected: 22건 전부 PASS (RTDB 16 + Firestore 6).

- [ ] **Step 5: 커밋**

```bash
git add firebase/rules/firestore.rules firebase/tests/rules.test.js
git commit -m "firebase: Firestore 보안 규칙과 규칙 시험 6건"
```

---

### Task 4: 관리 스크립트 (회사·PC·사용자·에이전트 등록)

계정을 손으로 만들면 claim 을 빠뜨린다. 등록은 스크립트 하나로만 한다. 이 스크립트는 **우리 PC 에서만** 돈다 (서비스 계정 키가 필요하다).

**Files:**
- Create: `firebase/admin/package.json`, `firebase/admin/setup.js`, `firebase/admin/README.md`

**Interfaces:**
- Consumes: `firebase/admin/serviceAccountKey.json`, Task 2 의 claim 규약
- Produces: 실기용 계정. 이 계획의 실기(Task 9)는 아래 이름을 쓴다.
  - 회사 `c_demo` ("시연 회사"), PC `pc_office` ("사무실 PC")
  - 총괄 `super@rpa-test-f02e0.firebaseapp.com` (role super)
  - 회사 관리자 `admin@c-demo.rpa-test-f02e0.firebaseapp.com` (cid c_demo, role admin)
  - 에이전트 `agent-pc-office@c-demo.rpa-test-f02e0.firebaseapp.com` (cid c_demo, pcId pc_office, role agent)

- [ ] **Step 1: 꾸러미와 의존성**

`firebase/admin/package.json`:

```json
{
  "name": "rpa-firebase-admin",
  "private": true,
  "type": "module",
  "devDependencies": {
    "firebase-admin": "^13.0.0"
  }
}
```

`firebase/admin/` 에서:

```powershell
npm install
```

- [ ] **Step 2: 등록 스크립트 쓰기**

`firebase/admin/setup.js`:

```js
// 회사·PC·사용자·에이전트를 등록하고 custom claim 을 심는다. 우리 PC 에서만 돈다.
//
//   node setup.js company  <cid> <회사 이름>
//   node setup.js pc       <cid> <pcId> <PC 이름>
//   node setup.js user     <이메일> <초기 비밀번호> <cid|-> <super|admin|viewer> <이름>
//   node setup.js agent    <이메일> <초기 비밀번호> <cid> <pcId>
//   node setup.js show     <이메일>
//
// 비밀번호는 화면에 다시 찍지 않는다. 초기 비밀번호는 발급 직후 사용자가 바꾼다.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { initializeApp, cert } from "firebase-admin/app";
import { getAuth } from "firebase-admin/auth";
import { getDatabase } from "firebase-admin/database";
import { getFirestore } from "firebase-admin/firestore";

const KEY = fileURLToPath(new URL("./serviceAccountKey.json", import.meta.url));
const DB_URL = "https://rpa-test-f02e0-default-rtdb.asia-southeast1.firebasedatabase.app";

const app = initializeApp({
  credential: cert(JSON.parse(readFileSync(KEY, "utf8"))),
  databaseURL: DB_URL,
});
const auth = getAuth(app);
const rtdb = getDatabase(app);
const store = getFirestore(app);

const KEY_RE = /^[a-z0-9_]+$/;

function checkKey(name, value) {
  if (!KEY_RE.test(value)) throw new Error(`${name} 는 영문 소문자·숫자·밑줄만 쓴다: ${value}`);
}

async function upsertUser(email, password) {
  try {
    return await auth.getUserByEmail(email);
  } catch (e) {
    if (e.code !== "auth/user-not-found") throw e;
    if (!password || password.length < 8) throw new Error("초기 비밀번호는 8자 이상이어야 한다");
    return await auth.createUser({ email, password, emailVerified: false });
  }
}

const [, , cmdName, ...rest] = process.argv;

if (cmdName === "company") {
  const [cid, ...nameParts] = rest;
  checkKey("cid", cid);
  await rtdb.ref(`meta/companies/${cid}`).update({ name: nameParts.join(" ") });
  console.log(`회사 등록: ${cid}`);

} else if (cmdName === "pc") {
  const [cid, pcId, ...labelParts] = rest;
  checkKey("cid", cid); checkKey("pcId", pcId);
  await rtdb.ref(`meta/companies/${cid}/pcs/${pcId}`).update({ label: labelParts.join(" ") });
  console.log(`PC 등록: ${cid}/${pcId}`);

} else if (cmdName === "user") {
  const [email, password, cidArg, role, ...nameParts] = rest;
  if (!["super", "admin", "viewer"].includes(role)) throw new Error("role 은 super/admin/viewer");
  const cid = cidArg === "-" ? null : cidArg;
  if (cid) checkKey("cid", cid);
  if (role !== "super" && !cid) throw new Error("super 가 아니면 cid 가 있어야 한다");
  const user = await upsertUser(email, password);
  await auth.setCustomUserClaims(user.uid, cid ? { cid, role } : { role });
  await store.doc(`users/${user.uid}`).set({
    cid: cid ?? null, role, name: nameParts.join(" ") || email, must_change_password: true,
  });
  console.log(`사용자 등록: ${email}  uid=${user.uid}  role=${role}  cid=${cid ?? "-"}`);

} else if (cmdName === "agent") {
  const [email, password, cid, pcId] = rest;
  checkKey("cid", cid); checkKey("pcId", pcId);
  const user = await upsertUser(email, password);
  await auth.setCustomUserClaims(user.uid, { cid, pcId, role: "agent" });
  console.log(`에이전트 등록: ${email}  uid=${user.uid}  cid=${cid}  pcId=${pcId}`);

} else if (cmdName === "show") {
  const user = await auth.getUserByEmail(rest[0]);
  console.log({ uid: user.uid, email: user.email, claims: user.customClaims ?? {} });

} else {
  console.log(readFileSync(fileURLToPath(import.meta.url), "utf8").split("\n").slice(1, 10).join("\n"));
  process.exit(1);
}

process.exit(0);
```

- [ ] **Step 3: 설명 파일**

`firebase/admin/README.md`:

```markdown
# 관리 스크립트

우리 PC 에서만 돈다. `serviceAccountKey.json` 이 있어야 하고, 그 파일은 **고객 PC 에 절대 복사하지 않는다**.
서비스 계정 키는 보안 규칙을 우회하는 만능 열쇠다. 유출되면 모든 회사 데이터가 열린다.

```
node setup.js company c_demo 시연 회사
node setup.js pc      c_demo pc_office 사무실 PC
node setup.js user    super@rpa-test-f02e0.firebaseapp.com <비밀번호> - super 총괄
node setup.js user    admin@c-demo.rpa-test-f02e0.firebaseapp.com <비밀번호> c_demo admin 시연 회사 관리자
node setup.js agent   agent-pc-office@c-demo.rpa-test-f02e0.firebaseapp.com <비밀번호> c_demo pc_office
node setup.js show    admin@c-demo.rpa-test-f02e0.firebaseapp.com
```

비밀번호는 명령 이력에 남는다. 등록한 뒤 PowerShell 기록(`Clear-History`)을 지우고, 사용자에게는 첫 로그인에서 바꾸게 한다.
```

- [ ] **Step 4: 실제로 등록하고 claim 확인**

`firebase/admin/` 에서 README 의 5줄을 실행한다. 비밀번호는 사용자가 정한 값을 쓴다 (계획서에 적지 않는다).

```powershell
node setup.js show agent-pc-office@c-demo.rpa-test-f02e0.firebaseapp.com
```

Expected: `claims: { cid: 'c_demo', pcId: 'pc_office', role: 'agent' }`

- [ ] **Step 5: 커밋**

```bash
git add firebase/admin/package.json firebase/admin/package-lock.json firebase/admin/setup.js firebase/admin/README.md
git commit -m "firebase: 회사·PC·계정 등록 스크립트"
```

`git status` 로 `serviceAccountKey.json` 이 안 잡히는지 반드시 확인한다.

---

### Task 5: 에이전트 - 설정과 비밀번호 보관 (DPAPI)

**Files:**
- Create: `firebase/agent/secret.py`, `firebase/tests/test_agent.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `secret.protect(text: str) -> str` (base64), `secret.unprotect(blob: str) -> str`
  - `secret.load_config(path=None) -> dict` — `{project_id, api_key, database_url, cid, pc_id, email, password}`. `password` 는 복호된 평문이며 **어디에도 기록하지 않는다**.
  - `secret.write_config(path, cfg_without_password, password)` — 비밀번호를 DPAPI 로 감싸 `password_dpapi` 로 저장
  - `secret.CONFIG_PATH` — `firebase/agent/agent_config.json`

- [ ] **Step 1: 실패하는 시험 쓰기**

`firebase/tests/test_agent.py`:

```python
"""에이전트 단위 시험. Firebase 없이 돈다.

실행: python tests/test_agent.py   (D:\\AX\\RPA\\firebase 에서)
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "agent"))

FAIL = []
COUNT = 0


def check(ok, label):
    global COUNT
    COUNT += 1
    if ok:
        print(f"  통과  {label}")
    else:
        FAIL.append(label)
        print(f"  실패  {label}")


print("1절 설정과 비밀번호 보관")
import secret

blob = secret.protect("비밀번호-시험-1234")
check(isinstance(blob, str) and "비밀번호" not in blob, "감싼 값에 평문이 보이지 않는다")
check(secret.unprotect(blob) == "비밀번호-시험-1234", "감쌌다가 풀면 원래 값")
check(secret.protect("같은값") != secret.protect("같은값"), "같은 값이라도 결과가 다르다")

with tempfile.TemporaryDirectory() as d:
    p = os.path.join(d, "agent_config.json")
    secret.write_config(p, {
        "project_id": "proj", "api_key": "key", "database_url": "https://db",
        "cid": "c_demo", "pc_id": "pc_office", "email": "a@b.c",
    }, "비밀번호-시험-1234")
    raw = open(p, encoding="utf-8").read()
    check("비밀번호-시험-1234" not in raw, "설정 파일에 평문 비밀번호가 없다")
    check("password_dpapi" in json.loads(raw), "password_dpapi 로 저장한다")
    cfg = secret.load_config(p)
    check(cfg["password"] == "비밀번호-시험-1234", "읽으면 비밀번호가 풀린다")
    check(cfg["cid"] == "c_demo" and cfg["pc_id"] == "pc_office", "나머지 값도 읽는다")

    json.dump({"cid": "c_demo"}, open(p, "w", encoding="utf-8"))
    try:
        secret.load_config(p)
        check(False, "빠진 항목이 있으면 막는다")
    except ValueError as e:
        check("api_key" in str(e), "빠진 항목이 있으면 막는다")

print(f"\n{COUNT - len(FAIL)}/{COUNT} 통과")
if FAIL:
    print("실패:", ", ".join(FAIL))
    sys.exit(1)
```

- [ ] **Step 2: 시험이 실패하는지 확인**

`firebase/` 에서:

```powershell
python tests/test_agent.py
```

Expected: `ModuleNotFoundError: No module named 'secret'`

- [ ] **Step 3: 구현**

`firebase/agent/secret.py`:

```python
"""에이전트 설정과 비밀번호 보관.

비밀번호는 윈도우 DPAPI(현재 사용자 범위)로 감싸 설정 파일에 넣는다.
파일을 그대로 복사해 가도 다른 사용자 계정에서는 풀 수 없다.
ERPia 자격증명(ERPIA_AI.txt)과 같은 성격이므로 화면·기록·응답에 절대 싣지 않는다.
"""
import base64
import ctypes
import json
import os
from ctypes import wintypes

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_config.json")
REQUIRED = ("project_id", "api_key", "database_url", "cid", "pc_id", "email")


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> _Blob:
    buf = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def _take(blob: _Blob) -> bytes:
    out = ctypes.string_at(blob.pbData, blob.cbData)
    ctypes.windll.kernel32.LocalFree(blob.pbData)
    return out


def protect(text: str) -> str:
    """평문을 DPAPI 로 감싸 base64 문자열로 돌려준다."""
    out = _Blob()
    src = _blob(text.encode("utf-8"))
    if not ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(src), "rpa-agent", None, None, None, 0, ctypes.byref(out)):
        raise OSError("비밀번호를 감싸지 못했습니다 (CryptProtectData)")
    return base64.b64encode(_take(out)).decode("ascii")


def unprotect(blob: str) -> str:
    """감싼 값을 평문으로 되돌린다."""
    out = _Blob()
    src = _blob(base64.b64decode(blob))
    if not ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(src), None, None, None, None, 0, ctypes.byref(out)):
        raise OSError("비밀번호를 풀지 못했습니다. 이 PC·이 사용자 계정에서 만든 설정인지 확인하세요.")
    return _take(out).decode("utf-8")


def write_config(path, values, password):
    """설정을 쓴다. password 는 감싸서 password_dpapi 로만 들어간다."""
    data = {k: values[k] for k in REQUIRED}
    data["password_dpapi"] = protect(password)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_config(path=None):
    """설정을 읽고 비밀번호를 푼 dict 를 돌려준다."""
    path = path or CONFIG_PATH
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    missing = [k for k in REQUIRED if not data.get(k)]
    if missing:
        raise ValueError(f"설정에 빠진 항목: {', '.join(missing)}  ({path})")
    if not data.get("password_dpapi"):
        raise ValueError(f"설정에 password_dpapi 가 없습니다 ({path})")
    out = {k: data[k] for k in REQUIRED}
    out["password"] = unprotect(data["password_dpapi"])
    return out
```

- [ ] **Step 4: 시험이 통과하는지 확인**

```powershell
python tests/test_agent.py
```

Expected: `8/8 통과`

- [ ] **Step 5: 커밋**

```bash
git add firebase/agent/secret.py firebase/tests/test_agent.py
git commit -m "firebase: 에이전트 설정과 DPAPI 비밀번호 보관"
```

---

### Task 6: 에이전트 - Firebase REST 클라이언트

**Files:**
- Create: `firebase/agent/fb.py`
- Modify: `firebase/tests/test_agent.py` (2절 추가)

**Interfaces:**
- Consumes: `secret.load_config()` 의 dict
- Produces: `fb.Client(cfg, opener=None)`
  - `client.token()` → 유효한 ID 토큰 문자열 (만료 60초 전 자동 갱신)
  - `client.put(path, value)` / `client.patch(path, value)` / `client.get(path)` — RTDB, `path` 는 `"live/c_demo/pc_office"` 처럼 `.json` 없이
  - `client.stream(path, params=None)` — SSE 제너레이터, `(event, data)` 를 내놓는다. `data` 는 `{"path": ..., "data": ...}` 또는 None
  - `fb.HttpError(status, body)` — 4xx/5xx 일 때

- [ ] **Step 1: 실패하는 시험 추가**

`firebase/tests/test_agent.py` 의 마지막 요약 출력 **앞에** 넣는다:

```python
print("\n2절 Firebase REST 클라이언트")
import io
import fb

CFG = {"project_id": "proj", "api_key": "KEY", "database_url": "https://db.example.com",
       "cid": "c_demo", "pc_id": "pc_office", "email": "a@b.c", "password": "pw"}


class FakeHTTP:
    """urlopen 을 대신한다. 부른 내역을 남기고 미리 정한 응답을 돌려준다."""

    def __init__(self):
        self.calls = []
        self.replies = []
        self.now = 1000.0

    def add(self, payload, status=200):
        self.replies.append((status, json.dumps(payload).encode("utf-8")))

    def __call__(self, req, timeout=None):
        body = req.data.decode("utf-8") if req.data else None
        self.calls.append((req.get_method(), req.full_url, body, dict(req.headers)))
        status, data = self.replies.pop(0)
        if status >= 400:
            import urllib.error
            raise urllib.error.HTTPError(req.full_url, status, "err", {}, io.BytesIO(data))
        return io.BytesIO(data)


http = FakeHTTP()
http.add({"idToken": "T1", "refreshToken": "R1", "expiresIn": "3600"})
c = fb.Client(CFG, opener=http, clock=lambda: http.now)
check(c.token() == "T1", "비밀번호로 첫 토큰을 받는다")
check("signInWithPassword?key=KEY" in http.calls[0][1], "로그인 주소에 api_key 를 쓴다")
check("pw" in http.calls[0][2], "로그인 요청에만 비밀번호가 들어간다")

check(c.token() == "T1" and len(http.calls) == 1, "만료 전에는 다시 받지 않는다")

http.now = 1000.0 + 3600 - 30      # 만료 30초 전
http.add({"id_token": "T2", "refresh_token": "R2", "expires_in": "3600"})
check(c.token() == "T2", "만료가 가까우면 갱신한다")
check("securetoken" in http.calls[1][1] and "R1" in http.calls[1][2], "갱신은 refresh token 으로")
check("pw" not in http.calls[1][2], "갱신 요청에는 비밀번호가 없다")

http.add({"ok": True})
c.put("live/c_demo/pc_office", {"host": "PC1"})
method, url, body, _ = http.calls[-1]
check(method == "PUT" and url.startswith("https://db.example.com/live/c_demo/pc_office.json"), "PUT 주소")
check("auth=T2" in url, "요청에 토큰을 싣는다")
check(json.loads(body) == {"host": "PC1"}, "보낸 몸통")

http.add({"ok": True})
c.patch("commands/c_demo/pc_office/x", {"state": "running"})
check(http.calls[-1][0] == "PATCH", "PATCH 로 일부만 고친다")

http.add({"error": "Permission denied"}, status=401)
http.add({"id_token": "T3", "refresh_token": "R3", "expires_in": "3600"})
http.add({"ok": True})
c.put("live/c_demo/pc_office", {"host": "PC1"})
check(c.token() == "T3", "401 이면 토큰을 새로 받고 한 번 더 시도한다")

http.add({"error": "Permission denied"}, status=403)
try:
    c.put("live/other/pc", {"x": 1})
    check(False, "거부는 HttpError 로 올린다")
except fb.HttpError as e:
    check(e.status == 403, "거부는 HttpError 로 올린다")

check(fb.parse_sse(["event: put", 'data: {"path":"/","data":{"a":1}}', ""]) ==
      [("put", {"path": "/", "data": {"a": 1}})], "SSE 한 덩이를 읽는다")
check(fb.parse_sse(["event: keep-alive", "data: null", ""]) == [("keep-alive", None)], "keep-alive 를 읽는다")
```

- [ ] **Step 2: 시험이 실패하는지 확인**

```powershell
python tests/test_agent.py
```

Expected: `ModuleNotFoundError: No module named 'fb'`

- [ ] **Step 3: 구현**

`firebase/agent/fb.py`:

```python
"""Firebase REST 클라이언트. 표준 라이브러리만 쓴다 (에이전트를 가볍게 두려고).

- 로그인: Identity Toolkit signInWithPassword
- 갱신: Secure Token refresh_token
- RTDB: <database_url>/<path>.json?auth=<idToken>
- 구독: 같은 주소에 Accept: text/event-stream (SSE)

비밀번호는 첫 로그인 요청에만 실린다. 기록에는 어떤 경우에도 남기지 않는다.
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

SIGNIN_URL = "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key="
REFRESH_URL = "https://securetoken.googleapis.com/v1/token?key="
RENEW_BEFORE_SEC = 60


class HttpError(Exception):
    def __init__(self, status, body):
        super().__init__(f"HTTP {status}")
        self.status = status
        self.body = body


def parse_sse(lines):
    """SSE 줄 목록을 [(event, data)] 로 바꾼다. 빈 줄이 한 덩이의 끝이다."""
    out, event, data = [], None, None
    for line in lines:
        line = line.rstrip("\r")
        if line == "":
            if event is not None:
                out.append((event, data))
            event, data = None, None
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            raw = line[5:].strip()
            try:
                data = json.loads(raw)
            except ValueError:
                data = None
    return out


class Client:
    def __init__(self, cfg, opener=None, clock=time.time):
        self._cfg = cfg
        self._open = opener or urllib.request.urlopen
        self._now = clock
        self._id_token = None
        self._refresh_token = None
        self._expires_at = 0.0

    # --- 토큰 ---------------------------------------------------------
    def _post_json(self, url, payload):
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        return json.loads(self._open(req, timeout=20).read().decode("utf-8"))

    def _sign_in(self):
        r = self._post_json(SIGNIN_URL + self._cfg["api_key"], {
            "email": self._cfg["email"], "password": self._cfg["password"],
            "returnSecureToken": True})
        self._id_token = r["idToken"]
        self._refresh_token = r["refreshToken"]
        self._expires_at = self._now() + float(r.get("expiresIn", 3600))

    def _refresh(self):
        r = self._post_json(REFRESH_URL + self._cfg["api_key"], {
            "grant_type": "refresh_token", "refresh_token": self._refresh_token})
        self._id_token = r["id_token"]
        self._refresh_token = r["refresh_token"]
        self._expires_at = self._now() + float(r.get("expires_in", 3600))

    def token(self):
        if self._id_token and self._now() < self._expires_at - RENEW_BEFORE_SEC:
            return self._id_token
        if self._refresh_token:
            try:
                self._refresh()
                return self._id_token
            except Exception:
                pass          # 갱신이 막히면 처음부터 다시 로그인한다
        self._sign_in()
        return self._id_token

    def renew(self):
        """다음 요청이 토큰을 새로 받게 한다 (401 을 만났을 때)."""
        self._expires_at = 0.0

    # --- RTDB ---------------------------------------------------------
    def _url(self, path, params=None):
        q = dict(params or {})
        q["auth"] = self.token()
        return f"{self._cfg['database_url'].rstrip('/')}/{path.strip('/')}.json?{urllib.parse.urlencode(q)}"

    def _send(self, method, path, value, params=None, retried=False):
        body = None if value is None else json.dumps(value, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self._url(path, params), data=body,
                                     headers={"Content-Type": "application/json"}, method=method)
        try:
            raw = self._open(req, timeout=30).read().decode("utf-8")
        except urllib.error.HTTPError as e:
            if e.code == 401 and not retried:
                self.renew()
                return self._send(method, path, value, params, retried=True)
            raise HttpError(e.code, e.read().decode("utf-8", "replace")) from None
        return json.loads(raw) if raw else None

    def put(self, path, value):
        return self._send("PUT", path, value)

    def patch(self, path, value):
        return self._send("PATCH", path, value)

    def get(self, path, params=None):
        return self._send("GET", path, None, params)

    def delete(self, path):
        return self._send("DELETE", path, None)

    # --- 구독 ---------------------------------------------------------
    def stream(self, path, params=None):
        """SSE 로 구독한다. (event, data) 를 내놓는 제너레이터. 끊기면 그냥 끝난다."""
        req = urllib.request.Request(self._url(path, params),
                                     headers={"Accept": "text/event-stream"})
        resp = self._open(req, timeout=None)
        buf = []
        for raw in resp:
            line = raw.decode("utf-8", "replace").rstrip("\n")
            buf.append(line)
            if line == "":
                for item in parse_sse(buf):
                    yield item
                buf = []
```

- [ ] **Step 4: 시험이 통과하는지 확인**

```powershell
python tests/test_agent.py
```

Expected: `23/23 통과`

- [ ] **Step 5: 커밋**

```bash
git add firebase/agent/fb.py firebase/tests/test_agent.py
git commit -m "firebase: 에이전트 REST 클라이언트 (토큰 갱신·RTDB·SSE)"
```

---

### Task 7: 에이전트 - 상태 올리기, heartbeat, 오프라인 큐

**Files:**
- Create: `firebase/agent/agent.py`
- Modify: `firebase/tests/test_agent.py` (3절 추가)

**Interfaces:**
- Consumes: `fb.Client`, `secret.load_config`, `rpa_status.dashboard_snapshot()`
- Produces:
  - `agent.clean_for_rtdb(value)` — RTDB 가 거부하는 키(`. $ # [ ] /`)를 지우고 빈 dict 를 None 으로 만든다
  - `agent.trim_logs(snapshot, lines=80)` — 각 프로그램의 `log` 를 뒤에서 80줄만 남긴다
  - `agent.Uploader(client, cid, pc_id, queue_path)` — `.push_live(snapshot)`, `.push_heartbeat(info)`, `.flush()`, `.pending()`

- [ ] **Step 1: 실패하는 시험 추가**

`firebase/tests/test_agent.py` 의 요약 출력 앞에 넣는다:

```python
print("\n3절 상태 올리기와 오프라인 큐")
import agent as ag

check(ag.clean_for_rtdb({"a.b": 1, "ok": 2}) == {"ok": 2}, "점이 든 키를 버린다")
check(ag.clean_for_rtdb({"a": {"b$": 1, "c": 2}}) == {"a": {"c": 2}}, "깊은 곳의 키도 버린다")
check(ag.clean_for_rtdb({"a": []}) == {"a": None}, "빈 목록은 None (RTDB 는 빈 값을 못 담는다)")
check(ag.clean_for_rtdb({"a": [1, 2]}) == {"a": [1, 2]}, "값이 있는 목록은 그대로")

snap = {"programs": {"routine": {"log": [f"줄{i}" for i in range(200)], "state": "running"},
                     "prepare": None}}
out = ag.trim_logs(snap, lines=80)
check(len(out["programs"]["routine"]["log"]) == 80, "로그는 80줄만 남는다")
check(out["programs"]["routine"]["log"][0] == "줄120", "뒤에서 80줄")
check(out["programs"]["prepare"] is None, "없는 프로그램은 그대로 None")
check(len(snap["programs"]["routine"]["log"]) == 200, "원본은 건드리지 않는다")


class FlakyClient:
    def __init__(self):
        self.ok = True
        self.puts = []

    def put(self, path, value):
        if not self.ok:
            raise fb.HttpError(503, "끊김")
        self.puts.append((path, value))


with tempfile.TemporaryDirectory() as d:
    q = os.path.join(d, "queue.jsonl")
    cl = FlakyClient()
    up = ag.Uploader(cl, "c_demo", "pc_office", q)

    up.push_live({"host": "PC1"})
    check(cl.puts[-1][0] == "live/c_demo/pc_office", "현황은 live/회사/PC 로 간다")

    cl.ok = False
    up.push_live({"host": "PC2"})
    up.push_heartbeat({"at": 1})
    check(up.pending() == 2, "끊기면 큐에 쌓는다")
    check(os.path.exists(q), "큐는 파일로 남는다")

    cl.ok = True
    up.flush()
    check(up.pending() == 0, "연결되면 큐를 비운다")
    check([p for p, _ in cl.puts][-2:] == ["live/c_demo/pc_office", "live/c_demo/pc_office/heartbeat"],
          "쌓인 순서대로 보낸다")

    cl.ok = False
    up.push_live({"host": "PC3"})
    up2 = ag.Uploader(cl, "c_demo", "pc_office", q)
    check(up2.pending() == 1, "에이전트를 다시 켜도 큐가 남아 있다")

    cl2 = FlakyClient()
    cl2.ok = True
    up3 = ag.Uploader(cl2, "c_demo", "pc_office", q)
    up3.flush()
    check(up3.pending() == 0 and len(cl2.puts) == 1, "다시 켠 뒤 밀린 것을 보낸다")
```

- [ ] **Step 2: 시험이 실패하는지 확인**

```powershell
python tests/test_agent.py
```

Expected: `ModuleNotFoundError: No module named 'agent'`

- [ ] **Step 3: 구현 (이 Task 에서 쓰는 부분만)**

`firebase/agent/agent.py`:

```python
"""ERPia RPA 클라우드 에이전트.

PC 에서만 할 수 있는 일을 맡는다: 상태 올리기, heartbeat, 클라우드 명령 수행.
화면과 로그인은 Firebase 가 맡는다.

기존 코드를 고치지 않고 가져다 쓴다:
  rpa_status.dashboard_snapshot()  현황
  rpa_dashboard.launch()/stop_erpia()  실행·종료 (1PC 1프로그램 잠금 포함)
  rpa_status.write_routine_modules()  실행 모듈
"""
import json
import os
import sys
import time

RPA_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
if RPA_DIR not in sys.path:
    sys.path.insert(0, RPA_DIR)

import fb   # noqa: E402

BAD_KEY_CHARS = ".$#[]/"
LOG_LINES = 80
QUEUE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "queue.jsonl")
QUEUE_MAX = 500


def clean_for_rtdb(value):
    """RTDB 가 거부하는 키를 버리고, 빈 dict/list 를 None 으로 바꾼다."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if not isinstance(k, str) or k == "" or any(c in k for c in BAD_KEY_CHARS):
                continue
            out[k] = clean_for_rtdb(v)
        return out or None
    if isinstance(value, (list, tuple)):
        return [clean_for_rtdb(v) for v in value] or None
    return value


def trim_logs(snapshot, lines=LOG_LINES):
    """로그 꼬리만 남긴 사본을 돌려준다 (원본은 건드리지 않는다)."""
    out = json.loads(json.dumps(snapshot, ensure_ascii=False, default=str))
    for view in (out.get("programs") or {}).values():
        if isinstance(view, dict) and isinstance(view.get("log"), list):
            view["log"] = view["log"][-lines:]
    return out


class Uploader:
    """올리기. 실패하면 파일 큐에 쌓아 두고 연결되면 순서대로 다시 보낸다.

    RPA 는 절대 막지 않는다 - 올리기가 실패해도 예외를 밖으로 내보내지 않는다.
    """

    def __init__(self, client, cid, pc_id, queue_path=QUEUE_PATH):
        self._client = client
        self._base = f"live/{cid}/{pc_id}"
        self._queue_path = queue_path
        self._queue = self._read_queue()

    def _read_queue(self):
        rows = []
        try:
            with open(self._queue_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            rows.append(json.loads(line))
                        except ValueError:
                            continue
        except FileNotFoundError:
            pass
        except Exception:
            pass
        return rows

    def _write_queue(self):
        try:
            if not self._queue:
                if os.path.exists(self._queue_path):
                    os.remove(self._queue_path)
                return
            tmp = f"{self._queue_path}.{os.getpid()}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                for row in self._queue[-QUEUE_MAX:]:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
            os.replace(tmp, self._queue_path)
        except Exception:
            pass

    def pending(self):
        return len(self._queue)

    def _send(self, path, value):
        try:
            self._client.put(path, value)
            return True
        except Exception:
            self._queue.append({"path": path, "value": value})
            del self._queue[:-QUEUE_MAX]
            self._write_queue()
            return False

    def push_live(self, snapshot):
        return self._send(self._base, clean_for_rtdb(trim_logs(snapshot)))

    def push_heartbeat(self, info):
        return self._send(f"{self._base}/heartbeat", clean_for_rtdb(info))

    def flush(self):
        """쌓인 것을 순서대로 보낸다. 하나라도 실패하면 거기서 멈춘다."""
        while self._queue:
            row = self._queue[0]
            try:
                self._client.put(row["path"], row["value"])
            except Exception:
                self._write_queue()
                return False
            self._queue.pop(0)
        self._write_queue()
        return True
```

- [ ] **Step 4: 시험이 통과하는지 확인**

```powershell
python tests/test_agent.py
```

Expected: `38/38 통과`

- [ ] **Step 5: 커밋**

```bash
git add firebase/agent/agent.py firebase/tests/test_agent.py
git commit -m "firebase: 에이전트 상태 올리기와 오프라인 큐"
```

---

### Task 8: 에이전트 - 명령 처리와 메인 루프

**Files:**
- Modify: `firebase/agent/agent.py` (명령 처리와 `main()` 추가)
- Modify: `firebase/tests/test_agent.py` (4절 추가)
- Create: `firebase/agent/에이전트_시작.bat`

**Interfaces:**
- Consumes: Task 7 의 `Uploader`, Task 2 의 `commands` 경로와 상태 값
- Produces:
  - `agent.decide(cmd, now)` → `("run", None)` / `("expired", 사유)` / `("bad", 사유)` — 순수 함수, 시험하기 쉽게 분리
  - `agent.Commands(client, cid, pc_id, actions)` — `.handle(cmd_id, cmd, now)` 가 상태를 옮긴다. `actions` 는 `{"launch": fn, "stop_erpia": fn, "set_modules": fn}` 이며 각 함수는 성공하면 메시지 문자열을 돌려주고 실패하면 예외를 올린다
  - `agent.real_actions()` — 기존 `rpa_dashboard` / `rpa_status` 를 묶은 실제 동작

- [ ] **Step 1: 실패하는 시험 추가**

`firebase/tests/test_agent.py` 의 요약 출력 앞에 넣는다:

```python
print("\n4절 명령 처리")

NOW = 2000.0
ok_cmd = {"type": "launch", "by": "u1", "created_at": 1900, "expires_at": 2500, "state": "queued"}

check(ag.decide(ok_cmd, NOW)[0] == "run", "아직 안 지난 명령은 실행한다")
check(ag.decide(dict(ok_cmd, expires_at=1999), NOW)[0] == "expired", "만료된 명령은 실행하지 않는다")
check(ag.decide(dict(ok_cmd, state="done"), NOW)[0] == "bad", "queued 가 아니면 건너뛴다")
check(ag.decide(dict(ok_cmd, type="rm_rf"), NOW)[0] == "bad", "모르는 종류는 건너뛴다")
check(ag.decide({}, NOW)[0] == "bad", "빈 명령은 건너뛴다")


class RecClient:
    def __init__(self):
        self.patches = []

    def patch(self, path, value):
        self.patches.append((path, value))


def make_cmds(actions):
    cl = RecClient()
    return cl, ag.Commands(cl, "c_demo", "pc_office", actions)


cl, cmds = make_cmds({"launch": lambda args: "띄웠습니다"})
cmds.handle("k1", dict(ok_cmd), NOW)
paths = [p for p, _ in cl.patches]
check(paths == ["commands/c_demo/pc_office/k1"] * 2, "명령 자리에만 쓴다")
check(cl.patches[0][1]["state"] == "running", "먼저 running 으로 바꾼다")
check(cl.patches[1][1]["state"] == "done" and cl.patches[1][1]["result"] == "띄웠습니다", "끝나면 done")
check("started_at" in cl.patches[0][1] and "ended_at" in cl.patches[1][1], "시각을 남긴다")


def boom(args):
    raise RuntimeError("루틴 RPA 가 이미 돌고 있습니다")


cl, cmds = make_cmds({"launch": boom})
cmds.handle("k2", dict(ok_cmd), NOW)
check(cl.patches[-1][1]["state"] == "failed", "동작이 실패하면 failed")
check("이미 돌고" in cl.patches[-1][1]["result"], "실패 사유를 남긴다")

cl, cmds = make_cmds({})
cmds.handle("k3", dict(ok_cmd, expires_at=1999), NOW)
check(cl.patches[-1][1]["state"] == "expired", "만료는 expired 로 닫는다")
check(len(cl.patches) == 1, "만료는 running 을 거치지 않는다")

cl, cmds = make_cmds({})
cmds.handle("k4", dict(ok_cmd, state="running"), NOW)
check(cl.patches == [], "이미 running 인 명령은 건드리지 않는다")

cl, cmds = make_cmds({"set_modules": lambda args: f"모듈 {sorted(args)} 적용"})
cmds.handle("k5", dict(ok_cmd, type="set_modules", args={"Login": True, "Sales": False}), NOW)
check(cl.patches[-1][1]["state"] == "done" and "Login" in cl.patches[-1][1]["result"], "set_modules 에 args 를 넘긴다")

cl, cmds = make_cmds({"launch": lambda args: "ok"})
cmds.handle("k6", dict(ok_cmd, type="stop_erpia"), NOW)
check(cl.patches[-1][1]["state"] == "failed" and "할 수 없" in cl.patches[-1][1]["result"],
      "할 줄 모르는 종류는 failed 로 닫는다 (명령이 영원히 남지 않게)")
```

- [ ] **Step 2: 시험이 실패하는지 확인**

```powershell
python tests/test_agent.py
```

Expected: `AttributeError: module 'agent' has no attribute 'decide'`

- [ ] **Step 3: 구현**

`firebase/agent/agent.py` 의 `Uploader` 클래스 **뒤에** 붙인다:

```python
# ---------------------------------------------------------------------------
# 명령
# ---------------------------------------------------------------------------
KNOWN_TYPES = ("launch", "stop_erpia", "set_modules", "set_schedule")


def decide(cmd, now):
    """명령을 실행할지 정한다. ('run'|'expired'|'bad', 사유)"""
    if not isinstance(cmd, dict):
        return "bad", "명령 모양이 아닙니다"
    if cmd.get("state") != "queued":
        return "bad", f"queued 가 아닙니다 ({cmd.get('state')})"
    if cmd.get("type") not in KNOWN_TYPES:
        return "bad", f"모르는 종류입니다 ({cmd.get('type')})"
    expires = cmd.get("expires_at")
    if not isinstance(expires, (int, float)):
        return "bad", "만료 시각이 없습니다"
    if expires < now:
        return "expired", "만료된 명령입니다 (PC 가 꺼져 있었을 수 있습니다)"
    return "run", None


class Commands:
    """명령 하나를 받아 상태를 옮긴다. 한 번에 하나씩만 부른다."""

    def __init__(self, client, cid, pc_id, actions):
        self._client = client
        self._base = f"commands/{cid}/{pc_id}"
        self._actions = actions

    def _mark(self, cmd_id, **fields):
        try:
            self._client.patch(f"{self._base}/{cmd_id}", fields)
        except Exception:
            pass      # 상태를 못 써도 에이전트는 계속 돈다

    def handle(self, cmd_id, cmd, now=None):
        now = time.time() if now is None else now
        verdict, reason = decide(cmd, now)
        if verdict == "bad":
            return verdict
        if verdict == "expired":
            self._mark(cmd_id, state="expired", result=reason, ended_at=int(now))
            return verdict

        self._mark(cmd_id, state="running", started_at=int(now))
        kind = cmd.get("type")
        action = self._actions.get(kind)
        try:
            if action is None:
                raise RuntimeError(f"이 에이전트는 '{kind}' 를 할 수 없습니다")
            message = action(cmd.get("args")) or "완료"
            self._mark(cmd_id, state="done", result=str(message)[:500], ended_at=int(time.time()))
            return "done"
        except Exception as e:
            self._mark(cmd_id, state="failed", result=f"{e}"[:500], ended_at=int(time.time()))
            return "failed"
```

- [ ] **Step 4: 시험이 통과하는지 확인**

```powershell
python tests/test_agent.py
```

Expected: `54/54 통과`

- [ ] **Step 5: 실제 동작과 메인 루프**

`firebase/agent/agent.py` 맨 아래에 붙인다:

```python
# ---------------------------------------------------------------------------
# 실제 동작 (기존 코드를 그대로 쓴다)
# ---------------------------------------------------------------------------
def real_actions():
    import rpa_dashboard as dash
    import rpa_status as st

    def do_launch(args):
        target = (args or {}).get("target") if isinstance(args, dict) else None
        target = target or "routine"
        if target not in dash.TARGETS:
            raise RuntimeError(f"실행 대상이 잘못되었습니다 ({target})")
        dash.launch(target, "cloud")         # 1PC 1프로그램 잠금·중복 방지는 launch 안에 있다
        return f"{dash.TARGETS[target][0]} 을(를) 띄웠습니다"

    def do_stop(args):
        status, body = dash.stop_erpia()
        if status != 200:
            raise RuntimeError(body.get("error") or "ERPia 를 종료하지 못했습니다")
        return body.get("message") or "ERPia 를 종료했습니다"

    def do_modules(args):
        if not isinstance(args, dict) or not args:
            raise RuntimeError("모듈 값이 없습니다")
        wanted = {k: bool(v) for k, v in args.items()
                  if k in dict(st.ROUTINE_CONFIG_MODULES)}
        if not wanted:
            raise RuntimeError("아는 모듈이 없습니다")
        if not any(wanted.values()):
            raise RuntimeError("최소 한 모듈은 켜야 합니다")
        st.write_routine_modules(wanted)
        on = [k for k, v in wanted.items() if v]
        return f"실행 모듈을 바꿨습니다 (켬: {', '.join(on)})"

    return {"launch": do_launch, "stop_erpia": do_stop, "set_modules": do_modules}


def log(text):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {text}"
    print(line, flush=True)
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "에이전트_기록.txt")
    try:
        if os.path.exists(path) and os.path.getsize(path) > 1024 * 1024:
            os.replace(path, path + ".1")
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def main():
    import threading
    import rpa_status as st
    import secret

    cfg = secret.load_config()
    client = fb.Client(cfg)
    up = Uploader(client, cfg["cid"], cfg["pc_id"])
    cmds = Commands(client, cfg["cid"], cfg["pc_id"], real_actions())
    log(f"에이전트 시작  회사={cfg['cid']}  PC={cfg['pc_id']}  밀린 기록={up.pending()}건")

    stop = threading.Event()

    def pump():
        """상태와 heartbeat. 1초마다 상태 파일을 보고 바뀌었을 때만 올린다."""
        last = None
        last_beat = 0.0
        while not stop.is_set():
            try:
                snap = st.dashboard_snapshot()
                body = json.dumps(snap.get("programs"), ensure_ascii=False, default=str)
                if body != last:
                    up.push_live(snap)
                    last = body
                if time.time() - last_beat >= 30:
                    up.push_heartbeat({
                        "at": int(time.time()),
                        "host": snap.get("host"),
                        "rpa_running": bool([p for p, v in (snap.get("programs") or {}).items()
                                             if v and v.get("state") == "running"]),
                    })
                    last_beat = time.time()
                up.flush()
            except Exception as e:
                log(f"상태 올리기 실패: {type(e).__name__}")
            stop.wait(1.0)

    threading.Thread(target=pump, daemon=True).start()

    backoff = 1
    while not stop.is_set():
        try:
            for event, data in client.stream(f"commands/{cfg['cid']}/{cfg['pc_id']}"):
                backoff = 1
                if event not in ("put", "patch") or not isinstance(data, dict):
                    continue
                path, payload = data.get("path") or "/", data.get("data")
                items = {}
                if path == "/" and isinstance(payload, dict):
                    items = payload
                elif path.count("/") == 1 and isinstance(payload, dict):
                    items = {path.strip("/"): payload}
                for cmd_id, cmd in items.items():
                    verdict = decide(cmd, time.time())[0]
                    if verdict == "bad":
                        continue
                    log(f"명령 {cmd.get('type')} ({cmd_id[:8]}) 처리")
                    log(f"  → {cmds.handle(cmd_id, cmd)}")
        except KeyboardInterrupt:
            break
        except Exception as e:
            log(f"구독이 끊겼습니다 ({type(e).__name__}). {backoff}초 뒤 다시 붙습니다")
            stop.wait(backoff)
            backoff = min(backoff * 2, 60)
    stop.set()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 6: 시작 배치파일**

`firebase/agent/에이전트_시작.bat` (CP949 로 저장한다. 만든 뒤 **반드시 한 번 실행해 본다** - 블록 안 괄호 하나로 배치파일이 통째로 죽는다):

```bat
@echo off
chcp 949 >nul
title ERPia RPA 클라우드 에이전트
cd /d "%~dp0"

fltmc >nul 2>&1
if errorlevel 1 (
    echo 관리자 권한이 필요합니다. 권한을 올려 다시 시작합니다.
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList 'elevated' -Verb RunAs"
    exit /b
)

echo ================================================
echo   ERPia RPA 클라우드 에이전트
echo   이 창을 닫으면 에이전트만 꺼집니다.
echo ================================================
echo.

python agent.py
echo.
echo 에이전트가 끝났습니다. 위 내용을 확인하세요.
pause
```

- [ ] **Step 7: 커밋**

```bash
git add firebase/agent/agent.py firebase/agent/에이전트_시작.bat firebase/tests/test_agent.py
git commit -m "firebase: 에이전트 명령 처리와 메인 루프"
```

---

### Task 9: 에뮬레이터 통합 시험

단위 시험은 가짜 클라이언트를 쓴다. 진짜 HTTP·진짜 규칙에 붙여 한 바퀴 돌려 본다.

**Files:**
- Create: `firebase/tests/integration.js`, `firebase/tests/run_integration.md`

**Interfaces:**
- Consumes: Task 1~8 전부
- Produces: 없음 (확인만)

- [ ] **Step 1: 에뮬레이터용 설정 만들기**

에뮬레이터는 실제 계정을 쓰지 않는다. `firebase/tests/integration.js` 가 에뮬레이터 Auth 에 계정을 만들고 claim 을 심는다:

```js
// 에뮬레이터에 시험용 계정을 만들고 claim 을 심는다.
// 실행: firebase emulators:exec --config ../firebase.json --only auth,database --project rpa-test-f02e0 "node integration.js"
//
// FIREBASE_AUTH_EMULATOR_HOST / FIREBASE_DATABASE_EMULATOR_HOST 는 emulators:exec 가 자식 프로세스에
// 직접 넣어 준다. 여기서 process.env 에 넣으면 늦다 - ES 모듈은 본문보다 import 가 먼저 평가된다.
import { initializeApp } from "firebase-admin/app";
import { getAuth } from "firebase-admin/auth";
import { getDatabase } from "firebase-admin/database";

const app = initializeApp({ projectId: "rpa-test-f02e0",
  databaseURL: "http://127.0.0.1:9000/?ns=rpa-test-f02e0-default-rtdb" });
const auth = getAuth(app);
const db = getDatabase(app);

const agent = await auth.createUser({ email: "agent@t.local", password: "pw123456" });
await auth.setCustomUserClaims(agent.uid, { cid: "c_demo", pcId: "pc_office", role: "agent" });
const admin = await auth.createUser({ email: "admin@t.local", password: "pw123456" });
await auth.setCustomUserClaims(admin.uid, { cid: "c_demo", role: "admin" });

// 에이전트가 처리할 명령 하나를 관리자 이름으로 넣어 둔다
const now = Math.floor(Date.now() / 1000);
await db.ref("commands/c_demo/pc_office").push({
  type: "launch", args: { target: "routine" }, by: admin.uid,
  created_at: now, expires_at: now + 600, state: "queued",
});
console.log("시험용 계정과 명령을 만들었습니다. 이제 에이전트를 띄우세요.");
console.log("에뮬레이터를 끄지 말고 새 창에서 run_integration.md 를 따라 하세요.");
await new Promise(() => {});   // 에뮬레이터를 살려 둔다 (Ctrl+C 로 끝낸다)
```

`firebase/admin/` 의 `node_modules` 를 쓰려면 `firebase/tests/package.json` 의 `devDependencies` 에 `"firebase-admin": "^13.0.0"` 을 더하고 `npm install` 한다.

- [ ] **Step 2: 절차 문서**

`firebase/tests/run_integration.md`:

```markdown
# 에뮬레이터 통합 시험 (손으로 한 번)

에뮬레이터는 실제 프로젝트를 건드리지 않는다. 실제 RPA 도 띄우지 않는다 (DRY_RUN).

## 1. 창 A - 에뮬레이터와 시험 데이터

```powershell
cd D:\AX\RPA\firebase\tests
firebase emulators:exec --only auth,database --project rpa-test-f02e0 "node integration.js"
```

## 2. 창 B - 에이전트

```powershell
cd D:\AX\RPA\firebase\agent
$env:RPA_DASHBOARD_DRY_RUN = "1"
$env:RPA_STATUS_DIR = "D:\AX\RPA\tests\status_sim"
python - <<'PY'
import secret
secret.write_config("agent_config.json", {
    "project_id": "rpa-test-f02e0",
    "api_key": "아무값",                     # 에뮬레이터는 키를 보지 않는다
    "database_url": "http://127.0.0.1:9000/?ns=rpa-test-f02e0-default-rtdb",
    "cid": "c_demo", "pc_id": "pc_office", "email": "agent@t.local",
}, "pw123456")
PY
$env:FIREBASE_AUTH_EMULATOR_HOST = "127.0.0.1:9099"
python agent.py
```

에뮬레이터를 쓰려면 `fb.py` 의 로그인 주소가 에뮬레이터를 향해야 한다. `FIREBASE_AUTH_EMULATOR_HOST` 가 있으면
`http://<host>/identitytoolkit.googleapis.com/v1/...` 로 바꾸도록 `fb.py` 에 아래를 넣는다 (Step 3).

## 3. 확인할 것

- 창 B 에 `명령 launch (…) 처리` 와 `→ done` 이 찍힌다.
- 에뮬레이터 UI(http://127.0.0.1:4000/database)에서 `commands/c_demo/pc_office/<키>/state` 가 `done`.
- `live/c_demo/pc_office/programs` 에 `tests/status_sim` 의 상태가 올라와 있다.
- `live/c_demo/pc_office/heartbeat/at` 이 30초마다 바뀐다.
- 창 A 를 Ctrl+C 로 끄면 창 B 에 `구독이 끊겼습니다 … 1초 뒤 다시 붙습니다` 가 찍히고 간격이 2, 4, 8 로 늘어난다.
- 창 A 를 다시 띄우면 밀린 상태가 올라간다 (`밀린 기록` 이 0 이 된다).
```

- [ ] **Step 3: 에뮬레이터 주소 지원 넣기**

`firebase/agent/fb.py` 의 `SIGNIN_URL` / `REFRESH_URL` 을 함수로 바꾼다:

```python
def _auth_host():
    host = os.environ.get("FIREBASE_AUTH_EMULATOR_HOST")
    return f"http://{host}/identitytoolkit.googleapis.com" if host else "https://identitytoolkit.googleapis.com"


def _token_host():
    host = os.environ.get("FIREBASE_AUTH_EMULATOR_HOST")
    return f"http://{host}/securetoken.googleapis.com" if host else "https://securetoken.googleapis.com"
```

`_sign_in` / `_refresh` 안의 주소를 각각 `f"{_auth_host()}/v1/accounts:signInWithPassword?key={...}"`,
`f"{_token_host()}/v1/token?key={...}"` 로 바꾸고 파일 맨 위에 `import os` 를 더한다.
2절 시험의 `check("signInWithPassword?key=KEY" in http.calls[0][1], ...)` 는 그대로 통과한다.

- [ ] **Step 4: 시험 다시 돌리기**

```powershell
python tests/test_agent.py
cd tests; npm test
```

Expected: 파이썬 54/54, Node 22/22.

- [ ] **Step 5: 통합 시험 수행**

`run_integration.md` 의 3절 확인 항목을 전부 눈으로 본다. 하나라도 어긋나면 고치고 다시 한다.

- [ ] **Step 6: 커밋**

```bash
git add firebase/agent/fb.py firebase/tests/integration.js firebase/tests/run_integration.md firebase/tests/package.json
git commit -m "firebase: 에뮬레이터 통합 시험"
```

---

### Task 10: 화면 - 로그인과 현황

**Files:**
- Create: `firebase/web/firebase-config.js`, `firebase/web/index.html`, `firebase/web/app.js`

**Interfaces:**
- Consumes: Task 2 의 RTDB 경로, Task 4 의 계정
- Produces: Hosting 에 올릴 수 있는 정적 화면. Task 11 이 여기에 버튼을 더한다.

- [ ] **Step 1: 설정 파일**

`firebase/web/firebase-config.js`:

```js
// 공개돼도 되는 값이다. 보안은 DB 규칙이 한다.
export const firebaseConfig = {
  apiKey: "AIzaSyCFbHQjWVxzi38IAYIhQX9wyiGIs1VcZuA",
  authDomain: "rpa-test-f02e0.firebaseapp.com",
  databaseURL: "https://rpa-test-f02e0-default-rtdb.asia-southeast1.firebasedatabase.app",
  projectId: "rpa-test-f02e0",
  storageBucket: "rpa-test-f02e0.firebasestorage.app",
  messagingSenderId: "420865367421",
  appId: "1:420865367421:web:14b9e1e10c5fadc7e04014",
};
export const HEARTBEAT_STALE_SEC = 120;
export const COMMAND_TTL_SEC = 600;
```

- [ ] **Step 2: 화면 뼈대**

`firebase/web/index.html`. 지금 `dashboard.html` 의 배색과 카드 모양을 따른다 (사용자는 설명 문구를 싫어한다 - 라벨만 쓴다):

```html
<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RPA 현황</title>
<style>
  :root { color-scheme: light dark; --bg:#f6f7f9; --card:#fff; --ink:#1c2024; --muted:#6b7280; --line:#e5e7eb; --ok:#15803d; --bad:#b91c1c; --run:#1d4ed8; }
  @media (prefers-color-scheme: dark) { :root { --bg:#14171a; --card:#1c2024; --ink:#e8eaed; --muted:#9aa2ad; --line:#2c3238; } }
  * { box-sizing: border-box; }
  body { margin:0; padding:16px; background:var(--bg); color:var(--ink); font:15px/1.5 "Malgun Gothic",system-ui,sans-serif; }
  .wrap { max-width: 880px; margin: 0 auto; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:16px; margin-bottom:12px; }
  .row { display:flex; align-items:center; gap:8px; justify-content:space-between; }
  h1 { font-size:18px; margin:0 0 12px; }
  h2 { font-size:15px; margin:0 0 10px; }
  label { display:block; margin-bottom:8px; }
  input, select, button { font:inherit; padding:8px 10px; border-radius:8px; border:1px solid var(--line); background:var(--card); color:var(--ink); }
  input, select { width:100%; }
  button { cursor:pointer; }
  button[disabled] { opacity:.5; cursor:default; }
  .muted { color:var(--muted); }
  .hide { display:none; }
  .st-running { color:var(--run); } .st-success { color:var(--ok); } .st-failed,.st-stopped { color:var(--bad); }
  .alert { border-radius:8px; padding:10px; margin-top:10px; border:1px solid var(--line); }
  .alert.bad { color:var(--bad); }
  ul.steps { list-style:none; padding:0; margin:8px 0 0; }
  ul.steps li { display:flex; justify-content:space-between; padding:4px 0; border-top:1px solid var(--line); }
</style>
</head>
<body>
<div class="wrap">

  <section id="login" class="card hide">
    <h1>RPA 현황</h1>
    <label>이메일 <input id="email" type="email" autocomplete="username"></label>
    <label>비밀번호 <input id="password" type="password" autocomplete="current-password"></label>
    <button id="login-btn">로그인</button>
    <div id="login-alert" class="alert bad hide"></div>
  </section>

  <section id="main" class="hide">
    <div class="card row">
      <h1 style="margin:0">RPA 현황</h1>
      <div class="row">
        <select id="pc-pick" class="hide" style="width:auto"></select>
        <span id="who" class="muted"></span>
        <button id="logout-btn">로그아웃</button>
      </div>
    </div>

    <div class="card">
      <div class="row"><h2>연결</h2><span id="conn" class="muted">확인 중</span></div>
    </div>

    <div class="card">
      <h2>루틴 RPA</h2>
      <div id="routine" class="muted">기록 없음</div>
    </div>

    <div class="card">
      <h2>프리페어 RPA</h2>
      <div id="prepare" class="muted">기록 없음</div>
    </div>
  </section>

</div>
<script type="module" src="./app.js"></script>
</body>
</html>
```

- [ ] **Step 3: 화면 코드**

`firebase/web/app.js`:

```js
import { initializeApp } from "https://www.gstatic.com/firebasejs/10.14.1/firebase-app.js";
import {
  getAuth, signInWithEmailAndPassword, signOut, onAuthStateChanged,
} from "https://www.gstatic.com/firebasejs/10.14.1/firebase-auth.js";
import {
  getDatabase, ref, onValue, get,
} from "https://www.gstatic.com/firebasejs/10.14.1/firebase-database.js";
import { firebaseConfig, HEARTBEAT_STALE_SEC } from "./firebase-config.js";

const app = initializeApp(firebaseConfig);
const auth = getAuth(app);
const db = getDatabase(app);
const $ = (id) => document.getElementById(id);

let me = null;          // { uid, email, cid, role }
let pcId = null;
let stopLive = null;

const show = (el, on) => el.classList.toggle("hide", !on);

// --- 로그인 ---------------------------------------------------------
$("login-btn").addEventListener("click", async () => {
  const alert = $("login-alert");
  show(alert, false);
  $("login-btn").disabled = true;
  try {
    await signInWithEmailAndPassword(auth, $("email").value.trim(), $("password").value);
    $("password").value = "";
  } catch (e) {
    alert.textContent = e.code === "auth/invalid-credential"
      ? "이메일 또는 비밀번호가 맞지 않습니다" : `로그인하지 못했습니다 (${e.code})`;
    show(alert, true);
  } finally {
    $("login-btn").disabled = false;
  }
});
$("password").addEventListener("keydown", (e) => { if (e.key === "Enter") $("login-btn").click(); });
$("logout-btn").addEventListener("click", () => signOut(auth));

onAuthStateChanged(auth, async (user) => {
  if (stopLive) { stopLive(); stopLive = null; }
  if (!user) {
    me = null; pcId = null;
    show($("login"), true); show($("main"), false);
    return;
  }
  const t = await user.getIdTokenResult(true);
  me = { uid: user.uid, email: user.email, cid: t.claims.cid || null, role: t.claims.role || null };
  $("who").textContent = `${user.email} (${me.role === "admin" ? "관리자" : me.role === "super" ? "총괄" : "열람"})`;
  show($("login"), false); show($("main"), true);
  await pickPc();
});

// --- PC 고르기 ------------------------------------------------------
async function pickPc() {
  let pcs = {};
  try {
    const snap = await get(ref(db, `meta/companies/${me.cid}/pcs`));
    pcs = snap.val() || {};
  } catch { pcs = {}; }
  const keys = Object.keys(pcs);
  const sel = $("pc-pick");
  sel.replaceChildren(...keys.map((k) => {
    const o = document.createElement("option");
    o.value = k; o.textContent = pcs[k]?.label || k;
    return o;
  }));
  show(sel, keys.length > 1);
  pcId = keys[0] || null;
  sel.onchange = () => { pcId = sel.value; watchLive(); };
  watchLive();
}

// --- 현황 -----------------------------------------------------------
function watchLive() {
  if (stopLive) { stopLive(); stopLive = null; }
  if (!pcId) { $("conn").textContent = "등록된 PC 가 없습니다"; return; }
  stopLive = onValue(ref(db, `live/${me.cid}/${pcId}`), (snap) => paint(snap.val()), (e) => {
    $("conn").textContent = e.code === "PERMISSION_DENIED" ? "권한 없음" : "읽지 못했습니다";
  });
}

const STATE_LABEL = { running: "진행 중", success: "성공", failed: "실패", stopped: "중단" };

function paint(live) {
  const beat = live?.heartbeat?.at;
  const age = beat ? Math.floor(Date.now() / 1000) - beat : null;
  $("conn").textContent = age == null ? "기록 없음"
    : age > HEARTBEAT_STALE_SEC ? `PC 연결 끊김 (${Math.floor(age / 60)}분 전)` : "연결됨";
  $("conn").className = age != null && age <= HEARTBEAT_STALE_SEC ? "st-success" : "muted";
  for (const key of ["routine", "prepare"]) paintProgram($(key), live?.programs?.[key]);
}

function paintProgram(box, view) {
  if (!view) { box.textContent = "기록 없음"; box.className = "muted"; return; }
  const steps = view.steps || [];
  const done = view.steps_done ?? 0;
  const total = view.steps_total ?? steps.length;
  const head = document.createElement("div");
  head.className = "row";
  const state = document.createElement("b");
  state.textContent = STATE_LABEL[view.state] || view.state || "";
  state.className = `st-${view.state}`;
  head.append(state, Object.assign(document.createElement("span"),
    { className: "muted", textContent: `${done}/${total} 단계` }));
  const list = document.createElement("ul");
  list.className = "steps";
  for (const s of steps.slice(-8)) {
    const li = document.createElement("li");
    li.append(Object.assign(document.createElement("span"), { textContent: s.label || s.key }),
      Object.assign(document.createElement("span"),
        { className: `st-${s.state} muted`, textContent: STATE_LABEL[s.state] || s.state || "" }));
    list.append(li);
  }
  box.replaceChildren(head, list);
  box.className = "";
}
```

- [ ] **Step 4: 로컬에서 띄워 확인**

`firebase/` 에서:

```powershell
firebase serve --only hosting --project rpa-test-f02e0
```

브라우저에서 http://127.0.0.1:5000 을 연다. Task 4 에서 만든 회사 관리자 계정으로 로그인한다.

Expected:
- 로그인이 되고 오른쪽 위에 이메일과 `(관리자)` 가 뜬다.
- 아직 에이전트를 안 띄웠으면 연결이 `기록 없음`.
- 틀린 비밀번호를 넣으면 `이메일 또는 비밀번호가 맞지 않습니다`.
- 로그아웃하면 로그인 화면으로 돌아온다.

- [ ] **Step 5: 커밋**

```bash
git add firebase/web
git commit -m "firebase: 화면 로그인과 현황"
```

---

### Task 11: 화면 - 실행, ERPia 종료, 실행 모듈

**Files:**
- Modify: `firebase/web/index.html` (버튼과 모듈 카드), `firebase/web/app.js`

**Interfaces:**
- Consumes: Task 10 의 `me` / `pcId`, Task 2 의 `commands` / `settings` 규칙
- Produces: 없음 (1차의 마지막 화면 기능)

- [ ] **Step 1: 화면에 카드 더하기**

`index.html` 의 `<section id="main">` 안, 연결 카드 **바로 뒤에** 넣는다:

```html
    <div class="card" id="act-card">
      <div class="row">
        <h2 style="margin:0">실행</h2>
        <div class="row">
          <button id="run-routine">루틴 RPA</button>
          <button id="run-all">전체 실행</button>
          <button id="stop-erpia">ERPia 종료</button>
        </div>
      </div>
      <div id="act-alert" class="alert hide"></div>
    </div>

    <div class="card" id="mod-card">
      <div class="row"><h2 style="margin:0">실행 모듈</h2><span id="mod-meta" class="muted"></span></div>
      <div id="mod-list"></div>
      <button id="mod-apply" disabled>적용</button>
    </div>
```

- [ ] **Step 2: 명령 보내기와 모듈 쓰기**

`app.js` 맨 아래에 붙인다:

```js
import { push, set, serverTimestamp } from "https://www.gstatic.com/firebasejs/10.14.1/firebase-database.js";
import { COMMAND_TTL_SEC } from "./firebase-config.js";

const MODULES = [
  ["Login", "로그인"], ["Sales", "주문매핑 매출처리"], ["Hold", "물류대기 관리"],
  ["Logistics", "물류관리"], ["Output", "운송장 출력 / 엑셀 생성"],
];
let savedModules = {};
let formModules = {};
let stopSettings = null;
let busy = false;

const isAdmin = () => me && (me.role === "admin" || me.role === "super");

function setAlert(kind, text) {
  const box = $("act-alert");
  box.textContent = text;
  box.className = `alert ${kind === "bad" ? "bad" : ""}`;
  show(box, !!text);
}

async function sendCommand(type, args, label) {
  if (busy) return;
  busy = true;
  for (const id of ["run-routine", "run-all", "stop-erpia"]) $(id).disabled = true;
  setAlert("", `${label} 명령을 보냈습니다. PC 응답을 기다립니다.`);
  try {
    const now = Math.floor(Date.now() / 1000);
    const node = await push(ref(db, `commands/${me.cid}/${pcId}`), {
      type, args: args ?? null, by: me.uid,
      created_at: now, expires_at: now + COMMAND_TTL_SEC, state: "queued",
    });
    await watchCommand(node.key, label);
  } catch (e) {
    setAlert("bad", e.code === "PERMISSION_DENIED" ? "권한이 없습니다" : `보내지 못했습니다 (${e.code || e})`);
  } finally {
    busy = false;
    paintButtons();
  }
}

function watchCommand(key, label) {
  return new Promise((resolve) => {
    const timer = setTimeout(() => {
      off(); setAlert("bad", "PC 가 응답하지 않습니다"); resolve();
    }, 60000);
    const off = onValue(ref(db, `commands/${me.cid}/${pcId}/${key}`), (snap) => {
      const v = snap.val();
      if (!v) return;
      if (v.state === "running") setAlert("", `${label} 진행 중`);
      if (["done", "failed", "expired"].includes(v.state)) {
        clearTimeout(timer); off();
        setAlert(v.state === "done" ? "" : "bad", v.result || v.state);
        resolve();
      }
    });
  });
}

$("run-routine").addEventListener("click", () => sendCommand("launch", { target: "routine" }, "루틴 RPA"));
$("run-all").addEventListener("click", () => sendCommand("launch", { target: "all" }, "전체 실행"));
$("stop-erpia").addEventListener("click", () => {
  if (confirm("ERPia 를 종료할까요? (종료가 곧 로그아웃입니다)")) sendCommand("stop_erpia", null, "ERPia 종료");
});

// --- 실행 모듈 ------------------------------------------------------
function watchSettings() {
  if (stopSettings) { stopSettings(); stopSettings = null; }
  if (!pcId) return;
  stopSettings = onValue(ref(db, `settings/${me.cid}/${pcId}/modules`), (snap) => {
    savedModules = snap.val() || {};
    formModules = Object.fromEntries(MODULES.map(([k]) => [k, savedModules[k] !== false]));
    paintModules();
  });
}

function modulesDirty() {
  return MODULES.some(([k]) => !!formModules[k] !== (savedModules[k] !== false));
}

function paintModules() {
  $("mod-list").replaceChildren(...MODULES.map(([key, label]) => {
    const row = document.createElement("label");
    row.className = "row";
    const cb = document.createElement("input");
    cb.type = "checkbox"; cb.checked = !!formModules[key];
    cb.style.width = "auto"; cb.disabled = !isAdmin() || busy;
    cb.setAttribute("aria-label", label);
    cb.onchange = () => { formModules[key] = cb.checked; paintModuleMeta(); };
    row.append(Object.assign(document.createElement("span"), { textContent: label }), cb);
    return row;
  }));
  paintModuleMeta();
}

function paintModuleMeta() {
  const on = MODULES.filter(([k]) => formModules[k]).length;
  $("mod-meta").textContent = `${on}/${MODULES.length} 켬`;
  $("mod-apply").disabled = !isAdmin() || busy || !modulesDirty() || on === 0;
}

$("mod-apply").addEventListener("click", async () => {
  const wanted = Object.fromEntries(MODULES.map(([k]) => [k, !!formModules[k]]));
  if (!Object.values(wanted).some(Boolean)) { setAlert("bad", "최소 한 모듈은 켜야 합니다"); return; }
  try {
    await set(ref(db, `settings/${me.cid}/${pcId}`), {
      modules: wanted, updated_by: me.uid, updated_at: Math.floor(Date.now() / 1000),
    });
  } catch (e) {
    setAlert("bad", e.code === "PERMISSION_DENIED" ? "권한이 없습니다" : `저장하지 못했습니다 (${e.code || e})`);
    return;
  }
  await sendCommand("set_modules", wanted, "실행 모듈");
});

function paintButtons() {
  for (const id of ["run-routine", "run-all", "stop-erpia"]) $(id).disabled = !isAdmin() || busy || !pcId;
  paintModuleMeta();
}
```

`import` 두 줄은 파일 맨 위 기존 import 옆으로 옮긴다 (ES 모듈은 import 가 맨 위여야 한다). `onValue` 의 반환값을 끄는 `off` 는 `onValue` 가 돌려주는 함수다.

`watchLive()` 안 마지막에 `watchSettings(); paintButtons();` 를 더하고, `onAuthStateChanged` 의 로그아웃 갈래에 `if (stopSettings) { stopSettings(); stopSettings = null; }` 를 더한다.

- [ ] **Step 3: 권한이 화면에서도 맞는지 확인**

```powershell
firebase serve --only hosting --project rpa-test-f02e0
```

- 관리자 계정: 버튼과 스위치가 눌린다.
- 열람자 계정(Task 4 의 `user … viewer` 로 하나 더 만든다): 버튼과 스위치가 모두 흐리고 눌리지 않는다. 개발자 도구 콘솔에서 직접 `push` 를 시도하면 `PERMISSION_DENIED` 가 난다 (규칙이 막는다는 확인).

- [ ] **Step 4: 커밋**

```bash
git add firebase/web
git commit -m "firebase: 화면에서 실행·ERPia 종료·실행 모듈"
```

---

### Task 12: 실기 (사내 PC 1대)

에뮬레이터가 아니라 진짜 프로젝트에 붙인다. **테스트 업체 erpiatest2 로, 로그인 모듈만 켠 채 시작한다.**

**Files:**
- Create: `firebase/agent/agent_config.json` (커밋하지 않는다)

**Interfaces:**
- Consumes: Task 1~11 전부
- Produces: 1차 완료

- [ ] **Step 1: Hosting 에 올리기**

```powershell
cd D:\AX\RPA\firebase
firebase login
firebase deploy --only hosting,database,firestore --project rpa-test-f02e0
```

Expected: `Hosting URL: https://rpa-test-f02e0.web.app`. 규칙도 같이 올라간다.

- [ ] **Step 2: 에이전트 설정 만들기**

`firebase/agent/` 에서. 비밀번호는 Task 4 에서 정한 에이전트 계정 비밀번호다.

```powershell
python -c "import secret, getpass; secret.write_config('agent_config.json', {'project_id':'rpa-test-f02e0','api_key':'AIzaSyCFbHQjWVxzi38IAYIhQX9wyiGIs1VcZuA','database_url':'https://rpa-test-f02e0-default-rtdb.asia-southeast1.firebasedatabase.app','cid':'c_demo','pc_id':'pc_office','email':'agent-pc-office@c-demo.rpa-test-f02e0.firebaseapp.com'}, getpass.getpass('에이전트 비밀번호: '))"
```

`getpass` 를 쓰므로 비밀번호가 화면과 명령 이력에 남지 않는다.

```powershell
git status --short
```

Expected: `agent_config.json` 이 목록에 없다 (`.gitignore` 가 막는다). 보이면 멈추고 `.gitignore` 부터 고친다.

- [ ] **Step 3: 실행 모듈을 로그인만 켜 둔다**

실기 중 사고를 막는다. 지금 대시보드(8765)나 `ERPIA_AI.txt` 에서 `Login=Y`, 나머지 `N` 으로 둔다.

```powershell
cd D:\AX\RPA
python -c "import rpa_status as st; print(st.read_routine_modules())"
```

Expected: `Login` 만 True.

- [ ] **Step 4: 에이전트 띄우기**

`firebase/agent/에이전트_시작.bat` 을 **더블클릭**한다 (관리자 권한 확인이 도는지 본다).

Expected: `에이전트 시작  회사=c_demo  PC=pc_office  밀린 기록=0건`

- [ ] **Step 5: 클라우드 화면에서 확인**

https://rpa-test-f02e0.web.app 을 열고 회사 관리자 계정으로 로그인한다.

Expected:
- 연결이 `연결됨`.
- 루틴 RPA 칸에 마지막 실행 기록이 보인다.
- 실행 모듈이 `1/5 켬`.

- [ ] **Step 6: 실행 시켜 보기**

화면에서 `루틴 RPA` 를 누른다.

Expected:
- 몇 초 안에 `루틴 RPA 진행 중` → `루틴 RPA 을(를) 띄웠습니다`.
- PC 에 콘솔 창이 뜨고 ERPia 로그인만 하고 끝난다 (나머지 모듈은 `설정에서 끔`).
- 화면의 루틴 RPA 칸이 진행 중 → 성공으로 바뀐다.
- 돌고 있는 동안 `루틴 RPA` 를 한 번 더 누르면 `… 가 이미 돌고 있습니다` 로 거절된다 (1PC 1프로그램).

- [ ] **Step 7: 모듈 바꾸기와 종료 확인**

- 화면에서 `물류대기 관리` 를 켜고 `적용` → `실행 모듈을 바꿨습니다`.
- `D:\AX\RPA` 에서 `python -c "import rpa_status as st; print(st.read_routine_modules())"` 로 파일이 실제로 바뀌었는지 본다. `ERPIA_AI.txt.bak` 이 생겼는지도 본다.
- 화면에서 `ERPia 종료` → ERPia 창이 닫힌다.
- 에이전트 창을 닫았다가 화면에서 `루틴 RPA` 를 누르면 60초 뒤 `PC 가 응답하지 않습니다`. 에이전트를 다시 띄우면 그 명령은 만료 전이면 그때 돈다. 10분이 지난 뒤면 `만료된 명령입니다` 로 닫힌다.

- [ ] **Step 8: 실행 모듈 원래대로**

사용자가 쓰던 값으로 되돌린다 (2026-09-19 기준: 로그인 켬 / 주문매핑 끔 / 물류대기 켬 / 물류관리 켬 / 출력 켬).

- [ ] **Step 9: 기록과 커밋**

`docs/superpowers/plans/2026-09-21-firebase-phase1.md` 맨 위에 실기 결과 한 줄을 더한다.

```bash
git add docs/superpowers/plans/2026-09-21-firebase-phase1.md
git commit -m "firebase: 1차 실기 확인"
```

---

## 남은 것 (2차, 이 계획 밖)

- 이력: 에이전트가 `history.jsonl` 새 줄을 Firestore `runs` 에 올리고, 화면에 이력 탭을 만든다. Firestore REST 는 값에 형(type)을 붙여야 하므로, 조회에 쓰는 필드(`cid`, `pcId`, `run_id`, `program`, `state`, `started_at`, `duration_sec`)만 형을 붙이고 나머지 기록은 `payload` 한 칸에 JSON 문자열로 넣는다.
- 자동 예약(`set_schedule`), super 의 회사 고르기, 두 번째 회사 등록 리허설.
- 첫 로그인 비밀번호 변경 강제 (`users/{uid}.must_change_password` 를 화면이 읽어 변경 화면으로 보낸다).
- 알림(실패 시 이메일). 여기서만 Cloud Functions 가 필요해질 수 있다.
- 옛 `rpa_dashboard.py` 를 언제 정리할지 결정. 그 전까지 둘은 공존한다.
