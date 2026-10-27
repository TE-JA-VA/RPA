// RTDB 보안 규칙 시험. 에뮬레이터가 떠 있어야 한다 (npm test 가 띄운다).
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import assert from "node:assert/strict";
import test, { before, after, beforeEach } from "node:test";
import {
  initializeTestEnvironment, assertFails, assertSucceeds,
} from "@firebase/rules-unit-testing";
import { ref, set, update, get, remove, serverTimestamp } from "firebase/database";
import { doc, setDoc, getDoc, updateDoc, deleteDoc, collection, getAggregateFromServer, sum } from "firebase/firestore";

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
    firestore: {
      host: "127.0.0.1",
      port: 8080,
      rules: readFileSync(fileURLToPath(new URL("../rules/firestore.rules", import.meta.url)), "utf8"),
    },
  });
});

after(async () => { await env.cleanup(); });
beforeEach(async () => { await env.clearDatabase(); await env.clearFirestore(); });

// 등장인물
const asAdminA = () => env.authenticatedContext("u_admin_a", { cid: "ca", role: "admin" }).database();
const asViewerA = () => env.authenticatedContext("u_view_a", { cid: "ca", role: "viewer" }).database();
const asAdminB = () => env.authenticatedContext("u_admin_b", { cid: "cb", role: "admin" }).database();
const asSuper = () => env.authenticatedContext("u_super", { role: "super" }).database();
const asAgentA1 = () => env.authenticatedContext("u_agent_a1", { cid: "ca", pcId: "pc1", role: "agent" }).database();
const asAgentA2 = () => env.authenticatedContext("u_agent_a2", { cid: "ca", pcId: "pc2", role: "agent" }).database();
const asAnon = () => env.unauthenticatedContext().database();

// 명령 시각은 초. 규칙이 만든 시각을 서버 시각 ±1분, 만료를 만든 시각 + 600초 이하로만 받는다 (BugBuster M1)
const nowS = () => Math.floor(Date.now() / 1000);
const cmd = (over = {}) => ({
  type: "launch",
  args: null,
  by: "u_admin_a",
  created_at: nowS(),
  expires_at: nowS() + 600,
  state: "queued",
  ...over,
});

test("live: 에이전트는 자기 PC 에 쓸 수 있다", async () => {
  await assertSucceeds(set(ref(asAgentA1(), "apps/rpa/live/ca/pc1"), { host: "PC1", programs: {} }));
});

test("live: 에이전트 현황 칸은 모두 받고, 모르는 칸·큰 글자·틀린 꼴은 거부 (BugBuster K15)", async () => {
  const obj = { a: 1 };
  await assertSucceeds(update(ref(asAgentA1(), "apps/rpa/live/ca/pc1"), {
    server_time: "2026-10-27T10:00:00", host: "PC1", labels: obj, programs: obj, preset_transfer: 1, modules: obj, modes: obj,
    presets: [obj], parallel: obj, together: obj, schedule: obj, recent: [obj], launching: false, version: obj, update: obj, tokens: obj,
  }));
  await assertSucceeds(set(ref(asAgentA1(), "apps/rpa/live/ca/pc1/heartbeat"), { at: 1, every: 5, host: "PC1", rpa_running: false, boot: "a1b2c3d4" }));
  await assertSucceeds(set(ref(asAgentA1(), "apps/rpa/live/ca/pc1/heartbeat"), { at: 1, host: "PC1", rpa_running: true }));   // 옛 에이전트
  await assertSucceeds(update(ref(asAgentA1(), "apps/rpa/live/ca/pc1"), { tokens: null, modes: null }));
  await assertFails(update(ref(asAgentA1(), "apps/rpa/live/ca/pc1"), { junk: "x".repeat(1000) }));
  await assertFails(update(ref(asAgentA1(), "apps/rpa/live/ca/pc1"), { host: "x".repeat(101) }));
  await assertFails(update(ref(asAgentA1(), "apps/rpa/live/ca/pc1"), { programs: "x" }));
  await assertFails(set(ref(asAgentA1(), "apps/rpa/live/ca/pc1/heartbeat"), { at: 1, junk: "x" }));
  await assertFails(set(ref(asAgentA1(), "apps/rpa/live/ca/pc1/heartbeat/boot"), "x".repeat(33)));
});

test("live: 에이전트가 남의 PC 에 쓰면 거부", async () => {
  await assertFails(set(ref(asAgentA2(), "apps/rpa/live/ca/pc1"), { host: "위조" }));
});

