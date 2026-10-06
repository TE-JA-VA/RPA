# 관리 화면 (AFTERMARKET_SETUP) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 터미널 `setup.js` 로 하던 일(신규 업체 셋팅·토큰·계정·정책·토큰 배율)을 우리 PC 의 브라우저 화면으로 한다.

**Architecture:** `setup.js` 의 일을 `ops.js` 함수로 빼서 터미널과 화면이 같은 코드를 쓴다. `admin.js` 는 127.0.0.1 에서만 듣는
`node:http` 서버 (켤 때마다 새 비밀 값 + Host 검사) 이고 `/api/*` 를 ops.js 로 넘긴다. 화면은 `AFTERMARKET_SETUP.html` 한 장.

**Tech Stack:** Node 24 (ES 모듈), firebase-admin 13 (이미 깔림), 바닐라 HTML/JS, 시험은 Python 3.14 + Playwright (.venv) + Firebase 에뮬레이터.

**Spec:** `docs/superpowers/specs/2026-10-06-admin-tool-design.md`

## Global Constraints

- 커밋·push 는 사용자가 말할 때만 (이 저장소 규칙) - 계획의 커밋 단계는 '사용자에게 커밋할지 묻기' 로 읽는다.
- 실서버에 계정을 만드는 일(user·agent·passwd, 화면의 같은 일)을 Claude 도구로 돌리지 않는다 - 시험은 에뮬레이터에서만.
- 비밀번호는 응답에만 싣는다 - 서버 콘솔·`관리_기록.txt`·시험 출력에 찍지 않는다 (시험은 길이만 본다).
- 사용자에게 보이는 글은 한국어, '값표' 대신 **'토큰 배율'** (명령 이름 `price` 는 그대로).
- `AFTERMARKET_SETUP.bat` 은 **영문(ASCII)만 + CRLF** (한글이 있으면 CP949 여야 하는 함정을 피한다).
- 새 npm 패키지 없음 - node 기본 모듈과 이미 있는 firebase-admin 만.
- 서버는 `127.0.0.1` 에서만 듣는다. `/api` 는 `X-Admin-Key` 가 맞고 `Host` 가 `127.0.0.1:<포트>` 일 때만.

## Review Focus

1. [만들기] 를 두 번 누르거나 요청이 겹치면 토큰이 두 번 들어가면 안 된다 → 고치는 요청은 서버가 하나씩 (Task 2 시험: 동시 두 요청 → 한 번만).
2. 업체코드 `Net-1`, 물류대기 사용 여부 안 고름, 토큰 `1,000` 같은 입력은 아무것도 만들기 전에 거절 (Task 2·3 시험).
3. 업체 이름에 HTML(`<img onerror>`)이 들어 있어도 글자로만 보인다 (Task 3 시험).
4. 서버를 다시 켠 뒤 옛 주소(옛 비밀 값)로 연 화면은 '다시 켜세요' 를 알린다 (Task 3 시험).
5. 중간에 실패한 흐름을 다시 누르면 남은 것만, 이미 있는 계정은 건너뛰고 재발급 안내 (Task 2 시험).

---

### Task 1: ops.js 로 옮기기 (setup.js 는 얇은 터미널 앞단)

**Files:**
- Create: `firebase/admin/ops.js`
- Modify: `firebase/admin/setup.js` (전부 다시 씀 - 명령·나오는 글은 그대로)
- Test: `firebase/tests/check_setup.py`

**Interfaces:**
- Produces (ops.js): `class Refused extends Error`, `PROJECT`, `DASHBOARD_URL`, `PRICE_BASE`, `POLICY_KEYS`, `emailFor(cid, local)`,
  `onEmulator()`, `nowKst()`, `checkKey(name, value)`, `cidOf(arg)`, `companyOf(cid, {removed})`, `usersOf(cid?)`, `spentSince(cid, since?)`,
  `addCompany(cid, name) → {cid, name}`, `addPc(cid, pcId, label) → {cid, pcId, label}`,
  `addUser(cidArg, id, role, name) → {email, uid, role, cid, password}`, `addAgent(cid, pcId) → {email, uid, cid, pcId, password}`,
  `resetPassword(cidArg, id) → {email, password, agent}`, `setDisabled(cidArg, id, disabled) → {email, disabled}`, `showUser(cidArg, id)`,
  `listAll(cid?) → {companies, users}`, `setModules(cid, {Key: "on"|"off"}) → policy`, `setCompanyRemoved(cid, removing) → {cid, name, already, users: [email]}`,
  `grantTokens(cid, amount, memo) → {created, cid, name, wallet}`, `tokenStatus(cid) → {cid, name, wallet: null | {granted, since, spent, left, grants}}`,
  `getPrices() → table`, `setPrice(key, value) → table`, `usageRows(cid?) → [{cid, name, stts, left, month, since}]`

- [ ] **Step 1: 실패할 시험 셋 더하기** - `firebase/tests/check_setup.py` 의 1절 `"없는 업체엔 user 를 못 만든다"` 바로 뒤에:

```python
check(out.strip().startswith("오류: 먼저 company") and "    at " not in out, "거절은 '오류: …' 한 줄 (오류 꼬리 없이)", out[-200:])
rc, out = setup("modules", "t_none", "Hold=off")
check(rc != 0 and "먼저 company" in out and db_get("meta/companies/t_none") is None, "없는 업체엔 모듈 정책을 못 넣는다", out[-200:])
```
4절 `rc, out = setup("price")` 의 check 를 바꾼다:
```python
check(rc == 0 and "토큰 배율" in out and "default" in out and "login" in out, "토큰 배율 보기 (서버에 없으면 처음 배율)", out[-200:])
```

- [ ] **Step 2: 실패 확인**

Run (PowerShell): `cd D:\AX\RPA\firebase; . .\emu_env.ps1; cd tests; firebase emulators:exec --config ../firebase.json --only auth,database,firestore --project rpa-test-f02e0 "D:\AX\RPA\.venv\Scripts\python.exe check_setup.py"`
Expected: 셋 실패 (오류 꼬리가 있다, 없는 업체에 정책을 쓴다, '토큰 값표').

- [ ] **Step 3: `firebase/admin/ops.js` 만들기**

```js
// 관리 작업 - setup.js(터미널 명령)와 admin.js(관리 화면 AFTERMARKET_SETUP)가 같이 쓴다. 우리 PC 에서만 돈다.
// 값을 돌려줄 뿐 찍지 않는다. 사람이 고칠 수 있는 거절은 Refused (그 글을 터미널은 '오류: …', 화면은 빨간 알림으로).
// 비밀번호는 무작위로 만들어 돌려줄 뿐 어디에도 남기지 않는다.
// 이메일은 조립한다: <아이디>@<cid 의 _ 를 - 로>.rpa-test-f02e0.firebaseapp.com (cid 가 없으면 도메인만, 기계 계정은 agent-<pcId>).
// 아이디에 @ 가 있으면 그대로 이메일로 쓴다(외부 메일 계정).
import { readFileSync } from "node:fs";
import { randomBytes } from "node:crypto";
import { fileURLToPath } from "node:url";
import { initializeApp, cert } from "firebase-admin/app";
import { getAuth } from "firebase-admin/auth";
import { getDatabase } from "firebase-admin/database";
import { getFirestore, AggregateField } from "firebase-admin/firestore";

export class Refused extends Error {}

// 공유 계약 — agent/agent.py, web/app.js 에도 같은 규칙이 한 줄씩 있다. 셋이 같아야 한다.
export const PROJECT = "rpa-test-f02e0";
export const DASHBOARD_URL = `https://${PROJECT}.web.app`;
const DOMAIN = `${PROJECT}.firebaseapp.com`;
export const emailFor = (cid, local) => local.includes("@") ? local : `${local.replaceAll("_", "-")}@${cid ? cid.replaceAll("_", "-") + "." : ""}${DOMAIN}`;
const randomPassword = () => randomBytes(18).toString("base64url");   // 24자
export const POLICY_KEYS = ["Sales", "Hold", "Logistics", "Output"];   // Login 은 언제나 켬이라 정책 대상이 아니다
export const PRICE_BASE = { default: 1, login: 0 };                    // 에이전트에 박힌 처음 토큰 배율 (agent.PRICES) - 서버 값이 위에 덮인다

const KEY = fileURLToPath(new URL("./serviceAccountKey.json", import.meta.url));
const app = initializeApp({
  credential: cert(JSON.parse(readFileSync(KEY, "utf8"))),
  databaseURL: "https://rpa-test-f02e0-default-rtdb.asia-southeast1.firebasedatabase.app",
});
const auth = getAuth(app), rtdb = getDatabase(app), store = getFirestore(app);

// emulators:exec 안이면 에뮬레이터 (관리 화면 띠가 '에뮬레이터 (시험)')
export const onEmulator = () => ["FIREBASE_AUTH_EMULATOR_HOST", "FIREBASE_DATABASE_EMULATOR_HOST", "FIRESTORE_EMULATOR_HOST"].some((k) => process.env[k]);
// 지금 한국 시각 - PC 가 기록에 적는 started_at 과 같은 꼴 ("2026-10-06T13:55:49")
export const nowKst = () => new Date().toLocaleString("sv-SE", { timeZone: "Asia/Seoul" }).replace(" ", "T");

const KEY_RE = /^[a-z0-9_]+$/;
export function checkKey(name, value) {
  if (!KEY_RE.test(value || "")) throw new Refused(`${name} 는 영문 소문자·숫자·밑줄만 쓴다: ${value ?? ""}`);
}
export function cidOf(arg) {
  if (arg === "-") return null;
  checkKey("cid", arg);
  return arg;
}

async function createAuthUser(email, password) {
  try {
    return await auth.createUser({ email, password, emailVerified: false });
  } catch (e) {
    if (e.code === "auth/email-already-exists") throw new Refused(`${email} 은 이미 있다. 비밀번호를 바꾸려면 passwd, 막으려면 disable`);
    throw e;
  }
}
async function userOf(cidArg, id) {
  const email = emailFor(cidOf(cidArg), String(id ?? ""));
  try {
    return await auth.getUserByEmail(email);
  } catch (e) {
    if (e.code === "auth/user-not-found") throw new Refused(`계정이 없다: ${email}`);
    throw e;
  }
}
// 업체 메타. 없거나 삭제(stts=9)된 업체면 멈춘다 - removed=true 는 remove/restore 처럼 삭제된 업체도 다뤄야 할 때
export async function companyOf(cid, { removed = false } = {}) {
  const v = (await rtdb.ref(`meta/companies/${cid}`).get()).val();
  if (!v?.name) throw new Refused(`먼저 company 로 등록: node setup.js company ${cid} <회사 이름>`);
  if (!removed && v.stts === 9) throw new Refused(`${cid} 는 삭제된 업체다. 되살리려면: node setup.js restore ${cid}`);
  return v;
}
// 그 업체의 계정 전부 (cid 없으면 모두). 기계 계정도 claim 에 cid 가 있어 같이 잡힌다
export async function usersOf(cid) {
  const rows = [];
  let token;
  do {
    const page = await auth.listUsers(1000, token);
    rows.push(...page.users.filter((u) => !cid || u.customClaims?.cid === cid));
    token = page.pageToken;
  } while (token);
  return rows;
}
// 그 업체 실행 기록의 쓴 토큰 합 (since 뒤에 시작한 것만). 서버가 더한다 - 복합 색인 started_at·cost (rules/firestore.indexes.json)
export async function spentSince(cid, since) {
  let q = store.collection(`runs/${cid}/items`);
  if (since) q = q.where("started_at", ">=", since);
  return (await q.aggregate({ s: AggregateField.sum("cost") }).get()).data().s ?? 0;
}

