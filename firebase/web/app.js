// AFTER MARKET 껍데기: 로그인, 회사·PC, 사이드바(앱·관리), 테마. 페이지 내용은 각 모듈이 mount/unmount 한다.
import { initializeApp } from "https://www.gstatic.com/firebasejs/10.14.1/firebase-app.js";
import {
  getAuth, signInWithEmailAndPassword, signOut, onAuthStateChanged, connectAuthEmulator,
} from "https://www.gstatic.com/firebasejs/10.14.1/firebase-auth.js";
import {
  getDatabase, ref, get, connectDatabaseEmulator,
} from "https://www.gstatic.com/firebasejs/10.14.1/firebase-database.js";
import { firebaseConfig } from "./firebase-config.js";
import { applyTheme, getTheme, isDark, applyAccent, getAccent } from "./theme.js";
import * as rpa from "./rpa.js";
import * as account from "./account.js";

// 앱 목록과 관리 페이지. 새 앱은 여기 한 줄과 모듈 파일 하나로 붙는다.
const APPS = [rpa];
const PAGES = [account];

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
function paintThemeButton() { $("theme").textContent = isDark() ? "☀ 밝게" : "☾ 어둡게"; }
$("theme").onclick = () => { applyTheme(isDark() ? "light" : "dark"); paintThemeButton(); };
applyTheme(getTheme());
paintThemeButton();
applyAccent(getAccent());

// --- 로그인 ---------------------------------------------------------
// 공유 계약 (agent.py·setup.js 와 같은 규칙): 아이디에 @ 가 있으면 그대로, 없으면 아이디@회사코드.프로젝트도메인. '_' 는 '-' 로. 업체코드가 비면(총괄) 프로젝트 도메인만
export const emailFor = (cid, id) => id.includes("@") ? id : `${id.replaceAll("_", "-")}@${cid ? cid.replaceAll("_", "-") + "." : ""}rpa-test-f02e0.firebaseapp.com`;
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
    $("password").value = "";
    try {
      if ($("remember").checked) localStorage.setItem("login", JSON.stringify({ cid, id: $("login-id").value.trim() }));
      else localStorage.removeItem("login");
    } catch {}
  } catch (e) {
    const wrong = ["auth/invalid-credential", "auth/invalid-login-credentials", "auth/wrong-password",
      "auth/user-not-found", "auth/invalid-email", "auth/missing-password"];
    alert.textContent = wrong.includes(e.code) ? "업체코드, 아이디 또는 비밀번호가 맞지 않습니다"
      : e.code === "auth/user-disabled" ? "사용이 중지된 계정입니다"   // setup.js disable, 또는 remove 로 업체째 막힘
      : `로그인하지 못했습니다 (${e.code})`;
    show(alert, true);
  } finally {
    $("login-btn").disabled = false;
  }
});
$("logout-btn").addEventListener("click", () => signOut(auth));

onAuthStateChanged(auth, async (user) => {
  unmount();
  if (!user) {
    me = null; company = null; pcId = null;
    show($("login"), true); show($("main"), false);
    return;
  }
  const t = await user.getIdTokenResult(true);
  if (t.claims.role === "agent") {   // 기계 계정은 PC 에이전트 전용. 화면에서 비밀번호를 바꾸면 그 PC 가 죽으니 아예 안 들인다
    await signOut(auth);
    $("login-alert").textContent = "에이전트 계정으로는 화면에 들어올 수 없습니다"; show($("login-alert"), true);
    return;
  }
  me = { uid: user.uid, email: user.email, cid: t.claims.cid || null, role: t.claims.role || null };
  $("who").textContent = `${user.email} (${me.role === "admin" ? "관리자" : me.role === "super" ? "총괄" : "유저"})`;
  await loadCompany();
  if (company.stts === 9) {   // 삭제(비활성)된 업체. setup.js remove 가 계정도 막지만 이미 받은 토큰은 1시간 살아서 화면에서도 막는다
    await signOut(auth);
    $("login-alert").textContent = "사용이 중지된 업체입니다"; show($("login-alert"), true);
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

const CHEV = `<svg class="chev" viewBox="0 0 512 512" aria-hidden="true"><path d="M233.4 406.6c12.5 12.5 32.8 12.5 45.3 0l192-192c12.5-12.5 12.5-32.8 0-45.3s-32.8-12.5-45.3 0L256 338.7 86.6 169.4c-12.5-12.5-32.8-12.5-45.3 0s-12.5 32.8 0 45.3l192 192z"/></svg>`;
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
           policy: company?.apps || {},   // 업체가 안 쓰는 기능 (총괄이 정한다). 예: apps.rpa.modules.Hold === false
           isAdmin: !!me && (me.role === "admin" || me.role === "super") };
}

function navLink(mod) {
  const a = document.createElement("a");
  a.href = "#"; a.dataset.key = mod.key;
  a.innerHTML = `<span class="ic">${mod.icon || "▣"}</span>`;
  a.append(mod.label);
  a.onclick = (e) => { e.preventDefault(); mount(mod); };
  return a;
}

function paintNav() {
  $("app-nav").replaceChildren(...APPS.map(navLink));
  $("admin-nav").replaceChildren(...PAGES.map(navLink));
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
