// AFTER MARKET 껍데기: 로그인, 회사·PC, 사이드바(앱·관리), 테마. 페이지 내용은 각 모듈이 mount/unmount 한다.
import * as data from "./data.js";
import { EDITION, TEST_BUILD, init, onSession, signIn, signOut, signedIn, sessionUid, handoffFailed, getCompany } from "./data.js";
import { CONSOLE_UID } from "./config.js";
import { icon } from "./icons.js";
import { applyTheme, getTheme, isDark, applyAccent, getAccent } from "./theme.js";
import * as rpa from "./rpa.js";
import * as account from "./account.js";
import * as settings from "./settings.js";

// 앱 목록과 관리 페이지. 새 앱은 여기 한 줄과 모듈 파일 하나로 붙는다.
const APPS = [rpa];
const PAGES = [settings, account];

const $ = (id) => document.getElementById(id);
const show = (el, on) => el.classList.toggle("hide", !on);

let me = null;          // { uid, email, cid, role }
let company = null;
let pcId = null;
let current = null;     // 떠 있는 모듈

// --- 테마·강조색: 고른 값은 이 브라우저에만 남는다 ----------------------
function paintThemeButton() { $("theme").innerHTML = isDark() ? `${icon("sun")}밝게` : `${icon("moon")}어둡게`; }
$("logout-btn").innerHTML = `${icon("log-out")}로그아웃<span id="idle-left" role="timer"></span>`;   // idle-left: 자동 로그아웃까지 남은 시간 (10분 미만일 때만, paintIdle)
$("theme").onclick = () => { applyTheme(isDark() ? "light" : "dark"); paintThemeButton(); };
applyTheme(getTheme());
paintThemeButton();
applyAccent(getAccent());

// --- 탭 단위 로그인·미사용 자동 로그아웃 (사용자 2026-11-19, 고객사 보안 검토) ---------------
// 로그인 정보는 탭 저장소에만 둔다 - 탭(브라우저)을 닫으면 로그인이 끝난다. 그 전에는 브라우저에 남아 닫았다 열어도 로그인돼 있었다.
// (저장소를 정하는 것은 아래 init() - data-firebase.js 의 setPersistence)
// 입력(마우스·키보드·터치·휠)이 IDLE_MIN 분 없으면 로그아웃한다. 마지막 입력 시각도 탭 저장소에 둔다 - 새로고침해도 이어서 센다
export const IDLE_MIN = 30;
const IDLE_KEY = "lastActive";
const lastActive = () => { try { return Number(sessionStorage.getItem(IDLE_KEY)) || 0; } catch { return 0; } };
const touch = () => { try { sessionStorage.setItem(IDLE_KEY, String(Date.now())); } catch {} };
const idleOver = () => { const t = lastActive(); return t > 0 && Date.now() - t > IDLE_MIN * 60000; };
let idleNote = null;       // 미사용으로 로그아웃했다 ("user" | "console") - onSession 콜백이 로그인 화면에 까닭을 적는다
let justSignedIn = false;  // 방금 로그인에 성공했다 - onSession 콜백이 입력 시각을 지금으로 적는다. 로그인을 시도하기 전에 적으면
                           // 못 쓰는 열쇠(#t=)를 붙여 새로고침하는 것만으로 시간을 넘긴 로그인이 되살아났다 (검토 2026-11-19)
