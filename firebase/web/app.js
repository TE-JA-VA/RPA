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
$("login-btn").addEventListener("click", async () => {
  const alert = $("login-alert");
  show(alert, false);
  $("login-btn").disabled = true;
  try {
    await signInWithEmailAndPassword(auth, $("email").value.trim(), $("password").value);
    $("password").value = "";
  } catch (e) {
    const wrong = ["auth/invalid-credential", "auth/invalid-login-credentials", "auth/wrong-password",
      "auth/user-not-found", "auth/invalid-email", "auth/missing-password"];
    alert.textContent = wrong.includes(e.code)
      ? "이메일 또는 비밀번호가 맞지 않습니다" : `로그인하지 못했습니다 (${e.code})`;
    show(alert, true);
  } finally {
    $("login-btn").disabled = false;
  }
});
$("password").addEventListener("keydown", (e) => { if (e.key === "Enter") $("login-btn").click(); });
$("logout-btn").addEventListener("click", () => signOut(auth));

onAuthStateChanged(auth, async (user) => {
  unmount();
  if (!user) {
    me = null; company = null; pcId = null;
    show($("login"), true); show($("main"), false);
    return;
  }
  const t = await user.getIdTokenResult(true);
  me = { uid: user.uid, email: user.email, cid: t.claims.cid || null, role: t.claims.role || null };
  $("who").textContent = `${user.email} (${me.role === "admin" ? "관리자" : me.role === "super" ? "총괄" : "열람"})`;
  show($("login"), false); show($("main"), true);
  await loadCompany();
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
  const pcs = company.pcs || {};
  const keys = Object.keys(pcs);
  const sel = $("pc-pick");
  sel.replaceChildren(...keys.map((k) => {
    const o = document.createElement("option");
    o.value = k; o.textContent = pcs[k]?.label || k;
    return o;
  }));
  show(sel, keys.length > 1);
  pcId = keys[0] || null;
  sel.onchange = () => { pcId = sel.value; if (current) mount(current); };
}

// --- 모듈 -----------------------------------------------------------
function ctx() {
  return { db, auth, me, pcId, pcLabel: company?.pcs?.[pcId]?.label || pcId || "",
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
