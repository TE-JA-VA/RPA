// 에뮬레이터 통합 시험: 진짜 HTTP·진짜 규칙에 에이전트를 붙여 한 바퀴 돌린다.
//
//   실행 (firebase/tests 에서, emu_env.ps1 을 읽은 창):
//   firebase emulators:exec --config ../firebase.json --only auth,database,firestore --project rpa-test-f02e0 "node integration.js"
//
// 하는 일: 시험 계정·claim 만들기 → 명령 하나 넣기 → 에이전트(DRY_RUN) 띄우기 → 결과 확인 → 에이전트 끄기.
// 실제 RPA 는 띄우지 않는다 (RPA_DASHBOARD_DRY_RUN=1). 실제 프로젝트도 건드리지 않는다.
//
// FIREBASE_AUTH_EMULATOR_HOST / FIREBASE_DATABASE_EMULATOR_HOST 는 emulators:exec 가 자식 프로세스에
// 직접 넣어 준다. 여기서 process.env 에 넣으면 늦다 - ES 모듈은 본문보다 import 가 먼저 평가된다.
import { spawn, spawnSync } from "node:child_process";
import { mkdtempSync, mkdirSync, rmSync, existsSync, cpSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { initializeApp } from "firebase-admin/app";
import { getAuth } from "firebase-admin/auth";
import { getDatabase } from "firebase-admin/database";

const PROJECT = "rpa-test-f02e0";
const DB_URL = `http://127.0.0.1:9000/?ns=${PROJECT}-default-rtdb`;
const AGENT_DIR = fileURLToPath(new URL("../agent/", import.meta.url));
const STATUS_SIM = fileURLToPath(new URL("../../tests/status_sim", import.meta.url));

const app = initializeApp({ projectId: PROJECT, databaseURL: DB_URL });
const auth = getAuth(app);
const db = getDatabase(app);

const results = [];
const check = (ok, label) => { results.push([ok, label]); console.log(`  ${ok ? "통과" : "실패"}  ${label}`); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// --- 1. 계정과 claim ------------------------------------------------------
const agentUser = await auth.createUser({ email: "agent@t.local", password: "pw123456" });
await auth.setCustomUserClaims(agentUser.uid, { cid: "c_demo", pcId: "pc_office", role: "agent" });
const adminUser = await auth.createUser({ email: "admin@t.local", password: "pw123456" });
await auth.setCustomUserClaims(adminUser.uid, { cid: "c_demo", role: "admin" });
console.log("시험 계정 생성");

// --- 2. 에이전트 설정 (DPAPI 는 파이썬이 한다) ------------------------------
const work = mkdtempSync(join(tmpdir(), "rpa-agent-it-"));
const cfgPath = join(work, "agent_config.json");
const queuePath = join(work, "queue.jsonl");
// launch() 가 settings.json 에 마지막 실행 시각을 쓰므로, 저장소의 status_sim 을 직접 쓰지 않고 복사본을 쓴다
const statusDir = join(work, "status_sim");
cpSync(STATUS_SIM, statusDir, { recursive: true });
const py = `import secret; secret.write_config(r"${cfgPath}", {"project_id": "${PROJECT}", "api_key": "emulator",
  "database_url": "${DB_URL}", "cid": "c_demo", "pc_id": "pc_office", "email": "agent@t.local"}, "pw123456")`;
const wrote = spawnSync("python", ["-c", py], { cwd: AGENT_DIR, encoding: "utf8" });
if (wrote.status !== 0) { console.error(wrote.stderr); process.exit(1); }
check(existsSync(cfgPath), "에이전트 설정 파일을 만들었다");

// 옛 두 파일 - 에이전트가 켤 때 RPA_UserConfig.json 으로 합치고 비밀번호를 잠근다. 실제 파일 대신 임시 폴더 (RPA_USER_CONFIG)
const userCfg = join(work, "RPA_UserConfig.json");
writeFileSync(join(work, "ERPIA_AI.txt"), JSON.stringify([
  { LogIn: [{ AdminCode: "x" }, { ID: "a" }, { PW: "통합-비번" }] }, { Routine: [{ Login: "Y" }] }]));
writeFileSync(join(work, "WebManageConfig.json"), JSON.stringify({
  SITE1: { URL: "https://a.example.com", ID: "u", PW: "사이트-비번", Action: ["login"], Stts: 9 } }));
const fakeExe = join(work, "ERPiaNet", "ERPiaMain.exe").replaceAll("\\", "/");     // 가짜 ERPia (빈 파일)
mkdirSync(join(work, "ERPiaNet"));
writeFileSync(fakeExe, "");
writeFileSync(join(work, "login_manager_config.json"), JSON.stringify({ admin_code: "x", id: "a", exe_path: fakeExe }));

// --- 3. 명령 하나를 관리자 이름으로 넣는다 ----------------------------------
const now = Math.floor(Date.now() / 1000);
const cmdRef = await db.ref("apps/rpa/commands/c_demo/pc_office").push({
  type: "launch", args: { target: "routine" }, by: adminUser.uid,
  created_at: now, expires_at: now + 600, state: "queued",
});
const expiredRef = await db.ref("apps/rpa/commands/c_demo/pc_office").push({
  type: "launch", args: null, by: adminUser.uid,
  created_at: now - 1000, expires_at: now - 400, state: "queued",
});

// 토큰 값표 (2026-10-06) - 에이전트가 기록을 올릴 때 읽는다. 처음 값표(sites 1)와 다르게 둬서 서버 값표를 읽었는지 본다
const { getFirestore, AggregateField } = await import("firebase-admin/firestore");
const store = getFirestore(app);
const PRICE = { default: 1, login: 0, sites: 2 };
await store.doc("meta/prices").set(PRICE);

// --- 4. 에이전트 띄우기 ---------------------------------------------------
const env = {
  ...process.env,
  RPA_DASHBOARD_DRY_RUN: "1",
  RPA_STATUS_DIR: statusDir,
  RPA_AGENT_CONFIG: cfgPath,
  RPA_AGENT_QUEUE: queuePath,
  RPA_USER_CONFIG: userCfg,
  PYTHONIOENCODING: "utf-8",
  RPA_AGENT_MUTEX: `Local\\AFTER_MARKET_RPA_AGENT_IT_${process.pid}`,   // 개발 PC 에서 도는 진짜 에이전트의 잠금과 따로
};
const agent = spawn("python", ["agent.py"], { cwd: AGENT_DIR, env });
let agentOut = "";
agent.stdout.on("data", (d) => { agentOut += d; });
agent.stderr.on("data", (d) => { agentOut += d; });

// --- 5. 결과를 기다린다 ---------------------------------------------------
async function waitFor(label, fn, ms = 20000) {
  const until = Date.now() + ms;
  while (Date.now() < until) {
    if (await fn()) { check(true, label); return true; }
    await sleep(500);
  }
  check(false, label);
  return false;
}

await waitFor("명령이 done 이 된다", async () => (await cmdRef.child("state").get()).val() === "done");
const done = (await cmdRef.get()).val();
check(typeof done.result === "string" && done.result.includes("띄웠"), "결과 문장이 남는다");
check(typeof done.started_at === "number" && typeof done.ended_at === "number", "시작·종료 시각이 남는다");
await waitFor("만료된 명령은 expired 로 닫힌다", async () => (await expiredRef.child("state").get()).val() === "expired");
await waitFor("live 에 현황이 올라온다", async () => {
  const v = (await db.ref("apps/rpa/live/c_demo/pc_office/programs").get()).val();
  return v && (v.routine || v.prepare);
});
await waitFor("heartbeat 가 올라온다", async () =>
  typeof (await db.ref("apps/rpa/live/c_demo/pc_office/heartbeat/at").get()).val() === "number");
const live = (await db.ref("apps/rpa/live/c_demo/pc_office").get()).val();
check(live?.heartbeat?.every === 5, `heartbeat 에 신호 주기 (${live?.heartbeat?.every})`);
check(typeof live?.launching === "boolean", `띄우는 중인지도 올린다 (${live?.launching})`);
const ver = live?.version;
check(ver && ["none", "ok", "mixed"].includes(ver.state) && typeof ver.checked_at === "string",
  `켤 때 판을 점검해 올린다 (${JSON.stringify(ver)})`);
check(/버전: /.test(agentOut), "에이전트 기록에 버전 줄이 남는다");
const logLen = live?.programs?.routine?.log?.length ?? 0;
check(logLen <= 80, `로그는 80줄 이하 (${logLen})`);

// 두 번째 명령: 실행 중 다시 실행 → launch 의 잠금이 거절 (DRY_RUN 은 3초 유예)
const secondRef = await db.ref("apps/rpa/commands/c_demo/pc_office").push({
  type: "launch", args: { target: "routine" }, by: adminUser.uid,
  created_at: now, expires_at: now + 600, state: "queued",
});
await waitFor("연달아 실행하면 잠금이 거절한다 (failed + 사유)", async () => {
  const v = (await secondRef.get()).val();
  return v.state === "failed" && /진행 중|돌고/.test(v.result || "");
});

// 사용자 설정 한 파일: 켤 때 옮기기·잠그기, set_modules 는 그 파일의 Routine 에 쓴다 (임시 폴더라 실제 설정은 안 건드린다)
await waitFor("켤 때 옛 두 파일을 RPA_UserConfig.json 으로 합친다", async () => existsSync(userCfg));
const uc = readFileSync(userCfg, "utf8");
check(!uc.includes("통합-비번") && !uc.includes("사이트-비번")
  && JSON.parse(uc).LogIn.PW.startsWith("dpapi:") && JSON.parse(uc).Sites.SITE1.PW.startsWith("dpapi:"), "비밀번호는 잠겨서 들어간다");
check(existsSync(join(work, "ERPIA_AI.txt.old")) && existsSync(join(work, "WebManageConfig.json.old"))
  && existsSync(join(work, "login_manager_config.json.old")), "옛 파일 셋은 .old 로");
check(JSON.parse(uc).ERPia?.ExePath === fakeExe, `ERPia 위치도 한 파일로 (${JSON.parse(uc).ERPia?.ExePath})`);
check(/ERPia 위치: /.test(agentOut), "에이전트가 켤 때 ERPia 위치를 확인해 기록한다 (창 없는 실행이라 고르는 창은 안 뜬다)");
const modRef = await db.ref("apps/rpa/commands/c_demo/pc_office").push({
  type: "set_modules", args: { Login: true, Sales: false, Hold: true, Logistics: true, Output: true }, by: adminUser.uid,
  created_at: now, expires_at: now + 600, state: "queued",
});
await waitFor("set_modules 가 done 이 된다", async () => (await modRef.child("state").get()).val() === "done");
const routine = JSON.parse(readFileSync(userCfg, "utf8")).Routine;
check(routine.Sales === "N" && routine.Hold === "Y" && routine.Login === "Y", `RPA_UserConfig.json 의 Routine 에 쓴다 (${JSON.stringify(routine)})`);
await waitFor("live.modules 로 올라온다 (Sales 끔)", async () =>
  (await db.ref("apps/rpa/live/c_demo/pc_office/modules/Sales").get()).val() === false);

// 자동 실행 설정: 복사한 status_sim 의 settings.json 에 쓰이고 live.schedule 로 돌아온다
const schedRef = await db.ref("apps/rpa/commands/c_demo/pc_office").push({
  type: "set_schedule", args: { enabled: true, days: [0, 2, 4], times: ["09:05", "13:30"] }, by: adminUser.uid,
  created_at: now, expires_at: now + 600, state: "queued",
});
await waitFor("set_schedule 가 done 이 된다", async () => (await schedRef.child("state").get()).val() === "done");
const sres = (await schedRef.get()).val();
check(/월·수·금 09:05, 13:30/.test(sres.result || ""), `결과에 요일·시간 (${sres.result})`);
const saved = JSON.parse(readFileSync(join(statusDir, "settings.json"), "utf8")).schedule;
check(saved.enabled === true && saved.days.join() === "0,2,4" && saved.times.join() === "09:05,13:30", "PC 의 settings.json 에 저장");
check(typeof saved.next_run_at === "string", "다음 실행 시각을 잡는다");
await waitFor("live.schedule 로 올라온다", async () =>
  (await db.ref("apps/rpa/live/c_demo/pc_office/schedule/times").get()).val()?.join() === "09:05,13:30");
const badSched = await db.ref("apps/rpa/commands/c_demo/pc_office").push({
  type: "set_schedule", args: { enabled: true, days: [9], times: ["09:00"] }, by: adminUser.uid,
  created_at: now, expires_at: now + 600, state: "queued",
});
await waitFor("잘못된 요일은 failed + 사유", async () => {
  const v = (await badSched.get()).val();
  return v.state === "failed" && /요일/.test(v.result || "");
});
check(!("accounts" in ((await db.ref("apps/rpa/live/c_demo/pc_office").get()).val() || {})), "계정 해시는 클라우드에 안 올라간다");
const recent = (await db.ref("apps/rpa/live/c_demo/pc_office/recent").get()).val() || [];
check(recent.length === 20 && recent.every((d) => /^\d{4}-\d\d-\d\d$/.test(d.date) && "success" in d && "failed" in d),
  `최근 20일 요약이 올라온다 (${recent.length}일)`);

// 이력: status_sim 의 history.jsonl (26건) 이 Firestore runs/c_demo/items 로 올라간다
await waitFor("이력이 Firestore 에 올라온다 (26건)", async () =>
  (await store.collection("runs/c_demo/items").count().get()).data().count >= 26, 30000);
const one = (await store.collection("runs/c_demo/items").where("state", "==", "stopped").limit(1).get()).docs[0]?.data();
check(one && one.pcId === "pc_office" && one.cid === "c_demo" && typeof one.date === "string", "문서에 cid·pcId·date");
check(one && Array.isArray(JSON.parse(one.payload).steps), "payload 에 단계 목록");

// 토큰: 기록마다 쓴 것(map)·쓴 토큰(정수). status_sim 에서 단계가 모두 완료인 프리페어 8건이 사이트 1회씩 (값표 sites 2)
const docs = (await store.collection("runs/c_demo/items").get()).docs.map((d) => d.data());
check(docs.every((d) => Number.isInteger(d.cost) && d.used && typeof d.used === "object"
  && d.cost === Object.entries(d.used).reduce((a, [k, n]) => a + (PRICE[k] ?? PRICE.default) * n, 0)),
  "모든 기록에 쓴 것(map)·쓴 토큰(정수) - 서버 값표로 셌다");
check(docs.filter((d) => d.used?.sites === 1).length === 8, `단계가 모두 완료인 프리페어 기록 8건이 사이트 1회씩 (${docs.filter((d) => d.used?.sites).length}건)`);
// 남은 토큰: 에이전트 코드(agent.balance)가 진짜 REST 로 통장을 읽고 쓴 토큰을 서버에서 더한다
const balancePy = `import json, secret, fb, agent
print(json.dumps(agent.balance(fb.Client(secret.load_config(r"${cfgPath}")), "c_demo")))`;
const bal = () => spawnSync("python", ["-c", balancePy], { cwd: AGENT_DIR, env, encoding: "utf8" });
let b = bal();
check(b.status === 0 && b.stdout.trim() === "null", `통장이 없는 업체는 null - 세기만 한다 (${b.stdout.trim() || b.stderr.slice(-300)})`);
await store.doc("wallet/c_demo").set({ granted: 100 });
const spent = (await store.collection("runs/c_demo/items").aggregate({ s: AggregateField.sum("cost") }).get()).data().s;
b = bal();
check(b.status === 0 && spent === 16 && Number(b.stdout.trim()) === 100 - spent,
  `남은 토큰 = 넣은 100 - 쓴 ${spent} (${b.stdout.trim() || b.stderr.slice(-300)})`);

// 2부 막기: 남은 토큰이 0 이하면 실행 명령은 까닭과 함께 실패 (에이전트가 띄우기 직전에 다시 확인한다)
await store.doc("wallet/c_demo").set({ granted: 10 });                       // 10 - 16 = -6
const tokenCmd = await db.ref("apps/rpa/commands/c_demo/pc_office").push({
  type: "launch", args: { target: "routine" }, by: adminUser.uid,
  created_at: Math.floor(Date.now() / 1000), expires_at: Math.floor(Date.now() / 1000) + 600, state: "queued",
});
await waitFor("토큰이 없으면 실행 명령이 실패로 끝난다", async () => (await tokenCmd.child("state").get()).val() === "failed");
const refusedCmd = (await tokenCmd.get()).val();
check(refusedCmd.result === "토큰이 없습니다 (남은 -6개). 충전한 뒤 실행하세요", `까닭을 그대로 (${refusedCmd.result})`);
await waitFor("현황에 남은 토큰·실행 1번에 드는 토큰", async () => {
  const t = (await db.ref("apps/rpa/live/c_demo/pc_office/tokens").get()).val();
  return t?.balance === -6 && Number.isInteger(t?.cost?.all) && t.cost.all === t.cost.routine + t.cost.prepare;
});
// 3부: 통장 시작 시각(since) 뒤에 시작한 기록만 뺀다 - 진짜 REST 의 started_at >= since 거르기
await store.doc("wallet/c_demo").set({ granted: 10, since: "2999-01-01T00:00:00" });
b = bal();
check(b.status === 0 && Number(b.stdout.trim()) === 10, `통장 시작 뒤 기록이 없으면 넣은 그대로 (${b.stdout.trim() || b.stderr.slice(-300)})`);

// --- 6. 정리 -------------------------------------------------------------
agent.kill();
await sleep(500);
rmSync(work, { recursive: true, force: true });

const failed = results.filter(([ok]) => !ok).length;
console.log(`\n통합 시험 ${results.length - failed}/${results.length} 통과`);
if (failed) {
  console.log("--- 에이전트 출력 ---");
  console.log(agentOut.slice(-3000));
  process.exit(1);
}
process.exit(0);
