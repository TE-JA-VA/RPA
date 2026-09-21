// RTDB 보안 규칙 시험. 에뮬레이터가 떠 있어야 한다 (npm test 가 띄운다).
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import test, { before, after, beforeEach } from "node:test";
import {
  initializeTestEnvironment, assertFails, assertSucceeds,
} from "@firebase/rules-unit-testing";
import { ref, set, update, get } from "firebase/database";

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
