// RPA 앱 화면. 껍데기(app.js)가 mount(root, ctx) 로 띄우고 unmount() 로 걷는다.
// 데이터는 apps/rpa/{live|commands|settings}/{cid}/{pcId}. 기준값은 PC 가 올린 live 다.
import {
  ref, onValue, push, set,
} from "https://www.gstatic.com/firebasejs/10.14.1/firebase-database.js";
import { HEARTBEAT_STALE_SEC, COMMAND_TTL_SEC } from "./firebase-config.js";

export const key = "rpa";
export const label = "RPA";
export const icon = "▣";
export const perPc = true;

const P = (kind, cid, pcId) => `apps/rpa/${kind}/${cid}/${pcId}`;
const STATE_LABEL = { running: "진행 중", success: "성공", failed: "실패", stopped: "중단", crashed: "비정상 종료", done: "완료", skipped: "건너뜀" };
const HERO_TITLE = { running: "진행 중", success: "성공", failed: "실패", stopped: "실패", crashed: "실패" };
const MODULES = [
  ["Login", "로그인"], ["Sales", "주문매핑 매출처리"], ["Hold", "물류대기 관리"],
  ["Logistics", "물류관리"], ["Output", "운송장 출력 / 엑셀 생성"],
];
const DAYS = ["월", "화", "수", "목", "금", "토", "일"];
const PRESETS = [["평일", [0, 1, 2, 3, 4]], ["매일", [0, 1, 2, 3, 4, 5, 6]], ["주말", [5, 6]]];

const HTML = `
  <section class="hero" id="hero" data-state="">
    <div class="stripe"></div>
    <div class="body">
      <div class="state"><span class="dot"></span><span id="h-state">확인 중</span></div>
      <div class="line1" id="h-line1"></div>
      <div class="line2" id="h-line2"></div>
    </div>
    <div class="act" id="h-act"></div>
  </section>
  <div class="tiles" id="tiles"></div>
  <div class="cols">
    <div>
      <div class="card"><details id="steps-routine"><summary>루틴 RPA <span><span class="muted" id="meta-routine"></span> &nbsp;<span class="chev">▶</span></span></summary><ul class="steps" id="list-routine"></ul></details></div>
      <div class="card"><details id="steps-prepare"><summary>프리페어 RPA <span><span class="muted" id="meta-prepare"></span> &nbsp;<span class="chev">▶</span></span></summary><ul class="steps" id="list-prepare"></ul></details></div>
      <div class="card"><details id="log-box"><summary>로그 <span><span class="muted" id="log-meta"></span> &nbsp;<span class="chev">▶</span></span></summary><pre class="num" id="log" style="font-size:12px;white-space:pre-wrap;margin:10px 0 0;color:var(--muted)"></pre></details></div>
    </div>
    <div id="sidecol">
      <div class="card" id="act-card">
        <h2>실행</h2>
        <div class="actions">
          <button id="run-routine" class="primary">루틴 RPA <span>▶</span></button>
          <button id="run-prepare">프리페어 RPA <span>▶</span></button>
          <button id="run-all">전체 실행 <span>▶▶</span></button>
          <button id="stop-erpia" class="danger">ERPia 종료</button>
        </div>
        <div id="act-alert" class="alert hide"></div>
      </div>
      <div class="card" id="mod-card">
        <h2>실행 모듈 <span class="muted" id="mod-meta"></span></h2>
        <div id="mod-list"></div>
        <button class="apply" id="mod-apply" disabled>적용</button>
      </div>
      <div class="card" id="sch-card">
        <h2>자동 실행 <span class="muted" id="sch-meta"></span></h2>
        <label class="switch first"><span>켬</span><input type="checkbox" id="sch-enabled"><span class="knob"></span></label>
        <div id="sch-form">
          <div class="lbl">요일</div>
          <div class="seg" id="sch-presets"></div>
          <div class="seg" id="sch-days"></div>
          <div class="lbl">시간</div>
          <div class="times" id="sch-times"></div>
          <div class="seg"><button id="sch-add">+ 시간</button></div>
        </div>
        <div class="msg" id="sch-info"></div>
        <button class="apply" id="sch-apply" disabled>적용</button>
      </div>
    </div>
  </div>
`;

