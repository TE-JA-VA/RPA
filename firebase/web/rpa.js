// RPA 앱 화면. 껍데기(app.js)가 mount(root, ctx) 로 띄우고 unmount() 로 걷는다.
// 현황은 apps/rpa/live/{cid}/{pcId} (RTDB), 기록은 runs/{cid}/items (Firestore). 기준값은 PC 가 올린 live 다.
import { ref, onValue } from "https://www.gstatic.com/firebasejs/10.14.1/firebase-database.js";
import {
  getFirestore, collection, query, where, orderBy, limit, getDocs, connectFirestoreEmulator,
  doc, getDoc, getAggregateFromServer, sum,
} from "https://www.gstatic.com/firebasejs/10.14.1/firebase-firestore.js";
import { HEARTBEAT_EVERY_DEFAULT, HEARTBEAT_MISS } from "./firebase-config.js";
import { toast } from "./toast.js";
import { P, esc, MODULES, hhmm, when, isoDay, sendCommand, slotNames, openWindow, repeatOf } from "./rpa-common.js";
export * as settings from "./rpa-settings.js";   // 관리 > 환경설정 이 이 앱의 설정 화면을 붙인다 (settings.js)

export const key = "rpa";
export const label = "RPA";
export const icon = "▣";
export const perPc = true;

// 상태 이름은 세 가지로 통일 (2026-09-22): 성공 / 실패(단계 검사에서 스스로 멈춤, 사용자 중지 포함) / 오류(프로그램이 죽음).
// 상태 카드·도넛 범례·기록 표 알약이 모두 같은 말을 쓴다. done·skipped 는 단계 상태
const STATE_LABEL = { running: "진행 중", success: "성공", failed: "실패", stopped: "실패", crashed: "오류", done: "완료", skipped: "건너뜀" };
const PROGRAM_SHORT = { routine: "루틴", prepare: "프리페어", observer: "옵저버" };   // 기록 표의 프로그램 칸. RPA 인 건 아니까 뗀다
const HERO_TITLE = { running: "진행 중", success: "성공", failed: "실패", stopped: "실패", crashed: "오류" };
const HISTORY_LIMIT = 100;

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
    <span class="ver-note hide" id="ver"></span>
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
          <div class="msg" id="token-line" hidden></div>
          <div class="msg bad" id="repeat-line" hidden></div>
          <button class="apply" id="repeat-resume" hidden>반복 다시 시작</button>
        </div>
        <div class="card hide" id="usage-card">
          <h2>이번 달 사용량 <span class="muted" id="usage-meta"></span></h2>
          <div id="usage-list"></div>
          <div class="msg" id="usage-sum"></div>
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
let fs = null;
let resizeObs = null;
let tick = null;   // 1초마다 상태 카드·연결 칸을 다시 그린다 - 진행 시간이 올라가고, 에이전트가 죽어도(값이 안 바뀜) 끊김이 보이게
let seenRun = {};  // 프로그램별로 마지막에 본 "run_id:상태" (토스트를 두 번 울리지 않게)
let paintedRecent = null;   // 마지막으로 그린 최근 20일 (같으면 다시 안 그린다 - 스크롤이 튀지 않게)

const $ = (id) => root.querySelector(`#${id}`);
const show = (el, on) => el.classList.toggle("hide", !on);
const dur = (sec) => sec == null ? "" : sec >= 60 ? `${Math.floor(sec / 60)}분 ${sec % 60}초` : `${sec}초`;
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
  $("run-routine").onclick = () => send("launch", { target: "routine" }, "루틴 RPA");
  $("run-prepare").onclick = () => send("launch", { target: "prepare" }, "프리페어 RPA");
  $("run-all").onclick = () => send("launch", { target: "all" }, "전체 실행");
  $("stop-erpia").onclick = () => { if (confirm("ERPia 를 종료할까요?")) send("stop_erpia", null, "ERPia 종료"); };
  $("repeat-resume").onclick = () => send("resume_repeat", null, "반복 다시 시작");
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
  tick = setInterval(() => { if (root && live) { paintHero(); paintTiles(); paintRepeat(); } }, 1000);   // 시간대가 열리고 닫히는 것은 시각이 정한다
  if (!c.pcId) { $("h-state").textContent = "등록된 PC 가 없습니다"; return; }
  stopLive = onValue(ref(c.db, P("live", c.me.cid, c.pcId)), (snap) => {
    const v = snap.val();
    const first = live == null;
    live = v || {};
    runToasts(first);
    paintHero(); paintTiles(); paintRecent(); paintSteps(); paintLog();
    paintButtons();
  }, (e) => { $("h-state").textContent = e.code === "PERMISSION_DENIED" ? "권한 없음" : "읽지 못했습니다"; });
}

