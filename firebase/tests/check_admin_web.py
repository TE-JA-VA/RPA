"""웹 관리 (Blaze 뒤에 배포 - 2026-10-15 밑작업) 시험: 관리 함수(functions/index.js)와 웹 관리 화면(admin_web)을 에뮬레이터로 본다.
실제 프로젝트는 안 건드린다. 함수 에뮬레이터는 무료 플랜에서도 돈다. 복사본(shared/, admin_web/)은 에뮬레이터를 켜기 전에 만들어야 한다:

    cd D:\\AX\\RPA\\firebase; . .\\emu_env.ps1; node functions\\sync.mjs
    firebase emulators:exec --config firebase.admin-web.json --only auth,database,firestore,functions,hosting --project rpa-test-f02e0 "D:\\AX\\RPA\\.venv\\Scripts\\python.exe tests\\check_admin_web.py"

만드는 계정은 에뮬레이터 것이라도 비밀번호를 찍지 않는다.
"""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
PROJECT = "rpa-test-f02e0"
AUTH = "http://127.0.0.1:9099"
FS = f"http://127.0.0.1:8080/v1/projects/{PROJECT}/databases/(default)/documents"
FN = f"http://127.0.0.1:5001/{PROJECT}/asia-northeast3/admin"
WEB = "http://127.0.0.1:5002/"
OWNER = {"Authorization": "Bearer owner"}
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
FAIL, SECRETS = [], []
COUNT = 0
for k in ("FIREBASE_AUTH_EMULATOR_HOST", "FIRESTORE_EMULATOR_HOST"):
    if not os.environ.get(k):
        sys.exit(f"{k} 가 없다. emulators:exec 안에서 돌릴 것")


def mask(text):
    text = str(text)
    for s in SECRETS:
        if s:
            text = text.replace(s, "****")
    return text


def check(ok, label, detail=""):
    global COUNT
    COUNT += 1
    print(f"  {'통과' if ok else '실패'}  {label}" + (f"  {mask(detail)}" if detail and not ok else ""))
    if not ok:
        FAIL.append(label)


def http(method, url, body=None, headers=None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or "null")


def read(path):
    with open(os.path.join(ROOT, path), "rb") as f:
        return f.read()


def user(email, password, claims=None):
    """에뮬레이터 계정을 만들고 claim 을 붙인 뒤 ID 토큰을 받는다."""
    SECRETS.append(password)
    _, r = http("POST", f"{AUTH}/identitytoolkit.googleapis.com/v1/accounts:signUp?key=x", {"email": email, "password": password})
    uid = r["localId"]
    if claims:
        http("POST", f"{AUTH}/identitytoolkit.googleapis.com/v1/projects/{PROJECT}/accounts:update",
             {"localId": uid, "customAttributes": json.dumps(claims)}, OWNER)
    return uid, sign_in(email, password)


def sign_in(email, password):
    _, r = http("POST", f"{AUTH}/identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=x",
                {"email": email, "password": password, "returnSecureToken": True})
    return r["idToken"]


def fn(token, method, path, body=None):
    """관리 함수 부르기 → (결과, 오류 상태, 오류 글)."""
    _, r = http("POST", FN, {"data": {"method": method, "path": path, "body": body}},
                {"Authorization": f"Bearer {token}"} if token else {})
    r = r or {}
    err = r.get("error") or {}
    return r.get("result"), err.get("status"), err.get("message", "")


print("=== 1. 복사본과 배포 설정 (로컬·지금 배포에 영향 없게) ===")
for f in ("ops.js", "routes.js"):
    check(read(f"functions/shared/{f}") == read(f"admin/{f}"), f"functions/shared/{f} 가 admin/{f} 와 같다 (다르면 node functions/sync.mjs)")
check(sorted(os.listdir(os.path.join(ROOT, "functions", "shared"))) == ["ops.js", "routes.js"],
      "shared/ 에는 두 파일만 - 키 파일이 함수 쪽으로 가지 않는다", os.listdir(os.path.join(ROOT, "functions", "shared")))
