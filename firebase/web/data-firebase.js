// 일반(cloud) 버전의 데이터 자리 - Firebase SDK 를 부르는 곳은 이 파일 하나다 (스탠드얼론 ② Task 1, 설계 6.3절).
// 화면은 data.js 를 거쳐 이 함수들을 부른다. 동작·오류 code 는 옮기기 전 화면 코드 그대로다:
// RTDB 는 대문자 PERMISSION_DENIED, Firestore(실행 기록)는 소문자 permission-denied, 로그인은 auth/* 가 e.code 로 올라온다.
import { initializeApp } from "https://www.gstatic.com/firebasejs/10.14.1/firebase-app.js";
import {
  getAuth, signInWithEmailAndPassword, signInWithCustomToken, signOut as fbSignOut, onAuthStateChanged, connectAuthEmulator,
  setPersistence, browserSessionPersistence, EmailAuthProvider, reauthenticateWithCredential, updatePassword,
} from "https://www.gstatic.com/firebasejs/10.14.1/firebase-auth.js";
import {
  getDatabase, ref, get, set, push, onValue, connectDatabaseEmulator,
} from "https://www.gstatic.com/firebasejs/10.14.1/firebase-database.js";
import {
  getFirestore, collection, query, where, orderBy, limit as fsLimit, getDocs, connectFirestoreEmulator,
  doc, getDoc, getAggregateFromServer, sum, onSnapshot,
} from "https://www.gstatic.com/firebasejs/10.14.1/firebase-firestore.js";
import { firebaseConfig } from "./firebase-config.js";
import { CONSOLE_UID, CONSOLE_SEC } from "./config.js";

let app = null, auth = null, db = null, fs = null;
let handoffBad = false;

/** Firebase 를 연다 - 기본 앱(이름 없음) 그대로. 화면 시험이 gstatic 모듈의 getApp()·getAuth() 로 같은 앱을 잡는다 */
export async function init() {
  if (app) return;
  app = initializeApp(firebaseConfig);
  auth = getAuth(app);
  db = getDatabase(app);
  fs = getFirestore(app);
  // 화면 시험용: 에뮬레이터 Hosting(127.0.0.1)에서 ?emu=1 로 열면 에뮬레이터에 붙는다. 실제 주소에서는 무시된다.
  if (location.hostname === "127.0.0.1" && new URLSearchParams(location.search).get("emu") === "1") {
    connectAuthEmulator(auth, "http://127.0.0.1:9099", { disableWarnings: true });
    connectDatabaseEmulator(db, "127.0.0.1", 9000);
    try { connectFirestoreEmulator(fs, "127.0.0.1", 8080); } catch {}
  }
  // 로그인 정보는 탭 저장소에만 둔다 - 탭(브라우저)을 닫으면 로그인이 끝난다 (사용자 2026-11-19, 고객사 보안 검토).
  // 옛 방식으로 브라우저에 남아 있던 로그인도 여기서 탭 저장소로 옮겨진다 (setPersistence 는 지금 로그인한 계정을 새 저장소로 옮긴다)
  await setPersistence(auth, browserSessionPersistence).catch(() => {});
  // 관리 화면 [대시보드 보기] 가 주소 # 뒤에 붙인 1시간짜리 총괄 로그인 열쇠 (2026-10-16) - 주소창에서 곧바로 지우고 그 열쇠로 로그인한다.
  // 이미 다른 계정으로 로그인돼 있어도 바꾼다 (총괄 화면을 보려고 누른 것). 못 쓰면 (1시간 지남) handoffFailed() 가 참 - 화면이 안내한다
  const handoff = new URLSearchParams(location.hash.slice(1)).get("t");
  if (handoff) {
    history.replaceState(null, "", location.pathname + location.search);
    try {
      await setPersistence(auth, browserSessionPersistence);
      await signInWithCustomToken(auth, handoff);
    } catch {
      handoffBad = true;
    }
  }
}

/** init 에서 #t= 열쇠로 로그인하지 못했나 */
export const handoffFailed = () => handoffBad;

/** 로그인·로그아웃·새로고침 복원을 한 콜백으로 알린다. cb(null) 로그아웃, cb({uid, email, cid, role, consoleLeftMs?}) 로그인,
 *  cb({error: "network"}) 토큰을 못 받음. 로그인은 토큰(claims)을 새로 받은 뒤에 알린다.
 *  consoleLeftMs 는 관리 화면 열쇠 계정일 때만 - 남은 시간은 서버 시각끼리(방금 받은 토큰의 iat - 로그인 auth_time)로 잰다 (브라우저 시계가 틀려도 맞게).
 *  auth_time 이 없으면 NaN (화면이 곧바로 로그아웃한다) */
export function onSession(cb) {
  return onAuthStateChanged(auth, async (user) => {
    if (!user) return cb(null);
    let t;
    try { t = await user.getIdTokenResult(true); } catch {   // 네트워크가 끊겨 토큰을 못 받으면 빈 화면에서 멈췄다 (BugBuster M4)
      return cb({ error: "network" });
    }
    const s = { uid: user.uid, email: user.email, cid: t.claims.cid || null, role: t.claims.role || null };
    if (user.uid === CONSOLE_UID) {
      s.consoleLeftMs = t.claims.auth_time
        ? (CONSOLE_SEC - ((Number(t.claims.iat) || 0) - (Number(t.claims.auth_time) || 0))) * 1000 : NaN;
    }
    return cb(s);
  });
}

