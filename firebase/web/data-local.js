// 스탠드얼론 버전의 데이터 자리 - 이 PC 의 로컬 서버(http://127.0.0.1:<포트>/api)를 부른다 (스탠드얼론 ② Task 3, 설계 6.3·6.5절).
// data.js 가 edition.js 를 보고 이 파일을 동적 import 한다. 이름·모양은 data-firebase.js 와 같다 (화면 코드는 둘을 구별하지 않는다).
//
// - 로그인은 탭 단위: 세션 토큰은 탭 저장소 sessionStorage["ap.session"] 에만 두고 요청마다 Authorization: Bearer 로 보낸다 (쿠키 없음).
// - 현황·명령은 스트림 하나(GET /api/stream)로 받는다. EventSource 는 머리글을 못 실어 fetch 로 읽는다. 받은 값을 기억해 두고
//   watch() 자리 글(apps/rpa/live/…, apps/rpa/commands/…, meta/companies/…)에 맞춰 나눠 준다.
// - 스트림이 끊기면 1·2·4…30초 물러서며 다시 붙는다. 서버가 세션을 끝냈으면(401·gone) 세션을 지우고 onSession(null).
// - 늦게 온 응답은 버린다: 로그인·로그아웃마다 세션 번호(gen)를 올리고, 응답이 왔을 때 번호가 다르면 쓰지 않는다.
// 바깥 주소는 부르지 않는다 (같은 출처의 /api 만).

const TOKEN_KEY = "ap.session", UID_KEY = "ap.uid";
const TOUCH_EVERY_MS = 60000;            // 미사용 시계 되돌리기는 1분에 한 번까지 (app.js 는 입력을 5초에 한 번 알린다)
const BACKOFF_MIN_MS = 1000, BACKOFF_MAX_MS = 30000;
const CMD_CACHE_MAX = 200;

let token = null;          // 세션 토큰
let uid = null;            // 그 세션의 아이디 - 서버에 못 닿아도 sessionUid() 가 답하게 탭 저장소에도 둔다
let session = null;        // {uid, email, cid, role, mustChange} (서버가 확인한 것)
let restoreFailed = false; // init 에서 토큰은 있는데 서버에 못 닿았다 → onSession 이 {error: "network"}
let gen = 0;               // 세션 번호 (로그인·로그아웃마다 +1)
let company = null;        // GET /api/company 값 (meta/companies/… 자리를 여기서 채운다)
let skewOff = 0, skewP = null, lastTouch = 0;
const listeners = new Set();

const store = {
  get(k) { try { return sessionStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { if (v == null) sessionStorage.removeItem(k); else sessionStorage.setItem(k, v); } catch {} },
};

function fail(code, message, status) {
  const e = new Error(message || code);
  e.code = code; e.status = status;
  return e;
}

/** /api 요청 하나 → JSON 값. 실패는 e.code (서버가 준 code, 못 닿으면 "unavailable") 와 e.status */
async function call(method, path, body, tok = token) {
  const headers = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (tok) headers.Authorization = `Bearer ${tok}`;
  let r;
  try {
    r = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), cache: "no-store" });
  } catch {
    throw fail("unavailable", "오토파일럿 서버에 연결하지 못했습니다.", 0);
  }
  let v = null;
  try { v = await r.json(); } catch {}
  if (!r.ok) throw fail(v?.code || `http-${r.status}`, v?.message, r.status);
  return v;
}

/** 로그인한 세션으로 부른다. 401 이면 (그 사이 다른 세션이 되지 않았다면) 세션을 끝낸다 */
async function authed(method, path, body) {
  const tok = token;
  try {
    return await call(method, path, body, tok);
  } catch (e) {
    if (e.status === 401 && tok && tok === token) ended();
    throw e;
  }
}

const pub = (s) => ({ uid: s.uid, email: s.email, cid: s.cid, role: s.role, mustChange: !!s.mustChange });
function emit(value) {
  for (const cb of [...listeners]) {
    try { cb(value); } catch (e) { queueMicrotask(() => { throw e; }); }
  }
}
function setSkew(nowMs) { if (Number.isFinite(nowMs)) { skewOff = nowMs - Date.now(); skewP = Promise.resolve(); } }

function begin(tok, s) {
  gen++;
  token = tok; session = s; uid = s.uid; restoreFailed = false; lastTouch = Date.now();
  store.set(TOKEN_KEY, tok); store.set(UID_KEY, s.uid);
  startStream();
}
function clear() {
  gen++;
  token = null; session = null; uid = null; restoreFailed = false; company = null; skewP = null; lastTouch = 0;
  store.set(TOKEN_KEY, null); store.set(UID_KEY, null);
  stopStream();
  liveVal = null; liveKnown = false; cmdCache.clear();
}
/** 서버가 세션을 끝냈다 (401·gone) - 로그인 화면으로 */
function ended() {
  if (!token) return;
  clear();
  emit(null);
}