let root = null, c = null;
let stopLive = null;
let busy = false;
let live = null;
let form = { modules: {}, sch: { enabled: false, days: [], times: [] } };

const $ = (id) => root.querySelector(`#${id}`);
const show = (el, on) => el.classList.toggle("hide", !on);
const hhmm = (iso) => iso ? iso.slice(11, 16) : "";
const dur = (sec) => sec == null ? "" : sec >= 60 ? `${Math.floor(sec / 60)}분 ${sec % 60}초` : `${sec}초`;
const when = (iso) => {
  if (!iso) return "";
  const d = new Date(iso);
  return `${d.getMonth() + 1}월 ${d.getDate()}일 (${DAYS[(d.getDay() + 6) % 7]}) ${hhmm(iso)}`;
};

export function mount(el, context) {
  root = el; c = context;
  root.innerHTML = HTML;
  busy = false; live = null;
  $("run-routine").onclick = () => sendCommand("launch", { target: "routine" }, "루틴 RPA");
  $("run-prepare").onclick = () => sendCommand("launch", { target: "prepare" }, "프리페어 RPA");
  $("run-all").onclick = () => sendCommand("launch", { target: "all" }, "전체 실행");
  $("stop-erpia").onclick = () => { if (confirm("ERPia 를 종료할까요?")) sendCommand("stop_erpia", null, "ERPia 종료"); };
  $("mod-apply").onclick = applyModules;
  $("sch-apply").onclick = applySchedule;
  $("sch-enabled").onchange = (e) => { form.sch.enabled = e.target.checked; paintScheduleMeta(); };
  $("sch-add").onclick = () => { form.sch.times.push("09:00"); paintTimes(); paintScheduleMeta(); };
  $("sch-presets").replaceChildren(...PRESETS.map(([t, days]) => {
    const b = document.createElement("button"); b.textContent = t;
    b.onclick = () => { form.sch.days = [...days]; paintDays(); paintScheduleMeta(); };
    return b;
  }));
  show($("act-card"), c.isAdmin); show($("mod-card"), c.isAdmin); show($("sch-card"), c.isAdmin);
  if (!c.pcId) { $("h-state").textContent = "등록된 PC 가 없습니다"; return; }
  stopLive = onValue(ref(c.db, P("live", c.me.cid, c.pcId)), (snap) => {
    const v = snap.val();
    const first = live == null;
    live = v || {};
    paintHero(); paintTiles(); paintSteps(); paintLog();
    // 편집 중이 아닐 때만 폼을 PC 값으로 맞춘다 (적용 뒤 돌아온 값으로 갱신)
    if (first || !modulesDirty()) resetModules();
    if (first || !scheduleDirty()) resetSchedule();
    paintButtons();
  }, (e) => { $("h-state").textContent = e.code === "PERMISSION_DENIED" ? "권한 없음" : "읽지 못했습니다"; });
}

export function unmount() {
  if (stopLive) { stopLive(); stopLive = null; }
  root = null; c = null;
}

// --- 현황 -----------------------------------------------------------
function latest() {
  const ps = live?.programs || {};
  const list = ["routine", "prepare"].map((k) => ps[k]).filter(Boolean);
  list.sort((a, b) => (b.updated_at || "").localeCompare(a.updated_at || ""));
  return list[0] || null;
}
function offlineSec() {
  const at = live?.heartbeat?.at;
  return at ? Math.floor(Date.now() / 1000) - at : null;
}
function metric(view, key) {
  return (view?.metrics || []).find((m) => m.key === key);
}
function metricText(view) {
  const ms = view?.metrics || [];
  return ms.slice(0, 3).map((m) => `${m.label} ${m.approx ? "약 " : ""}${m.value}${m.total != null ? "/" + m.total : ""}${m.unit || ""}`).join(" · ");
}