// 공유 계약 (agent.py·setup.js 와 같은 규칙): 아이디에 @ 가 있으면 그대로, 없으면 아이디@회사코드.프로젝트도메인. '_' 는 '-' 로. 업체코드가 비면(총괄) 프로젝트 도메인만
export const emailFor = (cid, id) => id.includes("@") ? id : `${id.replaceAll("_", "-")}@${cid ? cid.replaceAll("_", "-") + "." : ""}${firebaseConfig.authDomain}`;

/** 업체코드·아이디·비밀번호로 로그인 (탭 저장소에만 - init 의 setPersistence). 실패는 e.code (auth/*) */
export async function signIn(cid, id, password) {
  await signInWithEmailAndPassword(auth, emailFor(cid, id), password);
}
export const signOut = () => fbSignOut(auth);
export const signedIn = () => !!auth?.currentUser;
export const sessionUid = () => auth?.currentUser?.uid ?? null;

/** 현재 비밀번호로 다시 인증한 뒤 바꾼다 (Firebase 가 요구한다). 실패는 e.code */
export async function changePassword(current, next) {
  const user = auth.currentUser;
  await reauthenticateWithCredential(user, EmailAuthProvider.credential(user.email, current));
  await updatePassword(user, next);
}

/** 업체 정보 meta/companies/<cid> - 못 읽으면 {} */
export async function getCompany(cid) {
  try {
    const snap = await get(ref(db, `meta/companies/${cid}`));
    return snap.val() || {};
  } catch { return {}; }
}

/** RTDB 자리 하나를 지켜본다 - cb(값, 없으면 null), onError(e). 그만 보려면 돌려준 함수를 부른다 */
export const watch = (path, cb, onError) => onValue(ref(db, path), (snap) => cb(snap.val()), onError);

// 명령 시각은 서버 시각 = 이 브라우저 시각 + RTDB 가 알려 주는 차이 (BugBuster M1) - 브라우저 시계가 틀려도 규칙(서버 now±60초)·PC 판정이 맞게.
// 처음 부를 때 구독을 시작하고 그 뒤로는 계속 따라간다. 못 읽으면 차이 0 으로 넘어간다
let skew = null, skewOff = 0;
export function skewReady() {
  if (!skew) skew = new Promise((ok) => onValue(ref(db, ".info/serverTimeOffset"), (snap) => { skewOff = Number(snap.val()) || 0; ok(); }, () => ok()));
  return skew;
}
export const skewMs = () => skewOff;

/** 명령 하나를 apps/rpa/commands/<cid>/<pc> 에 넣고 그 키를 돌려준다 */
export async function pushCommand(cid, pcId, command) {
  const node = await push(ref(db, `apps/rpa/commands/${cid}/${pcId}`), command);
  return node.key;
}

/** 설정 한 칸 apps/rpa/settings/<cid>/<pc>/<part> 를 바꾼다 */
export async function saveSettings(cid, pcId, part, value) {
  await set(ref(db, `apps/rpa/settings/${cid}/${pcId}/${part}`), value);
}

/** 실행 기록 (Firestore runs/<cid>/items) - 그 PC 것만, 날짜를 주면 그날만, 시작 시각 최신 순으로 limit 개 */
export async function listRuns(cid, { pcId, date, limit }) {
  const col = collection(fs, "runs", cid, "items");
  const q = date
    ? query(col, where("pcId", "==", pcId), where("date", "==", date), orderBy("started_at", "desc"), fsLimit(limit))
    : query(col, where("pcId", "==", pcId), orderBy("started_at", "desc"), fsLimit(limit));
  const snap = await getDocs(q);
  return snap.docs.map((d) => d.data());
}

/** 업체 통장 wallet/<cid> - 없으면 null. 못 읽으면 던진다 */
export async function getWallet(cid) {
  const snap = await getDoc(doc(fs, "wallet", cid));
  return snap.data() || null;
}
/** 통장 문서가 바뀔 때마다 cb(통장, 없으면 null) */
export const watchWallet = (cid, cb, onError = () => {}) => onSnapshot(doc(fs, "wallet", cid), (snap) => cb(snap.data() || null), onError);

/** 실행 기록의 한 칸 합 (서버가 더한다). from·to 를 주면 started_at 이 그 사이인 것만. 못 읽으면 던진다 */
export async function sumRuns(cid, field, { from, to } = {}) {
  const col = collection(fs, "runs", cid, "items"), conds = [];
  if (from != null) conds.push(where("started_at", ">=", from));
  if (to != null) conds.push(where("started_at", "<=", to));
  const r = await getAggregateFromServer(conds.length ? query(col, ...conds) : col, { s: sum(field) });
  return r.data().s ?? 0;
}
