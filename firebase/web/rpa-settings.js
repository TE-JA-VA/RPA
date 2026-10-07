// RPA 의 환경설정 - 관리 > 환경설정 (settings.js) 이 붙인다. 실행 모듈 · 쇼핑몰 프리셋 · 자동 실행 (PC 마다).
// 값의 기준은 PC 가 올린 live. 적용 = settings 에 쓰고 명령을 넣는다 - PC 가 반영해 live 로 돌려준다
import { ref, onValue, set } from "https://www.gstatic.com/firebasejs/10.14.1/firebase-database.js";
import { P, MODULES, WELLIFE_MODULES, wellifeOn, LOCKED, NEEDS, DAYS, when, dict, josa, switchText, notify, sendCommand, RUN_CHIPS, slotNames, slotText, isoDay } from "./rpa-common.js";

export const title = "RPA";

const PRESETS = [["평일", [0, 1, 2, 3, 4]], ["매일", [0, 1, 2, 3, 4, 5, 6]], ["주말", [5, 6]]];

const HTML = `
  <div class="settings-grid" id="settings-grid">
    <div>
      <div class="card" id="mod-card">
        <h2>실행 모듈 <span class="muted" id="mod-meta"></span></h2>
        <div class="msg">전체 실행과 '전체' 예약이 이 모듈을 돌립니다</div>
        <div id="mod-list"></div>
        <button class="apply" id="mod-apply" disabled>적용</button>
      </div>
      <div class="card hide" id="shop-card">
        <h2>쇼핑몰 프리셋 <span class="muted" id="shop-meta"></span></h2>
        <div id="shop-list"></div>
        <div class="msg" id="shop-info"></div>
        <button class="apply" id="shop-apply" disabled>적용</button>
      </div>
    </div>
    <div>
      <div class="card" id="sch-card">
        <h2>자동 실행 <span class="muted" id="sch-meta"></span></h2>
        <label class="switch first"><span>켬</span><input type="checkbox" id="sch-enabled"><span class="knob"></span></label>
        <div id="sch-form">
          <div class="lbl">요일</div>
          <div class="seg" id="sch-presets"></div>
          <div class="seg" id="sch-days"></div>
          <div class="lbl">시간 · <span id="sch-count"></span></div>
          <div class="times" id="sch-times"></div>
          <div class="seg"><button id="sch-add">+ 시각</button><button id="sch-add-win" class="hide">+ 반복 시간대</button></div>
          <div class="msg" id="sch-limit"></div>
        </div>
        <div class="msg" id="sch-old" hidden>이 PC 는 새 판을 깔아야 시각별 모듈·반복을 쓸 수 있습니다</div>
        <div class="msg" id="sch-info"></div>
        <button class="apply" id="sch-apply" disabled>적용</button>
      </div>
    </div>
  </div>
  <p class="muted hide" id="no-pc">등록된 PC 가 없습니다</p>`;

let root = null, c = null, stopLive = null, stopLimit = null, stopFeatures = null, busy = false, live = null, liveLimit;
let sent = {};   // 카드마다 마지막으로 [적용] 한 폼 - PC 응답을 기다리는 동안은 '적용 안 한 변경' 이 아니다 (떠날 때 확인)
let form = { modules: {}, shops: {}, sch: { enabled: false, days: [], slots: [] } };
const $ = (id) => root.querySelector(`#${id}`);
const show = (el, on) => el.classList.toggle("hide", !on);