test("live: 관리자는 쓸 수 없다 (읽기 전용)", async () => {
  await assertFails(set(ref(asAdminA(), "apps/rpa/live/ca/pc1"), { host: "위조" }));
});

test("live: 같은 회사는 읽고, 다른 회사는 거부, super 는 읽는다", async () => {
  await env.withSecurityRulesDisabled(async (c) => {
    await set(ref(c.database(), "apps/rpa/live/ca/pc1"), { host: "PC1" });
  });
  await assertSucceeds(get(ref(asViewerA(), "apps/rpa/live/ca/pc1")));
  await assertFails(get(ref(asAdminB(), "apps/rpa/live/ca/pc1")));
  await assertSucceeds(get(ref(asSuper(), "apps/rpa/live/ca/pc1")));
});

test("live: 로그인하지 않으면 읽기 거부", async () => {
  await assertFails(get(ref(asAnon(), "apps/rpa/live/ca/pc1")));
});

test("commands: 관리자는 queued 명령을 만들 수 있다", async () => {
  await assertSucceeds(set(ref(asAdminA(), "apps/rpa/commands/ca/pc1/c1"), cmd()));
});

test("commands: 열람자는 명령을 만들 수 없다", async () => {
  await assertFails(set(ref(asViewerA(), "apps/rpa/commands/ca/pc1/c1"), cmd({ by: "u_view_a" })));
});

test("commands: 다른 회사 관리자는 거부", async () => {
  await assertFails(set(ref(asAdminB(), "apps/rpa/commands/ca/pc1/c1"), cmd({ by: "u_admin_b" })));
});

test("commands: by 를 남의 uid 로 위조하면 거부", async () => {
  await assertFails(set(ref(asAdminA(), "apps/rpa/commands/ca/pc1/c1"), cmd({ by: "u_super" })));
});

test("commands: 만들 때 state 가 queued 가 아니면 거부", async () => {
  await assertFails(set(ref(asAdminA(), "apps/rpa/commands/ca/pc1/c1"), cmd({ state: "done" })));
});

test("commands: set_presets 는 관리자가 만들 수 있다 (쇼핑몰 프리셋 켬/끔)", async () => {
  await assertSucceeds(set(ref(asAdminA(), "apps/rpa/commands/ca/pc1/c1"), cmd({ type: "set_presets", args: { PRESET1: true } })));
});

test("commands: set_parallel 은 관리자가 만들 수 있다 (동시 실행 창 수)", async () => {
  await assertSucceeds(set(ref(asAdminA(), "apps/rpa/commands/ca/pc1/c1"), cmd({ type: "set_parallel", args: { parallel: 3 } })));
});

test("commands: set_together 는 관리자가 만들 수 있다 (웰라이프 전체 실행 방식)", async () => {
  await assertSucceeds(set(ref(asAdminA(), "apps/rpa/commands/ca/pc1/c1"), cmd({ type: "set_together", args: { mode: "excel" } })));
});

test("commands: resume_repeat 는 관리자가 만들 수 있다 (반복 다시 시작)", async () => {
  await assertSucceeds(set(ref(asAdminA(), "apps/rpa/commands/ca/pc1/c1"), cmd({ type: "resume_repeat", args: null })));
});

test("commands: stop_rpa 는 관리자가 만들 수 있다 (RPA 중단, 2026-10-12)", async () => {
  await assertSucceeds(set(ref(asAdminA(), "apps/rpa/commands/ca/pc1/c1"), cmd({ type: "stop_rpa", args: null })));
});

test("commands: update·rollback 명령은 업체 관리자도 총괄도 못 넣는다 (관리 화면 Admin SDK 만 - 자동 업데이트 10절)", async () => {
  for (const [who, uid] of [[asAdminA, "u_admin_a"], [asSuper, "u_super"]]) {
    for (const type of ["update", "rollback"]) {
      await assertFails(set(ref(who(), `apps/rpa/commands/ca/pc1/x_${type}`), cmd({ type, by: uid })));
    }
  }
});

test("meta/releases 는 업체 계정이 못 읽는다", async () => {
  await assertFails(get(ref(asAdminA(), "meta/releases")));
});

test("commands: 모르는 type 은 거부", async () => {
  await assertFails(set(ref(asAdminA(), "apps/rpa/commands/ca/pc1/c1"), cmd({ type: "rm_rf" })));
});

