// 테마(밝음/어두움)와 강조색. 고른 값은 이 브라우저에만 남는다 (localStorage).
export const DEFAULT_ACCENT = "#2aa198";
// Solarized 강조 후보. green·orange·red 는 상태 색이라 뺐다
export const ACCENTS = [["cyan", "#2aa198"], ["blue", "#268bd2"], ["violet", "#6c71c4"], ["magenta", "#d33682"], ["yellow", "#b58900"]];

function luminance(hex) {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function getAccent() {
  try { return localStorage.getItem("accent") || DEFAULT_ACCENT; } catch { return DEFAULT_ACCENT; }
}

export function applyAccent(hex) {
  const ok = /^#[0-9a-f]{6}$/i.test(hex || "");
  const v = ok ? hex.toLowerCase() : DEFAULT_ACCENT;
  const root = document.documentElement.style;
  root.setProperty("--accent", v);
  root.setProperty("--accent-ink", luminance(v) > 0.45 ? "#002b36" : "#fdf6e3");   // 밝은 강조색이면 어두운 글자
  try { if (v === DEFAULT_ACCENT) localStorage.removeItem("accent"); else localStorage.setItem("accent", v); } catch {}
  return v;
}

export function getTheme() {
  try { return localStorage.getItem("theme"); } catch { return null; }
}

export function applyTheme(t) {
  if (t) document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme;
  try { if (t) localStorage.setItem("theme", t); else localStorage.removeItem("theme"); } catch {}
}

export function isDark() {
  const t = document.documentElement.dataset.theme;
  return t === "dark" || (!t && matchMedia("(prefers-color-scheme: dark)").matches);
}
