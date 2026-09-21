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
DB = "http://127.0.0.1:9000"
NS = f"{PROJECT}-default-rtdb"
AUTH = "http://127.0.0.1:9099"
WEB = "http://127.0.0.1:5000/?emu=1"
OWNER = {"Authorization": "Bearer owner"}
LIVE = "apps/rpa/live/c_demo/pc_office"
CMDS = "apps/rpa/commands/c_demo/pc_office"
SETTINGS = "apps/rpa/settings/c_demo/pc_office"

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


def db_patch(path, value):
    return call("PATCH", f"{DB}/{path}.json?ns={NS}", value, OWNER)


def db_get(path):
    return call("GET", f"{DB}/{path}.json?ns={NS}", None, OWNER)


def make_user(email, password, claims):
    r = call("POST", f"{AUTH}/identitytoolkit.googleapis.com/v1/accounts:signUp?key=emu",
             {"email": email, "password": password, "returnSecureToken": True})
    call("POST", f"{AUTH}/identitytoolkit.googleapis.com/v1/projects/{PROJECT}/accounts:update",
         {"localId": r["localId"], "customAttributes": json.dumps(claims)}, OWNER)
    return r["localId"]


def sign_in(email, password):
    try:
        call("POST", f"{AUTH}/identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=emu",
             {"email": email, "password": password, "returnSecureToken": True})
        return True
    except urllib.error.HTTPError:
        return False


# --- 시드 (9/14 시뮬레이션 값) ------------------------------------------------
NOW = int(time.time())
TODAY = time.strftime("%Y-%m-%d")
admin_uid = make_user("admin@t.local", "pw123456", {"cid": "c_demo", "role": "admin"})
viewer_uid = make_user("viewer@t.local", "pw123456", {"cid": "c_demo", "role": "viewer"})
db_put("meta/companies/c_demo", {"name": "시연 회사", "pcs": {"pc_office": {"label": "사무실 PC"}}})
routine = {
    "program": "routine", "program_label": "루틴 RPA", "state": "success",
    "started_at": f"{TODAY}T13:55:49", "updated_at": f"{TODAY}T13:58:22", "finished_at": f"{TODAY}T13:58:22",
    "duration_sec": 153, "steps_done": 3, "steps_total": 3,
    "steps": [{"key": "login", "label": "ERPia 로그인", "state": "done"},
              {"key": "hold", "label": "물류대기 저장", "state": "done"},
              {"key": "output", "label": "운송장 출력", "state": "done"}],
    "metrics": [{"key": "bottom_selected", "label": "하단 선택", "value": 30, "unit": "건"},
                {"key": "stock_hold", "label": "재고검토 보류", "value": 8, "total": 8, "unit": "건"},
                {"key": "abnormal_hold", "label": "비정상 보류", "value": 376, "unit": "건", "approx": True}],
    "log_tail": ["[13:55:49] === 루틴 시작 ===", "[13:58:22] 결과: 성공"],
}
db_put(LIVE, {
    "host": "OFFICE-PC",
    "heartbeat": {"at": NOW, "host": "OFFICE-PC", "rpa_running": False},
    "programs": {"routine": routine, "prepare": None},
    "modules": {"Login": True, "Sales": False, "Hold": True, "Logistics": True, "Output": True},
    "schedule": {"enabled": True, "days": [0, 1, 2, 3, 4], "times": ["09:05"], "next_run_at": "2026-09-22T09:05:00",
                 "last_launch_at": f"{TODAY}T13:55:40", "last_launch_by": "cloud", "last_error": None},
    # 최근 10일 (에이전트가 history.jsonl 에서 센다): 성공 5 · 실패 3
    "recent": [{"date": f"2026-09-{d:02d}", "success": s, "failed": f}
               for d, s, f in [(5, 0, 0), (6, 0, 0), (7, 0, 0), (8, 0, 0), (9, 0, 0), (10, 1, 0), (11, 1, 0), (12, 1, 0), (13, 1, 1), (14, 1, 2)]],
})
print("시드 완료")

