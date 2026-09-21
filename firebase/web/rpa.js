// RPA 앱 화면. 껍데기(app.js)가 mount(root, ctx) 로 띄우고 unmount() 로 걷는다.
// 현황은 apps/rpa/live/{cid}/{pcId} (RTDB), 기록은 runs/{cid}/items (Firestore). 기준값은 PC 가 올린 live 다.
import {
  ref, onValue, push, set,
} from "https://www.gstatic.com/firebasejs/10.14.1/firebase-database.js";
import {
  getFirestore, collection, query, where, orderBy, limit, getDocs, connectFirestoreEmulator,
} from "https://www.gstatic.com/firebasejs/10.14.1/firebase-firestore.js";
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
const HISTORY_LIMIT = 100;
const MAX_TIMES = 2;      // 하루 실행 시각 개수 (추가는 유료 옵션으로 열 예정)

const HTML = `
  <div class="subnav" role="tablist">
    <button id="tab-status" role="tab" aria-selected="true">현황</button>
    <button id="tab-history" role="tab" aria-selected="false">기록</button>
  </div>

  <div id="view-status">
    <section class="hero" id="hero" data-state="">
      <div class="body">
        <div class="state"><span class="dot"></span><span id="h-state">확인 중</span></div>
        <div class="line1" id="h-line1"></div>
        <div class="line2" id="h-line2"></div>
      </div>
    </section>
    <div class="tiles" id="tiles"></div>
    <div class="cols">
      <div>
        <div class="card recent">
          <h2>최근 10일 <span class="muted" id="recent-meta"></span></h2>
          <div class="recent-body">
            <div class="strip" id="recent-strip"></div>
            <div class="donut" id="recent-donut"></div>
          </div>
        </div>
        <div class="pair">
          <div class="card" id="steps-prepare"><h2>프리페어 RPA <span class="muted" id="meta-prepare"></span></h2><ul class="steps" id="list-prepare"></ul></div>
          <div class="card" id="steps-routine"><h2>루틴 RPA <span class="muted" id="meta-routine"></span></h2><ul class="steps" id="list-routine"></ul></div>
        </div>
        <div class="card"><details id="log-box"><summary>로그 <span><span class="muted" id="log-meta"></span> &nbsp;<span class="chev">▶</span></span></summary><pre class="num" id="log" style="font-size:12px;white-space:pre-wrap;margin:10px 0 0;color:var(--muted)"></pre></details></div>
      </div>
      <div id="sidecol">
        <div class="card" id="act-card">
          <h2>실행</h2>
          <div class="actions">
            <button id="run-all" class="primary">전체 실행 <span>▶</span></button>
            <button id="run-prepare">프리페어 RPA <span>▶</span></button>
            <button id="run-routine">루틴 RPA <span>▶</span></button>
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
  </div>

  <div id="view-history" class="hide">
    <div class="card">
      <h2><span id="hist-title">기록</span> <span class="row" style="gap:6px"><input type="date" id="hist-date" class="num" style="width:auto"><button id="hist-all">전체</button></span></h2>
      <div class="msg" id="hist-msg"></div>
      <div class="tbl"><table>
        <thead><tr><th>시각</th><th>프로그램</th><th>결과</th><th>소요</th><th>처리</th></tr></thead>
        <tbody id="hist-rows"></tbody>
      </table></div>
    </div>
  </div>
`;

let root = null, c = null;
let stopLive = null;
let busy = false;
let live = null;
let form = { modules: {}, sch: { enabled: false, days: [], times: [] } };
let fs = null;
let resizeObs = null;

const $ = (id) => root.querySelector(`#${id}`);
const show = (el, on) => el.classList.toggle("hide", !on);
const hhmm = (iso) => iso ? iso.slice(11, 16) : "";
const dur = (sec) => sec == null ? "" : sec >= 60 ? `${Math.floor(sec / 60)}분 ${sec % 60}초` : `${sec}초`;
const when = (iso) => {
  if (!iso) return "";
  const d = new Date(iso);
  return `${d.getMonth() + 1}월 ${d.getDate()}일 (${DAYS[(d.getDay() + 6) % 7]}) ${hhmm(iso)}`;
};
const isoDay = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