async function idleCheck() {
  if (!signedIn() || !idleOver()) return;
  idleNote = sessionUid() === CONSOLE_UID ? "console" : "user";
  await signOut();
}
let lastTouch = 0;
function onInput(e) {
  if (!signedIn()) return;
  if (idleOver()) {          // 시간을 넘긴 뒤의 첫 입력은 로그인을 살리지 않고, 누르려던 단추에도 닿지 않는다 ([실행]·[적용] 이 로그아웃보다 먼저 눌리지 않게)
    if (e.cancelable) e.preventDefault();
    e.stopImmediatePropagation();
    idleCheck();
    return;
  }
  const now = Date.now();
  if (now - lastTouch > 5000) { lastTouch = now; touch(); data.touch?.(); paintIdle(); }     // 저장소 쓰기는 5초에 한 번. 알약이 떠 있었다면 바로 지운다
                                                                                            // data.touch: 스탠드얼론은 서버의 미사용 시계도 되돌린다 (1분에 한 번까지, 일반 버전은 없음)
}
// 자동 로그아웃까지 남은 시간을 [로그아웃] 단추에 보인다 (사용자 2026-11-20). 평소에는 그냥 단추이고, 남은 시간이 10분 미만이면
// '로그아웃 9:59' 를 노란색 알약으로, 3분 미만이면 빨간색 알약으로, 1분 미만이면 빨간색이 깜빡인다. 입력하면 다시 30분이라 바로 평소 단추로
// 돌아간다. 0:00 이 되면 그 자리에서 로그아웃한다. 단추는 언제 눌러도 로그아웃이다
export const IDLE_SHOW_SEC = 600, IDLE_BAD_SEC = 180, IDLE_BLINK_SEC = 60;
$("logout-btn").title = `${IDLE_MIN}분 동안 사용하지 않으면 자동으로 로그아웃됩니다. 마우스를 움직이거나 화면을 누르면 다시 ${IDLE_MIN}분이 됩니다.`;
function paintIdle() {
  const btn = document.getElementById("logout-btn"), el = document.getElementById("idle-left");
  if (!btn || !el) return;
  const t = lastActive();
  const left = signedIn() && t > 0 ? Math.ceil((IDLE_MIN * 60000 - (Date.now() - t)) / 1000) : Infinity;
  if (left <= 0) idleCheck();
  const show = left > 0 && left < IDLE_SHOW_SEC;
  el.textContent = show ? `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}` : "";
  btn.classList.toggle("idle-warn", show && left >= IDLE_BAD_SEC);
  btn.classList.toggle("idle-bad", show && left < IDLE_BAD_SEC);
  btn.classList.toggle("idle-blink", show && left < IDLE_BLINK_SEC);
}
setInterval(paintIdle, 1000);
for (const ev of ["pointermove", "wheel", "touchstart"]) window.addEventListener(ev, onInput, { passive: true, capture: true });
for (const ev of ["pointerdown", "keydown", "click", "submit"]) window.addEventListener(ev, onInput, { capture: true });   // 막아야 하는 것 (passive 면 못 막는다)
document.addEventListener("visibilitychange", () => { if (!document.hidden) idleCheck(); });   // 다른 탭을 보다 돌아왔을 때 (숨은 탭은 타이머가 느려진다)
setInterval(idleCheck, 30000);

// --- 로그인 ---------------------------------------------------------
// 로그인 아이디 → 계정 이메일 (공유 계약, data-firebase.js). 화면 시험이 app.js 에서 가져간다. 스탠드얼론은 undefined
export const emailFor = data.emailFor;
// 스탠드얼론은 PC 하나에 업체 하나 - 업체코드 칸이 없다 (아이디·비밀번호만)
const STANDALONE = EDITION === "standalone";
// 시험용 빌드(스탠드얼론 시험 설치 파일)는 맨 위에 띠 - 고객에게 나가지 않게 (일반 버전·진짜 스탠드얼론은 TEST_BUILD = false)
$("test-build").hidden = !(STANDALONE && TEST_BUILD === true);
if (STANDALONE) {
  $("cid").closest("label").hidden = true;
  $("remember").nextSibling.textContent = " 아이디 저장";
}
// '업체코드·아이디 저장' 을 켜고 로그인하면 이 브라우저에 남긴다. 끄고 로그인하면 지운다
try {
  localStorage.removeItem("cid");   // 옛 저장(업체코드만, 항상)은 버린다
  const saved = JSON.parse(localStorage.getItem("login") || "null");
  if (saved) { $("cid").value = saved.cid || ""; $("login-id").value = saved.id || ""; $("remember").checked = true; }
} catch {}
$("login-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const alert = $("login-alert");
  show(alert, false);
  $("login-btn").disabled = true;
  const cid = $("cid").value.trim().replace(/^-$/, "");   // setup.js 관습대로 '-' 도 '회사 없음'
  try {
    justSignedIn = true;                 // 지난 로그인의 입력 시각이 남아 있어도 들어가자마자 미사용으로 로그아웃되지 않게 (onSession)
    await signIn(cid, $("login-id").value.trim(), $("password").value);   // 탭 저장소에만 (init 의 setPersistence)
    $("password").value = "";
    try {
      if ($("remember").checked) localStorage.setItem("login", JSON.stringify({ cid, id: $("login-id").value.trim() }));
      else localStorage.removeItem("login");
    } catch {}
  } catch (e) {
    justSignedIn = false;
    const wrong = ["auth/invalid-credential", "auth/invalid-login-credentials", "auth/wrong-password",
      "auth/user-not-found", "auth/invalid-email", "auth/missing-password"];
    alert.textContent = wrong.includes(e.code) ? (STANDALONE ? "아이디 또는 비밀번호가 일치하지 않습니다." : "업체코드, 아이디 또는 비밀번호가 일치하지 않습니다.")
      : e.code === "auth/user-disabled" ? "사용이 중지된 계정입니다."   // setup.js disable, 또는 remove 로 업체째 막힘
      : e.code === "auth/too-many-requests" ? "로그인 시도가 많아 잠시 잠겼습니다. 1분 뒤 다시 시도하여 주십시오."   // 두 버전 공통 (전엔 code 가 그대로 보였다)
      : STANDALONE && e.code === "auth/network-request-failed" ? "오토파일럿 서버에 연결하지 못했습니다. 오토파일럿이 실행 중인지 확인하여 주십시오."
      : `로그인하지 못했습니다. (${e.code})`;
    show(alert, true);
  } finally {
    $("login-btn").disabled = false;
  }
});
$("logout-btn").addEventListener("click", () => { if (leaveOk()) signOut(); });
// 탭 닫기·새로고침은 브라우저가 묻는다 (글은 브라우저가 정한다)
window.addEventListener("beforeunload", (e) => { if (current?.dirty?.()) { e.preventDefault(); e.returnValue = ""; } });

