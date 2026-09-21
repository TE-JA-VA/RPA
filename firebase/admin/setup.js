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
  if (!KEY_RE.test(value || "")) throw new Error(`${name} 는 영문 소문자·숫자·밑줄만 쓴다: ${value}`);
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
