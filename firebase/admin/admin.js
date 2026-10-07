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
  }, (b, r, p) => `PC 추가 ${p.cid}/${r.pc.pcId}${r.agent ? " + 에이전트 계정" : ""}`],
  ["POST", "/api/companies/:cid/users", (b, p) => ops.addUser(p.cid, b.id, b.role, b.name), (b, r, p) => `계정 추가 ${p.cid} ${r.email} (${r.role})`],
  ["POST", "/api/companies/:cid/passwd", (b, p) => ops.resetPassword(p.cid, b.id), (b, r, p) => `비밀번호 재발급 ${p.cid} ${r.email}`],
  ["POST", "/api/companies/:cid/disabled", (b, p) => ops.setDisabled(p.cid, b.id, b.disabled === true),
    (b, r, p) => `${r.disabled ? "사용중지" : "사용"} ${p.cid} ${r.email}`],
  ["POST", "/api/companies/:cid/modules", (b, p) => ops.setModules(p.cid, b),
    (b, r, p) => `모듈 정책 ${p.cid} ${Object.entries(b).map(([k, v]) => `${k}=${v}`).join(" ")}`],
  ["POST", "/api/companies/:cid/limits", (b, p) => ops.setScheduleLimit(p.cid, b.schedule), (b, r, p) => `자동 실행 개수 ${p.cid} = ${r.schedule}`],
  ["POST", "/api/companies/:cid/remove", (b, p) => {
    if (b.confirm !== p.cid) throw new ops.Refused("업체코드를 똑같이 쳐야 비활성화합니다");
    return ops.setCompanyRemoved(p.cid, true);
  }, (b, r, p) => `업체 비활성화 ${p.cid} (계정 ${r.users.length}개 사용중지)`],
  ["POST", "/api/companies/:cid/restore", (b, p) => ops.setCompanyRemoved(p.cid, false), (b, r, p) => (r.already ? null : `업체 다시 활성화 ${p.cid}`)],
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
    await serial(() => {});   // 하던 고치는 일을 끝낸 뒤 끈다 - 흐름 중간에 끊으면 claim 없는 반쪽 계정이 남고 다시 해도 '이미 있다' 로 건너뛴다
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
// try 밖에서 던져도 (new URL 이 못 읽는 요청 줄 등) 서버는 산다 - 흐름 중간에 죽으면 반쪽 계정이 남는다
const server = http.createServer((req, res) => handle(req, res).catch((e) => {
  console.error(e);
  if (res.headersSent) return res.destroy();
  res.writeHead(500, { "Content-Type": "application/json; charset=utf-8" });
  res.end(JSON.stringify({ error: "뜻밖의 오류 - 요청을 읽지 못했습니다" }));
}));
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