// 관리 화면 [대시보드 보기] 가 주소 # 뒤에 붙인 1시간짜리 총괄 로그인 열쇠 (2026-10-16) - init() 이 주소창에서 곧바로 지우고 그 열쇠로 로그인한다.
// 이미 다른 계정으로 로그인돼 있어도 바꾼다 (총괄 화면을 보려고 누른 것). 못 쓰면 (1시간 지남) 로그인 화면 안내
const handoff = STANDALONE ? null : new URLSearchParams(location.hash.slice(1)).get("t");   // 스탠드얼론에는 관리 화면 열쇠가 없다
// 이 로그인도 탭 저장소에만 둔다 (2026-11-19 부터 모든 로그인이 그렇다) - 탭을 닫으면 끝나고, 로그인 1시간 뒤에는 스스로 로그아웃한다 (BugBuster I15, 아래 onSession)
let consoleTimer = null;
if (handoff) justSignedIn = true;
await init();
if (handoffFailed()) {
  justSignedIn = false;
  $("login-alert").textContent = "관리 화면 로그인 정보가 만료되었습니다. 관리 화면에서 [대시보드 보기]를 다시 눌러 주십시오."; show($("login-alert"), true);
}

// 로그인·로그아웃·새로고침 복원을 이 콜백 하나가 맡는다. s = null 로그아웃 / {error: "network"} 토큰을 못 받음 /
// {uid, email, cid, role, consoleLeftMs?} 로그인 (토큰을 새로 받은 뒤)
onSession(async (s) => {
  unmount();
  clearTimeout(consoleTimer); consoleTimer = null;
  if (!s) {
    me = null; company = null; pcId = null;
    show($("login"), true); show($("main"), false);
    if (idleNote) {
      $("login-alert").textContent = `${IDLE_MIN}분 동안 사용하지 않아 로그아웃되었습니다. `
        + (idleNote === "console" ? "관리 화면에서 [대시보드 보기]를 다시 눌러 주십시오." : "다시 로그인하여 주십시오.");
      show($("login-alert"), true);
      idleNote = null;
    }
    return;
  }
  if (justSignedIn) { justSignedIn = false; lastTouch = Date.now(); touch(); }
  else if (idleOver()) { idleNote = sessionUid() === CONSOLE_UID ? "console" : "user"; await signOut(); return; }   // 새로고침으로 되살아난 로그인도 시간을 넘겼으면 끝낸다
  else if (!lastActive()) touch();
  if (s.error) {   // 네트워크가 끊겨 토큰을 못 받으면 빈 화면에서 멈췄다 (BugBuster M4)
    show($("login"), true); show($("main"), false);
    $("login-alert").textContent = "네트워크 연결을 확인한 뒤 새로고침하여 주십시오."; show($("login-alert"), true);
    return;
  }
  if (s.uid === CONSOLE_UID) {   // 관리 화면 [대시보드 보기] 로그인 - 로그인 1시간 뒤 로그아웃 (I15)
    // 남은 시간은 서버 시각끼리 잰다 (consoleLeftMs - data 쪽이 방금 받은 토큰의 iat - 로그인 auth_time 으로) - 브라우저 시계가 틀려도 맞게
    const left = s.consoleLeftMs;
    const end = async () => {
      await signOut();
      $("login-alert").textContent = "관리 화면 로그인은 1시간 동안만 사용할 수 있습니다. 관리 화면에서 [대시보드 보기]를 다시 눌러 주십시오.";
      show($("login-alert"), true);
    };
    if (!(left > 0)) { await end(); return; }   // 로그인 시각(auth_time)을 모르면 NaN
    consoleTimer = setTimeout(end, left);
  }
  if (s.role === "agent") {   // 기계 계정은 PC 에이전트 전용. 화면에서 비밀번호를 바꾸면 그 PC 가 죽으니 아예 안 들인다
    await signOut();
    $("login-alert").textContent = "에이전트 계정으로는 화면에 로그인할 수 없습니다."; show($("login-alert"), true);
    return;
  }
  // 총괄은 업체가 없다 - 관리 화면 [대시보드 보기] 가 연 주소의 ?cid= 업체를 본다 (규칙이 총괄에게 모든 업체를 연다). 다른 역할은 주소를 무시
  // 스탠드얼론은 업체가 하나라 ?cid= 띠가 없다
  const want = STANDALONE ? "" : new URLSearchParams(location.search).get("cid") || "";
  const asSuper = s.role === "super" ? (/^[A-Za-z0-9_-]{1,40}$/.test(want) ? want : "") : null;
  // mustChange: 스탠드얼론에서 처음 로그인했거나 관리자가 비밀번호를 다시 정한 계정 - 비밀번호를 바꿀 때까지 계정 화면만 (일반 버전은 늘 false)
  me = { uid: s.uid, email: s.email, cid: asSuper ?? (s.cid || null), role: s.role || null, mustChange: !!s.mustChange };
  $("who").textContent = `${s.email || "관리 화면"} (${me.role === "admin" ? "관리자" : me.role === "super" ? "총괄" : "유저"})`;
  const elsewhere = asSuper === null && want && want !== me.cid;   // 업체 계정이 [대시보드 보기] 주소를 연 것 - 이미 로그인된 브라우저에서 헷갈렸다 (2026-10-16)
  show($("super-bar"), asSuper !== null || elsewhere);
  if (elsewhere) $("super-bar").textContent = `지금 로그인한 계정(${s.email || s.uid})은 다른 업체(${want}) 화면을 볼 수 없어 자기 업체 화면을 보여 드립니다. `
    + "다른 업체를 보려면 로그아웃한 뒤 업체코드를 비우고 총괄 계정으로 로그인하여 주십시오.";
  if (asSuper === "") {
    $("super-bar").textContent = "총괄 계정입니다. 관리 화면의 업체 상세에서 [대시보드 보기]를 눌러 업체 화면을 열어 주십시오.";
    $("company").textContent = ""; $("app-nav").replaceChildren(); $("admin-nav").replaceChildren(); $("page-title").textContent = "";
    show($("pc-pick"), false); show($("login"), false); show($("main"), true);
    return;
  }
  await loadCompany();
  if (asSuper) {
    $("super-bar").textContent = `총괄 계정으로 ${company.name || asSuper} (${asSuper}) 업체 화면을 보고 있습니다. 실행과 설정 변경은 실제로 적용됩니다.`
      + (company.stts === 9 ? " 사용이 중지된 업체입니다." : "");
  } else if (company.stts === 9) {   // 삭제(비활성)된 업체. setup.js remove 가 계정도 막지만 이미 받은 토큰은 1시간 살아서 화면에서도 막는다
    await signOut();
    $("login-alert").textContent = "사용이 중지된 업체입니다."; show($("login-alert"), true);
    return;
  }
  show($("login"), false); show($("main"), true);
  paintNav();
  mount(me.mustChange ? account : APPS[0]);   // 비밀번호를 바꿔야 하는 계정은 계정 화면만 (메뉴 잠금 - paintNav)
});

