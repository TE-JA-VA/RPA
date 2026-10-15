// 웹 관리 준비물 복사 - 함수 배포 전(predeploy)과 시험 전에 돈다 (2026-10-15 웹 전환 밑작업).
//   admin/ops.js, admin/routes.js → functions/shared/  (로컬 관리 화면과 같은 작업 코드)
//   admin/AFTERMARKET_SETUP.html  → admin_web/index.html (WEB 스위치를 켜서 - 웹 관리 화면)
// 이 세 파일만 이름으로 복사한다. admin/ 에는 serviceAccountKey.json·update_signing_key.txt 가 있어 폴더째 복사·배포는 절대 하지 않는다.
import { copyFileSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";

const at = (p) => new URL(p, import.meta.url);
export const SHARED = ["ops.js", "routes.js"];
export const WEB_OFF = "const WEB = false;", WEB_ON = "const WEB = true;";

mkdirSync(at("./shared/"), { recursive: true });
for (const f of SHARED) copyFileSync(at(`../admin/${f}`), at(`./shared/${f}`));

const page = readFileSync(at("../admin/AFTERMARKET_SETUP.html"), "utf8");
if (page.split(WEB_OFF).length !== 2) throw new Error(`관리 화면에 '${WEB_OFF}' 줄이 하나 있어야 합니다`);
mkdirSync(at("../admin_web/"), { recursive: true });
writeFileSync(at("../admin_web/index.html"), page.replace(WEB_OFF, WEB_ON));
console.log(`웹 관리 준비물 복사: shared/${SHARED.join(", shared/")}, admin_web/index.html`);