// --- 로그인 ------------------------------------------------------------
/** 탭 저장소의 토큰을 서버에 물어 되살린다. 401 이면 지운다. 서버에 못 닿으면 토큰은 두고 onSession 이 network 를 알린다 */
export async function init() {
  const tok = store.get(TOKEN_KEY);
  if (!tok) return;
  const my = gen;
  try {
    const v = await call("GET", "/api/session", undefined, tok);
    if (my !== gen) return;                 // 기다리는 사이 새로 로그인했다 - 늦게 온 옛 세션은 버린다
    setSkew(v.now_ms);
    begin(tok, v.session);
  } catch (e) {
    if (my !== gen) return;
    if (e.status === 401) { clear(); return; }
    token = tok; uid = store.get(UID_KEY); restoreFailed = true;
  }
}

export const handoffFailed = () => false;    // 관리 화면 열쇠(#t=) 로그인은 스탠드얼론에 없다

/** cb(null) 로그아웃, cb({uid, email, cid, role, mustChange}) 로그인, cb({error: "network"}) 서버에 못 닿음 - 처음 한 번은 지금 상태로 */
export function onSession(cb) {
  listeners.add(cb);
  const my = gen;
  setTimeout(() => {
    if (!listeners.has(cb) || my !== gen) return;    // 그 사이 로그인·로그아웃이 있었다 - 그쪽에서 이미 알렸다
    try { cb(restoreFailed ? { error: "network" } : session ? pub(session) : null); } catch (e) { queueMicrotask(() => { throw e; }); }
  }, 0);
  return () => listeners.delete(cb);
}

/** 아이디·비밀번호로 로그인 (cid 는 보내지 않는다 - PC 하나에 업체 하나). 실패는 e.code (auth/*) */
export async function signIn(cid, id, password) {
  let v;
  try {
    v = await call("POST", "/api/login", { id, password }, null);
  } catch (e) {
    if (e.code === "unavailable") e.code = "auth/network-request-failed";
    throw e;
  }
  if (token) { const old = token; clear(); call("POST", "/api/logout", {}, old).catch(() => {}); }   // 이 탭의 앞 로그인은 닫는다
  begin(v.token, v.session);
  skewP = null;
  emit(pub(v.session));
}

export async function signOut() {
  const old = token;
  clear();
  if (old) await call("POST", "/api/logout", {}, old).catch(() => {});
  emit(null);
}
export const signedIn = () => !!token;
export const sessionUid = () => (token ? (session?.uid ?? uid) : null);

/** 현재 비밀번호를 확인하고 바꾼다. 실패는 e.code (auth/wrong-password·auth/weak-password·auth/too-many-requests) */
export async function changePassword(current, next) {
  const my = gen;
  const v = await authed("POST", "/api/password", { current, next });
  if (my === gen && v?.session) session = v.session;
}

/** 미사용 시계를 서버에도 되돌린다 - app.js 가 입력을 적을 때 부른다 (1분에 한 번까지) */
export function touch() {
  if (!token || Date.now() - lastTouch < TOUCH_EVERY_MS) return;
  lastTouch = Date.now();
  const my = gen;
  authed("GET", "/api/session?touch=1").then((v) => { if (my === gen) setSkew(v?.now_ms); }, () => {});
}

export const emailFor = undefined;           // 일반 버전 전용 (아이디를 그대로 쓴다)

// --- 업체 · 기록 ---------------------------------------------------------
/** 업체 정보 {name, stts, pcs, apps} - 이 PC 의 라이선스에서. 못 읽으면 {} */
export async function getCompany(cid) {
  const my = gen;
  try {
    const v = await authed("GET", "/api/company");
    if (my === gen) company = v;
    return { name: v.name, stts: v.stts, pcs: v.pcs, apps: v.apps };
  } catch { return {}; }
}

/** 실행 기록 - 이 PC 것만 (서버가 정한다), 날짜를 주면 그날만, 최신 순으로 limit 개 */
export async function listRuns(cid, { pcId, date, limit }) {
  const q = new URLSearchParams();
  if (date) q.set("date", date);
  if (limit) q.set("limit", String(limit));
  const v = await authed("GET", `/api/runs?${q}`);
  return v?.runs || [];
}

// 토큰은 스탠드얼론에 없다 (1회 구매) - 통장 없음
export const getWallet = async () => null;
export const watchWallet = () => () => {};
export const sumRuns = async () => 0;

// 설정은 명령(set_modules 등)에 실어 보낸다 - 클라우드의 settings 자리는 없다
export const saveSettings = async () => {};