export function unmount() {
  if (stopLive) { stopLive(); stopLive = null; }
  if (resizeObs) { resizeObs.disconnect(); resizeObs = null; }
  if (tick) { clearInterval(tick); tick = null; }
  usageSeq++; usageFor = null;   // 읽는 중인 사용량은 버린다 (화면을 떠난 뒤 늦게 온 결과가 없는 칸을 고치지 않게)
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

// live.version → 탭 줄 오른쪽 "버전" 글과 마우스를 올리면 보이는 글 (배포판 구조 1부 6절). null 이면 숨긴다.
// 옛 에이전트는 version 을 안 올리고, 목록이 없는 판(none)은 version·changed 필드가 빠진 채 온다.
// "최신 버전입니다 / 업데이트가 있습니다" 는 3부(자동 업데이트)에서 내보낸 판 번호가 생기면 붙인다
function verStat(v) {
  if (!v || typeof v !== "object") return null;
  const name = typeof v.version === "string" ? v.version : "";
  if (v.state === "ok" && name) return { text: `버전 ${name}`, title: "", warn: false };
  if (v.state === "mixed") {
    const list = Array.isArray(v.changed) ? v.changed.filter((x) => typeof x === "string") : [];
    const n = Number(v.changed_count) || list.length;
    const more = n > list.length ? ` 외 ${n - list.length}개` : "";
    return { text: `버전 ${name || "?"} · 다른 파일 ${n}`, warn: true,
             title: list.length ? `판 목록과 다른 파일: ${list.join(", ")}${more}` : "" };
  }
  if (v.state === "error") return { text: "버전 확인 실패", title: typeof v.error === "string" ? v.error : "", warn: true };
  return null;
}

// live.update → 판 글 옆 업데이트 상태 (자동 업데이트 9절). 까닭은 마우스 글
const UPD_TEXT = { downloading: "업데이트 받는 중", waiting: "업데이트 대기 중", ready: "바꾸는 중", applying: "바꾸는 중", rolling_back: "바꾸는 중",
  failed: "업데이트 실패", rolled_back: "업데이트 실패 - 옛 판으로 되돌림" };
const UPD_BUSY = ["waiting", "ready", "applying", "rolling_back"];   // 에이전트도 이 동안 실행을 거절한다 (rpa_update.BUSY_STATES)
function updStat(u) {
  if (!u || typeof u !== "object" || typeof u.state !== "string") return null;
  if (u.state === "done") {
    const at = typeof u.at === "string" ? u.at : "";
    return { text: at ? `업데이트됨 (${Number(at.slice(5, 7))}/${Number(at.slice(8, 10))} ${at.slice(11, 16)})` : "업데이트됨", title: "" };
  }
  return UPD_TEXT[u.state] ? { text: UPD_TEXT[u.state], title: typeof u.reason === "string" ? u.reason : "" } : null;
}
const updBusy = () => UPD_BUSY.includes(live?.update?.state);

function paintVer() {
  const v = verStat(live?.version), u = updStat(live?.update), el = $("ver");
  el.textContent = [v?.text, u?.text].filter(Boolean).join(" · ");   // 글자로만 넣는다 (이스케이프가 필요 없다)
  el.title = [v?.title, u?.title].filter(Boolean).join(" / ");
  el.classList.toggle("warn", !!v?.warn || ["failed", "rolled_back"].includes(live?.update?.state));
  el.classList.toggle("hide", !v && !u);
}

/** 상태 띠 '다음 자동 실행'. 열린 반복 시간대면 '반복 중 · 12:00까지' (다음 회차) / '반복 멈춤'.
 *  아니면 다음 줄 - '고르기' 면 모듈 이름까지 (예: 10월 7일 (화) 11:00 · 물류관리). 옛 판 PC 는 줄이 없어 시각만 */
function nextRunText(sch) {
  const win = openWindow(sch), rep = repeatOf(sch, win);
  if (win) {
    if (rep?.stopped) return "반복 멈춤";
    const soon = rep?.next_at && Date.parse(rep.next_at) > Date.now() ? ` · 다음 ${hhmm(rep.next_at)}` : "";
    return `반복 중 · ${win.until}까지${soon}`;
  }
  if (!(sch?.enabled && sch.next_run_at)) return "꺼짐";
  const slot = (Array.isArray(sch.slots) ? sch.slots : []).find((s) => s && s.at === sch.next_slot);
  const names = slotNames(slot);
  return when(sch.next_run_at) + (slot?.until ? " 반복" : "") + (names ? ` · ${names}` : "");
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
    ["다음 자동 실행", nextRunText(sch), ""],
  ].map(([k, v, id]) => {
    const d = document.createElement("div"); d.className = "stat";
    d.innerHTML = `<span class="k">${k}</span><span class="v num"${id ? ` id="${id}"` : ""}>${esc(v)}</span>`;
    return d;
  }));
  paintVer();
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
  const prog = (PROGRAM_SHORT[r.program] || r.program_label || r.program || "") + (payload.trigger === "repeat" ? " · 반복" : "");   // 표에선 'RPA' 를 뗀다. 처리한 반복 회차 (빈 회차는 기록에 없다)
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
/** 실행 단추의 명령. 응답을 기다리는 동안 단추를 잠근다 */
async function send(type, args, label) {
  if (busy || !c.pcId) return;
  busy = true; paintButtons();
  try { await sendCommand(c, type, args, label, () => !!root); }
  finally { busy = false; if (root) paintButtons(); }
}

