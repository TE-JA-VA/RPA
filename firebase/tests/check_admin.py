"""관리 화면(AFTERMARKET_SETUP) 시험 - admin.js 를 에뮬레이터에 붙여 API 와 화면을 본다. 실제 프로젝트는 안 건드린다.

    cd D:\\AX\\RPA\\firebase; . .\\emu_env.ps1; cd tests
    firebase emulators:exec --config ../firebase.json --only auth,database,firestore --project rpa-test-f02e0 "D:\\AX\\RPA\\.venv\\Scripts\\python.exe check_admin.py"

만드는 계정은 에뮬레이터 것이라도 비밀번호를 찍지 않는다 (길이만 보고, 실패 글에서도 가린다).
"""
import atexit
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
PROJECT = "rpa-test-f02e0"
DB = "http://127.0.0.1:9000"
NS = f"{PROJECT}-default-rtdb"
AUTH = "http://127.0.0.1:9099"
FS = f"http://127.0.0.1:8080/v1/projects/{PROJECT}/databases/(default)/documents"
OWNER = {"Authorization": "Bearer owner"}
ADMIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "admin")
LOG = os.path.join(ADMIN, "관리_기록.txt")
FAIL, SECRETS = [], []
COUNT = 0
for k in ("FIREBASE_AUTH_EMULATOR_HOST", "FIREBASE_DATABASE_EMULATOR_HOST", "FIRESTORE_EMULATOR_HOST"):
    if not os.environ.get(k):
        sys.exit(f"{k} 가 없다. emulators:exec 안에서 돌릴 것")


def mask(text):
    text = str(text)
    for s in SECRETS:
        if s:
            text = text.replace(s, "****")
    return re.sub(r"('password': ')[^']+", r"\1****", re.sub(r'("password": ")[^"]+', r"\1****", text))


def check(ok, label, detail=""):
    global COUNT
    COUNT += 1
    print(f"  {'통과' if ok else '실패'}  {label}" + (f"  {mask(detail)}" if detail and not ok else ""))
    if not ok:
        FAIL.append(label)


def call(method, url, body=None, headers=None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read().decode("utf-8")
        return json.loads(raw) if raw else None


def db_get(path):
    return call("GET", f"{DB}/{path}.json?ns={NS}", None, OWNER)


def db_put(path, value):
    return call("PUT", f"{DB}/{path}.json?ns={NS}", value, OWNER)


def account(email_):
    r = call("POST", f"{AUTH}/identitytoolkit.googleapis.com/v1/projects/{PROJECT}/accounts:lookup", {"email": [email_]}, OWNER)
    return (r or {}).get("users", [None])[0] or {}


def claims(email_):
    return json.loads(account(email_).get("customAttributes") or "{}")


def fs_doc(path):
    try:
        d = call("GET", f"{FS}/{path}", None, OWNER)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    return {k: int(v["integerValue"]) if "integerValue" in v else v.get("stringValue") for k, v in (d.get("fields") or {}).items()}


def email(cid, local):
    return f"{local.replace('_', '-')}@{cid.replace('_', '-')}.{PROJECT}.firebaseapp.com"


# --- 서버 켜기 (브라우저 없이) ---
log_start = os.path.getsize(LOG) if os.path.exists(LOG) else 0
srv = subprocess.Popen(["node", "admin.js", "--no-open"], cwd=ADMIN, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       text=True, encoding="utf-8", errors="replace")
atexit.register(lambda: srv.poll() is None and srv.kill())   # 시험이 중간에 죽어도 서버를 남기지 않는다
url = port = key = None
for line in srv.stdout:
    m = re.search(r"http://127\.0\.0\.1:(\d+)/\?k=([\w-]+)", line)
    if m:
        url, port, key = m.group(0), m.group(1), m.group(2)
        break
out_lines = []
threading.Thread(target=lambda: out_lines.extend(srv.stdout), daemon=True).start()   # 서버 출력을 계속 비운다 (막히지 않게)
BASE = f"http://127.0.0.1:{port}"


def api(method, path, body=None, k=None, host=None):
    headers = {"X-Admin-Key": key if k is None else k}
    if host:
        headers["Host"] = host
    try:
        return 200, call(method, BASE + path, body, headers)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or "{}")


print("=== 1. 켜기와 보안 ===")
check(url is not None, "브라우저 없이 켜면 주소(비밀 값 포함)를 찍는다")
code, r = api("GET", "/api/info", k="")
check(code == 403 and "비밀 값" in r.get("error", ""), "비밀 값 없이 /api 를 부르면 거절", (code, r))
code, r = api("GET", "/api/info", k="x" * len(key or ""))
check(code == 403, "비밀 값이 틀려도 거절", code)
code, r = api("GET", "/api/info", host=f"localhost:{port}")
check(code == 403 and "127.0.0.1" in r.get("error", ""), "Host 가 127.0.0.1:<포트> 가 아니면 거절 (주소 이름 위조)", (code, r))
try:   # new URL 이 못 읽는 요청 줄 - 브라우저 fetch 로도 보낼 수 있다. 서버가 죽으면 하던 신규 업체 흐름이 반쪽으로 남는다 (검토 2026-10-06)
    with socket.create_connection(("127.0.0.1", int(port)), timeout=10) as raw:
        raw.sendall(f"GET //[ HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n".encode())
        raw.recv(200)