page, web_page = read("admin/AFTERMARKET_SETUP.html").decode("utf-8"), read("admin_web/index.html").decode("utf-8")
check(page.count("const WEB = false;") == 1 and "const WEB = true;" not in page, "로컬 관리 화면은 WEB 꺼짐 그대로")
check(web_page == page.replace("const WEB = false;", "const WEB = true;"), "웹 관리 화면 = 로컬 화면 + WEB 켬 (다른 데는 같다)")
main = json.loads(read("firebase.json"))
check("functions" not in main and main["hosting"]["public"] == "web",
      "보통 firebase.json 에는 함수가 없고 업체 웹(web)만 - 지금 배포(--only hosting)에 웹 관리가 섞이지 않는다", main.keys())
adm = json.loads(read("firebase.admin-web.json"))
check(adm["hosting"]["public"] == "admin_web" and adm["functions"][0]["source"] == "functions"
      and all("sync.mjs" in " ".join(x["predeploy"]) for x in (adm["hosting"], adm["functions"][0])),
      "웹 관리 설정: admin/ 이 아니라 admin_web·functions 만 올리고, 올리기 전에 복사본을 새로 만든다")
check(all(x in adm["functions"][0]["ignore"] for x in ("**/serviceAccountKey.json", "**/update_signing_key.txt", ".env*")),
      "함수 배포는 비밀 파일 이름을 따로 막는다 (누가 실수로 복사해도 안 올라가게)", adm["functions"][0]["ignore"])
check(not os.path.exists(os.path.join(ROOT, "admin_web", "serviceAccountKey.json"))
      and set(os.listdir(os.path.join(ROOT, "admin_web"))) == {"index.html"}, "admin_web 에는 화면 하나만", os.listdir(os.path.join(ROOT, "admin_web")))

env = {k: v for k, v in os.environ.items() if k not in ("FUNCTIONS_EMULATOR", "K_SERVICE")}
r = subprocess.run(["node", "-e", "import('./index.js').then(m => console.log('LOADED', typeof m.admin), e => { console.log('FAILED', e.message); process.exit(1); })"],
                   cwd=os.path.join(ROOT, "functions"), env=env, capture_output=True, text=True, encoding="utf-8", timeout=120)
check("LOADED function" in r.stdout, "배포 도구처럼 (이 PC 에서, 함수 환경 변수 없이) 함수 코드를 불러도 된다 - 키 파일을 찾지 않는다 (검토 2026-10-15)",
      (r.stdout + r.stderr)[-300:])

print("=== 2. 누가 부를 수 있나 ===")
super_uid, super_tok = user("boss@rpa-test-f02e0.firebaseapp.com", "super-pw-1234", {"role": "super"})
_, admin_tok = user("adm@c-one.rpa-test-f02e0.firebaseapp.com", "admin-pw-1234", {"role": "admin", "cid": "c_one"})
_, agent_tok = user("agent-pc_a@c-one.rpa-test-f02e0.firebaseapp.com", "agent-pw-1234", {"role": "agent", "cid": "c_one", "pcId": "pc_a"})
_, plain_tok = user("nobody@rpa-test-f02e0.firebaseapp.com", "plain-pw-1234")
for label, tok in (("로그인 안 함", None), ("업체 관리자(admin)", admin_tok), ("에이전트", agent_tok), ("claim 없는 계정", plain_tok)):
    res, status, msg = fn(tok, "GET", "/api/companies")
    check(res is None and status == "PERMISSION_DENIED" and "총괄" in msg, f"{label} 는 거절 (총괄만)", (status, msg))