/** 이 PC 에서 RPA 가 돌고 있나 (누가 실행했든). 1PC 1프로그램이라 그 동안에는 다시 못 띄운다.
 *  launching 은 띄운 프로세스가 살아 있다는 뜻 - 명령이 done 이 된 뒤 상태 파일에 running 이 찍히기까지의 틈을 메운다 */
function rpaRunning() {
  return live?.launching === true || Object.values(live?.programs || {}).some((p) => p && p.state === "running");
}
// 도는 RPA 의 단추는 화살표 없이 '… 실행중' - 끝나면 (성공·실패·오류) 원래대로 (2026-10-02 요청)
const RUN_LABELS = { "run-prepare": ["prepare", "프리페어 RPA"], "run-routine": ["routine", "루틴 RPA"] };
function paintButtons() {
  const off = !c.isAdmin || busy || !c.pcId;
  const running = rpaRunning();
  const empty = typeof live?.tokens?.balance === "number" && live.tokens.balance <= 0;   // 에이전트도 거절한다 (2부)
  const upd = updBusy();
  for (const id of ["run-prepare", "run-routine", "run-all"]) {
    $(id).disabled = off || running || empty || upd;     // 다른 사람이 이미 돌리는 중이면 못 누른다
    $(id).title = upd && !off ? "업데이트 중이라 잠시 실행할 수 없습니다" : running && !off ? "RPA 가 돌고 있어 실행할 수 없습니다" : "";
  }
  for (const [id, [key, name]] of Object.entries(RUN_LABELS)) {
    const on = live?.programs?.[key]?.state === "running";
    $(id).querySelector(".t").textContent = on ? `${name} 실행중` : name;
    $(id).querySelector(".fly").hidden = on;
    $(id).classList.toggle("busy", on);
  }
  $("stop-erpia").disabled = off;                        // 종료는 도는 중에도 눌러야 한다
  paintTokens(); paintRepeat();
}

// --- 토큰 (2026-10-06, 2부): 실행 단추 아래 늘 보이는 한 줄. 통장이 없는 업체(live.tokens 없음)는 줄이 없다 ------
// 남은 토큰이 1 이상이면 실행은 된다 (도중에 떨어져도 끝까지) - 이번 실행에 드는 것보다 적으면 노랑, 0 이하면 빨강·잠금
function paintTokens() {
  const t = live?.tokens, line = $("token-line");
  paintUsage();                                          // 통장이 사라졌을 때 카드를 숨기는 것도 여기서
  line.hidden = typeof t?.balance !== "number";
  if (line.hidden) return;
  const all = t.cost?.all ?? 0;
  if (t.balance <= 0) {
    line.textContent = `토큰이 없습니다 (남은 ${t.balance}개) - 충전한 뒤 실행하세요`;
    line.className = "msg bad";
  } else {
    line.textContent = `남은 토큰 ${t.balance}개 · 전체 실행 1번에 ${all}개` + (t.balance < all ? " - 마이너스로 떨어질 수 있습니다" : "");
    line.className = t.balance < all ? "msg warn" : "msg";
  }
}

