// 옵저버 관제 화면 - observer_hub.py 의 /api 만 부른다 (Firebase·외부 스크립트 없음, 오프라인에서도 뜬다).
// 3초마다 /api/state 를 다시 읽는다. 적용 안 한 예약 변경이 있으면 폼을 덮지 않는다 (rpa-settings.js 의 scheduleDirty 방식).
"use strict";
const $ = (id) => document.getElementById(id);
const DAYS = ["월", "화", "수", "목", "금", "토", "일"];
const STATE_TEXT = { running: "실행 중", success: "완료", stopped: "중단", crashed: "오류" };
const PILL = { running: "run", success: "good", stopped: "bad", crashed: "crash" };
const OTP_PREFIX = "인증번호 입력 대기 - ";
const OTP_HINT = ". 열린 브라우저 창에 번호를 넣고 [확인]을 눌러 주십시오. (5분)";
let state = null;                 // 마지막 /api/state
let form = null;                  // 예약 폼 (사람이 고치는 값)
let picked = new Set();           // 프리셋 표에서 고른 번호
let period = "7";

async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  let data = null;
  try { data = await r.json(); } catch (e) { data = { ok: false, error: `HTTP ${r.status}` }; }
  if (!r.ok && data && data.ok === undefined) data.ok = false;
  return data;
}
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; };
const cell = (tr, cls, child) => { const td = el("td", cls); if (child !== undefined) td.append(child); tr.append(td); return td; };
const hm = (iso) => (iso ? iso.slice(5, 16).replace("T", " ") : "");

// --- 메뉴 ---
function showView(name) {
  for (const a of document.querySelectorAll("#nav a")) {
    const on = a.dataset.view === name;
    a.toggleAttribute("aria-current", on);
    if (on) a.setAttribute("aria-current", "page");
    $(`view-${a.dataset.view}`).classList.toggle("hide", !on);
  }
  if (name === "history") loadHistory();
}
window.addEventListener("hashchange", () => showView(location.hash.slice(1) || "now"));

// --- 현황 ---
function paintNow() {
  const p = state.snapshot.programs.prepare;
  const hero = $("hero");
  const problem = state.pc_problem;
  $("pc-problem").classList.toggle("hide", !problem);
  $("pc-problem").textContent = problem || "";
  const note = p && p.state === "running" ? p.note || "" : "";
  const waiting = note.startsWith(OTP_PREFIX);
  $("otp-band").classList.toggle("hide", !waiting);
  $("otp-band").textContent = waiting ? note + OTP_HINT : "";
  $("host").textContent = state.snapshot.host || "";
  if (!p) {
    hero.dataset.state = "none";
    $("hero-title").textContent = "실행 기록 없음";
    $("hero-sub").textContent = ""; $("hero-side").textContent = "";
    $("steps").textContent = "실행한 적이 없습니다.";
  } else {
    hero.dataset.state = p.state;
    $("hero-title").textContent = `ACTOR ${STATE_TEXT[p.state] || p.state}`;
    $("hero-sub").textContent = p.state === "running" ? (p.current_label ? `${p.current_label} ${p.note || ""}` : "시작하는 중입니다.")
      : (p.reason || "") ;
    $("hero-side").textContent = `${hm(p.started_at)} 시작` + (p.finished_at ? ` · ${hm(p.finished_at)} 끝` : "");
    const box = $("steps"); box.replaceChildren(); box.classList.remove("muted");
    for (const s of p.steps || []) {
      const row = el("div", "st");
      row.append(el("span", `pill ${s.state === "done" ? "good" : s.state === "failed" ? "bad" : s.state === "stopped" ? "halt" : s.state === "running" ? "run" : "halt"}`,
        { done: "완료", failed: "실패", stopped: "중단", running: "진행", skipped: "건너뜀", pending: "대기" }[s.state] || s.state));
      row.append(el("span", "", s.label || s.key));
      if (s.note) row.append(el("span", "note", s.note));
      box.append(row);
    }
  }
  const sch = state.schedule;
  const run = state.launch && !state.running ? `ACTOR 를 띄우는 중입니다. (${state.launch.sec}초)` : "";
  $("now-schedule").textContent = run || (sch.enabled ? `다음 자동 실행: ${sch.next_run_at ? hm(sch.next_run_at) : "(계산 중)"}` + (sch.waiting_reason ? ` · ${sch.waiting_reason}` : "")
    : "자동 실행 꺼짐");
  $("now-error").textContent = sch.last_error ? `마지막 예약 오류: ${sch.last_error}` : "";
  $("stop-btn").disabled = !state.running && !state.launch;
}

