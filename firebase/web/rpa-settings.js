// RPA 의 환경설정 - 관리 > 환경설정 (settings.js) 이 붙인다. 프리페어 RPA(사이트 수집: 쇼핑몰 프리셋) · 루틴 RPA(실행 모듈) · 자동 실행 (PC 마다).
// 값의 기준은 PC 가 올린 live. 적용 = settings 에 쓰고 명령을 넣는다 - PC 가 반영해 live 로 돌려준다
import { ref, onValue, set } from "https://www.gstatic.com/firebasejs/10.14.1/firebase-database.js";
import { P, MODULES, WELLIFE_MODULES, wellifeOn, LOCKED, NEEDS, DAYS, when, switchText, notify, sendCommand, sendPair, RUN_CHIPS, WELLIFE_RUN_CHIPS, slotNames, slotText, isoDay, schedNote } from "./rpa-common.js";

export const title = "오토파일럿";

const PRESETS = [["평일", [0, 1, 2, 3, 4]], ["매일", [0, 1, 2, 3, 4, 5, 6]], ["주말", [5, 6]]];

const HTML = `
  <div class="msg warn hide" id="changed-bar">다른 곳에서 이 PC의 설정이 변경되었습니다. <button id="reload-form">다시 불러오기</button></div>
  <div class="settings-grid" id="settings-grid">
    <div>
      <h3 class="grp">ACTOR 오토파일럿 (사이트 수집)</h3>
      <div class="msg grp-note">쇼핑몰 사이트에서 주문 엑셀을 다운로드합니다.</div>
      <div class="grp-cards">
      <div class="card hide" id="shop-card">
        <h2>쇼핑몰 프리셋 <span class="muted" id="shop-meta"></span></h2>
        <div id="shop-list"></div>
        <div class="msg" id="shop-info"></div>
        <button class="apply" id="shop-apply" disabled>적용</button>
      </div>
      <div class="msg hide" id="shop-none">이 PC 는 아직 사이트 수집 정보를 보내지 않았습니다 (에이전트를 새 버전으로 업데이트하세요)</div>
      <div class="card hide" id="copy-card">
        <h2>프리셋 복사 <span class="muted" id="copy-meta"></span></h2>
        <div class="msg">이 PC의 프리셋을 같은 업체의 다른 PC로 복사합니다. 아이디·비밀번호는 복사되지 않습니다.</div>
        <div class="lbl">받을 PC</div>
        <div class="seg"><select id="copy-to" aria-label="받을 PC"></select></div>
        <div class="lbl">프리셋 · 받을 번호</div>
        <div id="copy-list"></div>
        <div class="seg"><button id="copy-all">전부 선택</button></div>
        <div class="msg" id="copy-info"></div>
        <button class="apply" id="copy-send" disabled>복사</button>
      </div>
      <div class="card hide" id="par-card">
        <h2>동시 실행 <span class="muted" id="par-meta"></span></h2>
        <div class="msg">쇼핑몰 사이트를 동시에 몇 개까지 열어 엑셀을 다운로드할지 선택합니다. 창은 PC 화면에 나눠 표시합니다.</div>
        <div class="seg"><select id="par-n" aria-label="동시 실행 창 수"></select></div>
        <button class="apply" id="par-apply" disabled>적용</button>
      </div>
      <div class="card hide" id="tog-card">
        <h2>전체 실행 방식 <span class="muted" id="tog-meta"></span></h2>
        <div class="msg">전체 실행에서 ACTOR와 PROCESS를 어떤 순서로 실행할지 선택합니다.</div>
        <div class="seg"><select id="tog-mode" aria-label="전체 실행 방식"></select></div>
        <div class="msg" id="tog-note"></div>
        <button class="apply" id="tog-apply" disabled>적용</button>
      </div>
      </div>
    </div>
    <div>
      <h3 class="grp">자동 실행</h3>
      <div class="msg grp-note">시각마다 사이트 수집과 PROCESS를 함께 선택할 수 있습니다.</div>
      <div class="card" id="sch-card">
        <h2>자동 실행 <span class="muted" id="sch-meta"></span></h2>
        <label class="switch first"><span>활성화</span><input type="checkbox" id="sch-enabled"><span class="knob"></span></label>
        <div id="sch-form">
          <div class="lbl" id="sch-days-lbl">요일</div>
          <div class="seg" id="sch-presets"></div>
          <div class="seg" id="sch-days"></div>
          <div class="lbl">시간 · <span id="sch-count"></span></div>
          <div class="times" id="sch-times"></div>
          <div class="seg"><button id="sch-add">+ 시각</button><button id="sch-add-win" class="hide">+ 반복 시간대</button></div>
          <div class="msg" id="sch-limit"></div>
          <div class="msg warn hide" id="sch-warn">너무 잦은 사이트 수집은 2차인증을 요구할 수도 있습니다.</div>
          <div class="msg good hide" id="sch-full"></div>
          <div class="hide" id="sch-off-box">
            <div class="lbl">휴무일</div>
            <label class="switch first"><span>공휴일 휴무 적용<span class="why">공휴일에는 예약 실행과 반복 실행을 진행하지 않습니다. 수동 실행으로 진행할 수 있습니다.</span></span><input type="checkbox" id="sch-holidays"><span class="knob"></span></label>
            <div class="seg"><input type="date" id="sch-off-date" aria-label="휴무일 선택"><button id="sch-off-add">+ 휴무일 추가</button></div>
            <div class="offs" id="sch-off-list"></div>
            <div class="msg" id="sch-off-note"></div>
          </div>
        </div>
        <div class="msg" id="sch-old" hidden>이 PC를 새 버전으로 업데이트하면 시각별 모듈·반복 실행을 사용할 수 있습니다.</div>
        <div class="msg" id="sch-info"></div>
        <button class="apply" id="sch-apply" disabled>적용</button>
      </div>
      <h3 class="grp">PROCESS 오토파일럿</h3>
      <div class="msg grp-note">다운로드한 주문을 ERPia에서 처리합니다.</div>
      <div class="card" id="mod-card">
        <h2>실행 모듈 <span class="muted" id="mod-meta"></span></h2>
        <div class="msg">전체 실행과 '전체 모듈 실행' 예약은 이 모듈을 실행합니다.</div>
        <div id="mod-list"></div>
        <div class="msg hide" id="mod-modes"></div>
        <button class="apply" id="mod-apply" disabled>적용</button>
      </div>
    </div>
  </div>
  <p class="muted hide" id="no-pc">등록된 PC가 없습니다.</p>`;

let root = null, c = null, stopLive = null, stopLimit = null, stopFeatures = null, stopPar = null, busy = false, live = null, liveLimit;
let stopPeers = [], transferOk = {};   // 다른 PC 의 live.preset_transfer (새 명령을 아는 PC 만 복사 상대로 고른다 - Review Focus 5)
let copyKey = "";   // 복사 카드의 줄·받을 PC 목록을 마지막으로 만든 기준 - 같으면 다시 안 만든다 (heartbeat 가 5초마다 live 를 바꾼다, Task 7 검토)
let parLimit;    // 관리 화면이 허용한 동시 실행 최대 (limits/parallel) - 2 미만이면 '동시 실행' 카드가 없다 (업체는 이 기능을 모른다)
let sent = {};   // 카드마다 마지막으로 [적용] 한 폼 - PC 응답을 기다리는 동안은 '적용 안 한 변경' 이 아니다 (떠날 때 확인)
let form = { modules: {}, shops: {}, parallel: 1, together: "off", sch: { enabled: false, days: [], slots: [], holidays: true, offDates: [] }, copy: { to: "", pick: {} } };
const $ = (id) => root.querySelector(`#${id}`);
const show = (el, on) => el.classList.toggle("hide", !on);