// --- 반복 (3부): 지금 열린 시간대가 멈췄으면 까닭과 [반복 다시 시작] (관리자만) ------------------------------
function paintRepeat() {
  const sch = live?.schedule, rep = repeatOf(sch, openWindow(sch));
  const stopped = !!rep?.stopped;
  $("repeat-line").hidden = !stopped;
  $("repeat-line").textContent = stopped ? `반복 멈춤: ${rep.stopped.reason || ""}`.trim() : "";
  $("repeat-resume").hidden = !stopped || !c.isAdmin;
  $("repeat-resume").disabled = busy || !c.pcId;
}

// --- 이번 달 사용량 (토큰 3부, 관리자만 - 오른쪽 열): 이달 1일과 통장 시작 중 늦은 때부터, 업체 전체(PC 모두)를 서버가 더한다.
// 남은 토큰이 바뀔 때(실행이 끝났거나 충전됐다)만 다시 읽는다. 로그인은 0개라 안 보인다. 새 모듈은 여기와 색인(firestore.indexes.json)에 더한다
const USAGE_KEYS = [...MODULES.filter(([k]) => k !== "Login").map(([k, l]) => [k.toLowerCase(), l]), ["sites", "쇼핑몰·사이트 받기"]];
let usageFor = null, usageSeq = 0;
async function paintUsage() {
  const t = live?.tokens, card = $("usage-card");
  if (typeof t?.balance !== "number") { card.classList.add("hide"); usageFor = null; usageSeq++; return; }
  if (usageFor === t.balance) return;
  usageFor = t.balance;
  const seq = ++usageSeq;                      // 읽는 사이 남은 토큰이 바뀌거나 통장이 사라지면 늦게 온 결과는 버린다
  try {
    const w = (await getDoc(doc(fs, "wallet", c.me.cid))).data();
    if (seq !== usageSeq) return;
    if (!w) { card.classList.add("hide"); return; }
    const kst = new Date().toLocaleString("sv-SE", { timeZone: "Asia/Seoul" }).replace(" ", "T");   // PC 기록의 started_at 과 같은 꼴
    const month = `${kst.slice(0, 7)}-01T00:00:00`, today = `${kst.slice(0, 10)}T00:00:00`;
    const from = w.since > month ? w.since : month;
    // 한 질의에 여러 칸을 같이 더하면 그 칸이 모두 있는 기록만 센다 (Firestore) - 칸마다 따로 (각각 읽기 1번 꼴)
    const one = (at, field) => getAggregateFromServer(query(collection(fs, "runs", c.me.cid, "items"), where("started_at", ">=", at)),
      { s: sum(field) }).then((r) => r.data().s ?? 0);
    const keys = USAGE_KEYS.map(([k]) => k);
    const [total, todayTotal, ...counts] = await Promise.all([
      one(from, "cost"), one(from > today ? from : today, "cost"), ...keys.map((k) => one(from, `used.${k}`))]);
    if (seq !== usageSeq) return;
    const got = Object.fromEntries(keys.map((k, i) => [k, counts[i]]));
    $("usage-list").replaceChildren(...USAGE_KEYS.filter(([k]) => got[k] > 0).map(([k, label]) => {
      const row = document.createElement("div"); row.className = "u-row";
      const name = document.createElement("span"); name.textContent = label;
      const n = document.createElement("span"); n.className = "num"; n.textContent = `${got[k]}회`;
      row.append(name, n);
      return row;
    }));
    $("usage-meta").textContent = `(${+from.slice(5, 7)}월 ${+from.slice(8, 10)}일${from === month ? "" : " 토큰 정보 생성"}부터)`;
    $("usage-sum").textContent = total ? `합계 ${total}개 · 오늘 ${todayTotal}개` : "이번 달에 쓴 토큰이 없습니다";
    card.classList.remove("hide");
  } catch {
    if (seq !== usageSeq) return;
    usageFor = null;                           // 다음 현황 때 다시 읽는다
    $("usage-list").replaceChildren();
    $("usage-sum").textContent = "사용량을 읽지 못했습니다";
    card.classList.remove("hide");
  }
}
