"""화면 시험 (Playwright + 에뮬레이터). 실제 프로젝트를 건드리지 않는다.

실행 (firebase/tests 에서, emu_env.ps1 을 읽은 창):
  firebase emulators:exec --config ../firebase.json --only auth,database,hosting --project rpa-test-f02e0 "python check_web.py"

에뮬레이터 REST 는 'Authorization: Bearer owner' 로 규칙을 우회한다 (시드용).
"""
import json
import sys
import time
import urllib.request

PROJECT = "rpa-test-f02e0"
DB = f"http://127.0.0.1:9000"
NS = f"{PROJECT}-default-rtdb"
AUTH = "http://127.0.0.1:9099"
WEB = "http://127.0.0.1:5000/?emu=1"
OWNER = {"Authorization": "Bearer owner"}

FAIL = []
COUNT = 0


def check(ok, label):
    global COUNT
    COUNT += 1
    print(f"  {'통과' if ok else '실패'}  {label}")
    if not ok:
        FAIL.append(label)


def call(method, url, body=None, headers=None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=15) as r:
        raw = r.read().decode("utf-8")
        return json.loads(raw) if raw else None


def db_put(path, value):
    return call("PUT", f"{DB}/{path}.json?ns={NS}", value, OWNER)


def db_get(path):
    return call("GET", f"{DB}/{path}.json?ns={NS}", None, OWNER)


def make_user(email, password, claims):
    r = call("POST", f"{AUTH}/identitytoolkit.googleapis.com/v1/accounts:signUp?key=emu",
             {"email": email, "password": password, "returnSecureToken": True})
    call("POST", f"{AUTH}/identitytoolkit.googleapis.com/v1/projects/{PROJECT}/accounts:update",
         {"localId": r["localId"], "customAttributes": json.dumps(claims)}, OWNER)
    return r["localId"]


# --- 시드 ------------------------------------------------------------------
admin_uid = make_user("admin@t.local", "pw123456", {"cid": "c_demo", "role": "admin"})
viewer_uid = make_user("viewer@t.local", "pw123456", {"cid": "c_demo", "role": "viewer"})
db_put("meta/companies/c_demo", {"name": "시연 회사", "pcs": {"pc_office": {"label": "사무실 PC"}}})
db_put("live/c_demo/pc_office", {
    "host": "OFFICE-PC",
    "heartbeat": {"at": int(time.time()), "host": "OFFICE-PC", "rpa_running": False},
    "programs": {
        "routine": {"state": "success", "steps_done": 3, "steps_total": 3,
                    "steps": [{"key": "login", "label": "로그인", "state": "done"},
                              {"key": "hold", "label": "물류대기 관리", "state": "done"},
                              {"key": "output", "label": "운송장 출력", "state": "done"}]},
        "prepare": None,
    },
    # PC 가 올리는 실제 실행 모듈 - 화면의 기준값
    "modules": {"Login": True, "Sales": False, "Hold": True, "Logistics": True, "Output": True},
})
db_put("settings/c_demo/pc_office", {"modules": {"Login": True, "Sales": False, "Hold": True,
                                                 "Logistics": True, "Output": True},
                                     "updated_by": admin_uid, "updated_at": int(time.time())})
print("시드 완료")

from playwright.sync_api import sync_playwright  # noqa: E402


