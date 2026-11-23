// 스탠드얼론 환경설정 '휴대폰 인증' 카드 (계획 ④ Task 3) - rpa-settings.js 가 스탠드얼론일 때만 동적 import 한다
// (일반 버전 화면은 이 파일·qr.js 를 받지 않는다). 환경설정 메뉴는 이미 관리자 전용이고, 서버도 관리자만 받는다.
// 카드·표·단추는 지금 웹의 것 그대로 (.card · h2 · .msg · .lbl · .seg · .tbl table · .pill). 따로 뜨는 창 없이 QR 은 카드 안에.
// QR 글(짝 열쇠)은 짝짓기 시작 응답에만 한 번 온다 - 화면을 새로 고치면 다시 [휴대폰 추가] 를 누른다.
import { listPhones, startPhonePair, phonePairState, cancelPhonePair, updatePhone, removePhone } from "./data.js";
import { toast } from "./toast.js";

const HTML = `
  <h3 class="grp">휴대폰 인증</h3>
  <div class="msg grp-note">문자로 받는 쇼핑몰 로그인 인증번호를 휴대폰에서 이 PC로 전달합니다.</div>
  <div class="card" id="phone-card">
    <h2>휴대폰 <span class="muted" id="phone-meta"></span></h2>
    <div class="msg">쇼핑몰 로그인 인증번호(문자)를 사내 와이파이에 연결된 휴대폰에서 이 PC로 전달합니다. 문자 내용은 전달하지 않으며 인증번호 숫자만 전달합니다.</div>
    <div class="tbl hide" id="phone-tbl" style="margin-top:12px"><table style="word-break:keep-all">
      <thead><tr><th>이름 · 담당자</th><th>허용 발신번호</th><th>상태</th><th></th></tr></thead>
      <tbody id="phone-rows"></tbody>
    </table></div>
    <div class="msg hide" id="phone-none">등록된 휴대폰이 없습니다. 휴대폰을 등록하지 않으면 인증번호를 PC의 Edge 창에 직접 입력하여야 합니다.</div>
    <div class="msg warn hide" id="phone-net">이 PC의 네트워크 종류(공용·개인)를 확인하지 못했습니다. 네트워크가 '공용'이면 휴대폰이 연결되지 않습니다. 연결되지 않으면 윈도우 설정 → 네트워크 및 인터넷에서 네트워크 프로필을 '개인'으로 변경하여 주십시오.</div>
    <div class="lbl">휴대폰 추가</div>
    <div class="seg" id="phone-add-row" style="gap:6px">
      <input id="phone-label" autocomplete="off" maxlength="40" placeholder="이름 (예: 김OO 휴대폰)" aria-label="휴대폰 이름" style="flex:1 1 150px;width:auto">
      <input id="phone-owner" autocomplete="off" maxlength="40" placeholder="담당자" aria-label="담당자" style="flex:1 1 90px;width:auto">
      <input id="phone-senders" autocomplete="off" placeholder="허용 발신번호 (쉼표로 구분)" aria-label="허용 발신번호" style="flex:2 1 180px;width:auto">
      <button id="phone-add" class="primary" style="flex:0 0 auto;white-space:nowrap">휴대폰 추가</button>
    </div>
    <div class="hide" id="phone-pair">
      <div class="phone-qr">
        <span id="phone-qr-box"></span>
        <div class="msg">
          <div id="phone-pair-text"></div>
          <div class="warn" style="margin-top:8px">QR 코드를 촬영하여 다른 사람에게 전달하지 마십시오.</div>
          <div class="seg"><button id="phone-cancel">취소</button></div>
        </div>
      </div>
    </div>
    <div class="msg" id="phone-msg" role="status" style="white-space:pre-line"></div>
  </div>`;

let root = null, nodes = [], data = null, busy = false, seq = 0, editFor = null;
let pairing = null;        // {expiresAt (브라우저 시각 ms), label} - 짝짓기 중
let tickTimer = null, pollTimer = null, listTimer = null;
const $ = (id) => root.querySelector(`#${id}`);
const show = (el, on) => el.classList.toggle("hide", !on);

