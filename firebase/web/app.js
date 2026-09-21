// AFTER MARKET 껍데기: 로그인, 회사·PC 고르기, 앱 고르기. 앱 화면은 각 앱 모듈이 그린다.
import { initializeApp } from "https://www.gstatic.com/firebasejs/10.14.1/firebase-app.js";
import {
  getAuth, signInWithEmailAndPassword, signOut, onAuthStateChanged, connectAuthEmulator,
} from "https://www.gstatic.com/firebasejs/10.14.1/firebase-auth.js";
import {
  getDatabase, ref, get, connectDatabaseEmulator,
} from "https://www.gstatic.com/firebasejs/10.14.1/firebase-database.js";
import { firebaseConfig } from "./firebase-config.js";
import * as rpa from "./rpa.js";

// 앱 목록. 새 앱은 여기 한 줄과 모듈 파일 하나로 붙는다.
const APPS = [rpa];

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
let company = null;     // { name, pcs }
let pcId = null;
let current = null;     // 떠 있는 앱 모듈

// --- 로그인 ---------------------------------------------------------
$("login-btn").addEventListener("click", async () => {
  const alert = $("login-alert");
  show(alert, false);
  $("login-btn").disabled = true;
  try {
    await signInWithEmailAndPassword(auth, $("email").value.trim(), $("password").value);
    $("password").value = "";
  } catch (e) {
    // 실서비스는 invalid-credential 하나로 뭉뚱그리고, 에뮬레이터·옛 SDK 는 wrong-password 등으로 나눈다
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
  unmountApp();
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
  mountApp(APPS[0]);
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
  sel.onchange = () => { pcId = sel.value; remountApp(); };
}

// --- 앱 -------------------------------------------------------------
function ctx() {
  return { db, me, pcId, isAdmin: !!me && (me.role === "admin" || me.role === "super") };
}

function paintNav() {
  const nav = $("app-nav");
  nav.replaceChildren(...APPS.map((a) => {
    const b = document.createElement("button");
    b.textContent = a.label;
    b.dataset.app = a.key;
    b.onclick = () => mountApp(a);
    return b;
  }));
  show(nav, APPS.length > 1);
}

function mountApp(mod) {
  unmountApp();
  current = mod;
  for (const b of $("app-nav").querySelectorAll("button")) {
    if (b.dataset.app === mod.key) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current");
  }
  mod.mount($("app-root"), ctx());
}

function unmountApp() {
  if (current) { current.unmount(); current = null; }
  $("app-root").replaceChildren();
}

function remountApp() {
  if (current) mountApp(current);
}