res, status, msg = fn("not-a-token", "GET", "/api/companies")
check(res is None and status in ("UNAUTHENTICATED", "PERMISSION_DENIED"), "엉터리 토큰은 거절", (status, msg))
res, status, msg = fn(super_tok, "GET", "/api/info")
check(status is None and res and res.get("emulator") is True and res.get("project") == PROJECT, "총괄은 된다 (/api/info, 에뮬레이터 표시)", (res, status, msg))

print("=== 3. 로컬과 같은 작업 ===")
PLAN = {"cid": "w_new", "name": "웹 업체", "hold": False, "pcs": [{"pcId": "pc_a", "label": "사무실 PC"}],
        "users": [{"id": "boss", "name": "대표", "role": "admin"}], "tokens": {"amount": "+300", "memo": "첫 결제"}}
res, status, msg = fn(super_tok, "POST", "/api/setup", PLAN)
check(status is None and res and all(s["ok"] for s in res["steps"]), "신규 업체 만들기 (로컬 /api/setup 과 같은 요청)", (status, msg, res and res.get("steps")))
def harvest(x):                               # 응답 어디에 있든 비밀번호는 가린다
    if isinstance(x, dict):
        SECRETS.extend(v for k, v in x.items() if k == "password" and isinstance(v, str))
        for v in x.values():
            harvest(v)
    elif isinstance(x, list):
        for v in x:
            harvest(v)
harvest(res)
res, status, msg = fn(super_tok, "GET", "/api/companies")
check(status is None and any(r.get("cid") == "w_new" for r in (res or [])), "업체 표에 새 업체가 보인다", (status, msg))
res, status, msg = fn(super_tok, "POST", "/api/companies/w_new/passwd", {"id": "boss"})
pw = (res or {}).get("password")
SECRETS.append(pw)
check(status is None and pw and len(pw) >= 16, "비밀번호 재발급 - 새 비밀번호는 응답에만", (status, msg))
SUPER_EMAIL = "boss@rpa-test-f02e0.firebaseapp.com"
res, status, msg = fn(super_tok, "POST", "/api/companies/w_new/users", {"id": "staff2", "role": "viewer", "name": "직원"})
harvest(res)
check(status is None and res and res.get("role") == "viewer", "업체 계정 추가는 된다", (status, msg))
for label, path, body in (("총괄 만들기 (role super)", "/api/companies/w_new/users", {"id": "evil", "role": "super", "name": "x"}),
                          ("다른 총괄 비밀번호 재발급", "/api/companies/w_new/passwd", {"id": SUPER_EMAIL}),
                          ("다른 총괄 사용중지", "/api/companies/w_new/disabled", {"id": SUPER_EMAIL, "disabled": True})):
    res, status, msg = fn(super_tok, "POST", path, body)
    harvest(res)
    check(res is None and status == "PERMISSION_DENIED" and "setup.js" in msg, f"웹에서 총괄 계정은 못 건드린다: {label}", (status, msg))
status, r = http("POST", f"{AUTH}/identitytoolkit.googleapis.com/v1/projects/{PROJECT}/accounts:lookup",
                 {"email": ["evil@w-new.rpa-test-f02e0.firebaseapp.com"]}, OWNER)
check(not (r or {}).get("users"), "거절된 총괄 계정은 만들어지지 않았다", r)
res, status, msg = fn(super_tok, "GET", "/api/info")
check(status is None and res, "거절 뒤에도 총괄 자신은 그대로 (사용중지·재발급 안 됨)", (status, msg))
res, status, msg = fn(super_tok, "POST", "/api/companies/nope_co/limits", {"schedule": 3})
check(res is None and status == "FAILED_PRECONDITION" and "등록" in msg, "사람이 고칠 거절은 그 글 그대로 (Refused → failed-precondition)", (status, msg))
for path in ("/api/prefs", "/api/quit", "/api/nothing", "/admin"):
    res, status, msg = fn(super_tok, "POST", path, {})
    check(res is None and status == "NOT_FOUND", f"로컬 전용·없는 요청은 모른다: {path}", (status, msg))