/** 명령 하나를 넣고 키를 돌려준다. 보내는 것은 종류·인자뿐 (by·시각·상태는 서버가 정한다) */
export async function pushCommand(cid, pcId, command) {
  const v = await authed("POST", "/api/commands", { type: command.type, args: command.args ?? null });
  if (v?.key) remember(v.key, v.value ?? null);
  return v.key;
}

// 서버 시각 - 브라우저 시각 (명령 시각은 서버가 적지만 화면의 남은 시간 계산에 쓴다)
export function skewReady() {
  if (!skewP) {
    const my = gen;
    skewP = (token ? authed("GET", "/api/session") : Promise.reject()).then((v) => { if (my === gen) setSkew(v?.now_ms); }, () => {});
  }
  return skewP;
}
export const skewMs = () => skewOff;

// --- 계정 관리 (관리자, 계획 ② Task 4) ----------------------------------------------
/** [{id, role, disabled, mustChange}] - 실패는 e.code·e.message (서버의 사람 말) */
export const listAccounts = async () => (await authed("GET", "/api/accounts")).accounts || [];
export const addAccount = async (id, password, role) => (await authed("POST", "/api/accounts", { id, password, role })).accounts || [];
/** change = {disabled} 또는 {password} */
export const updateAccount = async (id, change) => (await authed("POST", `/api/accounts/${encodeURIComponent(id)}`, change)).accounts || [];
export const removeAccount = async (id) => (await authed("DELETE", `/api/accounts/${encodeURIComponent(id)}`)).accounts || [];

// --- 휴대폰 (관리자, 계획 ④ Task 3) ----------------------------------------------------
// 실패는 e.code (phone/firewall·phone/public-network·invalid-argument 등)·e.message (서버의 사람 말)
/** {phones: [{id, label, owner, senders, last_seen, os, device, stale, …}], gate: {open, port, firewall, hosts, fingerprint}} */
export const listPhones = async () => await authed("GET", "/api/phones");
/** 짝짓기 시작 → {qr, phone_id, expires_in, hosts, port, fingerprint}. QR 글은 이 응답에만 한 번 온다 (다시 받을 수 없다) */
export const startPhonePair = async ({ label, owner, senders }) => await authed("POST", "/api/phone-pair", { label, owner, senders });
/** {state: "none"|"waiting"|"paired"|"expired", left_sec?, phone?} - 화면이 2초마다 묻는다 (미사용 시계를 되돌리지 않는다) */
export const phonePairState = async () => await authed("GET", "/api/phone-pair");
export const cancelPhonePair = async () => await authed("DELETE", "/api/phone-pair");
/** change = {label?, owner?, senders?} (senders 가 빈 글이면 제한 없음) → {phones, gate} */
export const updatePhone = async (id, change) => await authed("POST", `/api/phones/${encodeURIComponent(id)}`, change);
export const removePhone = async (id) => await authed("DELETE", `/api/phones/${encodeURIComponent(id)}`);

// --- 지켜보기 (스트림 하나) -------------------------------------------------------
let liveVal = null, liveKnown = false;
const cmdCache = new Map();      // 명령 키 → 마지막으로 본 값 (스트림·보낸 응답·한 번 읽기)
const subs = new Set();          // {kind: "live"|"cmd", rest, key, cb, last, dead}

function remember(key, value) {
  cmdCache.delete(key);
  cmdCache.set(key, value);
  while (cmdCache.size > CMD_CACHE_MAX) cmdCache.delete(cmdCache.keys().next().value);
}
const at = (v, rest) => rest.reduce((o, k) => (o && typeof o === "object" ? o[k] : undefined), v) ?? null;

/** 값이 바뀌었을 때만 부른다 (Firebase onValue 처럼). 받는 쪽이 고쳐 써도 기억한 값이 바뀌지 않게 새 사본으로 준다 */
function deliver(sub, value) {
  if (sub.dead) return;
  const s = JSON.stringify(value ?? null);
  if (s === sub.last) return;
  sub.last = s;
  try { sub.cb(JSON.parse(s)); } catch (e) { queueMicrotask(() => { throw e; }); }
}
const later = (fn) => setTimeout(fn, 0);

