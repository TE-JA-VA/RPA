// QR 코드를 SVG 요소로 그린다 (스탠드얼론 환경설정의 휴대폰 짝짓기, 계획 ④ Task 3).
// 무늬 계산은 공개 코드 vendor/qrcode.js (qrcode-generator 2.0.4, MIT) - 바깥 CDN 을 부르지 않는다.
// canvas·data: 그림 없이 createElementNS 로만 만든다 (로컬 서버의 CSP default-src 'self' 그대로).
// 스탠드얼론 화면만 이 파일을 동적 import 한다 (일반 버전 화면은 받지 않는다).
import qrcode from "./vendor/qrcode.js";

const NS = "http://www.w3.org/2000/svg";
const MARGIN = 4;              // 둘레 여백 (모듈 4칸 - QR 규격의 조용한 자리)

/** text 의 QR (오류 정정 M, 크기는 내용에 맞춰 자동) → <svg> 요소. 검정 무늬·흰 바탕 고정 (어두운 바탕에서도 읽히게).
 *  data-modules = 모듈 수 (4×버전+17), 시험이 본다 */
export function qrSvg(text) {
  const qr = qrcode(0, "M");
  qr.addData(String(text), "Byte");
  qr.make();
  const n = qr.getModuleCount(), size = n + MARGIN * 2;
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", `0 0 ${size} ${size}`);
  svg.setAttribute("shape-rendering", "crispEdges");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "휴대폰 연결 QR 코드");
  svg.dataset.modules = String(n);
  const bg = document.createElementNS(NS, "rect");
  bg.setAttribute("width", String(size)); bg.setAttribute("height", String(size)); bg.setAttribute("fill", "#ffffff");
  const parts = [];
  for (let r = 0; r < n; r++) {
    for (let c = 0; c < n; c++) {
      if (qr.isDark(r, c)) parts.push(`M${c + MARGIN} ${r + MARGIN}h1v1h-1z`);
    }
  }
  const path = document.createElementNS(NS, "path");
  path.setAttribute("d", parts.join(""));
  path.setAttribute("fill", "#000000");
  svg.append(bg, path);
  return svg;
}

/** 모듈 하나가 검정인가 (시험 - 세 귀퉁이 찾기 무늬) */
export function qrMatrix(text) {
  const qr = qrcode(0, "M");
  qr.addData(String(text), "Byte");
  qr.make();
  const n = qr.getModuleCount();
  return Array.from({ length: n }, (_, r) => Array.from({ length: n }, (_, c) => qr.isDark(r, c)));
}
