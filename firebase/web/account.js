// 관리 > 계정: 비밀번호 바꾸기. 현재 비밀번호로 다시 인증한 뒤 바꾼다 (Firebase 가 요구한다).
import {
  EmailAuthProvider, reauthenticateWithCredential, updatePassword,
} from "https://www.gstatic.com/firebasejs/10.14.1/firebase-auth.js";

export const key = "account";
export const label = "계정";
export const icon = "◎";
export const perPc = false;

const HTML = `
  <div class="card narrow">
    <h2>비밀번호</h2>
    <label>현재 <input id="pw-cur" type="password" autocomplete="current-password"></label>
    <label>새 비밀번호 <input id="pw-new" type="password" autocomplete="new-password" minlength="8"></label>
    <label>다시 입력 <input id="pw-new2" type="password" autocomplete="new-password" minlength="8"></label>
    <button id="pw-btn" class="primary">바꾸기</button>
    <div class="msg" id="pw-msg"></div>
  </div>
  <div class="card narrow">
    <h2>로그인 정보</h2>
    <div id="acct-email"></div>
    <div class="muted" id="acct-role"></div>
  </div>
`;

let root = null, c = null;
const $ = (id) => root.querySelector(`#${id}`);

export function mount(el, context) {
  root = el; c = context;
  root.innerHTML = HTML;
  $("acct-email").textContent = c.me.email;
  $("acct-role").textContent = { admin: "관리자", super: "총괄", viewer: "열람" }[c.me.role] || c.me.role || "";
  $("pw-btn").onclick = change;
  $("pw-new2").addEventListener("keydown", (e) => { if (e.key === "Enter") change(); });
}

export function unmount() { root = null; c = null; }

async function change() {
  const cur = $("pw-cur").value, nw = $("pw-new").value, nw2 = $("pw-new2").value;
  const msg = $("pw-msg");
  msg.className = "msg";
  if (nw.length < 8) { msg.className = "msg bad"; msg.textContent = "새 비밀번호는 8자 이상이어야 합니다"; return; }
  if (nw !== nw2) { msg.className = "msg bad"; msg.textContent = "다시 입력한 비밀번호가 다릅니다"; return; }
  if (nw === cur) { msg.className = "msg bad"; msg.textContent = "지금 비밀번호와 같습니다"; return; }
  $("pw-btn").disabled = true;
  msg.textContent = "바꾸는 중";
  try {
    const user = c.auth.currentUser;
    await reauthenticateWithCredential(user, EmailAuthProvider.credential(user.email, cur));
    await updatePassword(user, nw);
    msg.textContent = "비밀번호를 바꿨습니다. 다른 기기는 다시 로그인해야 합니다.";
    for (const id of ["pw-cur", "pw-new", "pw-new2"]) $(id).value = "";
  } catch (e) {
    msg.className = "msg bad";
    const wrong = ["auth/invalid-credential", "auth/invalid-login-credentials", "auth/wrong-password"];
    msg.textContent = wrong.includes(e.code) ? "현재 비밀번호가 맞지 않습니다"
      : e.code === "auth/weak-password" ? "비밀번호가 너무 짧거나 단순합니다"
      : `바꾸지 못했습니다 (${e.code || e})`;
  } finally {
    if (root) $("pw-btn").disabled = false;
  }
}
