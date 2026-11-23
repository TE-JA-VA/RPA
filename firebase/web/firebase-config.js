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
// 일반 버전만 쓴다 (data-firebase.js). 끊김 기준·명령 만료처럼 Firebase 와 상관없는 값은 config.js 로 옮겼다 (스탠드얼론 ② Task 1)
