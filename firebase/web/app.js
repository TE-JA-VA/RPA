// AFTER MARKET 껍데기: 로그인, 회사·PC, 사이드바(앱·관리), 테마. 페이지 내용은 각 모듈이 mount/unmount 한다.
import { initializeApp } from "https://www.gstatic.com/firebasejs/10.14.1/firebase-app.js";
import {
  getAuth, signInWithEmailAndPassword, signInWithCustomToken, signOut, onAuthStateChanged, connectAuthEmulator,
  setPersistence, browserSessionPersistence, browserLocalPersistence,
} from "https://www.gstatic.com/firebasejs/10.14.1/firebase-auth.js";
import {
  getDatabase, ref, get, connectDatabaseEmulator,
} from "https://www.gstatic.com/firebasejs/10.14.1/firebase-database.js";
import { firebaseConfig } from "./firebase-config.js";
import { icon } from "./icons.js";
import { applyTheme, getTheme, isDark, applyAccent, getAccent } from "./theme.js";
import * as rpa from "./rpa.js";
import * as account from "./account.js";
import * as settings from "./settings.js";

// 앱 목록과 관리 페이지. 새 앱은 여기 한 줄과 모듈 파일 하나로 붙는다.
const APPS = [rpa];
const PAGES = [settings, account];

const app = initializeApp(firebaseConfig);
const auth = getAuth(app);
const db = getDatabase(app);
// 화면 시험용: 에뮬레이터 Hosting(127.0.0.1)에서 ?emu=1 로 열면 에뮬레이터에 붙는다. 실제 주소에서는 무시된다.
if (location.hostname === "127.0.0.1" && new URLSearchParams(location.search).get("emu") === "1") {
  connectAuthEmulator(auth, "http://127.0.0.1:9099", { disableWarnings: true });
  connectDatabaseEmulator(db, "127.0.0.1", 9000);
}

const $ = (id) => document.getElementById(id);
const show = (el, on) => el.classList.toggle("hide", !on);

let me = null;          // { uid, email, cid, role }
let company = null;
let pcId = null;
let current = null;     // 떠 있는 모듈

// --- 테마·강조색: 고른 값은 이 브라우저에만 남는다 ----------------------
function paintThemeButton() { $("theme").innerHTML = isDark() ? `${icon("sun")}밝게` : `${icon("moon")}어둡게`; }
$("logout-btn").innerHTML = `${icon("log-out")}로그아웃`;
$("theme").onclick = () => { applyTheme(isDark() ? "light" : "dark"); paintThemeButton(); };
applyTheme(getTheme());
paintThemeButton();
applyAccent(getAccent());

// --- 로그인 ---------------------------------------------------------
// 공유 계약 (agent.py·setup.js 와 같은 규칙): 아이디에 @ 가 있으면 그대로, 없으면 아이디@회사코드.프로젝트도메인. '_' 는 '-' 로. 업체코드가 비면(총괄) 프로젝트 도메인만
export const emailFor = (cid, id) => id.includes("@") ? id : `${id.replaceAll("_", "-")}@${cid ? cid.replaceAll("_", "-") + "." : ""}${firebaseConfig.authDomain}`;
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
    await signInWithEmailAndPassword(auth, emailFor(cid, $("login-id").value.trim()), $("password").value);
    // 관리 화면 열쇠가 탭 저장소로 바꿨을 수 있다 - 업체 계정은 브라우저에 남긴다. 로그인된 뒤에 바꿔 열쇠 계정이 브라우저에 옮겨지지 않게 (BugBuster I15)
    await setPersistence(auth, browserLocalPersistence).catch(() => {});
    $("password").value = "";
    try {
      if ($("remember").checked) localStorage.setItem("login", JSON.stringify({ cid, id: $("login-id").value.trim() }));
      else localStorage.removeItem("login");
    } catch {}
  } catch (e) {
    const wrong = ["auth/invalid-credential", "auth/invalid-login-credentials", "auth/wrong-password",
      "auth/user-not-found", "auth/invalid-email", "auth/missing-password"];
    alert.textContent = wrong.includes(e.code) ? "업체코드, 아이디 또는 비밀번호가 일치하지 않습니다."
      : e.code === "auth/user-disabled" ? "사용이 중지된 계정입니다."   // setup.js disable, 또는 remove 로 업체째 막힘
      : `로그인하지 못했습니다. (${e.code})`;
    show(alert, true);
  } finally {
    $("login-btn").disabled = false;
  }
});
$("logout-btn").addEventListener("click", () => { if (leaveOk()) signOut(auth); });
// 탭 닫기·새로고침은 브라우저가 묻는다 (글은 브라우저가 정한다)
window.addEventListener("beforeunload", (e) => { if (current?.dirty?.()) { e.preventDefault(); e.returnValue = ""; } });