export function mount(el, context) {
  root = el; c = context; busy = false; live = null; liveLimit = undefined; sent = {};
  root.innerHTML = HTML;
  if (!c.pcId) { show($("settings-grid"), false); show($("no-pc"), true); return; }
  $("mod-apply").onclick = applyModules;
  $("shop-apply").onclick = applyShops;
  $("sch-apply").onclick = applySchedule;
  $("sch-enabled").onchange = (e) => { form.sch.enabled = e.target.checked; paintScheduleMeta(); };
  $("sch-add").onclick = () => { if (form.sch.slots.length >= limitOf()) return; form.sch.slots.push({ at: "09:00", run: null }); paintTimes(); paintScheduleMeta(); };
  $("sch-add-win").onclick = () => {
    if (form.sch.slots.length >= limitOf()) return;
    form.sch.slots.push({ at: "10:00", until: "11:00", rest_min: 2, run: [] });
    paintTimes(); paintScheduleMeta();
  };
  $("sch-presets").replaceChildren(...PRESETS.map(([t, days]) => {
    const b = document.createElement("button"); b.textContent = t;
    b.onclick = () => { form.sch.days = [...days]; paintDays(); paintScheduleMeta(); };
    return b;
  }));
  // 업체 한도는 총괄·관리 도구가 바꾼다 - 로그인 때 읽은 값(c.policy) 대신 바로 따라간다
  stopLimit = onValue(ref(c.db, `meta/companies/${c.me.cid}/apps/rpa/limits/schedule`), (snap) => {
    liveLimit = snap.val();
    if (root && live) { paintTimes(); paintScheduleMeta(); }
  }, () => {});
  // 웰라이프 열림도 같은 방식 - 로그인 뒤 관리 화면에서 바뀌어도 따라간다
  stopFeatures = onValue(ref(c.db, `meta/companies/${c.me.cid}/apps/rpa/features`), (snap) => {
    const was = root && live ? [modulesDirty(), scheduleDirty()] : null;   // 정책을 바꾸기 전 목록으로 편집 중인지 본다
    c.policy = { ...c.policy, rpa: { ...c.policy?.rpa, features: snap.val() || {} } };
    if (!was) return;
    if (!was[0]) resetModules();   // 편집 중인 폼은 건드리지 않는다 (보내는 값은 어차피 규칙대로 거른다)
    if (!was[1]) resetSchedule(); else { paintTimes(); paintScheduleMeta(); }
  }, () => {});
  stopLive = onValue(ref(c.db, P("live", c.me.cid, c.pcId)), (snap) => {
    const first = live == null;
    // 편집 중이 아닐 때만 폼을 PC 값으로 맞춘다 (적용 뒤 돌아온 값으로 갱신). 편집 중인지는 바뀌기 전 PC 값과 견준다 -
    // 새 값과 견주면 PC 쪽이 바뀌었을 때 손대지 않은 폼도 '편집 중' 으로 보여 옛 값에 머문다
    const was = first ? [] : [modulesDirty(), shopsDirty(), scheduleDirty()];
    live = snap.val() || {};
    if (first || !was[0]) resetModules();
    if (first || !was[1]) resetShops();
    if (first || !was[2]) resetSchedule();
    paintAll();
  }, (e) => notify("bad", e.code === "PERMISSION_DENIED" ? "권한이 없습니다" : `읽지 못했습니다 (${e.code || e})`));
}

export function unmount() {
  if (stopLive) { stopLive(); stopLive = null; }
  if (stopLimit) { stopLimit(); stopLimit = null; }
  if (stopFeatures) { stopFeatures(); stopFeatures = null; }
  root = null; c = null;
}

/** 적용 안 한 변경이 있나 (떠날 때 확인 - app.js) */
export function dirty() {
  return !!root && !!live && ((modulesDirty() && sent.modules !== keyOf.modules())
    || (shopsDirty() && sent.shops !== keyOf.shops()) || (scheduleDirty() && sent.sch !== keyOf.sch()));
}
const keyOf = { modules: () => JSON.stringify(form.modules), shops: () => JSON.stringify(form.shops), sch: () => JSON.stringify(payloadOf()) };

function paintAll() { paintModuleMeta(); paintShopMeta(); paintScheduleMeta(); }

/** 명령을 넣는 동안 카드 단추를 잠근다 */
async function send(type, args, label) {
  busy = true; paintAll();
  try { await sendCommand(c, type, args, label, () => !!root); }
  finally { busy = false; if (root) paintAll(); }
}

