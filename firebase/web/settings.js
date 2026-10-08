// 관리 > 환경설정: 앱마다 설정 화면을 붙인다 (앱 모듈이 settings 를 내보내면). 관리자·총괄만. PC 마다 (위쪽 PC 고르기).
// 앱이 둘이 되면 위에 앱 탭을 붙인다 - 지금은 앱 이름 머리 아래 그대로.
export const key = "settings";
export const label = "환경설정";
export const icon = "⚙️";
export const perPc = true;
export const adminOnly = true;

let mounted = [];

export function mount(el, c) {
  if (!c.isAdmin) { el.innerHTML = `<p class="muted">관리자만 볼 수 있습니다</p>`; return; }
  mounted = c.apps.filter((a) => a.settings).map((a) => {
    const sec = document.createElement("section");
    sec.className = "app-settings";
    const h = Object.assign(document.createElement("h2"), { className: "app-title", textContent: a.settings.title || a.label });
    const body = document.createElement("div");
    sec.append(h, body);
    el.append(sec);
    a.settings.mount(body, c);
    return a.settings;
  });
}

export function unmount() {
  for (const s of mounted) s.unmount();
  mounted = [];
}

export function dirty() {
  return mounted.some((s) => s.dirty?.());
}