export function mount(el, context) {
  root = el; c = context; busy = false; live = null; liveLimit = undefined; parLimit = undefined; sent = {};
  form.copy = { to: "", pick: {} }; transferOk = {}; copyKey = "";
  root.innerHTML = HTML;
  if (!c.pcId) { show($("settings-grid"), false); show($("no-pc"), true); return; }
  // [적용] 은 저장(set)부터 명령 끝까지 잠근다 - 저장 왕복 사이에 두 번 눌러도 한 번만 (BugBuster K11)
  $("mod-apply").onclick = () => locked(applyModules);
  $("shop-apply").onclick = () => locked(applyShops);
  $("reload-form").onclick = reloadForm;   // (I14)
  $("copy-send").onclick = copyPresets;
  $("copy-all").onclick = () => { for (const p of copyable()) form.copy.pick[p.no] = { ...form.copy.pick[p.no], on: true }; copyKey = ""; paintCopy(); };
  $("copy-to").onchange = (e) => { form.copy.to = e.target.value; paintCopyMeta(); };
  if (copyPeers().length) {
    stopPeers = copyPeers().map((pc) => onValue(ref(c.db, `${P("live", c.me.cid, pc)}/preset_transfer`), (snap) => {
      transferOk[pc] = snap.val() === 1;
      if (root && live) paintCopy();
    }, () => {}));
  }
  $("par-apply").onclick = () => locked(applyParallel);
  $("par-n").onchange = (e) => { form.parallel = Number(e.target.value); paintParMeta(); };
  $("tog-apply").onclick = () => locked(applyTogether);
  $("tog-mode").onchange = (e) => { form.together = e.target.value; paintTogMeta(); };
  $("sch-apply").onclick = () => locked(applySchedule);
  $("sch-enabled").onchange = (e) => { form.sch.enabled = e.target.checked; paintScheduleMeta(); };
  // 휴무일 (판 4 PC - 사용자 2026-10-15): 공휴일 휴무 적용 켬/끔과 업체 휴무일. 지난 날은 못 고른다 (PC 도 저장할 때 뺀다)
  $("sch-off-date").min = isoDay(new Date());          // 달력에서 지난 날을 못 고르게 (검토 2026-10-16)
  $("sch-holidays").onchange = (e) => { form.sch.holidays = e.target.checked; paintScheduleMeta(); };
  $("sch-off-add").onclick = () => {
    const v = $("sch-off-date").value;                  // "YYYY-MM-DD", 안 골랐으면 ""
    // 까닭을 알린다 - 전엔 말없이 넘어갔다 (W10, 2026-11-03)
    const why = !/^\d{4}-\d\d-\d\d$/.test(v) ? "날짜를 선택하여 주십시오." : v < isoDay(new Date()) ? "지난 날짜는 추가할 수 없습니다."
      : form.sch.offDates.includes(v) ? "이미 추가된 휴무일입니다." : "";
    if (why) { notify("warn", why); $("sch-off-date").value = ""; paintScheduleMeta(); return; }   // 못 넣는 날은 비운다 - [적용] 을 막지 않게
    form.sch.offDates = [...form.sch.offDates, v].sort();
    $("sch-off-date").value = "";
    paintOffDates(); paintScheduleMeta();
  };
  $("sch-off-date").oninput = () => paintScheduleMeta();   // 고르기만 하고 [+ 휴무일 추가] 를 안 누르면 [적용] 을 막고 알린다 (W10)
  $("sch-add").onclick = () => { if (form.sch.slots.length >= limitOf()) return; form.sch.slots.push({ at: "09:00", run: null, ...newDays() }); paintTimes(); paintScheduleMeta(); };
  $("sch-add-win").onclick = () => {
    if (form.sch.slots.length >= limitOf()) return;
    form.sch.slots.push({ at: "10:00", until: "11:00", rest_min: 2, run: [], ...newDays() });
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
  // 동시 실행 허용도 같은 방식 (사용자 2026-10-16) - 허용을 거두면 카드가 바로 사라진다
  stopPar = onValue(ref(c.db, `meta/companies/${c.me.cid}/apps/rpa/limits/parallel`), (snap) => {
    const was = root && live ? parDirty() : null;
    parLimit = snap.val();
    if (was === null) return;
    if (!was) resetParallel(); else paintParallel();
  }, () => {});
  // 웰라이프 열림도 같은 방식 - 로그인 뒤 관리 화면에서 바뀌어도 따라간다
  stopFeatures = onValue(ref(c.db, `meta/companies/${c.me.cid}/apps/rpa/features`), (snap) => {
    const was = root && live ? [modulesDirty(), scheduleDirty(), togDirty()] : null;   // 정책을 바꾸기 전 목록으로 편집 중인지 본다
    c.policy = { ...c.policy, rpa: { ...c.policy?.rpa, features: snap.val() || {} } };
    if (!was) return;
    if (!was[0]) resetModules();   // 편집 중인 폼은 건드리지 않는다 (보내는 값은 어차피 규칙대로 거른다)
    if (!was[1]) resetSchedule(); else { paintTimes(); paintScheduleMeta(); }
    if (!was[2]) resetTogether(); else paintTogether();   // 전체 실행 방식 - 정책이 바뀌면 카드를 다시 그린다
  }, () => {});
  stopLive = onValue(ref(c.db, P("live", c.me.cid, c.pcId)), (snap) => {
    const first = live == null;
    // 편집 중이 아닐 때만 폼을 PC 값으로 맞춘다 (적용 뒤 돌아온 값으로 갱신). 편집 중인지는 바뀌기 전 PC 값과 견준다 -
    // 새 값과 견주면 PC 쪽이 바뀌었을 때 손대지 않은 폼도 '편집 중' 으로 보여 옛 값에 머문다
    const was = first ? [] : dirtyList(), before = first ? [] : savedKeys();
    live = snap.val() || {};
    if (first || !was[0]) resetModules();
    if (first || !was[1]) resetShops();
    if (first || !was[3]) resetParallel();
    if (first || !was[4]) resetTogether();
    if (first || !was[2]) resetSchedule();
    // 편집 중인 카드의 PC 값이 바뀌었는데 폼과 다르면 (다른 관리자가 [적용]) 띠로 알린다 - 그대로 [적용] 하면 그 변경을 덮는다 (BugBuster I14)
    if (!first) {
      const now = dirtyList(), after = savedKeys();
      const mine = (i) => { const k = SENT_KEYS[i]; return sent[k] === keyOf[k](); };   // 내가 [적용] 한 폼 - PC 가 다듬어 돌려준 값은 띠 없이
      if (was.some((d, i) => d && now[i] && before[i] !== after[i] && !mine(i))) show($("changed-bar"), true);
      if (!now.some(Boolean)) show($("changed-bar"), false);
    }
    paintAll();
  }, (e) => notify("bad", e.code === "PERMISSION_DENIED" ? "권한이 없습니다." : `읽지 못했습니다. (${e.code || e})`));
}

export function unmount() {
  if (stopLive) { stopLive(); stopLive = null; }
  if (stopLimit) { stopLimit(); stopLimit = null; }
  if (stopFeatures) { stopFeatures(); stopFeatures = null; }
  if (stopPar) { stopPar(); stopPar = null; }
  for (const off of stopPeers) off();
  stopPeers = [];
  root = null; c = null;
}

/** 적용 안 한 변경이 있나 (떠날 때 확인 - app.js) */
export function dirty() {
  return !!root && !!live && ((modulesDirty() && sent.modules !== keyOf.modules())
    || (shopsDirty() && sent.shops !== keyOf.shops()) || (scheduleDirty() && sent.sch !== keyOf.sch())
    || (parDirty() && sent.par !== keyOf.par()) || (togDirty() && sent.tog !== keyOf.tog()));
}
const keyOf = { modules: () => JSON.stringify([form.modules, form.holdReview]), shops: () => JSON.stringify([form.shops, form.xlPw]), sch: () => JSON.stringify(payloadOf()),
  par: () => String(form.parallel), tog: () => form.together };

// 카드 차례: 모듈·프리셋·자동 실행·동시 실행·전체 실행 방식 (I14). PC 값 열쇠에는 사람이 고치는 칸만 (next_run_at 처럼 저절로 바뀌는 것은 뺀다)
const SENT_KEYS = ["modules", "shops", "sch", "par", "tog"];
const dirtyList = () => [modulesDirty(), shopsDirty(), scheduleDirty(), parDirty(), togDirty()];
const savedKeys = () => {
  const s = savedSch();
  return [JSON.stringify([savedModules(), live?.hold_review ?? null]), JSON.stringify(savedShops().map((p) => [p.no, !!p.on, p.excel_pw ?? null])),
    JSON.stringify([!!s.enabled, s.days || [], slotsKey(savedSlots()), s.skip_holidays, savedOff()]), String(savedPar()), savedTog()];
};
/** [다시 불러오기] - 폼을 모두 PC 값으로 (I14) */
function reloadForm() {
  sent = {};
  resetModules(); resetShops(); resetParallel(); resetTogether(); resetSchedule();
  show($("changed-bar"), false);
  paintAll();
}

function paintAll() { paintModuleMeta(); paintShopMeta(); paintCopyMeta(); paintParMeta(); paintTogMeta(); paintScheduleMeta(); }

/** 저장·명령을 넣는 동안 카드 단추를 잠근다. 이미 잠겨 있으면 (두 번 누름) 그냥 돌아간다 (BugBuster K11) */
async function locked(run) {
  if (busy) return;
  busy = true; paintAll();
  try { await run(); }
  finally { busy = false; if (root) { paintAll(); paintModules(); } }   // 기다리는 동안 물류대기·물류관리를 눌러 잠긴 채 다시 그려진 스위치를 푼다
}
// 부르는 쪽이 locked 안에서 (K11). PC 가 거절하면 보낸 표시(sent)를 지운다 - 고친 칸이 다시 '안 보냄' 으로 보여 떠날 때 묻는다 (W2)
// 보낸 화면이 아직 그대로인가 - PC 를 바꾸면 mount 가 새 c·sent 를 만든다. 앞 PC 의 결과가 지금 PC 일처럼 뜨거나 새 화면의 sent 를 지우지 않게 (검토 2026-11-03)
const here = () => { const mine = c; return () => !!root && c === mine; };
const send = (type, args, label, key) => {
  const mineSent = sent;
  return sendCommand(c, type, args, label, here()).then((k) => { if (k === "bad" && key) delete mineSent[key]; });
};

// --- 실행 모듈 ------------------------------------------------------

/** 이 업체가 안 쓰는 모듈 (총괄이 meta/companies/{cid}/apps/rpa/modules 에 false 로 정한다). 화면에서 아예 숨긴다 */
const isWellife = () => wellifeOn(c?.me?.cid, c?.policy);
const modList = () => (isWellife() ? WELLIFE_MODULES : MODULES);
const offByCompany = (k) => c?.policy?.rpa?.modules?.[k] === false;
// PC 가 보고한 모듈만 (옛 버전 PC 는 새 모듈 - 운송장번호 전송 - 을 모른다: 보이면 켜진 것처럼 보이고 [적용] 을 PC 가 거절한다)
const reported = (k) => !live?.modules || k in live.modules;
const ownModules = () => modList().filter(([k]) => reported(k));
const shownModules = () => ownModules().filter(([k]) => !offByCompany(k));

/** 딸린 모듈과 업체 정책을 규칙대로 끈다. 켜는 것은 사람이 직접 한다 (물류관리를 켜도 출력은 꺼진 채로 둘 수 있다) */
function applyNeeds(mods) {
  for (const k of Object.keys(mods)) if (offByCompany(k)) mods[k] = false;
  for (const [k, need] of Object.entries(NEEDS)) if (k in mods && !mods[need]) mods[k] = false;
  return mods;
}
const savedModules = () => live?.modules || {};
// 물류대기 '상품별 재고검토' (사용자 2026-11-03) - PC 가 올린 값이 있을 때만 (옛 에이전트·웰라이프는 없다 - 웰라이프 물류대기는 재고검토가 없다)
const holdFeature = () => !isWellife() && typeof live?.hold_review === "boolean";
function resetModules() {
  form.modules = applyNeeds(Object.fromEntries(ownModules().map(([k]) => [k, LOCKED.has(k) || savedModules()[k] !== false])));
  form.holdReview = live?.hold_review !== false;
  paintModules();
}
// PC 값도 화면 규칙대로 읽는다 - 물류관리 N · 출력 Y (손으로 고친 파일) 이면 숨은 출력 줄 때문에 '바뀜' 이 되지 않게
const savedOn = (k) => !offByCompany(k) && savedModules()[k] !== false && (!NEEDS[k] || savedOn(NEEDS[k]));
function modulesDirty() {
  return ownModules().some(([k]) => !!form.modules[k] !== savedOn(k))
    || (holdFeature() && form.holdReview !== live.hold_review);
}
/** 물류대기를 켰을 때 그 아래 '상품별 재고검토'. 끄면 PC 가 일반 탭 조회 → 전체선택 → 저장만 한다 (Routine HoldSaveOnly) */
function holdReviewRow() {
  const row = document.createElement("label"); row.className = "switch sub";
  const cb = Object.assign(document.createElement("input"), { type: "checkbox", checked: !!form.holdReview, disabled: !c.isAdmin || busy });
  cb.setAttribute("aria-label", "상품별 재고검토");
  cb.onchange = () => { form.holdReview = cb.checked; paintModuleMeta(); };
  row.append(switchText("상품별 재고검토"), cb,
    Object.assign(document.createElement("span"), { className: "knob" }));
  return row;
}
function paintModules() {
  $("mod-list").replaceChildren(...shownModules().flatMap(([k, text], i) => {
    // 딸린 모듈 (운송장 출력) 은 앞 모듈 (물류관리) 을 켰을 때만 그 아래 들여 쓴 줄로 보인다 (사용자 2026-11-03 - 전엔 잠긴 채 보였다)
    if (NEEDS[k] && !form.modules[NEEDS[k]]) return [];
    const row = document.createElement("label"); row.className = "switch" + (i === 0 ? " first" : "") + (NEEDS[k] ? " sub" : "");
    const cb = document.createElement("input");
    cb.type = "checkbox"; cb.checked = !!form.modules[k]; cb.disabled = !c.isAdmin || busy || LOCKED.has(k);
    cb.setAttribute("aria-label", text);
    cb.onchange = () => {
      form.modules[k] = cb.checked;
      // 딸린 줄이 있는 스위치면 다시 그린다 (끄면 딸린 것도 꺼지고 숨고, 다시 켜면 꺼진 채 보인다). 물류대기는 '상품별 재고검토' 를 보이고 숨긴다
      if (Object.values(NEEDS).includes(k) || k === "Hold") { applyNeeds(form.modules); paintModules(); return; }
      paintModuleMeta();
    };
    row.append(switchText(text), cb, Object.assign(document.createElement("span"), { className: "knob" }));
    return k === "Hold" && holdFeature() && form.modules.Hold ? [row, holdReviewRow()] : [row];
  }));
  paintModuleMeta();
}
function paintModuleMeta() {
  const shown = shownModules();
  const on = shown.filter(([k]) => form.modules[k]).length;
  $("mod-meta").textContent = live ? `${on}/${shown.length} 켬` : "";
  // 웰라이프 모드 - 보기만 (시험 기간용, 사용자 2026-10-13). 바꾸기는 PC 설정 파일. 옛 에이전트는 안 올려서 숨는다
  const modes = isWellife() && Array.isArray(live?.modes) ? live.modes : [];
  $("mod-modes").textContent = modes.length ? `모드 (PC 설정 파일에서 바꿈): ${modes.map(([k, v]) => `${k} ${v}`).join(" · ")}` : "";
  $("mod-modes").classList.toggle("warn", modes.some(([, v]) => v !== "실행"));   // 기본이 실행이라 (사용자 2026-11-03) 리허설·1건·오류를 눈에 띄게
  show($("mod-modes"), modes.length > 0);
  $("mod-apply").disabled = !c.isAdmin || busy || !modulesDirty() || on === 0;
}
async function applyModules() {
  const wanted = applyNeeds(Object.fromEntries(ownModules().map(([k]) => [k, !!form.modules[k]])));
  if (!Object.values(wanted).some(Boolean)) { notify("warn", "최소 하나 이상의 모듈을 선택해야 합니다."); return; }
  try {
    await set(ref(c.db, `${P("settings", c.me.cid, c.pcId)}/modules`), wanted);
  } catch (e) { notify("bad", e.code === "PERMISSION_DENIED" ? "권한이 없습니다." : `저장하지 못했습니다. (${e.code || e})`); return; }
  sent.modules = keyOf.modules();
  // 상품별 재고검토는 같은 명령에 실어 보낸다 (새 명령 종류는 RTDB 규칙을 바꿔야 한다). 물류대기를 꺼도 고른 값은 그대로 둔다
  await send("set_modules", holdFeature() ? { ...wanted, HoldSaveOnly: !form.holdReview } : wanted, "실행 모듈", "modules");
}

// --- 쇼핑몰 프리셋 --------------------------------------------------
// PC 의 옵저버가 저장한 프리셋 (에이전트가 이름·코드·단계 수·켬만 올린다). 켜면 다음 프리페어부터 그 쇼핑몰에서 엑셀을 받는다.
// 명령 키는 "PRESET1" - 숫자 키는 Realtime DB 가 배열로 바꿔 읽는다
// ① ~ ㊿ - 유니코드 동그라미 숫자는 세 줄 (1~20, 21~35, 36~50). 프리셋 최대 50개 (rpa_status.circled 와 같은 규칙, 2026-11-03)
const circled = (n) => String.fromCharCode(n <= 20 ? 0x2460 + n - 1 : n <= 35 ? 0x3251 + n - 21 : 0x32B1 + n - 36);
const savedShops = () => (Array.isArray(live?.presets) ? live.presets : []);
const shopReady = (p) => p.steps > 0 && p.has_login;
// 엑셀 비밀번호 (사용자 2026-11-05) - 프리셋마다. 업로드할 엑셀에 쇼핑몰이 건 값이라 로그인 비밀번호가 아니다. PC 가 칸을 올릴 때만 보인다 (옛 에이전트는 없다)
const hasXlPw = (p) => typeof p.excel_pw === "string";
function resetShops() {
  form.shops = Object.fromEntries(savedShops().map((p) => [p.no, !!p.on]));
  form.xlPw = Object.fromEntries(savedShops().map((p) => [p.no, p.excel_pw || ""]));
  paintShops();
}
function shopsDirty() {
  return savedShops().some((p) => !!form.shops?.[p.no] !== !!p.on || (hasXlPw(p) && (form.xlPw?.[p.no] ?? "").trim() !== p.excel_pw));
}
function xlPwRow(p) {
  const row = Object.assign(document.createElement("label"), { className: "xl-pw" });
  const inp = Object.assign(document.createElement("input"), { type: "text", maxLength: 100, autocomplete: "off", value: form.xlPw?.[p.no] ?? "", disabled: !c.isAdmin || busy });
  inp.setAttribute("aria-label", `${circled(p.no)} 엑셀 비밀번호`);
  inp.oninput = () => { form.xlPw[p.no] = inp.value; paintShopMeta(); };
  row.append("엑셀 비밀번호", inp);
  return row;
}
function shopLine(p) {
  const saved = p.saved_at ? ` · ${Number(p.saved_at.slice(5, 7))}/${Number(p.saved_at.slice(8, 10))} 저장` : "";
  return `${circled(p.no)} ${p.name}${p.code ? ` (${p.code})` : ""} · ${p.imap ? "메일 받기" : `${p.steps}단계`}${saved}`;   // imap: 메일 서버에서 받는 프리셋 (2026-10-22)
}
function paintShops() {
  show($("shop-card"), Array.isArray(live?.presets));   // 옛 에이전트·설정이 깨진 PC 는 카드를 숨긴다
  show($("shop-none"), !!live && !Array.isArray(live.presets));
  const list = savedShops();
  // 치는 중인 칸을 live 가 다시 그려 지우지 않게
  if (document.activeElement?.closest?.(".xl-pw") && $("shop-list").contains(document.activeElement)) { paintShopMeta(); paintCopy(); return; }
  $("shop-list").replaceChildren(...list.flatMap((p, i) => {
    const row = document.createElement("label"); row.className = "switch" + (i === 0 ? " first" : "");
    const cb = document.createElement("input");
    const ready = shopReady(p);
    cb.type = "checkbox"; cb.checked = !!form.shops[p.no];
    cb.disabled = !c.isAdmin || busy || (!ready && !cb.checked);   // 켜진 것은 준비가 안 됐어도 끌 수는 있다
    cb.setAttribute("aria-label", `${circled(p.no)} ${p.name}`);
    const why = ready ? "" : p.steps ? "옵저버에서 아이디·비밀번호를 입력한 뒤 저장하여 주십시오." : "옵저버에서 기록한 뒤 저장하여 주십시오.";
    cb.onchange = () => { form.shops[p.no] = cb.checked; paintShopMeta(); };
    const text = switchText(shopLine(p), why), extras = [];
    // 복사·넣어 주기로 받은 칸은 아이디·비밀번호가 비어 있다 (설계 2026-10-19 4.3절). 보관이 있으면 [되돌리기] (restore_preset)
    if (p.steps > 0 && !p.has_login) extras.push(Object.assign(document.createElement("span"), { className: "pill bad", textContent: "아이디·비밀번호 입력 필요" }));
    if (c.isAdmin && p.backup) {
      const b = Object.assign(document.createElement("button"), { type: "button", className: "restore", textContent: "되돌리기", disabled: busy });
      b.onclick = (e) => { e.preventDefault(); restorePreset(p.no); };   // 스위치(label)는 안 건드린다
      extras.push(b);
    }
    if (extras.length) text.firstChild.after(" ", ...extras);
    row.append(text, cb, Object.assign(document.createElement("span"), { className: "knob" }));
    return hasXlPw(p) && p.steps > 0 ? [row, xlPwRow(p)] : [row];
  }));
  $("shop-info").textContent = list.some((p) => p.steps > 0) ? "" : "기록한 프리셋이 없습니다. 이 PC의 '옵저버'에서 기록하여 주십시오.";
  paintShopMeta();
  paintCopy();
}
async function restorePreset(no) {
  if (!confirm(`프리셋 ${no}을(를) 이전 기록으로 되돌리시겠습니까?`)) return;
  await locked(() => send("restore_preset", { nos: [no] }, "프리셋 되돌리기"));
}
function paintShopMeta() {
  const list = savedShops();
  const on = list.filter((p) => form.shops?.[p.no]).length;
  $("shop-meta").textContent = list.length ? `${on}/${list.length} 켬` : "";
  $("shop-apply").disabled = !c.isAdmin || busy || !shopsDirty();
  for (const b of $("shop-list").querySelectorAll(".restore")) b.disabled = busy;   // 줄은 live 가 올 때만 다시 만든다 - 잠금은 여기서
}
async function applyShops() {
  const wanted = Object.fromEntries(savedShops().map((p) => [`PRESET${p.no}`, !!form.shops[p.no]]));
  try {
    await set(ref(c.db, `${P("settings", c.me.cid, c.pcId)}/presets`), wanted);
  } catch (e) { notify("bad", e.code === "PERMISSION_DENIED" ? "권한이 없습니다." : `저장하지 못했습니다. (${e.code || e})`); return; }
  sent.shops = keyOf.shops();
  const xl = savedShops().filter(hasXlPw);      // 옛 에이전트는 모르는 키를 프리셋 번호로 읽어 거절한다
  await send("set_presets", xl.length ? { ...wanted, excel_pw: Object.fromEntries(xl.map((p) => [`PRESET${p.no}`, (form.xlPw[p.no] ?? "").trim()])) } : wanted, "쇼핑몰 프리셋", "shops");
}

// --- 프리셋 복사 (설계 2026-10-19 4.3절) --------------------------------
// 관리자가 이 PC 의 프리셋을 같은 업체의 다른 PC 로. 보낼 PC 에 export_preset, 받을 PC 에 import_preset 을 같은 tid 로 한꺼번에 넣는다.
// 기록만 오간다 (아이디·비밀번호는 안 간다, 인증 휴대폰은 업체 안이라 따라간다 - with_phone). 받을 번호는 프리셋마다 (기본 같은 번호)
const SLOT_MAX = 50;   // ops.importPreset 과 같다
const copyPeers = () => Object.keys(c?.pcs || {}).filter((k) => k !== c.pcId);
const copyShown = () => !!c?.isAdmin && copyPeers().length > 0 && Array.isArray(live?.presets);
const copyable = () => savedShops().filter((p) => p.steps > 0);
const pcLabel = (k) => c.pcs?.[k]?.label || k;
function copyPicked() {
  return copyable().filter((p) => form.copy.pick[p.no]?.on).map((p) => [p.no, form.copy.pick[p.no].slot]);
}
function copyProblem() {
  const picked = copyPicked();
  if (picked.some(([, s]) => !Number.isInteger(s) || s < 1 || s > SLOT_MAX)) return `받을 프리셋 번호는 1~${SLOT_MAX} 사이로 입력하여 주십시오.`;
  if (new Set(picked.map(([, s]) => s)).size !== picked.length) return "받을 프리셋 번호가 중복되어 있습니다.";
  return "";
}
function paintCopy() {
  show($("copy-card"), copyShown());
  if (!copyShown()) return;
  // 복사할 목록·받을 PC·버전이 그대로면 줄을 다시 만들지 않는다 - 치는 중인 받을 번호 칸의 포커스가 빠지지 않게 (heartbeat 마다 live 가 온다)
  const key = JSON.stringify([copyable().map((p) => [p.no, p.name, p.code]), copyPeers(), transferOk]);
  if (key === copyKey) { paintCopyMeta(); return; }
  copyKey = key;
  $("copy-to").replaceChildren(...copyPeers().map((k) => {
    const ok = transferOk[k] === true;
    const o = new Option(ok ? pcLabel(k) : `${pcLabel(k)} (업데이트 필요)`, k);
    o.disabled = !ok;
    return o;
  }));
  if (!transferOk[form.copy.to]) form.copy.to = copyPeers().find((k) => transferOk[k]) || "";
  $("copy-to").value = form.copy.to;
  const list = copyable();
  for (const p of list) form.copy.pick[p.no] ??= { on: false, slot: p.no };
  $("copy-list").replaceChildren(...list.map((p) => {
    const pick = form.copy.pick[p.no];
    const row = document.createElement("label"); row.className = "copy-row";
    const cb = Object.assign(document.createElement("input"), { type: "checkbox", checked: pick.on });
    cb.setAttribute("aria-label", `${circled(p.no)} ${p.name}`);
    cb.onchange = () => { pick.on = cb.checked; paintCopyMeta(); };
    const num = Object.assign(document.createElement("input"), { type: "number", min: 1, max: SLOT_MAX, value: pick.slot, className: "num copy-slot" });
    num.setAttribute("aria-label", "받을 번호");
    num.oninput = () => { pick.slot = num.value === "" ? NaN : Number(num.value); paintCopyMeta(); };
    row.append(cb, Object.assign(document.createElement("span"), { className: "copy-name", textContent: `${circled(p.no)} ${p.name}${p.code ? ` (${p.code})` : ""}` }),
      Object.assign(document.createElement("span"), { className: "muted", textContent: "→" }), num);
    return row;
  }));
  paintCopyMeta();
}
function paintCopyMeta() {
  if (!copyShown()) return;
  const picked = copyPicked(), problem = copyProblem();
  const old = live?.preset_transfer !== 1;   // 이 PC 가 옛 버전이면 보낼 수 없다
  $("copy-info").textContent = problem || (old ? "이 PC를 새 버전으로 업데이트하면 프리셋을 복사할 수 있습니다." : copyable().length ? "" : "복사할 프리셋이 없습니다.");
  $("copy-info").className = "msg" + (problem ? " bad" : "");
  $("copy-meta").textContent = `${picked.length}개 선택`;
  for (const el of $("copy-card").querySelectorAll("input, select, button")) el.disabled = busy;
  for (const o of $("copy-to").options) o.disabled = transferOk[o.value] !== true;
  $("copy-send").disabled = busy || old || !form.copy.to || !picked.length || !!problem;
}
async function copyPresets() {
  const picked = copyPicked(), to = form.copy.to;
  if (!picked.length || copyProblem() || !to || live?.preset_transfer !== 1) return;
  const slots = picked.map(([, s]) => s);
  if (!confirm(`${pcLabel(to)}의 프리셋 ${slots.join(", ")}을(를) 이 PC의 프리셋으로 변경합니다. 기록이 있으면 덮어쓰며 아이디·비밀번호는 복사되지 않습니다. 진행하시겠습니까?`)) return;
  // 전송 id: 영문 소문자·숫자 20자 (ops.newTid·agent.TRANSFER_RE 와 같은 꼴)
  const tid = Array.from(crypto.getRandomValues(new Uint8Array(10)), (b) => b.toString(16).padStart(2, "0")).join("");
  await locked(() => sendPair(c, [[c.pcId, "export_preset", { tid, nos: picked.map(([n]) => n), with_phone: true }],
                                  [to, "import_preset", { tid, slots, from_label: pcLabel(c.pcId) }]], "프리셋 복사", here()));   // 결과 글에 PC 이름 (사용자 2026-10-20)
}

// --- 동시 실행 (사용자 2026-10-16) ---------------------------------
// 관리 화면이 허용한 업체(limits.parallel 2 이상)이고 PC 가 새 에이전트(live.parallel)일 때만 카드가 보인다. 1 ~ 허용 최대 중에서 고른다
const parMax = () => (Number.isInteger(parLimit) && parLimit >= 2 ? Math.min(parLimit, 16) : 0);
const parShown = () => parMax() >= 2 && !!live?.parallel;
const savedPar = () => Math.min(Number.isInteger(live?.parallel?.chosen) ? live.parallel.chosen : 1, parMax() || 1);   // 허용을 줄이면 PC 도 그만큼만 연다
function resetParallel() {
  form.parallel = savedPar();
  paintParallel();
}
function parDirty() {
  return parShown() && form.parallel !== savedPar();
}
function paintParallel() {
  show($("par-card"), parShown());
  if (!parShown()) return;
  $("par-n").replaceChildren(...Array.from({ length: parMax() }, (_, i) =>
    Object.assign(document.createElement("option"), { value: String(i + 1), textContent: i ? `${i + 1}개` : "1개 (하나씩)" })));
  form.parallel = Math.min(form.parallel, parMax());
  $("par-n").value = String(form.parallel);
  paintParMeta();
}
function paintParMeta() {
  if (!parShown()) return;
  $("par-meta").textContent = `${savedPar()}개`;
  $("par-n").disabled = !c.isAdmin || busy;
  $("par-apply").disabled = !c.isAdmin || busy || !parDirty();
}
async function applyParallel() {
  const n = form.parallel;
  try {
    await set(ref(c.db, `${P("settings", c.me.cid, c.pcId)}/parallel`), n);
  } catch (e) { notify("bad", e.code === "PERMISSION_DENIED" ? "권한이 없습니다." : `저장하지 못했습니다. (${e.code || e})`); return; }
  sent.par = keyOf.par();
  await send("set_parallel", { parallel: n }, "동시 실행", "par");
}

// --- 전체 실행 방식 (모든 업체, 사용자 2026-10-20 - 웰라이프만이던 것을 같은 날 넓힘) -----------------
// PC 가 새 에이전트(live.together)일 때만 보인다. 값·이름은 rpa_status.TOGETHER_MODES 와 같다 (PC 가 다른 값은 거절한다)
const TOGETHER = [
  ["off", "순서대로", "사이트 수집(ACTOR)이 끝난 뒤 PROCESS를 실행합니다."],
  ["excel", "함께 (엑셀 업로드)", "PROCESS를 함께 실행하여 사이트별 엑셀을 다운로드하는 대로 업로드합니다. 자동 수집은 사이트 수집이 끝난 뒤 실행합니다."],
  ["excel_import", "함께 (엑셀 업로드·자동 수집)", "PROCESS를 함께 실행하여 엑셀 업로드와 자동 수집을 사이트 수집과 함께 진행합니다."],
];
const togOf = (k) => TOGETHER.find(([v]) => v === k) || TOGETHER[0];
const togShown = () => !!live?.together;
const savedTog = () => togOf(live?.together?.chosen)[0];
function resetTogether() {
  form.together = savedTog();
  paintTogether();
}
function togDirty() {
  return togShown() && form.together !== savedTog();
}
function paintTogether() {
  show($("tog-card"), togShown());
  if (!togShown()) return;
  $("tog-mode").replaceChildren(...TOGETHER.map(([k, label]) =>
    Object.assign(document.createElement("option"), { value: k, textContent: label })));
  $("tog-mode").value = form.together;
  paintTogMeta();
}
function paintTogMeta() {
  if (!togShown()) return;
  $("tog-meta").textContent = togOf(savedTog())[1];
  $("tog-note").textContent = togOf(form.together)[2];
  $("tog-mode").disabled = !c.isAdmin || busy;
  $("tog-apply").disabled = !c.isAdmin || busy || !togDirty();
}
async function applyTogether() {
  const mode = form.together;
  try {
    await set(ref(c.db, `${P("settings", c.me.cid, c.pcId)}/together`), mode);
  } catch (e) { notify("bad", e.code === "PERMISSION_DENIED" ? "권한이 없습니다." : `저장하지 못했습니다. (${e.code || e})`); return; }
  sent.tog = keyOf.tog();
  await send("set_together", { mode }, "전체 실행 방식", "tog");
}

// --- 자동 실행 (2부: 줄마다 전체/고르기, 업체 한도) ----------------------------------------
// 새 판 PC 는 live.schedule.version 2 와 줄(slots)을 올린다. 없으면 옛 판 - 시각만 넣고 옛 모양 {enabled, days, times} 로 보낸다
const isV2 = () => (live?.schedule?.version ?? 0) >= 2;
// 판 3 PC 는 줄마다 요일 (slots[i].days, 사용자 2026-10-08). 옛 판 PC 에는 지금처럼 카드의 공통 요일 하나
const isV3 = () => (live?.schedule?.version ?? 0) >= 3;
const isV4 = () => (live?.schedule?.version ?? 0) >= 4;   // 공휴일·업체 휴무일 쉬기 (2026-10-15)
const isV5 = () => (live?.schedule?.version ?? 0) >= 5;   // 줄마다 운송장 전송 '켠 사이트만' (slots[i].inv_sites, 2026-11-02)
const isV6 = () => (live?.schedule?.version ?? 0) >= 6;   // 1분 단위 시각 (2026-11-03) - 그 전 판 PC 는 5분 단위만 받는다
// 판 7: 줄마다 운송장 전송 방식 (slots[i].inv - 없으면 전체 전송, 사용자 2026-11-09). 판 5·6 은 켬/끔.
// 엑셀 다운로드의 비밀번호·사유는 PC 설정 파일 값이라 여기에 보이지 않는다 (사용자 2026-11-09)
const isV7 = () => (live?.schedule?.version ?? 0) >= 7;
// 순서·이름은 사용자 2026-11-09 그대로 (st.INVOICE_OPTIONS). 2·3 은 사이트 수집에서 끈 사이트를 전송·출력하지 않는다 - 2 는 켬·끔 모두 빼고, 3 은 켠 것만
const INV_OPTIONS = [["", "전체 전송"], ["auto", "자동수집 사이트만 전송"], ["excel", "수집 사이트 엑셀출력"]];
const INV_WHY = { "": "전체 사이트로 조회 후 송장 전송합니다.",
  auto: "사이트 수집을 제외한 사이트만 전송합니다.",
  excel: "사이트 수집으로 설정한 사이트의 마켓업로드용 엑셀을 받고 ERPia에서는 미전송 완료처리합니다. 업로드 프리셋이 있는 사이트만 사이트에 올라갑니다." };
// 판 8: 운송장 전송 줄의 할 일 체크 셋 (사용자 2026-11-09 저녁 - 셋 중 하나로는 '엑셀출력 + 수집 사이트를 뺀 전송요청' 을 못 골랐다).
// 줄 값: inv (없음 = 전체 전송 / auto = 수집 사이트 제외 / none = 전송요청 안 함), xl: true (수집 사이트 엑셀출력). PC 는 st.slot_invoice 로 읽는다
const isV8 = () => (live?.schedule?.version ?? 0) >= 8;
/** 판 8 PC 가 올린 줄의 할 일 {inv?, xl?} - 판 7 의 inv: excel·판 5·6 의 inv_sites: true 는 '전송요청 안 함 + 엑셀출력' (PC 의 st.slot_invoice 와 같다) */
const invSaved = (x) => (x.inv === "excel" || (x.inv === undefined && x.inv_sites === true) ? { inv: "none", xl: true }
  : { ...(x.inv === "auto" || x.inv === "none" ? { inv: x.inv } : {}), ...(x.xl === true ? { xl: true } : {}) });
const offStep = (t) => !isV6() && /^\d\d:\d\d$/.test(t || "") && +t.slice(3) % 5 !== 0;
/** 이 줄이 운송장 전송을 골랐는가 - '켠 사이트만' 은 그 줄에만 (PC 의 normalize_slots 와 같은 규칙) */
const sendsInvoice = (s) => !!s.run?.includes("InvoiceSend");
const OFF_DATES_MAX = 100;                                // rpa_dashboard.OFF_DATES_MAX
const savedOff = () => [...(live?.schedule?.off_dates || [])].sort();
/** '12월 31일 (목)' */
function dayText(iso) {
  const d = new Date(`${iso}T00:00:00`);
  return `${d.getMonth() + 1}월 ${d.getDate()}일 (${DAYS[(d.getDay() + 6) % 7]})`;
}
function paintOffDates() {
  $("sch-off-list").replaceChildren(...form.sch.offDates.map((iso) => {
    const b = document.createElement("button");
    b.textContent = `${dayText(iso)} ✕`;
    b.title = "삭제";
    b.onclick = () => { form.sch.offDates = form.sch.offDates.filter((x) => x !== iso); paintOffDates(); paintScheduleMeta(); };
    return b;
  }));
}
const WEEKDAYS = [0, 1, 2, 3, 4];
const newDays = () => (isV3() ? { days: [...WEEKDAYS] } : {});     // 새 줄은 늘 평일 (사용자 2026-10-08)
const sameDay = (a, b) => !isV3() || a.days.some((d) => b.days.includes(d));
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
  return (Array.isArray(s.slots) ? s.slots : []).filter((x) => x && typeof x.at === "string").map((x) => fitSlot({
    at: x.at, run: Array.isArray(x.run) ? x.run.filter((k) => k !== "Login") : null,
    ...(x.until ? { until: x.until, rest_min: x.rest_min ?? 2 } : {}),
    ...(isV3() ? { days: [...(Array.isArray(x.days) ? x.days : s.days || [])].sort() } : {}),
    // 판 7 PC 도 판을 올리기 전에 저장한 inv_sites 가 남아 있을 수 있다 - PC 는 그것을 'excel' 로 읽는다 (st.slot_invoice)
    ...(isV8() ? invSaved(x) : isV7() ? (x.inv === "excel" || x.inv === "auto" ? { inv: x.inv } : x.inv_sites === true ? { inv: "excel" } : {})
      : isV5() && x.inv_sites === true ? { inv_sites: true } : {}),
  }));
}
/** 줄 단추 - 웰라이프 업체는 물류관리·운송장 대신 SAP 연동·WMS 이관·운송장 전송 (사용자 10-08: ②~⑥ 따로, ⑤⑥ 은 반복도) */
// PC 가 보고한 모듈만 (옛 PC 는 운송장 전송을 몰라 그 줄을 거절한다 - 실행 모듈 카드와 같은 규칙)
const runChipList = () => (isWellife() ? WELLIFE_RUN_CHIPS : RUN_CHIPS).filter(([k]) => k === "Prepare" || reported(k));
/** 줄의 모듈은 이 업체 단추에 있는 것만 (업체 종류가 바뀌기 전에 저장한 줄 - 에이전트가 맞지 않는 모듈을 거절한다). 폼 줄과 보내는 값이 같은 곳을 지난다 */
const fitSlot = (s) => (s.run ? { ...s, run: s.run.filter((k) => runChipList().some(([x]) => x === k)) } : s);
function resetSchedule() {
  const s = savedSch();
  form.sch = { enabled: !!s.enabled, days: [...(s.days || [])], slots: savedSlots(), holidays: s.skip_holidays !== false, offDates: savedOff() };
  $("sch-enabled").checked = form.sch.enabled;
  $("sch-holidays").checked = form.sch.holidays;
  paintDays(); paintTimes(); paintOffDates(); paintScheduleMeta();
}
const runKey = (run) => (run ? [...run].filter((k) => k !== "Login").sort().join() : "*");
const slotKey = (s) => `${s.at}${s.until ? `~${s.until}/${s.rest_min}` : ""}=${runKey(s.run)}${s.days ? `@${[...s.days].sort()}` : ""}`
  + (s.inv_sites && sendsInvoice(s) ? "+inv" : "") + (s.inv && sendsInvoice(s) ? `+inv:${s.inv}` : "") + (s.xl && sendsInvoice(s) ? "+xl" : "");