export function mount(el, context) {
  root = el; c = context;
  root.innerHTML = HTML;
  busy = false; live = null;
  fs = getFirestore(c.db.app);
  if (location.hostname === "127.0.0.1" && new URLSearchParams(location.search).get("emu") === "1") {
    try { connectFirestoreEmulator(fs, "127.0.0.1", 8080); } catch {}   // 두 번째 mount 부터는 이미 붙어 있다
  }
  $("tab-status").onclick = () => showView("status");
  $("tab-history").onclick = () => showView("history");
  $("hist-date").onchange = () => loadHistory($("hist-date").value || null);
  $("hist-all").onclick = () => { $("hist-date").value = ""; loadHistory(null); };
  $("run-routine").onclick = () => sendCommand("launch", { target: "routine" }, "루틴 RPA");
  $("run-prepare").onclick = () => sendCommand("launch", { target: "prepare" }, "프리페어 RPA");
  $("run-all").onclick = () => sendCommand("launch", { target: "all" }, "전체 실행");
  $("stop-erpia").onclick = () => { if (confirm("ERPia 를 종료할까요?")) sendCommand("stop_erpia", null, "ERPia 종료"); };
  $("mod-apply").onclick = applyModules;
  $("sch-apply").onclick = applySchedule;
  $("sch-enabled").onchange = (e) => { form.sch.enabled = e.target.checked; paintScheduleMeta(); };
  $("sch-add").onclick = () => { if (form.sch.times.length >= MAX_TIMES) return; form.sch.times.push("09:00"); paintTimes(); paintScheduleMeta(); };
  $("sch-presets").replaceChildren(...PRESETS.map(([t, days]) => {
    const b = document.createElement("button"); b.textContent = t;
    b.onclick = () => { form.sch.days = [...days]; paintDays(); paintScheduleMeta(); };
    return b;
  }));
  show($("act-card"), c.isAdmin); show($("mod-card"), c.isAdmin); show($("sch-card"), c.isAdmin);
  // 창 폭이 바뀌면 띠의 날짜 수를 다시 센다
  resizeObs = new ResizeObserver(() => { if (root && live) paintRecent(); });
  resizeObs.observe($("recent-strip").parentElement);
  if (!c.pcId) { $("h-state").textContent = "등록된 PC 가 없습니다"; return; }
  stopLive = onValue(ref(c.db, P("live", c.me.cid, c.pcId)), (snap) => {
    const v = snap.val();
    const first = live == null;
    live = v || {};
    paintHero(); paintTiles(); paintRecent(); paintSteps(); paintLog();
    // 편집 중이 아닐 때만 폼을 PC 값으로 맞춘다 (적용 뒤 돌아온 값으로 갱신)
    if (first || !modulesDirty()) resetModules();
    if (first || !scheduleDirty()) resetSchedule();
    paintButtons();
  }, (e) => { $("h-state").textContent = e.code === "PERMISSION_DENIED" ? "권한 없음" : "읽지 못했습니다"; });
}

export function unmount() {
  if (stopLive) { stopLive(); stopLive = null; }
  if (resizeObs) { resizeObs.disconnect(); resizeObs = null; }
  root = null; c = null;
}

function showView(name) {
  show($("view-status"), name === "status");
  show($("view-history"), name === "history");
  $("tab-status").setAttribute("aria-selected", name === "status");
  $("tab-history").setAttribute("aria-selected", name === "history");
  if (name === "history" && !$("hist-rows").children.length) loadHistory($("hist-date").value || null);
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
function metric(view, k) {
  return (view?.metrics || []).find((m) => m.key === k);
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
    title = HERO_TITLE[v.state] || v.state;
    if (v.state === "running") {
      l1 = `${hhmm(v.started_at)} ${v.program_label} · ${v.steps_done ?? 0}/${v.steps_total ?? 0} 단계` + (v.current_label ? ` · ${v.current_label}` : "");
      l2 = `시작 ${dur(v.elapsed_sec)} 전`;
    } else {
      const stopped = (v.steps || []).find((s) => s.state === "stopped" || s.state === "failed");
      l1 = [`${hhmm(v.started_at)} ${v.program_label}`, dur(v.duration_sec), stopped ? `${stopped.label}에서 멈춤` : ""]
        .filter(Boolean).join(" · ");
      l2 = v.reason ? v.reason : summaryText(v);
    }
  }
  hero.dataset.state = state;
  $("h-state").textContent = title;
  $("h-line1").textContent = l1;
  $("h-line2").textContent = l2;
}

