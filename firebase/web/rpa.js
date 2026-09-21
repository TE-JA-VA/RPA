// RPA 앱 화면. 껍데기(app.js)가 mount(root, ctx) 로 띄우고 unmount() 로 걷는다.
// 데이터는 apps/rpa/{live|commands|settings}/{cid}/{pcId} 에 있다.
import {
  ref, onValue, push, set,
} from "https://www.gstatic.com/firebasejs/10.14.1/firebase-database.js";
import { HEARTBEAT_STALE_SEC, COMMAND_TTL_SEC } from "./firebase-config.js";

export const key = "rpa";
export const label = "RPA";

const APP_PATH = (kind, cid, pcId) => `apps/rpa/${kind}/${cid}/${pcId}`;
const STATE_LABEL = { running: "진행 중", success: "성공", failed: "실패", stopped: "중단", crashed: "비정상 종료", done: "완료", skipped: "건너뜀" };
const MODULES = [
  ["Login", "로그인"], ["Sales", "주문매핑 매출처리"], ["Hold", "물류대기 관리"],
  ["Logistics", "물류관리"], ["Output", "운송장 출력 / 엑셀 생성"],
];

const HTML = `
    <div class="card">
      <div class="row"><h2 style="margin:0">연결</h2><span id="conn" class="muted">확인 중</span></div>
    </div>

    <div class="card" id="act-card">
      <div class="row">
        <h2 style="margin:0">실행</h2>
        <div class="row">
          <button id="run-prepare">프리페어 RPA</button>
          <button id="run-routine">루틴 RPA</button>
          <button id="run-all">전체 실행</button>
          <button id="stop-erpia">ERPia 종료</button>
        </div>
      </div>
      <div id="act-alert" class="alert hide"></div>
    </div>

    <div class="card">
      <h2>루틴 RPA</h2>
      <div id="routine" class="muted">기록 없음</div>
    </div>

    <div class="card">
      <h2>프리페어 RPA</h2>
      <div id="prepare" class="muted">기록 없음</div>
    </div>

    <div class="card" id="mod-card">
      <div class="row"><h2 style="margin:0">실행 모듈</h2><span id="mod-meta" class="muted"></span></div>
      <div id="mod-list"></div>
      <button id="mod-apply" disabled style="margin-top:10px">적용</button>
    </div>
`;

let root = null;
let c = null;              // ctx: { db, me, pcId, isAdmin }
let stopLive = null;
let stopSettings = null;
let busy = false;
let savedModules = {};
let formModules = {};

const $ = (id) => root.querySelector(`#${id}`);
const show = (el, on) => el.classList.toggle("hide", !on);

export function mount(el, context) {
  root = el;
  c = context;
  root.innerHTML = HTML;
  $("run-prepare").addEventListener("click", () => sendCommand("launch", { target: "prepare" }, "프리페어 RPA"));
  $("run-routine").addEventListener("click", () => sendCommand("launch", { target: "routine" }, "루틴 RPA"));
  $("run-all").addEventListener("click", () => sendCommand("launch", { target: "all" }, "전체 실행"));
  $("stop-erpia").addEventListener("click", () => {
    if (confirm("ERPia 를 종료할까요?")) sendCommand("stop_erpia", null, "ERPia 종료");
  });
  $("mod-apply").addEventListener("click", applyModules);
  busy = false; savedModules = {}; formModules = {};
  watchLive();
}

export function unmount() {
  if (stopLive) { stopLive(); stopLive = null; }
  if (stopSettings) { stopSettings(); stopSettings = null; }
  root = null; c = null;
}

// --- 현황 -----------------------------------------------------------
function watchLive() {
  if (!c.pcId) { $("conn").textContent = "등록된 PC 가 없습니다"; paintButtons(); paintModules(); return; }
  stopLive = onValue(ref(c.db, APP_PATH("live", c.me.cid, c.pcId)), (snap) => paint(snap.val()), (e) => {
    $("conn").textContent = e.code === "PERMISSION_DENIED" ? "권한 없음" : "읽지 못했습니다";
  });
  watchSettings();
  paintButtons();
}