// --- 실행 모듈 ------------------------------------------------------

/** 이 업체가 안 쓰는 모듈 (총괄이 meta/companies/{cid}/apps/rpa/modules 에 false 로 정한다). 화면에서 아예 숨긴다 */
const isWellife = () => wellifeOn(c?.me?.cid, c?.policy);
const modList = () => (isWellife() ? WELLIFE_MODULES : MODULES);
const offByCompany = (k) => c?.policy?.rpa?.modules?.[k] === false;
const shownModules = () => modList().filter(([k]) => !offByCompany(k));

/** 딸린 모듈과 업체 정책을 규칙대로 끈다. 켜는 것은 사람이 직접 한다 (물류관리를 켜도 출력은 꺼진 채로 둘 수 있다) */
function applyNeeds(mods) {
  for (const k of Object.keys(mods)) if (offByCompany(k)) mods[k] = false;
  for (const [k, need] of Object.entries(NEEDS)) if (k in mods && !mods[need]) mods[k] = false;
  return mods;
}
const savedModules = () => live?.modules || {};
function resetModules() {
  form.modules = applyNeeds(Object.fromEntries(modList().map(([k]) => [k, LOCKED.has(k) || savedModules()[k] !== false])));
  paintModules();
}
function modulesDirty() {
  return modList().some(([k]) => !!form.modules[k] !== (!offByCompany(k) && savedModules()[k] !== false));
}
function paintModules() {
  $("mod-list").replaceChildren(...shownModules().map(([k, text], i) => {
    const row = document.createElement("label"); row.className = "switch" + (i === 0 ? " first" : "");
    const cb = document.createElement("input");
    const needOff = NEEDS[k] && !form.modules[NEEDS[k]];   // 앞 모듈이 꺼져 있으면 이 스위치는 잠근다
    cb.type = "checkbox"; cb.checked = !!form.modules[k]; cb.disabled = !c.isAdmin || busy || LOCKED.has(k) || needOff;
    cb.setAttribute("aria-label", text);
    const need = needOff ? dict(modList())[NEEDS[k]] : "";
    cb.onchange = () => {
      form.modules[k] = cb.checked;
      // 딸린 모듈이 있는 스위치면 다시 그린다 (끄면 딸린 것도 꺼지고 잠기고, 켜면 잠금만 풀린다)
      if (Object.values(NEEDS).includes(k)) { applyNeeds(form.modules); paintModules(); return; }
      paintModuleMeta();
    };
    row.append(switchText(text, need && `${need}${josa(need)} 켜야 쓸 수 있습니다`), cb,
      Object.assign(document.createElement("span"), { className: "knob" }));
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
  const wanted = applyNeeds(Object.fromEntries(modList().map(([k]) => [k, !!form.modules[k]])));
  if (!Object.values(wanted).some(Boolean)) { notify("warn", "최소 한 모듈은 켜야 합니다"); return; }
  try {
    await set(ref(c.db, `${P("settings", c.me.cid, c.pcId)}/modules`), wanted);
  } catch (e) { notify("bad", e.code === "PERMISSION_DENIED" ? "권한이 없습니다" : `저장하지 못했습니다 (${e.code || e})`); return; }
  sent.modules = keyOf.modules();
  await send("set_modules", wanted, "실행 모듈");
}

// --- 쇼핑몰 프리셋 --------------------------------------------------
// PC 의 옵저버가 저장한 프리셋 (에이전트가 이름·코드·단계 수·켬만 올린다). 켜면 다음 프리페어부터 그 쇼핑몰에서 엑셀을 받는다.
// 명령 키는 "PRESET1" - 숫자 키는 Realtime DB 가 배열로 바꿔 읽는다
const circled = (n) => String.fromCharCode(0x2460 + n - 1);
const savedShops = () => (Array.isArray(live?.presets) ? live.presets : []);
const shopReady = (p) => p.steps > 0 && p.has_login;
function resetShops() {
  form.shops = Object.fromEntries(savedShops().map((p) => [p.no, !!p.on]));
  paintShops();
}
function shopsDirty() {
  return savedShops().some((p) => !!form.shops?.[p.no] !== !!p.on);
}
function shopLine(p) {
  const saved = p.saved_at ? ` · ${Number(p.saved_at.slice(5, 7))}/${Number(p.saved_at.slice(8, 10))} 저장` : "";
  return `${circled(p.no)} ${p.name}${p.code ? ` (${p.code})` : ""} · ${p.steps}단계${saved}`;
}
function paintShops() {
  show($("shop-card"), Array.isArray(live?.presets));   // 옛 에이전트·설정이 깨진 PC 는 카드를 숨긴다
  const list = savedShops();
  $("shop-list").replaceChildren(...list.map((p, i) => {
    const row = document.createElement("label"); row.className = "switch" + (i === 0 ? " first" : "");
    const cb = document.createElement("input");
    const ready = shopReady(p);
    cb.type = "checkbox"; cb.checked = !!form.shops[p.no];
    cb.disabled = !c.isAdmin || busy || (!ready && !cb.checked);   // 켜진 것은 준비가 안 됐어도 끌 수는 있다
    cb.setAttribute("aria-label", `${circled(p.no)} ${p.name}`);
    const why = ready ? "" : p.steps ? "옵저버에서 아이디·비밀번호를 넣고 저장하세요" : "옵저버에서 기록하고 저장하세요";
    cb.onchange = () => { form.shops[p.no] = cb.checked; paintShopMeta(); };
    row.append(switchText(shopLine(p), why), cb, Object.assign(document.createElement("span"), { className: "knob" }));
    return row;
  }));
  $("shop-info").textContent = list.some((p) => p.steps > 0) ? "" : "기록한 프리셋이 없습니다. 이 PC 의 '옵저버' 에서 기록하세요";
  paintShopMeta();
}
function paintShopMeta() {
  const list = savedShops();
  const on = list.filter((p) => form.shops?.[p.no]).length;
  $("shop-meta").textContent = list.length ? `${on}/${list.length} 켬` : "";
  $("shop-apply").disabled = !c.isAdmin || busy || !shopsDirty();
}
async function applyShops() {
  const wanted = Object.fromEntries(savedShops().map((p) => [`PRESET${p.no}`, !!form.shops[p.no]]));
  try {
    await set(ref(c.db, `${P("settings", c.me.cid, c.pcId)}/presets`), wanted);
  } catch (e) { notify("bad", e.code === "PERMISSION_DENIED" ? "권한이 없습니다" : `저장하지 못했습니다 (${e.code || e})`); return; }
  sent.shops = keyOf.shops();
  await send("set_presets", wanted, "쇼핑몰 프리셋");
}

// --- 자동 실행 (2부: 줄마다 전체/고르기, 업체 한도) ----------------------------------------
// 새 판 PC 는 live.schedule.version 2 와 줄(slots)을 올린다. 없으면 옛 판 - 시각만 넣고 옛 모양 {enabled, days, times} 로 보낸다
const isV2 = () => (live?.schedule?.version ?? 0) >= 2;
/** 업체 한도 '자동 실행 개수' (meta/companies/{cid}/apps/rpa/limits/schedule, 없으면 2). 옛 판 PC 는 3개까지밖에 못 받는다 */
function limitOf() {
  const n = liveLimit !== undefined ? liveLimit : c?.policy?.rpa?.limits?.schedule;
  const lim = Number.isInteger(n) && n >= 0 ? n : 2;
  return isV2() ? lim : Math.min(lim, 3);
}
const savedSch = () => live?.schedule || { enabled: false, days: [] };
/** PC 가 올린 줄 → 폼 줄. run 에서 로그인은 뺀다 (늘 붙으니 화면엔 안 보인다). 옛 판은 times 를 '전체' 줄로 */
function savedSlots() {
  const s = savedSch();
  if (!isV2()) return (s.times || []).map((t) => ({ at: t, run: null }));
  return (Array.isArray(s.slots) ? s.slots : []).filter((x) => x && typeof x.at === "string").map((x) => wellifySlot({
    at: x.at, run: Array.isArray(x.run) ? x.run.filter((k) => k !== "Login") : null,
    ...(x.until ? { until: x.until, rest_min: x.rest_min ?? 2 } : {}),
  }));
}
/** 웰라이프 업체는 '전체' 시각만 - 반복·고르기 줄은 시작 시각만 남긴 '전체' 줄로 (에이전트가 그런 줄을 거절한다). 폼 줄과 보내는 값이 같은 곳을 지난다 */
const wellifySlot = (s) => (isWellife() ? { at: s.at, run: null } : s);
function resetSchedule() {
  const s = savedSch();
  form.sch = { enabled: !!s.enabled, days: [...(s.days || [])], slots: savedSlots() };
  $("sch-enabled").checked = form.sch.enabled;
  paintDays(); paintTimes(); paintScheduleMeta();
}
const runKey = (run) => (run ? [...run].filter((k) => k !== "Login").sort().join() : "*");
const slotKey = (s) => `${s.at}${s.until ? `~${s.until}/${s.rest_min}` : ""}=${runKey(s.run)}`;
const slotsKey = (slots) => slots.map(slotKey).sort().join("|");
function scheduleDirty() {
  const s = savedSch();
  return form.sch.enabled !== !!s.enabled
    || [...form.sch.days].sort().join() !== [...(s.days || [])].sort().join()
    || slotsKey(form.sch.slots) !== slotsKey(savedSlots());
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
const sortedForm = () => [...form.sch.slots].sort((a, b) => a.at.localeCompare(b.at));
function timeInput(value, label, apply) {
  const inp = document.createElement("input"); inp.type = "time"; inp.step = 300; inp.value = value; inp.className = "num";
  inp.setAttribute("aria-label", label);
  inp.onchange = () => { apply(inp.value); paintTimes(); paintScheduleMeta(); };
  return inp;
}
/** 줄의 모듈 단추. 업체가 안 쓰는 모듈은 없다. 운송장은 물류관리를 고르기 전엔 잠김 (실행 모듈 카드와 같은 규칙) */
function runChips(s, withPrepare) {
  const box = document.createElement("span"); box.className = "seg chips";
  for (const [k, text] of RUN_CHIPS) {
    if (k === "Prepare" ? !withPrepare : offByCompany(k)) continue;
    const b = document.createElement("button"); b.type = "button"; b.textContent = text; b.dataset.k = k;
    b.setAttribute("aria-pressed", s.run.includes(k));
    const locked = k === "Output" && !s.run.includes("Logistics");
    b.disabled = !c.isAdmin || busy || locked;
    if (locked) b.title = "물류관리를 켜야 쓸 수 있습니다";
    b.onclick = () => {
      s.run = s.run.includes(k) ? s.run.filter((x) => x !== k) : [...s.run, k];
      if (!s.run.includes("Logistics")) s.run = s.run.filter((x) => x !== "Output");
      paintTimes(); paintScheduleMeta();
    };
    box.append(b);
  }
  return box;
}
function paintTimes() {
  const over = new Set(sortedForm().slice(limitOf()));      // 시각 순으로 한도를 넘는 줄 (PC 도 이 줄은 안 돌린다)
  $("sch-times").replaceChildren(...form.sch.slots.map((s, i) => {
    const row = document.createElement("div"); row.className = "t" + (over.has(s) ? " over" : "");
    row.append(timeInput(s.at, "시각", (v) => { s.at = v; }));
    if (s.until) {                                   // 반복 시간대 줄: 시작 ~ 끝 · 모듈 (쇼핑몰 받기 없음) · 쉬는 시간
      const rest = document.createElement("input");
      Object.assign(rest, { type: "number", min: 1, max: 60, value: s.rest_min, className: "num rest-min" });
      rest.setAttribute("aria-label", "쉬는 시간 (분)");
      rest.onchange = () => { s.rest_min = Number(rest.value); paintScheduleMeta(); };
      row.append(Object.assign(document.createElement("span"), { textContent: "~" }), timeInput(s.until, "끝 시각", (v) => { s.until = v; }),
        Object.assign(document.createElement("span"), { className: "muted", textContent: "반복" }), runChips(s, false),
        rest, Object.assign(document.createElement("span"), { className: "muted", textContent: "분 쉬고" }));
    } else if (isV2() && !isWellife()) {
      const mode = document.createElement("select"); mode.className = "mode"; mode.setAttribute("aria-label", "돌릴 모듈");
      mode.append(new Option("전체", "all"), new Option("고르기", "pick"));
      mode.value = s.run ? "pick" : "all";
      mode.onchange = () => { s.run = mode.value === "pick" ? [] : null; paintTimes(); paintScheduleMeta(); };
      row.append(mode);
      if (s.run) row.append(runChips(s, true));
    }
    const del = document.createElement("button"); del.className = "del"; del.textContent = "빼기";
    del.onclick = () => { form.sch.slots.splice(i, 1); paintTimes(); paintScheduleMeta(); };
    row.append(del);
    if (over.has(s)) row.append(Object.assign(document.createElement("span"), { className: "rest", textContent: "미실행 (한도초과)" }));
    return row;
  }));
}
/** 적용을 막는 까닭 (없으면 ""). 줄 모양은 꺼도 지킨다 (PC 가 본다). 한도는 켤 때만 - 끄기는 언제나 된다 (에이전트도 같다) */
function scheduleProblem() {
  const lim = limitOf(), slots = form.sch.slots;
  if (form.sch.enabled && slots.length > lim) return lim ? `자동 실행은 ${lim}개까지입니다 - 줄을 줄여야 적용할 수 있습니다` : "자동 실행을 쓰려면 담당자에게 문의하세요";
  if (slots.some((s) => !/^\d\d:\d\d$/.test(s.at))) return "시간을 확인하세요";
  for (const w of slots.filter((s) => s.until)) {
    if (!/^\d\d:\d\d$/.test(w.until) || w.until <= w.at) return `반복 끝 시각은 시작(${w.at})보다 늦어야 합니다`;
    if (!(Number.isInteger(w.rest_min) && w.rest_min >= 1 && w.rest_min <= 60)) return "쉬는 시간은 1~60분입니다";
    if (!w.run.length) return "반복 줄에 모듈을 하나 이상 고르세요";
    for (const x of slots) {
      if (x === w) continue;
      if (x.until && x.at < w.until && w.at < x.until) return `반복 시간대가 겹칩니다: ${w.at}~${w.until}, ${x.at}~${x.until}`;
      if (!x.until && w.at <= x.at && x.at < w.until) return `${w.at}~${w.until} 반복 안에는 시각을 넣을 수 없습니다`;
    }
  }
  const ats = slots.map((s) => s.at);
  if (new Set(ats).size !== ats.length) return "같은 시각이 두 번 있습니다";
  if (slots.some((s) => s.run && !s.run.length)) return "고르기 줄에 모듈을 하나 이상 고르세요";
  if (!form.sch.enabled) return "";
  if (!form.sch.days.length) return "요일을 하나 이상 고르세요";
  if (!slots.length) return "시간을 하나 이상 넣으세요";
  return "";
}
function paintScheduleMeta() {
  const s = savedSch(), lim = limitOf(), n = form.sch.slots.length;
  const dis = !c.isAdmin || busy;
  $("sch-enabled").disabled = dis;
  for (const el of $("sch-form").querySelectorAll("button, input, select")) if (!el.closest(".chips")) el.disabled = dis;
  $("sch-add").disabled = dis || n >= lim;
  show($("sch-add-win"), isV2() && !isWellife()); $("sch-add-win").disabled = dis || n >= lim;
  $("sch-count").textContent = `${n}/${lim} 사용`;
  const problem = scheduleProblem();
  const full = n >= lim ? (lim ? `자동 실행은 ${lim}개까지입니다. 더 필요하면 담당자에게 문의하세요` : "자동 실행을 쓰려면 담당자에게 문의하세요") : "";
  $("sch-limit").textContent = problem || full;
  $("sch-limit").className = "msg" + (problem ? " bad" : "");
  $("sch-old").hidden = !live || isV2();
  $("sch-meta").textContent = !live ? "" : s.enabled ? `${labelDays(s.days)} ${savedSlots().map(slotText).join(", ")}` : "꺼짐";
  const info = [];
  if (s.enabled && s.next_run_at) {
    const names = slotNames((Array.isArray(s.slots) ? s.slots : []).find((x) => x && x.at === s.next_slot));
    info.push(`다음 ${when(s.next_run_at)}${names ? ` (${names})` : ""}`);
  }
  if (s.last_launch_at) info.push(`마지막 ${when(s.last_launch_at)}${s.last_launch_by === "auto" ? " (자동)" : ""}`);
  if (s.last_error) info.push(`오류: ${s.last_error}`);
  let cls = s.last_error ? " bad" : "";
  const rep = s.repeat;                                  // 반복 상태 (PC 가 적는다) - 오늘 것만
  if (rep && rep.date === isoDay(new Date())) {
    info.push(`오늘 반복 ${rep.runs || 0}회 · 처리 ${rep.done || 0}회`);
    if (rep.stopped) { info.push(rep.stopped.reason || "반복을 멈췄습니다"); cls = " bad"; }
  }
  const t = live?.tokens;                                // 예약 실행은 지켜볼 사람이 없다 - 토큰이 모자라면 여기에도 (토큰 2부)
  if (s.enabled && typeof t?.balance === "number") {
    const need = t.cost?.next ?? t.cost?.all ?? 0;       // 다음 줄이 '고르기' 면 그 줄의 토큰 (에이전트가 cost.next)
    if (t.balance <= 0) { info.push("토큰이 없어 예약 실행을 건너뜁니다"); cls = " bad"; }
    else if (t.balance < need) { info.push(`다음 예약 실행에 ${need}개 · 남은 ${t.balance}개 - 마이너스로 떨어질 수 있습니다`); cls = cls || " warn"; }
  }
  $("sch-info").textContent = info.join(" · ");
  $("sch-info").className = "msg" + cls;
  $("sch-apply").disabled = dis || !scheduleDirty() || !!problem;
}
function labelDays(days) {
  const d = [...new Set(days || [])].sort();
  if (d.join() === "0,1,2,3,4,5,6") return "매일";
  if (d.join() === "0,1,2,3,4") return "평일";
  if (d.join() === "5,6") return "주말";
  return d.map((i) => DAYS[i]).join("·") || "요일 없음";
}
/** 보낼 값. 옛 판 PC 는 옛 모양, 새 판은 줄 (로그인은 PC 가 붙인다) */
function payloadOf() {
  const base = { enabled: form.sch.enabled, days: [...new Set(form.sch.days)].sort() };
  if (!isV2()) return { ...base, times: [...new Set(form.sch.slots.map((s) => s.at))].sort() };
  return { ...base, slots: sortedForm().map(wellifySlot).map((s) => ({ at: s.at, ...(s.until ? { until: s.until, rest_min: s.rest_min } : {}), ...(s.run ? { run: [...s.run] } : {}) })) };
}
async function applySchedule() {
  const payload = payloadOf();
  try {
    await set(ref(c.db, `${P("settings", c.me.cid, c.pcId)}/schedule`), payload);
  } catch (e) { notify("bad", e.code === "PERMISSION_DENIED" ? "권한이 없습니다" : `저장하지 못했습니다 (${e.code || e})`); return; }
  sent.sch = keyOf.sch();
  await send("set_schedule", payload, "자동 실행");
}
