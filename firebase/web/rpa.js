// RPA 앱 화면. 껍데기(app.js)가 mount(root, ctx) 로 띄우고 unmount() 로 걷는다.
// 현황은 apps/rpa/live/{cid}/{pcId} (RTDB), 기록은 runs/{cid}/items (Firestore). 기준값은 PC 가 올린 live 다.
import {
  ref, onValue, push, set,
} from "https://www.gstatic.com/firebasejs/10.14.1/firebase-database.js";
import {
  getFirestore, collection, query, where, orderBy, limit, getDocs, connectFirestoreEmulator,
} from "https://www.gstatic.com/firebasejs/10.14.1/firebase-firestore.js";
import { HEARTBEAT_EVERY_DEFAULT, HEARTBEAT_MISS, COMMAND_TTL_SEC } from "./firebase-config.js";
import { toast } from "./toast.js";

export const key = "rpa";
export const label = "RPA";
export const icon = "▣";
export const perPc = true;

const P = (kind, cid, pcId) => `apps/rpa/${kind}/${cid}/${pcId}`;
// 상태 이름은 세 가지로 통일 (2026-09-22): 성공 / 실패(단계 검사에서 스스로 멈춤, 사용자 중지 포함) / 오류(프로그램이 죽음).
// 상태 카드·도넛 범례·기록 표 알약이 모두 같은 말을 쓴다. done·skipped 는 단계 상태
const STATE_LABEL = { running: "진행 중", success: "성공", failed: "실패", stopped: "실패", crashed: "오류", done: "완료", skipped: "건너뜀" };
const PROGRAM_SHORT = { routine: "루틴", prepare: "프리페어" };   // 기록 표의 프로그램 칸. RPA 인 건 아니까 뗀다
const HERO_TITLE = { running: "진행 중", success: "성공", failed: "실패", stopped: "실패", crashed: "오류" };
const MODULES = [
  ["Login", "로그인"], ["Sales", "주문매핑 매출처리"], ["Hold", "물류대기 관리"],
  ["Logistics", "물류관리"], ["Output", "운송장 출력 / 엑셀 생성"],
];
const DAYS = ["월", "화", "수", "목", "금", "토", "일"];
const PRESETS = [["평일", [0, 1, 2, 3, 4]], ["매일", [0, 1, 2, 3, 4, 5, 6]], ["주말", [5, 6]]];
const HISTORY_LIMIT = 100;
const MAX_TIMES = 2;      // 하루 실행 시각 개수 (추가는 유료 옵션으로 열 예정)

// 실행 버튼 아이콘 (heroicons 선 아이콘, 글자색을 따라간다)
const ARROW = `<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12h15m0 0l-6.75-6.75M19.5 12l-6.75 6.75"/></svg>`;
// 전원은 유니코드 ⏼ (U+23FC POWER ON-OFF SYMBOL) 글자 그대로. 글꼴 대체 목록은 index.html 의 .ic 에 있다
const POWER = `<span class="ic" aria-hidden="true">&#x23FC;</span>`;

// 실행 버튼: 표시(.fly)는 왼쪽에 떠 있고 글자는 그 오른쪽. 마우스를 올리면 표시가 가운데로 간다
const runBtn = (id, icon, text, cls = "") =>
  `<button id="${id}"${cls ? ` class="${cls}"` : ""}><span class="fly" aria-hidden="true">${icon}</span><span class="t">${text}</span></button>`;

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
      <div class="stats" id="hero-side"></div>
    </section>
    <div class="tiles" id="tiles"></div>
    <div class="cols">
      <div>
        <div class="card recent">
          <h2>최근 20일 <span class="muted" id="recent-meta"></span></h2>
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
            ${runBtn("run-all", ARROW, "전체 실행", "primary")}
            ${runBtn("run-prepare", ARROW, "프리페어 RPA")}
            ${runBtn("run-routine", ARROW, "루틴 RPA")}
            ${runBtn("stop-erpia", POWER, "ERPia 종료", "danger")}
          </div>
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
let tick = null;   // 1초마다 상태 카드·연결 칸을 다시 그린다 - 진행 시간이 올라가고, 에이전트가 죽어도(값이 안 바뀜) 끊김이 보이게
let seenRun = {};  // 프로그램별로 마지막에 본 "run_id:상태" (토스트를 두 번 울리지 않게)
let paintedRecent = null;   // 마지막으로 그린 최근 20일 (같으면 다시 안 그린다 - 스크롤이 튀지 않게)