/** 자리 하나를 지켜본다 - cb(값, 없으면 null). 그만 보려면 돌려준 함수를 부른다 */
export function watch(path, cb, onError) {
  const parts = String(path).split("/").filter(Boolean);
  const sub = { cb, last: undefined, dead: false };
  const off = () => { sub.dead = true; subs.delete(sub); };
  const mine = (cid, pc) => !!session && cid === session.cid && !!company && pc === company.pcId;
  if (parts[0] === "apps" && parts[1] === "rpa" && parts[2] === "live" && mine(parts[3], parts[4])) {
    Object.assign(sub, { kind: "live", rest: parts.slice(5) });
    subs.add(sub);
    if (liveKnown) later(() => deliver(sub, at(liveVal, sub.rest)));
  } else if (parts[0] === "apps" && parts[1] === "rpa" && parts[2] === "commands" && parts.length === 6 && mine(parts[3], parts[4])) {
    const key = parts[5];
    Object.assign(sub, { kind: "cmd", key });
    subs.add(sub);
    if (cmdCache.has(key)) later(() => deliver(sub, cmdCache.get(key)));
    else fetchCommand(key);
  } else if (parts[0] === "meta" && parts[1] === "companies" && session && parts[2] === session.cid) {
    const my = gen;
    (company ? Promise.resolve() : getCompany(parts[2])).then(() => { if (my === gen) deliver(sub, at(company, parts.slice(3))); });
  } else {
    later(() => deliver(sub, null));    // 다른 PC·업체 자리는 스탠드얼론에 없다
  }
  return off;
}

/** 명령 하나를 한 번 읽어 채운다 (스트림이 그 사이 더 새 값을 줬으면 그것을 둔다) */
function fetchCommand(key) {
  const my = gen;
  authed("GET", `/api/commands/${encodeURIComponent(key)}`).then((v) => {
    if (my !== gen || cmdCache.has(key)) return;
    remember(key, v ?? null);
    for (const sub of subs) if (sub.kind === "cmd" && sub.key === key) deliver(sub, v ?? null);
  }, () => {});
}

function onEvent(event, data) {
  if (event === "live") {
    liveVal = data; liveKnown = true;
    for (const sub of [...subs]) if (sub.kind === "live") deliver(sub, at(liveVal, sub.rest));
  } else if (event === "command" && data && typeof data.key === "string") {
    remember(data.key, data.value ?? null);
    for (const sub of [...subs]) if (sub.kind === "cmd" && sub.key === data.key) deliver(sub, data.value ?? null);
  }
}

let streamCtl = null, streamNo = 0, retryTimer = null, backoff = BACKOFF_MIN_MS;
function stopStream() {
  streamNo++;
  clearTimeout(retryTimer); retryTimer = null;
  if (streamCtl) { try { streamCtl.abort(); } catch {} streamCtl = null; }
  backoff = BACKOFF_MIN_MS;
}
function startStream() {
  stopStream();
  const my = streamNo, tok = token, ctl = new AbortController();
  streamCtl = ctl;
  const alive = () => my === streamNo && tok === token;
  (async () => {
    let fresh = true;            // 이 연결에서 아직 live 를 못 받았다 - 받으면 물러서기를 처음으로, 지켜보던 명령을 다시 채운다
    try {
      const r = await fetch("/api/stream", { headers: { Authorization: `Bearer ${tok}` }, signal: ctl.signal, cache: "no-store" });
      if (!alive()) return;
      if (r.status === 401) { ended(); return; }
      if (!r.ok || !r.body) throw new Error(`stream ${r.status}`);
      const reader = r.body.getReader(), dec = new TextDecoder();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (!alive()) { try { reader.cancel(); } catch {} return; }
        if (done) break;
        buf += dec.decode(value, { stream: true }).replace(/\r\n/g, "\n");
        let i;
        while ((i = buf.indexOf("\n\n")) >= 0) {
          const block = buf.slice(0, i);
          buf = buf.slice(i + 2);
          let event = "message", data = "";
          for (const line of block.split("\n")) {
            if (line.startsWith("event:")) event = line.slice(6).trim();
            else if (line.startsWith("data:")) data += line.slice(5).trim();
          }
          if (event === "gone") { ended(); return; }
          let value = null;
          try { value = data ? JSON.parse(data) : null; } catch { continue; }
          onEvent(event, value);
          if (event === "live" && fresh) {
            fresh = false; backoff = BACKOFF_MIN_MS;
            for (const key of new Set([...subs].filter((s) => s.kind === "cmd").map((s) => s.key))) { cmdCache.delete(key); fetchCommand(key); }
          }
        }
      }
    } catch {
      if (!alive()) return;
    }
    if (!alive()) return;
    // 끊겼다 (서버가 다시 켜짐 등) - 물러서며 다시 붙는다. 세션이 사라졌으면 다시 붙을 때 401 → 로그인 화면
    const wait = backoff;
    backoff = Math.min(backoff * 2, BACKOFF_MAX_MS);
    retryTimer = setTimeout(() => { if (alive()) reconnect(); }, wait);
  })();
}
function reconnect() {
  const keep = backoff;
  startStream();
  backoff = keep;                 // startStream 의 stopStream 이 물러서기를 처음으로 돌리지 않게
}