/** col = 환경설정의 왼쪽 열 - 그 끝에 '휴대폰 인증' 묶음을 붙인다 */
export function mount(col) {
  unmount();
  const tpl = document.createElement("template");
  tpl.innerHTML = HTML;
  nodes = [...tpl.content.childNodes];
  col.append(...nodes);                      // 감싸지 않고 열의 형제로 (h3.grp ~ h3.grp 간격 규칙이 그대로 걸린다)
  root = col;
  $("phone-add").onclick = start;
  $("phone-cancel").onclick = () => cancel(true);
  for (const id of ["phone-label", "phone-owner", "phone-senders"]) $(id).addEventListener("keydown", (e) => { if (e.key === "Enter") start(); });
  load();
  listTimer = setInterval(() => { if (!busy && !editFor) load(); }, 30000);   // '연결됨 · N분 전' 을 새로 (미사용 시계는 되돌리지 않는다)
  // 새로 고침 등으로 QR 을 잃은 짝짓기가 남아 있으면 취소한다 (QR 은 다시 받을 수 없다 - 화면을 떠나면 취소)
  phonePairState().then((s) => { if (root && !pairing && s?.state === "waiting") cancelPhonePair().catch(() => {}); }, () => {});
}

export function unmount() {
  clearInterval(tickTimer); clearInterval(pollTimer); clearInterval(listTimer);
  tickTimer = pollTimer = listTimer = null;
  if (pairing) cancelPhonePair().catch(() => {});            // 화면을 떠나면 짝짓기를 취소한다
  pairing = null; editFor = null; busy = false; seq++;
  for (const n of nodes) n.remove();
  nodes = []; root = null; data = null;
}

async function load() {
  const my = ++seq;
  try {
    const v = await listPhones();
    if (my !== seq || !root) return;
    data = v;
    paint();
  } catch (e) {
    if (my === seq && root) say("bad", e.message || `휴대폰 목록을 읽지 못했습니다. (${e.code || e})`);
  }
}

function say(kind, text) {
  if (!root) return;
  $("phone-msg").className = `msg${kind ? " " + kind : ""}`;
  $("phone-msg").textContent = text || "";
}

