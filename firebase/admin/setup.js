// 회사·PC·사용자·에이전트를 등록하고 custom claim 을 심는다. 우리 PC 에서만 돈다.
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
//
// 업체 상태 stts: 0(또는 없음) 사용, 9 삭제(비활성). 삭제된 업체엔 pc·user·agent 를 못 만든다.
// 비밀번호는 명령줄로 받지 않는다. 무작위로 만들어 딱 한 번 찍고, 잃으면 passwd 로 다시 발급한다.
// 이메일은 조립한다: <아이디>@<cid 의 _ 를 - 로>.rpa-test-f02e0.firebaseapp.com (cid 가 - 면 도메인만, 기계 계정은 agent-<pcId>).
// 아이디에 @ 가 있으면 그대로 이메일로 쓴다(외부 메일 계정).
import { readFileSync } from "node:fs";
import { randomBytes } from "node:crypto";
import { fileURLToPath } from "node:url";
import { initializeApp, cert } from "firebase-admin/app";
import { getAuth } from "firebase-admin/auth";
import { getDatabase } from "firebase-admin/database";
import { getFirestore } from "firebase-admin/firestore";

// 공유 계약 — agent/agent.py, web/app.js 에도 같은 규칙이 한 줄씩 있다. 셋이 같아야 한다.
const DOMAIN = "rpa-test-f02e0.firebaseapp.com";
const emailFor = (cid, local) => local.includes("@") ? local : `${local.replaceAll("_", "-")}@${cid ? cid.replaceAll("_", "-") + "." : ""}${DOMAIN}`;
const randomPassword = () => randomBytes(18).toString("base64url");   // 24자

// 인수 개수 [최소, 최대]. 옛 꼴(user <이메일> <비밀번호> …, agent <이메일> <비밀번호> …)은 받지 않는다.
const ARGC = { company: [2], pc: [3], user: [4], agent: [2, 2], passwd: [2, 2], disable: [2, 2], enable: [2, 2], show: [2, 2], list: [0, 1], modules: [2], remove: [1, 1], restore: [1, 1] };

const [, , cmdName, ...rest] = process.argv;
const [min, max = Infinity] = ARGC[cmdName] ?? [];
if (!ARGC[cmdName] || rest.length < min || rest.length > max) {
  const src = readFileSync(fileURLToPath(import.meta.url), "utf8").split("\n");
  console.log(src.slice(1, src.findIndex((l) => !l.startsWith("//"))).join("\n"));
  process.exit(1);
}

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
  if (!KEY_RE.test(value || "")) throw new Error(`${name} 는 영문 소문자·숫자·밑줄만 쓴다: ${value}`);
}

function cidOf(arg) {
  if (arg === "-") return null;
  checkKey("cid", arg);
  return arg;
}

async function createUser(email, password) {
  try {
    return await auth.createUser({ email, password, emailVerified: false });
  } catch (e) {
    if (e.code === "auth/email-already-exists") throw new Error(`${email} 은 이미 있다. 비밀번호를 바꾸려면 passwd, 막으려면 disable`);
    throw e;
  }
}

const userOf = (cidArg, id) => auth.getUserByEmail(emailFor(cidOf(cidArg), id));

// 업체 메타. 없거나 삭제(stts=9)된 업체면 멈춘다 - removed=true 는 remove/restore 처럼 삭제된 업체도 다뤄야 할 때
async function companyOf(cid, { removed = false } = {}) {
  const v = (await rtdb.ref(`meta/companies/${cid}`).get()).val();
  if (!v?.name) throw new Error(`먼저 company 로 등록: node setup.js company ${cid} <회사 이름>`);
  if (!removed && v.stts === 9) throw new Error(`${cid} 는 삭제된 업체다. 되살리려면: node setup.js restore ${cid}`);
  return v;
}

