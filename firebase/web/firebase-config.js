// 공개돼도 되는 값이다. 보안은 DB 규칙이 한다.
export const firebaseConfig = {
  apiKey: "AIzaSyCFbHQjWVxzi38IAYIhQX9wyiGIs1VcZuA",
  authDomain: "rpa-test-f02e0.firebaseapp.com",
  databaseURL: "https://rpa-test-f02e0-default-rtdb.asia-southeast1.firebasedatabase.app",
  projectId: "rpa-test-f02e0",
  storageBucket: "rpa-test-f02e0.firebasestorage.app",
  messagingSenderId: "420865367421",
  appId: "1:420865367421:web:14b9e1e10c5fadc7e04014",
};
// 끊김 기준은 에이전트가 올리는 heartbeat.every(신호 주기)로 잡는다.
// 새 에이전트는 5초마다 보내니 20초, every 를 안 올리는 옛 에이전트는 30초 주기로 보아 95초.
// 이렇게 하지 않으면 아직 안 고친 PC 가 정상과 끊김을 오간다.
export const HEARTBEAT_EVERY_DEFAULT = 30;
export const HEARTBEAT_MISS = 3;         // 이만큼 연달아 놓치면 끊김
export const COMMAND_TTL_SEC = 600;