// --- 프리셋 ---
function lastResult(no) {
  const p = state.snapshot.programs.prepare;
  const s = (p && p.steps || []).find((x) => (x.key || "").startsWith(`PRESET${no}:`));
  if (!s) return ["", ""];
  const text = { done: "완료", failed: "실패", stopped: "중단", running: "진행 중", skipped: "건너뜀", pending: "대기" }[s.state] || s.state;
  return [text, s.note || ""];
}
function paintPresets() {
  const rows = state.presets || [];
  const body = document.querySelector("#presets-table tbody");
  body.replaceChildren();
  const shown = rows.filter((r) => r.steps || r.saved_at);
  $("presets-none").classList.toggle("hide", shown.length > 0);
  for (const r of shown) {
    const tr = el("tr");
    const cb = el("input"); cb.type = "checkbox"; cb.checked = picked.has(r.no); cb.disabled = !r.on; cb.setAttribute("aria-label", `프리셋 ${r.no} 선택`);
    cb.onchange = () => { if (cb.checked) picked.add(r.no); else picked.delete(r.no); paintRunBtn(); };
    cell(tr, "", cb);
    cell(tr, "num", String(r.no));
    cell(tr, "", r.name);
    cell(tr, "num", r.code || "");
    cell(tr, "", el("span", `pill ${r.on ? "good" : "halt"}`, r.on ? "켬" : "끔"));
    const [res, note] = lastResult(r.no);
    const td = cell(tr, "", res); if (note) td.append(" ", el("span", "muted", note));
    cell(tr, "", [r.manual ? "사람 입력 필요" : "", r.imap ? "메일 받기" : "", !r.has_login ? "아이디·비밀번호 없음" : ""].filter(Boolean).join(" · "));
    body.append(tr);
  }
  paintRunBtn();
}
function paintRunBtn() {
  $("run-btn").textContent = picked.size ? `지금 실행 (${[...picked].sort((a, b) => a - b).join("·")})` : "지금 실행";
  $("run-btn").disabled = !!state.pc_problem || state.running || !!state.launch || state.observer_open;
  $("observer-btn").disabled = state.observer_open || state.running;
  $("presets-note").textContent = state.observer_open ? "옵저버가 실행 중입니다. 옵저버를 종료한 뒤 실행하여 주십시오."
    : state.running ? "ACTOR 가 실행 중입니다." : "선택한 프리셋만 실행합니다. 선택하지 않으면 켠 프리셋을 모두 실행합니다.";
}
$("run-btn").onclick = async () => {
  const r = await api("/api/run", { presets: picked.size ? [...picked] : null });
  $("presets-msg").textContent = r.ok ? r.message : r.error;
  $("presets-msg").classList.toggle("bad", !r.ok);
  if (r.ok) { picked.clear(); refresh(); }
};
$("observer-btn").onclick = async () => {
  const r = await api("/api/observer", {});
  $("presets-msg").textContent = r.ok ? r.message : r.error;
  $("presets-msg").classList.toggle("bad", !r.ok);
};
$("stop-btn").onclick = async () => {
  if (!confirm("실행 중인 ACTOR 를 중단하시겠습니까?")) return;
  const r = await api("/api/stop", {});
  $("now-error").textContent = r.ok ? r.message : r.error;
  refresh();
};

// --- 예약 ---
// 줄에 요일이 없으면 공통 요일 (옛 저장 값) - 화면은 줄마다 요일을 보이고 저장한다
const savedSlots = () => (state.schedule.slots || []).map((s) => ({ at: s.at, days: [...(s.days || state.schedule.days || [0, 1, 2, 3, 4])], until: s.until,
  rest_min: s.rest_min ?? 2, presets: s.presets ? [...s.presets] : null }));
