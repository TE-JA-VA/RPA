// 웹 관리 함수 (Blaze 뒤에 배포 - 2026-10-15 밑작업, 옮기는 날 순서는 docs/admin-web-transition.md).
// 로컬 관리 화면(admin/admin.js)과 같은 작업 목록(routes.js)·작업 코드(ops.js)를 총괄(super) 계정에게만 연다.
// 화면은 같은 AFTERMARKET_SETUP.html (WEB 스위치를 켠 admin_web/index.html) - 요청 {method, path, body} 를 로컬 /api 와 똑같이 보낸다.
// shared/ 는 sync.mjs 가 admin/ 에서 복사한다 (배포 전 predeploy·시험 전). 직접 고치지 말 것 - admin/ 을 고친다.
import { onCall, HttpsError } from "firebase-functions/v2/https";
import { getAuth } from "firebase-admin/auth";
import { ROUTES, find } from "./shared/routes.js";
import * as ops from "./shared/ops.js";

const REGION = "asia-northeast3";      // 서울 - 화면(AFTERMARKET_SETUP.html webStart)과 같아야 한다

// 총괄 계정인가 - 토큰의 claim 만 믿지 않고 계정을 다시 읽는다: ID 토큰은 1시간 살아 있어서
// 그 사이 사용중지·권한 회수가 바로 먹게 (로컬은 이 PC 를 켤 수 있는 사람만 쓰니 이런 확인이 없었다)
async function superOf(auth) {
  if (!auth?.uid || auth.token?.role !== "super") return null;
  const user = await getAuth().getUser(auth.uid).catch(() => null);
  return user && !user.disabled && user.customClaims?.role === "super" ? user : null;
}

// 총괄 계정 만들기·비밀번호 재발급·사용중지는 로컬(setup.js·로컬 관리 화면)에서만 - 웹 세션을 뺏겨도
// 총괄을 새로 심거나 다른 총괄을 잠그지 못하게. 계정 고르기는 ops.userOf 와 같은 꼴 (아이디에 @ 가 있으면 그대로 이메일)
async function touchesSuper(path, params, b) {
  if (path.endsWith("/users")) return b.role === "super";
  if (!path.endsWith("/passwd") && !path.endsWith("/disabled")) return false;
  const u = await getAuth().getUserByEmail(ops.emailFor(params.cid, String(b.id ?? ""))).catch((e) => {
    if (e.code === "auth/user-not-found") return null;      // 없는 계정 - ops 가 '계정이 없다' 로 거절한다
    throw e;                                                 // 다른 오류로 못 읽으면 막는다 (못 읽었다고 통과시키지 않는다)
  });
  return u?.customClaims?.role === "super";
}

// ponytail: 로컬은 고치는 요청을 하나씩 줄 세우지만(admin.js serial) 함수는 인스턴스가 여럿이라 못 세운다.
// 화면이 누르는 동안 단추를 잠그고(act), ops 의 만들기는 '이미 있다' 를 건너뛰어 겹쳐도 반쪽이 남지 않는다. 총괄이 여럿 동시에 고치게 되면 트랜잭션으로.
export const admin = onCall({ region: REGION, timeoutSeconds: 300, memory: "512MiB" }, async (req) => {
  const user = await superOf(req.auth);
  if (!user) throw new HttpsError("permission-denied", "총괄 계정만 사용할 수 있습니다.");
  const { method, path, body } = req.data ?? {};
  const found = find(ROUTES, method, path);
  if (!found) throw new HttpsError("not-found", "알 수 없는 요청입니다.");
  const b = body && typeof body === "object" && !Array.isArray(body) ? body : {};
  if (method === "POST" && await touchesSuper(path, found.params, b)) {
    throw new HttpsError("permission-denied", "총괄 계정은 웹에서 등록하거나 변경할 수 없습니다. 관리 PC의 관리 도구(setup.js)를 사용하여 주십시오.");
  }
  try {
    const result = await found.route.run(b, found.params);
    const line = found.route.note?.(b, result, found.params);
    if (line) await ops.logToDb(line, user.email ?? user.uid, "웹");
    return result;
  } catch (e) {
    if (e instanceof ops.Refused) throw new HttpsError("failed-precondition", e.message);
    console.error(e);                             // 비밀번호는 결과에만 있고 오류에는 없다
    throw new HttpsError("internal", `예기치 않은 오류가 발생하였습니다. (${e.code ?? e.name}: ${e.message})`);
  }
});