def login(page, email):
    page.goto(WEB)
    page.wait_for_selector("#login:not(.hide)")
    page.fill("#email", email)
    page.fill("#password", "pw123456")
    page.click("#login-btn")
    page.wait_for_selector("#main:not(.hide)", timeout=15000)


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    print("1절 로그인")
    page.goto(WEB)
    page.wait_for_selector("#login:not(.hide)")
    page.fill("#email", "admin@t.local")
    page.fill("#password", "틀린비밀번호")
    page.click("#login-btn")
    page.wait_for_selector("#login-alert:not(.hide)")
    check("맞지 않습니다" in page.text_content("#login-alert"), "틀린 비밀번호 안내")

    page.fill("#password", "pw123456")
    page.click("#login-btn")
    page.wait_for_selector("#main:not(.hide)", timeout=15000)
    check("(관리자)" in page.text_content("#who"), "관리자로 표시")
    check(page.input_value("#password") == "", "비밀번호 칸을 비운다")

    print("2절 현황")
    page.wait_for_function("document.getElementById('conn').textContent === '연결됨'", timeout=10000)
    check(True, "heartbeat 가 최근이면 연결됨")
    check("3/3 단계" in page.text_content("#routine"), "루틴 단계 수")
    check("성공" in page.text_content("#routine"), "루틴 상태")
    check("기록 없음" in page.text_content("#prepare"), "프리페어 없음")
    check(page.is_hidden("#pc-pick"), "PC 가 하나면 고르기 숨김")
    page.wait_for_function("document.getElementById('mod-meta').textContent === '4/5 켬'", timeout=10000)
    check(True, "실행 모듈 요약 4/5")
    check(page.is_disabled("#mod-apply"), "바뀐 게 없으면 적용 비활성")
    check(not page.is_disabled("#run-routine"), "관리자는 실행 버튼 활성")

    print("3절 명령 투입")
    page.click("#run-routine")
    page.wait_for_selector("#act-alert:not(.hide)")
    check("보냈습니다" in page.text_content("#act-alert"), "보냈다는 안내")
    time.sleep(1.0)
    cmds = db_get("commands/c_demo/pc_office") or {}
    check(len(cmds) == 1, "명령이 하나 만들어졌다")
    c = next(iter(cmds.values())) if cmds else {}
    check(c.get("type") == "launch" and c.get("state") == "queued" and c.get("by") == admin_uid,
          "launch / queued / by=관리자 uid")
    check(c.get("args", {}).get("target") == "routine", "대상 routine")
    check(590 <= c.get("expires_at", 0) - c.get("created_at", 0) <= 610, "만료 10분")
    check(page.is_disabled("#run-routine"), "응답 대기 중에는 버튼 잠금")

    # 에이전트 역할을 대신해 done 으로 옮긴다
    key = next(iter(cmds))
    call("PATCH", f"{DB}/commands/c_demo/pc_office/{key}.json?ns={NS}",
         {"state": "done", "result": "루틴 RPA 을(를) 띄웠습니다", "started_at": 1, "ended_at": 2}, OWNER)
    page.wait_for_function("document.getElementById('act-alert').textContent.includes('띄웠습니다')", timeout=10000)
    check(True, "done 이 되면 결과 문장이 보인다")
    page.wait_for_function("!document.getElementById('run-routine').disabled", timeout=5000)
    check(True, "끝나면 버튼이 풀린다")

    print("4절 실행 모듈")
    page.click("#mod-list input[aria-label='주문매핑 매출처리']")
    check("5/5 켬" in page.text_content("#mod-meta"), "스위치를 켜면 요약이 바뀐다")
    check(not page.is_disabled("#mod-apply"), "바뀌면 적용 활성")
    page.click("#mod-apply")
    time.sleep(1.5)
    s = db_get("settings/c_demo/pc_office")
    check(s and s["modules"]["Sales"] is True and s["updated_by"] == admin_uid, "settings 에 저장")
    cmds = db_get("commands/c_demo/pc_office") or {}
    mods = [v for v in cmds.values() if v.get("type") == "set_modules"]
    check(len(mods) == 1 and mods[0]["args"]["Sales"] is True, "set_modules 명령을 보낸다")

    print("5절 열람자")
    page.click("#logout-btn")
    page.wait_for_selector("#login:not(.hide)")
    login(page, "viewer@t.local")
    check("(열람)" in page.text_content("#who"), "열람자로 표시")
    page.wait_for_function("document.getElementById('conn').textContent === '연결됨'", timeout=10000)
    check(page.is_disabled("#run-routine") and page.is_disabled("#stop-erpia"), "열람자는 버튼 비활성")
    page.wait_for_selector("#mod-list input")
    check(page.is_disabled("#mod-list input[aria-label='로그인']"), "열람자는 스위치 비활성")
    # 규칙이 막는지: 화면을 우회해 직접 쓴다
    denied = page.evaluate("""async () => {
      const m = await import('https://www.gstatic.com/firebasejs/10.14.1/firebase-database.js');
      const a = await import('https://www.gstatic.com/firebasejs/10.14.1/firebase-app.js');
      const db = m.getDatabase(a.getApp());
      try { await m.push(m.ref(db, 'commands/c_demo/pc_office'), {type:'launch', by:'x', created_at:1, expires_at:2, state:'queued'}); return 'ok'; }
      catch (e) { return e.code || String(e); }
    }""")
    check(denied == "PERMISSION_DENIED", f"열람자가 우회해 써도 규칙이 거부 ({denied})")

    check(not errors, f"페이지 오류 없음 {errors[:2]}")
    browser.close()

print(f"\n{COUNT - len(FAIL)}/{COUNT} 통과")
if FAIL:
    print("실패:", ", ".join(FAIL))
    sys.exit(1)