except OSError:
    pass
try:
    code, r = api("GET", "/api/info")
except urllib.error.URLError as e:
    code, r = None, e
check(code == 200, "이상한 요청 줄(GET //[)을 받아도 서버가 죽지 않는다", (code, r))
page_html = urllib.request.urlopen(BASE + "/", timeout=30).read().decode("utf-8")
check("AFTER MARKET 관리" in page_html and (key or "?") not in page_html, "화면 파일은 비밀 값 없이 내려주고, 그 안에 비밀 값이 없다")
code, r = api("GET", "/api/info")
check(code == 200 and r == {"emulator": True, "project": PROJECT, "dashboard": f"https://{PROJECT}.web.app"}, "에뮬레이터에 붙었다고 알린다", r)

print("=== 2. 신규 업체 (한 흐름) ===")
PLAN = {"cid": "t_new", "name": "<img src=x onerror=alert(1)> 새 업체", "hold": False,
        "pcs": [{"pcId": "pc_a", "label": "사무실 PC"}, {"pcId": "pc_b", "label": "창고 PC"}],
        "users": [{"id": "boss", "name": "대표", "role": "admin"}, {"id": "staff", "name": "직원", "role": "viewer"}],
        "tokens": {"amount": "+500", "memo": "첫 결제"}}
for bad, why in ((dict(PLAN, cid="Net-1"), "업체코드"), ({k: v for k, v in PLAN.items() if k != "hold"}, "물류대기"),
                 (dict(PLAN, pcs=[]), "PC"), (dict(PLAN, users=[{"id": "v", "role": "viewer"}]), "관리자"),
                 (dict(PLAN, tokens={"amount": "1,000"}), "최초 토큰량")):
    code, r = api("POST", "/api/setup", bad)
    check(code == 400 and why in r.get("error", ""), f"잘못된 내용은 만들기 전에 거절: {why}", (code, r))
check(db_get("meta/companies/t_new") is None, "거절된 내용으로는 아무것도 안 만든다")
code, r = api("POST", "/api/setup", PLAN)
made = r.get("made", {}) if code == 200 else {}
SECRETS += [u.get("password", "") for u in made.get("users", [])] + [a.get("password", "") for a in made.get("agents", [])]
check(code == 200 and r["ok"] and len(r["steps"]) == 9 and all(s["ok"] for s in r["steps"]),
      "다 만들었다 (업체·PC 2·계정 2·에이전트 계정 2·물류대기·첫 토큰 = 9 줄)", (code, r.get("steps")))
labels = [x["label"] for x in r.get("steps", [])] if code == 200 else []
check("유저 계정 staff" in labels and "에이전트 계정 pc_a" in labels and "물류대기 관리 메뉴 사용 안 함" in labels and "최초 토큰 500개" in labels
      and not any(w in " ".join(labels) for w in ("열람자", "기계", "첫 토큰", "씀")),
      "단계 이름: 유저 계정·에이전트 계정 (사용자가 고른 이름 2026-10-06)", labels)
check({u["id"] for u in made.get("users", [])} == {"boss", "staff"} and {a["pcId"] for a in made.get("agents", [])} == {"pc_a", "pc_b"}
      and len(SECRETS) == 4 and all(len(s) == 24 for s in SECRETS), "만든 계정의 비밀번호를 한 번 돌려준다 (24자)")
check(claims(email("t_new", "boss")) == {"cid": "t_new", "role": "admin"} and claims(email("t_new", "staff")) == {"cid": "t_new", "role": "viewer"}
      and claims(email("t_new", "agent-pc_a")) == {"cid": "t_new", "pcId": "pc_a", "role": "agent"}, "계정·권한(claim)이 실제로 생겼다")
meta = db_get("meta/companies/t_new") or {}
check(meta.get("name") == PLAN["name"] and set(meta.get("pcs", {})) == {"pc_a", "pc_b"}
      and meta.get("apps", {}).get("rpa", {}).get("modules") == {"Hold": False}, "업체·PC·물류대기 끔 (모듈 정책)", meta)
