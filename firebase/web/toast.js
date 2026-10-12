// 토스트 알림. 화면 오른쪽 아래(좁은 창에선 아래 전체)에 쌓이고 스스로 사라진다.
// 자리는 index.html 의 #toasts 하나뿐이라 어느 앱에서든 같은 자리에 뜬다.
import { icon } from "./icons.js";
// 종류별 Lucide 아이콘 (icons.js)
const ICON = { ok: "circle-check", info: "info", warn: "triangle-alert", bad: "circle-x" };
const TTL = { bad: 8000, warn: 6000 };   // 나쁜 소식은 조금 더 머문다
const MAX = () => (window.innerWidth < 720 ? 3 : 4);

/** kind: ok | info | warn | bad. id 를 주면 같은 id 토스트를 새로 쌓지 않고 제자리에서 고친다 (명령 진행 안내) */
export function toast(kind, text, ttlMs, id) {
  const box = document.getElementById("toasts");
  if (!box || !text) return null;
  let el = id ? box.querySelector(`[data-id="${id}"]`) : null;
  if (!el) {
    el = document.createElement("div");
    if (id) el.dataset.id = id;
    el.innerHTML = `<span class="tic"></span><p></p><span class="x">${icon("x")}</span>`;
    el.onclick = () => close(el);
    box.append(el);
  }
  el.className = `toast ${ICON[kind] ? kind : "info"}`;
  el.setAttribute("role", kind === "bad" ? "alert" : "status");
  el.querySelector(".tic").innerHTML = icon(ICON[kind] || ICON.info);
  el.querySelector("p").textContent = text;
  clearTimeout(el._timer);
  el._timer = setTimeout(() => close(el), ttlMs || TTL[kind] || 4500);
  while (box.children.length > MAX()) box.firstElementChild.remove();
  return el;
}

function close(el) {
  clearTimeout(el._timer);
  el.classList.add("out");
  setTimeout(() => el.remove(), 200);
}
