// 테마(밝음/어두움)와 강조색. 고른 값은 이 브라우저에만 남는다 (localStorage).
//
// 강조색은 [이름, 밝음용, 어두움용] 쌍이다. 밝은 바탕(sand)과 어두운 카드(dark) 양쪽에서 잘 보이는 색은 드물어서
// 모드마다 다른 값을 쓴다. 저장은 밝음용 값으로 하고, 어두운 모드면 짝을 찾아 바꿔 단다. 직접 고른 색은 양쪽 같은 값.
// 상태색(성공 초록·오류 주황·실패 빨강·진행 파랑)과 헷갈리는 색은 후보에 넣지 않는다.
export const DEFAULT_ACCENT = "#f29f67";   // StarAdmin 팔레트의 주황. 크림 바탕과 짙은 청록 바탕 양쪽에서 같은 값
export const ACCENTS = [
  ["orange", "#f29f67", "#f29f67"],
  ["navy", "#21263a", "#fdf6e3"],     // 어두운 모드에선 크림
  ["violet", "#6c71c4", "#9a9fe0"],
];
// 파랑·청록·노랑은 팔레트에 있지만 진행·성공·오류 색이라 강조 후보에서 뺀다
const INK_DARK = "#1e1e2c", INK_LIGHT = "#fdf6e3";

function luminance(hex) {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
function contrast(a, b) {
  const la = luminance(a), lb = luminance(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

export function getAccent() {
  try { return localStorage.getItem("accent") || DEFAULT_ACCENT; } catch { return DEFAULT_ACCENT; }
}

/** 지금 모드에서 실제로 칠할 값. hex 는 저장된(밝음용) 값 */
export function accentFor(hex, dark = isDark()) {
  const pair = ACCENTS.find(([, light]) => light === hex);
  return dark && pair ? pair[2] : hex;
}

export function applyAccent(hex) {
  const ok = /^#[0-9a-f]{6}$/i.test(hex || "");
  const v = ok ? hex.toLowerCase() : DEFAULT_ACCENT;
  const shown = accentFor(v);
  const root = document.documentElement.style;
  root.setProperty("--accent", shown);
  // 글자색은 대비가 더 큰 쪽. 밝기 문턱으로 고르면 teal 위에 흰 글자가 올라가 4.5:1 에 못 미친다
  root.setProperty("--accent-ink", contrast(shown, INK_DARK) >= contrast(shown, INK_LIGHT) ? INK_DARK : INK_LIGHT);
  try { if (v === DEFAULT_ACCENT) localStorage.removeItem("accent"); else localStorage.setItem("accent", v); } catch {}
  return v;
}

export function getTheme() {
  try { return localStorage.getItem("theme"); } catch { return null; }
}

export function applyTheme(t) {
  if (t) document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme;
  try { if (t) localStorage.setItem("theme", t); else localStorage.removeItem("theme"); } catch {}
  applyAccent(getAccent());   // 모드가 바뀌면 강조색 짝도 바꿔 단다
}

export function isDark() {
  const t = document.documentElement.dataset.theme;
  return t === "dark" || (!t && matchMedia("(prefers-color-scheme: dark)").matches);
}