test("commands: 관리자가 state 를 직접 done 으로 바꾸면 거부", async () => {
  await assertSucceeds(set(ref(asAdminA(), "apps/rpa/commands/ca/pc1/c1"), cmd()));
  await assertFails(update(ref(asAdminA(), "apps/rpa/commands/ca/pc1/c1"), { state: "done" }));
});

test("commands: 그 PC 의 에이전트만 state 를 옮길 수 있다", async () => {
  await assertSucceeds(set(ref(asAdminA(), "apps/rpa/commands/ca/pc1/c1"), cmd()));
  await assertFails(update(ref(asAgentA2(), "apps/rpa/commands/ca/pc1/c1"), { state: "running" }));
  await assertSucceeds(update(ref(asAgentA1(), "apps/rpa/commands/ca/pc1/c1"), { state: "running", started_at: 1100 }));
  await assertSucceeds(update(ref(asAgentA1(), "apps/rpa/commands/ca/pc1/c1"), { state: "done", ended_at: 1200, result: "ok" }));
});

// 전이는 queued→running|expired, running→done|failed 만. 그 밖은 규칙이 거부한다 (선점·재접속 중복 실행 방지).
test("commands: queued 에서 바로 done 은 거부, running 은 한 번만 잡는다, done 뒤엔 못 돌아간다", async () => {
  const at = (db) => ref(db, "apps/rpa/commands/ca/pc1/c1");
  await assertSucceeds(set(at(asAdminA()), cmd()));
  await assertFails(update(at(asAgentA1()), { state: "done", ended_at: 1200, result: "ok" }));       // queued→done
  await assertSucceeds(update(at(asAgentA1()), { state: "running", started_at: 1100 }));
  await assertFails(update(at(asAgentA1()), { state: "running", started_at: 1101 }));                // running→running (두 번째 선점)
  await assertSucceeds(update(at(asAgentA1()), { state: "done", ended_at: 1200, result: "ok" }));
  await assertFails(update(at(asAgentA1()), { state: "running", started_at: 1300 }));                // done→running
});

test("commands: 늦게 받으면 queued→expired, 돌다 죽으면 running→failed", async () => {
  await assertSucceeds(set(ref(asAdminA(), "apps/rpa/commands/ca/pc1/c1"), cmd()));
  await assertSucceeds(update(ref(asAgentA1(), "apps/rpa/commands/ca/pc1/c1"), { state: "expired" }));
  await assertFails(update(ref(asAgentA1(), "apps/rpa/commands/ca/pc1/c1"), { state: "running", started_at: 1100 }));   // expired→running
  await assertSucceeds(set(ref(asAdminA(), "apps/rpa/commands/ca/pc1/c2"), cmd()));
  await assertSucceeds(update(ref(asAgentA1(), "apps/rpa/commands/ca/pc1/c2"), { state: "running", started_at: 1100 }));
  await assertSucceeds(update(ref(asAgentA1(), "apps/rpa/commands/ca/pc1/c2"), { state: "failed", ended_at: 1200, result: "죽음" }));
});

test("commands: 만든 시각이 서버 시각과 1분 넘게 다르거나 만료가 10분 넘으면 거부 - 브라우저 시계로 명령 수명을 늘리지 못한다 (BugBuster M1)", async () => {
  const at = (k) => ref(asAdminA(), `apps/rpa/commands/ca/pc1/${k}`);
  await assertFails(set(at("c1"), cmd({ created_at: nowS() + 120, expires_at: nowS() + 720 })));
  await assertFails(set(at("c2"), cmd({ created_at: nowS() - 120, expires_at: nowS() + 480 })));
  await assertFails(set(at("c3"), cmd({ expires_at: nowS() + 601 })));
  await assertSucceeds(set(at("c4"), cmd({ created_at: nowS() + 30, expires_at: nowS() + 30 + 90 })));
  await assertSucceeds(update(ref(asAgentA1(), "apps/rpa/commands/ca/pc1/c4"), { state: "running", started_at: 1100 }));   // 고칠 때는 시각을 다시 보지 않는다
});

test("commands: 에이전트는 명령을 고치기만 하고 지울 수 없다 (BugBuster L16)", async () => {
  await assertSucceeds(set(ref(asAdminA(), "apps/rpa/commands/ca/pc1/c1"), cmd()));
  await assertFails(remove(ref(asAgentA1(), "apps/rpa/commands/ca/pc1/c1")));
  await assertFails(set(ref(asAgentA1(), "apps/rpa/commands/ca/pc1/c1"), null));
  await assertFails(remove(ref(asAgentA1(), "apps/rpa/commands/ca/pc1")));
  await assertSucceeds(update(ref(asAgentA1(), "apps/rpa/commands/ca/pc1/c1"), { state: "expired" }));
});