const $ = (id) => root.querySelector(`#${id}`);
const show = (el, on) => el.classList.toggle("hide", !on);
// 에이전트·Firestore 에서 온 값은 innerHTML 에 넣기 전에 반드시 씌운다 (app.js 와 같은 구현)
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const hhmm = (iso) => iso ? iso.slice(11, 16) : "";
const dur = (sec) => sec == null ? "" : sec >= 60 ? `${Math.floor(sec / 60)}분 ${sec % 60}초` : `${sec}초`;
const when = (iso) => {
  if (!iso) return "";
  const d = new Date(iso);
  return `${d.getMonth() + 1}월 ${d.getDate()}일 (${DAYS[(d.getDay() + 6) % 7]}) ${hhmm(iso)}`;
};
const isoDay = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
// 현황은 하루 단위다. 어제 실행을 오늘 것처럼 띄우지 않는다 (상태 띠·단계·로그 모두)
const isToday = (v) => ((v?.started_at || v?.finished_at || "").slice(0, 10)) === isoDay(new Date());

export function mount(el, context) {
  root = el; c = context;
  root.innerHTML = HTML;
  busy = false; live = null; seenRun = {};
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
  show($("sidecol"), c.isAdmin);   // 열람 계정은 오른쪽 열이 통째로 빠지고 본문이 그 자리를 쓴다 (.cols:has)
  paintedRecent = null;
  const strip = $("recent-strip");
  // 폭이 바뀌거나 다시 보이면 칸 크기를 다시 맞추고 오늘(오른쪽 끝)로. 띠 위에서 세로 휠은 가로 스크롤로 (넘칠 때만)
  resizeObs = new ResizeObserver(fitStrip);
  resizeObs.observe(strip);
  strip.addEventListener("wheel", (e) => {
    if (strip.scrollWidth <= strip.clientWidth || e.deltaX) return;
    strip.scrollLeft += e.deltaY; e.preventDefault();
  }, { passive: false });
  tick = setInterval(() => { if (root && live) { paintHero(); paintTiles(); } }, 1000);
  if (!c.pcId) { $("h-state").textContent = "등록된 PC 가 없습니다"; return; }
  stopLive = onValue(ref(c.db, P("live", c.me.cid, c.pcId)), (snap) => {
    const v = snap.val();
    const first = live == null;
    live = v || {};
    runToasts(first);
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
  if (tick) { clearInterval(tick); tick = null; }
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
/** 실행이 시작·끝날 때만 알린다. 처음 열 때(첫 snapshot)와 PC 를 바꿀 때는 옛 결과로 울리지 않는다 */
function runToasts(first) {
  for (const k of ["routine", "prepare"]) {
    const v = live?.programs?.[k];
    if (!v) continue;
    const mark = `${v.run_id || ""}:${v.state}`;
    const was = seenRun[k];
    seenRun[k] = mark;
    if (first || was === undefined || was === mark) continue;
    const label = v.program_label || PROGRAM_SHORT[k] || k;
    if (v.state === "running") toast("info", `${label} 를 시작했습니다`);
    else if (v.state === "success") toast("ok", [`${label} 성공`, dur(v.duration_sec)].filter(Boolean).join(" · "));
    else if (v.state === "crashed") toast("warn", `${label} 오류 · ${v.reason || "프로그램이 도중에 멈췄습니다"}`);
    else if (["failed", "stopped"].includes(v.state)) {
      const at = (v.steps || []).find((s) => s.state === "stopped" || s.state === "failed");
      toast("bad", `${label} 실패` + (at ? ` · ${at.label}에서 멈춤` : v.reason ? ` · ${v.reason}` : ""));
    }
  }
}

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
function staleSec() {
  // 그 PC 의 신호 주기에 맞춘다. every 가 없으면 옛 에이전트(30초)로 본다
  return (live?.heartbeat?.every || HEARTBEAT_EVERY_DEFAULT) * HEARTBEAT_MISS + 5;
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
  if (off == null || off > staleSec()) {
    state = "offline";
    title = "PC 연결 끊김";
    l1 = off == null ? "에이전트 기록 없음" : `${ago(off)} 전부터 응답 없음` + (v ? ` · 마지막 ${STATE_LABEL[v.state] || v.state} ${hhmm(v.finished_at || v.updated_at)}` : "");
    l2 = "PC 가 꺼졌거나 에이전트가 닫혔습니다. PC 에서 에이전트_시작.bat 을 다시 실행하세요.";
  } else if (!v) {
    state = ""; title = "기록 없음"; l1 = "PC 연결됨"; l2 = "";
  } else if (v.state !== "running" && !isToday(v)) {
    // 오늘 실행이 아직 없으면 어제 결과를 그대로 띄우지 않는다 (지금 상태는 '대기중')
    state = ""; title = "대기중";
    l1 = `마지막 실행 ${when(v.finished_at || v.started_at)} · ${STATE_LABEL[v.state] || v.state}`;
    l2 = v.reason || summaryText(v);
  } else {
    state = v.state;
    title = HERO_TITLE[v.state] || v.state;
    if (v.state === "running") {
      l1 = `${hhmm(v.started_at)} ${v.program_label} · ${v.steps_done ?? 0}/${v.steps_total ?? 0} 단계`;
      // 흐른 시간 | 지금 단계. 시간은 1초마다 올라간다 (mm:ss, 1시간 넘으면 HH:mm:ss). 긴 단계 이름은 CSS 가 … 로 자른다
      l2 = clock(elapsedSec(v)) + (v.current_label ? ` | ${v.current_label}` : "");
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

// 진행 시간. started_at(PC 시각, 시간대 없음)은 이 브라우저의 지역 시각으로 읽는다. 없으면 PC 가 올린 elapsed_sec
function elapsedSec(v) {
  const t = v.started_at ? Date.parse(v.started_at) : NaN;
  return Number.isFinite(t) ? Math.max(0, Math.floor((Date.now() - t) / 1000)) : (v.elapsed_sec || 0);
}
// mm:ss, 1시간을 넘으면 HH:mm:ss
function clock(sec) {
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  const mmss = `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  return h ? `${String(h).padStart(2, "0")}:${mmss}` : mmss;
}
// 얼마나 지났는지 한 단위로: 59초까지 초, 59분까지 분, 23시간까지 시간, 그 뒤는 일
function ago(sec) {
  if (sec < 60) return `${sec}초`;
  if (sec < 3600) return `${Math.floor(sec / 60)}분`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}시간`;
  return `${Math.floor(sec / 86400)}일`;
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
  $("tiles").classList.toggle("hide", !tiles.length);
  $("tiles").replaceChildren(...tiles.map(([k, v, u, approx]) => {
    const d = document.createElement("div"); d.className = "tile";
    d.innerHTML = `<span class="k">${esc(k)}</span><span class="v num">${approx ? '<span class="approx">≈</span>' : ""}${esc(v)}<small>${esc(u)}</small></span>`;
    return d;
  }));
  // 연결·다음 자동 실행은 처리 건수와 성격이 달라 상태 띠 오른쪽에 붙인다 (띠 색을 따라가므로 글자색은 안 준다)
  const conn = off != null && off <= staleSec();
  const sch = live?.schedule;
  $("hero-side").replaceChildren(...[
    ["연결", conn ? "정상" : (off == null ? "없음" : `끊김 ${ago(off)}`), "conn"],
    ["다음 자동 실행", sch?.enabled && sch.next_run_at ? when(sch.next_run_at) : "꺼짐", ""],
  ].map(([k, v, id]) => {
    const d = document.createElement("div"); d.className = "stat";
    d.innerHTML = `<span class="k">${k}</span><span class="v num"${id ? ` id="${id}"` : ""}>${esc(v)}</span>`;
    return d;
  }));
}

// 도넛 SVG. 둘레 100 으로 맞춘 stroke-dasharray. 가운데 글자는 없다 (수치는 옆 범례에)
function donutSvg(ok, bad, crash, size) {
  // 세 색: 성공 초록 → 오류 노랑 → 실패 빨강. 바탕 고리를 빨강으로 다 칠하고 초록·노랑 호를 12시부터 차례로 얹는다
  // (둘레 100 이라 dasharray 가 곧 %). 실행이 없으면 빗금 고리 (index.html 의 #hatch 무늬)
  const total = ok + bad + crash;
  const goodLen = total ? ok / total * 100 : 0, crashLen = total ? crash / total * 100 : 0;
  const arc = (len, start, color) => `<circle cx="21" cy="21" r="15.915" fill="none" stroke="${color}" stroke-width="6"
      stroke-dasharray="${len} ${100 - len}" stroke-dashoffset="${25 - start}"></circle>`;
  return `<svg viewBox="0 0 42 42" width="${size}" height="${size}" role="img" aria-label="${total ? esc(`성공 ${ok}건, 실패 ${bad}건, 오류 ${crash}건`) : "실행 없음"}">
    <circle cx="21" cy="21" r="15.915" fill="none" stroke="${total ? "var(--bad)" : "url(#hatch)"}" stroke-width="6"></circle>
    ${total ? arc(goodLen, 0, "var(--good)") + arc(crashLen, goodLen, "var(--warn-mark)") : ""}
  </svg>`;
}

const RECENT_MAX = 20;   // 에이전트가 올리는 만큼 다 그린다. 보이는 건 15칸까지, 나머지는 옆으로 민다
const VISIBLE_MAX = 15, CELL_MIN = 48, CELL_MAX = 72, GAP_MIN = 6;

function fitStrip() {
  // 남는 폭에 15칸이 꼭 맞게 칸 크기(48~72px)를 정하고, 그래도 남으면 간격을 벌린다. 좁으면 48px 로 두고 옆으로 민다
  const s = root && $("recent-strip");
  const w = s ? s.clientWidth : 0;
  if (!w) return;
  const cell = Math.max(CELL_MIN, Math.min(CELL_MAX, Math.floor((w + GAP_MIN) / VISIBLE_MAX) - GAP_MIN));
  const gap = Math.max(GAP_MIN, (w - cell * VISIBLE_MAX) / (VISIBLE_MAX - 1));
  s.style.setProperty("--cell", `${cell}px`);
  s.style.setProperty("--sgap", `${gap}px`);
  s.scrollLeft = s.scrollWidth;   // 오늘이 오른쪽 끝, 도넛 옆에
}

function paintRecent() {
  // 띠는 최근 20일 전부, 큰 도넛은 오늘(마지막 날)만. 내용이 같으면 다시 그리지 않는다
  const days = (live?.recent || []).slice(-RECENT_MAX);
  const key = JSON.stringify(days);
  if (key === paintedRecent) return;
  paintedRecent = key;
  const today = days[days.length - 1] || {};
  const ok = today.success || 0, bad = today.failed || 0, crash = today.crashed || 0;   // 옛 에이전트는 crashed 를 안 올린다 (실패에 합산)
  $("recent-meta").textContent = days.length
    ? (ok + bad + crash ? `오늘 성공 ${ok} · 실패 ${bad}` + (crash ? ` · 오류 ${crash}` : "") : "오늘 실행 없음") : "";
  const strip = $("recent-strip");
  strip.replaceChildren(...days.map((d) => {
    const cell = document.createElement("button");
    const n = (d.success || 0) + (d.failed || 0) + (d.crashed || 0);
    cell.className = "day" + (n ? "" : " empty");
    cell.dataset.date = d.date;
    cell.title = n ? `${d.date} · 성공 ${d.success || 0} 실패 ${d.failed || 0} 오류 ${d.crashed || 0} · 기록 보기` : `${d.date} · 실행 없음`;
    cell.innerHTML = `${donutSvg(d.success || 0, d.failed || 0, d.crashed || 0, 44)}<div class="d">${esc(d.date.slice(5).replace("-", "/"))}</div>`;
    cell.onclick = () => { $("hist-date").value = d.date; showView("history"); loadHistory(d.date); };
    return cell;
  }));
  fitStrip();
  const total = ok + bad + crash;
  $("recent-donut").innerHTML = total
    ? `${donutSvg(ok, bad, crash, 104)}<div class="legend"><span><i style="background:var(--good)"></i>성공 ${esc(ok)}</span><span><i style="background:var(--bad)"></i>실패 ${esc(bad)}</span><span><i style="background:var(--warn-mark)"></i>오류 ${esc(crash)}</span></div>`
    : donutSvg(0, 0, 0, 104);   // 실행이 없는 날도 같은 자리에 빗금 도넛 (칸과 같은 모양)
}

/** 이미 있는 목록은 제자리에서 고친다. 통째로 새로 그리면 진행 중 점의 애니메이션이 매번 처음부터 다시 돈다 */
function paintStepsInto(ul, steps) {
  const list = steps || [], rows = ul.children;
  const same = rows.length === list.length
    && list.every((s, i) => rows[i].children[1].textContent === (s.label || s.key));
  if (!same) { ul.replaceChildren(...stepList(list).children); return; }
  list.forEach((s, i) => {
    const li = rows[i], note = li.children[2];
    if (li.className !== stepClass(s)) li.className = stepClass(s);
    if (note.textContent !== stepNote(s)) { note.textContent = stepNote(s); note.title = stepNote(s); }
  });
}
const stepClass = (s) => (s.state === "skipped" && s.note === "설정에서 끔") ? "skipped" : (s.state || "pending");
const stepNote = (s) => (s.state === "skipped" && s.note === "설정에서 끔") ? "설정에서 끔"
  : (s.note || (s.state === "running" ? "진행 중" : ""));

function stepList(steps) {
  const ul = document.createElement("ul");
  ul.className = "steps";
  ul.replaceChildren(...(steps || []).map((s) => {
    const li = document.createElement("li");
    li.className = stepClass(s);
    li.append(Object.assign(document.createElement("span"), { className: "mark" }),
              Object.assign(document.createElement("span"), { textContent: s.label || s.key }),
              Object.assign(document.createElement("span"), { className: "note", textContent: stepNote(s), title: stepNote(s) }));
    return li;
  }));
  return ul;
}

function paintSteps() {
  for (const k of ["routine", "prepare"]) {
    const v = live?.programs?.[k];
    const ul = $(`list-${k}`), meta = $(`meta-${k}`);
    if (!v) { ul.replaceChildren(); meta.textContent = "기록 없음"; continue; }
    if (v.state !== "running" && !isToday(v)) {   // 어제 것은 지우고 언제가 마지막이었는지만 남긴다
      ul.replaceChildren();
      meta.textContent = `오늘 실행 없음 · 마지막 ${when(v.finished_at || v.started_at)}`;
      continue;
    }
    const steps = v.steps || [];
    meta.textContent = `${STATE_LABEL[v.state] || v.state} · ${v.steps_done ?? 0}/${v.steps_total ?? steps.length}` + (v.duration_sec != null ? ` · ${dur(v.duration_sec)}` : "");
    paintStepsInto(ul, steps);
  }
}

/** 로그는 단계별 한 줄로만 보여준다. RPA 원본 로그(log_tail)는 화면에 담기엔 너무 길다 - PC 의 로그 파일에 그대로 남는다 */
function logLines(v) {
  return (v?.steps || []).filter((s) => ["running", "done", "failed", "stopped"].includes(s.state)).map((s) => {
    const label = s.label || s.key;
    const at = (s.finished_at || s.started_at || "").slice(11, 19) || "--:--:--";
    if (s.state === "running") return `[${at}] ${label} 진행 중`;
    if (s.state === "done") return `[${at}] ${label} 성공`;
    return `[${at}] ${label} ${STATE_LABEL[s.state] || s.state} : ${s.note || `${label} 단계에서 오류가 발생했습니다.`}`;
  });
}

function paintLog() {
  const v = latest();
  const lines = (v && (v.state === "running" || isToday(v))) ? logLines(v) : [];
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
  // 오류(crashed)는 노랑 채움 알약, 실패(stopped·failed)는 옅은 빨강 알약
  const cls = r.state === "success" ? "good" : r.state === "running" ? "run" : r.state === "crashed" ? "crash" : "bad";
  const t = (r.started_at || "").slice(5, 16).replace("T", " ").replace("-", "/");
  const prog = PROGRAM_SHORT[r.program] || r.program_label || r.program || "";   // 표에선 'RPA' 를 뗀다
  tr.innerHTML = `<td class="num">${esc(t)}</td><td>${esc(prog)}</td><td><span class="pill ${cls}">${esc(STATE_LABEL[r.state] || r.state || "")}</span></td><td class="num">${esc(dur(r.duration_sec))}</td><td class="muted">${esc(r.reason || ms)}</td>`;
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
/** 명령·설정 안내는 토스트 하나를 이어서 고쳐 쓴다 (보냄 → 진행 중 → 결과) */
const notify = (kind, text, ttlMs) => toast(kind, text, ttlMs, "act");

async function sendCommand(type, args, label) {
  if (busy || !c.pcId) return;
  busy = true; paintButtons();
  notify("info", `${label} 명령을 보냈습니다. PC 응답을 기다립니다.`);
  try {
    const now = Math.floor(Date.now() / 1000);
    const node = await push(ref(c.db, P("commands", c.me.cid, c.pcId)), {
      type, args: args ?? null, by: c.me.uid, created_at: now, expires_at: now + COMMAND_TTL_SEC, state: "queued",
    });
    await watchCommand(node.key, label);
  } catch (e) {
    notify("bad", e.code === "PERMISSION_DENIED" ? "권한이 없습니다" : `보내지 못했습니다 (${e.code || e})`);
  } finally {
    busy = false;
    if (root) paintButtons();
  }
}

function watchCommand(cmdKey, label) {
  return new Promise((resolve) => {
    const timer = setTimeout(() => { off(); if (root) notify("bad", "PC 가 응답하지 않습니다"); resolve(); }, 60000);
    const off = onValue(ref(c.db, `${P("commands", c.me.cid, c.pcId)}/${cmdKey}`), (snap) => {
      const v = snap.val();
      if (!v || !root) return;
      if (v.state === "running") notify("info", `${label} 진행 중`);
      if (["done", "failed", "expired"].includes(v.state)) {
        clearTimeout(timer); off();
        notify(v.state === "done" ? "ok" : "bad", v.result || v.state);
        resolve();
      }
    });
  });
}

/** 이 PC 에서 RPA 가 돌고 있나 (누가 실행했든). 1PC 1프로그램이라 그 동안에는 다시 못 띄운다.
 *  launching 은 띄운 프로세스가 살아 있다는 뜻 - 명령이 done 이 된 뒤 상태 파일에 running 이 찍히기까지의 틈을 메운다 */
function rpaRunning() {
  return live?.launching === true || Object.values(live?.programs || {}).some((p) => p && p.state === "running");
}
function paintButtons() {
  const off = !c.isAdmin || busy || !c.pcId;
  const running = rpaRunning();
  for (const id of ["run-prepare", "run-routine", "run-all"]) {
    $(id).disabled = off || running;                     // 다른 사람이 이미 돌리는 중이면 못 누른다
    $(id).title = running && !off ? "RPA 가 돌고 있어 실행할 수 없습니다" : "";
  }
  $("stop-erpia").disabled = off;                        // 종료는 도는 중에도 눌러야 한다
  paintModuleMeta(); paintScheduleMeta();
}

// --- 실행 모듈 ------------------------------------------------------
const LOCKED = new Set(["Login"]);   // 항상 켬. 관리자도 못 끈다 (에이전트도 파일에 Y 로 고정)
// 앞 모듈이 꺼지면 따라 꺼지는 모듈. 운송장 출력은 물류관리가 만든 화면에서 돌기 때문에 혼자 돌 수 없다 (에이전트도 못 박는다)
const NEEDS = { Output: "Logistics" };

/** 이 업체가 안 쓰는 모듈 (총괄이 meta/companies/{cid}/apps/rpa/modules 에 false 로 정한다). 화면에서 아예 숨긴다 */
const offByCompany = (k) => c?.policy?.rpa?.modules?.[k] === false;
const shownModules = () => MODULES.filter(([k]) => !offByCompany(k));

/** 딸린 모듈과 업체 정책을 규칙대로 끈다. 켜는 것은 사람이 직접 한다 (물류관리를 켜도 출력은 꺼진 채로 둘 수 있다) */
function applyNeeds(mods) {
  for (const k of Object.keys(mods)) if (offByCompany(k)) mods[k] = false;
  for (const [k, need] of Object.entries(NEEDS)) if (!mods[need]) mods[k] = false;
  return mods;
}
const savedModules = () => live?.modules || {};
function resetModules() {
  form.modules = applyNeeds(Object.fromEntries(MODULES.map(([k]) => [k, LOCKED.has(k) || savedModules()[k] !== false])));
  paintModules();
}
function modulesDirty() {
  return MODULES.some(([k]) => !!form.modules[k] !== (!offByCompany(k) && savedModules()[k] !== false));
}
const dict = (pairs) => Object.fromEntries(pairs);
// 받침이 있으면 '을', 없으면 '를' (한글이 아니면 '를')
const josa = (w) => {
  const code = (w || "").charCodeAt((w || "").length - 1) - 0xac00;
  return code >= 0 && code < 11172 && code % 28 ? "을" : "를";
};
function paintModules() {
  $("mod-list").replaceChildren(...shownModules().map(([k, text], i) => {
    const row = document.createElement("label"); row.className = "switch" + (i === 0 ? " first" : "");
    const cb = document.createElement("input");
    const needOff = NEEDS[k] && !form.modules[NEEDS[k]];   // 앞 모듈이 꺼져 있으면 이 스위치는 잠근다
    cb.type = "checkbox"; cb.checked = !!form.modules[k]; cb.disabled = !c.isAdmin || busy || LOCKED.has(k) || needOff;
    cb.setAttribute("aria-label", text);
    if (needOff) { const need = dict(MODULES)[NEEDS[k]]; row.title = `${need}${josa(need)} 켜야 쓸 수 있습니다`; }
    cb.onchange = () => {
      form.modules[k] = cb.checked;
      // 딸린 모듈이 있는 스위치면 다시 그린다 (끄면 딸린 것도 꺼지고 잠기고, 켜면 잠금만 풀린다)
      if (Object.values(NEEDS).includes(k)) { applyNeeds(form.modules); paintModules(); return; }
      paintModuleMeta();
    };
    row.append(Object.assign(document.createElement("span"), { textContent: text }), cb, Object.assign(document.createElement("span"), { className: "knob" }));
    return row;
  }));
  paintModuleMeta();
}
function paintModuleMeta() {
  const shown = shownModules();
  const on = shown.filter(([k]) => form.modules[k]).length;
  $("mod-meta").textContent = live ? `${on}/${shown.length} 켬` : "";
  $("mod-apply").disabled = !c.isAdmin || busy || !modulesDirty() || on === 0;
}
async function applyModules() {
  const wanted = applyNeeds(Object.fromEntries(MODULES.map(([k]) => [k, !!form.modules[k]])));
  if (!Object.values(wanted).some(Boolean)) { notify("warn", "최소 한 모듈은 켜야 합니다"); return; }
  try {
    await set(ref(c.db, `${P("settings", c.me.cid, c.pcId)}/modules`), wanted);
  } catch (e) { notify("bad", e.code === "PERMISSION_DENIED" ? "권한이 없습니다" : `저장하지 못했습니다 (${e.code || e})`); return; }
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
  } catch (e) { notify("bad", e.code === "PERMISSION_DENIED" ? "권한이 없습니다" : `저장하지 못했습니다 (${e.code || e})`); return; }
  await sendCommand("set_schedule", payload, "자동 실행");
}