// --- 업체·PC·계정 ---------------------------------------------------------
export async function addCompany(cid, name) {
  checkKey("cid", cid);
  const clean = String(name ?? "").trim();
  if (!clean) throw new Refused("업체 이름을 넣으세요");
  if ((await rtdb.ref(`meta/companies/${cid}/stts`).get()).val() === 9) throw new Refused(`${cid} 는 삭제된 업체다. 되살리려면: node setup.js restore ${cid}`);
  await rtdb.ref(`meta/companies/${cid}`).update({ name: clean, stts: 0 });
  return { cid, name: clean };
}
export async function addPc(cid, pcId, label) {
  checkKey("cid", cid); checkKey("pcId", pcId);
  await companyOf(cid);
  const clean = String(label ?? "").trim();
  await rtdb.ref(`meta/companies/${cid}/pcs/${pcId}`).update({ label: clean });
  return { cid, pcId, label: clean };
}
export async function addUser(cidArg, id, role, name) {
  if (!["super", "admin", "viewer"].includes(role)) throw new Refused("role 은 super/admin/viewer");
  const cid = cidOf(cidArg);
  if (role !== "super" && !cid) throw new Refused("super 가 아니면 cid 가 있어야 한다");
  if (cid) await companyOf(cid);
  const local = String(id ?? "").trim();
  if (!local) throw new Refused("아이디를 넣으세요");
  const email = emailFor(cid, local), password = randomPassword();
  const user = await createAuthUser(email, password);
  try {
    await auth.setCustomUserClaims(user.uid, cid ? { cid, role } : { role });
    await store.doc(`users/${user.uid}`).set({ cid: cid ?? null, role, name: String(name ?? "").trim() || email, must_change_password: true });
  } catch (e) { await auth.deleteUser(user.uid); throw e; }   // claim 없는 반쪽 계정을 남기지 않는다. 다시 하면 된다
  return { email, uid: user.uid, role, cid, password };
}
export async function addAgent(cid, pcId) {
  checkKey("cid", cid); checkKey("pcId", pcId);
  if (!(await companyOf(cid)).pcs?.[pcId]) throw new Refused(`먼저 pc 로 등록: node setup.js pc ${cid} ${pcId} <PC 이름>`);
  const email = emailFor(cid, `agent-${pcId}`), password = randomPassword();
  const user = await createAuthUser(email, password);
  try {
    await auth.setCustomUserClaims(user.uid, { cid, pcId, role: "agent" });
  } catch (e) { await auth.deleteUser(user.uid); throw e; }
  return { email, uid: user.uid, cid, pcId, password };
}
export async function resetPassword(cidArg, id) {
  const user = await userOf(cidArg, id);
  const password = randomPassword();
  await auth.updateUser(user.uid, { password });
  await auth.revokeRefreshTokens(user.uid);
  return { email: user.email, password, agent: user.customClaims?.role === "agent" };
}
export async function setDisabled(cidArg, id, disabled) {
  const user = await userOf(cidArg, id);
  await auth.updateUser(user.uid, { disabled });
  if (disabled) await auth.revokeRefreshTokens(user.uid);
  return { email: user.email, disabled };
}
export async function showUser(cidArg, id) {
  const u = await userOf(cidArg, id);
  return { uid: u.uid, email: u.email, claims: u.customClaims ?? {}, disabled: u.disabled,
    created: u.metadata.creationTime, lastSignIn: u.metadata.lastSignInTime, lastRefresh: u.metadata.lastRefreshTime };
}
export async function listAll(cid) {
  if (cid) checkKey("cid", cid);
  const companies = (await rtdb.ref("meta/companies").get()).val() ?? {};
  const users = (await usersOf(cid)).map((u) => {
    const c = u.customClaims ?? {};
    return { email: u.email, cid: c.cid ?? "-", stts: c.cid ? companies[c.cid]?.stts ?? 0 : "-", role: c.role ?? "-", pcId: c.pcId ?? "-",
      disabled: u.disabled, lastSignIn: u.metadata.lastSignInTime ?? "-" };
  });
  return { companies, users };
}
// 업체가 안 쓰는 모듈 - off = 화면에서 숨고 에이전트가 강제로 끔, on = 정책을 지움(그 업체가 쓴다)
export async function setModules(cid, patch) {
  checkKey("cid", cid);
  await companyOf(cid, { removed: true });
  const clean = {};
  for (const [k, v] of Object.entries(patch ?? {})) {
    if (!POLICY_KEYS.includes(k)) throw new Refused(`모듈 키는 ${POLICY_KEYS.join(", ")} 중 하나 (받은 값: ${k})`);
    if (v !== "on" && v !== "off") throw new Refused(`${k} 의 값은 on 또는 off (받은 값: ${v})`);
    clean[k] = v === "off" ? false : null;
  }
  const at = rtdb.ref(`meta/companies/${cid}/apps/rpa/modules`);
  await at.update(clean);
  return (await at.get()).val() ?? {};
}
// 삭제는 표시(stts=9)와 계정 막기뿐 - 메타·현황·명령·이력·통장은 남아 되살리면 그대로 돌아온다.
// 살아 있는 업체를 되살리면 아무것도 안 한다 (계정을 다 열면 따로 막아 둔 계정까지 열린다).
// ponytail: 되살림은 그 업체 계정을 전부 다시 연다 - 삭제 전에 따로 막아 둔 계정이 있었으면 다시 막을 것
export async function setCompanyRemoved(cid, removing) {
  checkKey("cid", cid);
  const v = await companyOf(cid, { removed: true });
  const was = v.stts === 9;
  if (!removing && !was) return { cid, name: v.name, already: true, users: [] };
  const users = await usersOf(cid);
  await rtdb.ref(`meta/companies/${cid}/stts`).set(removing ? 9 : 0);
  for (const u of users) {
    await auth.updateUser(u.uid, { disabled: removing });
    if (removing) await auth.revokeRefreshTokens(u.uid);
  }
  return { cid, name: v.name, already: removing && was, users: users.map((u) => u.email) };
}

// --- 토큰 (통장 wallet/{cid} = {granted, since} + grants 넣은 내역 - 업체는 못 본다) ---------------
// 남은 토큰 = granted - since 뒤에 시작한 기록의 cost 합 (agent.balance 와 같다). 통장이 생기면 그 업체는 0 이하에서 막힌다
export async function grantTokens(cid, amount, memo) {
  checkKey("cid", cid);
  await companyOf(cid);
  const text = String(amount ?? "").trim(), n = Number(text);
  if (!/^[+-]?\d+$/.test(text) || !Number.isSafeInteger(n) || n === 0) throw new Refused(`토큰 수는 +1000 이나 -50 처럼 0 이 아닌 정수 (받은 값: ${text})`);
  const wallet = store.doc(`wallet/${cid}`), at = nowKst();
  const created = await store.runTransaction(async (t) => {
    const cur = await t.get(wallet);
    t.set(wallet, cur.exists ? { granted: (cur.data().granted ?? 0) + n } : { granted: n, since: at }, { merge: true });
    t.create(wallet.collection("grants").doc(), { amount: n, at, memo: String(memo ?? "").trim() });
    return !cur.exists;
  });
  return { created, ...(await tokenStatus(cid)) };
}
export async function tokenStatus(cid) {
  checkKey("cid", cid);
  const v = await companyOf(cid, { removed: true });
  const wallet = store.doc(`wallet/${cid}`), w = (await wallet.get()).data();
  if (!w) return { cid, name: v.name, wallet: null };
  const spent = await spentSince(cid, w.since);
  const grants = (await wallet.collection("grants").orderBy("at", "desc").limit(10).get()).docs.map((d) => d.data());
  return { cid, name: v.name, wallet: { granted: w.granted, since: w.since, spent, left: w.granted - spent, grants } };
}
export async function getPrices() {
  return { ...PRICE_BASE, ...((await store.doc("meta/prices").get()).data() ?? {}) };
}
export async function setPrice(key, value) {
  checkKey("모듈 키", key);
  const text = String(value ?? "").trim();
  if (!/^\d+$/.test(text)) throw new Refused(`토큰 배율은 0 이상 정수 (받은 값: ${text})`);
  await store.doc("meta/prices").set({ [key]: Number(text) }, { merge: true });
  return getPrices();
}
// 우리 통계: 업체마다 남은 토큰 · 이번 달 쓴 토큰 (통장 시작이 이번 달이면 그때부터). 통장이 없어도 쓴 것은 센다
export async function usageRows(cid) {
  if (cid) checkKey("cid", cid);
  const companies = (await rtdb.ref("meta/companies").get()).val() ?? {};
  const month = `${nowKst().slice(0, 7)}-01T00:00:00`, rows = [];
  for (const [k, v] of Object.entries(companies)) {
    if (cid && k !== cid) continue;
    const w = (await store.doc(`wallet/${k}`).get()).data();
    rows.push({ cid: k, name: v.name ?? "-", stts: v.stts ?? 0, left: w ? w.granted - await spentSince(k, w.since) : null,
      month: await spentSince(k, w?.since > month ? w.since : month), since: w?.since ?? null });
  }
  return rows;
}
```

- [ ] **Step 4: `firebase/admin/setup.js` 다시 쓰기** (머리글 주석은 지금 것 + 맨 첫 줄과 price 줄만 바꾼다)

```js
// 회사·PC·사용자·에이전트·토큰을 다룬다. 우리 PC 에서만 돈다. 같은 일을 화면으로: 바탕화면 'AFTER MARKET 관리' (node admin.js)
//
//   node setup.js company  <cid> <회사 이름>
//   node setup.js pc       <cid> <pcId> <PC 이름>                  (company 먼저)
//   node setup.js user     <cid|-> <아이디|이메일> <super|admin|viewer> <이름>
//   node setup.js agent    <cid> <pcId>                            (pc 먼저)
//   node setup.js passwd   <cid|-> <아이디|이메일>                  새 비밀번호 발급, 옛 토큰 무효
//   node setup.js disable  <cid|-> <아이디|이메일>                  막기 (enable 로 다시 연다)
//   node setup.js enable   <cid|-> <아이디|이메일>
//   node setup.js show     <cid|-> <아이디|이메일>
//   node setup.js list     [cid]
//   node setup.js modules  <cid> Hold=off Output=on   (업체가 안 쓰는 모듈. off 면 화면에서 숨고 에이전트가 강제로 끈다)
//   node setup.js remove   <cid>                                   업체 삭제(비활성): stts=9, 그 업체 계정 전부 막음. 자료는 남는다
//   node setup.js restore  <cid>                                   되살림: stts=0, 계정 다시 엶
//   node setup.js tokens   <cid> [+1000|-50] [메모]                토큰 넣기·빼기 (처음 넣으면 통장을 만든다), 금액 없으면 보기
//   node setup.js price    [<모듈 키> <배율>]                       토큰 배율 보기·바꾸기 (예: price logistics 2)
//   node setup.js usage    [cid]                                   업체마다 남은 토큰·이번 달 쓴 토큰
//
// 업체 상태 stts: 0(또는 없음) 사용, 9 삭제(비활성). 삭제된 업체엔 pc·user·agent 를 못 만든다.
// 비밀번호는 명령줄로 받지 않는다. 무작위로 만들어 딱 한 번 찍고, 잃으면 passwd 로 다시 발급한다.
// 일은 ops.js 가 한다 (관리 화면과 같은 코드). 이메일 조립 규칙도 거기에.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

// 인수 개수 [최소, 최대]. 옛 꼴(user <이메일> <비밀번호> …, agent <이메일> <비밀번호> …)은 받지 않는다.
const ARGC = { company: [2], pc: [3], user: [4], agent: [2, 2], passwd: [2, 2], disable: [2, 2], enable: [2, 2], show: [2, 2], list: [0, 1], modules: [2], remove: [1, 1], restore: [1, 1],
  tokens: [1], price: [0, 2], usage: [0, 1] };

const [, , cmdName, ...rest] = process.argv;
const [min, max = Infinity] = ARGC[cmdName] ?? [];
if (!ARGC[cmdName] || rest.length < min || rest.length > max) {
  const src = readFileSync(fileURLToPath(import.meta.url), "utf8").split("\n");
  console.log(src.slice(1, src.findIndex((l) => !l.startsWith("//"))).join("\n"));
  process.exit(1);
}
const ops = await import("./ops.js");     // 인수를 본 뒤에 연다 - 도움말은 서비스 계정 키 없이도 나온다