// --- 회사·PC --------------------------------------------------------
async function loadCompany() {
  company = await getCompany(me.cid);   // 못 읽으면 {}
  $("company").textContent = company.name || "";
  const keys = Object.keys(company.pcs || {});
  // 마지막에 고른 PC 를 기억한다. 없으면 첫 PC (Firebase 는 키 이름순이라 pc_a 가 pc_office 앞에 온다)
  let saved = null;
  try { saved = localStorage.getItem(`pc:${me.cid}`); } catch {}
  pcId = keys.includes(saved) ? saved : (keys[0] || null);
  paintPcPick();
  show($("pc-pick"), keys.length > 1);
}

const CHEV = icon("chevron-down", "chev");
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// PC 고르기: 알약에 지금 PC, 아래 목록엔 나머지 PC. 올리거나(마우스) 누르면(터치·키보드) 펼쳐진다
function paintPcPick() {
  const box = $("pc-pick"), pcs = company?.pcs || {};
  const label = (k) => pcs[k]?.label || k;
  box.classList.remove("open");
  box.innerHTML = `<button type="button" class="selected" aria-haspopup="listbox"><span>${esc(label(pcId))}</span>${CHEV}</button>
    <div class="options" role="listbox">${Object.keys(pcs).filter((k) => k !== pcId)
      .map((k) => `<button type="button" class="option" role="option" data-pc="${esc(k)}">${esc(label(k))}</button>`).join("")}</div>`;
  box.querySelector(".selected").onclick = () => box.classList.toggle("open");
  for (const b of box.querySelectorAll(".option")) {
    b.onclick = () => {
      if (!leaveOk()) { box.classList.remove("open"); b.blur(); return; }
      pcId = b.dataset.pc; b.blur();
      try { localStorage.setItem(`pc:${me.cid}`, pcId); } catch {}
      paintPcPick(); if (current) mount(current);
    };
  }
}
document.addEventListener("click", (e) => { if (!$("pc-pick").contains(e.target)) $("pc-pick").classList.remove("open"); });

