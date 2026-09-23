// 토스트 알림. 화면 오른쪽 아래(좁은 창에선 아래 전체)에 쌓이고 스스로 사라진다.
// 자리는 index.html 의 #toasts 하나뿐이라 어느 앱에서든 같은 자리에 뜬다.
const ICON = {
  ok: "M9 12.75 11.25 15 15 9.75M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z",
  info: "M11.25 11.25h1.5v5.25m-1.5 0h3M12 7.5h.01M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z",
  warn: "M12 9v3.75m0 3.75h.01M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z",
  bad: "M9.75 9.75l4.5 4.5m0-4.5l-4.5 4.5M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z",
};
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
    el.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"
      stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path/></svg><p></p><span class="x">✕</span>`;
    el.onclick = () => close(el);
    box.append(el);
  }
  el.className = `toast ${ICON[kind] ? kind : "info"}`;
  el.setAttribute("role", kind === "bad" ? "alert" : "status");
  el.querySelector("path").setAttribute("d", ICON[kind] || ICON.info);
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