// 관리 화면 [대시보드 보기] 가 주소 # 뒤에 붙인 1시간짜리 총괄 로그인 열쇠 (2026-10-16) - 주소창에서 곧바로 지우고 그 열쇠로 로그인한다.
// 이미 다른 계정으로 로그인돼 있어도 바꾼다 (총괄 화면을 보려고 누른 것). 못 쓰면 (1시간 지남) 로그인 화면 안내
const handoff = new URLSearchParams(location.hash.slice(1)).get("t");
// 이 로그인은 탭 저장소에만 둔다 - 탭을 닫으면 끝나고, 로그인 1시간 뒤에는 스스로 로그아웃한다 (BugBuster I15, 아래 onAuthStateChanged)
const CONSOLE_UID = "admin-console";   // ops.CONSOLE_UID 와 같다
const CONSOLE_SEC = 3600;
let consoleTimer = null;
if (handoff) {
  history.replaceState(null, "", location.pathname + location.search);
  try {
    await setPersistence(auth, browserSessionPersistence);
    await signInWithCustomToken(auth, handoff);
  } catch {
    await setPersistence(auth, browserLocalPersistence).catch(() => {});   // 열쇠를 못 썼으면 원래대로
    $("login-alert").textContent = "관리 화면 로그인 정보가 만료되었습니다. 관리 화면에서 [대시보드 보기]를 다시 눌러 주십시오."; show($("login-alert"), true);
  }
}

onAuthStateChanged(auth, async (user) => {
  unmount();
  clearTimeout(consoleTimer); consoleTimer = null;
  if (!user) {
    me = null; company = null; pcId = null;
    show($("login"), true); show($("main"), false);
    return;
  }
  let t;
  try { t = await user.getIdTokenResult(true); } catch {   // 네트워크가 끊겨 토큰을 못 받으면 빈 화면에서 멈췄다 (BugBuster M4)
    show($("login"), true); show($("main"), false);
    $("login-alert").textContent = "네트워크 연결을 확인한 뒤 새로고침하여 주십시오."; show($("login-alert"), true);
    return;
  }
  if (user.uid === CONSOLE_UID) {   // 관리 화면 [대시보드 보기] 로그인 - 로그인 1시간 뒤 로그아웃 (I15)
    // 남은 시간은 서버 시각끼리(방금 받은 토큰의 iat - 로그인 auth_time)로 잰다 - 브라우저 시계가 틀려도 맞게
    const left = (CONSOLE_SEC - ((Number(t.claims.iat) || 0) - (Number(t.claims.auth_time) || 0))) * 1000;
    const end = async () => {
      await signOut(auth);
      $("login-alert").textContent = "관리 화면 로그인은 1시간 동안만 사용할 수 있습니다. 관리 화면에서 [대시보드 보기]를 다시 눌러 주십시오.";
      show($("login-alert"), true);
    };
    if (!(left > 0) || !t.claims.auth_time) { await end(); return; }
    consoleTimer = setTimeout(end, left);
  }
  if (t.claims.role === "agent") {   // 기계 계정은 PC 에이전트 전용. 화면에서 비밀번호를 바꾸면 그 PC 가 죽으니 아예 안 들인다
    await signOut(auth);
    $("login-alert").textContent = "에이전트 계정으로는 화면에 로그인할 수 없습니다."; show($("login-alert"), true);
    return;
  }
  // 총괄은 업체가 없다 - 관리 화면 [대시보드 보기] 가 연 주소의 ?cid= 업체를 본다 (규칙이 총괄에게 모든 업체를 연다). 다른 역할은 주소를 무시
  const want = new URLSearchParams(location.search).get("cid") || "";
  const asSuper = t.claims.role === "super" ? (/^[A-Za-z0-9_-]{1,40}$/.test(want) ? want : "") : null;
  me = { uid: user.uid, email: user.email, cid: asSuper ?? (t.claims.cid || null), role: t.claims.role || null };
  $("who").textContent = `${user.email || "관리 화면"} (${me.role === "admin" ? "관리자" : me.role === "super" ? "총괄" : "유저"})`;
  const elsewhere = asSuper === null && want && want !== me.cid;   // 업체 계정이 [대시보드 보기] 주소를 연 것 - 이미 로그인된 브라우저에서 헷갈렸다 (2026-10-16)
  show($("super-bar"), asSuper !== null || elsewhere);
  if (elsewhere) $("super-bar").textContent = `지금 로그인한 계정(${user.email || user.uid})은 다른 업체(${want}) 화면을 볼 수 없어 자기 업체 화면을 보여 드립니다. `
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
    await signOut(auth);
    $("login-alert").textContent = "사용이 중지된 업체입니다."; show($("login-alert"), true);
    return;
  }
  show($("login"), false); show($("main"), true);
  paintNav();
  mount(APPS[0]);
});

// --- 회사·PC --------------------------------------------------------
async function loadCompany() {
  try {
    const snap = await get(ref(db, `meta/companies/${me.cid}`));
    company = snap.val() || {};
  } catch { company = {}; }
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
  return { db, auth, me, pcId, pcLabel: company?.pcs?.[pcId]?.label || pcId || "",
           pcs: company?.pcs || {},         // 업체 PC 모두 {pcId: {label}} - 프리셋 복사의 받을 PC 목록
           policy: company?.apps || {},   // 업체가 안 쓰는 기능 (총괄이 정한다). 예: apps.rpa.modules.Hold === false
           isAdmin: !!me && (me.role === "admin" || me.role === "super"),
           apps: APPS };   // 환경설정 페이지가 앱마다 설정 화면을 붙인다
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