function paint(live) {
  const beat = live?.heartbeat?.at;
  const age = beat ? Math.floor(Date.now() / 1000) - beat : null;
  $("conn").textContent = age == null ? "기록 없음"
    : age > HEARTBEAT_STALE_SEC ? `PC 연결 끊김 (${Math.floor(age / 60)}분 전)` : "연결됨";
  $("conn").className = age != null && age <= HEARTBEAT_STALE_SEC ? "st-success" : "muted";
  for (const k of ["routine", "prepare"]) paintProgram($(k), live?.programs?.[k]);
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
  for (const s of steps) {
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
  if (busy || !c.pcId) return;
  busy = true;
  paintButtons();
  setAlert("", `${label} 명령을 보냈습니다. PC 응답을 기다립니다.`);
  try {
    const now = Math.floor(Date.now() / 1000);
    const node = await push(ref(c.db, APP_PATH("commands", c.me.cid, c.pcId)), {
      type, args: args ?? null, by: c.me.uid,
      created_at: now, expires_at: now + COMMAND_TTL_SEC, state: "queued",
    });
    await watchCommand(node.key, label);
  } catch (e) {
    setAlert("bad", e.code === "PERMISSION_DENIED" ? "권한이 없습니다" : `보내지 못했습니다 (${e.code || e})`);
  } finally {
    busy = false;
    if (root) paintButtons();
  }
}

function watchCommand(cmdKey, label) {
  return new Promise((resolve) => {
    const timer = setTimeout(() => {
      off(); if (root) setAlert("bad", "PC 가 응답하지 않습니다"); resolve();
    }, 60000);
    const off = onValue(ref(c.db, `${APP_PATH("commands", c.me.cid, c.pcId)}/${cmdKey}`), (snap) => {
      const v = snap.val();
      if (!v || !root) return;
      if (v.state === "running") setAlert("", `${label} 진행 중`);
      if (["done", "failed", "expired"].includes(v.state)) {
        clearTimeout(timer); off();
        setAlert(v.state === "done" ? "" : "bad", v.result || v.state);
        resolve();
      }
    });
  });
}

function paintButtons() {
  for (const id of ["run-prepare", "run-routine", "run-all", "stop-erpia"]) $(id).disabled = !c.isAdmin || busy || !c.pcId;
  paintModuleMeta();
}

// --- 실행 모듈 ------------------------------------------------------
function watchSettings() {
  // 기준값은 PC 가 올린 실제 값(live.modules)이다. settings 는 화면이 요청한 값이고, 반영은 에이전트가 파일에 쓴 뒤 live 로 돌아온다.
  stopSettings = onValue(ref(c.db, `${APP_PATH("live", c.me.cid, c.pcId)}/modules`), (snap) => {
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
  $("mod-list").replaceChildren(...MODULES.map(([k, text]) => {
    const row = document.createElement("label");
    const cb = document.createElement("input");
    cb.type = "checkbox"; cb.checked = !!formModules[k];
    cb.disabled = !c.isAdmin || busy;
    cb.setAttribute("aria-label", text);
    cb.onchange = () => { formModules[k] = cb.checked; paintModuleMeta(); };
    row.append(Object.assign(document.createElement("span"), { textContent: text }), cb);
    return row;
  }));
  paintModuleMeta();
}

function paintModuleMeta() {
  const on = MODULES.filter(([k]) => formModules[k]).length;
  $("mod-meta").textContent = Object.keys(formModules).length ? `${on}/${MODULES.length} 켬` : "";
  $("mod-apply").disabled = !c.isAdmin || busy || !modulesDirty() || on === 0;
}

async function applyModules() {
  const wanted = Object.fromEntries(MODULES.map(([k]) => [k, !!formModules[k]]));
  if (!Object.values(wanted).some(Boolean)) { setAlert("bad", "최소 한 모듈은 켜야 합니다"); return; }
  try {
    await set(ref(c.db, APP_PATH("settings", c.me.cid, c.pcId)), {
      modules: wanted, updated_by: c.me.uid, updated_at: Math.floor(Date.now() / 1000),
    });
  } catch (e) {
    setAlert("bad", e.code === "PERMISSION_DENIED" ? "권한이 없습니다" : `저장하지 못했습니다 (${e.code || e})`);
    return;
  }
  await sendCommand("set_modules", wanted, "실행 모듈");
}