// 한 줄 요약. 루틴: "수집 30건 (자동 12건, 엑셀 2개) · 재고검토 보류 8/8 · 비정상 보류 ≈376건". 프리페어: 메일·첨부.
function summaryText(v) {
  const m = (k) => metric(v, k);
  const parts = [];
  if (v.program === "routine") {
    const got = m("bottom_selected"), auto = m("top_selected"), xl = m("excel_upload");
    if (got) {
      const inner = [auto ? `자동 ${auto.value}건` : "", xl ? `엑셀 ${xl.value}개` : ""].filter(Boolean).join(", ");
      parts.push(`수집 ${got.value}건` + (inner ? ` (${inner})` : ""));
    }
    for (const k of ["stock_hold", "abnormal_hold"]) {
      const x = m(k);
      if (x) parts.push(`${x.label} ${x.approx ? "≈" : ""}${x.value}${x.total != null ? "/" + x.total : ""}${x.unit || "건"}`);
    }
  } else {
    for (const x of (v.metrics || []).filter((x) => /mail_hits|files/.test(x.key || ""))) parts.push(`${x.label} ${x.value}${x.unit || "건"}`);
  }
  return parts.length ? parts.join(" · ") : metricText(v);
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
  tiles.push(["연결", conn ? "정상" : (off == null ? "없음" : `끊김 ${Math.floor(off / 60)}분`), "", false, conn ? "var(--good)" : "var(--warn)", "conn"]);
  const sch = live?.schedule;
  tiles.push(["다음 자동 실행", sch?.enabled && sch.next_run_at ? when(sch.next_run_at) : "꺼짐", "", false]);
  $("tiles").replaceChildren(...tiles.map(([k, v, u, approx, color, id]) => {
    const d = document.createElement("div"); d.className = "tile";
    d.innerHTML = `<span class="k">${k}</span><span class="v num">${approx ? '<span class="approx">≈</span>' : ""}${v}<small>${u}</small></span>`;
    if (color) d.querySelector(".v").style.color = color;
    if (id) d.querySelector(".v").id = id;
    return d;
  }));
}

// 도넛 SVG. 둘레 100 으로 맞춘 stroke-dasharray. 가운데 글자는 없다 (수치는 옆 범례에)
function donutSvg(ok, bad, size) {
  const total = ok + bad;
  const goodLen = total ? ok / total * 100 : 0;
  // 실행이 없으면 빗금 고리 (index.html 의 #hatch 무늬)
  return `<svg viewBox="0 0 42 42" width="${size}" height="${size}" role="img" aria-label="${total ? `성공 ${ok}건, 실패 ${bad}건` : "실행 없음"}">
    <circle cx="21" cy="21" r="15.915" fill="none" stroke="${total ? "var(--bad)" : "url(#hatch)"}" stroke-width="6"></circle>
    ${total ? `<circle cx="21" cy="21" r="15.915" fill="none" stroke="var(--good)" stroke-width="6"
      stroke-dasharray="${goodLen} ${100 - goodLen}" stroke-dashoffset="25"></circle>` : ""}
  </svg>`;
}