// --- 모듈 -----------------------------------------------------------
function ctx() {
  return { edition: EDITION, me, pcId, pcLabel: company?.pcs?.[pcId]?.label || pcId || "",
           pcs: company?.pcs || {},         // 업체 PC 모두 {pcId: {label}} - 프리셋 복사의 받을 PC 목록
           policy: company?.apps || {},   // 업체가 안 쓰는 기능 (총괄이 정한다). 예: apps.rpa.modules.Hold === false
           isAdmin: !!me && (me.role === "admin" || me.role === "super"),
           apps: APPS,     // 환경설정 페이지가 앱마다 설정 화면을 붙인다
           unlock };       // 계정 화면이 비밀번호를 바꾼 뒤 부른다 - mustChange 메뉴 잠금을 푼다 (스탠드얼론)
}

/** 비밀번호를 바꿔 mustChange 가 풀렸다 - 메뉴를 다시 그린다 (지금 보던 계정 화면은 그대로) */
function unlock() {
  if (!me?.mustChange) return;
  me.mustChange = false;
  paintNav();
  for (const a of document.querySelectorAll(".nav a")) if (a.dataset.key === current?.key) a.setAttribute("aria-current", "page");
}

/** 적용 안 한 변경이 있는 페이지(환경설정)를 떠나기 전에 묻는다 - 메뉴·PC 바꾸기·로그아웃 */
function leaveOk() {
  return !current?.dirty?.() || confirm("적용하지 않은 변경 사항이 있습니다. 저장하지 않고 나가시겠습니까?");
}

function navLink(mod) {
  const a = document.createElement("a");
  a.href = "#"; a.dataset.key = mod.key;
  a.innerHTML = `<span class="ic">${icon(mod.icon || "square")}</span>`;   // mod.icon = Lucide 이름
  a.append(mod.label);
  a.onclick = (e) => { e.preventDefault(); if (leaveOk()) mount(mod); };
  return a;
}

function paintNav() {
  if (me?.mustChange) { $("app-nav").replaceChildren(); $("admin-nav").replaceChildren(navLink(account)); return; }   // 비밀번호를 바꿀 때까지 계정 화면만
  $("app-nav").replaceChildren(...APPS.map(navLink));
  $("admin-nav").replaceChildren(...PAGES.filter((p) => (!p.adminOnly || ctx().isAdmin) && (p !== account || me?.email)).map(navLink));   // 관리 화면 열쇠로 들어온 계정은 이메일·비밀번호가 없다 - 계정 페이지 없음   // 유저는 환경설정 링크가 없다
}

function mount(mod) {
  unmount();
  current = mod;
  for (const a of document.querySelectorAll(".nav a")) {
    if (a.dataset.key === mod.key) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  }
  $("page-title").textContent = mod.label;
  show($("pc-pick"), !!mod.perPc && Object.keys(company?.pcs || {}).length > 1);
  mod.mount($("app-root"), ctx());
}

function unmount() {
  if (current) { current.unmount(); current = null; }
  $("app-root").replaceChildren();
}
