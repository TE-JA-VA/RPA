// 관리 > 계정: 비밀번호 바꾸기. 현재 비밀번호로 다시 인증한 뒤 바꾼다 (Firebase 가 요구한다).
// 스탠드얼론: 비밀번호를 바꿔야 하는 계정(mustChange)은 이 화면만 보이고 바꾸면 메뉴가 풀린다. 관리자에게는 아래에 '계정 관리' 카드 (계획 ② Task 4).
import { changePassword, listAccounts, addAccount, updateAccount, removeAccount } from "./data.js";
import { ACCENTS, DEFAULT_ACCENT, applyAccent, getAccent, accentFor } from "./theme.js";
import { toast } from "./toast.js";

export const key = "account";
export const label = "계정";
export const icon = "circle-user";   // Lucide 이름 (icons.js)
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
    <h2>강조색 <span class="muted" id="accent-now"></span></h2>
    <div class="swatches" id="accent-swatches"></div>
    <div class="row" style="justify-content:flex-start;gap:10px;margin-top:10px">
      <input type="color" id="accent-pick" aria-label="강조색 직접 고르기">
      <button id="accent-reset">기본값</button>
    </div>
  </div>
  <div class="card narrow">
    <h2>로그인 정보</h2>
    <div id="acct-email"></div>
    <div class="muted" id="acct-role"></div>
  </div>
`;

// 계정 관리 (스탠드얼론·관리자). 카드·표·단추는 지금 웹의 것 그대로 (.card · .tbl table · .pill · .seg · .lbl · .msg)
const ACCOUNTS_HTML = `
  <div class="card hide" id="acct-card">
    <h2>계정 관리 <span class="muted" id="acct-meta"></span></h2>
    <div class="msg">이 PC의 오토파일럿 화면에 로그인할 계정입니다. 새로 만든 계정과 비밀번호를 다시 정한 계정은 처음 로그인할 때 비밀번호를 바꿉니다.</div>
    <div class="tbl" style="margin-top:12px"><table>
      <thead><tr><th>아이디</th><th>권한</th><th>상태</th><th></th></tr></thead>
      <tbody id="acct-rows"></tbody>
    </table></div>
    <div class="lbl">계정 추가</div>
    <div id="acct-add-row" style="display:flex;gap:6px;flex-wrap:wrap;margin-top:6px">
      <input id="acct-new-id" autocomplete="off" placeholder="아이디" aria-label="새 계정 아이디" style="flex:1 1 140px;width:auto">
      <input id="acct-new-pw" type="password" autocomplete="new-password" placeholder="비밀번호 (8자 이상)" aria-label="새 계정 비밀번호" style="flex:1 1 160px;width:auto">
      <select id="acct-new-role" aria-label="새 계정 권한" style="flex:0 0 auto;width:auto"><option value="viewer">유저</option><option value="admin">관리자</option></select>
      <button id="acct-add" class="primary">추가</button>
    </div>
    <div class="msg">아이디는 영문 소문자·숫자·점(.)·밑줄(_)·빼기(-) 2~32자입니다. 유저는 현황과 기록만 볼 수 있습니다.</div>
  </div>
`;
const ROLE_NAME = { admin: "관리자", super: "총괄", viewer: "유저" };

let root = null, c = null;
let accounts = null, resetFor = null, acctBusy = false, acctSeq = 0;
const $ = (id) => root.querySelector(`#${id}`);
const show = (el, on) => el.classList.toggle("hide", !on);
const manages = () => c?.edition === "standalone" && c?.me?.role === "admin";   // 계정 관리는 스탠드얼론 관리자만

export function mount(el, context) {
  root = el; c = context;
  accounts = null; resetFor = null; acctBusy = false;
  root.innerHTML = HTML + (manages() ? ACCOUNTS_HTML : "");
  $("acct-email").textContent = c.me.email;
  $("acct-role").textContent = ROLE_NAME[c.me.role] || c.me.role || "";
  if (c.me.mustChange) {   // 스탠드얼론: 비밀번호를 바꿀 때까지 이 화면만 (일반 버전은 이 줄이 없다)
    root.querySelector(".card h2").after(Object.assign(document.createElement("div"), { className: "msg warn", id: "pw-must",
      textContent: "처음 로그인했거나 관리자가 비밀번호를 다시 정한 계정입니다. 비밀번호를 바꾼 뒤 다른 메뉴를 사용할 수 있습니다." }));
  }
  $("pw-btn").onclick = change;
  $("pw-new2").addEventListener("keydown", (e) => { if (e.key === "Enter") change(); });
  $("accent-pick").oninput = (e) => setAccent(e.target.value);
  $("accent-reset").onclick = () => setAccent(DEFAULT_ACCENT);
  paintAccent();
  if (manages()) {
    $("acct-add").onclick = add;
    $("acct-new-pw").addEventListener("keydown", (e) => { if (e.key === "Enter") add(); });
    if (!c.me.mustChange) loadAccounts();   // 비밀번호를 바꾸기 전에는 서버도 계정 창구를 막는다 - 바꾸면 그때 읽는다
  }
}

