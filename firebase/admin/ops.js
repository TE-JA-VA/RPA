// 관리 작업 - setup.js(터미널 명령)와 admin.js(관리 화면 AFTERMARKET_SETUP)가 같이 쓴다. 우리 PC 에서만 돈다.
// 값을 돌려줄 뿐 찍지 않는다. 사람이 고칠 수 있는 거절은 Refused (그 글을 터미널은 '오류: …', 화면은 빨간 알림으로).
// 비밀번호는 무작위로 만들어 돌려줄 뿐 어디에도 남기지 않는다.
// 이메일은 조립한다: <아이디>@<cid 의 _ 를 - 로>.rpa-test-f02e0.firebaseapp.com (cid 가 없으면 도메인만, 에이전트 계정은 agent-<pcId>).
// 아이디에 @ 가 있으면 그대로 이메일로 쓴다(외부 메일 계정).
import { readFileSync } from "node:fs";
import { randomBytes } from "node:crypto";
import { fileURLToPath } from "node:url";
import { initializeApp, cert } from "firebase-admin/app";
import { getAuth } from "firebase-admin/auth";
import { getDatabase } from "firebase-admin/database";
import { getFirestore, AggregateField, FieldValue } from "firebase-admin/firestore";

export class Refused extends Error {}

// 공유 계약 — agent/agent.py, web/app.js 에도 같은 규칙이 한 줄씩 있다. 셋이 같아야 한다.
export const PROJECT = "rpa-test-f02e0";
export const DASHBOARD_URL = `https://${PROJECT}.web.app`;
const DOMAIN = `${PROJECT}.firebaseapp.com`;
export const emailFor = (cid, local) => local.includes("@") ? local : `${local.replaceAll("_", "-")}@${cid ? cid.replaceAll("_", "-") + "." : ""}${DOMAIN}`;
const randomPassword = () => randomBytes(18).toString("base64url");   // 24자
export const POLICY_KEYS = ["Sales", "Hold", "Logistics", "Output"];   // Login 은 언제나 켬이라 정책 대상이 아니다
export const SCHEDULE_LIMIT_DEFAULT = 2;   // 자동 실행 개수 - 값이 없을 때 (agent.SCHEDULE_LIMIT_DEFAULT 와 같다)
export const SCHEDULE_LIMIT_MAX = 12;      // PC 쪽 절대 상한 (rpa_status.SCHEDULE_MAX_SLOTS)
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
    if (e.code === "auth/email-already-exists") throw new Refused(`${email} 은 이미 있다. 비밀번호를 바꾸려면 passwd, 사용중지하려면 disable`);
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
  if (!removed && v.stts === 9) throw new Refused(`${cid} 는 비활성화된 업체다. 다시 활성화: 관리 화면의 [다시 활성화] 또는 node setup.js restore ${cid}`);
  return v;
}
// 그 업체의 계정 전부 (cid 없으면 모두). 에이전트 계정도 claim 에 cid 가 있어 같이 잡힌다
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
  if ((await rtdb.ref(`meta/companies/${cid}/stts`).get()).val() === 9) throw new Refused(`${cid} 는 비활성화된 업체다. 다시 활성화: 관리 화면의 [다시 활성화] 또는 node setup.js restore ${cid}`);
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
/** 웰라이프 업체인가 - 업체코드에 wellife (대소문자 무관) 또는 관리 화면에서 연 업체. 에이전트(agent.wellife_on)·업체 웹(rpa-common.wellifeOn)과 같은 규칙 */
export const wellifeAuto = (cid) => String(cid ?? "").toLowerCase().includes("wellife");
export const wellifeOn = (cid, features) => wellifeAuto(cid) || features?.wellife === true;
export async function setFeature(cid, key, on) {
  checkKey("cid", cid);
  if (key !== "wellife") throw new Refused(`모르는 기능입니다: ${key}`);
  await companyOf(cid, { removed: true });
  if (!on && wellifeAuto(cid)) throw new Refused("업체코드에 wellife 포함 - 늘 켜짐 (끌 수 없습니다)");
  const at = rtdb.ref(`meta/companies/${cid}/apps/rpa/features/${key}`);
  await at.set(on ? true : null);
  return { features: (await rtdb.ref(`meta/companies/${cid}/apps/rpa/features`).get()).val() ?? {} };
}
// 자동 실행 개수 = 시각·반복 시간대를 합친 줄 수 (설계 5-3). 유료 옵션 자리 - 업체마다 우리가 정한다. PC 에는 10분 안에 닿는다
export async function setScheduleLimit(cid, n) {
  checkKey("cid", cid);
  await companyOf(cid, { removed: true });
  const s = String(n ?? "").trim();
  if (!/^\d+$/.test(s) || Number(s) > SCHEDULE_LIMIT_MAX) throw new Refused(`자동 실행 개수는 0~${SCHEDULE_LIMIT_MAX} 정수 (받은 값: ${s})`);
  await rtdb.ref(`meta/companies/${cid}/apps/rpa/limits/schedule`).set(Number(s));
  return { cid, schedule: Number(s) };
}
// 판 목록 (자동 업데이트 4절) - meta/releases. 판 키는 점을 _ 로 (RTDB 키에 . 을 못 쓴다)
const relKey = (v) => String(v).replaceAll(".", "_");
const VERSION_RE = /^\d{4}\.\d{2}\.\d{2}-\d+$/;
export async function releasesOf() {
  const v = (await rtdb.ref("meta/releases").get()).val() ?? {};
  const list = Object.values(v.list ?? {}).sort((a, b) => (b.published_at ?? "").localeCompare(a.published_at ?? ""));
  return { list, stable: v.stable ?? null, newest: v.newest ?? null };
}
export async function setReleases(list) {
  if (!Array.isArray(list) || list.some((x) => !VERSION_RE.test(x?.version ?? ""))) throw new Refused("판 목록 모양이 다릅니다");
  const cur = await releasesOf();
  const newest = [...list].sort((a, b) => (b.published_at ?? "").localeCompare(a.published_at ?? ""))[0]?.version ?? null;
  const stable = list.some((x) => x.version === cur.stable) ? cur.stable : null;
  await rtdb.ref("meta/releases").set({ list: Object.fromEntries(list.map((x) => [relKey(x.version),
    { version: x.version, published_at: x.published_at ?? null, bytes: Number(x.bytes) || 0, memo: x.memo ?? "" }])), stable, newest });
  return { count: list.length, newest, stable };
}
const COMMAND_TTL_SEC = 600;     // 웹 화면(firebase-config.js)과 같은 값 - PC 가 받자마자 '예약했습니다' 로 끝낸다
async function sendAdminCommand(cid, pcId, type, args) {
  checkKey("cid", cid); checkKey("pcId", pcId);
  const v = await companyOf(cid);
  if (!v.pcs?.[pcId]) throw new Refused(`없는 PC 입니다: ${pcId}`);
  const now = Math.floor(Date.now() / 1000);
  const ref = rtdb.ref(`apps/rpa/commands/${cid}/${pcId}`).push();
  await ref.set({ type, args: args ?? null, by: "admin-tool", created_at: now, expires_at: now + COMMAND_TTL_SEC, state: "queued" });
  return { key: ref.key };
}
export async function sendUpdate(cid, pcId, version) {
  if (!(await releasesOf()).list.some((x) => x.version === version)) throw new Refused(`올라가 있지 않은 판입니다: ${version}`);
  return sendAdminCommand(cid, pcId, "update", { version });
}
export const sendRollback = (cid, pcId) => sendAdminCommand(cid, pcId, "rollback", null);
/** PC 한 대의 버전·업데이트 상태와 관리 화면이 보낸 마지막 업데이트/되돌리기 명령 - 화면이 진행 중인 줄만 3초마다 다시 읽는다 */
export async function pcUpdateStatus(cid, pcId) {
  checkKey("cid", cid); checkKey("pcId", pcId);
  const live = (await rtdb.ref(`apps/rpa/live/${cid}/${pcId}`).get()).val() ?? {};
  const recent = (await rtdb.ref(`apps/rpa/commands/${cid}/${pcId}`).orderByKey().limitToLast(20).get()).val() ?? {};
  const c = Object.values(recent).filter((x) => x?.by === "admin-tool" && (x.type === "update" || x.type === "rollback")).at(-1);
  const cmd = c ? { type: c.type, state: c.state, created_at: c.created_at ?? null, expires_at: c.expires_at ?? null,
    started_at: c.started_at ?? null, result: c.result ?? null } : null;
  return { version: live.version ?? null, update: live.update ?? null, cmd };
}
export async function setStable(version) {
  const cur = await releasesOf();
  if (!cur.list.some((x) => x.version === version)) throw new Refused(`올라가 있지 않은 판입니다: ${version}`);
  await rtdb.ref("meta/releases/stable").set(version);
  return { stable: version };
}
export async function scheduleLimitOf(cid) {
  checkKey("cid", cid);
  return (await companyOf(cid, { removed: true })).apps?.rpa?.limits?.schedule ?? null;
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
function priceValue(value) {
  const text = String(value ?? "").trim();
  if (!/^\d+$/.test(text)) throw new Refused(`토큰 배율은 0 이상 정수 (받은 값: ${text})`);
  return Number(text);
}
export async function setPrice(key, value) {
  checkKey("모듈 키", key);
  await store.doc("meta/prices").set({ [key]: priceValue(value) }, { merge: true });
  return getPrices();
}
// 업체 배율 prices/{cid} (2026-10-08) - 에이전트가 meta/prices 위에 덮는다. 웰라이프 업체면 웰라이프 모듈 줄을 보인다
export async function companyPrices(cid) {
  checkKey("cid", cid);
  const v = await companyOf(cid, { removed: true });
  return { cid, prices: (await store.doc(`prices/${cid}`).get()).data() ?? {}, wellife: wellifeOn(cid, v.apps?.rpa?.features) };
}
// 값을 비우면 그 키를 지워 기본값을 따른다
export async function setCompanyPrice(cid, key, value) {
  checkKey("cid", cid); checkKey("모듈 키", key);
  await companyOf(cid, { removed: true });
  const blank = String(value ?? "").trim() === "";
  await store.doc(`prices/${cid}`).set({ [key]: blank ? FieldValue.delete() : priceValue(value) }, { merge: true });
  return companyPrices(cid);
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
  return { cid, name: v.name, stts: v.stts ?? 0, pcs: await Promise.all(Object.entries(v.pcs ?? {}).map(async ([pcId, p]) =>
      ({ pcId, label: p.label ?? "", ...(await pcUpdateStatus(cid, pcId)) }))),
    users, modules: v.apps?.rpa?.modules ?? {}, features: v.apps?.rpa?.features ?? {}, wellife: wellifeOn(cid, v.apps?.rpa?.features),
    wellifeAuto: wellifeAuto(cid), scheduleLimit: v.apps?.rpa?.limits?.schedule ?? null, tokens: (await tokenStatus(cid)).wallet };
}
// 신규 업체 한 흐름 (설계 4-2). 먼저 내용을 다 본 뒤(틀리면 아무것도 안 만든다) 차례로 하고 첫 실패에서 멈춘다.
// 이미 있는 업체·PC 는 그대로 쓰고, 이미 있는 계정은 건너뛰고, 토큰 정보가 이미 있으면 최초 토큰은 건너뛴다 - 다시 누르면 남은 것만
function checkPlan(plan) {
  if (!plan || typeof plan !== "object") throw new Refused("신규 업체 내용이 비었습니다");
  checkKey("업체코드", plan.cid);
  if (!String(plan.name ?? "").trim()) throw new Refused("업체 이름을 넣으세요");
  const pcs = plan.pcs ?? [], users = plan.users ?? [];
  if (!pcs.length) throw new Refused("PC 를 하나 이상 넣으세요");
  for (const p of pcs) checkKey("PC코드", p.pcId);
  if (new Set(pcs.map((p) => p.pcId)).size !== pcs.length) throw new Refused("PC코드가 겹칩니다");
  if (!users.some((u) => u.role === "admin")) throw new Refused("관리자 계정을 한 명 이상 넣으세요");
  for (const u of users) {
    if (u.role !== "admin" && u.role !== "viewer") throw new Refused("계정 역할은 관리자나 유저");
    if (!String(u.id ?? "").trim()) throw new Refused("계정 아이디를 넣으세요");
  }
  if (new Set(users.map((u) => String(u.id).trim())).size !== users.length) throw new Refused("계정 아이디가 겹칩니다");
  if (typeof plan.hold !== "boolean") throw new Refused("물류대기 관리 메뉴 사용 여부를 골라 주세요 (업체마다 다릅니다)");
  if (plan.tokens) {
    const a = String(plan.tokens.amount ?? "").trim();
    if (!/^\+?\d+$/.test(a) || Number(a) <= 0) throw new Refused(`최초 토큰량은 1 이상 정수 (받은 값: ${a})`);
  }
}
export async function setupCompany(plan) {
  checkPlan(plan);
  const { cid } = plan, steps = [], made = { users: [], agents: [] };
  // 이미 있는 업체코드는 이름이 같을 때만 이어서 한다 - 오타로 남의 업체 이름을 바꾸고 거기에 새 고객 계정을 만들면 그 고객이 남의 자료를 본다
  const was = (await rtdb.ref(`meta/companies/${cid}/name`).get()).val();
  if (was && was !== String(plan.name).trim()) throw new Refused(`업체코드 ${cid} 는 이미 있는 업체(${was})입니다 - 이어서 하려면 이름을 똑같이, 새 업체면 다른 업체코드를 쓰세요`);
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
    && await each(plan.users, (u) => step(`${u.role === "viewer" ? "유저" : "관리자"} 계정 ${String(u.id).trim()}`,
      () => skipExisting(async () => { made.users.push({ ...(await addUser(cid, String(u.id).trim(), u.role, u.name)), id: String(u.id).trim() }); })))
    && await each(plan.pcs, (p) => step(`에이전트 계정 ${p.pcId}`,
      () => skipExisting(async () => { made.agents.push({ ...(await addAgent(cid, p.pcId)), label: p.label ?? "" }); })))
    && await step(`물류대기 관리 메뉴 ${plan.hold ? "사용" : "사용 안 함"}`, async () => { await setModules(cid, { Hold: plan.hold ? "on" : "off" }); });
  if (ok && plan.tokens) {
    await step(`최초 토큰 ${Number(String(plan.tokens.amount).trim())}개`, async () => {
      if ((await store.doc(`wallet/${cid}`).get()).exists) return "이미 토큰 정보가 있어 건너뜀";
      await grantTokens(cid, plan.tokens.amount, plan.tokens.memo);
    });
  }
  return { ok: steps.every((s) => s.ok), steps, made };
}