const slotKey = (s) => `${s.at}${s.until ? `~${s.until}/${s.rest_min}` : ""}=${s.presets ? [...s.presets].sort((a, b) => a - b).join() : "*"}${s.days ? `@${[...s.days].sort()}` : ""}`;
const slotsKey = (slots) => slots.map(slotKey).sort().join("|");
function resetSchedule() {
  const s = state.schedule;
  form = { enabled: !!s.enabled, days: [...(s.days || [])], holidays: s.skip_holidays !== false, slots: savedSlots() };
  $("sch-enabled").checked = form.enabled;
  $("sch-holidays").checked = form.holidays;
  paintTimes();
}
function scheduleDirty() {
  if (!form) return false;
  const s = state.schedule;
  return form.enabled !== !!s.enabled || form.holidays !== (s.skip_holidays !== false) || slotsKey(form.slots) !== slotsKey(savedSlots());
}
const newDays = () => (form.days.length ? [...form.days] : [0, 1, 2, 3, 4]);
function timeInput(value, label, apply) {
  const inp = el("input", "num"); inp.type = "time"; inp.step = 300; inp.value = value; inp.setAttribute("aria-label", label);
  inp.onchange = () => { apply(inp.value); paintTimes(); };
  return inp;
}
function paintTimes() {
  const box = $("sch-times"); box.replaceChildren();
  form.slots.forEach((s, i) => {
    const t = el("div", "t");
    const head = el("div", "t-head");
    head.append(timeInput(s.at, "시각", (v) => { s.at = v; }));
    if (s.until !== undefined) {
      head.append(el("span", "", "~"), timeInput(s.until, "끝 시각", (v) => { s.until = v; }), el("span", "t-kind", "반복"));
      const rest = el("input", "num rest-min"); rest.type = "number"; rest.min = 1; rest.max = 60; rest.value = s.rest_min; rest.setAttribute("aria-label", "쉬는 시간(분)");
      rest.onchange = () => { s.rest_min = Number(rest.value); paintMeta(); };
      head.append(el("span", "t-kind", "쉬는 시간"), rest, el("span", "t-kind", "분"));
    }
    const del = el("button", "del", "삭제"); del.type = "button"; del.onclick = () => { form.slots.splice(i, 1); paintTimes(); };
    head.append(del);
    t.append(head);
    const days = el("div", "t-line");
    const dm = el("span", "seg days-mini");
    DAYS.forEach((d, k) => {
      const b = el("button", "", d); b.type = "button"; b.setAttribute("aria-pressed", s.days.includes(k));
      b.onclick = () => { s.days = s.days.includes(k) ? s.days.filter((x) => x !== k) : [...s.days, k].sort(); paintTimes(); };
      dm.append(b);
    });
    days.append(dm);
    t.append(days);
    const line = el("div", "t-line");
    const mode = el("select", "mode");
    for (const [v, text] of [["all", "모든 켠 프리셋"], ["pick", "고른 프리셋만"]]) { const o = el("option", "", text); o.value = v; mode.append(o); }
    mode.value = s.presets ? "pick" : "all";
    mode.setAttribute("aria-label", "프리셋 선택");
    mode.onchange = () => { s.presets = mode.value === "pick" ? [] : null; paintTimes(); };
    line.append(mode);
    if (s.presets) {
      const chips = el("span", "seg chips");
      for (const p of (state.presets || []).filter((r) => r.steps)) {
        const b = el("button", "", `${p.no} ${p.name}`); b.type = "button"; b.dataset.no = p.no; b.setAttribute("aria-pressed", s.presets.includes(p.no));
        b.onclick = () => { s.presets = s.presets.includes(p.no) ? s.presets.filter((x) => x !== p.no) : [...s.presets, p.no].sort((a, b2) => a - b2); paintTimes(); };
        chips.append(b);
      }
      line.append(chips);
    }
    t.append(line);
    box.append(t);
  });
  paintMeta();
}
function problems() {
  const out = [];
  for (const s of form.slots) {
    if (!/^\d\d:\d\d$/.test(s.at)) out.push("시각을 입력하여 주십시오.");
    if (!s.days.length) out.push(`${s.at} 줄의 요일을 선택하여 주십시오.`);
    if (s.until !== undefined && (!/^\d\d:\d\d$/.test(s.until) || s.until <= s.at)) out.push(`반복 끝 시각은 시작 시각(${s.at})보다 늦어야 합니다.`);
    if (s.presets && !s.presets.length) out.push(`${s.at} 줄의 프리셋을 선택하여 주십시오.`);
  }
  if (form.enabled && !form.slots.length) out.push("실행 줄을 하나 이상 추가하여 주십시오.");
  return out;
}
function paintMeta() {
  const probs = problems();
  $("sch-msg").textContent = probs[0] || "";
  $("sch-apply").disabled = !scheduleDirty() || probs.length > 0;
  const s = state.schedule;
  $("sch-info").textContent = s.enabled && s.next_run_at ? `다음 자동 실행: ${hm(s.next_run_at)}` : "";
  $("sch-off-note").textContent = s.next_off ? `${s.next_off.date} ${s.next_off.name}에는 자동 실행을 하지 않습니다.` : "공휴일에는 자동 실행을 하지 않습니다.";
  $("sch-add").disabled = form.slots.length >= 12; $("sch-add-win").disabled = form.slots.length >= 12;
}
$("sch-enabled").onchange = () => { form.enabled = $("sch-enabled").checked; paintMeta(); };
$("sch-holidays").onchange = () => { form.holidays = $("sch-holidays").checked; paintMeta(); };
$("sch-add").onclick = () => { form.slots.push({ at: "09:00", days: newDays(), presets: null }); paintTimes(); };
$("sch-add-win").onclick = () => { form.slots.push({ at: "10:00", until: "11:00", rest_min: 2, days: newDays(), presets: null }); paintTimes(); };
$("sch-apply").onclick = async () => {
  const payload = { enabled: form.enabled, days: form.days.length ? form.days : [0, 1, 2, 3, 4], skip_holidays: form.holidays, off_dates: state.schedule.off_dates || [],
    slots: form.slots.map((s) => ({ at: s.at, days: [...s.days].sort(), ...(s.until !== undefined ? { until: s.until, rest_min: s.rest_min } : {}), ...(s.presets ? { presets: [...s.presets] } : {}) })) };
  const r = await api("/api/schedule", payload);
  if (!r.ok) { $("sch-msg").textContent = r.error; return; }
  state.schedule = r.schedule;
  resetSchedule();
  $("sch-msg").textContent = "";
  $("sch-info").textContent = "예약을 저장하였습니다." + (r.schedule.next_run_at ? ` 다음 자동 실행: ${hm(r.schedule.next_run_at)}` : "");
};