try {
  if (cmdName === "company") {
    const r = await ops.addCompany(rest[0], rest.slice(1).join(" "));
    console.log(`회사 등록: ${r.cid}`);
    console.log(`  이 업체가 안 쓰는 모듈이 있으면: node setup.js modules ${r.cid} Hold=off`);
  } else if (cmdName === "pc") {
    const r = await ops.addPc(rest[0], rest[1], rest.slice(2).join(" "));
    console.log(`PC 등록: ${r.cid}/${r.pcId}`);
  } else if (cmdName === "user") {
    const r = await ops.addUser(rest[0], rest[1], rest[2], rest.slice(3).join(" "));
    console.log(`사용자 등록: ${r.email}  uid=${r.uid}  role=${r.role}  cid=${r.cid ?? "-"}`);
    console.log(`  비밀번호: ${r.password}   (다시 볼 수 없다. 잃으면 passwd)`);
  } else if (cmdName === "agent") {
    const r = await ops.addAgent(rest[0], rest[1]);
    console.log(`에이전트 등록: ${r.email}  uid=${r.uid}`);
    console.log(`  PC 에서 그대로 넣는다 →  회사 코드: ${r.cid}   PC 이름: ${r.pcId}   비밀번호: ${r.password}`);
    console.log(`  다시 볼 수 없다. 잃으면 passwd`);
  } else if (cmdName === "passwd") {
    const r = await ops.resetPassword(rest[0], rest[1]);
    console.log(`비밀번호 교체: ${r.email}`);
    console.log(`  비밀번호: ${r.password}   (다시 볼 수 없다. 잃으면 다시 passwd. 이미 받은 토큰은 최대 1시간 산다)`);
    if (r.agent) console.log(`  PC 에서 에이전트가 1시간 안에 멈추고 새 비밀번호를 묻는다`);
  } else if (cmdName === "disable" || cmdName === "enable") {
    const r = await ops.setDisabled(rest[0], rest[1], cmdName === "disable");
    console.log(r.disabled ? `막음: ${r.email}  (이미 받은 토큰은 최대 1시간 산다)` : `다시 엶: ${r.email}`);
  } else if (cmdName === "show") {
    console.log(await ops.showUser(rest[0], rest[1]));
  } else if (cmdName === "list") {
    const { companies, users } = await ops.listAll(rest[0]);
    if (!rest[0]) console.table(Object.entries(companies).map(([k, v]) => ({ cid: k, name: v.name ?? "-", stts: v.stts ?? 0, pcs: Object.keys(v.pcs ?? {}).join(" ") || "-" })));
    console.table(users);
  } else if (cmdName === "remove" || cmdName === "restore") {
    const removing = cmdName === "remove";
    const r = await ops.setCompanyRemoved(rest[0], removing);
    if (!removing && r.already) {
      console.log("이미 서비스중인 업체입니다.");
    } else {
      if (removing && r.already) console.log("이미 삭제된 업체입니다.");   // 그래도 다시 막았다 (중간에 멈췄거나 누가 enable 했을 때)
      console.log(removing
        ? `업체 삭제(비활성): ${r.cid} ${r.name}  stts=9, 계정 ${r.users.length}개 막음 (이미 받은 토큰은 최대 1시간 산다. 에이전트는 그 안에 멈춘다)`
        : `업체 되살림: ${r.cid} ${r.name}  stts=0, 계정 ${r.users.length}개 다시 엶`);
      for (const e of r.users) console.log(`  ${e}`);
    }
  } else if (cmdName === "modules") {
    const [cid, ...pairs] = rest;
    const p = await ops.setModules(cid, Object.fromEntries(pairs.map((x) => x.split("="))));
    console.log(`모듈 정책: ${cid}`, Object.keys(p).length ? p : "(없음 - 전부 사용)");
  } else if (cmdName === "tokens") {
    const [cid, amount, ...memoParts] = rest;
    const s = amount === undefined ? await ops.tokenStatus(cid) : await ops.grantTokens(cid, amount, memoParts.join(" "));
    if (s.created) console.log(`통장을 만들었습니다: ${s.cid} ${s.name} - 지금부터 남은 토큰이 0 이하면 실행이 막힙니다 (그 전에 쓴 것은 안 뺀다)`);
    if (!s.wallet) {
      console.log(`${s.cid} ${s.name} 는 통장이 없다 (토큰 제도 밖 - 세기만 한다). 넣으려면: node setup.js tokens ${s.cid} +1000 "메모"`);
    } else {
      const w = s.wallet;
      console.log(`토큰: ${s.cid} ${s.name}  넣은 합계 ${w.granted} · 쓴 ${w.spent} · 남은 ${w.left}  (${w.since} 부터)`);
      console.table(w.grants.map((g) => ({ 언제: g.at, 얼마: g.amount, 메모: g.memo || "-" })));
    }
  } else if (cmdName === "price") {
    const t = rest.length ? await ops.setPrice(rest[0], rest[1]) : await ops.getPrices();
    console.log("토큰 배율 (모듈을 한 번 쓸 때 빠지는 토큰 - 여기 없는 모듈은 default):", t);
  } else if (cmdName === "usage") {
    console.table((await ops.usageRows(rest[0])).map((r) => ({ cid: r.cid, 이름: r.name, 남은: r.left ?? "-", 이번달: r.month, 통장: r.since ? `${r.since} 부터` : "없음" })));
  }
} catch (e) {
  if (!(e instanceof ops.Refused)) throw e;
  console.error(`오류: ${e.message}`);
  process.exit(1);
}
process.exit(0);
```

- [ ] **Step 5: 통과 확인** - Step 2 와 같은 명령. Expected: `42/42 통과`.

- [ ] **Step 6: 커밋은 사용자에게 묻는다.**

---

### Task 2: 관리 화면 서버 admin.js + ops.js 의 화면용 함수

**Files:**
- Create: `firebase/admin/admin.js`
- Modify: `firebase/admin/ops.js` (끝에 화면용 함수 더하기)
- Create (빈 화면 자리): `firebase/admin/AFTERMARKET_SETUP.html` - 이 task 에서는 `<!doctype html><title>AFTER MARKET 관리</title>` 한 줄 (Task 3 에서 채운다)
- Test: `firebase/tests/check_admin.py` (1~3절 - API)

**Interfaces:**
- Consumes: Task 1 의 ops.js 전부.
- Produces (ops.js): `companyTable() → [{cid, name, stts, left, month, since, pcs, users, lastSignIn}]`,
  `companyDetail(cid) → {cid, name, stts, pcs: [{pcId, label}], users: [{email, id, role, pcId, disabled, lastSignIn}], modules, tokens: wallet|null}`,
  `setupCompany(plan) → {ok, steps: [{label, ok, note}], made: {users: [{email, uid, role, cid, password, id}], agents: [{email, uid, cid, pcId, password, label}]}}`
  - plan = `{cid, name, pcs: [{pcId, label}], users: [{id, name, role: "admin"|"viewer"}], hold: true|false, tokens: {amount, memo} | null}`
- Produces (HTTP, 모두 JSON, 실패는 `{error}` - 400 거절 / 403 보안 / 404 / 500):
  `GET /api/info → {emulator, project, dashboard}`, `GET /api/companies`, `GET /api/companies/:cid`, `POST /api/setup (plan)`,
  `POST /api/companies/:cid/pcs {pcId, label, agent} → {pc, agent|null}`, `POST /api/companies/:cid/users {id, role, name}`,
  `POST /api/companies/:cid/passwd {id}`, `POST /api/companies/:cid/disabled {id, disabled}`, `POST /api/companies/:cid/modules {Key: on|off}`,
  `POST /api/companies/:cid/remove {confirm}`, `POST /api/companies/:cid/restore {}`, `POST /api/companies/:cid/tokens {amount, memo}`,
  `GET /api/prices`, `POST /api/prices {key, value}`, `GET /api/usage`, `POST /api/quit`
- 계정 `id` 는 이메일 전체를 보내도 된다 (emailFor 가 @ 가 있으면 그대로).

- [ ] **Step 1: 실패할 시험 쓰기** - `firebase/tests/check_admin.py`

```python
"""관리 화면(AFTERMARKET_SETUP) 시험 - admin.js 를 에뮬레이터에 붙여 API 와 화면을 본다. 실제 프로젝트는 안 건드린다.

    cd D:\\AX\\RPA\\firebase; . .\\emu_env.ps1; cd tests
    firebase emulators:exec --config ../firebase.json --only auth,database,firestore --project rpa-test-f02e0 "D:\\AX\\RPA\\.venv\\Scripts\\python.exe check_admin.py"

만드는 계정은 에뮬레이터 것이라도 비밀번호를 찍지 않는다 (길이만 보고, 실패 글에서도 가린다).
"""
import json
import os
import re
import subprocess
import sys
import threading
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
PROJECT = "rpa-test-f02e0"
DB = "http://127.0.0.1:9000"
NS = f"{PROJECT}-default-rtdb"
AUTH = "http://127.0.0.1:9099"
FS = f"http://127.0.0.1:8080/v1/projects/{PROJECT}/databases/(default)/documents"
OWNER = {"Authorization": "Bearer owner"}
ADMIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "admin")
LOG = os.path.join(ADMIN, "관리_기록.txt")
FAIL, SECRETS = [], []
COUNT = 0
for k in ("FIREBASE_AUTH_EMULATOR_HOST", "FIREBASE_DATABASE_EMULATOR_HOST", "FIRESTORE_EMULATOR_HOST"):
    if not os.environ.get(k):
        sys.exit(f"{k} 가 없다. emulators:exec 안에서 돌릴 것")


def mask(text):
    text = str(text)
    for s in SECRETS:
        if s:
            text = text.replace(s, "****")
    return re.sub(r"('password': ')[^']+", r"\1****", re.sub(r'("password": ")[^"]+', r"\1****", text))


def check(ok, label, detail=""):
    global COUNT
    COUNT += 1
    print(f"  {'통과' if ok else '실패'}  {label}" + (f"  {mask(detail)}" if detail and not ok else ""))
    if not ok:
        FAIL.append(label)


def call(method, url, body=None, headers=None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read().decode("utf-8")
        return json.loads(raw) if raw else None


def db_get(path):
    return call("GET", f"{DB}/{path}.json?ns={NS}", None, OWNER)


def account(email_):
    r = call("POST", f"{AUTH}/identitytoolkit.googleapis.com/v1/projects/{PROJECT}/accounts:lookup", {"email": [email_]}, OWNER)
    return (r or {}).get("users", [None])[0] or {}


def claims(email_):
    return json.loads(account(email_).get("customAttributes") or "{}")


def fs_doc(path):
    try:
        d = call("GET", f"{FS}/{path}", None, OWNER)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    return {k: int(v["integerValue"]) if "integerValue" in v else v.get("stringValue") for k, v in (d.get("fields") or {}).items()}


def email(cid, local):
    return f"{local.replace('_', '-')}@{cid.replace('_', '-')}.{PROJECT}.firebaseapp.com"


# --- 서버 켜기 (브라우저 없이) ---
log_start = os.path.getsize(LOG) if os.path.exists(LOG) else 0
srv = subprocess.Popen(["node", "admin.js", "--no-open"], cwd=ADMIN, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       text=True, encoding="utf-8", errors="replace")
url = port = key = None
for line in srv.stdout:
    m = re.search(r"http://127\.0\.0\.1:(\d+)/\?k=([\w-]+)", line)
    if m:
        url, port, key = m.group(0), m.group(1), m.group(2)
        break
out_lines = []
threading.Thread(target=lambda: out_lines.extend(srv.stdout), daemon=True).start()   # 서버 출력을 계속 비운다 (막히지 않게)
BASE = f"http://127.0.0.1:{port}"


def api(method, path, body=None, k=None, host=None):
    headers = {"X-Admin-Key": key if k is None else k}
    if host:
        headers["Host"] = host
    try:
        return 200, call(method, BASE + path, body, headers)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or "{}")


print("=== 1. 켜기와 보안 ===")
check(url is not None, "브라우저 없이 켜면 주소(비밀 값 포함)를 찍는다")
code, r = api("GET", "/api/info", k="")
check(code == 403 and "비밀 값" in r.get("error", ""), "비밀 값 없이 /api 를 부르면 거절", (code, r))
code, r = api("GET", "/api/info", k="x" * len(key or ""))
check(code == 403, "비밀 값이 틀려도 거절", code)
code, r = api("GET", "/api/info", host=f"localhost:{port}")
check(code == 403 and "127.0.0.1" in r.get("error", ""), "Host 가 127.0.0.1:<포트> 가 아니면 거절 (주소 이름 위조)", (code, r))
page_html = urllib.request.urlopen(BASE + "/", timeout=30).read().decode("utf-8")
check("AFTER MARKET 관리" in page_html and (key or "?") not in page_html, "화면 파일은 비밀 값 없이 내려주고, 그 안에 비밀 값이 없다")
code, r = api("GET", "/api/info")
check(code == 200 and r == {"emulator": True, "project": PROJECT, "dashboard": f"https://{PROJECT}.web.app"}, "에뮬레이터에 붙었다고 알린다", r)