// 그 업체의 계정 전부 (cid 없으면 모두). 기계 계정도 claim 에 cid 가 있어 같이 잡힌다
async function usersOf(cid) {
  const rows = [];
  let token;
  do {
    const page = await auth.listUsers(1000, token);
    rows.push(...page.users.filter((u) => !cid || u.customClaims?.cid === cid));
    token = page.pageToken;
  } while (token);
  return rows;
}

if (cmdName === "company") {
  const [cid, ...nameParts] = rest;
  checkKey("cid", cid);
  if ((await rtdb.ref(`meta/companies/${cid}/stts`).get()).val() === 9) throw new Error(`${cid} 는 삭제된 업체다. 되살리려면: node setup.js restore ${cid}`);
  await rtdb.ref(`meta/companies/${cid}`).update({ name: nameParts.join(" "), stts: 0 });
  console.log(`회사 등록: ${cid}`);
  console.log(`  이 업체가 안 쓰는 모듈이 있으면: node setup.js modules ${cid} Hold=off`);

} else if (cmdName === "pc") {
  const [cid, pcId, ...labelParts] = rest;
  checkKey("cid", cid); checkKey("pcId", pcId);
  await companyOf(cid);
  await rtdb.ref(`meta/companies/${cid}/pcs/${pcId}`).update({ label: labelParts.join(" ") });
  console.log(`PC 등록: ${cid}/${pcId}`);

} else if (cmdName === "user") {
  const [cidArg, id, role, ...nameParts] = rest;
  if (!["super", "admin", "viewer"].includes(role)) throw new Error("role 은 super/admin/viewer");
  const cid = cidOf(cidArg);
  if (role !== "super" && !cid) throw new Error("super 가 아니면 cid 가 있어야 한다");
  if (cid) await companyOf(cid);
  const email = emailFor(cid, id), password = randomPassword();
  const user = await createUser(email, password);
  try {
    await auth.setCustomUserClaims(user.uid, cid ? { cid, role } : { role });
    await store.doc(`users/${user.uid}`).set({
      cid: cid ?? null, role, name: nameParts.join(" ") || email, must_change_password: true,
    });
  } catch (e) { await auth.deleteUser(user.uid); throw e; }   // claim 없는 반쪽 계정을 남기지 않는다. 같은 명령을 다시 돌리면 된다
  console.log(`사용자 등록: ${email}  uid=${user.uid}  role=${role}  cid=${cid ?? "-"}`);
  console.log(`  비밀번호: ${password}   (다시 볼 수 없다. 잃으면 passwd)`);

} else if (cmdName === "agent") {
  const [cid, pcId] = rest;
  checkKey("cid", cid); checkKey("pcId", pcId);
  if (!(await companyOf(cid)).pcs?.[pcId]) throw new Error(`먼저 pc 로 등록: node setup.js pc ${cid} ${pcId} <PC 이름>`);
  const email = emailFor(cid, `agent-${pcId}`), password = randomPassword();
  const user = await createUser(email, password);
  try {
    await auth.setCustomUserClaims(user.uid, { cid, pcId, role: "agent" });
  } catch (e) { await auth.deleteUser(user.uid); throw e; }   // 위와 같다
  console.log(`에이전트 등록: ${email}  uid=${user.uid}`);
  console.log(`  PC 에서 그대로 넣는다 →  회사 코드: ${cid}   PC 이름: ${pcId}   비밀번호: ${password}`);
  console.log(`  다시 볼 수 없다. 잃으면 passwd`);

} else if (cmdName === "passwd") {
  const user = await userOf(rest[0], rest[1]);
  const password = randomPassword();
  await auth.updateUser(user.uid, { password });
  await auth.revokeRefreshTokens(user.uid);
  console.log(`비밀번호 교체: ${user.email}`);
  console.log(`  비밀번호: ${password}   (다시 볼 수 없다. 잃으면 다시 passwd. 이미 받은 토큰은 최대 1시간 산다)`);
  if (user.customClaims?.role === "agent") console.log(`  PC 에서 에이전트가 1시간 안에 멈추고 새 비밀번호를 묻는다`);

} else if (cmdName === "disable" || cmdName === "enable") {
  const user = await userOf(rest[0], rest[1]);
  const disabled = cmdName === "disable";
  await auth.updateUser(user.uid, { disabled });
  if (disabled) await auth.revokeRefreshTokens(user.uid);
  console.log(disabled ? `막음: ${user.email}  (이미 받은 토큰은 최대 1시간 산다)` : `다시 엶: ${user.email}`);

} else if (cmdName === "show") {
  const u = await userOf(rest[0], rest[1]);
  console.log({
    uid: u.uid, email: u.email, claims: u.customClaims ?? {}, disabled: u.disabled,
    created: u.metadata.creationTime, lastSignIn: u.metadata.lastSignInTime, lastRefresh: u.metadata.lastRefreshTime,
  });

} else if (cmdName === "list") {
  const [cid] = rest;
  if (cid) checkKey("cid", cid);
  const companies = (await rtdb.ref("meta/companies").get()).val() ?? {};
  if (!cid) console.table(Object.entries(companies).map(([k, v]) => ({ cid: k, name: v.name ?? "-", stts: v.stts ?? 0, pcs: Object.keys(v.pcs ?? {}).join(" ") || "-" })));
  console.table((await usersOf(cid)).map((u) => {
    const c = u.customClaims ?? {};
    return { email: u.email, cid: c.cid ?? "-", stts: c.cid ? companies[c.cid]?.stts ?? 0 : "-", role: c.role ?? "-", pcId: c.pcId ?? "-", disabled: u.disabled, lastSignIn: u.metadata.lastSignInTime ?? "-" };
  }));

} else if (cmdName === "remove" || cmdName === "restore") {
  // 삭제는 표시(stts=9)와 계정 막기뿐이다. 메타·현황·명령·이력은 남으니 되살리면 그대로 돌아온다.
  // ponytail: restore 는 그 업체 계정을 전부 다시 연다 - 삭제 전에 따로 막아 둔 계정이 있었으면 다시 disable 할 것
  const [cid] = rest;
  checkKey("cid", cid);
  const removing = cmdName === "remove";
  const v = await companyOf(cid, { removed: true });
  const users = await usersOf(cid);
  await rtdb.ref(`meta/companies/${cid}/stts`).set(removing ? 9 : 0);
  for (const u of users) {
    await auth.updateUser(u.uid, { disabled: removing });
    if (removing) await auth.revokeRefreshTokens(u.uid);
  }
  console.log(removing
    ? `업체 삭제(비활성): ${cid} ${v.name}  stts=9, 계정 ${users.length}개 막음 (이미 받은 토큰은 최대 1시간 산다. 에이전트는 그 안에 멈춘다)`
    : `업체 되살림: ${cid} ${v.name}  stts=0, 계정 ${users.length}개 다시 엶`);
  for (const u of users) console.log(`  ${u.email}`);

} else if (cmdName === "modules") {
  // 업체 단위로 안 쓰는 모듈을 정한다. off = 화면에서 숨기고 에이전트가 강제로 끔, on = 정책을 지움(그 업체가 쓴다)
  const [cid, ...pairs] = rest;
  checkKey("cid", cid);
  const KEYS = ["Sales", "Hold", "Logistics", "Output"];   // Login 은 언제나 켬이라 정책 대상이 아니다
  const patch = {};
  for (const p of pairs) {
    const [k, v] = p.split("=");
    if (!KEYS.includes(k)) throw new Error(`모듈 키는 ${KEYS.join(", ")} 중 하나 (받은 값: ${k})`);
    if (v !== "on" && v !== "off") throw new Error(`${k} 의 값은 on 또는 off (받은 값: ${v})`);
    patch[k] = v === "off" ? false : null;
  }
  const at = rtdb.ref(`meta/companies/${cid}/apps/rpa/modules`);
  await at.update(patch);
  console.log(`모듈 정책: ${cid}`, (await at.get()).val() ?? "(없음 - 전부 사용)");
}

process.exit(0);
