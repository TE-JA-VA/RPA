// 일반·스탠드얼론 버전이 같이 쓰는 값 (Firebase 와 상관없는 것만 - firebase-config.js 에서 옮김, 스탠드얼론 ② Task 1)
// 끊김 기준은 에이전트가 올리는 heartbeat.every(신호 주기)로 잡는다.
// 새 에이전트는 5초마다 보내니 20초, every 를 안 올리는 옛 에이전트는 30초 주기로 보아 95초.
// 이렇게 하지 않으면 아직 안 고친 PC 가 정상과 끊김을 오간다.
export const HEARTBEAT_EVERY_DEFAULT = 30;
export const HEARTBEAT_MISS = 3;         // 이만큼 연달아 놓치면 끊김
export const COMMAND_TTL_SEC = 600;
// 관리 화면 [대시보드 보기] 로그인 계정 - ops.CONSOLE_UID 와 같다. 로그인 1시간 뒤 로그아웃 (BugBuster I15)
export const CONSOLE_UID = "admin-console";
export const CONSOLE_SEC = 3600;