print("=== 2. 신규 업체 (한 흐름) ===")
PLAN = {"cid": "t_new", "name": "<img src=x onerror=alert(1)> 새 업체", "hold": False,
        "pcs": [{"pcId": "pc_a", "label": "사무실 PC"}, {"pcId": "pc_b", "label": "창고 PC"}],
        "users": [{"id": "boss", "name": "대표", "role": "admin"}, {"id": "staff", "name": "직원", "role": "viewer"}],
        "tokens": {"amount": "+500", "memo": "첫 결제"}}
for bad, why in ((dict(PLAN, cid="Net-1"), "업체코드"), ({k: v for k, v in PLAN.items() if k != "hold"}, "물류대기"),
                 (dict(PLAN, pcs=[]), "PC"), (dict(PLAN, users=[{"id": "v", "role": "viewer"}]), "관리자"),
                 (dict(PLAN, tokens={"amount": "1,000"}), "첫 토큰")):
    code, r = api("POST", "/api/setup", bad)
    check(code == 400 and why in r.get("error", ""), f"잘못된 내용은 만들기 전에 거절: {why}", (code, r))
check(db_get("meta/companies/t_new") is None, "거절된 내용으로는 아무것도 안 만든다")
code, r = api("POST", "/api/setup", PLAN)
made = r.get("made", {}) if code == 200 else {}
SECRETS += [u.get("password", "") for u in made.get("users", [])] + [a.get("password", "") for a in made.get("agents", [])]
check(code == 200 and r["ok"] and len(r["steps"]) == 9 and all(s["ok"] for s in r["steps"]),
      "다 만들었다 (업체·PC 2·계정 2·기계 계정 2·물류대기·첫 토큰 = 9 줄)", (code, r.get("steps")))
check({u["id"] for u in made.get("users", [])} == {"boss", "staff"} and {a["pcId"] for a in made.get("agents", [])} == {"pc_a", "pc_b"}
      and len(SECRETS) == 4 and all(len(s) == 24 for s in SECRETS), "만든 계정의 비밀번호를 한 번 돌려준다 (24자)")
check(claims(email("t_new", "boss")) == {"cid": "t_new", "role": "admin"} and claims(email("t_new", "staff")) == {"cid": "t_new", "role": "viewer"}
      and claims(email("t_new", "agent-pc_a")) == {"cid": "t_new", "pcId": "pc_a", "role": "agent"}, "계정·권한(claim)이 실제로 생겼다")
meta = db_get("meta/companies/t_new") or {}
check(meta.get("name") == PLAN["name"] and set(meta.get("pcs", {})) == {"pc_a", "pc_b"}
      and meta.get("apps", {}).get("rpa", {}).get("modules") == {"Hold": False}, "업체·PC·물류대기 끔 (모듈 정책)", meta)
