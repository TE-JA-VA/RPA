// 에뮬레이터 통합 시험: 진짜 HTTP·진짜 규칙에 에이전트를 붙여 한 바퀴 돌린다.
//
//   실행 (firebase/tests 에서, emu_env.ps1 을 읽은 창):
//   firebase emulators:exec --config ../firebase.json --only auth,database --project rpa-test-f02e0 "node integration.js"
//
// 하는 일: 시험 계정·claim 만들기 → 명령 하나 넣기 → 에이전트(DRY_RUN) 띄우기 → 결과 확인 → 에이전트 끄기.
// 실제 RPA 는 띄우지 않는다 (RPA_DASHBOARD_DRY_RUN=1). 실제 프로젝트도 건드리지 않는다.
//
// FIREBASE_AUTH_EMULATOR_HOST / FIREBASE_DATABASE_EMULATOR_HOST 는 emulators:exec 가 자식 프로세스에
// 직접 넣어 준다. 여기서 process.env 에 넣으면 늦다 - ES 모듈은 본문보다 import 가 먼저 평가된다.
import { spawn, spawnSync } from "node:child_process";
import { mkdtempSync, rmSync, existsSync, cpSync } from "node:fs";
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

// --- 4. 에이전트 띄우기 ---------------------------------------------------
const env = {
  ...process.env,
  RPA_DASHBOARD_DRY_RUN: "1",
  RPA_STATUS_DIR: statusDir,
  RPA_AGENT_CONFIG: cfgPath,
  RPA_AGENT_QUEUE: queuePath,
  PYTHONIOENCODING: "utf-8",
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

// 모듈 명령: 상태 시뮬 폴더의 가짜 자격증명 파일로
const credPath = join(work, "ERPIA_AI.txt");
spawnSync("python", ["-c", `import json; json.dump([{"LogIn": [{"AdminCode": "x"}, {"ID": "a"}, {"PW": "시험"}]}], open(r"${credPath}", "w", encoding="utf-8"))`], { encoding: "utf8" });
// 에이전트는 이미 떠 있어 환경변수를 못 바꾼다 - set_modules 는 실기(Task 12)에서 본다. 여기서는 모르는 종류만.
const badRef = await db.ref("apps/rpa/commands/c_demo/pc_office").push({
  type: "set_schedule", args: null, by: adminUser.uid,
  created_at: now, expires_at: now + 600, state: "queued",
});
await waitFor("못 하는 종류는 failed 로 닫힌다", async () => (await badRef.child("state").get()).val() === "failed");

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