function setAccent(hex) { applyAccent(hex); paintAccent(); }

function paintAccent() {
  const now = getAccent();
  $("accent-now").textContent = now === DEFAULT_ACCENT ? "기본" : now;
  $("accent-pick").value = now;
  $("accent-swatches").replaceChildren(...ACCENTS.map(([name, hex]) => {
    const b = document.createElement("button");
    b.className = "swatch"; b.style.background = accentFor(hex); b.title = name;   // 어두운 모드면 그 모드용 색을 보여 준다
    b.setAttribute("aria-label", `강조색 ${name}`);
    b.setAttribute("aria-pressed", hex === now);
    b.onclick = () => setAccent(hex);
    return b;
  }));
}

export function unmount() { root = null; c = null; acctSeq++; }

async function change() {
  const cur = $("pw-cur").value, nw = $("pw-new").value, nw2 = $("pw-new2").value;
  const msg = $("pw-msg");
  msg.className = "msg";
  if (nw.length < 8) { msg.className = "msg bad"; msg.textContent = "새 비밀번호는 8자 이상이어야 합니다."; return; }
  if (nw !== nw2) { msg.className = "msg bad"; msg.textContent = "다시 입력한 비밀번호가 일치하지 않습니다."; return; }
  if (nw === cur) { msg.className = "msg bad"; msg.textContent = "현재 비밀번호와 같습니다."; return; }
  $("pw-btn").disabled = true;
  msg.textContent = "바꾸는 중";
  const mine = c;
  try {
    await changePassword(cur, nw);
    if (c !== mine) return;
    // 스탠드얼론은 같은 PC 의 다른 탭 세션을 서버가 닫는다 (기기 단위가 아니다)
    msg.textContent = `비밀번호를 바꿨습니다. ${c.edition === "standalone" ? "다른 탭은" : "다른 기기는"} 다시 로그인해야 합니다.`;
    for (const id of ["pw-cur", "pw-new", "pw-new2"]) $(id).value = "";
    if (c.me.mustChange) {        // 메뉴 잠금을 푼다 (스탠드얼론)
      c.unlock?.();
      $("pw-must")?.remove();
      if (manages()) loadAccounts();
    }
  } catch (e) {
    if (c !== mine) return;
    msg.className = "msg bad";
    const wrong = ["auth/invalid-credential", "auth/invalid-login-credentials", "auth/wrong-password"];
    msg.textContent = wrong.includes(e.code) ? "현재 비밀번호가 일치하지 않습니다."
      : e.code === "auth/weak-password" ? "비밀번호가 너무 짧거나 단순합니다."
      : c.edition === "standalone" && e.code === "auth/too-many-requests" ? "시도가 많아 잠시 잠겼습니다. 1분 뒤 다시 시도하여 주십시오."
      : `비밀번호를 변경하지 못했습니다. (${e.code || e})`;
  } finally {
    if (root) $("pw-btn").disabled = false;
  }
}

// --- 계정 관리 (스탠드얼론·관리자) ---------------------------------------------------
async function loadAccounts() {
  const seq = ++acctSeq;
  try {
    const list = await listAccounts();
    if (seq !== acctSeq || !root) return;
    accounts = list;
    paintAccounts();
  } catch (e) {
    if (seq !== acctSeq || !root) return;
    toast("bad", e.message || `계정 목록을 읽지 못했습니다. (${e.code || e})`);
  }
}

/** 계정 창구 하나를 부르고 받은 목록으로 다시 그린다. 서버가 거절하면 그 글을 토스트로 (실패는 false) */
async function act(run, okText) {
  if (acctBusy) return false;
  acctBusy = true; paintAccounts();
  const seq = ++acctSeq;
  try {
    const list = await run();
    if (seq !== acctSeq || !root) return true;
    accounts = list;
    toast("ok", okText);
    return true;
  } catch (e) {
    if (seq === acctSeq && root) toast("bad", e.message || `처리하지 못했습니다. (${e.code || e})`);
    return false;
  } finally {
    acctBusy = false;
    if (root && seq === acctSeq) paintAccounts();
  }
}