from playwright.sync_api import sync_playwright  # noqa: E402


def login(page, email, pw="pw123456"):
    page.goto(WEB)
    page.wait_for_selector("#login:not(.hide)")
    page.fill("#email", email)
    page.fill("#password", pw)
    page.click("#login-btn")
    page.wait_for_selector("#main:not(.hide)", timeout=15000)


def cmds_of(kind):
    return [v for v in (db_get(CMDS) or {}).values() if v.get("type") == kind]


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    print("1절 로그인과 껍데기")
    page.goto(WEB)
    page.wait_for_selector("#login:not(.hide)")
    page.fill("#email", "admin@t.local"); page.fill("#password", "틀린비밀번호"); page.click("#login-btn")
    page.wait_for_selector("#login-alert:not(.hide)")
    check("맞지 않습니다" in page.text_content("#login-alert"), "틀린 비밀번호 안내")
    page.fill("#password", "pw123456"); page.click("#login-btn")
    page.wait_for_selector("#main:not(.hide)", timeout=15000)
    check(page.title() == "AFTER MARKET", "플랫폼 이름")
    check("(관리자)" in page.text_content("#who"), "관리자로 표시")
    page.wait_for_function("document.getElementById('company')?.textContent === '시연 회사'", timeout=10000)
    check(True, "회사 이름 표시")
    check(page.text_content("#app-nav a[aria-current='page']").strip().endswith("RPA"), "사이드바에서 RPA 가 현재 페이지")
    check(page.text_content("#page-title") == "RPA", "페이지 제목")
    check(page.is_hidden("#pc-pick"), "PC 가 하나면 고르기 숨김")
    before = page.evaluate("getComputedStyle(document.body).backgroundColor")
    page.click("#theme")
    after = page.evaluate("getComputedStyle(document.body).backgroundColor")
    check(before != after and page.evaluate("document.documentElement.dataset.theme") == "dark", "어둡게 토글이 바탕색을 바꾼다")
    check("밝게" in page.text_content("#theme"), "버튼 글자가 바뀐다")
    page.click("#theme")
    check(page.evaluate("document.documentElement.dataset.theme") == "light", "다시 밝게")

    print("2절 상태 헤더와 타일")
    page.wait_for_function("document.getElementById('h-state')?.textContent === '오늘 성공'", timeout=10000)
    check(True, "오늘 성공")
    check(page.get_attribute("#hero", "data-state") == "success", "헤더 색 상태")
    l1 = page.text_content("#h-line1")
    check("13:55" in l1 and "2분 33초" in l1 and "하단 선택 30건" in l1, f"헤더 한 줄 ({l1})")
    tiles = page.text_content("#tiles")
    flat = tiles.replace(" ", "").replace("\n", "")
    check("처리주문30건" in flat and "재고검토보류8/8" in flat, f"숫자 타일 ({flat[:60]})")
    check("≈376" in tiles.replace(" ", ""), "추정치는 ≈")
    check("정상" in page.text_content("#conn"), "연결 정상")
    check("9월 22일" in tiles and "09:05" in tiles, "다음 자동 실행")
    check(page.is_visible("#list-routine li"), "단계 목록은 항상 펼쳐져 있다")
    check("성공 · 3/3 · 2분 33초" in page.text_content("#meta-routine"), "단계 요약")
    check("기록 없음" in page.text_content("#meta-prepare"), "프리페어 없음")
    pair = page.evaluate("""() => { const p = document.querySelector('.pair'); const [a, b] = p.children;
      return [a.id, b.id, a.getBoundingClientRect().top === b.getBoundingClientRect().top, a.getBoundingClientRect().left < b.getBoundingClientRect().left]; }""")
    check(pair[0] == "steps-prepare" and pair[1] == "steps-routine" and pair[2] and pair[3], f"프리페어가 왼쪽, 루틴이 오른쪽에 나란히 ({pair})")
    check("2줄" in page.text_content("#log-meta"), "로그 줄 수")
    check(page.locator("#recent-strip .day").count() == 10, "최근 10일 격자 10칸")
    check(page.locator("#recent-strip .c.good").count() == 3 and page.locator("#recent-strip .c.mix").count() == 2, "격자 색: 성공 3칸, 섞임 2칸")
    check("09/14" in page.text_content("#recent-strip"), "날짜 표시")
    check("성공 5 · 실패 3" in page.text_content("#recent-meta"), "10일 합계")
    check("63%" in page.text_content("#recent-donut svg text"), "도넛 가운데 성공률 (5/8)")
    dash = page.get_attribute("#recent-donut svg circle:nth-child(2)", "stroke-dasharray")
    check(dash and abs(float(dash.split()[0]) - 62.5) < 0.1, f"도넛 호 길이 ({dash})")

    print("3절 실패·끊김 표시")
    db_patch(f"{LIVE}/programs/routine", {"state": "stopped", "reason": "물류 관리 저장 실패 - 주소를 입력하세요",
                                          "steps": [{"key": "login", "label": "ERPia 로그인", "state": "done"},
                                                    {"key": "save", "label": "물류 관리 저장", "state": "stopped", "note": "주소를 입력하세요"},
                                                    {"key": "output", "label": "운송장 출력", "state": "pending"}],
                                          "steps_done": 1, "updated_at": f"{TODAY}T14:00:00"})
    page.wait_for_function("document.getElementById('h-state')?.textContent === '실패'", timeout=10000)
    check(page.get_attribute("#hero", "data-state") == "stopped", "실패는 빨강 상태")
    check("물류 관리 저장에서 멈춤" in page.text_content("#h-line1"), "멈춘 단계를 한 줄에")
    check("주소를 입력하세요" in page.text_content("#h-line2"), "사유")
    check("주소를 입력하세요" in page.text_content("#list-routine li.stopped .note"), "멈춘 단계가 목록에서 빨갛게")
    check("다시 실행" in page.text_content("#h-act"), "헤더 버튼은 다시 실행")
    db_patch(f"{LIVE}/heartbeat", {"at": NOW - 900})
    page.wait_for_function("document.getElementById('h-state')?.textContent === 'PC 연결 끊김'", timeout=10000)
    check(page.get_attribute("#hero", "data-state") == "offline", "끊김은 주황 상태")
    check("15분 전부터" in page.text_content("#h-line1"), "끊긴 시간")
    check(page.is_disabled("#h-act button"), "끊기면 헤더 실행 버튼 잠금")
    db_patch(f"{LIVE}/heartbeat", {"at": NOW})
    db_patch(f"{LIVE}/programs/routine", routine)
    page.wait_for_function("document.getElementById('h-state')?.textContent === '오늘 성공'", timeout=10000)

    print("4절 명령 투입")
    page.click("#run-routine")
    page.wait_for_selector("#act-alert:not(.hide)")
    check("보냈습니다" in page.text_content("#act-alert"), "보냈다는 안내")
    time.sleep(1.0)
    launched = cmds_of("launch")
    check(len(launched) == 1, "명령이 하나 만들어졌다")
    c = launched[0] if launched else {}
    check(c.get("state") == "queued" and c.get("by") == admin_uid and c.get("args", {}).get("target") == "routine", "launch / queued / by / target")
    check(590 <= c.get("expires_at", 0) - c.get("created_at", 0) <= 610, "만료 10분")
    check(page.is_disabled("#run-routine") and page.is_disabled("#h-act button"), "응답 대기 중 버튼 잠금")
    key = next(k for k, v in (db_get(CMDS) or {}).items() if v.get("type") == "launch")
    db_patch(f"{CMDS}/{key}", {"state": "done", "result": "루틴 RPA 을(를) 띄웠습니다", "started_at": 1, "ended_at": 2})
    page.wait_for_function("document.getElementById('act-alert')?.textContent?.includes('띄웠습니다')", timeout=10000)
    check(True, "done 이 되면 결과 문장")
    page.wait_for_function("document.getElementById('run-routine')?.disabled === false", timeout=5000)
    check(True, "끝나면 버튼이 풀린다")

    print("5절 실행 모듈")
    page.wait_for_function("document.getElementById('mod-meta')?.textContent === '4/5 켬'", timeout=10000)
    check(page.is_disabled("#mod-apply"), "바뀐 게 없으면 적용 비활성")
    page.click("#mod-list label:nth-child(2)")     # 스위치의 input 은 숨겨져 있어 label 을 누른다
    check("5/5 켬" in page.text_content("#mod-meta") and not page.is_disabled("#mod-apply"), "켜면 요약·적용 활성")
    page.click("#mod-apply")
    time.sleep(1.5)
    check((db_get(f"{SETTINGS}/modules") or {}).get("Sales") is True, "settings.modules 에 저장")
    mods = cmds_of("set_modules")
    check(len(mods) == 1 and mods[0]["args"]["Sales"] is True, "set_modules 명령")
    key = next(k for k, v in (db_get(CMDS) or {}).items() if v.get("type") == "set_modules")
    db_patch(f"{CMDS}/{key}", {"state": "done", "result": "실행 모듈을 바꿨습니다", "started_at": 1, "ended_at": 2})
    db_patch(f"{LIVE}/modules", {"Sales": True})
    page.wait_for_function("document.getElementById('mod-apply')?.disabled === true", timeout=10000)
    check("5/5 켬" in page.text_content("#mod-meta"), "PC 값이 돌아오면 기준값 갱신")

    print("6절 자동 실행")
    check("평일 09:05" in page.text_content("#sch-meta"), "현재 예약 요약")
    check("다음 9월 22일" in page.text_content("#sch-info") and "마지막" in page.text_content("#sch-info"), "다음·마지막 실행")
    check(page.is_disabled("#sch-apply"), "바뀐 게 없으면 적용 비활성")
    check(page.get_attribute("#sch-days button:nth-child(1)", "aria-pressed") == "true"
          and page.get_attribute("#sch-days button:nth-child(6)", "aria-pressed") == "false", "요일 버튼 상태")
    page.click("#sch-presets button:nth-child(2)")      # 매일
    page.click("#sch-add")
    inputs = page.query_selector_all("#sch-times input")
    check(len(inputs) == 2, "시간 추가")
    inputs[1].fill("13:30")
    inputs[1].dispatch_event("change")
    check(not page.is_disabled("#sch-apply"), "바뀌면 적용 활성")
    page.click("#sch-apply")
    time.sleep(1.5)
    saved = db_get(f"{SETTINGS}/schedule") or {}
    check(saved.get("enabled") is True and saved.get("days") == [0, 1, 2, 3, 4, 5, 6] and saved.get("times") == ["09:05", "13:30"],
          f"settings.schedule 저장 ({saved.get('days')} {saved.get('times')})")
    sched = cmds_of("set_schedule")
    check(len(sched) == 1 and sched[0]["args"]["times"] == ["09:05", "13:30"], "set_schedule 명령")
    # 에이전트 역할: 명령을 닫고 PC 값(live.schedule)을 돌려준다
    key = next(k for k, v in (db_get(CMDS) or {}).items() if v.get("type") == "set_schedule")
    db_patch(f"{CMDS}/{key}", {"state": "done", "result": "자동 실행: 매일 09:05, 13:30", "started_at": 1, "ended_at": 2})
    db_patch(f"{LIVE}/schedule", {"days": [0, 1, 2, 3, 4, 5, 6], "times": ["09:05", "13:30"]})
    page.wait_for_function("document.getElementById('sch-meta')?.textContent === '매일 09:05, 13:30'", timeout=10000)
    check(page.is_disabled("#sch-apply"), "PC 값이 돌아오면 요약 갱신·적용 비활성")
    page.click("label:has(#sch-enabled)")
    page.wait_for_function("document.getElementById('sch-apply')?.disabled === false", timeout=5000)
    page.click("#sch-times .t:nth-child(1) button")
    page.click("#sch-times .t:nth-child(1) button")
    check(page.is_disabled("#sch-apply") is False, "끄면 시간이 없어도 적용 가능")
    page.click("label:has(#sch-enabled)")
    check(page.is_disabled("#sch-apply"), "켠 채 시간이 없으면 적용 불가")

    print("7절 계정 페이지")
    page.click("#admin-nav a[data-key='account']")
    page.wait_for_selector("#pw-btn")
    check(page.text_content("#page-title") == "계정", "계정 페이지 제목")
    check("admin@t.local" in page.text_content("#acct-email"), "이메일 표시")
    page.fill("#pw-cur", "pw123456"); page.fill("#pw-new", "short"); page.fill("#pw-new2", "short"); page.click("#pw-btn")
    check("8자" in page.text_content("#pw-msg"), "짧은 비밀번호 거부")
    page.fill("#pw-new", "newpass123"); page.fill("#pw-new2", "newpass124"); page.click("#pw-btn")
    check("다릅니다" in page.text_content("#pw-msg"), "재입력 불일치 거부")
    page.fill("#pw-cur", "wrongpass"); page.fill("#pw-new2", "newpass123"); page.click("#pw-btn")
    page.wait_for_function("/맞지 않습니다|바꾸지 못했/.test(document.getElementById('pw-msg')?.textContent || '')", timeout=10000)
    check("현재 비밀번호가 맞지 않습니다" in page.text_content("#pw-msg"), "현재 비밀번호 틀림 거부")
    page.fill("#pw-cur", "pw123456"); page.click("#pw-btn")
    page.wait_for_function("(document.getElementById('pw-msg')?.textContent || '').includes('바꿨습니다')", timeout=10000)
    check(True, "비밀번호 변경 성공 안내")
    check(sign_in("admin@t.local", "newpass123") and not sign_in("admin@t.local", "pw123456"), "새 비밀번호로만 로그인된다")
    page.click("#app-nav a[data-key='rpa']")
    page.wait_for_selector("#hero")
    check(page.text_content("#page-title") == "RPA", "RPA 로 돌아온다")

    print("8절 열람자")
    page.click("#logout-btn")
    page.wait_for_selector("#login:not(.hide)")
    login(page, "viewer@t.local")
    check("(열람)" in page.text_content("#who"), "열람자로 표시")
    page.wait_for_function("document.getElementById('h-state')?.textContent === '오늘 성공'", timeout=10000)
    check(page.is_hidden("#act-card") and page.is_hidden("#mod-card") and page.is_hidden("#sch-card"), "열람자는 실행·모듈·자동 실행 카드가 없다")
    check(page.query_selector("#h-act button") is None, "열람자는 헤더 버튼도 없다")
    denied = page.evaluate("""async () => {
      const m = await import('https://www.gstatic.com/firebasejs/10.14.1/firebase-database.js');
      const a = await import('https://www.gstatic.com/firebasejs/10.14.1/firebase-app.js');
      const db = m.getDatabase(a.getApp());
      try { await m.push(m.ref(db, 'apps/rpa/commands/c_demo/pc_office'), {type:'launch', by:'x', created_at:1, expires_at:2, state:'queued'}); return 'ok'; }
      catch (e) { return e.code || String(e); }
    }""")
    check(denied == "PERMISSION_DENIED", f"열람자가 우회해 써도 규칙이 거부 ({denied})")

    check(not errors, f"페이지 오류 없음 {errors[:2]}")
    browser.close()

print(f"\n{COUNT - len(FAIL)}/{COUNT} 통과")
if FAIL:
    print("실패:", ", ".join(FAIL))
    sys.exit(1)