const slotsKey = (slots) => slots.map(slotKey).sort().join("|");
function scheduleDirty() {
  const s = savedSch();
  return form.sch.enabled !== !!s.enabled
    || (!isV3() && [...form.sch.days].sort().join() !== [...(s.days || [])].sort().join())
    || slotsKey(form.sch.slots) !== slotsKey(savedSlots())
    || (isV4() && (form.sch.holidays !== (s.skip_holidays !== false) || form.sch.offDates.join() !== savedOff().join()));
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
  const inp = document.createElement("input"); inp.type = "time"; inp.step = isV6() ? 60 : 300; inp.value = value; inp.className = "num";
  inp.setAttribute("aria-label", label);
  inp.onchange = () => { apply(inp.value); paintTimes(); paintScheduleMeta(); };
  return inp;
}
/** 줄의 요일 단추 일곱 개 (판 3 PC) */
function dayChips(s) {
  const box = document.createElement("span"); box.className = "seg days-mini";
  DAYS.forEach((d, i) => {
    const b = document.createElement("button"); b.type = "button"; b.textContent = d;
    b.setAttribute("aria-pressed", s.days.includes(i));
    b.disabled = !c.isAdmin || busy;
    b.onclick = () => { s.days = s.days.includes(i) ? s.days.filter((x) => x !== i) : [...s.days, i].sort(); paintTimes(); paintScheduleMeta(); };
    box.append(b);
  });
  return box;
}
/** 줄의 모듈 단추. 업체가 안 쓰는 모듈은 없다. 운송장은 물류관리를 고르기 전엔 잠김 (실행 모듈 카드와 같은 규칙) */
function runChips(s) {
  const box = document.createElement("span"); box.className = "seg chips";
  for (const [k, text] of runChipList()) {
    if (k !== "Prepare" && offByCompany(k)) continue;
    const b = document.createElement("button"); b.type = "button"; b.textContent = text; b.dataset.k = k;
    b.setAttribute("aria-pressed", s.run.includes(k));
    const locked = k === "Output" && !s.run.includes("Logistics");
    b.disabled = !c.isAdmin || busy || locked;
    if (locked) b.title = "물류관리를 켜야 사용할 수 있습니다.";
    b.onclick = () => {
      s.run = s.run.includes(k) ? s.run.filter((x) => x !== k) : [...s.run, k];
      if (!s.run.includes("Logistics")) s.run = s.run.filter((x) => x !== "Output");
      if (!sendsInvoice(s)) { delete s.inv_sites; delete s.inv; delete s.xl; }
      paintTimes(); paintScheduleMeta();
    };
    box.append(b);
  }
  return box;
}
/** 운송장 전송을 고른 줄의 '켠 사이트만' 켬/끔 (사용자 2026-11-02) - 켜면 PC 가 사이트 수집에서 켠 사이트만 매출구분으로 골라 조회·전송 */
function invSitesSwitch(s) {
  const l = document.createElement("label"); l.className = "switch first inv-sites";   // 줄 안이라 위 선 없이
  const text = Object.assign(document.createElement("span"), { textContent: "쇼핑몰 프리셋에서 수집 설정된 사이트만 전송" });   // 판 7 전 PC 는 엑셀 출력을 모르고 [전송요청(S)] 을 누른다 - 글을 바꾸지 말 것 (PR #33 검토)
  text.append(Object.assign(document.createElement("span"), { className: "why",
    textContent: "쇼핑몰 프리셋에서 수집 설정된 사이트만 전송합니다. 비활성화 시 모든 사이트를 전송합니다." }));   // 문구 사용자 2026-11-03, 이름 2026-11-09 ('수집된 사이트만' 이 ACTOR 가 실제로 받은 사이트로 읽혔다)
  const box = Object.assign(document.createElement("input"), { type: "checkbox", checked: !!s.inv_sites });
  box.setAttribute("aria-label", "운송장 전송: 쇼핑몰 프리셋에서 수집 설정된 사이트만");
  box.onchange = () => { if (box.checked) s.inv_sites = true; else delete s.inv_sites; paintScheduleMeta(); };
  l.append(text, box, Object.assign(document.createElement("span"), { className: "knob" }));
  return l;
}
/** 판 7: 운송장 전송을 고른 줄의 방식 셋 중 하나 (사용자 2026-11-09). 고르지 않은 값('')은 전체 전송 - 줄에 inv 를 두지 않는다 */
function invOption(s) {
  const box = document.createElement("div"); box.className = "inv-box";   // 고르기 아래 줄에 설명 (옆에 붙이면 글이 고르기 오른쪽에서 끊겨 줄바꿈됐다, 사용자 2026-11-09)
  const sel = document.createElement("select"); sel.className = "mode inv-opt"; sel.setAttribute("aria-label", "운송장 전송 방식");
  for (const [v, text] of INV_OPTIONS) sel.append(new Option(text, v));
  sel.value = s.inv || "";
  sel.onchange = () => { if (sel.value) s.inv = sel.value; else delete s.inv; paintTimes(); paintScheduleMeta(); };
  box.append(sel, Object.assign(document.createElement("span"), { className: "why", textContent: INV_WHY[s.inv || ""] }));
  return box;
}
/** 판 8: 운송장 전송을 고른 줄의 할 일 체크 셋 (사용자 2026-11-09 저녁). [전송요청] 끔 = inv 'none' (수집 사이트 제외도 함께 버린다),
 *  [수집 사이트 제외] = inv 'auto' (전송요청을 켰을 때만 보인다), [수집 사이트 엑셀출력] = xl true. 전송요청·엑셀출력을 둘 다 끄면 적용을 막는다 (scheduleProblems) */