const DAY_CELL = 44, DAY_GAP = 6, DAYS_MIN = 5, DAYS_MAX = 20;
function visibleDays() {
  // 카드 안쪽 폭에서 (같은 줄에 있으면) 오늘 도넛 폭을 뺀 만큼 (5~20일). 띠 자신의 폭은 내용에 따라 변해 기준으로 못 쓴다
  const strip = $("recent-strip"), donut = $("recent-donut");
  let w = strip.parentElement.clientWidth || 0;
  const sameRow = donut.getBoundingClientRect().left > strip.getBoundingClientRect().left + 10;
  if (sameRow) w -= donut.offsetWidth + 20;
  return Math.max(DAYS_MIN, Math.min(DAYS_MAX, Math.floor((w + DAY_GAP) / (DAY_CELL + DAY_GAP))));
}

function paintRecent() {
  // 띠는 폭에 맞춘 최근 N일, 큰 도넛은 오늘(마지막 날)만
  const days = (live?.recent || []).slice(-visibleDays());
  const today = days[days.length - 1] || { success: 0, failed: 0 };
  const ok = today.success || 0, bad = today.failed || 0;
  $("recent-meta").textContent = days.length ? (ok + bad ? `오늘 성공 ${ok} · 실패 ${bad}` : "오늘 실행 없음") : "";
  $("recent-strip").replaceChildren(...days.map((d) => {
    const cell = document.createElement("button");
    cell.className = "day" + (d.success || d.failed ? "" : " empty");
    cell.dataset.date = d.date;
    cell.title = d.success || d.failed ? `${d.date} · 성공 ${d.success} 실패 ${d.failed} · 기록 보기` : `${d.date} · 실행 없음`;
    cell.innerHTML = `${donutSvg(d.success || 0, d.failed || 0, 44)}<div class="d">${d.date.slice(5).replace("-", "/")}</div>`;
    cell.onclick = () => { $("hist-date").value = d.date; showView("history"); loadHistory(d.date); };
    return cell;
  }));
  const total = ok + bad;
  $("recent-donut").innerHTML = total
    ? `${donutSvg(ok, bad, 104)}<div class="legend"><span><i style="background:var(--good)"></i>성공 ${ok}</span><span><i style="background:var(--bad)"></i>실패 ${bad}</span></div>`
    : `<div class="muted" style="font-size:13px">실행 없음</div>`;
}

function stepList(steps) {
  const ul = document.createElement("ul");
  ul.className = "steps";
  ul.replaceChildren(...(steps || []).map((s) => {
    const li = document.createElement("li");
    const off = s.state === "skipped" && s.note === "설정에서 끔";
    li.className = off ? "skipped" : (s.state || "pending");
    const note = off ? "설정에서 끔" : (s.note || (s.state === "running" ? "진행 중" : ""));
    li.innerHTML = `<span class="mark"></span><span>${s.label || s.key}</span><span class="note">${note}</span>`;
    return li;
  }));
  return ul;
}

function paintSteps() {
  for (const k of ["routine", "prepare"]) {
    const v = live?.programs?.[k];
    const ul = $(`list-${k}`), meta = $(`meta-${k}`);
    if (!v) { ul.replaceChildren(); meta.textContent = "기록 없음"; continue; }
    const steps = v.steps || [];
    meta.textContent = `${STATE_LABEL[v.state] || v.state} · ${v.steps_done ?? 0}/${v.steps_total ?? steps.length}` + (v.duration_sec != null ? ` · ${dur(v.duration_sec)}` : "");
    ul.replaceChildren(...stepList(steps).children);
  }
}

function paintLog() {
  const v = latest();
  const lines = v?.log_tail || v?.log || [];
  $("log").textContent = lines.join("\n");
  $("log-meta").textContent = lines.length ? `${v.program_label} · ${lines.length}줄` : "없음";
}