for odd in (123, ["/api/info"], None):
    res, status, msg = fn(super_tok, "GET", odd)
    check(res is None and status == "NOT_FOUND", f"경로가 글자가 아니면 모르는 요청 (뜻밖의 오류가 아니라): {odd!r}", (status, msg))
res, status, msg = fn(super_tok, "GET", "/api/companies/../x")
check(res is None and status == "NOT_FOUND", "경로 값에 이상한 글자는 안 맞는다", (status, msg))
res, status, msg = fn(super_tok, "POST", "/api/companies/w_new/limits", ["not", "object"])
check(res is None and status == "FAILED_PRECONDITION", "body 가 객체가 아니면 빈 값으로 보고 거절 (자동 실행 슬롯 수 없음)", (status, msg))

print("=== 4. 관리 기록 (DB admin_log) ===")
docs = (http("GET", f"{FS}/admin_log?pageSize=500", headers=OWNER)[1] or {}).get("documents", [])
rows = [{k: list(v.values())[0] for k, v in d["fields"].items()} for d in docs]
check(any("신규 업체 w_new" in r.get("line", "") and r.get("via") == "웹" and r.get("by") == "boss@rpa-test-f02e0.firebaseapp.com" and r.get("at")
          for r in rows), "웹에서 한 일은 {at, line, by=총괄 이메일, via=웹} 으로 남는다", rows[-3:])
check(any("비밀번호 재발급 w_new" in r.get("line", "") for r in rows), "비밀번호 재발급도 남는다 (비밀번호 없이)")
check(not any(s in json.dumps(rows, ensure_ascii=False) for s in SECRETS if s), "DB 관리 기록에 비밀번호가 없다")
check(not any("w_new/limits" in r.get("line", "") or "nope_co" in r.get("line", "") for r in rows), "거절된 일은 기록하지 않는다")
status, r = http("GET", f"{FS}/admin_log", headers={"Authorization": f"Bearer {super_tok}"})
check(status == 403, "화면(총괄 토큰)에서 admin_log 를 직접 읽지는 못한다 - 규칙은 그대로 (모두 막음)", status)

print("=== 5. 토큰이 살아 있어도 사용중지·권한 회수는 바로 ===")
http("POST", f"{AUTH}/identitytoolkit.googleapis.com/v1/projects/{PROJECT}/accounts:update",
     {"localId": super_uid, "customAttributes": json.dumps({"role": "admin", "cid": "c_one"})}, OWNER)
res, status, msg = fn(super_tok, "GET", "/api/companies")
check(res is None and status == "PERMISSION_DENIED", "총괄을 뺀 뒤 예전 토큰(claim 은 아직 super)은 거절", (status, msg))
http("POST", f"{AUTH}/identitytoolkit.googleapis.com/v1/projects/{PROJECT}/accounts:update",
     {"localId": super_uid, "customAttributes": json.dumps({"role": "super"})}, OWNER)
res, status, msg = fn(super_tok, "GET", "/api/info")
check(status is None and res, "다시 총괄로 돌리면 된다", (status, msg))
http("POST", f"{AUTH}/identitytoolkit.googleapis.com/v1/projects/{PROJECT}/accounts:update",
     {"localId": super_uid, "disableUser": True}, OWNER)
res, status, msg = fn(super_tok, "GET", "/api/info")
check(res is None and status == "PERMISSION_DENIED", "사용중지한 총괄은 예전 토큰으로도 거절", (status, msg))
http("POST", f"{AUTH}/identitytoolkit.googleapis.com/v1/projects/{PROJECT}/accounts:update",
     {"localId": super_uid, "disableUser": False}, OWNER)

print("=== 5-1. 업체 비활성화·다시 활성화는 총괄을 건드리지 않는다 ===")
super2_uid, _ = user("boss2@w-new.rpa-test-f02e0.firebaseapp.com", "super2-pw-1234", {"role": "super", "cid": "w_new"})   # setup.js user w_new boss2 super


