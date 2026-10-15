// 관리 작업 목록 - 로컬 관리 화면(admin.js)과 웹 관리 함수(../functions/index.js)가 같이 쓴다 (2026-10-15 웹 전환 밑작업).
// 작업을 늘릴 때는 여기 한 줄만 - 두 쪽이 같이 받는다. 이 PC 에만 있는 것(화면 테마 파일·[끄기])은 admin.js 에 따로 있다.
// [메서드, 경로, 할 일(body, params), 기록 글(body, 결과, params) - 없거나 null 이면 안 남긴다]. 비밀번호는 기록 글에 절대 넣지 않는다
import * as ops from "./ops.js";

// 관리 기록 한 줄: 'sales = 2, hold = (기본값)'
const priceNote = (values) => Object.entries(values ?? {}).map(([k, v]) => `${k} = ${String(v ?? "").trim() || "(기본값)"}`).join(", ");

export function compile(list) {
  return list.map(([method, pattern, run, note]) => {
    const names = [];
    const re = new RegExp(`^${pattern.replace(/:(\w+)/g, (_, n) => { names.push(n); return "([a-z0-9_]+)"; })}$`);
    return { method, re, names, run, note };
  });
}

// 맞는 작업과 경로 값 {route, params} - 없으면 null
export function find(routes, method, path) {
  const p = typeof path === "string" ? path : "";      // 웹은 아무 값이나 보낼 수 있다 - 글자가 아니면 모르는 요청
  const route = routes.find((r) => r.method === method && r.re.test(p));
  if (!route) return null;
  const hit = p.match(route.re);
  return { route, params: Object.fromEntries(route.names.map((n, i) => [n, hit[i + 1]])) };
}

export const ROUTES = compile([
  ["GET", "/api/info", () => ({ emulator: ops.onEmulator(), project: ops.PROJECT, dashboard: ops.DASHBOARD_URL })],
  ["GET", "/api/companies", () => ops.companyTable()],
  ["GET", "/api/companies/:cid", (b, p) => ops.companyDetail(p.cid)],
  ["POST", "/api/setup", (b) => ops.setupCompany(b),
    (b, r) => `신규 업체 ${b.cid}: ${r.steps.map((s) => `${s.ok ? "✓" : "✗"} ${s.label}`).join(", ")}`],
  ["POST", "/api/companies/:cid/pcs", async (b, p) => {
    const pc = await ops.addPc(p.cid, b.pcId, b.label);
    return { pc, agent: b.agent ? await ops.addAgent(p.cid, b.pcId) : null };
  }, (b, r, p) => `PC 추가 ${p.cid}/${r.pc.pcId}${r.agent ? " + 에이전트 계정" : ""}`],
  ["POST", "/api/companies/:cid/phones", (b, p) => ops.addPhone(p.cid, String(b.phoneId ?? "").trim(), b.label, b.owner),
    (b, r, p) => `휴대폰 추가 ${p.cid}/${r.phoneId} (${r.label})`],
  ["POST", "/api/companies/:cid/users", (b, p) => ops.addUser(p.cid, b.id, b.role, b.name), (b, r, p) => `계정 추가 ${p.cid} ${r.email} (${r.role})`],
  ["POST", "/api/companies/:cid/passwd", (b, p) => ops.resetPassword(p.cid, b.id), (b, r, p) => `비밀번호 재발급 ${p.cid} ${r.email}`],
  ["POST", "/api/companies/:cid/disabled", (b, p) => ops.setDisabled(p.cid, b.id, b.disabled === true),
    (b, r, p) => `${r.disabled ? "사용중지" : "사용"} ${p.cid} ${r.email}`],
  ["POST", "/api/companies/:cid/modules", (b, p) => ops.setModules(p.cid, b),
    (b, r, p) => `모듈 정책 ${p.cid} ${Object.entries(b).map(([k, v]) => `${k}=${v}`).join(" ")}`],
  ["POST", "/api/companies/:cid/features", (b, p) => ops.setFeature(p.cid, "wellife", b.wellife === true),
    (b, r, p) => `웰라이프 실행 ${p.cid} = ${b.wellife === true ? "켬" : "끔"}`],
  ["POST", "/api/companies/:cid/limits", (b, p) => ops.setScheduleLimit(p.cid, b.schedule), (b, r, p) => `자동 실행 슬롯 수 ${p.cid} = ${r.schedule}`],
  ["POST", "/api/companies/:cid/presets", (b, p) => ops.setPresetLimit(p.cid, b.presets), (b, r, p) => `옵저버 프리셋 수 ${p.cid} = ${r.presets}`],
  ["POST", "/api/companies/:cid/remove", (b, p) => {
    if (b.confirm !== p.cid) throw new ops.Refused("업체코드를 정확히 입력해야 비활성화할 수 있습니다.");
    return ops.setCompanyRemoved(p.cid, true);
  }, (b, r, p) => `업체 비활성화 ${p.cid} (계정 ${r.users.length}개 사용중지)`],
  ["POST", "/api/companies/:cid/restore", (b, p) => ops.setCompanyRemoved(p.cid, false), (b, r, p) => (r.already ? null : `업체 다시 활성화 ${p.cid}`)],
  ["POST", "/api/companies/:cid/tokens", (b, p) => ops.grantTokens(p.cid, b.amount, b.memo), (b, r, p) => `토큰 ${b.amount} ${p.cid} ${b.memo ?? ""}`.trim()],
  ["GET", "/api/releases", () => ops.releasesOf()],
  ["POST", "/api/releases/stable", (b) => ops.setStable(b.version), (b) => `안정본 지정 ${b.version}`],
  ["GET", "/api/companies/:cid/pcs/:pcId/status", (b, p) => ops.pcUpdateStatus(p.cid, p.pcId)],
  ["POST", "/api/companies/:cid/pcs/:pcId/update", (b, p) => ops.sendUpdate(p.cid, p.pcId, b.version), (b, r, p) => `업데이트 ${p.cid}/${p.pcId} → ${b.version}`],
  ["POST", "/api/companies/:cid/pcs/:pcId/rollback", (b, p) => ops.sendRollback(p.cid, p.pcId), (b, r, p) => `이전 판으로 되돌리기 ${p.cid}/${p.pcId}`],
  ["GET", "/api/prices", () => ops.getPrices()],
  ["POST", "/api/prices", (b) => ops.setPrices(b.values), (b) => `토큰 배율 ${priceNote(b.values)}`],
  ["GET", "/api/usage", () => ops.usageRows()],
  ["GET", "/api/companies/:cid/prices", (b, p) => ops.companyPrices(p.cid)],
  ["POST", "/api/companies/:cid/prices", (b, p) => ops.setCompanyPrices(p.cid, b.values),
    (b, r, p) => `업체 토큰 배율 ${p.cid} ${priceNote(b.values)}`],
]);