// --- 기록 (Firestore) ------------------------------------------------
async function loadHistory(date) {
  const rows = $("hist-rows"), msg = $("hist-msg");
  $("hist-title").textContent = date ? `기록 · ${date}` : "기록";
  msg.textContent = "불러오는 중"; msg.className = "msg";
  rows.replaceChildren();
  try {
    const col = collection(fs, "runs", c.me.cid, "items");
    const q = date
      ? query(col, where("pcId", "==", c.pcId), where("date", "==", date), orderBy("started_at", "desc"), limit(HISTORY_LIMIT))
      : query(col, where("pcId", "==", c.pcId), orderBy("started_at", "desc"), limit(HISTORY_LIMIT));
    const snap = await getDocs(q);
    const items = snap.docs.map((d) => d.data());
    msg.textContent = items.length ? `${items.length}건` + (items.length >= HISTORY_LIMIT ? " (최근 것만)" : "") : "기록이 없습니다";
    rows.replaceChildren(...items.flatMap(histRow));
  } catch (e) {
    msg.className = "msg bad";
    msg.textContent = e.code === "permission-denied" ? "권한이 없습니다" : `불러오지 못했습니다 (${e.code || e})`;
  }
}

function histRow(r) {
  let payload = {};
  try { payload = JSON.parse(r.payload || "{}"); } catch {}
  const ms = (payload.metrics || []).slice(0, 3).map((m) => `${m.label} ${m.approx ? "≈" : ""}${m.value}${m.total != null ? "/" + m.total : ""}`).join(" · ");
  const tr = document.createElement("tr");
  tr.className = "hist";
  const cls = r.state === "success" ? "good" : r.state === "running" ? "run" : "bad";
  const t = (r.started_at || "").slice(5, 16).replace("T", " ").replace("-", "/");
  tr.innerHTML = `<td class="num">${t}</td><td>${r.program_label || r.program || ""}</td><td><span class="pill ${cls}">${STATE_LABEL[r.state] || r.state || ""}</span></td><td class="num">${dur(r.duration_sec)}</td><td class="muted">${r.reason || ms}</td>`;
  const detail = document.createElement("tr");
  detail.className = "hist-detail hide";
  const td = document.createElement("td"); td.colSpan = 5;
  td.append(stepList(payload.steps));
  const pre = document.createElement("pre"); pre.className = "num"; pre.textContent = (payload.log || []).join("\n");
  td.append(pre);
  detail.append(td);
  tr.onclick = () => detail.classList.toggle("hide");
  return [tr, detail];
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
  paintModuleMeta(); paintScheduleMeta();
}

// --- 실행 모듈 ------------------------------------------------------
const LOCKED = new Set(["Login"]);   // 항상 켬. 관리자도 못 끈다 (에이전트도 파일에 Y 로 고정)
const savedModules = () => live?.modules || {};
function resetModules() {
  form.modules = Object.fromEntries(MODULES.map(([k]) => [k, LOCKED.has(k) || savedModules()[k] !== false]));
  paintModules();
}
function modulesDirty() {
  return MODULES.some(([k]) => !!form.modules[k] !== (savedModules()[k] !== false));
}
function paintModules() {
  $("mod-list").replaceChildren(...MODULES.map(([k, text], i) => {
    const row = document.createElement("label"); row.className = "switch" + (i === 0 ? " first" : "");
    const cb = document.createElement("input");
    cb.type = "checkbox"; cb.checked = !!form.modules[k]; cb.disabled = !c.isAdmin || busy || LOCKED.has(k);
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
  $("sch-add").disabled = dis || form.sch.times.length >= MAX_TIMES;
  $("sch-meta").textContent = !live ? "" : s.enabled ? `${labelDays(s.days)} ${(s.times || []).join(", ")}` : "꺼짐";
  const info = [];
  if (s.enabled && s.next_run_at) info.push(`다음 ${when(s.next_run_at)}`);
  if (s.last_launch_at) info.push(`마지막 ${when(s.last_launch_at)}${s.last_launch_by === "auto" ? " (자동)" : ""}`);
  if (s.last_error) info.push(`오류: ${s.last_error}`);
  $("sch-info").textContent = info.join(" · ");
  $("sch-info").className = "msg" + (s.last_error ? " bad" : "");
  const ok = !form.sch.enabled || (form.sch.days.length > 0 && form.sch.times.length > 0 && form.sch.times.length <= MAX_TIMES
    && form.sch.times.every((t) => /^\d\d:\d\d$/.test(t)));
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