def disabled(uid):
    _, r = http("POST", f"{AUTH}/identitytoolkit.googleapis.com/v1/projects/{PROJECT}/accounts:lookup", {"localId": [uid]}, OWNER)
    return bool(((r or {}).get("users") or [{}])[0].get("disabled"))
res, status, msg = fn(super_tok, "POST", "/api/companies/w_new/remove", {"confirm": "w_new"})
check(status is None and res, "업체 비활성화 (웹)", (status, msg))
check(not disabled(super2_uid), "업체코드가 붙은 총괄은 업체 비활성화로 사용중지되지 않는다", disabled(super2_uid))
http("POST", f"{AUTH}/identitytoolkit.googleapis.com/v1/projects/{PROJECT}/accounts:update", {"localId": super2_uid, "disableUser": True}, OWNER)
res, status, msg = fn(super_tok, "POST", "/api/companies/w_new/restore", {})
check(status is None and res, "업체 다시 활성화 (웹)", (status, msg))
check(disabled(super2_uid), "일부러 막아 둔 총괄은 업체 다시 활성화로 풀리지 않는다", disabled(super2_uid))

print("=== 6. 웹 관리 화면 (브라우저) ===")
try:
    from playwright.sync_api import sync_playwright
    sys.path.insert(0, os.path.join(ROOT, ".."))
    import web_replay
    with sync_playwright() as p:
        b = web_replay.edge(p.chromium.launch, headless=True)
        pg = b.new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(WEB)
        pg.wait_for_selector("#login-id", timeout=30000)
        check(pg.is_visible("#login-id") and pg.is_visible("#login-pw"), "웹으로 열면 로그인부터 (아이디·비밀번호)")

        def login(i, w):
            pg.fill("#login-id", i)
            pg.fill("#login-pw", w)
            pg.click("#login button[type=submit]")
        login("boss", "wrong-pw")
        pg.wait_for_selector("#login p.bad", timeout=20000)
        check("맞지 않습니다" in pg.inner_text("#login p.bad"), "틀린 비밀번호는 알린다", pg.inner_text("#login"))
        login("adm@c-one.rpa-test-f02e0.firebaseapp.com", "admin-pw-1234")
        pg.wait_for_function("document.querySelector('#login p.bad')?.textContent.includes('총괄')", timeout=20000)
        check(True, "총괄이 아닌 계정은 '총괄 계정만' 으로 막는다")
        login("boss", "super-pw-1234")           # 아이디만 치면 총괄 이메일로 (ops.emailFor(null, 아이디))
        pg.wait_for_selector("#login", state="detached", timeout=30000)
        pg.wait_for_function("document.getElementById('badge').textContent.includes('에뮬레이터')", timeout=30000)
        pg.wait_for_function("document.body.innerText.includes('w_new')", timeout=30000)
        check(True, "총괄로 로그인하면 업체 표가 뜬다 (함수를 거쳐)")
        check(pg.inner_text("#quit") == "로그아웃", "[끄기] 대신 [로그아웃]", pg.inner_text("#quit"))
        pg.reload()
        pg.wait_for_function("document.body.innerText.includes('w_new')", timeout=30000)
        check(not pg.query_selector("#login"), "새로고침해도 로그인이 남는다 (총괄이면 다시 묻지 않음)")
        pg.on("dialog", lambda d: d.accept())
        pg.click("#quit")
        pg.wait_for_selector("#login-id", timeout=30000)
        check(True, "[로그아웃] 하면 다시 로그인 화면")
        check(not errors, "화면 스크립트 오류 없음", errors)
        b.close()
except Exception as e:
    check(False, "웹 관리 화면 시험이 끝까지 돌았다", f"{type(e).__name__}: {e}")

print(f"\n{COUNT - len(FAIL)}/{COUNT} 통과")
if FAIL:
    print("실패:", ", ".join(FAIL))
    sys.exit(1)