test("commands: 에이전트가 type 을 바꾸면 거부", async () => {
  await assertSucceeds(set(ref(asAdminA(), "apps/rpa/commands/ca/pc1/c1"), cmd()));
  await assertFails(update(ref(asAgentA1(), "apps/rpa/commands/ca/pc1/c1"), { type: "stop_erpia" }));
});

test("settings: 관리자는 쓰고, 열람자는 못 쓰고, 그 PC 의 에이전트는 읽는다", async () => {
  await assertSucceeds(set(ref(asAdminA(), "apps/rpa/settings/ca/pc1"), {
    modules: { Login: true, Sales: false, Hold: true, Logistics: true, Output: true },
    updated_by: "u_admin_a", updated_at: 1000,
  }));
  await assertFails(set(ref(asViewerA(), "apps/rpa/settings/ca/pc1"), { modules: { Login: false } }));
  await assertSucceeds(get(ref(asAgentA1(), "apps/rpa/settings/ca/pc1")));
  await assertFails(get(ref(asAdminB(), "apps/rpa/settings/ca/pc1")));
});

// ---------------------------------------------------------------------------
// 휴대폰 인증번호 중계 apps/otp (2026-10-12, specs/2026-10-12-phone-otp-relay-design.md)
// ---------------------------------------------------------------------------
const asPhoneA1 = () => env.authenticatedContext("u_phone_a1", { cid: "ca", phoneId: "ph1", role: "phone" }).database();
const asPhoneA2 = () => env.authenticatedContext("u_phone_a2", { cid: "ca", phoneId: "ph2", role: "phone" }).database();
const asPhoneB1 = () => env.authenticatedContext("u_phone_b1", { cid: "cb", phoneId: "ph1", role: "phone" }).database();
const REQ = "apps/otp/requests/ca/ph1/current";
const CODE = "apps/otp/codes/ca/ph1/current";
const otpReq = (over = {}) => ({
  req_id: "req_abcdef12", site: "가나몰", senders: { "15881234": true }, pcId: "pc1", created_at: serverTimestamp(), ...over,
});
const otpCode = (over = {}) => ({
  req_id: "req_abcdef12", code: "123456", sender: "15881234", sms_at: 1000, written_at: serverTimestamp(), ...over,
});
const putReqRaw = (over = {}) => env.withSecurityRulesDisabled(async (c) => {
  await set(ref(c.database(), REQ), { ...otpReq(), created_at: Date.now(), ...over });
});

test("otp: 휴대폰 계정은 cid 가 같아도 업체 자료(현황·설정·명령·업체 정보)를 못 읽는다", async () => {
  for (const p of ["apps/rpa/live/ca/pc1", "apps/rpa/settings/ca/pc1", "apps/rpa/commands/ca/pc1", "meta/companies/ca", "apps/otp/phones/ca/ph1"]) {
    await assertFails(get(ref(asPhoneA1(), p)));
  }
});

test("otp: 휴대폰 계정은 Firestore 의 기록·통장·값표·배율도 못 읽는다", async () => {
  const fsPhone = env.authenticatedContext("u_phone_a1", { cid: "ca", phoneId: "ph1", role: "phone" }).firestore();
  await env.withSecurityRulesDisabled(async (c) => {
    await setDoc(doc(c.firestore(), "runs/ca/items/r1"), run());
    await setDoc(doc(c.firestore(), "wallet/ca"), { granted: 1 });
    await setDoc(doc(c.firestore(), "meta/prices"), { default: 1 });
    await setDoc(doc(c.firestore(), "prices/ca"), { sales: 1 });
  });
  for (const p of ["runs/ca/items/r1", "wallet/ca", "meta/prices", "prices/ca"]) await assertFails(getDoc(doc(fsPhone, p)));
  await assertSucceeds(getDoc(doc(fsAgentA1(), "meta/prices")));      // 다른 계정은 그대로
});

