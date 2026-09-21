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
export const HEARTBEAT_STALE_SEC = 20;   // 에이전트는 5초마다 보낸다 - 네 번 놓치면 끊김
export const COMMAND_TTL_SEC = 600;
