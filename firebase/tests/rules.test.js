// RTDB 보안 규칙 시험. 에뮬레이터가 떠 있어야 한다 (npm test 가 띄운다).
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import assert from "node:assert/strict";
import test, { before, after, beforeEach } from "node:test";
import {
  initializeTestEnvironment, assertFails, assertSucceeds,
} from "@firebase/rules-unit-testing";
import { ref, set, update, get } from "firebase/database";
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
  await assertSucceeds(set(ref(asAgentA1(), "apps/rpa/live/ca/pc1"), { host: "PC1", programs: {} }));
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

test("commands: resume_repeat 는 관리자가 만들 수 있다 (반복 다시 시작)", async () => {
  await assertSucceeds(set(ref(asAdminA(), "apps/rpa/commands/ca/pc1/c1"), cmd({ type: "resume_repeat", args: null })));
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

test("wallet: 같은 회사와 super 는 읽고 다른 회사는 거부, 아무도 못 쓴다 (넣기는 setup.js 만)", async () => {
  await env.withSecurityRulesDisabled(async (c) => {
    await setDoc(doc(c.firestore(), "wallet/ca"), { granted: 100 });
    await setDoc(doc(c.firestore(), "wallet/ca/grants/g1"), { amount: 100, at: "2026-10-06T12:00:00", memo: "첫 결제" });
  });
  for (const who of [fsAgentA1(), fsAdminA(), fsSuper()]) {
    await assertSucceeds(getDoc(doc(who, "wallet/ca")));
    await assertSucceeds(getDoc(doc(who, "wallet/ca/grants/g1")));
  }
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