function paintHero() {
  const v = latest();
  const off = offlineSec();
  const hero = $("hero");
  let state, title, l1 = "", l2 = "";
  if (off == null || off > HEARTBEAT_STALE_SEC) {
    state = "offline";
    title = "PC 연결 끊김";
    l1 = off == null ? "에이전트 기록 없음" : `${Math.floor(off / 60)}분 전부터 응답 없음` + (v ? ` · 마지막 ${STATE_LABEL[v.state] || v.state} ${hhmm(v.finished_at || v.updated_at)}` : "");
    l2 = "PC 가 꺼졌거나 에이전트가 닫혔습니다. PC 에서 에이전트_시작.bat 을 다시 실행하세요.";
  } else if (!v) {
    state = ""; title = "기록 없음"; l1 = "PC 연결됨"; l2 = "";
  } else {
    state = v.state;
    const today = (v.started_at || "").slice(0, 10) === new Date().toISOString().slice(0, 10);
    title = (today && v.state === "success" ? "오늘 " : "") + (HERO_TITLE[v.state] || v.state);
    if (v.state === "running") {
      l1 = `${hhmm(v.started_at)} ${v.program_label} · ${v.steps_done ?? 0}/${v.steps_total ?? 0} 단계` + (v.current_label ? ` · ${v.current_label}` : "");
      l2 = `시작 ${dur(v.elapsed_sec)} 전 · PC 연결됨`;
    } else {
      const stopped = (v.steps || []).find((s) => s.state === "stopped" || s.state === "failed");
      l1 = `${hhmm(v.started_at)} ${v.program_label} · ${dur(v.duration_sec)}` + (stopped ? ` · ${stopped.label}에서 멈춤` : (metricText(v) ? " · " + metricText(v) : ""));
      l2 = v.reason ? v.reason : "PC 연결됨";
    }
  }
  hero.dataset.state = state;
  $("h-state").textContent = title;
  $("h-line1").textContent = l1;
  $("h-line2").textContent = l2;
  const act = $("h-act");
  act.replaceChildren();
  if (c.isAdmin && state !== "running") {
    const b = document.createElement("button");
    b.className = "primary"; b.textContent = state === "success" || !v ? "루틴 RPA 실행" : "루틴 RPA 다시 실행";
    b.disabled = busy || state === "offline";
    b.onclick = () => sendCommand("launch", { target: "routine" }, "루틴 RPA");
    act.append(b);
  }
}

function paintTiles() {
  const r = live?.programs?.routine;
  const off = offlineSec();
  const tiles = [];
  const m1 = metric(r, "bottom_selected"), m2 = metric(r, "stock_hold"), m3 = metric(r, "abnormal_hold");
  if (m1) tiles.push(["처리 주문", String(m1.value), m1.unit || "건", false]);
  if (m2) tiles.push(["재고검토 보류", String(m2.value), m2.total != null ? `/ ${m2.total}` : (m2.unit || ""), false]);
  if (m3) tiles.push(["비정상 보류", String(m3.value), m3.unit || "건", !!m3.approx]);
  const conn = off != null && off <= HEARTBEAT_STALE_SEC;
  tiles.push(["연결", conn ? "정상" : (off == null ? "없음" : `끊김 ${Math.floor(off / 60)}분`), "", false, conn ? "var(--good)" : "var(--warn)"]);
  const sch = live?.schedule;
  tiles.push(["다음 자동 실행", sch?.enabled && sch.next_run_at ? when(sch.next_run_at) : "꺼짐", "", false]);
  $("tiles").replaceChildren(...tiles.map(([k, v, u, approx, color]) => {
    const d = document.createElement("div"); d.className = "tile";
    d.innerHTML = `<span class="k">${k}</span><span class="v num">${approx ? '<span class="approx">≈</span>' : ""}${v}<small>${u}</small></span>`;
    if (color) d.querySelector(".v").style.color = color;
    return d;
  }));
  $("tiles").querySelector(".tile:nth-last-child(2) .v").id = "conn";
}

