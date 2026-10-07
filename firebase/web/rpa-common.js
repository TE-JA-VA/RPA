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
export const LOCKED = new Set(["Login"]);   // 항상 켬. 관리자도 못 끈다 (에이전트도 파일에 Y 로 고정)
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
