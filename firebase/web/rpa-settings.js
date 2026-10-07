// RPA 의 환경설정 - 관리 > 환경설정 (settings.js) 이 붙인다. 실행 모듈 · 쇼핑몰 프리셋 · 자동 실행 (PC 마다).
// 값의 기준은 PC 가 올린 live. 적용 = settings 에 쓰고 명령을 넣는다 - PC 가 반영해 live 로 돌려준다
import { ref, onValue, set } from "https://www.gstatic.com/firebasejs/10.14.1/firebase-database.js";
import { P, MODULES, LOCKED, NEEDS, DAYS, when, dict, josa, switchText, notify, sendCommand } from "./rpa-common.js";

export const title = "RPA";

const PRESETS = [["평일", [0, 1, 2, 3, 4]], ["매일", [0, 1, 2, 3, 4, 5, 6]], ["주말", [5, 6]]];
const MAX_TIMES = 2;      // 하루 실행 시각 개수 - 2부(Task 4)에서 업체 한도로 바뀐다

const HTML = `
  <div class="settings-grid" id="settings-grid">
    <div>
      <div class="card" id="mod-card">
        <h2>실행 모듈 <span class="muted" id="mod-meta"></span></h2>
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
          <div class="lbl">시간</div>
          <div class="times" id="sch-times"></div>
          <div class="seg"><button id="sch-add">+ 시간</button></div>
        </div>
        <div class="msg" id="sch-info"></div>
        <button class="apply" id="sch-apply" disabled>적용</button>
      </div>
    </div>
  </div>
  <p class="muted hide" id="no-pc">등록된 PC 가 없습니다</p>`;

let root = null, c = null, stopLive = null, busy = false, live = null;
let form = { modules: {}, shops: {}, sch: { enabled: false, days: [], times: [] } };
const $ = (id) => root.querySelector(`#${id}`);
const show = (el, on) => el.classList.toggle("hide", !on);

export function mount(el, context) {
  root = el; c = context; busy = false; live = null;
  root.innerHTML = HTML;
  if (!c.pcId) { show($("settings-grid"), false); show($("no-pc"), true); return; }
  $("mod-apply").onclick = applyModules;
  $("shop-apply").onclick = applyShops;
  $("sch-apply").onclick = applySchedule;
  $("sch-enabled").onchange = (e) => { form.sch.enabled = e.target.checked; paintScheduleMeta(); };
  $("sch-add").onclick = () => { if (form.sch.times.length >= MAX_TIMES) return; form.sch.times.push("09:00"); paintTimes(); paintScheduleMeta(); };
  $("sch-presets").replaceChildren(...PRESETS.map(([t, days]) => {
    const b = document.createElement("button"); b.textContent = t;
    b.onclick = () => { form.sch.days = [...days]; paintDays(); paintScheduleMeta(); };
    return b;
  }));
  stopLive = onValue(ref(c.db, P("live", c.me.cid, c.pcId)), (snap) => {
    const first = live == null;
    live = snap.val() || {};
    // 편집 중이 아닐 때만 폼을 PC 값으로 맞춘다 (적용 뒤 돌아온 값으로 갱신)
    if (first || !modulesDirty()) resetModules();
    if (first || !shopsDirty()) resetShops();
    if (first || !scheduleDirty()) resetSchedule();
    paintAll();
  }, (e) => notify("bad", e.code === "PERMISSION_DENIED" ? "권한이 없습니다" : `읽지 못했습니다 (${e.code || e})`));
}

export function unmount() {
  if (stopLive) { stopLive(); stopLive = null; }
  root = null; c = null;
}

/** 적용 안 한 변경이 있나 (떠날 때 확인 - app.js) */
export function dirty() {
  return !!root && !!live && (modulesDirty() || shopsDirty() || scheduleDirty());
}

function paintAll() { paintModuleMeta(); paintShopMeta(); paintScheduleMeta(); }

/** 명령을 넣는 동안 카드 단추를 잠근다 */
async function send(type, args, label) {
  busy = true; paintAll();
  try { await sendCommand(c, type, args, label, () => !!root); }
  finally { busy = false; if (root) paintAll(); }
}

// --- 실행 모듈 ------------------------------------------------------

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
function paintModules() {
  $("mod-list").replaceChildren(...shownModules().map(([k, text], i) => {
    const row = document.createElement("label"); row.className = "switch" + (i === 0 ? " first" : "");
    const cb = document.createElement("input");
    const needOff = NEEDS[k] && !form.modules[NEEDS[k]];   // 앞 모듈이 꺼져 있으면 이 스위치는 잠근다
    cb.type = "checkbox"; cb.checked = !!form.modules[k]; cb.disabled = !c.isAdmin || busy || LOCKED.has(k) || needOff;
    cb.setAttribute("aria-label", text);
    const need = needOff ? dict(MODULES)[NEEDS[k]] : "";
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
  const wanted = applyNeeds(Object.fromEntries(MODULES.map(([k]) => [k, !!form.modules[k]])));
  if (!Object.values(wanted).some(Boolean)) { notify("warn", "최소 한 모듈은 켜야 합니다"); return; }
  try {
    await set(ref(c.db, `${P("settings", c.me.cid, c.pcId)}/modules`), wanted);
  } catch (e) { notify("bad", e.code === "PERMISSION_DENIED" ? "권한이 없습니다" : `저장하지 못했습니다 (${e.code || e})`); return; }
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
  await send("set_presets", wanted, "쇼핑몰 프리셋");
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
  let cls = s.last_error ? " bad" : "";
  const t = live?.tokens;                                // 예약 실행은 지켜볼 사람이 없다 - 토큰이 모자라면 여기에도 (2부)
  if (s.enabled && typeof t?.balance === "number") {
    if (t.balance <= 0) { info.push("토큰이 없어 예약 실행을 건너뜁니다"); cls = " bad"; }
    else if (t.balance < (t.cost?.all ?? 0)) {
      info.push(`다음 예약 실행에 ${t.cost.all}개 · 남은 ${t.balance}개 - 마이너스로 떨어질 수 있습니다`);
      cls = cls || " warn";
    }
  }
  $("sch-info").textContent = info.join(" · ");
  $("sch-info").className = "msg" + cls;
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
  await send("set_schedule", payload, "자동 실행");
}