function ago(ms) {
  const sec = Math.max(0, Math.round((Date.now() - ms) / 1000));
  if (sec < 60) return "방금";
  if (sec < 3600) return `${Math.floor(sec / 60)}분 전`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}시간 전`;
  const d = new Date(ms);
  return `${d.getMonth() + 1}월 ${d.getDate()}일`;
}

function paint() {
  if (!root || !data) return;
  const phones = data.phones || [], gate = data.gate || {};
  $("phone-meta").textContent = (phones.length ? `${phones.length}대` : "등록된 휴대폰 없음")
    + ` · 포트 ${gate.port || 8782} ${gate.open ? "열림" : "닫힘"}`;
  show($("phone-tbl"), phones.length > 0);
  show($("phone-none"), phones.length === 0);
  show($("phone-net"), !!gate.open && gate.network === "unknown");   // 서버가 PowerShell 없이 소켓으로 주소를 찾았다 (local_phone.Gate.hosts)
  const rows = [];
  for (const p of phones) {
    const tr = document.createElement("tr");
    tr.dataset.id = p.id;
    // 왼쪽 열은 좁다 - 담당자는 이름 아래 작은 글로 (칸 넷). 이름은 한 줄 (단추 칸에 밀려 한 글자씩 세로로 깨지지 않게)
    const name = document.createElement("td");
    name.append(Object.assign(document.createElement("div"), { textContent: p.label || p.id }));
    if (p.owner) name.append(Object.assign(document.createElement("div"), { className: "muted", textContent: p.owner, style: "font-size:12px" }));
    // 짝지은 기기 · OS (짝지을 때 앱이 보낸 값) - QR 을 가로챈 짝짓기를 나중에도 알아보게. 기기 이름은 길 수 있어 줄을 넘긴다
    const dev = [p.device, p.os].filter(Boolean).join(" · ");
    if (dev) {
      const d = Object.assign(document.createElement("div"), { className: "muted", textContent: dev });
      d.dataset.col = "device";
      d.style.cssText = "font-size:12px;white-space:normal;overflow-wrap:anywhere";
      name.append(d);
    }
    name.style.whiteSpace = "nowrap";
    const cells = [name, Object.assign(document.createElement("td"), { textContent: (p.senders || []).length ? p.senders.join(", ") : "제한 없음" })];
    const st = document.createElement("td");
    st.style.whiteSpace = "nowrap";
    const [cls, text] = p.stale ? ["bad", "다시 연결 필요"] : p.last_seen ? ["good", `연결됨 · ${ago(p.last_seen)}`] : ["note", "연결 기록 없음"];
    st.append(Object.assign(document.createElement("span"), { className: `pill ${cls}`, textContent: text }));
    const act = document.createElement("td");
    const seg = Object.assign(document.createElement("div"), { className: "seg" });
    seg.style.marginTop = "0"; seg.style.justifyContent = "flex-end";   // 칸이 좁으면 [수정]·[삭제] 를 위아래로 (표 밖으로 잘리지 않게)
    seg.append(button("수정", "edit", () => { editFor = editFor === p.id ? null : p.id; paint(); }),
               button("삭제", "remove", () => remove(p)));
    act.append(seg);
    for (const td of [...cells, st, act]) td.style.verticalAlign = "middle";
    tr.append(...cells, st, act);
    rows.push(tr);
    if (editFor === p.id) rows.push(editRow(p));
  }
  $("phone-rows").replaceChildren(...rows);
  for (const el of root.querySelectorAll("#phone-card input, #phone-card button")) el.disabled = busy;
  if (pairing) { $("phone-add").disabled = true; $("phone-cancel").disabled = busy; }
}

function button(text, act, onclick) {
  const b = document.createElement("button");
  b.textContent = text; b.dataset.act = act; b.onclick = onclick;
  return b;
}

function editRow(p) {
  const tr = document.createElement("tr");
  tr.className = "phone-edit";
  const td = document.createElement("td");
  td.colSpan = 4;
  const row = Object.assign(document.createElement("div"), { className: "seg" });
  row.style.gap = "6px";
  const inp = (v, ph, flex) => Object.assign(document.createElement("input"), { value: v, placeholder: ph, autocomplete: "off", ariaLabel: ph,
    style: `flex:${flex};width:auto` });
  const label = inp(p.label || "", "이름", "1 1 140px"), owner = inp(p.owner || "", "담당자", "1 1 90px"),
    senders = inp((p.senders || []).join(", "), "허용 발신번호 (쉼표로 구분, 비우면 제한 없음)", "2 1 180px");
  row.append(label, owner, senders,
    button("저장", "edit-ok", () => act(() => updatePhone(p.id, { label: label.value, owner: owner.value, senders: senders.value }),
      () => { editFor = null; toast("ok", `휴대폰 '${label.value.trim()}'의 정보를 저장하였습니다.`); })),
    button("취소", "edit-cancel", () => { editFor = null; paint(); }));
  td.append(row);
  tr.append(td);
  return tr;
}

/** 서버 창구 하나를 부르고 받은 목록으로 다시 그린다. 거절되면 그 글을 토스트로 */
async function act(run, done) {
  if (busy) return;
  busy = true; paint();
  const my = ++seq;
  try {
    const v = await run();
    if (my !== seq || !root) return;
    if (v?.phones) data = { phones: v.phones, gate: v.gate || data?.gate };
    done?.(v);
  } catch (e) {
    if (my === seq && root) toast("bad", e.message || `처리하지 못했습니다. (${e.code || e})`);
  } finally {
    busy = false;
    if (root && my === seq) paint();
  }
}

function remove(p) {
  const name = p.label || p.id;
  if (!confirm(`휴대폰 '${name}'을(를) 삭제하시겠습니까? 삭제하면 이 휴대폰은 인증번호를 전달할 수 없습니다.`)) return;
  if (editFor === p.id) editFor = null;
  act(() => removePhone(p.id), (v) => {
    if (!(v.phones || []).length && !v.gate?.open) say("", "휴대폰을 삭제하였습니다. 등록된 휴대폰이 없어 휴대폰 포트를 닫았습니다.");
    else say("", `휴대폰 '${name}'을(를) 삭제하였습니다.`);
  });
}

// --- 짝짓기 ---------------------------------------------------------------------------------
async function start() {
  if (busy || pairing) return;
  const label = $("phone-label").value.trim();
  if (!label) { say("bad", "휴대폰 이름을 입력하여 주십시오. (예: 김OO 휴대폰)"); $("phone-label").focus(); return; }
  busy = true; say("", ""); paint();
  const my = ++seq;
  try {
    const v = await startPhonePair({ label, owner: $("phone-owner").value.trim(), senders: $("phone-senders").value });
    if (my !== seq || !root) { cancelPhonePair().catch(() => {}); return; }
    const { qrSvg } = await import("./qr.js");
    if (my !== seq || !root) { cancelPhonePair().catch(() => {}); return; }
    pairing = { expiresAt: Date.now() + (v.expires_in || 300) * 1000, label };
    $("phone-qr-box").replaceChildren(qrSvg(v.qr));
    show($("phone-pair"), true);
    paintLeft();
    tickTimer = setInterval(paintLeft, 1000);
    pollTimer = setInterval(poll, 2000);
    load();
  } catch (e) {
    if (my === seq && root) say("bad", e.message || `휴대폰을 추가하지 못했습니다. (${e.code || e})`);
  } finally {
    busy = false;
    if (root) paint();
  }
}

function paintLeft() {
  if (!root || !pairing) return;
  const left = Math.max(0, Math.round((pairing.expiresAt - Date.now()) / 1000));
  $("phone-pair-text").textContent = "휴대폰의 '오토파일럿 컨트롤타워' 앱에서 QR 코드를 스캔하여 주십시오. QR 코드는 5분 동안 한 번만 사용할 수 있습니다. "
    + `(남은 시간 ${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")})`;
}

function endPair() {
  clearInterval(tickTimer); clearInterval(pollTimer);
  tickTimer = pollTimer = null;
  pairing = null;
  if (!root) return;
  $("phone-qr-box").replaceChildren();       // 짝 열쇠가 든 QR 을 화면에 남기지 않는다
  show($("phone-pair"), false);
  paint();
}

async function poll() {
  if (!pairing) return;
  let s;
  try { s = await phonePairState(); } catch { return; }
  if (!root || !pairing) return;
  if (s?.state === "waiting") {
    if (Number.isFinite(s.left_sec)) pairing.expiresAt = Date.now() + s.left_sec * 1000;   // 서버의 남은 시간에 맞춘다
    return;
  }
  endPair();
  if (s?.state === "paired") {
    const ph = s.phone || {};
    say("good", `휴대폰 '${ph.label || ""}'이(가) 연결되었습니다. (${ph.device || ""} · ${ph.os || ""})`);
    for (const id of ["phone-label", "phone-owner", "phone-senders"]) $(id).value = "";
  } else if (s?.state === "expired") {
    say("warn", "QR 코드의 사용 시간이 지났습니다. [휴대폰 추가]를 다시 눌러 주십시오.");
  }
  load();
}

async function cancel(fromButton) {
  if (!pairing) return;
  endPair();
  try { await cancelPhonePair(); } catch (e) { if (fromButton && root) toast("bad", e.message || "짝짓기를 취소하지 못했습니다."); }
  if (root) { say("", ""); load(); }
}