function paintSteps() {
  for (const key of ["routine", "prepare"]) {
    const v = live?.programs?.[key];
    const ul = $(`list-${key}`), meta = $(`meta-${key}`), box = $(`steps-${key}`);
    if (!v) { ul.replaceChildren(); meta.textContent = "기록 없음"; continue; }
    const steps = v.steps || [];
    meta.textContent = `${STATE_LABEL[v.state] || v.state} · ${v.steps_done ?? 0}/${v.steps_total ?? steps.length}` + (v.duration_sec != null ? ` · ${dur(v.duration_sec)}` : "");
    ul.replaceChildren(...steps.map((s) => {
      const li = document.createElement("li");
      const off = s.state === "skipped" && s.note === "설정에서 끔";
      li.className = off ? "skipped" : (s.state || "pending");
      const note = off ? "설정에서 끔" : (s.note || (s.state === "running" ? "진행 중" : ""));
      li.innerHTML = `<span class="mark"></span><span>${s.label || s.key}</span><span class="note">${note}</span>`;
      return li;
    }));
    if (v.state === "running" || v.state === "stopped" || v.state === "failed" || v.state === "crashed") box.open = true;
  }
}

function paintLog() {
  const v = latest();
  const lines = v?.log_tail || v?.log || [];
  $("log").textContent = lines.join("\n");
  $("log-meta").textContent = lines.length ? `${v.program_label} · ${lines.length}줄` : "없음";
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
  busy = true; paintButtons();
  setAlert("", `${label} 명령을 보냈습니다. PC 응답을 기다립니다.`);
  try {
    const now = Math.floor(Date.now() / 1000);
    const node = await push(ref(c.db, P("commands", c.me.cid, c.pcId)), {
      type, args: args ?? null, by: c.me.uid, created_at: now, expires_at: now + COMMAND_TTL_SEC, state: "queued",
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
    const timer = setTimeout(() => { off(); if (root) setAlert("bad", "PC 가 응답하지 않습니다"); resolve(); }, 60000);
    const off = onValue(ref(c.db, `${P("commands", c.me.cid, c.pcId)}/${cmdKey}`), (snap) => {
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
  const hb = $("h-act").querySelector("button"); if (hb) hb.disabled = busy || $("hero").dataset.state === "offline";
  paintModuleMeta(); paintScheduleMeta();
}

// --- 실행 모듈 ------------------------------------------------------
const savedModules = () => live?.modules || {};
function resetModules() {
  form.modules = Object.fromEntries(MODULES.map(([k]) => [k, savedModules()[k] !== false]));
  paintModules();
}
function modulesDirty() {
  return MODULES.some(([k]) => !!form.modules[k] !== (savedModules()[k] !== false));
}
function paintModules() {
  $("mod-list").replaceChildren(...MODULES.map(([k, text], i) => {
    const row = document.createElement("label"); row.className = "switch" + (i === 0 ? " first" : "");
    const cb = document.createElement("input");
    cb.type = "checkbox"; cb.checked = !!form.modules[k]; cb.disabled = !c.isAdmin || busy;
    cb.setAttribute("aria-label", text);
    cb.onchange = () => { form.modules[k] = cb.checked; paintModuleMeta(); };
    row.append(Object.assign(document.createElement("span"), { textContent: text }), cb, Object.assign(document.createElement("span"), { className: "knob" }));
    return row;
  }));
  paintModuleMeta();
}
function paintModuleMeta() {
  const on = MODULES.filter(([k]) => form.modules[k]).length;
  $("mod-meta").textContent = live ? `${on}/${MODULES.length} 켬` : "";
  $("mod-apply").disabled = !c.isAdmin || busy || !modulesDirty() || on === 0;
}
async function applyModules() {
  const wanted = Object.fromEntries(MODULES.map(([k]) => [k, !!form.modules[k]]));
  if (!Object.values(wanted).some(Boolean)) { setAlert("bad", "최소 한 모듈은 켜야 합니다"); return; }
  try {
    await set(ref(c.db, `${P("settings", c.me.cid, c.pcId)}/modules`), wanted);
  } catch (e) { setAlert("bad", e.code === "PERMISSION_DENIED" ? "권한이 없습니다" : `저장하지 못했습니다 (${e.code || e})`); return; }
  await sendCommand("set_modules", wanted, "실행 모듈");
}

// --- 자동 실행 ------------------------------------------------------
const savedSch = () => live?.schedule || { enabled: false, days: [], times: [] };
function resetSchedule() {
  const s = savedSch();
  form.sch = { enabled: !!s.enabled, days: [...(s.days || [])], times: [...(s.times || [])] };
  $("sch-enabled").checked = form.sch.enabled;
  paintDays(); paintTimes(); paintScheduleMeta();
}
function scheduleDirty() {
  const s = savedSch();
  return form.sch.enabled !== !!s.enabled
    || [...form.sch.days].sort().join() !== [...(s.days || [])].sort().join()
    || [...form.sch.times].sort().join() !== [...(s.times || [])].sort().join();
}
function paintDays() {
  $("sch-days").replaceChildren(...DAYS.map((d, i) => {
    const b = document.createElement("button"); b.textContent = d;
    b.setAttribute("aria-pressed", form.sch.days.includes(i));
    b.onclick = () => {
      form.sch.days = form.sch.days.includes(i) ? form.sch.days.filter((x) => x !== i) : [...form.sch.days, i];
      paintDays(); paintScheduleMeta();
    };
    return b;
  }));
}
function paintTimes() {
  $("sch-times").replaceChildren(...form.sch.times.map((t, i) => {
    const row = document.createElement("div"); row.className = "t";
    const inp = document.createElement("input"); inp.type = "time"; inp.step = 300; inp.value = t; inp.className = "num";
    inp.onchange = () => { form.sch.times[i] = inp.value; paintScheduleMeta(); };
    const del = document.createElement("button"); del.textContent = "빼기";
    del.onclick = () => { form.sch.times.splice(i, 1); paintTimes(); paintScheduleMeta(); };
    row.append(inp, del);
    return row;
  }));
}
function paintScheduleMeta() {
  const s = savedSch();
  const dis = !c.isAdmin || busy;
  $("sch-enabled").disabled = dis;
  for (const b of $("sch-form").querySelectorAll("button, input")) b.disabled = dis;
  $("sch-meta").textContent = !live ? "" : s.enabled ? `${labelDays(s.days)} ${(s.times || []).join(", ")}` : "꺼짐";
  const info = [];
  if (s.enabled && s.next_run_at) info.push(`다음 ${when(s.next_run_at)}`);
  if (s.last_launch_at) info.push(`마지막 ${when(s.last_launch_at)}${s.last_launch_by === "auto" ? " (자동)" : ""}`);
  if (s.last_error) info.push(`오류: ${s.last_error}`);
  $("sch-info").textContent = info.join(" · ");
  $("sch-info").className = "msg" + (s.last_error ? " bad" : "");
  const ok = !form.sch.enabled || (form.sch.days.length > 0 && form.sch.times.length > 0 && form.sch.times.every((t) => /^\d\d:\d\d$/.test(t)));
  $("sch-apply").disabled = dis || !scheduleDirty() || !ok;
}
function labelDays(days) {
  const d = [...new Set(days || [])].sort();
  if (d.join() === "0,1,2,3,4,5,6") return "매일";
  if (d.join() === "0,1,2,3,4") return "평일";
  if (d.join() === "5,6") return "주말";
  return d.map((i) => DAYS[i]).join("·") || "요일 없음";
}
async function applySchedule() {
  const payload = { enabled: form.sch.enabled, days: [...new Set(form.sch.days)].sort(), times: [...new Set(form.sch.times)].sort() };
  try {
    await set(ref(c.db, `${P("settings", c.me.cid, c.pcId)}/schedule`), payload);
  } catch (e) { setAlert("bad", e.code === "PERMISSION_DENIED" ? "권한이 없습니다" : `저장하지 못했습니다 (${e.code || e})`); return; }
  await sendCommand("set_schedule", payload, "자동 실행");
}