// --- 기록 ---
async function loadHistory() {
  const r = await api(`/api/history?period=${period}`);
  if (!r.summary) return;
  const tiles = $("hist-tiles"); tiles.replaceChildren();
  for (const [k, v] of [["실행", r.summary.total], ["완료", r.summary.success], ["중단", r.summary.stopped], ["오류", r.summary.crashed]]) {
    const t = el("div", "tile"); t.append(el("div", "k", k), el("div", "v num", String(v))); tiles.append(t);
  }
  const body = document.querySelector("#hist-table tbody"); body.replaceChildren();
  $("hist-none").classList.toggle("hide", r.runs.length > 0);
  for (const run of r.runs) {
    const tr = el("tr");
    cell(tr, "nowrap num", hm(run.started_at));
    cell(tr, "nowrap", el("span", `pill ${run.reason === "대시보드에서 중단했습니다" ? "halt" : PILL[run.state] || "halt"}`, STATE_TEXT[run.state] || run.state));
    cell(tr, "", run.last_step || "");
    const files = (run.metrics || []).filter((m) => (m.key || "").endsWith(":files")).reduce((a, m) => a + (Number(m.value) || 0), 0);
    cell(tr, "num", `${files}개`);
    cell(tr, "", run.reason || "");
    const td = cell(tr, "nowrap");
    if (run.state !== "success") { const b = el("button", "", "사진 열기"); b.onclick = async () => { const x = await api("/api/open", { run_id: run.run_id }); if (!x.ok) alert(x.error); }; td.append(b); }
    body.append(tr);
  }
}
for (const b of document.querySelectorAll("#hist-period button")) b.onclick = () => {
  period = b.dataset.p;
  for (const x of document.querySelectorAll("#hist-period button")) x.setAttribute("aria-pressed", x === b);
  loadHistory();
};

// --- 설정 ---
let settingsTouched = false;
function paintSettings() {
  if (settingsTouched) return;
  $("set-dir").value = state.settings.download_dir || "";
  $("set-parallel").value = state.settings.parallel || 1;
  $("set-parallel").max = state.limits.parallel_max;
  $("set-parallel-note").textContent = `ACTOR 가 동시에 여는 사이트 창 수입니다. (1~${state.limits.parallel_max})`;
}
$("set-dir").oninput = () => { settingsTouched = true; };
$("set-parallel").oninput = () => { settingsTouched = true; };
$("set-apply").onclick = async () => {
  const r = await api("/api/settings", { download_dir: $("set-dir").value, parallel: Number($("set-parallel").value) });
  $("set-msg").textContent = r.ok ? "설정을 저장하였습니다." : r.error;
  $("set-msg").classList.toggle("bad", !r.ok); $("set-msg").classList.toggle("good", !!r.ok);
  if (r.ok) { settingsTouched = false; refresh(); }
};

// --- 3초마다 ---
async function refresh() {
  const s = await api("/api/state");
  if (!s || !s.snapshot) return;
  const dirty = scheduleDirty();
  state = s;
  paintNow(); paintPresets(); paintSettings();
  if (!dirty) resetSchedule(); else paintMeta();
}
refresh().then(() => { showView(location.hash.slice(1) || "now"); });
setInterval(refresh, 3000);
