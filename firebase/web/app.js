import { initializeApp } from "https://www.gstatic.com/firebasejs/10.14.1/firebase-app.js";
import {
  getAuth, signInWithEmailAndPassword, signOut, onAuthStateChanged, connectAuthEmulator,
} from "https://www.gstatic.com/firebasejs/10.14.1/firebase-auth.js";
import {
  getDatabase, ref, onValue, get, push, set, connectDatabaseEmulator,
} from "https://www.gstatic.com/firebasejs/10.14.1/firebase-database.js";
import { firebaseConfig, HEARTBEAT_STALE_SEC, COMMAND_TTL_SEC } from "./firebase-config.js";

const app = initializeApp(firebaseConfig);
const auth = getAuth(app);
const db = getDatabase(app);
// 화면 시험용: 에뮬레이터 Hosting(127.0.0.1)에서 ?emu=1 로 열면 에뮬레이터에 붙는다. 실제 주소에서는 무시된다.
if (location.hostname === "127.0.0.1" && new URLSearchParams(location.search).get("emu") === "1") {
  connectAuthEmulator(auth, "http://127.0.0.1:9099", { disableWarnings: true });
  connectDatabaseEmulator(db, "127.0.0.1", 9000);
}
const $ = (id) => document.getElementById(id);

let me = null;          // { uid, email, cid, role }
let pcId = null;
let stopLive = null;
let stopSettings = null;
let busy = false;

const show = (el, on) => el.classList.toggle("hide", !on);
const isAdmin = () => !!me && (me.role === "admin" || me.role === "super");

// --- 로그인 ---------------------------------------------------------
$("login-btn").addEventListener("click", async () => {
  const alert = $("login-alert");
  show(alert, false);
  $("login-btn").disabled = true;
  try {
    await signInWithEmailAndPassword(auth, $("email").value.trim(), $("password").value);
    $("password").value = "";
  } catch (e) {
    // 실서비스는 invalid-credential 하나로 뭉뚱그리고, 에뮬레이터·옛 SDK 는 wrong-password 등으로 나눈다
    const wrong = ["auth/invalid-credential", "auth/invalid-login-credentials", "auth/wrong-password",
      "auth/user-not-found", "auth/invalid-email", "auth/missing-password"];
    alert.textContent = wrong.includes(e.code)
      ? "이메일 또는 비밀번호가 맞지 않습니다" : `로그인하지 못했습니다 (${e.code})`;
    show(alert, true);
  } finally {
    $("login-btn").disabled = false;
  }
});
$("password").addEventListener("keydown", (e) => { if (e.key === "Enter") $("login-btn").click(); });
$("logout-btn").addEventListener("click", () => signOut(auth));

onAuthStateChanged(auth, async (user) => {
  if (stopLive) { stopLive(); stopLive = null; }
  if (stopSettings) { stopSettings(); stopSettings = null; }
  if (!user) {
    me = null; pcId = null;
    show($("login"), true); show($("main"), false);
    return;
  }
  const t = await user.getIdTokenResult(true);
  me = { uid: user.uid, email: user.email, cid: t.claims.cid || null, role: t.claims.role || null };
  $("who").textContent = `${user.email} (${me.role === "admin" ? "관리자" : me.role === "super" ? "총괄" : "열람"})`;
  show($("login"), false); show($("main"), true);
  await pickPc();
});

// --- PC 고르기 ------------------------------------------------------
async function pickPc() {
  let pcs = {};
  try {
    const snap = await get(ref(db, `meta/companies/${me.cid}/pcs`));
    pcs = snap.val() || {};
  } catch { pcs = {}; }
  const keys = Object.keys(pcs);
  const sel = $("pc-pick");
  sel.replaceChildren(...keys.map((k) => {
    const o = document.createElement("option");
    o.value = k; o.textContent = pcs[k]?.label || k;
    return o;
  }));
  show(sel, keys.length > 1);
  pcId = keys[0] || null;
  sel.onchange = () => { pcId = sel.value; watchLive(); };
  watchLive();
}

// --- 현황 -----------------------------------------------------------
function watchLive() {
  if (stopLive) { stopLive(); stopLive = null; }
  if (!pcId) { $("conn").textContent = "등록된 PC 가 없습니다"; paintButtons(); return; }
  stopLive = onValue(ref(db, `live/${me.cid}/${pcId}`), (snap) => paint(snap.val()), (e) => {
    $("conn").textContent = e.code === "PERMISSION_DENIED" ? "권한 없음" : "읽지 못했습니다";
  });
  watchSettings();
  paintButtons();
}

const STATE_LABEL = { running: "진행 중", success: "성공", failed: "실패", stopped: "중단", crashed: "비정상 종료", done: "완료", skipped: "건너뜀" };

function paint(live) {
  const beat = live?.heartbeat?.at;
  const age = beat ? Math.floor(Date.now() / 1000) - beat : null;
  $("conn").textContent = age == null ? "기록 없음"
    : age > HEARTBEAT_STALE_SEC ? `PC 연결 끊김 (${Math.floor(age / 60)}분 전)` : "연결됨";
  $("conn").className = age != null && age <= HEARTBEAT_STALE_SEC ? "st-success" : "muted";
  for (const key of ["routine", "prepare"]) paintProgram($(key), live?.programs?.[key]);
}