function invTasks(s) {
  const box = document.createElement("div"); box.className = "inv-box inv-tasks";
  const send = s.inv !== "none";
  const item = (key, name, why, checked, onchange) => {
    const l = document.createElement("label"); l.className = "inv-task";
    const b = Object.assign(document.createElement("input"), { type: "checkbox", checked, className: `inv-${key}` });
    b.setAttribute("aria-label", `운송장 전송: ${name}`);
    b.onchange = () => { onchange(b.checked); paintTimes(); paintScheduleMeta(); };
    l.append(b, Object.assign(document.createElement("span"), { textContent: name }), Object.assign(document.createElement("span"), { className: "why", textContent: why }));
    return l;
  };
  box.append(item("send", "전송요청", "조회된 송장을 [전송요청(S)]로 사이트에 보냅니다.", send, (on) => { if (on) delete s.inv; else s.inv = "none"; }));
  if (send) box.append(item("auto", "수집 사이트 제외", "전송요청에서 사이트 수집으로 등록한 사이트를 뺍니다.", s.inv === "auto",
    (on) => { if (on) s.inv = "auto"; else delete s.inv; }));
  box.append(item("excel", "수집 사이트 엑셀출력", "사이트 수집으로 켠 사이트의 마켓업로드용 엑셀을 받아 사이트에 올리고, ERPia에서는 미전송 완료처리합니다.", !!s.xl,
    (on) => { if (on) s.xl = true; else delete s.xl; }));
  return box;
}
function paintTimes() {
  const over = new Set(sortedForm().slice(limitOf()));      // 시각 순으로 한도를 넘는 줄 (PC 도 이 줄은 안 돌린다)
  $("sch-times").replaceChildren(...form.sch.slots.map((s, i) => {
    // 슬롯마다 같은 틀 (사용자 2026-10-08): ① 시각 · [빼기] ② 요일 ③ 모듈 ④ 쉬는 시간(반복만). 슬롯 사이는 가로선
    const row = document.createElement("div"); row.className = "t" + (over.has(s) ? " over" : "");
    const span = (cls, text) => Object.assign(document.createElement("span"), { className: cls, textContent: text });
    const line = (label, ...kids) => {             // 이름 칸 + 값 칸 - 값이 길면 값 칸 안에서만 줄바꿈 (휴대폰에서도 같은 자리에서 시작)
      const l = document.createElement("div"); l.className = "t-line";
      const v = document.createElement("div"); v.className = "t-val"; v.append(...kids);
      l.append(span("t-lbl", label), v); return l;
    };
    const head = document.createElement("div"); head.className = "t-head";
    head.append(timeInput(s.at, "시각", (v) => { s.at = v; }));
    const win = s.until !== undefined;              // 반복 시간대 줄. 끝 시각을 지워도("") 반복 줄 그대로
    if (win) head.append(span("", "~"), timeInput(s.until, "끝 시각", (v) => { s.until = v; }), span("t-kind", "반복"));
    if (over.has(s)) head.append(span("rest", "미실행 (한도초과)"));
    const del = document.createElement("button"); del.className = "del"; del.textContent = "빼기";
    del.onclick = () => { form.sch.slots.splice(i, 1); paintTimes(); paintScheduleMeta(); };
    head.append(del);
    row.append(head);
    if (isV3()) row.append(line("요일", dayChips(s)));   // 웰라이프 업체도 줄마다 요일
    if (win) {                                     // 모듈 (사이트 수집 포함 - 사용자 2026-10-08) · 쉬는 시간
      const rest = document.createElement("input");
      Object.assign(rest, { type: "number", min: 1, max: 60, value: s.rest_min, className: "num rest-min" });
      rest.setAttribute("aria-label", "쉬는 시간 (분)");
      rest.onchange = () => { s.rest_min = Number(rest.value); paintScheduleMeta(); };
      row.append(line("모듈", runChips(s)), line("쉬는 시간", rest, span("muted", "분 쉬고 다시")));
    } else if (isV2()) {
      const mode = document.createElement("select"); mode.className = "mode"; mode.setAttribute("aria-label", "돌릴 모듈");
      mode.append(new Option("전체 모듈 실행", "all"), new Option("선택 모듈만 실행", "pick"));
      mode.value = s.run ? "pick" : "all";
      mode.onchange = () => { s.run = mode.value === "pick" ? [] : null; delete s.inv_sites; delete s.inv; delete s.xl; paintTimes(); paintScheduleMeta(); };
      row.append(line("모듈", mode, ...(s.run ? [runChips(s)] : [])));
    }
    if (isV8() && sendsInvoice(s)) row.append(line("운송장 전송", invTasks(s)));
    else if (isV7() && sendsInvoice(s)) row.append(line("운송장 전송", invOption(s)));
    else if (isV5() && sendsInvoice(s)) row.append(line("운송장 전송", invSitesSwitch(s)));
    return row;
  }));
}
/** 적용을 막는 까닭 모두 (없으면 []) - 하나 고치고 나서야 다음 까닭이 보이지 않게 한꺼번에 (사용자 2026-10-08). 줄 모양은 꺼도 지킨다 (PC 가 본다), 한도는 켤 때만 - 끄기는 언제나 된다 */
function scheduleProblems() {
  const lim = limitOf(), slots = form.sch.slots, out = [];
  if (form.sch.enabled && slots.length > lim) out.push(lim ? `자동 실행은 최대 ${lim}개까지입니다. 줄을 줄여야 적용할 수 있습니다.` : "자동 실행을 쓰려면 ERPia에 문의해주세요.");
  if (slots.some((s) => !/^\d\d:\d\d$/.test(s.at))) out.push("시간을 확인하여 주십시오.");
  if (slots.some((s) => offStep(s.at) || offStep(s.until))) out.push("이 PC는 5분 단위로만 예약할 수 있습니다. (예: 09:05)");
  if (isV3() && slots.some((s) => !s.days.length)) out.push("요일을 하나 이상 선택하여 주십시오.");
  if (isV8() && slots.some((s) => sendsInvoice(s) && s.inv === "none" && !s.xl)) out.push("운송장 전송 줄에서 전송요청이나 수집 사이트 엑셀출력 중 하나는 켜 주십시오.");
  if (isV4() && form.sch.offDates.length > OFF_DATES_MAX) out.push(`휴무일은 최대 ${OFF_DATES_MAX}개까지 등록할 수 있습니다.`);
  if (isV4() && $("sch-off-date")?.value) out.push("선택한 날짜를 [+ 휴무일 추가]로 추가하여 주십시오.");
  slots.forEach((w, wi) => {
    if (w.until === undefined) return;
    if (!/^\d\d:\d\d$/.test(w.until) || w.until <= w.at) { out.push(`반복 끝 시각은 시작 시각(${w.at})보다 늦어야 합니다.`); return; }
    if (!(Number.isInteger(w.rest_min) && w.rest_min >= 1 && w.rest_min <= 60)) out.push("쉬는 시간은 1~60분 사이로 입력하여 주십시오.");
    if (!w.run.length) out.push("반복 줄에 모듈을 하나 이상 선택하여 주십시오.");
    slots.forEach((x, xi) => {
      if (x === w || !sameDay(w, x)) return;
      if (x.until && xi > wi && x.at < w.until && w.at < x.until) out.push(`반복 시간대가 겹칩니다. (${w.at}~${w.until}, ${x.at}~${x.until})`);
      if (!x.until && w.at <= x.at && x.at < w.until) out.push(`${x.at} 은 반복 시간대(${w.at}~${w.until}) 와 겹칩니다. 반복 시간대와 겹치지 않도록 수정해주십시오.`);
    });
  });
  const plain = slots.filter((s) => s.until === undefined);   // 반복 시간대가 끼면 위의 '겹칩니다' 가 이미 말한다
  if (plain.some((a, i) => plain.slice(i + 1).some((b) => a.at === b.at && sameDay(a, b)))) out.push("같은 시각이 중복되어 있습니다.");
  if (slots.some((s) => s.until === undefined && s.run && !s.run.length)) out.push("'선택 모듈만 실행' 줄에 모듈을 하나 이상 선택하여 주십시오.");   // 반복 줄은 위에서 따로
  if (form.sch.enabled && !isV3() && !form.sch.days.length) out.push("요일을 하나 이상 선택하여 주십시오.");
  if (form.sch.enabled && !slots.length && lim) out.push("시간을 하나 이상 입력하여 주십시오.");   // 슬롯 0개 업체는 초록 'ERPia 문의' 만
  return [...new Set(out)];
}
function paintScheduleMeta() {
  const s = savedSch(), lim = limitOf(), n = form.sch.slots.length;
  const dis = !c.isAdmin || busy;
  $("sch-enabled").disabled = dis;
  for (const el of $("sch-form").querySelectorAll("button, input, select")) if (!el.closest(".chips")) el.disabled = dis;
  $("sch-add").disabled = dis || n >= lim;
  show($("sch-add-win"), isV2()); $("sch-add-win").disabled = dis || n >= lim;
  $("sch-count").textContent = `${n}/${lim} 사용`;
  const problems = scheduleProblems(), problem = problems.length > 0;
  const full = n >= lim ? (lim ? `자동 실행 슬롯은 최대 ${lim}개까지입니다. 추가를 원하시면 ERPia에 문의해주세요.` : "자동 실행을 쓰려면 ERPia에 문의해주세요.") : "";
  // 글은 중요도 순으로 위에서 아래: 막는 까닭(빨강) > 사이트 수집 경고(호박색) > 한도 안내(초록) (사용자 2026-10-08)
  $("sch-limit").replaceChildren(...problems.map((t) => Object.assign(document.createElement("div"), { textContent: t })));   // 한 줄에 하나씩
  $("sch-limit").className = "msg" + (problem ? " bad" : "");
  $("sch-full").textContent = full;
  show($("sch-full"), !!full && !(form.sch.enabled && n > lim));   // 넘친 채 켜 두면 빨간 글이 같은 말을 한다
  // 반복 줄에 사이트 수집 - 쇼핑몰에 자주 로그인하면 2차 인증을 물을 수 있다 (사용자 2026-10-08, 빨강 아래 호박색)
  show($("sch-warn"), form.sch.slots.some((x) => x.until !== undefined && x.run?.includes("Prepare")));
  $("sch-old").hidden = !live || isV2();
  show($("sch-off-box"), isV4());
  $("sch-off-add").disabled = dis || form.sch.offDates.length >= OFF_DATES_MAX;
  const off = [];                                        // PC 가 알려 준 가까운 휴무일·공휴일 표가 끝나 가는지
  if (s.enabled && s.next_off) off.push(`다음 휴무일: ${dayText(s.next_off.date)} ${s.next_off.name}. 해당 일에는 자동 실행을 진행하지 않습니다.`);
  const until = s.holidays_until || "";
  if (until && isoDay(new Date()) >= `${until.slice(0, 4)}-11-01`) off.push(`공휴일 정보가 ${until.slice(0, 4)}년까지 등록되어 있습니다. 새 버전으로 업데이트하여 주십시오.`);
  $("sch-off-note").textContent = off.join(" · ");
  for (const id of ["sch-days-lbl", "sch-presets", "sch-days"]) show($(id), !isV3());
  $("sch-meta").textContent = !live ? "" : !s.enabled ? "비활성화"
    : isV3() ? savedSlots().map((x) => `${labelDays(x.days)} ${slotText(x)}`).join(", ") : `${labelDays(s.days)} ${savedSlots().map(slotText).join(", ")}`;
  // 안내는 한 줄에 하나씩, 색은 문제 줄에만 (2026-10-30 - 예전엔 한 줄로 이어 하나라도 오류면 '다음 실행' 까지 빨갰다). [글, 색]
  const info = [];
  const note = schedNote(s);                             // 설정 파일을 못 읽음(R4)·막혀 기다림(R5)·PC 시간대(R13) - 2026-11-03
  if (note) info.push(note);
  if (s.enabled && s.next_run_at) {
    const wd = (new Date(s.next_run_at).getDay() + 6) % 7;     // 월=0 - 같은 시각 줄이 요일별로 여럿이면 그날 줄
    const names = slotNames((Array.isArray(s.slots) ? s.slots : []).find((x) => x && x.at === s.next_slot && (!Array.isArray(x.days) || x.days.includes(wd))));
    info.push([`다음 ${when(s.next_run_at)}${names ? ` (${names})` : ""}`, ""]);
  }
  if (s.last_launch_at) info.push([`마지막 ${when(s.last_launch_at)}${s.last_launch_by === "auto" ? " (자동)" : ""}`, ""]);
  // PC 의 토큰 거절 글은 아래 토큰 글과 같은 말이고, 충전한 뒤엔 지난 일이다 - 토큰을 아는 PC 면 보이지 않는다
  const t = live?.tokens, knowTokens = typeof t?.balance === "number";
  const tokenErr = (x) => knowTokens && /^(\d\d:\d\d )?토큰이 없습니다/.test(x || "");
  const err = s.last_error && !tokenErr(s.last_error) ? s.last_error : null;
  if (err) info.push([`오류: ${err}`, "bad"]);
  const rep = s.repeat;                                  // 반복 상태 (PC 가 적는다) - 오늘 것만
  if (rep && rep.date === isoDay(new Date())) {
    info.push([`오늘 반복 ${rep.runs || 0}회 · 처리 ${rep.done || 0}회` + (rep.skipped ? ` · 화면 잠김으로 건너뜀 ${rep.skipped}회` : ""), ""]);   // 잠긴 회차는 건너뛰고 잇는다 (사용자 2026-10-08)
    if (rep.stopped) {
      const why = rep.stopped.reason || "반복 실행을 중단하였습니다.";
      info.push([tokenErr(why) && t.balance <= 0 ? "반복 실행을 중단하였습니다." : why, "bad"]);
    }
  }
  if (s.enabled && knowTokens) {                         // 예약 실행은 지켜볼 사람이 없다 - 토큰이 모자라면 여기에도 (토큰 2부)
    const need = t.cost?.next ?? t.cost?.all ?? 0;       // 다음 줄이 '고르기' 면 그 줄의 토큰 (에이전트가 cost.next)
    // PC 가 10분마다 센 값이다 - 충전한 직후엔 옛 값일 수 있어 그렇게 적는다 (W8, 2026-11-03. 실행 직전엔 PC 가 서버에서 다시 센다)
    if (t.balance <= 0) info.push(["토큰이 없어 예약 실행을 건너뜁니다. (PC가 마지막으로 확인한 값 - 충전하면 10분 안에 반영됩니다)", "bad"]);
    else if (t.balance < need) info.push([`다음 예약 실행에 ${need}개 · 남은 토큰 ${t.balance}개 (PC가 마지막으로 확인한 값). 잔여 토큰이 마이너스가 될 수 있습니다.`, "warn"]);
  }
  $("sch-info").replaceChildren(...info.map(([text, cls]) => Object.assign(document.createElement("div"), { textContent: text, className: cls })));
  $("sch-info").className = "msg";
  $("sch-apply").disabled = dis || !scheduleDirty() || problem;
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
  // 판 3 은 공통 요일 = 줄 요일을 모두 합친 것 (옛 판 에이전트가 읽어도 그 요일만 돈다)
  const base = { enabled: form.sch.enabled, days: [...new Set(isV3() ? form.sch.slots.flatMap((s) => s.days) : form.sch.days)].sort(),
    ...(isV4() ? { skip_holidays: form.sch.holidays, off_dates: [...form.sch.offDates] } : {}) };   // 옛 판 PC 는 모르는 값 - 안 보낸다
  if (!isV2()) return { ...base, times: [...new Set(form.sch.slots.map((s) => s.at))].sort() };
  return { ...base, slots: sortedForm().map(fitSlot).map((s) => ({ at: s.at, ...(s.until ? { until: s.until, rest_min: s.rest_min } : {}), ...(s.run ? { run: [...s.run] } : {}), ...(s.days ? { days: [...s.days].sort() } : {}),
    ...(isV8() ? (sendsInvoice(s) ? { ...(s.inv ? { inv: s.inv } : {}), ...(s.xl ? { xl: true } : {}) } : {})
      : isV7() ? (s.inv && sendsInvoice(s) ? { inv: s.inv } : {}) : isV5() && s.inv_sites && sendsInvoice(s) ? { inv_sites: true } : {}) })) };
}
async function applySchedule() {
  const payload = payloadOf();
  try {
    await set(ref(c.db, `${P("settings", c.me.cid, c.pcId)}/schedule`), payload);
  } catch (e) { notify("bad", e.code === "PERMISSION_DENIED" ? "권한이 없습니다." : `저장하지 못했습니다. (${e.code || e})`); return; }
  sent.sch = keyOf.sch();
  await send("set_schedule", payload, "자동 실행", "sch");
}