test("otp 요청: 에이전트가 자기 PC 이름·서버 시각으로 연다, 휴대폰은 자기 것만 읽는다", async () => {
  await assertSucceeds(set(ref(asAgentA1(), REQ), otpReq()));
  await assertSucceeds(get(ref(asPhoneA1(), REQ)));
  await assertSucceeds(get(ref(asViewerA(), REQ)));                     // 대시보드 STAND BY 표시
  await assertFails(get(ref(asPhoneA2(), REQ)));                        // 같은 업체 다른 휴대폰
  await assertFails(get(ref(asPhoneB1(), REQ)));                        // 다른 업체
  await assertFails(get(ref(asAdminB(), REQ)));
});

test("otp 요청: 시각 위조·PC 위조·발신번호 없음·이상한 발신번호·모르는 칸은 거부, 관리자·휴대폰은 못 연다", async () => {
  await assertFails(set(ref(asAgentA1(), REQ), otpReq({ created_at: Date.now() })));
  await assertFails(set(ref(asAgentA1(), REQ), otpReq({ pcId: "pc2" })));
  await assertFails(set(ref(asAgentA1(), REQ), otpReq({ senders: null })));
  await assertFails(set(ref(asAgentA1(), REQ), otpReq({ senders: { "1588-1234": true } })));
  await assertFails(set(ref(asAgentA1(), REQ), otpReq({ body: "본문" })));
  await assertFails(set(ref(asAdminA(), REQ), otpReq()));
  await assertFails(set(ref(asPhoneA1(), REQ), otpReq()));
});

test("otp 요청: 남의 PC 가 연 요청은 2분 안에 덮거나 지우지 못하고, 지나면 된다. 자기 것은 언제든", async () => {
  await assertSucceeds(set(ref(asAgentA1(), REQ), otpReq()));
  await assertFails(set(ref(asAgentA2(), REQ), otpReq({ pcId: "pc2" })));
  await assertFails(remove(ref(asAgentA2(), REQ)));
  await assertSucceeds(set(ref(asAgentA1(), REQ), otpReq({ req_id: "req_again123" })));
  await assertSucceeds(remove(ref(asAgentA1(), REQ)));
  await putReqRaw({ created_at: Date.now() - 121000 });
  await assertSucceeds(set(ref(asAgentA2(), REQ), otpReq({ pcId: "pc2" })));
});

test("otp 번호: 열린 요청·같은 req_id·발신번호 일치·숫자 4~8자리일 때만 자기 휴대폰이 쓴다", async () => {
  await assertFails(set(ref(asPhoneA1(), CODE), otpCode()));                        // 요청 없음
  await putReqRaw();
  await assertFails(set(ref(asPhoneA1(), CODE), otpCode({ req_id: "req_other123" })));
  await assertFails(set(ref(asPhoneA1(), CODE), otpCode({ sender: "16001111" })));   // 은행 등 다른 발신번호
  for (const code of ["12a456", "123", "123456789", 123456]) await assertFails(set(ref(asPhoneA1(), CODE), otpCode({ code })));
  await assertFails(set(ref(asPhoneA1(), CODE), otpCode({ written_at: Date.now() })));
  await assertFails(set(ref(asPhoneA1(), CODE), otpCode({ body: "본문" })));
  await assertFails(set(ref(asPhoneA2(), CODE), otpCode()));                        // 다른 휴대폰
  await assertFails(set(ref(asPhoneB1(), "apps/otp/codes/ca/ph1/current"), otpCode()));   // 다른 업체
  await assertFails(set(ref(asAgentA1(), CODE), otpCode()));                        // 에이전트는 지우기만
  await assertSucceeds(set(ref(asPhoneA1(), CODE), otpCode()));
});

test("otp 번호: 2분 지난 요청엔 못 쓴다", async () => {
  await putReqRaw({ created_at: Date.now() - 121000 });
  await assertFails(set(ref(asPhoneA1(), CODE), otpCode()));
});

test("otp 번호: 요청을 연 PC 의 에이전트만 읽고 지운다. 휴대폰·관리자는 못 읽는다", async () => {
  await putReqRaw();
  await assertSucceeds(set(ref(asPhoneA1(), CODE), otpCode()));
  await assertSucceeds(get(ref(asAgentA1(), CODE)));
  for (const who of [asAgentA2, asPhoneA1, asAdminA, asViewerA]) await assertFails(get(ref(who(), CODE)));
  await assertFails(remove(ref(asAgentA2(), CODE)));                    // 남의 PC 가 연 요청의 번호는 못 지운다 (BugBuster M7)
  await assertSucceeds(remove(ref(asAgentA1(), CODE)));
});