w = fs_doc("wallet/t_new") or {}
check(w.get("granted") == 500 and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d", w.get("since") or ""), "첫 토큰 500 - 통장과 시작 시각", w)
code, r = api("POST", "/api/setup", dict(PLAN, name="다른 업체", users=[{"id": "newboss", "role": "admin"}], tokens=None))
check(code == 400 and "이미 있는 업체" in r.get("error", "") and (db_get("meta/companies/t_new") or {}).get("name") == PLAN["name"]
      and not account(email("t_new", "newboss")), "이미 있는 업체코드를 다른 이름으로 치면 거절 (그 업체 이름을 안 바꾸고 계정도 안 만든다)", (code, r))

TWICE = dict(PLAN, cid="t_twice", name="두번", pcs=[{"pcId": "pc_1", "label": "PC"}], users=[{"id": "boss", "role": "admin"}],
             tokens={"amount": "100"})
results = [None, None]
threads = [threading.Thread(target=lambda i=i: results.__setitem__(i, api("POST", "/api/setup", TWICE))) for i in (0, 1)]
for t in threads:
    t.start()
for t in threads:
    t.join()
for _, res in results:
    SECRETS += [u["password"] for u in res.get("made", {}).get("users", [])] + [a["password"] for a in res.get("made", {}).get("agents", [])]
w = fs_doc("wallet/t_twice") or {}
check(all(c == 200 for c, _ in results) and w.get("granted") == 100, f"동시에 두 번 눌러도 토큰은 한 번만 ({w.get('granted')})")
late = [res for _, res in results if not res.get("made", {}).get("users")]
check(len(late) == 1 and any("이미 있어 건너뜀" in s["note"] for s in late[0]["steps"])
      and any("이미 토큰 정보가 있어" in s["note"] for s in late[0]["steps"]), "늦은 쪽은 이미 있는 계정·통장을 건너뛴다", late)

subprocess.run(["node", "setup.js", "company", "t_retry", "다시"], cwd=ADMIN, capture_output=True, timeout=60)
code, r = api("POST", "/api/companies/t_retry/users", {"id": "boss", "role": "admin", "name": "먼저"})
SECRETS.append(r.get("password", ""))
code, r = api("POST", "/api/setup", dict(TWICE, cid="t_retry", name="다시", tokens=None))
SECRETS += [a["password"] for a in r.get("made", {}).get("agents", [])]
check(code == 200 and r["ok"] and not r["made"]["users"] and [a["pcId"] for a in r["made"]["agents"]] == ["pc_1"]
      and any("boss" in s["label"] and "재발급" in s["note"] for s in r["steps"]), "다시 누르면 남은 것만 (이미 있는 계정은 건너뛰고 재발급 안내)", r.get("steps"))
check(fs_doc("wallet/t_retry") is None, "첫 토큰을 '나중에' 로 하면 통장 없이 (세기만)")

print("=== 3. 업체 표·상세 ===")
code, rows = api("GET", "/api/companies")
row = next((x for x in rows if x["cid"] == "t_new"), {}) if code == 200 else {}
check(row.get("pcs") == 2 and row.get("users") == 4 and row.get("left") == 500 and row.get("month") == 0 and row.get("stts") == 0,
      "업체 표: PC 2 · 계정 4 · 남은 500 · 이번 달 0", row)
code, d = api("GET", "/api/companies/t_new")
check(code == 200 and {u["role"] for u in d["users"]} == {"admin", "viewer", "agent"} and d["modules"] == {"Hold": False}
      and d["tokens"]["granted"] == 500 and d["tokens"]["grants"][0]["memo"] == "첫 결제", "상세: 계정·역할·모듈·통장·넣은 내역", str(d)[:300])
code, r = api("POST", "/api/companies/t_new/tokens", {"amount": "+100", "memo": "추가"})
check(code == 200 and r["wallet"]["left"] == 600 and not r["created"], "토큰 더 넣기 → 남은 600", str(r)[:200])
code, r = api("POST", "/api/companies/t_new/tokens", {"amount": "1,000"})
check(code == 400 and "0 이 아닌 정수" in r.get("error", ""), "토큰 수 '1,000' 은 거절 (쉼표)", r)
boss = email("t_new", "boss")
code, r = api("POST", "/api/companies/t_new/passwd", {"id": boss})
SECRETS.append(r.get("password", ""))
check(code == 200 and len(r.get("password", "")) == 24 and r.get("email") == boss, "비밀번호 재발급 (새 값을 한 번 돌려준다)")
code, r = api("POST", "/api/companies/t_new/disabled", {"id": boss, "disabled": True})
check(code == 200 and account(boss).get("disabled") is True, "계정 막기")
code, r = api("POST", "/api/companies/t_new/disabled", {"id": boss, "disabled": False})
check(code == 200 and account(boss).get("disabled") is not True, "계정 다시 열기")
code, r = api("POST", "/api/companies/t_new/modules", {"Hold": "on"})
check(code == 200 and (db_get("meta/companies/t_new/apps/rpa/modules") or {}) == {}, "모듈 정책 켜기 (정책을 지운다 = 그 업체가 쓴다)")
code, d = api("GET", "/api/companies/t_new")
check(code == 200 and d.get("scheduleLimit") is None, "자동 실행 개수: 값이 없으면 null (화면은 기본 2)", str(d.get("scheduleLimit")))
code, r = api("POST", "/api/companies/t_new/limits", {"schedule": "3"})
check(code == 200 and r == {"cid": "t_new", "schedule": 3} and db_get("meta/companies/t_new/apps/rpa/limits/schedule") == 3, "자동 실행 개수 3", r)
for bad in ("13", "-1", "2.5", "", "셋"):
    code, r = api("POST", "/api/companies/t_new/limits", {"schedule": bad})
    check(code == 400 and "0~12" in r.get("error", "") and db_get("meta/companies/t_new/apps/rpa/limits/schedule") == 3, f"자동 실행 개수 거절 {bad!r}", r)
code, r = api("POST", "/api/companies/t_new/remove", {"confirm": "t_ne"})
check(code == 400 and db_get("meta/companies/t_new/stts") == 0, "업체코드를 똑같이 안 치면 삭제하지 않는다", (code, r))
code, r = api("POST", "/api/companies/t_new/remove", {"confirm": "t_new"})
check(code == 200 and db_get("meta/companies/t_new/stts") == 9 and account(boss).get("disabled") is True, "업체 삭제: stts 9, 계정 막힘")
code, r = api("POST", "/api/companies/t_new/restore", {})
check(code == 200 and db_get("meta/companies/t_new/stts") == 0 and account(boss).get("disabled") is not True, "되살림")
code, r = api("POST", "/api/prices", {"key": "logistics", "value": "3"})
check(code == 200 and r.get("logistics") == 3 and r.get("login") == 0, "토큰 배율 바꾸기", r)
code, r = api("POST", "/api/prices", {"key": "logistics", "value": "-1"})
check(code == 400 and "토큰 배율" in r.get("error", ""), "토큰 배율 음수는 거절", r)
code, rows = api("GET", "/api/usage")
check(code == 200 and any(x["cid"] == "t_new" and x["left"] == 600 for x in rows), "통계: 업체마다 남은 토큰", str(rows)[:200])
code, r = api("GET", "/api/companies/Bad")
check(code == 404, "업체코드 꼴이 아닌 주소는 없는 요청", code)

print("=== 4. 화면 (Playwright headless) ===")
from playwright.sync_api import sync_playwright  # noqa: E402

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page()
    dialogs = []
    page.on("dialog", lambda d: (dialogs.append(d.message), d.accept()))
    page.goto(url)
    page.wait_for_function("document.getElementById('badge')?.textContent.includes('에뮬레이터')", timeout=15000)
    check(page.text_content("#badge") == "에뮬레이터 (시험)" and "k=" not in page.url, "띠에 '에뮬레이터 (시험)', 주소창에서 비밀 값을 지운다", page.url)
    page.wait_for_selector("#companies tr[data-cid='t_new']", timeout=15000)
    cell = page.text_content("#companies tr[data-cid='t_new'] td:nth-child(2)")
    check(cell == PLAN["name"] and "1" not in dialogs and page.locator("#companies img").count() == 0,
          "업체 이름에 넣은 HTML 은 글자 그대로 (스크립트로 안 돈다)", cell)
    page.click("#companies tr[data-cid='t_new']")
    page.wait_for_function("document.querySelector('#detail table.wallet td.left')?.textContent === '600'", timeout=15000)
    check(True, "줄을 누르면 상세: 현재 토큰 600")
    heads = [h.strip() for h in page.locator("#detail table.wallet th").all_text_contents()]
    check(heads == ["발급한 토큰", "사용한 토큰", "현재 토큰", "토큰 정보 생성"], f"토큰 정보는 표로 ({heads})")
    OLD = ("기계", "열람자", "통장", "막기", "막힘", "막을", "막았", "열기", "열림", "열었", "더하기", "더했", "삭제", "되살",
           "한 대 더", "쓰나요", "예, 씁니다", "첫 토큰", "세기만", "관리자 계정 (대시보드에 로그인할 사람)", "유저 추가")
    NEW = ("에이전트 계정도 만들기", "PC 추가", '"추가"', "사용중지", "사용중", "유저", "토큰 정보", "업체 비활성화", "다시 활성화",
           '<button id="s-add-pc">+ 추가</button>', "4. 물류대기 관리 메뉴 사용 여부", 'value="yes">예</label>', 'value="no">아니오</label>',
           "5. 최초 토큰량 설정", 'value="later" checked>나중에 설정</label>', "3. 대시보드 계정", '<button id="s-add-user">+ 추가</button>',
           "업체가 보유한 토큰 정보가 없습니다. 최초 토큰 생성시 토큰 정보가 함께 생성됩니다. 토큰이 0이하라면 모듈 실행을 막습니다.",
           "업체가 사용할 모듈을 결정합니다. 체크 해제시 업체 대시보드에서 보이지 않고, 에이전트도 실행하지 않습니다.",
           "이 업체를 비활성화 합니다. 데이터(기록, 토큰 정보 등)도 남고, 언제든지 다시 활성화 할 수 있습니다.")
    shown = page_html + page.text_content("body")
    check(not [w for w in OLD if w in shown] and all(w in shown for w in NEW),
          "화면 이름은 사용자가 고른 것 (에이전트·유저·사용중지/사용·추가·토큰 정보·업체 비활성화 - 2026-10-06)",
          ([w for w in OLD if w in shown], [w for w in NEW if w not in shown]))
    page.fill("#detail input[placeholder^='+1000']", "+50")
    page.fill("#detail input[placeholder^='비고']", "화면에서")
    page.click("#detail button:has-text('넣기')")
    page.wait_for_function("document.querySelector('#detail table.wallet td.left')?.textContent === '650'", timeout=15000)
    check(True, "화면에서 토큰 넣기 → 현재 토큰 650")
    page.fill("#detail input[aria-label='자동 실행 슬롯 수']", "4")
    page.click("#detail .row:has(input[aria-label='자동 실행 슬롯 수']) button")
    page.wait_for_function("document.querySelector(\"#detail input[aria-label='자동 실행 슬롯 수']\")?.value === '4'", timeout=10000)
    check(db_get("meta/companies/t_new/apps/rpa/limits/schedule") == 4, "화면: 업체 상세에서 자동 실행 개수 저장")

    print("자동 업데이트 (설계 8절)")
    CID, PC = "t_new", "pc_a"
    db_put("meta/releases", {"list": {"2026_10_07-4": {"version": "2026.10.07-4", "published_at": "2026-10-07T12:00:00", "bytes": 1, "memo": "안정"},
                                      "2026_10_07-5": {"version": "2026.10.07-5", "published_at": "2026-10-07T13:00:00", "bytes": 1, "memo": "새"}},
                             "stable": "2026.10.07-4", "newest": "2026.10.07-5"})
    db_put(f"apps/rpa/live/{CID}/{PC}", {"version": {"version": "2026.10.07-4", "state": "ok"},
                                          "update": {"state": "done", "target": "2026.10.07-4", "from": "2026.10.07-3", "at": "2026-10-07T14:03:00", "backup": "2026.10.07-3"}})

    def open_company(pg, cid):
        pg.click("nav button[data-view='companies']")
        pg.wait_for_timeout(1000)   # 앞서 늦게 도착하는 상세 응답이 새 그림을 덮지 않게
        pg.evaluate("document.getElementById('detail').replaceChildren()")   # 옛 상세를 비워야 새로 그린 줄을 기다린다
        pg.click(f"#companies tr[data-cid='{cid}']")
        pg.wait_for_selector(f"#detail #pc-{PC}", timeout=15000)

    open_company(page, CID)
    heads = [h.strip() for h in page.locator("#detail table.pcs th").all_text_contents()]
    check(heads == ["PC 이름", "PC코드", "버전", "업데이트 상태", "업데이트"], f"PC 는 표로 - 칸이 맞춰진다 ({heads})")
    cells = [c.strip() for c in page.locator(f"#pc-{PC} td").all_text_contents()]
    check(cells[1] == PC and cells[2] == "2026.10.07-4 (안정본)" and cells[3] == "업데이트됨 10/7 14:03", f"PC 줄 칸: 코드·버전·상태 ({cells})")
    check(page.input_value(f"#pc-{PC} select.upd-ver") == "2026.10.07-4"
          and "(최신본)" in page.text_content(f"#pc-{PC} select.upd-ver option[value='2026.10.07-5']"), "판 고르기: 처음은 안정본, 최신본 표시")
    page.select_option(f"#pc-{PC} select.upd-ver", "2026.10.07-5")
    dialogs.clear()   # 위쪽 page.on("dialog") 가 이미 모두 받아들인다
    page.click(f"#pc-{PC} button.upd-go")
    page.wait_for_timeout(800)
    cmd = [v for v in (db_get(f"apps/rpa/commands/{CID}/{PC}") or {}).values() if v.get("type") == "update"]
    check(dialogs == [f"{CID} / {PC} 를 2026.10.07-5 로 바꿉니다. RPA 가 끝나면 바로 바뀝니다."], f"확인 창 ({dialogs})")
    check(len(cmd) == 1 and cmd[0]["args"] == {"version": "2026.10.07-5"} and cmd[0]["by"] == "admin-tool" and cmd[0]["state"] == "queued"
          and cmd[0]["expires_at"] - cmd[0]["created_at"] == 600, f"update 명령 ({cmd})")
    check(page.is_visible(f"#pc-{PC} button.upd-back") and "2026.10.07-3" in page.text_content(f"#pc-{PC} button.upd-back"), "보관본이 있으면 되돌리기 단추")
    page.click(f"#pc-{PC} button.upd-back")
    page.wait_for_timeout(800)
    check(any(v.get("type") == "rollback" and v["by"] == "admin-tool" and v["state"] == "queued"
              for v in (db_get(f"apps/rpa/commands/{CID}/{PC}") or {}).values()), "되돌리기 명령")
    code, r = api("POST", f"/api/companies/{CID}/pcs/{PC}/update", {"version": "2026.10.07-9"})
    check(code == 400, "올라가 있지 않은 판은 거절", r)
    db_put(f"apps/rpa/live/{CID}/{PC}/update", {"state": "waiting", "target": "2026.10.07-5", "from": "2026.10.07-4", "at": "2026-10-07T15:00:00", "backup": "2026.10.07-3"})
    open_company(page, CID)
    check(page.is_disabled(f"#pc-{PC} button.upd-go") and page.is_disabled(f"#pc-{PC} button.upd-back")
          and "업데이트 대기 중" in page.text_content(f"#pc-{PC}"), "진행 중이면 두 단추 잠금")
    page.click("#releases-open")
    page.click("#releases button[data-stable='2026.10.07-5']")
    page.wait_for_timeout(800)
    check(db_get("meta/releases/stable") == "2026.10.07-5", "판 목록에서 안정본으로 지정")
    check("안정본 지정 2026.10.07-5" in open(LOG, encoding="utf-8").read(), "관리 기록에 남는다")

    print("화면 다듬기 (사용자 2026-10-07)")
    check("지금은 기본값" not in page.text_content("#detail"), "자동 실행 개수: '지금은 기본값' 글 없음")
    hold0 = page.is_checked("#detail input[data-mod='Hold']")
    page.evaluate("document.getElementById('flash').classList.add('hide')")
    before = db_get(f"meta/companies/{CID}/apps/rpa/modules") or {}
    page.click("#detail input[data-mod='Hold']")
    page.wait_for_timeout(800)
    check((db_get(f"meta/companies/{CID}/apps/rpa/modules") or {}) == before, "모듈 정책: 체크만으로는 안 바뀐다 ([적용] 을 눌러야)")
    page.click("#detail button.mod-apply")
    page.wait_for_selector("#detail .mod-ok:not(.hide)", timeout=5000)
    mods = db_get(f"meta/companies/{CID}/apps/rpa/modules") or {}
    check(page.text_content("#detail .mod-ok").strip() == "반영되었습니다." and (mods.get("Hold") is False) == hold0
          and "hide" in (page.get_attribute("#flash", "class") or ""), f"[적용] → 제목 옆 초록 '반영되었습니다.' (아래 알림 없음) ({mods})")
    page.wait_for_selector("#detail .mod-ok.hide", state="attached", timeout=5000)
    check(True, "초록 글은 잠깐 뒤 사라진다")
    check("자동 실행 슬롯 수" in page.text_content("#detail") and "자동 실행 개수" not in page.text_content("#detail"), "자동 실행 슬롯 수 (이름)")
    check("예약 실행, 반복 실행 슬롯을 몇 개까지 열어줄 지 결정합니다. (0~12, 기본 2)" in page.text_content("#detail"), "자동 실행 슬롯 수 설명")
    page.click("#detail input[data-mod='Hold']")   # 되돌려 둔다
    page.click("#detail button.mod-apply")
    page.wait_for_timeout(800)
    api("POST", f"/api/companies/{CID}/tokens", {"amount": 1500, "memo": "보기 시험"})
    api("POST", f"/api/companies/{CID}/tokens", {"amount": -50, "memo": "보기 시험 빼기"})
    open_company(page, CID)
    heads = [h.strip() for h in page.locator("#detail table.grants th").all_text_contents()]
    check(heads == ["날짜", "토큰량", "비고"], f"토큰 내역 머리 ({heads})")
    amt = page.evaluate("""[...document.querySelectorAll('#detail table.grants td.num')].map((td) => [td.textContent.trim(), getComputedStyle(td).color])""")
    good, bad = page.evaluate("[getComputedStyle(document.body).getPropertyValue('--good').trim(), getComputedStyle(document.body).getPropertyValue('--bad').trim()]")
    plus = [c for t, c in amt if t == "+1,500"]
    minus = [c for t, c in amt if t == "-50"]
    check(plus and minus and plus[0] != minus[0] and plus[0] != page.evaluate("getComputedStyle(document.body).color"),
          f"토큰량: 1000 단위 콤마, + 초록·- 빨강 ({amt}, good {good}, bad {bad})")
    sec = page.evaluate("""[...document.querySelectorAll('#detail .sec')].map((s) => {
        const c = getComputedStyle(s); return [parseFloat(c.borderLeftWidth), c.backgroundColor, c.borderTopColor, parseFloat(c.borderTopLeftRadius)]; })""")
    card = page.evaluate("getComputedStyle(document.getElementById('detail')).backgroundColor")
    row_line = page.evaluate("getComputedStyle(document.querySelector('#detail table td')).borderBottomColor")
    check(len(sec) >= 6 and all(w >= 1 and bg != card and r > 0 for w, bg, _, r in sec) and sec[1][2] != row_line and sec[-1][2] != sec[1][2],
          f"상세 항목마다 상자 (바탕이 카드와 다르고, 테두리는 표 줄보다 진하게, 비활성화는 빨간 테두리) ({sec}, card {card}, row {row_line})")
    crow = page.text_content(f"#companies tr[data-cid='{CID}']")
    check("현재 토큰" in page.text_content("table:has(#companies) thead") and re.search(r"\d,\d{3}", crow), f"업체 표: 현재 토큰, 1000 단위 콤마 ({crow})")
    ph = page.get_attribute("#detail .sec.danger input", "placeholder")
    check(ph == CID, f"업체 비활성화 칸 안내 글은 업체코드만 (길면 잘림) ({ph})")
    nav = page.text_content("nav")
    check("신규 업체 등록" in nav and "토큰 배율·통계" in nav, f"위 메뉴 글 ({nav})")
    check(page.text_content("#releases-open").strip() == "버전 목록", "버전 목록 단추")
    heads = [h.strip() for h in page.locator("#releases th").all_text_contents()]
    check(heads[:5] == ["버전", "업데이트 날짜", "크기(MB)", "비고", "버전 특이사항"], f"버전 목록 머리 ({heads})")
    gap = page.evaluate(f"""(() => {{ const s = document.querySelector('#pc-{PC} select.upd-ver').getBoundingClientRect(),
        b = document.querySelector('#pc-{PC} button.upd-go').getBoundingClientRect(); return b.left - s.right; }})()""")
    check(6 <= gap <= 12, f"PC 줄 고르기·단추 사이가 아래 줄처럼 8px 남짓 ({gap}px)")
    prefs = os.path.join(ADMIN, "admin_prefs.json")
    prefs_before = open(prefs, encoding="utf-8").read() if os.path.exists(prefs) else None
    try:
        theme = lambda: page.evaluate("document.documentElement.dataset.theme || ''")
        bg = lambda: page.evaluate("getComputedStyle(document.body).backgroundColor")
        t0, bg0 = theme(), bg()
        page.click("#theme")
        page.wait_for_timeout(500)
        t1 = theme()
        check(t1 in ("light", "dark") and t1 != t0 and bg() != bg0, f"[테마] 단추로 밝게/어둡게 ({t0!r} → {t1!r})")
        check(page.text_content("#theme").strip() == ("☀ 밝게" if t1 == "dark" else "☾ 어둡게"), "단추 글은 바꿀 쪽")
        page.reload()
        page.wait_for_function(f"document.documentElement.dataset.theme === '{t1}'", timeout=10000)
        check(True, "다시 열어도 고른 테마 (포트가 바뀌어도 - 관리 도구 옆 파일에 남긴다)")
    finally:
        if prefs_before is None:
            if os.path.exists(prefs):
                os.remove(prefs)
        else:
            open(prefs, "w", encoding="utf-8").write(prefs_before)

    page.click("nav button[data-view='setup']")
    page.fill("#s-tok-amount", "100000")
    page.focus("#s-tok-memo")
    shown = page.input_value("#s-tok-amount")
    page.focus("#s-tok-amount")
    check(shown == "100,000" and page.input_value("#s-tok-amount") == "100000", f"최초 토큰량: 칸을 벗어나면 콤마, 다시 들어오면 콤마 없이 ({shown})")
    check(page.get_attribute("#s-tok-memo", "placeholder").startswith("비고"), "최초 토큰량 옆 칸은 비고")
    page.fill("#s-tok-amount", "")
    page.fill("#s-cid", "t_ui")
    page.fill("#s-name", "화면 업체")
    page.fill("#s-pcs .pc-id", "pc_ui")
    page.fill("#s-pcs .pc-label", "화면 PC")
    page.fill("#s-users .acct:nth-child(1) .u-id", "ui_admin")
    page.fill("#s-users .acct:nth-child(1) .u-name", "담당")
    page.click("#s-add-user"); page.click("#s-add-user")
    roles = [page.input_value(f"#s-users .acct:nth-child({i}) .u-role") for i in (1, 2, 3)]
    check(roles == ["admin", "viewer", "viewer"], f"계정 줄마다 역할 - 첫 줄은 관리자, + 추가 한 줄은 유저로 시작 ({roles})")
    page.fill("#s-users .acct:nth-child(2) .u-id", "ui_boss2")
    page.select_option("#s-users .acct:nth-child(2) .u-role", "admin")
    page.fill("#s-users .acct:nth-child(3) .u-id", "ui_view")
    page.check("input[name=tok][value=later]")
    page.click("#s-make")
    page.wait_for_function("document.getElementById('flash')?.textContent.includes('물류대기')", timeout=15000)
    check(db_get("meta/companies/t_ui") is None, "물류대기 사용 여부를 안 고르면 빨간 알림, 아무것도 안 만든다")
    page.check("input[name=hold][value=yes]")
    page.click("#s-make")
    page.wait_for_selector("#setup-result:not(.hide) .secret pre", timeout=30000)
    sent = page.text_content("#setup-result .secret pre")
    seen = re.findall(r"비밀번호: (\S{24})", sent)
    SECRETS.extend(seen)
    check(page.text_content("#setup-result h2") == "다 만들었습니다" and "관리자  업체코드: t_ui   아이디: ui_admin" in sent
          and "관리자  업체코드: t_ui   아이디: ui_boss2" in sent and "유저  업체코드: t_ui   아이디: ui_view" in sent
          and "업체코드: t_ui   PC코드: pc_ui" in sent and len(seen) == 4 and f"https://{PROJECT}.web.app" in sent,
          "다 만들면 고객에게 보낼 정보 (대시보드 주소·관리자 둘·유저·에이전트 계정)", sent)
    check(claims(email("t_ui", "ui_admin")) == {"cid": "t_ui", "role": "admin"} and claims(email("t_ui", "ui_boss2")) == {"cid": "t_ui", "role": "admin"}
          and claims(email("t_ui", "ui_view")) == {"cid": "t_ui", "role": "viewer"} and (db_get("meta/companies/t_ui/apps/rpa/modules") or {}) == {},
          "화면으로 만든 업체: 고른 역할대로 관리자 둘·유저 하나, 물류대기 씀 (정책 없음)")

    page.click("nav button[data-view='rates']")
    page.wait_for_selector("#rates tr", timeout=15000)
    rate = page.locator("#rates tr", has_text="주문매핑 매출처리")
    rate.locator("input").fill("2")
    rate.locator("button").click()
    page.wait_for_function("document.getElementById('flash')?.textContent.includes('배율')", timeout=15000)
    check((fs_doc("meta/prices") or {}).get("sales") == 2, "토큰 배율 화면에서 바꾸기 (sales 2)")
    check(page.locator("#usage tr", has_text="t_new").count() == 1, "통계 표에 업체가 나온다")
    rh = [h.strip() for h in page.locator("#view-rates table").first.locator("th").all_text_contents()]
    uh = [h.strip() for h in page.locator("#view-rates table").nth(1).locator("th").all_text_contents()]
    check("키" not in rh and rh[:2] == ["모듈", "배율"], f"토큰 배율 표: 키 칸 없음 ({rh})")
    check("현재 토큰" in uh and "이번 달 사용한 토큰" in uh, f"통계 표 머리 ({uh})")

    old = browser.new_page()
    old.goto(f"{BASE}/?k={'x' * len(key)}")
    old.wait_for_function("document.getElementById('badge')?.textContent === '연결 안 됨'", timeout=15000)
    check("다시 켜세요" in old.text_content("#flash"), "비밀 값이 틀린 화면(옛 주소)은 '다시 켜세요' 를 알린다")

    LATE = dict(PLAN, cid="t_late", name="끄기 직전", pcs=[{"pcId": f"pc_{i}", "label": f"PC {i}"} for i in range(1, 31)],
                users=[{"id": "boss", "role": "admin"}], tokens={"amount": "7"})
    late = []
    worker = threading.Thread(target=lambda: late.append(api("POST", "/api/setup", LATE)))
    worker.start()
    for _ in range(1000):   # 첫 단계(업체)가 끝나 흐름이 한창 돌 때 [끄기] - PC 30대·에이전트 계정 30개가 남아 있다
        if db_get("meta/companies/t_late"):
            break
        time.sleep(0.01)
    page.click("#quit")
    worker.join(timeout=60)
    srv.wait(timeout=15)
    browser.close()
    done = late[0][1] if late and late[0][0] == 200 else {}
    SECRETS += [u["password"] for u in done.get("made", {}).get("users", [])] + [a["password"] for a in done.get("made", {}).get("agents", [])]
    check(done.get("ok") and len(done.get("made", {}).get("agents", [])) == 30 and (fs_doc("wallet/t_late") or {}).get("granted") == 7,
          "[만들기] 바로 뒤 [끄기] 를 눌러도 하던 일을 끝내고 끈다", late[0][0] if late else "응답 없음 (중간에 꺼짐)")

print("=== 5. 기록 ===")
if srv.poll() is None:
    code, r = api("POST", "/api/quit")
    srv.wait(timeout=15)
text = open(LOG, "rb").read()[log_start:].decode("utf-8") if os.path.exists(LOG) else ""
check("신규 업체 t_new" in text and "토큰 +100 t_new 추가" in text and "비밀번호 재발급 t_new" in text and "업체 비활성화 t_new" in text,
      "관리_기록.txt 에 한 일이 한 줄씩", text[-400:])
check(SECRETS and all(SECRETS) and not any(s in text for s in SECRETS) and not any(s in "".join(out_lines) for s in SECRETS),
      "기록 파일·서버 출력 어디에도 비밀번호가 없다")
check(0 <= text.find("신규 업체 t_late") < text.rfind("관리 화면 끔"), "끄기는 하던 일(신규 업체 t_late)이 끝난 뒤에 (기록 차례)", text[-300:])
check(srv.returncode == 0, "[끄기](/api/quit) 로 서버가 끝난다", srv.returncode)
if srv.poll() is None:
    srv.kill()
print(f"\n{COUNT - len(FAIL)}/{COUNT} 통과")
if FAIL:
    print("실패:", ", ".join(FAIL))
    sys.exit(1)