function paintAccounts() {
  if (!root || !manages() || !accounts) return;
  show($("acct-card"), true);
  $("acct-meta").textContent = `${accounts.length}개`;
  const rows = [];
  for (const a of accounts) {
    const self = a.id === c.me.uid;
    const tr = document.createElement("tr");
    tr.dataset.id = a.id;
    const idTd = document.createElement("td");
    idTd.textContent = a.id;
    if (self) idTd.append(" ", Object.assign(document.createElement("span"), { className: "muted", textContent: "(지금 로그인)" }));
    const roleTd = Object.assign(document.createElement("td"), { textContent: ROLE_NAME[a.role] || a.role });
    const stTd = document.createElement("td");
    const [cls, text] = a.disabled ? ["bad", "사용 중지"] : a.mustChange ? ["note", "비밀번호 변경 필요"] : ["good", "사용 중"];
    stTd.append(Object.assign(document.createElement("span"), { className: `pill ${cls}`, textContent: text }));
    const btnTd = document.createElement("td");
    if (!self) {   // 자기 줄에는 단추가 없다 - 자기 비밀번호는 위 '비밀번호' 카드에서, 자기 계정은 중지·삭제할 수 없다
      const seg = Object.assign(document.createElement("div"), { className: "seg" });
      seg.style.marginTop = "0"; seg.style.flexWrap = "nowrap";
      seg.append(button("비밀번호 다시 정하기", "reset", () => { resetFor = resetFor === a.id ? null : a.id; paintAccounts(); }),
                 button(a.disabled ? "다시 사용" : "사용 중지", "toggle", () => act(() => updateAccount(a.id, { disabled: !a.disabled }),
                   a.disabled ? `${a.id} 계정을 다시 사용합니다.` : `${a.id} 계정의 사용을 중지했습니다.`)),
                 button("삭제", "remove", () => {
                   if (!confirm(`${a.id} 계정을 삭제하시겠습니까? 삭제한 계정은 되돌릴 수 없습니다.`)) return;
                   if (resetFor === a.id) resetFor = null;
                   act(() => removeAccount(a.id), `${a.id} 계정을 삭제했습니다.`);
                 }));
      btnTd.append(seg);
    }
    for (const td of [idTd, roleTd, stTd, btnTd]) td.style.verticalAlign = "middle";   // 글과 단추의 높이를 맞춘다
    tr.append(idTd, roleTd, stTd, btnTd);
    rows.push(tr);
    if (resetFor === a.id && !self) rows.push(resetRow(a));
  }
  $("acct-rows").replaceChildren(...rows);
  for (const el of $("acct-card").querySelectorAll("input, select, button")) el.disabled = acctBusy;
}

function button(text, act_, onclick) {
  const b = Object.assign(document.createElement("button"), { textContent: text });
  b.dataset.act = act_;
  b.onclick = onclick;
  return b;
}

/** [비밀번호 다시 정하기] 를 누른 줄 아래 - 새 비밀번호 칸과 [정하기]·[취소] */
function resetRow(a) {
  const tr = document.createElement("tr");
  tr.className = "acct-reset";
  const td = document.createElement("td"); td.colSpan = 4;
  const seg = document.createElement("div");      // 계정 추가 줄과 같은 꼴 (.seg 안에서는 .primary 글자색이 덮인다)
  seg.style.cssText = "display:flex;gap:6px;flex-wrap:wrap";
  const pw = Object.assign(document.createElement("input"), { type: "password", autocomplete: "new-password", placeholder: "새 비밀번호 (8자 이상)" });
  pw.setAttribute("aria-label", `${a.id} 계정의 새 비밀번호`);
  pw.style.flex = "1 1 180px"; pw.style.width = "auto";
  const go = async () => {
    if (await act(() => updateAccount(a.id, { password: pw.value }), `${a.id} 계정의 비밀번호를 다시 정했습니다. 다음 로그인에서 비밀번호를 바꿉니다.`)) {
      resetFor = null; if (root) paintAccounts();
    }
  };
  pw.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
  const ok = button("정하기", "reset-ok", go);
  ok.className = "primary";
  seg.append(pw, ok, button("취소", "reset-cancel", () => { resetFor = null; paintAccounts(); }));
  td.append(seg, Object.assign(document.createElement("div"), { className: "msg", textContent: "이 계정의 열린 화면은 로그아웃되고, 다음 로그인에서 비밀번호를 바꿉니다." }));
  tr.append(td);
  setTimeout(() => pw.focus(), 0);
  return tr;
}

async function add() {
  const id = $("acct-new-id").value.trim(), pw = $("acct-new-pw").value, role = $("acct-new-role").value;
  if (await act(() => addAccount(id, pw, role), `${id} 계정을 추가했습니다. 처음 로그인할 때 비밀번호를 바꿉니다.`) && root) {
    $("acct-new-id").value = ""; $("acct-new-pw").value = ""; $("acct-new-role").value = "viewer";
  }
}