function paintProgram(box, view) {
  if (!view) { box.textContent = "기록 없음"; box.className = "muted"; return; }
  const steps = view.steps || [];
  const done = view.steps_done ?? 0;
  const total = view.steps_total ?? steps.length;
  const head = document.createElement("div");
  head.className = "row";
  const state = document.createElement("b");
  state.textContent = STATE_LABEL[view.state] || view.state || "";
  state.className = `st-${view.state}`;
  head.append(state, Object.assign(document.createElement("span"),
    { className: "muted", textContent: `${done}/${total} 단계` }));
  const list = document.createElement("ul");
  list.className = "steps";
  for (const s of steps.slice(-8)) {
    const li = document.createElement("li");
    li.append(Object.assign(document.createElement("span"), { textContent: s.label || s.key }),
      Object.assign(document.createElement("span"),
        { className: `st-${s.state} muted`, textContent: STATE_LABEL[s.state] || s.state || "" }));
    list.append(li);
  }
  box.replaceChildren(head, list);
  box.className = "";
}

// --- 명령 -----------------------------------------------------------
function setAlert(kind, text) {
  const box = $("act-alert");
  box.textContent = text;
  box.className = `alert ${kind === "bad" ? "bad" : ""}`;
  show(box, !!text);
}

async function sendCommand(type, args, label) {
  if (busy || !pcId) return;
  busy = true;
  paintButtons();
  setAlert("", `${label} 명령을 보냈습니다. PC 응답을 기다립니다.`);
  try {
    const now = Math.floor(Date.now() / 1000);
    const node = await push(ref(db, `commands/${me.cid}/${pcId}`), {
      type, args: args ?? null, by: me.uid,
      created_at: now, expires_at: now + COMMAND_TTL_SEC, state: "queued",
    });
    await watchCommand(node.key, label);
  } catch (e) {
    setAlert("bad", e.code === "PERMISSION_DENIED" ? "권한이 없습니다" : `보내지 못했습니다 (${e.code || e})`);
  } finally {
    busy = false;
    paintButtons();
  }
}

function watchCommand(key, label) {
  return new Promise((resolve) => {
    const timer = setTimeout(() => {
      off(); setAlert("bad", "PC 가 응답하지 않습니다"); resolve();
    }, 60000);
    const off = onValue(ref(db, `commands/${me.cid}/${pcId}/${key}`), (snap) => {
      const v = snap.val();
      if (!v) return;
      if (v.state === "running") setAlert("", `${label} 진행 중`);
      if (["done", "failed", "expired"].includes(v.state)) {
        clearTimeout(timer); off();
        setAlert(v.state === "done" ? "" : "bad", v.result || v.state);
        resolve();
      }
    });
  });
}

$("run-routine").addEventListener("click", () => sendCommand("launch", { target: "routine" }, "루틴 RPA"));
$("run-all").addEventListener("click", () => sendCommand("launch", { target: "all" }, "전체 실행"));
$("stop-erpia").addEventListener("click", () => {
  if (confirm("ERPia 를 종료할까요? (종료가 곧 로그아웃입니다)")) sendCommand("stop_erpia", null, "ERPia 종료");
});

function paintButtons() {
  for (const id of ["run-routine", "run-all", "stop-erpia"]) $(id).disabled = !isAdmin() || busy || !pcId;
  paintModuleMeta();
}

// --- 실행 모듈 ------------------------------------------------------
const MODULES = [
  ["Login", "로그인"], ["Sales", "주문매핑 매출처리"], ["Hold", "물류대기 관리"],
  ["Logistics", "물류관리"], ["Output", "운송장 출력 / 엑셀 생성"],
];
let savedModules = {};
let formModules = {};

function watchSettings() {
  if (stopSettings) { stopSettings(); stopSettings = null; }
  if (!pcId) return;
  stopSettings = onValue(ref(db, `settings/${me.cid}/${pcId}/modules`), (snap) => {
    savedModules = snap.val() || {};
    formModules = Object.fromEntries(MODULES.map(([k]) => [k, savedModules[k] !== false]));
    paintModules();
  }, () => {
    savedModules = {}; formModules = Object.fromEntries(MODULES.map(([k]) => [k, true]));
    paintModules();
  });
}

function modulesDirty() {
  return MODULES.some(([k]) => !!formModules[k] !== (savedModules[k] !== false));
}

function paintModules() {
  $("mod-list").replaceChildren(...MODULES.map(([key, label]) => {
    const row = document.createElement("label");
    const cb = document.createElement("input");
    cb.type = "checkbox"; cb.checked = !!formModules[key];
    cb.disabled = !isAdmin() || busy;
    cb.setAttribute("aria-label", label);
    cb.onchange = () => { formModules[key] = cb.checked; paintModuleMeta(); };
    row.append(Object.assign(document.createElement("span"), { textContent: label }), cb);
    return row;
  }));
  paintModuleMeta();
}

function paintModuleMeta() {
  const on = MODULES.filter(([k]) => formModules[k]).length;
  $("mod-meta").textContent = Object.keys(formModules).length ? `${on}/${MODULES.length} 켬` : "";
  $("mod-apply").disabled = !isAdmin() || busy || !modulesDirty() || on === 0;
}

$("mod-apply").addEventListener("click", async () => {
  const wanted = Object.fromEntries(MODULES.map(([k]) => [k, !!formModules[k]]));
  if (!Object.values(wanted).some(Boolean)) { setAlert("bad", "최소 한 모듈은 켜야 합니다"); return; }
  try {
    await set(ref(db, `settings/${me.cid}/${pcId}`), {
      modules: wanted, updated_by: me.uid, updated_at: Math.floor(Date.now() / 1000),
    });
  } catch (e) {
    setAlert("bad", e.code === "PERMISSION_DENIED" ? "권한이 없습니다" : `저장하지 못했습니다 (${e.code || e})`);
    return;
  }
  await sendCommand("set_modules", wanted, "실행 모듈");
});