w = fs_doc("wallet/t_new") or {}
check(w.get("granted") == 500 and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d", w.get("since") or ""), "첫 토큰 500 - 통장과 시작 시각", w)

TWICE = dict(PLAN, cid="t_twice", name="두번", pcs=[{"pcId": "pc_1", "label": "PC"}], users=[{"id": "boss", "role": "admin"}],
             tokens={"amount": "100"})
results = [None, None]
threads = [threading.Thread(target=lambda i=i: results.__setitem__(i, api("POST", "/api/setup", TWICE))) for i in (0, 1)]
for t in threads:
    t.start()
for t in threads:
    t.join()
for _, res in results:
    SECRETS += [u["password"] for u in res.get("made", {}).get("users", [])] + [a["password"] for a in res.get("made", {}).get("agents", [])]
w = fs_doc("wallet/t_twice") or {}
check(all(c == 200 for c, _ in results) and w.get("granted") == 100, f"동시에 두 번 눌러도 토큰은 한 번만 ({w.get('granted')})")
late = [res for _, res in results if not res.get("made", {}).get("users")]
check(len(late) == 1 and any("이미 있어 건너뜀" in s["note"] for s in late[0]["steps"])
      and any("이미 통장이 있어" in s["note"] for s in late[0]["steps"]), "늦은 쪽은 이미 있는 계정·통장을 건너뛴다", late)

subprocess.run(["node", "setup.js", "company", "t_retry", "다시"], cwd=ADMIN, capture_output=True, timeout=60)
code, r = api("POST", "/api/companies/t_retry/users", {"id": "boss", "role": "admin", "name": "먼저"})
SECRETS.append(r.get("password", ""))
code, r = api("POST", "/api/setup", dict(TWICE, cid="t_retry", name="다시", tokens=None))
SECRETS += [a["password"] for a in r.get("made", {}).get("agents", [])]
check(code == 200 and r["ok"] and not r["made"]["users"] and [a["pcId"] for a in r["made"]["agents"]] == ["pc_1"]
      and any("boss" in s["label"] and "재발급" in s["note"] for s in r["steps"]), "다시 누르면 남은 것만 (이미 있는 계정은 건너뛰고 재발급 안내)", r.get("steps"))
check(fs_doc("wallet/t_retry") is None, "첫 토큰을 '나중에' 로 하면 통장 없이 (세기만)")

print("=== 3. 업체 표·상세 ===")
code, rows = api("GET", "/api/companies")
row = next((x for x in rows if x["cid"] == "t_new"), {}) if code == 200 else {}
check(row.get("pcs") == 2 and row.get("users") == 4 and row.get("left") == 500 and row.get("month") == 0 and row.get("stts") == 0,
      "업체 표: PC 2 · 계정 4 · 남은 500 · 이번 달 0", row)
code, d = api("GET", "/api/companies/t_new")
check(code == 200 and {u["role"] for u in d["users"]} == {"admin", "viewer", "agent"} and d["modules"] == {"Hold": False}
      and d["tokens"]["granted"] == 500 and d["tokens"]["grants"][0]["memo"] == "첫 결제", "상세: 계정·역할·모듈·통장·넣은 내역", str(d)[:300])
code, r = api("POST", "/api/companies/t_new/tokens", {"amount": "+100", "memo": "추가"})
check(code == 200 and r["wallet"]["left"] == 600 and not r["created"], "토큰 더 넣기 → 남은 600", str(r)[:200])
code, r = api("POST", "/api/companies/t_new/tokens", {"amount": "1,000"})
check(code == 400 and "0 이 아닌 정수" in r.get("error", ""), "토큰 수 '1,000' 은 거절 (쉼표)", r)
boss = email("t_new", "boss")
code, r = api("POST", "/api/companies/t_new/passwd", {"id": boss})
SECRETS.append(r.get("password", ""))
check(code == 200 and len(r.get("password", "")) == 24 and r.get("email") == boss, "비밀번호 재발급 (새 값을 한 번 돌려준다)")
code, r = api("POST", "/api/companies/t_new/disabled", {"id": boss, "disabled": True})
check(code == 200 and account(boss).get("disabled") is True, "계정 막기")
code, r = api("POST", "/api/companies/t_new/disabled", {"id": boss, "disabled": False})
check(code == 200 and account(boss).get("disabled") is not True, "계정 다시 열기")
code, r = api("POST", "/api/companies/t_new/modules", {"Hold": "on"})
check(code == 200 and (db_get("meta/companies/t_new/apps/rpa/modules") or {}) == {}, "모듈 정책 켜기 (정책을 지운다 = 그 업체가 쓴다)")
code, r = api("POST", "/api/companies/t_new/remove", {"confirm": "t_ne"})
check(code == 400 and db_get("meta/companies/t_new/stts") == 0, "업체코드를 똑같이 안 치면 삭제하지 않는다", (code, r))
code, r = api("POST", "/api/companies/t_new/remove", {"confirm": "t_new"})
check(code == 200 and db_get("meta/companies/t_new/stts") == 9 and account(boss).get("disabled") is True, "업체 삭제: stts 9, 계정 막힘")
code, r = api("POST", "/api/companies/t_new/restore", {})
check(code == 200 and db_get("meta/companies/t_new/stts") == 0 and account(boss).get("disabled") is not True, "되살림")
code, r = api("POST", "/api/prices", {"key": "logistics", "value": "3"})
check(code == 200 and r.get("logistics") == 3 and r.get("login") == 0, "토큰 배율 바꾸기", r)
code, r = api("POST", "/api/prices", {"key": "logistics", "value": "-1"})
check(code == 400 and "토큰 배율" in r.get("error", ""), "토큰 배율 음수는 거절", r)
code, rows = api("GET", "/api/usage")
check(code == 200 and any(x["cid"] == "t_new" and x["left"] == 600 for x in rows), "통계: 업체마다 남은 토큰", str(rows)[:200])
code, r = api("GET", "/api/companies/Bad")
check(code == 404, "업체코드 꼴이 아닌 주소는 없는 요청", code)

# (Task 3 이 여기에 '=== 4. 화면' 을 넣는다)

print("=== 5. 기록 ===")
if srv.poll() is None:
    code, r = api("POST", "/api/quit")
    srv.wait(timeout=15)
text = open(LOG, "rb").read()[log_start:].decode("utf-8") if os.path.exists(LOG) else ""
check("신규 업체 t_new" in text and "토큰 +100 t_new 추가" in text and "비밀번호 재발급 t_new" in text and "업체 삭제 t_new" in text,
      "관리_기록.txt 에 한 일이 한 줄씩", text[-400:])
check(SECRETS and all(SECRETS) and not any(s in text for s in SECRETS) and not any(s in "".join(out_lines) for s in SECRETS),
      "기록 파일·서버 출력 어디에도 비밀번호가 없다")
check(srv.returncode == 0, "[끄기](/api/quit) 로 서버가 끝난다", srv.returncode)
if srv.poll() is None:
    srv.kill()
print(f"\n{COUNT - len(FAIL)}/{COUNT} 통과")
if FAIL:
    print("실패:", ", ".join(FAIL))
    sys.exit(1)
```

- [ ] **Step 2: 실패 확인**

Run: `… emulators:exec … "D:\AX\RPA\.venv\Scripts\python.exe check_admin.py"` (Task 1 Step 2 와 같은 꼴, 파일만 check_admin.py)
Expected: admin.js 가 없어 주소를 못 찍는다 → 1절부터 실패.

- [ ] **Step 3: ops.js 끝에 화면용 함수 더하기**

```js
// --- 관리 화면 (AFTERMARKET_SETUP) ---------------------------------------------
const signedIn = (u) => (u.metadata.lastSignInTime ? new Date(u.metadata.lastSignInTime).toISOString() : null);
export async function companyTable() {
  const [rows, users] = await Promise.all([usageRows(), usersOf()]);
  const companies = (await rtdb.ref("meta/companies").get()).val() ?? {};
  return rows.map((r) => {
    const mine = users.filter((u) => u.customClaims?.cid === r.cid);
    return { ...r, pcs: Object.keys(companies[r.cid]?.pcs ?? {}).length, users: mine.length,
      lastSignIn: mine.map(signedIn).filter(Boolean).sort().at(-1) ?? null };
  });
}
export async function companyDetail(cid) {
  checkKey("cid", cid);
  const v = await companyOf(cid, { removed: true });
  const users = (await usersOf(cid)).map((u) => ({ email: u.email, id: u.email.split("@")[0], role: u.customClaims?.role ?? "-",
    pcId: u.customClaims?.pcId ?? null, disabled: u.disabled, lastSignIn: signedIn(u) }));
  return { cid, name: v.name, stts: v.stts ?? 0, pcs: Object.entries(v.pcs ?? {}).map(([pcId, p]) => ({ pcId, label: p.label ?? "" })),
    users, modules: v.apps?.rpa?.modules ?? {}, tokens: (await tokenStatus(cid)).wallet };
}
// 신규 업체 한 흐름 (설계 4-2). 먼저 내용을 다 본 뒤(틀리면 아무것도 안 만든다) 차례로 하고 첫 실패에서 멈춘다.
// 이미 있는 업체·PC 는 그대로 쓰고, 이미 있는 계정은 건너뛰고, 통장이 이미 있으면 첫 토큰은 건너뛴다 - 다시 누르면 남은 것만
function checkPlan(plan) {
  if (!plan || typeof plan !== "object") throw new Refused("신규 업체 내용이 비었습니다");
  checkKey("업체코드", plan.cid);
  if (!String(plan.name ?? "").trim()) throw new Refused("업체 이름을 넣으세요");
  const pcs = plan.pcs ?? [], users = plan.users ?? [];
  if (!pcs.length) throw new Refused("PC 를 하나 이상 넣으세요");
  for (const p of pcs) checkKey("PC코드", p.pcId);
  if (new Set(pcs.map((p) => p.pcId)).size !== pcs.length) throw new Refused("PC코드가 겹칩니다");
  if (!users.some((u) => u.role === "admin")) throw new Refused("관리자 계정을 넣으세요");
  for (const u of users) {
    if (u.role !== "admin" && u.role !== "viewer") throw new Refused("계정 역할은 관리자나 열람자");
    if (!String(u.id ?? "").trim()) throw new Refused("계정 아이디를 넣으세요");
  }
  if (new Set(users.map((u) => String(u.id).trim())).size !== users.length) throw new Refused("계정 아이디가 겹칩니다");
  if (typeof plan.hold !== "boolean") throw new Refused("물류대기 관리를 쓰는지 골라 주세요 (업체마다 다릅니다)");
  if (plan.tokens) {
    const a = String(plan.tokens.amount ?? "").trim();
    if (!/^\+?\d+$/.test(a) || Number(a) <= 0) throw new Refused(`첫 토큰은 1 이상 정수 (받은 값: ${a})`);
  }
}
export async function setupCompany(plan) {
  checkPlan(plan);
  const { cid } = plan, steps = [], made = { users: [], agents: [] };
  const step = async (label, fn) => {
    try {
      steps.push({ label, ok: true, note: (await fn()) ?? "" });
      return true;
    } catch (e) {
      steps.push({ label, ok: false, note: e instanceof Refused ? e.message : `${e.code ?? e.name}: ${e.message}` });
      return false;
    }
  };
  const skipExisting = async (fn) => {
    try {
      await fn();
      return "";
    } catch (e) {
      if (e instanceof Refused && e.message.includes("이미 있다")) return "이미 있어 건너뜀 - 비밀번호를 모르면 재발급";
      throw e;
    }
  };
  const each = async (items, fn) => { for (const x of items) if (!await fn(x)) return false; return true; };
  const ok = await step(`업체 ${cid} ${String(plan.name).trim()}`, async () => { await addCompany(cid, plan.name); })
    && await each(plan.pcs, (p) => step(`PC ${p.pcId} ${p.label ?? ""}`.trim(), async () => { await addPc(cid, p.pcId, p.label); }))
    && await each(plan.users, (u) => step(`${u.role === "viewer" ? "열람자" : "관리자"} 계정 ${String(u.id).trim()}`,
      () => skipExisting(async () => { made.users.push({ ...(await addUser(cid, String(u.id).trim(), u.role, u.name)), id: String(u.id).trim() }); })))
    && await each(plan.pcs, (p) => step(`기계 계정 ${p.pcId}`,
      () => skipExisting(async () => { made.agents.push({ ...(await addAgent(cid, p.pcId)), label: p.label ?? "" }); })))
    && await step(`물류대기 관리 ${plan.hold ? "씀" : "안 씀"}`, async () => { await setModules(cid, { Hold: plan.hold ? "on" : "off" }); });
  if (ok && plan.tokens) {
    await step(`첫 토큰 ${Number(String(plan.tokens.amount).trim())}개`, async () => {
      if ((await store.doc(`wallet/${cid}`).get()).exists) return "이미 통장이 있어 건너뜀";
      await grantTokens(cid, plan.tokens.amount, plan.tokens.memo);
    });
  }
  return { ok: steps.every((s) => s.ok), steps, made };
}
```

- [ ] **Step 4: `firebase/admin/admin.js` 만들기**

```js
// 관리 화면 서버 (AFTERMARKET_SETUP) - setup.js 와 같은 일을 화면으로 (같은 ops.js). 우리 PC 에서만 돈다:
// 127.0.0.1 에서만 듣고, 켤 때마다 새 비밀 값을 만들어 연 주소(?k=)에만 싣는다. 화면은 /api 요청마다 X-Admin-Key 로 그 값을 보낸다 -
// 다른 사이트는 값을 모르고 다른 출처에서는 맞춤 머리글을 못 보낸다 (CORS 를 안 연다). Host 가 127.0.0.1:<포트> 가 아니면 거절.
// 비밀번호는 만든 응답에만 싣고 콘솔·기록에는 안 남긴다. 한 일은 관리_기록.txt 에 한 줄씩 (비밀번호 없이). 고치는 요청은 하나씩.
//   node admin.js               켜고 기본 브라우저로 연다 (AFTERMARKET_SETUP.bat 이 부른다)
//   node admin.js --no-open     브라우저 없이 주소만 찍는다 (시험)
//   node admin.js --port 8790   포트를 정한다 (없으면 빈 포트)
//   node admin.js --shortcut    바탕화면에 'AFTER MARKET 관리' 바로 가기를 만든다 (한 번)
import http from "node:http";
import { randomBytes, timingSafeEqual } from "node:crypto";
import { readFileSync, appendFileSync } from "node:fs";
import { execFileSync, spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

const here = (name) => fileURLToPath(new URL(name, import.meta.url));
const args = process.argv.slice(2);

if (args.includes("--shortcut")) {
  const q = (s) => `'${s.replaceAll("'", "''")}'`;       // PowerShell 작은따옴표 글
  execFileSync("powershell", ["-NoProfile", "-Command", [
    "$w = New-Object -ComObject WScript.Shell",
    `$l = $w.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) ${q("AFTER MARKET 관리.lnk")}))`,
    `$l.TargetPath = ${q(here("./AFTERMARKET_SETUP.bat"))}`,
    `$l.WorkingDirectory = ${q(here("./"))}`,
    `$l.IconLocation = ${q(here("../../release/AFTER_MARKET.ico"))}`,
    "$l.Save()"].join("; ")], { stdio: "inherit" });
  console.log("바탕화면에 'AFTER MARKET 관리' 바로 가기를 만들었습니다");
  process.exit(0);
}

const ops = await import("./ops.js");
const KEY = Buffer.from(randomBytes(32).toString("base64url"));
const PAGE = readFileSync(here("./AFTERMARKET_SETUP.html"));
const LOG = here("./관리_기록.txt");
const log = (line) => { try { appendFileSync(LOG, `${ops.nowKst()}  ${line}\n`, "utf8"); } catch { /* 기록은 일을 막지 않는다 */ } };

// [메서드, 경로, 할 일(body, params), 기록 글(body, 결과, params) - 없거나 null 이면 안 남긴다]. 비밀번호는 기록 글에 절대 넣지 않는다
const ROUTES = [
  ["GET", "/api/info", () => ({ emulator: ops.onEmulator(), project: ops.PROJECT, dashboard: ops.DASHBOARD_URL })],
  ["GET", "/api/companies", () => ops.companyTable()],
  ["GET", "/api/companies/:cid", (b, p) => ops.companyDetail(p.cid)],
  ["POST", "/api/setup", (b) => ops.setupCompany(b),
    (b, r) => `신규 업체 ${b.cid}: ${r.steps.map((s) => `${s.ok ? "✓" : "✗"} ${s.label}`).join(", ")}`],
  ["POST", "/api/companies/:cid/pcs", async (b, p) => {
    const pc = await ops.addPc(p.cid, b.pcId, b.label);
    return { pc, agent: b.agent ? await ops.addAgent(p.cid, b.pcId) : null };
  }, (b, r, p) => `PC 더하기 ${p.cid}/${r.pc.pcId}${r.agent ? " + 기계 계정" : ""}`],
  ["POST", "/api/companies/:cid/users", (b, p) => ops.addUser(p.cid, b.id, b.role, b.name), (b, r, p) => `사용자 더하기 ${p.cid} ${r.email} (${r.role})`],
  ["POST", "/api/companies/:cid/passwd", (b, p) => ops.resetPassword(p.cid, b.id), (b, r, p) => `비밀번호 재발급 ${p.cid} ${r.email}`],
  ["POST", "/api/companies/:cid/disabled", (b, p) => ops.setDisabled(p.cid, b.id, b.disabled === true),
    (b, r, p) => `${r.disabled ? "막기" : "열기"} ${p.cid} ${r.email}`],
  ["POST", "/api/companies/:cid/modules", (b, p) => ops.setModules(p.cid, b),
    (b, r, p) => `모듈 정책 ${p.cid} ${Object.entries(b).map(([k, v]) => `${k}=${v}`).join(" ")}`],
  ["POST", "/api/companies/:cid/remove", (b, p) => {
    if (b.confirm !== p.cid) throw new ops.Refused("업체코드를 똑같이 쳐야 삭제합니다");
    return ops.setCompanyRemoved(p.cid, true);
  }, (b, r, p) => `업체 삭제 ${p.cid} (계정 ${r.users.length}개 막음)`],
  ["POST", "/api/companies/:cid/restore", (b, p) => ops.setCompanyRemoved(p.cid, false), (b, r, p) => (r.already ? null : `업체 되살림 ${p.cid}`)],
  ["POST", "/api/companies/:cid/tokens", (b, p) => ops.grantTokens(p.cid, b.amount, b.memo), (b, r, p) => `토큰 ${b.amount} ${p.cid} ${b.memo ?? ""}`.trim()],
  ["GET", "/api/prices", () => ops.getPrices()],
  ["POST", "/api/prices", (b) => ops.setPrice(b.key, b.value), (b) => `토큰 배율 ${b.key} = ${b.value}`],
  ["GET", "/api/usage", () => ops.usageRows()],
].map(([method, pattern, run, note]) => {
  const names = [];
  const re = new RegExp(`^${pattern.replace(/:(\w+)/g, (_, n) => { names.push(n); return "([a-z0-9_]+)"; })}$`);
  return { method, re, names, run, note };
});

// 고치는 요청은 한 번에 하나씩 - [만들기] 를 두 번 눌러도 두 번 만들지 않게 (늦은 쪽은 이미 있는 것을 건너뛴다)
let chain = Promise.resolve();
const serial = (fn) => { const run = chain.then(fn); chain = run.catch(() => {}); return run; };

function readJson(req) {
  return new Promise((ok, fail) => {
    const chunks = [];
    let size = 0;
    req.on("data", (c) => {
      size += c.length;
      if (size > 65536) { fail(new ops.Refused("요청이 너무 큽니다")); req.destroy(); } else chunks.push(c);
    });
    req.on("end", () => {
      try { ok(chunks.length ? JSON.parse(Buffer.concat(chunks).toString("utf8")) : {}); } catch { fail(new ops.Refused("요청 형식이 잘못되었습니다")); }
    });
    req.on("error", fail);
  });
}

let port = 0;
async function handle(req, res) {
  const send = (code, body, type = "application/json; charset=utf-8") => {
    res.writeHead(code, { "Content-Type": type, "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
      "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY" });
    res.end(Buffer.isBuffer(body) ? body : JSON.stringify(body));
  };
  if (req.headers.host !== `127.0.0.1:${port}`) return send(403, { error: "이 PC 의 관리 화면 주소(127.0.0.1)로만 엽니다" });
  const path = new URL(req.url, "http://127.0.0.1").pathname;
  if (!path.startsWith("/api/")) return path === "/" && req.method === "GET" ? send(200, PAGE, "text/html; charset=utf-8") : send(404, { error: "없는 주소입니다" });
  const got = Buffer.from(String(req.headers["x-admin-key"] ?? ""));
  if (got.length !== KEY.length || !timingSafeEqual(got, KEY)) {
    return send(403, { error: "비밀 값이 맞지 않습니다 - 관리 화면을 다시 켜세요 (바탕화면 'AFTER MARKET 관리')" });
  }
  if (req.method === "POST" && path === "/api/quit") {
    log("관리 화면 끔");
    send(200, { ok: true });
    setTimeout(() => process.exit(0), 200);
    return;
  }
  const route = ROUTES.find((r) => r.method === req.method && r.re.test(path));
  if (!route) return send(404, { error: "모르는 요청입니다" });
  const hit = path.match(route.re), params = Object.fromEntries(route.names.map((n, i) => [n, hit[i + 1]]));
  try {
    const body = req.method === "POST" ? await readJson(req) : {};
    const work = () => route.run(body, params);
    const result = await (req.method === "POST" ? serial(work) : work());
    const line = route.note?.(body, result, params);
    if (line) log(line);
    send(200, result);
  } catch (e) {
    if (e instanceof ops.Refused) return send(400, { error: e.message });
    console.error(e);
    send(500, { error: `뜻밖의 오류 - ${e.code ?? e.name}: ${e.message}` });
  }
}

const at = args.indexOf("--port");
const server = http.createServer(handle);
server.on("error", (e) => { console.error(`오류: 관리 화면을 켜지 못했습니다 (${e.code}) - 이미 켜져 있으면 그 창을 쓰세요`); process.exit(1); });
server.listen(at >= 0 ? Number(args[at + 1]) || 0 : 0, "127.0.0.1", () => {
  port = server.address().port;
  const url = `http://127.0.0.1:${port}/?k=${KEY}`;
  const where = ops.onEmulator() ? "에뮬레이터 (시험)" : `실제 서버 (${ops.PROJECT})`;
  console.log(`AFTER MARKET 관리 화면 - ${where}`);
  console.log(`  ${url}`);
  console.log("  브라우저가 안 열리면 위 주소를 여세요. 끄려면 화면의 [끄기] 를 누르거나 이 창을 닫으세요");
  log(`관리 화면 켬 - ${where}`);
  if (!args.includes("--no-open")) spawn("rundll32", ["url.dll,FileProtocolHandler", url], { detached: true, stdio: "ignore" }).unref();
});
```

- [ ] **Step 5: 빈 화면 자리** - `firebase/admin/AFTERMARKET_SETUP.html` 에 `<!doctype html><title>AFTER MARKET 관리</title>` 한 줄 (1절의 '화면 파일' 시험용, Task 3 에서 채운다).

- [ ] **Step 6: 통과 확인** - Expected: 1~3절·5절 모두 통과 (`N/N 통과`). check_setup.py 도 다시 돌려 42/42.

- [ ] **Step 7: 커밋은 사용자에게 묻는다.**

---

### Task 3: 화면 AFTERMARKET_SETUP.html

**Files:**
- Modify: `firebase/admin/AFTERMARKET_SETUP.html` (전부)
- Test: `firebase/tests/check_admin.py` (4절 - Playwright)

**Interfaces:**
- Consumes: Task 2 의 HTTP API (위 표).
- Produces (시험이 쓰는 이름): `#badge`, `nav button[data-view=companies|setup|rates]`, `#quit`, `#companies` (tbody, 줄마다 `data-cid`,
  칸 차례 업체코드·이름·상태·PC·계정·남은 토큰·이번 달·마지막 로그인), `#detail`, `#flash`, 신규 업체 `#s-cid` `#s-name` `#s-pcs .pc .pc-id/.pc-label`
  `#s-add-pc` `#s-admin-id` `#s-admin-name` `#s-viewers` `#s-add-viewer` `input[name=hold][value=yes|no]` `input[name=tok][value=now|later]`
  `#s-tok-amount` `#s-tok-memo` `#s-make` `#setup-result` (h2 + `.secret pre`), `#rates` (줄마다 input·button), `#usage`.

- [ ] **Step 1: 실패할 시험 쓰기** - check_admin.py 의 `# (Task 3 이 여기에 '=== 4. 화면' 을 넣는다)` 자리에:

```python
print("=== 4. 화면 (Playwright headless) ===")
from playwright.sync_api import sync_playwright  # noqa: E402

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page()
    dialogs = []
    page.on("dialog", lambda d: (dialogs.append(d.message), d.accept()))
    page.goto(url)
    page.wait_for_function("document.getElementById('badge')?.textContent.includes('에뮬레이터')", timeout=15000)
    check(page.text_content("#badge") == "에뮬레이터 (시험)" and "k=" not in page.url, "띠에 '에뮬레이터 (시험)', 주소창에서 비밀 값을 지운다", page.url)
    page.wait_for_selector("#companies tr[data-cid='t_new']", timeout=15000)
    cell = page.text_content("#companies tr[data-cid='t_new'] td:nth-child(2)")
    check(cell == PLAN["name"] and "1" not in dialogs and page.locator("#companies img").count() == 0,
          "업체 이름에 넣은 HTML 은 글자 그대로 (스크립트로 안 돈다)", cell)
    page.click("#companies tr[data-cid='t_new']")
    page.wait_for_function("document.getElementById('detail')?.textContent.includes('남은 600')", timeout=15000)
    check(True, "줄을 누르면 상세: 남은 토큰 600")
    page.fill("#detail input[placeholder^='+1000']", "+50")
    page.fill("#detail input[placeholder^='메모']", "화면에서")
    page.click("#detail button:has-text('넣기')")
    page.wait_for_function("document.getElementById('detail')?.textContent.includes('남은 650')", timeout=15000)
    check(True, "화면에서 토큰 넣기 → 남은 650")

    page.click("nav button[data-view='setup']")
    page.fill("#s-cid", "t_ui")
    page.fill("#s-name", "화면 업체")
    page.fill("#s-pcs .pc-id", "pc_ui")
    page.fill("#s-pcs .pc-label", "화면 PC")
    page.fill("#s-admin-id", "ui_admin")
    page.fill("#s-admin-name", "담당")
    page.check("input[name=tok][value=later]")
    page.click("#s-make")
    page.wait_for_function("document.getElementById('flash')?.textContent.includes('물류대기')", timeout=15000)
    check(db_get("meta/companies/t_ui") is None, "물류대기 사용 여부를 안 고르면 빨간 알림, 아무것도 안 만든다")
    page.check("input[name=hold][value=yes]")
    page.click("#s-make")
    page.wait_for_selector("#setup-result:not(.hide) .secret pre", timeout=30000)
    sent = page.text_content("#setup-result .secret pre")
    seen = re.findall(r"비밀번호: (\S{24})", sent)
    SECRETS.extend(seen)
    check(page.text_content("#setup-result h2") == "다 만들었습니다" and "업체코드: t_ui   아이디: ui_admin" in sent
          and "업체코드: t_ui   PC코드: pc_ui" in sent and len(seen) == 2 and f"https://{PROJECT}.web.app" in sent,
          "다 만들면 고객에게 보낼 정보 (대시보드 주소·관리자·기계 계정)", sent)
    check(claims(email("t_ui", "ui_admin")) == {"cid": "t_ui", "role": "admin"} and (db_get("meta/companies/t_ui/apps/rpa/modules") or {}) == {},
          "화면으로 만든 업체: 관리자 계정, 물류대기 씀 (정책 없음)")

    page.click("nav button[data-view='rates']")
    page.wait_for_selector("#rates tr", timeout=15000)
    rate = page.locator("#rates tr", has_text="주문매핑 매출처리")
    rate.locator("input").fill("2")
    rate.locator("button").click()
    page.wait_for_function("document.getElementById('flash')?.textContent.includes('배율')", timeout=15000)
    check((fs_doc("meta/prices") or {}).get("sales") == 2, "토큰 배율 화면에서 바꾸기 (sales 2)")
    check(page.locator("#usage tr", has_text="t_new").count() == 1, "통계 표에 업체가 나온다")

    old = browser.new_page()
    old.goto(f"{BASE}/?k={'x' * len(key)}")
    old.wait_for_function("document.getElementById('badge')?.textContent === '연결 안 됨'", timeout=15000)
    check("다시 켜세요" in old.text_content("#flash"), "비밀 값이 틀린 화면(옛 주소)은 '다시 켜세요' 를 알린다")

    page.click("#quit")
    srv.wait(timeout=15)
    browser.close()
```

- [ ] **Step 2: 실패 확인** - Expected: 4절에서 `#badge` 를 못 찾아 시간 초과 (빈 화면).

- [ ] **Step 3: `firebase/admin/AFTERMARKET_SETUP.html` 쓰기**

```html
<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AFTER MARKET 관리</title>
<style>
  /* 색은 대시보드(firebase/web/index.html)와 같은 토큰. 밖에서 불러오는 것이 없다 */
  :root {
    --bg:#fdf6e3; --card:#fffdf6; --soft:#eee8d5; --ink:#3d3d4d; --strong:#1e1e2c; --muted:#6e6e80; --line:#e6dfc8;
    --accent:#f29f67; --accent-ink:#1e1e2c; --good:#1a7f79; --bad:#c93b36;
    --font: "Pretendard Variable", Pretendard, -apple-system, BlinkMacSystemFont, system-ui, Roboto, "Segoe UI", "Apple SD Gothic Neo", "Noto Sans KR", "Malgun Gothic", sans-serif;
  }
  @media (prefers-color-scheme: dark) { :root {
    --bg:#002b36; --card:#073642; --soft:#0f4553; --ink:#dbe3e3; --strong:#fdf6e3; --muted:#9cb0b0; --line:#1b4f5c; --good:#34b1aa; --bad:#f57a72;
  } }
  body { margin:0; background:var(--bg); color:var(--ink); font:15px/1.5 var(--font); }
  header { position:sticky; top:0; z-index:5; display:flex; flex-wrap:wrap; align-items:center; gap:10px 14px; padding:12px 20px;
    background:var(--card); border-bottom:1px solid var(--line); }
  header strong { color:var(--strong); font-size:17px; }
  .badge { padding:3px 10px; border-radius:999px; font-size:13px; font-weight:600; background:var(--soft); color:var(--muted); }
  .badge.real { background:var(--accent); color:var(--accent-ink); }
  nav { display:flex; gap:6px; }
  .grow { flex:1; }
  button { font:inherit; cursor:pointer; border-radius:8px; border:1px solid var(--line); background:var(--card); color:var(--strong); padding:7px 12px; }
  button.primary { background:var(--accent); color:var(--accent-ink); border-color:var(--accent); font-weight:600; }
  button.danger { color:var(--bad); }
  button:disabled { opacity:.5; cursor:default; }
  nav button.on { background:var(--strong); color:var(--card); border-color:var(--strong); }
  input, select { font:inherit; padding:7px 9px; border-radius:8px; border:1px solid var(--line); background:var(--card); color:var(--strong); }
  input[type=checkbox], input[type=radio] { width:auto; }
  button:focus-visible, input:focus-visible, select:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
  main { max-width:1100px; margin:0 auto; padding:18px 16px 60px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:16px 18px; margin-bottom:16px; }
  h2 { margin:0 0 12px; font-size:17px; color:var(--strong); }
  h3 { margin:18px 0 6px; font-size:15px; color:var(--strong); }
  table { width:100%; border-collapse:collapse; font-size:14px; }
  th, td { text-align:left; padding:7px 8px; border-bottom:1px solid var(--line); vertical-align:middle; }
  th { color:var(--muted); font-weight:500; font-size:13px; }
  tbody tr.pick { cursor:pointer; }
  tbody tr.pick:hover, tbody tr.pick.on { background:var(--soft); }
  .num { font-variant-numeric:tabular-nums; }
  .muted { color:var(--muted); }
  .bad { color:var(--bad); }
  .hide { display:none !important; }
  .row { display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin:6px 0; }
  .lbl { font-size:13px; color:var(--muted); margin:14px 0 4px; }
  .secret { margin:10px 0; padding:10px 12px; border-radius:8px; background:var(--soft); }
  .secret pre { margin:6px 0; white-space:pre-wrap; font-family:ui-monospace, Consolas, monospace; font-size:13px; color:var(--strong); }
  .steps { padding-left:18px; } .steps li.ok { color:var(--good); } .steps li.bad { color:var(--bad); }
  label.inline { display:inline-flex; align-items:center; gap:6px; margin-right:14px; }
  #flash { position:fixed; left:50%; bottom:20px; transform:translateX(-50%); padding:10px 16px; border-radius:10px; background:var(--strong);
    color:var(--card); font-size:14px; max-width:90vw; }
  #flash.bad { background:var(--bad); color:#fff; }
</style>
</head>
<body>
<header>
  <strong>AFTER MARKET 관리</strong>
  <span id="badge" class="badge">연결 확인 중</span>
  <nav>
    <button data-view="companies" class="on">업체</button>
    <button data-view="setup">신규 업체</button>
    <button data-view="rates">토큰 배율·통계</button>
  </nav>
  <span class="grow"></span>
  <button id="quit">끄기</button>
</header>
<main>
  <section id="view-companies">
    <div class="card">
      <h2>업체</h2>
      <table>
        <thead><tr><th>업체코드</th><th>이름</th><th>상태</th><th>PC</th><th>계정</th><th>남은 토큰</th><th>이번 달</th><th>마지막 로그인</th></tr></thead>
        <tbody id="companies"></tbody>
      </table>
    </div>
    <div class="card hide" id="detail"></div>
  </section>

  <section id="view-setup" class="hide">
    <div class="card">
      <h2>신규 업체</h2>
      <div class="lbl">1. 업체</div>
      <div class="row"><input id="s-cid" placeholder="업체코드 (영문 소문자·숫자·밑줄, 예: net)" size="34"><input id="s-name" placeholder="업체 이름" size="24"></div>
      <div class="lbl">2. PC</div>
      <div id="s-pcs"></div>
      <button id="s-add-pc">한 대 더</button>
      <div class="lbl">3. 관리자 계정 (대시보드에 로그인할 사람)</div>
      <div class="row"><input id="s-admin-id" placeholder="아이디 (예: admin)" size="18"><input id="s-admin-name" placeholder="이름" size="18"></div>
      <div id="s-viewers"></div>
      <button id="s-add-viewer">열람자 더하기</button>
      <div class="lbl">4. 물류대기 관리를 쓰나요? (업체마다 다릅니다 - 꼭 고르세요)</div>
      <div class="row">
        <label class="inline"><input type="radio" name="hold" value="yes">예, 씁니다</label>
        <label class="inline"><input type="radio" name="hold" value="no">아니요 (그 업체 화면에서 숨기고 PC 가 끕니다)</label>
      </div>
      <div class="lbl">5. 첫 토큰</div>
      <div class="row">
        <label class="inline"><input type="radio" name="tok" value="now">지금 넣기</label>
        <input id="s-tok-amount" placeholder="토큰 수 (예: 1000)" size="14" inputmode="numeric"><input id="s-tok-memo" placeholder="메모 (예: 10월 결제)" size="22">
      </div>
      <div class="row"><label class="inline"><input type="radio" name="tok" value="later" checked>나중에 (통장 없이 시작 - 막지 않고 세기만 합니다)</label></div>
      <div class="row" style="margin-top:16px"><button id="s-make" class="primary">만들기</button></div>
    </div>
    <div class="card hide" id="setup-result"></div>
  </section>

  <section id="view-rates" class="hide">
    <div class="card">
      <h2>토큰 배율</h2>
      <p class="muted">모듈을 한 번 쓸 때 빠지는 토큰 수입니다. 처음엔 모두 1, 로그인은 0. 바꿔도 지난 기록은 그때 값 그대로입니다. PC 는 10분 안에 새 배율을 씁니다.</p>
      <table><thead><tr><th>모듈</th><th>키</th><th>배율</th><th></th></tr></thead><tbody id="rates"></tbody></table>
    </div>
    <div class="card">
      <h2>통계</h2>
      <table><thead><tr><th>업체코드</th><th>이름</th><th>남은 토큰</th><th>이번 달 쓴 토큰</th><th>통장 시작</th></tr></thead><tbody id="usage"></tbody></table>
    </div>
  </section>
</main>
<div id="flash" class="hide"></div>
<script>
"use strict";
const $ = (id) => document.getElementById(id);
// 비밀 값은 서버가 연 주소(?k=)에만 있다 - 탭 안에만 두고 주소창에서는 지운다 (새로고침은 sessionStorage 로)
const KEY = new URLSearchParams(location.search).get("k") || sessionStorage.getItem("k") || "";
if (KEY) sessionStorage.setItem("k", KEY);
history.replaceState(null, "", "/");
const ROLE = { admin: "관리자", viewer: "열람자", agent: "기계", super: "총괄" };
const MODULE_NAMES = { Sales: "주문매핑 매출처리", Hold: "물류대기 관리", Logistics: "물류관리", Output: "운송장 출력 / 엑셀 생성" };
const RATE_NAMES = { default: "그 밖의 모듈 (기본)", login: "로그인", sales: "주문매핑 매출처리", hold: "물류대기 관리",
  logistics: "물류관리", output: "운송장 출력 / 엑셀 생성", sites: "쇼핑몰·사이트 받기" };
let info = { dashboard: "" };

// 글은 모두 textContent 로 넣는다 - 업체 이름 등에 HTML 이 있어도 글자로만 보인다
function el(tag, props = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (v === true) e.setAttribute(k, "");
    else if (v !== false && v !== null && v !== undefined) e.setAttribute(k, v);
  }
  for (const kid of kids.flat()) if (kid !== null && kid !== undefined && kid !== false && kid !== "") e.append(kid instanceof Node ? kid : String(kid));
  return e;
}
let flashTimer;
function flash(text, bad = false) {
  const f = $("flash");
  f.textContent = text;
  f.className = bad ? "bad" : "";
  clearTimeout(flashTimer);
  flashTimer = setTimeout(() => f.classList.add("hide"), bad ? 9000 : 3500);
}
async function api(method, path, body) {
  const r = await fetch(path, { method, headers: { "X-Admin-Key": KEY, "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body) });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `요청이 실패했습니다 (${r.status})`);
  return data;
}
// 누르는 동안 단추를 잠그고 실패하면 빨간 알림 (서버도 고치는 요청은 하나씩 한다)
async function act(btn, fn) {
  if (btn) btn.disabled = true;
  try { return await fn(); } catch (e) { flash(e.message, true); return undefined; } finally { if (btn) btn.disabled = false; }
}
const when = (iso) => (iso ? new Date(iso).toLocaleString("ko-KR", { timeZone: "Asia/Seoul", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "-");
const local = (s) => (s ? s.replace("T", " ") : "-");     // 한국 시각 글 ("2026-10-06T13:55:49") 그대로
function secretBox(title, text) {
  const copy = el("button", { onclick: async () => { await navigator.clipboard.writeText(text).catch(() => {}); copy.textContent = "복사했습니다"; } }, "복사");
  return el("div", { class: "secret" }, el("strong", {}, title), el("pre", {}, text),
    el("div", { class: "row" }, copy, el("span", { class: "muted" }, "이 화면을 떠나면 비밀번호는 다시 볼 수 없습니다 (잃으면 재발급)")));
}

// --- 메뉴 --------------------------------------------------------------------
function show(view) {
  for (const b of document.querySelectorAll("nav button")) b.classList.toggle("on", b.dataset.view === view);
  for (const v of ["companies", "setup", "rates"]) $(`view-${v}`).classList.toggle("hide", v !== view);
  if (view === "companies") loadCompanies();
  if (view === "rates") loadRates();
}
for (const b of document.querySelectorAll("nav button")) b.onclick = () => show(b.dataset.view);

// --- ① 업체 ---------------------------------------------------------------------
let current = null;
async function loadCompanies() {
  const rows = await act(null, () => api("GET", "/api/companies"));
  if (!rows) return;
  $("companies").replaceChildren(...rows.map((r) => el("tr", { class: `pick${r.cid === current ? " on" : ""}`, "data-cid": r.cid, onclick: () => openDetail(r.cid) },
    el("td", {}, r.cid), el("td", {}, r.name), el("td", { class: r.stts === 9 ? "muted" : "" }, r.stts === 9 ? "삭제" : "사용"),
    el("td", { class: "num" }, r.pcs), el("td", { class: "num" }, r.users), el("td", { class: "num" }, r.left === null ? "통장 없음" : r.left),
    el("td", { class: "num" }, r.month), el("td", {}, when(r.lastSignIn)))));
}
async function openDetail(cid, keep) {
  const d = await act(null, () => api("GET", `/api/companies/${cid}`));
  if (!d) return;
  current = cid;
  for (const tr of $("companies").children) tr.classList.toggle("on", tr.dataset.cid === cid);
  const box = $("detail");
  box.replaceChildren(el("h2", {}, `${d.name} (${d.cid})`, d.stts === 9 ? el("span", { class: "muted" }, " · 삭제된 업체") : ""),
    keep ?? "", pcSection(d), userSection(d), tokenSection(d), moduleSection(d), dangerSection(d));
  box.classList.remove("hide");
}
const refresh = (cid, keep) => { openDetail(cid, keep); loadCompanies(); };
function pcSection(d) {
  const id = el("input", { placeholder: "PC코드 (예: office)", size: 16 }), label = el("input", { placeholder: "PC 이름 (예: 사무실 PC)", size: 20 });
  const agent = el("input", { type: "checkbox", checked: true });
  const add = el("button", { onclick: () => act(add, async () => {
    const r = await api("POST", `/api/companies/${d.cid}/pcs`, { pcId: id.value.trim(), label: label.value.trim(), agent: agent.checked });
    flash(`PC ${r.pc.pcId} 를 더했습니다`);
    refresh(d.cid, r.agent ? secretBox("기계 계정 - PC 설정 창에 넣을 값", `업체코드: ${d.cid}   PC코드: ${r.pc.pcId}   비밀번호: ${r.agent.password}`) : null);
  }) }, "PC 더하기");
  return el("div", {}, el("h3", {}, "PC"),
    d.pcs.length ? el("ul", {}, d.pcs.map((p) => el("li", {}, `${p.label || "(이름 없음)"} · ${p.pcId}`))) : el("p", { class: "muted" }, "PC 가 없습니다"),
    el("div", { class: "row" }, id, label, el("label", { class: "inline" }, agent, "기계 계정도 만들기"), add));
}
function userSection(d) {
  const rows = d.users.map((u) => {
    const pw = el("button", { onclick: () => act(pw, async () => {
      if (!confirm(`${u.email} 의 비밀번호를 새로 만들까요? 옛 비밀번호의 로그인은 1시간 안에 끊깁니다.`)) return;
      const r = await api("POST", `/api/companies/${d.cid}/passwd`, { id: u.email });
      openDetail(d.cid, secretBox(`새 비밀번호 - ${r.email}`, r.agent ? `업체코드: ${d.cid}   PC코드: ${u.pcId}   비밀번호: ${r.password}`
        : `업체코드: ${d.cid}   아이디: ${u.id}   비밀번호: ${r.password}`));
    }) }, "비밀번호 재발급");
    const lock = el("button", { onclick: () => act(lock, async () => {
      if (!u.disabled && !confirm(`${u.email} 계정을 막을까요? 1시간 안에 로그인이 끊깁니다.`)) return;
      await api("POST", `/api/companies/${d.cid}/disabled`, { id: u.email, disabled: !u.disabled });
      flash(u.disabled ? "계정을 다시 열었습니다" : "계정을 막았습니다");
      openDetail(d.cid);
    }) }, u.disabled ? "열기" : "막기");
    return el("tr", {}, el("td", {}, u.role === "agent" ? `${u.id} (PC ${u.pcId})` : u.id), el("td", {}, ROLE[u.role] || u.role),
      el("td", { class: u.disabled ? "bad" : "" }, u.disabled ? "막힘" : "열림"), el("td", {}, when(u.lastSignIn)), el("td", {}, el("div", { class: "row" }, pw, lock)));
  });
  const id = el("input", { placeholder: "아이디", size: 14 }), name = el("input", { placeholder: "이름", size: 14 });
  const role = el("select", {}, el("option", { value: "admin" }, "관리자"), el("option", { value: "viewer" }, "열람자"));
  const add = el("button", { onclick: () => act(add, async () => {
    const r = await api("POST", `/api/companies/${d.cid}/users`, { id: id.value.trim(), name: name.value.trim(), role: role.value });
    refresh(d.cid, secretBox(`새 계정 - 대시보드 로그인 (${ROLE[r.role]})`, `업체코드: ${d.cid}   아이디: ${id.value.trim()}   비밀번호: ${r.password}`));
  }) }, "사용자 더하기");
  return el("div", {}, el("h3", {}, "계정"),
    el("table", {}, el("thead", {}, el("tr", {}, el("th", {}, "아이디"), el("th", {}, "역할"), el("th", {}, "상태"), el("th", {}, "마지막 로그인"), el("th", {}, ""))),
      el("tbody", {}, rows)),
    el("div", { class: "row" }, id, name, role, add));
}
function tokenSection(d) {
  const t = d.tokens;
  const amount = el("input", { placeholder: "+1000 또는 -50", size: 12, inputmode: "numeric" }), memo = el("input", { placeholder: "메모 (예: 10월 결제)", size: 22 });
  const give = el("button", { class: "primary", onclick: () => act(give, async () => {
    const r = await api("POST", `/api/companies/${d.cid}/tokens`, { amount: amount.value.trim(), memo: memo.value.trim() });
    flash(r.created ? "통장을 만들었습니다 - 지금부터 남은 토큰이 0 이하면 실행이 막힙니다" : "토큰을 넣었습니다");
    refresh(d.cid);
  }) }, "넣기");
  return el("div", {}, el("h3", {}, "토큰"),
    t ? el("p", {}, `넣은 합계 ${t.granted} · 쓴 ${t.spent} · `, el("strong", {}, `남은 ${t.left}`), el("span", { class: "muted" }, `  (${local(t.since)} 통장 시작)`))
      : el("p", { class: "muted" }, "통장이 없습니다 - 처음 넣으면 통장이 생기고, 그때부터 남은 토큰이 0 이하면 실행이 막힙니다 (그 전에 쓴 것은 안 뺍니다)"),
    el("div", { class: "row" }, amount, memo, give),
    t && t.grants.length ? el("table", {}, el("thead", {}, el("tr", {}, el("th", {}, "언제"), el("th", {}, "얼마"), el("th", {}, "메모"))),
      el("tbody", {}, t.grants.map((g) => el("tr", {}, el("td", {}, local(g.at)), el("td", { class: "num" }, g.amount > 0 ? `+${g.amount}` : g.amount), el("td", {}, g.memo || "-"))))) : "");
}
function moduleSection(d) {
  const boxes = Object.entries(MODULE_NAMES).map(([k, name]) => {
    const cb = el("input", { type: "checkbox", checked: d.modules[k] !== false });
    cb.onchange = () => act(cb, async () => {
      try { await api("POST", `/api/companies/${d.cid}/modules`, { [k]: cb.checked ? "on" : "off" }); flash(`${name}: ${cb.checked ? "씀" : "안 씀"}`); }
      finally { openDetail(d.cid); }
    });
    return el("label", { class: "inline" }, cb, name);
  });
  return el("div", {}, el("h3", {}, "모듈 정책"), el("p", { class: "muted" }, "끄면 그 업체 대시보드에서 숨고, PC 가 그 모듈을 끕니다."), el("div", { class: "row" }, boxes));
}
function dangerSection(d) {
  if (d.stts === 9) {
    const back = el("button", { onclick: () => act(back, async () => {
      await api("POST", `/api/companies/${d.cid}/restore`, {});
      flash("업체를 되살렸습니다 - 계정을 다시 열었습니다");
      refresh(d.cid);
    }) }, "되살리기");
    return el("div", {}, el("h3", {}, "업체 되살림"), el("p", { class: "muted" }, "그 업체 계정을 모두 다시 엽니다."), back);
  }
  const code = el("input", { placeholder: `${d.cid} 를 똑같이 치세요`, size: 22 });
  const del = el("button", { class: "danger", onclick: () => act(del, async () => {
    const r = await api("POST", `/api/companies/${d.cid}/remove`, { confirm: code.value.trim() });
    flash(`업체를 삭제했습니다 - 계정 ${r.users.length}개를 막았습니다 (자료는 남습니다)`);
    refresh(d.cid);
  }) }, "업체 삭제");
  return el("div", {}, el("h3", {}, "업체 삭제"), el("p", { class: "muted" }, "그 업체 계정을 모두 막습니다. 자료(기록·통장)는 남고 되살릴 수 있습니다."),
    el("div", { class: "row" }, code, del));
}

// --- ② 신규 업체 -----------------------------------------------------------------
const pcRow = () => el("div", { class: "row pc" }, el("input", { class: "pc-id", placeholder: "PC코드 (예: office)", size: 18 }),
  el("input", { class: "pc-label", placeholder: "PC 이름 (예: 사무실 PC)", size: 22 }));
const viewerRow = () => el("div", { class: "row viewer" }, el("input", { class: "v-id", placeholder: "열람자 아이디", size: 18 }),
  el("input", { class: "v-name", placeholder: "이름", size: 18 }));
$("s-pcs").append(pcRow());
$("s-add-pc").onclick = () => $("s-pcs").append(pcRow());
$("s-add-viewer").onclick = () => $("s-viewers").append(viewerRow());
$("s-make").onclick = () => act($("s-make"), async () => {
  const hold = document.querySelector("input[name=hold]:checked"), tok = document.querySelector("input[name=tok]:checked");
  const plan = {
    cid: $("s-cid").value.trim(), name: $("s-name").value.trim(),
    pcs: [...document.querySelectorAll("#s-pcs .pc")].map((r) => ({ pcId: r.querySelector(".pc-id").value.trim(), label: r.querySelector(".pc-label").value.trim() }))
      .filter((p) => p.pcId || p.label),
    users: [{ id: $("s-admin-id").value.trim(), name: $("s-admin-name").value.trim(), role: "admin" },
      ...[...document.querySelectorAll("#s-viewers .viewer")].map((r) => ({ id: r.querySelector(".v-id").value.trim(), name: r.querySelector(".v-name").value.trim(), role: "viewer" }))
        .filter((u) => u.id)],
    hold: hold ? hold.value === "yes" : null,         // 안 고르면 서버가 '물류대기 관리를 쓰는지 골라 주세요' 로 거절한다
    tokens: tok?.value === "now" ? { amount: $("s-tok-amount").value.trim(), memo: $("s-tok-memo").value.trim() } : null,
  };
  showSetupResult(plan, await api("POST", "/api/setup", plan));
});
function showSetupResult(plan, r) {
  const pw = (made) => (made ? made.password : "(이미 있던 계정 - 모르면 업체 화면에서 재발급)");
  const lines = [`[대시보드]  ${info.dashboard}`];
  for (const u of plan.users) lines.push(`${u.role === "viewer" ? "열람자" : "관리자"}  업체코드: ${plan.cid}   아이디: ${u.id}   비밀번호: ${pw(r.made.users.find((m) => m.id === u.id))}`);
  lines.push("", "[PC 설정 창 - 기계 계정]");
  for (const p of plan.pcs) lines.push(`${p.label || p.pcId} → 업체코드: ${plan.cid}   PC코드: ${p.pcId}   비밀번호: ${pw(r.made.agents.find((a) => a.pcId === p.pcId))}`);
  const box = $("setup-result");
  box.replaceChildren(el("h2", {}, r.ok ? "다 만들었습니다" : "중간에 멈췄습니다 - 고친 뒤 [만들기] 를 다시 누르면 남은 것만 합니다"),
    el("ul", { class: "steps" }, r.steps.map((s) => el("li", { class: s.ok ? "ok" : "bad" }, `${s.ok ? "✓" : "✗"} ${s.label}${s.note ? ` - ${s.note}` : ""}`))),
    r.made.users.length || r.made.agents.length ? secretBox("고객에게 보낼 정보", lines.join("\n")) : "");
  box.classList.remove("hide");
  box.scrollIntoView({ behavior: "smooth" });
}

// --- ③ 토큰 배율·통계 ---------------------------------------------------------------
async function loadRates() {
  const got = await act(null, () => Promise.all([api("GET", "/api/prices"), api("GET", "/api/usage")]));
  if (!got) return;
  const [rates, usage] = got;
  $("rates").replaceChildren(...[...new Set([...Object.keys(RATE_NAMES), ...Object.keys(rates)])].map((k) => {
    const v = el("input", { value: rates[k] ?? rates.default ?? 1, size: 5, inputmode: "numeric", class: "num" });
    const save = el("button", { onclick: () => act(save, async () => {
      await api("POST", "/api/prices", { key: k, value: v.value.trim() });
      flash(`${RATE_NAMES[k] || k} 토큰 배율을 ${v.value.trim()} 로 바꿨습니다`);
      loadRates();
    }) }, "저장");
    return el("tr", {}, el("td", {}, RATE_NAMES[k] || k), el("td", { class: "muted" }, k), el("td", {}, v), el("td", {}, save));
  }));
  $("usage").replaceChildren(...usage.map((u) => el("tr", {}, el("td", {}, u.cid), el("td", {}, u.name),
    el("td", { class: "num" }, u.left === null ? "통장 없음" : u.left), el("td", { class: "num" }, u.month), el("td", {}, local(u.since)))));
}

// --- 켜기·끄기 -----------------------------------------------------------------------
$("quit").onclick = () => act($("quit"), async () => {
  if (!confirm("관리 화면을 끌까요?")) return;
  await api("POST", "/api/quit");
  document.body.replaceChildren(el("main", {}, el("div", { class: "card" }, el("h2", {}, "관리 화면을 껐습니다"),
    el("p", { class: "muted" }, "다시 쓰려면 바탕화면의 'AFTER MARKET 관리' 를 누르세요. 이 창은 닫아도 됩니다."))));
});
(async () => {
  try {
    info = await api("GET", "/api/info");
    $("badge").textContent = info.emulator ? "에뮬레이터 (시험)" : `실제 서버 (${info.project})`;
    $("badge").className = info.emulator ? "badge" : "badge real";
    loadCompanies();
  } catch (e) {
    $("badge").textContent = "연결 안 됨";
    flash(e.message, true);
  }
})();
</script>
</body>
</html>
```

- [ ] **Step 4: 통과 확인** - Expected: 1~5절 모두 통과.

- [ ] **Step 5: 커밋은 사용자에게 묻는다.**

---

### Task 4: 바로 가기·bat·문서

**Files:**
- Create: `firebase/admin/AFTERMARKET_SETUP.bat` (영문만, CRLF - 파이썬으로 바이트를 써서 줄 끝을 못 박는다)
- Modify: `tests/test_encoding.py` (1-2절), `firebase/admin/README.md`, `docs/firebase-architecture.md`
- 메모리: `next-steps.md`, 새 `admin-tool.md` + `MEMORY.md` 한 줄

- [ ] **Step 1: 실패할 시험** - `tests/test_encoding.py` 의 1절 루프 바로 뒤에:

```python
print("=== 1-2. 관리 화면 bat 은 영문만 (한글이 없으면 CP949·UTF-8 어느 쪽으로 읽어도 같다 - 2026-10-06) ===")
admin_bat = ROOT / "firebase" / "admin" / "AFTERMARKET_SETUP.bat"
b = admin_bat.read_bytes() if admin_bat.exists() else b"\xff"
check("AFTERMARKET_SETUP.bat 는 영문만 (ASCII)", all(c < 128 for c in b))
check("AFTERMARKET_SETUP.bat 줄 끝은 모두 CRLF", b.count(b"\n") == b.count(b"\r\n") and b.count(b"\n") > 0)
```

- [ ] **Step 2: 실패 확인** - `.venv\Scripts\python.exe tests\test_encoding.py` → 두 줄 실패 (파일 없음).

- [ ] **Step 3: bat 만들기** (파이썬 한 번)

```python
open(r"D:\AX\RPA\firebase\admin\AFTERMARKET_SETUP.bat", "wb").write(b"\r\n".join([
    b"@echo off",
    b"rem AFTER MARKET admin screen: starts the local server (node admin.js) and opens the browser.",
    b"rem ASCII only on purpose - a bat with Korean text must be CP949 (UTF-8 breaks cmd line parsing).",
    b'cd /d "%~dp0"',
    b"node admin.js",
    b"if errorlevel 1 pause",
    b""]))
```

- [ ] **Step 4: 통과 확인** - test_encoding 다시 → 실패 없음.

- [ ] **Step 5: 바로 가기 만들기 (이 PC)** - `cd D:\AX\RPA\firebase\admin; node admin.js --shortcut` →
  `[Environment]::GetFolderPath('Desktop')` 아래 `AFTER MARKET 관리.lnk` 가 있는지 PowerShell `Test-Path` 로 확인. (서버는 안 켠다.)

- [ ] **Step 6: README·구조 안내·메모리**
  - `firebase/admin/README.md` 맨 위에 "## 관리 화면 (먼저 이것)" - 바탕화면 'AFTER MARKET 관리' 를 두 번 누르면 이 PC 에서만 열린다,
    맨 위 띠(실제 서버 주황/에뮬레이터 회색), 비밀번호는 한 번만, [끄기], 바로 가기를 다시 만들려면 `node admin.js --shortcut`.
    '값표' 대신 '토큰 배율'. 터미널 명령 목록은 아래에 그대로.
  - `docs/firebase-architecture.md`: 파일 지도의 `admin/` 줄에 `ops.js · admin.js · AFTERMARKET_SETUP.html/.bat`, 4절 계정 단락에
    "같은 일을 관리 화면(바탕화면 'AFTER MARKET 관리')으로도", 시험 표에 `| 관리 화면 | N | tests/check_admin.py … |`.
  - 메모리 `admin-tool.md` (결정: 방식 A, 이름 토큰 배율·AFTERMARKET_SETUP, bat 영문만, 보안 3가지, 실서버 계정은 Claude 도구로 안 만든다),
    `next-steps.md` 0-11 갱신, `MEMORY.md` 한 줄.

- [ ] **Step 7: 마지막 확인** - check_setup.py (42), check_admin.py (전부), test_encoding.py, `graphify update .`. 커밋은 사용자에게 묻는다.