test("otp 번호: 요청이 없거나 2분 지났으면 같은 업체 에이전트가 지운다, 다른 업체는 못 지운다 (BugBuster M7)", async () => {
  const putCodeRaw = () => env.withSecurityRulesDisabled(async (c) => { await set(ref(c.database(), CODE), { ...otpCode(), written_at: Date.now() }); });
  await putCodeRaw();
  await assertFails(remove(ref(asAgentB1(), CODE)));
  await assertSucceeds(remove(ref(asAgentA2(), CODE)));                 // 요청 없음
  await putReqRaw({ created_at: Date.now() - 121000 });
  await putCodeRaw();
  await assertSucceeds(remove(ref(asAgentA2(), CODE)));                 // 지난 요청
});

test("otp 휴대폰 표시: 자기 것만 서버 시각으로 쓰고, 같은 업체 화면이 읽는다", async () => {
  const me = { os: "android", app_version: "1", last_seen: serverTimestamp() };
  await assertSucceeds(set(ref(asPhoneA1(), "apps/otp/phones/ca/ph1"), me));
  await assertFails(set(ref(asPhoneA1(), "apps/otp/phones/ca/ph2"), me));
  await assertFails(set(ref(asPhoneA1(), "apps/otp/phones/ca/ph1"), { ...me, last_seen: 1 }));
  await assertFails(set(ref(asPhoneA1(), "apps/otp/phones/ca/ph1"), { ...me, os: "windows" }));
  await assertSucceeds(get(ref(asViewerA(), "apps/otp/phones/ca/ph1")));
  await assertFails(get(ref(asAdminB(), "apps/otp/phones/ca/ph1")));
});

test("meta: super 만 쓴다", async () => {
  await assertFails(set(ref(asAdminA(), "meta/companies/ca"), { name: "위조" }));
  await assertSucceeds(set(ref(asSuper(), "meta/companies/ca"), { name: "테스트 회사" }));
});

// ---------------------------------------------------------------------------
// Firestore
// ---------------------------------------------------------------------------
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

// 토큰 (2026-10-06): 실행 기록 한 장에 쓴 것(used)·쓴 토큰(cost). 남은 토큰 = wallet.granted - 기록들의 cost 합
test("runs: 쓴 토큰은 0 이상 정수, 쓴 것은 map (없으면 옛 에이전트 - 그대로 받는다)", async () => {
  await assertSucceeds(setDoc(doc(fsAgentA1(), "runs/ca/items/r1"), run({ used: { sales: 1, login: 1 }, cost: 1 })));
  await assertFails(setDoc(doc(fsAgentA1(), "runs/ca/items/r2"), run({ run_id: "r2", cost: -1 })));
  await assertFails(setDoc(doc(fsAgentA1(), "runs/ca/items/r3"), run({ run_id: "r3", cost: 1.5 })));
  await assertFails(setDoc(doc(fsAgentA1(), "runs/ca/items/r4"), run({ run_id: "r4", cost: "1" })));
  await assertFails(setDoc(doc(fsAgentA1(), "runs/ca/items/r5"), run({ run_id: "r5", used: "sales" })));
});

test("runs: 에이전트는 자기 회사 기록의 쓴 토큰을 서버에서 더하고, 다른 회사 것은 거부", async () => {
  await env.withSecurityRulesDisabled(async (c) => {
    await setDoc(doc(c.firestore(), "runs/ca/items/r1"), run({ cost: 2 }));
    await setDoc(doc(c.firestore(), "runs/ca/items/r2"), run({ run_id: "r2", cost: 3 }));
  });
  const got = await assertSucceeds(getAggregateFromServer(collection(fsAgentA1(), "runs/ca/items"), { s: sum("cost") }));
  assert.equal(got.data().s, 5);
  const fsAgentB1 = env.authenticatedContext("u_agent_b1", { cid: "cb", pcId: "pc1", role: "agent" }).firestore();
  await assertFails(getAggregateFromServer(collection(fsAgentB1, "runs/ca/items"), { s: sum("cost") }));
});

test("meta/prices: 로그인한 사람은 읽고 아무도 못 쓴다 (값표는 setup.js 만)", async () => {
  await env.withSecurityRulesDisabled(async (c) => {
    await setDoc(doc(c.firestore(), "meta/prices"), { default: 1, login: 0 });
  });
  await assertSucceeds(getDoc(doc(fsAgentA1(), "meta/prices")));
  await assertSucceeds(getDoc(doc(fsAdminB(), "meta/prices")));
  await assertFails(getDoc(doc(env.unauthenticatedContext().firestore(), "meta/prices")));
  await assertFails(setDoc(doc(fsSuper(), "meta/prices"), { default: 0 }));
  await assertFails(setDoc(doc(fsAgentA1(), "meta/prices"), { default: 0 }));
});

