// RPA 화면 둘이 같이 쓰는 것 - 현황(rpa.js)·환경설정(rpa-settings.js). 경로, 모듈 표, 글 도우미, 명령 보내기.
import { ref, onValue, push } from "https://www.gstatic.com/firebasejs/10.14.1/firebase-database.js";
import { COMMAND_TTL_SEC } from "./firebase-config.js";
import { toast } from "./toast.js";

export const P = (kind, cid, pcId) => `apps/rpa/${kind}/${cid}/${pcId}`;
// 에이전트·Firestore 에서 온 값은 innerHTML 에 넣기 전에 반드시 씌운다 (app.js 와 같은 구현)
export const esc = (s) => String(s).replace(/[&<>"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch]));
export const MODULES = [
  ["Login", "로그인"], ["Sales", "주문매핑 매출처리"], ["Hold", "물류대기 관리"],
  ["Logistics", "물류관리"], ["Output", "운송장 출력 / 엑셀 생성"],
];
// 웰라이프 업체 모듈 (설계 2026-10-07-wellife-gate) - PC 의 Wellife 섹션 키, wellife.MODULES 와 같다
export const WELLIFE_MODULES = [
  ["Login", "로그인"], ["Sales", "주문매핑 매출처리"], ["Hold", "물류대기 관리"],
  ["Sap", "웰라이프 SAP 연동관리"], ["Wms", "웰라이프 WMS 이관관리"],
];
/** 웰라이프 업체인가 - 업체코드에 wellife (대소문자 무관) 또는 관리 화면에서 연 업체. 에이전트·관리 화면과 같은 규칙 */
export const wellifeOn = (cid, policy) => String(cid ?? "").toLowerCase().includes("wellife") || policy?.rpa?.features?.wellife === true;
export const LOCKED =new Set(["Login"]);   // 항상 켬. 관리자도 못 끈다 (에이전트도 파일에 Y 로 고정)
// 앞 모듈이 꺼지면 따라 꺼지는 모듈. 운송장 출력은 물류관리가 만든 화면에서 돌기 때문에 혼자 돌 수 없다 (에이전트도 못 박는다)
export const NEEDS = { Output: "Logistics" };
export const DAYS = ["월", "화", "수", "목", "금", "토", "일"];
export const hhmm = (iso) => iso ? iso.slice(11, 16) : "";
export const when = (iso) => {
  if (!iso) return "";
  const d = new Date(iso);
  return `${d.getMonth() + 1}월 ${d.getDate()}일 (${DAYS[(d.getDay() + 6) % 7]}) ${hhmm(iso)}`;
};
export const isoDay = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
export const dict = (pairs) => Object.fromEntries(pairs);
// 받침이 있으면 '을', 없으면 '를' (한글이 아니면 '를')
export const josa = (w) => {
  const code = (w || "").charCodeAt((w || "").length - 1) - 0xac00;
  return code >= 0 && code < 11172 && code % 28 ? "을" : "를";
};
/** 스위치 줄의 글자. why 가 있으면 그 아래 작은 글씨로 - 잠긴 까닭 (마우스 글(title)은 휴대폰에 안 보인다 - 2026-10-02) */
export function switchText(text, why) {
  const s = Object.assign(document.createElement("span"), { textContent: text });
  if (why) s.append(Object.assign(document.createElement("small"), { className: "why", textContent: why }));
  return s;
}
/** 명령·설정 안내는 토스트 하나를 이어서 고쳐 쓴다 (보냄 → 진행 중 → 결과) */
export const notify = (kind, text, ttlMs) => toast(kind, text, ttlMs, "act");

/** 명령을 넣고 PC 가 끝낼 때까지 토스트로 알린다. 실패도 토스트 - 던지지 않는다.
 *  alive() 가 거짓이면 (화면을 떠났다) 결과 안내를 하지 않는다 */
export async function sendCommand(c, type, args, label, alive = () => true) {
  notify("info", `${label} 명령을 보냈습니다. PC 응답을 기다립니다.`);
  try {
    const now = Math.floor(Date.now() / 1000);
    const node = await push(ref(c.db, P("commands", c.me.cid, c.pcId)), {
      type, args: args ?? null, by: c.me.uid, created_at: now, expires_at: now + COMMAND_TTL_SEC, state: "queued",
    });
    await watchCommand(c, node.key, label, alive);
  } catch (e) {
    notify("bad", e.code === "PERMISSION_DENIED" ? "권한이 없습니다" : `보내지 못했습니다 (${e.code || e})`);
  }
}

function watchCommand(c, cmdKey, label, alive) {
  return new Promise((resolve) => {
    const timer = setTimeout(() => { off(); if (alive()) notify("bad", "PC 가 응답하지 않습니다"); resolve(); }, 60000);
    const off = onValue(ref(c.db, `${P("commands", c.me.cid, c.pcId)}/${cmdKey}`), (snap) => {
      const v = snap.val();
      if (!v || !alive()) return;
      if (v.state === "running") notify("info", `${label} 진행 중`);
      if (["done", "failed", "expired"].includes(v.state)) {
        clearTimeout(timer); off();
        notify(v.state === "done" ? "ok" : "bad", v.result || v.state);
        resolve();
      }
    });
  });
}

// 예약 줄 (2부). 단추 글은 PC 의 rpa_dashboard.SLOT_NAMES 와 같은 말
export const RUN_CHIPS = [["Prepare", "쇼핑몰 받기"], ["Sales", "주문매핑"], ["Hold", "물류대기"], ["Logistics", "물류관리"], ["Output", "운송장"]];
export const RUN_NAMES = dict(RUN_CHIPS);
/** '고르기' 줄의 모듈 이름 (로그인은 늘 붙으니 안 적는다). '전체' 거나 줄이 없으면 "" */
export const slotNames = (slot) => (slot?.run ? slot.run.filter((k) => k !== "Login").map((k) => RUN_NAMES[k] || k).join("·") : "");
/** 줄 한 칸 글: '10:00' / '11:00 물류관리' / '11:00~12:00 반복 물류관리' (PC 의 slot_text 와 같다) */
export const slotText = (s) => (s.until ? `${s.at}~${s.until} 반복` : s.at) + (s.run ? ` ${slotNames(s)}` : "");

// 반복 시간대 (3부)
/** 도는 줄 (시각 순, 업체 한도로 자른 것 - PC 의 rpa_dashboard.active_slots 와 같은 규칙) */
export function activeSlots(sch) {
  const all = (Array.isArray(sch?.slots) ? sch.slots : []).filter((s) => s && typeof s.at === "string").sort((a, b) => a.at.localeCompare(b.at));
  const lim = sch?.policy?.limit;
  return Number.isInteger(lim) && lim >= 0 ? all.slice(0, lim) : all;
}
/** 지금 열려 있는 반복 시간대 (그날 요일 + 시작 ≤ 지금 < 끝). 이 브라우저 시각으로 본다 */
export function openWindow(sch, now = new Date()) {
  if (!sch?.enabled || !(sch.days || []).includes((now.getDay() + 6) % 7)) return null;
  const hm = `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;
  return activeSlots(sch).find((s) => s.until && s.at <= hm && hm < s.until) || null;
}
/** 오늘 그 시간대의 반복 상태 (PC 가 schedule.repeat 에 적는다). 다른 날·다른 시간대 것이면 null */
export function repeatOf(sch, win, now = new Date()) {
  const r = sch?.repeat;
  return r && win && r.date === isoDay(now) && r.at === win.at ? r : null;
}
