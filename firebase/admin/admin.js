// 관리 화면 서버 (AFTERMARKET_SETUP) - setup.js 와 같은 일을 화면으로 (같은 ops.js). 우리 PC 에서만 돈다:
// 127.0.0.1 에서만 듣고, 켤 때마다 새 비밀 값을 만들어 연 주소(?k=)에만 싣는다. 화면은 /api 요청마다 X-Admin-Key 로 그 값을 보낸다 -
// 다른 사이트는 값을 모르고 다른 출처에서는 맞춤 머리글을 못 보낸다 (CORS 를 안 연다). Host 가 127.0.0.1:<포트> 가 아니면 거절.
// 비밀번호는 만든 응답에만 싣고 콘솔·기록에는 안 남긴다. 한 일은 관리_기록.txt 와 DB admin_log 에 한 줄씩 (비밀번호 없이). 고치는 요청은 하나씩.
// 작업 목록은 routes.js (Blaze 뒤 웹 관리 함수 ../functions/index.js 와 같이 쓴다).
//   node admin.js               켜고 기본 브라우저로 연다 (AFTERMARKET_SETUP.bat 이 부른다)
//   node admin.js --no-open     브라우저 없이 주소만 찍는다 (시험)
//   node admin.js --port 8790   포트를 정한다 (없으면 빈 포트)
//   node admin.js --shortcut    바탕화면에 'AFTER MARKET 관리' 바로 가기를 만든다 (한 번)
import http from "node:http";
import { randomBytes, timingSafeEqual } from "node:crypto";
import { readFileSync, appendFileSync, writeFileSync } from "node:fs";
import { execFileSync, spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

const here = (name) => fileURLToPath(new URL(name, import.meta.url));
const args = process.argv.slice(2);

if (args.includes("--shortcut")) {
  const q = (s) => `'${s.replaceAll("'", "''")}'`;       // PowerShell 작은따옴표 글
  execFileSync("powershell", ["-NoProfile", "-Command", [
    "$w = New-Object -ComObject WScript.Shell",
    `$l = $w.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) ${q("오토파일럿 관리.lnk")}))`,
    `$l.TargetPath = ${q(here("./AFTERMARKET_SETUP.bat"))}`,
    `$l.WorkingDirectory = ${q(here("./"))}`,
    `$l.IconLocation = ${q(here("../../release/AFTER_MARKET.ico"))}`,
    "$l.Save()"].join("; ")], { stdio: "inherit" });
  console.log("바탕화면에 '오토파일럿 관리' 바로 가기를 생성하였습니다.");
  process.exit(0);
}

const ops = await import("./ops.js");
const routes = await import("./routes.js");
const KEY = Buffer.from(randomBytes(32).toString("base64url"));
const PAGE = readFileSync(here("./AFTERMARKET_SETUP.html"));
const LOG = here("./관리_기록.txt");
// 한 일은 이 PC 의 관리_기록.txt 와 DB(admin_log - 웹 관리와 한 곳에 모인다, 2026-10-15)에. 둘 다 일을 막지 않는다 (DB 는 기다리지도 않는다)
const log = (line) => {
  try { appendFileSync(LOG, `${ops.nowKst()}  ${line}\n`, "utf8"); } catch { /* 기록은 일을 막지 않는다 */ }
  return ops.logToDb(line, null, "로컬");      // 실패해도 false 를 돌려줄 뿐 던지지 않는다
};

// 화면 테마 (밝게/어둡게) - 켤 때마다 포트가 바뀌어 브라우저 저장소로는 안 남는다 → 이 폴더의 파일에
const PREFS = here("./admin_prefs.json");
const readPrefs = () => { try { return JSON.parse(readFileSync(PREFS, "utf8")); } catch { return {}; } };
// 이 PC 에만 있는 요청 + 웹 관리 함수와 같이 쓰는 작업 목록 (routes.js - 작업을 늘릴 때는 거기 한 줄)
const ROUTES = [...routes.compile([
  ["GET", "/api/prefs", () => readPrefs()],
  ["POST", "/api/prefs", (b) => {
    const prefs = { ...readPrefs(), theme: ["light", "dark"].includes(b.theme) ? b.theme : null };
    writeFileSync(PREFS, JSON.stringify(prefs));
    return prefs;
  }],
]), ...routes.ROUTES];

// 고치는 요청은 한 번에 하나씩 - [만들기] 를 두 번 눌러도 두 번 만들지 않게 (늦은 쪽은 이미 있는 것을 건너뛴다)
let chain = Promise.resolve();
const serial = (fn) => { const run = chain.then(fn); chain = run.catch(() => {}); return run; };

const BODY_MAX = 65536, PRESET_BODY_MAX = 8 * 1048576;   // 프리셋 파일(기록 수십~수백 KB)을 올리는 요청만 크게
function readJson(req, max = BODY_MAX) {
  return new Promise((ok, fail) => {
    const chunks = [];
    let size = 0;
    req.on("data", (c) => {
      size += c.length;
      if (size > max) { fail(new ops.Refused("요청이 너무 큽니다.")); req.destroy(); } else chunks.push(c);
    });
    req.on("end", () => {
      try { ok(chunks.length ? JSON.parse(Buffer.concat(chunks).toString("utf8")) : {}); } catch { fail(new ops.Refused("요청 형식이 올바르지 않습니다.")); }
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
  if (req.headers.host !== `127.0.0.1:${port}`) return send(403, { error: "이 PC의 관리 화면 주소(127.0.0.1)로만 접속할 수 있습니다." });
  const path = new URL(req.url, "http://127.0.0.1").pathname;
  if (!path.startsWith("/api/")) return path === "/" && req.method === "GET" ? send(200, PAGE, "text/html; charset=utf-8") : send(404, { error: "존재하지 않는 주소입니다." });
  const got = Buffer.from(String(req.headers["x-admin-key"] ?? ""));
  if (got.length !== KEY.length || !timingSafeEqual(got, KEY)) {
    return send(403, { error: "비밀 값이 일치하지 않습니다. 관리 화면을 다시 실행하여 주십시오. (바탕화면 '오토파일럿 관리')" });
  }
  if (req.method === "POST" && path === "/api/quit") {
    await serial(() => {});   // 하던 고치는 일을 끝낸 뒤 끈다 - 흐름 중간에 끊으면 claim 없는 반쪽 계정이 남고 다시 해도 '이미 있다' 로 건너뛴다
    await log("관리 화면 끔");   // 곧 끝나므로 DB 기록만은 기다린다 (최대 ops.LOG_WAIT_MS)
    send(200, { ok: true });
    setTimeout(() => process.exit(0), 200);
    return;
  }
  const found = routes.find(ROUTES, req.method, path);
  if (!found) return send(404, { error: "알 수 없는 요청입니다." });
  const { route, params } = found;
  try {
    const body = req.method === "POST" ? await readJson(req, path.endsWith("/presets/import") ? PRESET_BODY_MAX : BODY_MAX) : {};
    const work = () => route.run(body, params);
    const result = await (req.method === "POST" ? serial(work) : work());
    const line = route.note?.(body, result, params);
    if (line) log(line);
    send(200, result);
  } catch (e) {
    if (e instanceof ops.Refused) return send(400, { error: e.message });
    console.error(e);
    send(500, { error: `예기치 않은 오류가 발생하였습니다. (${e.code ?? e.name}: ${e.message})` });
  }
}

const at = args.indexOf("--port");
// try 밖에서 던져도 (new URL 이 못 읽는 요청 줄 등) 서버는 산다 - 흐름 중간에 죽으면 반쪽 계정이 남는다
const server = http.createServer((req, res) => handle(req, res).catch((e) => {
  console.error(e);
  if (res.headersSent) return res.destroy();
  res.writeHead(500, { "Content-Type": "application/json; charset=utf-8" });
  res.end(JSON.stringify({ error: "예기치 않은 오류가 발생하였습니다. 요청을 읽지 못했습니다." }));
}));
server.on("error", (e) => { console.error(`오류: 관리 화면을 실행하지 못했습니다. (${e.code}) 이미 실행 중이면 해당 창을 사용하여 주십시오.`); process.exit(1); });
server.listen(at >= 0 ? Number(args[at + 1]) || 0 : 0, "127.0.0.1", () => {
  port = server.address().port;
  const url = `http://127.0.0.1:${port}/?k=${KEY}`;
  const where = ops.onEmulator() ? "에뮬레이터 (시험)" : `실제 서버 (${ops.PROJECT})`;
  console.log(`오토파일럿 관리 화면 - ${where}`);
  console.log(`  ${url}`);
  console.log("  브라우저가 열리지 않으면 위 주소로 접속하여 주십시오. 종료하려면 화면의 [끄기]를 누르거나 이 창을 닫아 주십시오.");
  log(`관리 화면 켬 - ${where}`);
  if (!args.includes("--no-open")) spawn("rundll32", ["url.dll,FileProtocolHandler", url], { detached: true, stdio: "ignore" }).unref();
});