test("prices/{cid}: 업체 배율은 그 업체와 super 만 읽고 아무도 못 쓴다 (관리 화면만, 사용자 2026-10-08)", async () => {
  await env.withSecurityRulesDisabled(async (c) => {
    await setDoc(doc(c.firestore(), "prices/ca"), { sales: 5 });
  });
  for (const who of [fsAgentA1(), fsAdminA(), fsSuper()]) await assertSucceeds(getDoc(doc(who, "prices/ca")));
  await assertFails(getDoc(doc(fsAdminB(), "prices/ca")));
  await assertFails(getDoc(doc(env.unauthenticatedContext().firestore(), "prices/ca")));
  for (const who of [fsAgentA1(), fsAdminA(), fsSuper()]) await assertFails(setDoc(doc(who, "prices/ca"), { sales: 0 }));
});

test("wallet: 같은 회사와 super 는 읽고 다른 회사는 거부, 아무도 못 쓴다 (넣기는 setup.js 만)", async () => {
  await env.withSecurityRulesDisabled(async (c) => {
    await setDoc(doc(c.firestore(), "wallet/ca"), { granted: 100 });
    await setDoc(doc(c.firestore(), "wallet/ca/grants/g1"), { amount: 100, at: "2026-10-06T12:00:00", memo: "첫 결제" });
  });
  for (const who of [fsAgentA1(), fsAdminA(), fsSuper()]) await assertSucceeds(getDoc(doc(who, "wallet/ca")));
  for (const who of [fsAgentA1(), fsAdminA()]) await assertFails(getDoc(doc(who, "wallet/ca/grants/g1")));   // 넣은 내역은 super 만 (BugBuster L17)
  await assertSucceeds(getDoc(doc(fsSuper(), "wallet/ca/grants/g1")));
  await assertFails(getDoc(doc(fsAdminB(), "wallet/ca")));
  await assertFails(getDoc(doc(fsAdminB(), "wallet/ca/grants/g1")));
  for (const who of [fsAgentA1(), fsAdminA(), fsSuper()]) {
    await assertFails(updateDoc(doc(who, "wallet/ca"), { granted: 999 }));
    await assertFails(setDoc(doc(who, "wallet/ca/grants/g2"), { amount: 999 }));
  }
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

// ---------------------------------------------------------------------------
// 프리셋 전송 자리 apps/rpa/transfers (2026-10-19, specs/2026-10-19-preset-transfer-design.md 5절)
// ---------------------------------------------------------------------------
const asAgentB1 = () => env.authenticatedContext("u_agent_b1", { cid: "cb", pcId: "pc1", role: "agent" }).database();
const TID = "abcdef0123456789abcd";
const TR = `apps/rpa/transfers/ca/${TID}`;
const T0 = Date.now();      // 규칙이 만든 시각을 서버 시각 ±10분만 받는다 (2026-10-21)
const transfer = (over = {}) => ({
  by: "u_admin_a", from_pc: "pc1", created_at: T0, expires_at: T0 + 6 * 3600 * 1000,
  presets: [{ kind: "autopilot-preset", version: 1, no: 1, name: "가나몰", code: "001", record: { steps: [] } }],
  ...over,
});
const putTransferRaw = () => env.withSecurityRulesDisabled(async (c) => { await set(ref(c.database(), TR), transfer()); });

test("transfers: 그 업체 에이전트가 자기 PC 이름으로 만든다, 남의 PC 이름·관리자는 거부", async () => {
  await assertSucceeds(set(ref(asAgentA1(), TR), transfer()));
  await assertFails(set(ref(asAgentA1(), `apps/rpa/transfers/ca/${TID.replace("a", "b")}`), transfer({ from_pc: "pc2" })));
  await assertFails(set(ref(asAdminA(), `apps/rpa/transfers/ca/${TID.replace("a", "c")}`), transfer()));
  await assertFails(set(ref(asAgentB1(), `apps/rpa/transfers/ca/${TID.replace("a", "d")}`), transfer()));
});

test("transfers: 만료 7시간·by 없음·모르는 칸·짧은 id 는 거부", async () => {
  await assertFails(set(ref(asAgentA1(), TR), transfer({ expires_at: T0 + 7 * 3600 * 1000 })));
  await assertFails(set(ref(asAgentA1(), TR), transfer({ by: null })));
  await assertFails(set(ref(asAgentA1(), TR), transfer({ by: 1 })));
  await assertFails(set(ref(asAgentA1(), TR), transfer({ extra: 1 })));
  await assertFails(set(ref(asAgentA1(), "apps/rpa/transfers/ca/short"), transfer()));
  await assertFails(set(ref(asAgentA1(), "apps/rpa/transfers/ca/" + "x".repeat(41)), transfer()));
});

test("transfers: 만든 시각이 서버 시각과 10분 넘게 다르면 거부 - PC 시계로 만료를 늘리지 못한다 (2026-10-21)", async () => {
  const h = 3600 * 1000;
  await assertFails(set(ref(asAgentA1(), TR), transfer({ created_at: T0 + 2 * h, expires_at: T0 + 8 * h })));
  await assertFails(set(ref(asAgentA1(), TR), transfer({ created_at: 1000, expires_at: 1000 + 6 * h })));
  await assertSucceeds(set(ref(asAgentA1(), TR), transfer({ created_at: T0 + 5 * 60000, expires_at: T0 + 5 * 60000 + 6 * h })));
});

test("transfers: 보내기 실패 표시(failed)는 프리셋 없이 받는다, 둘 다 없거나 200자 넘으면 거부 (2026-10-21)", async () => {
  await assertSucceeds(set(ref(asAgentA1(), TR), transfer({ presets: null, failed: "프리셋 2에 기록이 없습니다." })));
  await assertFails(set(ref(asAgentA1(), `apps/rpa/transfers/ca/${TID.replace("a", "e")}`), transfer({ presets: null })));
  await assertFails(set(ref(asAgentA1(), `apps/rpa/transfers/ca/${TID.replace("a", "f")}`), transfer({ presets: null, failed: "가".repeat(201) })));
  await assertFails(set(ref(asAgentA1(), `apps/rpa/transfers/ca/${TID.replace("a", "g")}`), transfer({ presets: null, failed: 1 })));
});

test("transfers: 업체 목록(shallow)은 그 업체 에이전트·super 가 읽고 관리자·열람자·다른 업체는 못 읽는다 (cleanup_transfers)", async () => {
  await putTransferRaw();
  await assertSucceeds(get(ref(asAgentA2(), "apps/rpa/transfers/ca")));
  await assertSucceeds(get(ref(asSuper(), "apps/rpa/transfers/ca")));
  for (const who of [asAdminA, asViewerA, asAgentB1, asAnon]) await assertFails(get(ref(who(), "apps/rpa/transfers/ca")));
});

test("transfers: 받는 PC 에이전트가 한 건을 읽고 지운다, 관리자·다른 업체는 읽기·쓰기 거부, super 는 읽는다", async () => {
  await putTransferRaw();
  await assertSucceeds(get(ref(asAgentA2(), TR)));
  await assertSucceeds(get(ref(asSuper(), TR)));
  for (const who of [asAdminA, asViewerA, asAgentB1]) await assertFails(get(ref(who(), TR)));
  await assertFails(set(ref(asAdminA(), TR), transfer({ by: "u_admin_a" })));
  await assertFails(remove(ref(asAdminA(), TR)));
  await assertFails(remove(ref(asAgentB1(), TR)));
  await assertFails(set(ref(asAgentA2(), TR), transfer({ from_pc: "pc2" })));   // 있는 것 덮어쓰기는 안 된다
  await assertSucceeds(remove(ref(asAgentA2(), TR)));
});

test("commands: export_preset·import_preset·restore_preset 은 관리자가 만들 수 있다", async () => {
  await assertSucceeds(set(ref(asAdminA(), "apps/rpa/commands/ca/pc1/c1"), cmd({ type: "export_preset", args: { tid: TID, nos: [1], with_phone: true } })));
  await assertSucceeds(set(ref(asAdminA(), "apps/rpa/commands/ca/pc2/c2"), cmd({ type: "import_preset", args: { tid: TID, slots: [1] } })));
  await assertSucceeds(set(ref(asAdminA(), "apps/rpa/commands/ca/pc1/c3"), cmd({ type: "restore_preset", args: { nos: [1] } })));
  await assertFails(set(ref(asViewerA(), "apps/rpa/commands/ca/pc2/c4"), cmd({ type: "import_preset", by: "u_view_a", args: { tid: TID, slots: [1] } })));
});
