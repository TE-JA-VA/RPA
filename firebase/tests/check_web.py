"""화면 시험 (Playwright + 에뮬레이터). 실제 프로젝트를 건드리지 않는다.

실행 (firebase/tests 에서, emu_env.ps1 을 읽은 창):
  firebase emulators:exec --config ../firebase.json --only auth,database,firestore,hosting --project rpa-test-f02e0 "python check_web.py"

에뮬레이터 REST 는 'Authorization: Bearer owner' 로 규칙을 우회한다 (시드용).
"""
import datetime
import json
import os
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


def sign_in_id(email):
    """에뮬레이터 계정의 localId (막기 전에 찾는다)"""
    r = call("POST", f"{AUTH}/identitytoolkit.googleapis.com/v1/projects/{PROJECT}/accounts:lookup", {"email": [email]}, OWNER)
    return r["users"][0]["localId"]


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
    "steps": [{"key": "login", "label": "ERPia 로그인", "state": "done",
               "started_at": f"{TODAY}T13:55:49", "finished_at": f"{TODAY}T13:56:30"},
              {"key": "hold", "label": "물류대기 저장", "state": "done",
               "started_at": f"{TODAY}T13:56:30", "finished_at": f"{TODAY}T13:57:40"},
              {"key": "output", "label": "운송장 출력", "state": "done",
               "started_at": f"{TODAY}T13:57:40", "finished_at": f"{TODAY}T13:58:22"}],
    "metrics": [{"key": "bottom_selected", "label": "하단 선택", "value": 30, "unit": "건"},
                {"key": "stock_hold", "label": "재고검토 보류", "value": 8, "total": 8, "unit": "건"},
                {"key": "abnormal_hold", "label": "비정상 보류", "value": 376, "unit": "건", "approx": True}],
    "log_tail": ["[13:55:49] === 루틴 시작 ===", "[13:58:22] 결과: 성공"],
}
db_put(LIVE, {
    "host": "OFFICE-PC",
    # 시험 내내 '정상' 이도록 미래 시각. every=5 는 새 에이전트 (끊김 기준 5*3+5 = 20초)
    "heartbeat": {"at": NOW + 3600, "every": 5, "host": "OFFICE-PC", "rpa_running": False},
    "programs": {"routine": routine, "prepare": None},
    "modules": {"Login": True, "Sales": False, "Hold": True, "Logistics": True, "Output": True},
    "schedule": {"enabled": True, "days": [0, 1, 2, 3, 4], "times": ["09:05"], "next_run_at": "2026-09-22T09:05:00",
                 "last_launch_at": f"{TODAY}T13:55:40", "last_launch_by": "cloud", "last_error": None},
    # 최근 20일 (에이전트가 history.jsonl 에서 센다). 8/26~9/4 는 실행 없음, 9/10~9/14 성공 5 · 실패 3 · 비정상 1(9/13)
    "recent": [{"date": f"2026-08-{d:02d}", "success": 0, "failed": 0, "crashed": 0} for d in range(26, 32)]
              + [{"date": f"2026-09-{d:02d}", "success": s, "failed": f, "crashed": c}
                 for d, s, f, c in [(1, 0, 0, 0), (2, 0, 0, 0), (3, 0, 0, 0), (4, 0, 0, 0), (5, 0, 0, 0), (6, 0, 0, 0), (7, 0, 0, 0),
                                    (8, 0, 0, 0), (9, 0, 0, 0), (10, 1, 0, 0), (11, 1, 0, 0), (12, 1, 0, 0), (13, 1, 1, 1), (14, 1, 2, 0)]],
})
# 이력 (Firestore 에뮬레이터 REST, Bearer owner). 에이전트가 올리는 문서와 같은 모양
FS = f"http://127.0.0.1:8080/v1/projects/{PROJECT}/databases/(default)/documents"


def fs_fields(d):
    out = {}
    for k, v in d.items():
        if v is None: out[k] = {"nullValue": None}
        elif isinstance(v, bool): out[k] = {"booleanValue": v}
        elif isinstance(v, int): out[k] = {"integerValue": str(v)}
        else: out[k] = {"stringValue": v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)}
    return out


def seed_run(run_id, program, state, started, dur_sec, reason=None, steps=None, log=None, metrics=None, trigger=None):
    payload = {"run_id": run_id, "program": program, "state": state, "started_at": started, "duration_sec": dur_sec,
               "reason": reason, "steps": steps or [], "log": log or [], "metrics": metrics or [], "trigger": trigger}
    doc = {"cid": "c_demo", "pcId": "pc_office", "run_id": run_id, "program": program,
           "program_label": "루틴 RPA" if program == "routine" else "프리페어 RPA", "state": state, "reason": reason,
           "started_at": started, "finished_at": None, "duration_sec": dur_sec, "date": started[:10], "payload": json.dumps(payload, ensure_ascii=False)}
    call("POST", f"{FS}/runs/c_demo/items?documentId={run_id}", {"fields": fs_fields(doc)}, OWNER)


seed_run("r_0914_1355", "routine", "success", "2026-09-14T13:55:49", 153,
         steps=[{"key": "login", "label": "ERPia 로그인", "state": "done"}], log=["[13:55:49] 시작", "[13:58:22] 결과: 성공"],
         metrics=[{"key": "bottom_selected", "label": "하단 선택", "value": 30}])
seed_run("r_0914_1339", "routine", "stopped", "2026-09-14T13:39:05", 2, reason="물류 관리 저장 실패 - 주소를 입력하세요",
         steps=[{"key": "save", "label": "물류 관리 저장", "state": "stopped", "note": "주소를 입력하세요"}], log=["[13:39:05] 주소를 입력하세요"])
seed_run("r_0914_1338", "prepare", "success", "2026-09-14T13:38:41", 2, log=["[13:38:43] 완료"])
seed_run("r_0913_0906", "routine", "stopped", "2026-09-13T09:06:00", 547, reason="물류 관리 저장 실패 - 주소를 입력하세요")
seed_run("r_0912_0906", "routine", "success", "2026-09-12T09:06:00", 580)
seed_run("r_0911_0900", "routine", "crashed", "2026-09-11T09:00:00", 26,
         reason="프로그램이 도중에 꺼졌습니다 (강제 종료되었거나 오류로 멈췄습니다). 마지막 로그를 확인하세요.")
seed_run("r_other_pc", "routine", "success", "2026-09-14T10:00:00", 10)
call("PATCH", f"{FS}/runs/c_demo/items/r_other_pc?updateMask.fieldPaths=pcId", {"fields": {"pcId": {"stringValue": "pc_other"}}}, OWNER)
print("시드 완료")

from playwright.sync_api import sync_playwright  # noqa: E402


def login(page, login_id, pw="pw123456", cid=""):
    """세 칸 로그인. 아이디 칸에 이메일을 넣으면 그대로 쓰이고, 회사 코드 + 아이디면 화면이 이메일을 조립한다"""
    page.goto(WEB)
    page.wait_for_selector("#login:not(.hide)")
    page.fill("#cid", cid)
    page.fill("#login-id", login_id)
    page.fill("#password", pw)
    page.click("#login-btn")
    page.wait_for_selector("#main:not(.hide)", timeout=15000)


def cmds_of(kind):
    return [v for v in (db_get(CMDS) or {}).values() if v.get("type") == kind]


def goto(page, key):
    """사이드바 메뉴로 페이지를 바꾼다 (rpa / settings / account). 적용 안 한 변경이 있으면 확인 창이 뜬다 - 그런 곳은 시험이 직접 다룬다"""
    page.click(f"{'#app-nav' if key == 'rpa' else '#admin-nav'} a[data-key='{key}']")
    page.wait_for_selector({"rpa": "#hero", "settings": "#mod-card", "account": "#pw-btn"}[key])


def reload_to(page, key):
    """새로고침하면 첫 앱(RPA)이 뜬다 - 그 뒤 key 페이지로"""
    page.reload(); page.wait_for_selector("#main:not(.hide)", timeout=15000); page.wait_for_selector("#hero")
    if key != "rpa":
        goto(page, key)


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    print("1절 로그인과 껍데기")
    page.goto(WEB)
    page.wait_for_selector("#login:not(.hide)")
    box = lambda sel: page.evaluate(f"(() => {{ const r = document.querySelector('{sel}').getBoundingClientRect(); return [r.left, r.right, r.top, r.bottom]; }})()")
    col, art = box("#login .login-col"), box("#login .login-art")
    check(art[0] >= col[1] - 1 and art[1] >= 1270 and art[3] - art[2] >= 700, "로그인은 왼쪽 양식 + 오른쪽 그림이 세로로 꽉 참")
    check(page.is_visible("#login .login-art") and "url(" in page.evaluate("getComputedStyle(document.querySelector('#login .login-art')).backgroundImage")
          and page.evaluate("fetch('img/login.webp').then(r => r.ok && r.headers.get('content-type'))") == "image/webp", "오른쪽 그림이 보이고 파일도 내려온다")
    check(page.locator("#login a, #login [class*=social], #login [id*=signup]").count() == 0 and "가입" not in page.text_content("#login"), "SNS 로그인·회원가입 없음")
    check(page.is_visible("#remember") and not page.is_checked("#remember") and "업체코드·아이디 저장" in page.text_content("#login .remember"), "업체코드·아이디 저장 체크박스 (처음엔 꺼짐)")
    if os.environ.get("SHOT_DIR"): page.screenshot(path=os.path.join(os.environ["SHOT_DIR"], "login_light.png"))
    page.set_viewport_size({"width": 400, "height": 900}); page.wait_for_timeout(300)
    check(page.is_hidden("#login .login-art") and page.evaluate("document.documentElement.scrollWidth <= window.innerWidth") and box("#login-btn")[1] <= 400, "폰 폭에서는 그림을 숨기고 양식이 폭 안에 든다")
    if os.environ.get("SHOT_DIR"): page.screenshot(path=os.path.join(os.environ["SHOT_DIR"], "login_phone.png"))
    page.set_viewport_size({"width": 1280, "height": 720}); page.wait_for_timeout(300)
    page.fill("#login-id", "admin@t.local"); page.fill("#password", "틀린비밀번호"); page.click("#login-btn")
    page.wait_for_selector("#login-alert:not(.hide)")
    check(page.text_content("#login-alert") == "업체코드, 아이디 또는 비밀번호가 맞지 않습니다", "틀린 비밀번호 안내 (세 칸 문구)")
    geo = page.evaluate("""() => { const b = document.getElementById('login-btn').getBoundingClientRect(),
        a = document.getElementById('login-alert').getBoundingClientRect(), s = getComputedStyle(document.getElementById('login-alert'));
        return { right: a.left >= b.right, row: Math.abs((a.top + a.bottom) / 2 - (b.top + b.bottom) / 2) < 4, color: s.color,
                 bad: getComputedStyle(document.documentElement).getPropertyValue('--bad').trim(), bg: getComputedStyle(document.body).backgroundColor }; }""")
    check(geo["right"] and geo["row"], "로그인 안내는 로그인 버튼 오른쪽 같은 줄")
    _rgb = lambda s: "#%02x%02x%02x" % tuple(int(x) for x in s[s.index("(") + 1:-1].split(",")[:3])
    check(_rgb(geo["color"]) == geo["bad"].lower(), "로그인 안내는 빨간 글씨(--bad)")
    _lum = lambda h: sum(w * ((v / 12.92) if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4)
                         for w, v in zip((0.2126, 0.7152, 0.0722), (int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))))
    _la, _lb = _lum(_rgb(geo["color"])), _lum(_rgb(geo["bg"]))
    check((max(_la, _lb) + 0.05) / (min(_la, _lb) + 0.05) >= 4.5, "로그인 안내 글자 대비 4.5:1 이상")
    make_user("off@t.local", "pw123456", {"cid": "c_demo", "role": "viewer"})
    call("POST", f"{AUTH}/identitytoolkit.googleapis.com/v1/projects/{PROJECT}/accounts:update",
         {"localId": sign_in_id("off@t.local"), "disableUser": True}, OWNER)
    page.fill("#login-id", "off@t.local"); page.fill("#password", "pw123456"); page.click("#login-btn")
    page.wait_for_function("(document.getElementById('login-alert')?.textContent || '').includes('중지된 계정')", timeout=15000)
    check(page.text_content("#login-alert") == "사용이 중지된 계정입니다", "막힌 계정 안내 (auth/user-disabled)")
    page.fill("#login-id", "admin@t.local")
    check(page.locator("#email").count() == 0 and "업체코드" in page.text_content("#login") and page.get_attribute("#cid", "placeholder") is None and page.get_attribute("#login-id", "placeholder") is None, "로그인은 업체코드·아이디·비밀번호 세 칸, 힌트 글 없음")
    page.fill("#password", "pw123456"); page.click("#login-btn")
    page.wait_for_selector("#main:not(.hide)", timeout=15000)
    check(page.title() == "AFTER MARKET", "플랫폼 이름")
    check("(관리자)" in page.text_content("#who"), "관리자로 표시")
    page.wait_for_function("document.getElementById('company')?.textContent === '시연 회사'", timeout=10000)
    check(True, "회사 이름 표시")
    check(page.text_content("#app-nav a[aria-current='page']").strip().endswith("RPA"), "사이드바에서 RPA 가 현재 페이지")
    check(page.text_content("#page-title") == "RPA", "페이지 제목")
    check(page.is_hidden("#pc-pick"), "PC 가 하나면 고르기 숨김")
    check(page.evaluate("[...document.querySelectorAll('#admin-nav a')].map((a) => a.dataset.key).join()") == "settings,account"
          and page.text_content("#admin-nav a[data-key='settings']").strip().endswith("환경설정"), "관리 메뉴: 환경설정 · 계정 (환경설정이 위)")
    check(page.locator("#mod-card, #shop-card, #sch-card").count() == 0, "RPA 화면에는 설정 카드가 없다 (환경설정으로 옮김)")
    def lum(hex6):
        ch = [int(hex6[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        ch = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in ch]
        return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]

    def contrast(a, b):
        la, lb = lum(a), lum(b)
        return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)

    def tok(name):
        return page.evaluate(f"getComputedStyle(document.documentElement).getPropertyValue('{name}').trim()")

    rgb2hex = lambda s: "#%02x%02x%02x" % tuple(int(x) for x in s[4:-1].split(",")[:3])

    def contrast_ok(theme):
        card = tok("--card")
        pairs = {"글자": contrast(tok("--ink"), card), "회색 글자": contrast(tok("--muted"), card), "제목": contrast(tok("--strong"), card)}
        for st_ in ["good", "warn", "bad", "run"]:
            pairs[f"채운 카드 {st_}"] = contrast(tok("--on-fill"), tok(f"--{st_}-fill"))
        for st_ in ["red", "amber", "green"]:
            pairs[f"환경설정 글자 {st_}"] = contrast(tok(f"--ecam-{st_}"), card)
            pairs[f"환경설정 글자 {st_} (바탕)"] = contrast(tok(f"--ecam-{st_}"), tok("--bg"))
        low = {k: round(v, 2) for k, v in pairs.items() if v < 4.5}
        check(not low, f"{theme} 대비 4.5:1 이상 {low or ''}")
        # 환경설정 안내 글자만 AIRBUS ECAM 처럼 빨강·호박색·초록 (사용자 2026-10-08) - 색상(hue)으로 본다, 밝기는 대비에 맞춘다
        import colorsys
        hue = lambda h: colorsys.rgb_to_hls(*[int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)])[0] * 360
        hues = {k: round(hue(tok(f"--ecam-{k}"))) for k in ("red", "amber", "green")}
        check((hues["red"] <= 5 or hues["red"] >= 355) and 30 <= hues["amber"] <= 42 and 110 <= hues["green"] <= 130,
              f"{theme} 환경설정 글자색은 ECAM 빨강·호박색·초록 ({hues})")
        check(round(hue(tok("--good"))) > 150, f"{theme} RPA 메뉴의 상태 색은 그대로 (환경설정만 ECAM) ({round(hue(tok('--good')))})")
    check(page.evaluate("getComputedStyle(document.body).fontFamily").startswith('"Pretendard Variable"'), "본문 서체 Pretendard")
    contrast_ok("밝음")
    if os.environ.get("SHOT_DIR"): page.screenshot(path=os.path.join(os.environ["SHOT_DIR"], "theme_light.png"), full_page=True)
    before = page.evaluate("getComputedStyle(document.body).backgroundColor")
    page.click("#theme")
    after = page.evaluate("getComputedStyle(document.body).backgroundColor")
    check(before != after and page.evaluate("document.documentElement.dataset.theme") == "dark", "어둡게 토글이 바탕색을 바꾼다")
    check("밝게" in page.text_content("#theme"), "버튼 글자가 바뀐다")
    contrast_ok("어두움")
    if os.environ.get("SHOT_DIR"):   # 색 전환(.5s)이 끝난 뒤에 찍는다 - 도중엔 옛 글자색이 새 카드색과 같아 글자가 안 보인다
        page.wait_for_timeout(700)
        page.screenshot(path=os.path.join(os.environ["SHOT_DIR"], "theme_dark.png"), full_page=True)
    page.wait_for_timeout(700)
    card_bg = page.evaluate("getComputedStyle(document.getElementById('act-card')).backgroundColor")
    check(page.evaluate("getComputedStyle(document.querySelector('#run-routine .t')).color") != card_bg, "어두운 모드에서 테두리 버튼 글자가 카드색과 다르다")
    page.click("#theme")
    check(page.evaluate("document.documentElement.dataset.theme") == "light", "다시 밝게")

    print("2절 상태 헤더와 타일")
    page.wait_for_function("document.getElementById('h-state')?.textContent === '성공'", timeout=10000)
    check(True, "성공 (오늘 없이 간단히)")
    check(page.get_attribute("#hero", "data-state") == "success", "헤더 색 상태")
    l1 = page.text_content("#h-line1")
    check(l1 == "13:55 루틴 RPA · 2분 33초", f"헤더 한 줄 ({l1})")
    l2 = page.text_content("#h-line2")
    check(l2 == "수집 30건 · 재고검토 보류 8/8건 · 비정상 보류 ≈376건", f"요약 한 줄 ({l2})")
    check(page.query_selector("#hero button") is None, "상태 카드에 버튼 없음 (실행 카드와 중복)")
    check(page.locator("#toasts .toast").count() == 0, "처음 열 때는 옛 결과로 토스트가 울리지 않는다")
    tiles = page.text_content("#tiles")
    flat = tiles.replace(" ", "").replace("\n", "")
    check("처리주문30건" in flat and "재고검토보류8/8" in flat, f"숫자 타일 ({flat[:60]})")
    check("≈376" in tiles.replace(" ", ""), "추정치는 ≈")
    check(page.evaluate("getComputedStyle(document.querySelector('.tile .v')).fontFamily").startswith('"Pretendard Variable"'), "숫자 칸도 같은 서체")
    side = page.text_content("#hero .stats")
    check("정상" in page.text_content("#conn") and page.query_selector("#hero .stats #conn") is not None, "연결은 상태 띠 오른쪽에")
    check("9월 22일" in side and "09:05" in side and "다음 자동 실행" not in tiles, "다음 자동 실행도 상태 띠 오른쪽에")
    geo = page.evaluate("""() => { const b = document.querySelector('#hero .body').getBoundingClientRect(),
        d = document.querySelector('#hero .stats').getBoundingClientRect(), h = document.getElementById('hero').getBoundingClientRect();
      return [d.left > b.right - 1, h.right - d.right < 40]; }""")
    check(geo[0] and geo[1], f"본문 오른쪽에 붙어 있다 ({geo})")
    db_patch(f"{LIVE}/programs/routine", {"metrics": None})   # 숫자 칸이 하나도 없는 업체 (모듈을 거의 끈 경우)
    page.wait_for_function("document.getElementById('tiles')?.classList.contains('hide')", timeout=10000)
    gap = page.evaluate("""() => Math.round(document.querySelector('#view-status .cols').getBoundingClientRect().top
      - document.getElementById('hero').getBoundingClientRect().bottom)""")
    check(12 <= gap <= 20, f"숫자 칸이 없어도 상태 띠와 아래 카드가 붙지 않는다 ({gap}px)")
    db_patch(f"{LIVE}/programs/routine", {"metrics": routine["metrics"]})
    page.wait_for_function("!document.getElementById('tiles')?.classList.contains('hide')", timeout=10000)
    check(page.is_visible("#list-routine li"), "단계 목록은 항상 펼쳐져 있다")
    check("성공 · 3/3 · 2분 33초" in page.text_content("#meta-routine"), "단계 요약")
    check("기록 없음" in page.text_content("#meta-prepare"), "프리페어 없음")
    pair = page.evaluate("""() => { const p = document.querySelector('.pair'); const [a, b] = p.children;
      return [a.id, b.id, a.getBoundingClientRect().top === b.getBoundingClientRect().top, a.getBoundingClientRect().left < b.getBoundingClientRect().left]; }""")
    check(pair[0] == "steps-prepare" and pair[1] == "steps-routine" and pair[2] and pair[3], f"프리페어가 왼쪽, 루틴이 오른쪽에 나란히 ({pair})")
    log = page.text_content("#log")
    check("3줄" in page.text_content("#log-meta"), f"로그 줄 수는 단계 수 ({page.text_content('#log-meta')})")
    check(log.splitlines()[0] == "[13:56:30] ERPia 로그인 성공", f"단계마다 한 줄 ({log.splitlines()[0]})")
    check("===" not in log, "RPA 원본 로그는 안 싣는다")
    # 띠는 최근 20일 전부. 왼쪽 끝부터 오늘 도넛까지 채우되 15칸까지만 보이고(칸 48~72px, 남으면 간격), 나머지는 가로 스크롤
    def strip_geo():
        return page.evaluate("""() => { const s = document.getElementById('recent-strip'), d = document.getElementById('recent-donut');
          const cell = s.querySelector('.day').offsetWidth, gap = parseFloat(getComputedStyle(s).columnGap) || 0;
          const sr = s.getBoundingClientRect(), dr = d.getBoundingClientRect(), pr = s.parentElement.getBoundingClientRect();
          return { n: s.children.length, cell, visible: Math.floor((s.clientWidth + gap + 0.5) / (cell + gap)),
                   overflow: s.scrollWidth > s.clientWidth + 1, atEnd: s.scrollLeft + s.clientWidth >= s.scrollWidth - 1,
                   gap: dr.left - sr.right, leftGap: sr.left - pr.left, sameRow: Math.abs(dr.top - sr.top) < 80 }; }""")
    g = strip_geo()
    check(g["n"] == 20, f"띠는 20일을 다 그린다 ({g['n']})")
    check(page.locator("#recent-strip .day:last-child").get_attribute("data-date") == "2026-09-14", "마지막 칸은 오늘")
    check(page.locator("#recent-strip .day:first-child").get_attribute("data-date") == "2026-08-26", "첫 칸은 8/26")
    check(g["visible"] <= 15 and g["overflow"] and g["atEnd"], f"기본 창: {g['visible']}칸 보이고 오늘이 오른쪽 끝")
    check(g["sameRow"] and 0 <= g["gap"] <= 21 and g["leftGap"] < 2, f"띠가 왼쪽 끝부터 오늘 도넛까지 (틈 {g['gap']:.0f}px)")
    card_right = page.evaluate("document.querySelector('.card.recent').getBoundingClientRect().right")
    check(card_right - page.evaluate("document.getElementById('recent-donut').getBoundingClientRect().right") < 40, "오늘 도넛은 오른쪽에 고정")
    page.set_viewport_size({"width": 2200, "height": 900}); page.wait_for_timeout(300)
    g = strip_geo()
    check(g["visible"] == 15 and g["overflow"] and g["atEnd"] and 0 <= g["gap"] <= 21 and g["leftGap"] < 2 and 48 <= g["cell"] <= 72,
          f"넓은 창: 칸을 키워 15칸이 꼭 맞고 도넛에 붙는다 ({g['visible']}칸, 칸 {g['cell']:.0f}px)")
    if os.environ.get("SHOT_DIR"):   # 눈으로 볼 때: SHOT_DIR 에 최근 카드 사진을 남긴다
        for w in (2560, 1920, 1280, 400):
            page.set_viewport_size({"width": w, "height": 900}); page.wait_for_timeout(300)
            page.locator(".card.recent").screenshot(path=os.path.join(os.environ["SHOT_DIR"], f"recent_{w}.png"))
        page.set_viewport_size({"width": 2200, "height": 900}); page.wait_for_timeout(300)
    before = page.evaluate("document.getElementById('recent-strip').scrollLeft")
    page.hover("#recent-strip .day:last-child"); page.mouse.wheel(0, -200); page.wait_for_timeout(200)
    after = page.evaluate("document.getElementById('recent-strip').scrollLeft")
    check(after < before, f"띠 위에서 휠을 굴리면 옆으로 민다 ({before:.0f} → {after:.0f})")
    page.set_viewport_size({"width": 400, "height": 900}); page.wait_for_timeout(300)
    g = strip_geo()
    check(g["n"] == 20 and g["overflow"] and g["visible"] <= 8 and g["atEnd"] and g["cell"] == 48,
          f"좁은 창: 20일 그대로, 48px {g['visible']}칸 보이고 오늘이 끝에")
    page.set_viewport_size({"width": 1280, "height": 720}); page.wait_for_timeout(300)
    check(page.locator("#recent-strip .day.empty").count() == 15, "실행 없는 날은 빈 도넛")
    check(page.get_attribute("#recent-strip .day.empty svg circle", "stroke") == "url(#hatch)", "빈 도넛은 빗금")
    bg = page.evaluate("getComputedStyle(document.getElementById('hero')).backgroundColor")
    good = page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--good-fill').trim()")
    hexbg = "#%02x%02x%02x" % tuple(int(x) for x in bg[4:-1].split(",")[:3])
    check(hexbg == good, f"성공이면 상태 카드가 진한 초록으로 채워진다 ({hexbg} = {good})")
    check(page.evaluate("getComputedStyle(document.getElementById('h-state')).color") == "rgb(255, 255, 255)", "채운 카드 글자는 흰색")
    yday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    db_patch(f"{LIVE}/programs/routine", {"started_at": f"{yday}T13:55:49", "finished_at": f"{yday}T13:58:22"})
    page.wait_for_function("document.getElementById('h-state')?.textContent === '대기중'", timeout=10000)
    check(page.get_attribute("#hero", "data-state") == "" and "마지막 실행" in page.text_content("#h-line1"),
          f"오늘 실행이 없으면 지난 결과 대신 대기중 ({page.text_content('#h-line1')})")
    check(page.locator("#list-routine li").count() == 0 and "오늘 실행 없음" in page.text_content("#meta-routine"),
          f"단계 목록도 어제 것을 안 보여 준다 ({page.text_content('#meta-routine')})")
    check("마지막" in page.text_content("#meta-routine"), "대신 마지막이 언제였는지 적는다")
    check(page.text_content("#log") == "" and page.text_content("#log-meta") == "없음", "로그도 어제 것을 안 보여 준다")
    db_patch(f"{LIVE}/programs/routine", {"started_at": f"{TODAY}T13:55:49", "finished_at": f"{TODAY}T13:58:22"})
    page.wait_for_function("document.getElementById('h-state')?.textContent === '성공'", timeout=10000)
    d14 = page.get_attribute("#recent-strip .day[data-date='2026-09-14'] svg circle:nth-child(2)", "stroke-dasharray")
    check(d14 and abs(float(d14.split()[0]) - 33.33) < 0.1, f"9/14 도넛은 성공 1/3 ({d14})")
    check("09/14" in page.text_content("#recent-strip"), "날짜 표시")
    check(page.text_content("#recent-meta") == "오늘 성공 1 · 실패 2", f"큰 도넛은 오늘 ({page.text_content('#recent-meta')})")
    check(page.locator("#recent-donut svg text").count() == 0, "도넛에 퍼센트 글자 없음")
    dash = page.get_attribute("#recent-donut svg circle:nth-child(2)", "stroke-dasharray")
    check(dash and abs(float(dash.split()[0]) - 33.33) < 0.1, f"오늘 도넛 호 길이 1/3 ({dash})")
    legend = page.text_content("#recent-donut .legend")
    check("성공 1" in legend and "실패 2" in legend and "오류 0" in legend, f"오늘 도넛 범례 세 가지 ({legend.strip()})")
    db_patch(f"{LIVE}/recent/19", {"success": 0, "failed": 0, "crashed": 0})   # 마지막 날 = 큰 도넛
    page.wait_for_function("document.getElementById('recent-meta')?.textContent === '오늘 실행 없음'", timeout=10000)
    check(page.get_attribute("#recent-donut svg circle", "stroke") == "url(#hatch)" and page.locator("#recent-donut .legend").count() == 0,
          "실행 없는 날은 큰 자리에도 빗금 도넛 (글자 대신)")
    db_patch(f"{LIVE}/recent/19", {"success": 1, "failed": 2, "crashed": 0})
    page.wait_for_function("document.getElementById('recent-meta')?.textContent !== '오늘 실행 없음'", timeout=10000)
    # 9/13 = 성공 1 · 실패 1 · 오류 1 → 초록 1/3 (12시부터), 노랑 1/3 (초록 다음부터), 나머지 빨강
    c13 = page.evaluate("""(() => { const cs = document.querySelectorAll("#recent-strip .day[data-date='2026-09-13'] svg circle");
      return [...cs].map((c) => [c.getAttribute('stroke'), c.getAttribute('stroke-dasharray'), c.getAttribute('stroke-dashoffset')]); })()""")
    check(len(c13) == 3 and c13[0][0] == "var(--bad)" and c13[1][0] == "var(--good)" and c13[2][0] == "var(--warn-mark)", f"도넛은 빨강 바탕 + 초록 + 노랑 호 ({[x[0] for x in c13]})")
    check(abs(float(c13[2][1].split()[0]) - 33.33) < 0.1 and abs(float(c13[2][2]) - (25 - 33.33)) < 0.1,
          f"오류 호는 초록 다음부터 1/3 (dasharray {c13[2][1]}, offset {c13[2][2]})")
    # 도넛·범례의 노랑은 글자용 --warn(대비 4.5:1 맞추느라 올리브색)이 아니라 밝은 표시용 --warn-mark
    arc_hex = lambda: rgb2hex(page.evaluate("getComputedStyle(document.querySelector(\"#recent-strip .day[data-date='2026-09-13'] svg circle:nth-child(3)\")).stroke"))
    check(arc_hex() == tok("--warn-mark") == "#e0b50f" and tok("--warn") != tok("--warn-mark"),
          f"밝은 모드 오류 호는 밝은 노랑 (호 {arc_hex()}, 글자용 {tok('--warn')})")
    check(rgb2hex(page.evaluate("getComputedStyle(document.querySelector('#recent-donut .legend span:nth-child(3) i')).backgroundColor")) == "#e0b50f", "범례 표식도 같은 노랑")

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
    hero_hex = lambda: "#%02x%02x%02x" % tuple(int(x) for x in page.evaluate("getComputedStyle(document.getElementById('hero')).backgroundColor")[4:-1].split(",")[:3])
    token = lambda name: page.evaluate(f"getComputedStyle(document.documentElement).getPropertyValue('{name}').trim()")
    check(hero_hex() == token("--bad-fill"), "실패는 빨강으로 채움")
    db_patch(f"{LIVE}/programs/routine", {"state": "crashed", "reason": "프로그램이 중간에 사라졌습니다"})
    page.wait_for_function("document.getElementById('hero')?.dataset.state === 'crashed'", timeout=10000)
    check(hero_hex() == token("--warn-fill"), "비정상 종료(오류)는 노랑으로 채움")
    check(page.text_content("#h-state") == "오류", "상태 카드 제목도 '오류' (도넛·기록 표와 같은 말)")
    db_patch(f"{LIVE}/heartbeat", {"at": NOW - 900})
    page.wait_for_function("document.getElementById('h-state')?.textContent === 'PC 연결 끊김'", timeout=10000)
    check(page.get_attribute("#hero", "data-state") == "offline" and hero_hex() == token("--warn-fill"), "연결 끊김도 노랑")
    check("15분 전부터" in page.text_content("#h-line1"), "끊긴 시간")
    db_patch(f"{LIVE}/heartbeat", {"at": NOW + 3600})
    db_patch(f"{LIVE}/programs/routine", routine)
    page.wait_for_function("document.getElementById('h-state')?.textContent === '성공'", timeout=10000)
    # 진행 중엔 시작 시각부터 흐른 시간이 1초마다 올라간다 (mm:ss, 1시간 넘으면 HH:mm:ss)
    iso = lambda ago_s: time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - ago_s))
    db_patch(f"{LIVE}/programs/routine", {"state": "running", "started_at": iso(65), "updated_at": iso(0),
                                          "steps_done": 0, "steps_total": 15, "current_label": "ERPia 로그인", "reason": None})
    page.wait_for_function("document.getElementById('h-state')?.textContent === '진행 중'", timeout=10000)
    t1 = page.text_content("#h-line2")
    check(page.evaluate("/^01:0[5-7] \\| ERPia 로그인$/.test(document.getElementById('h-line2').textContent)"), f"둘째 줄은 '흐른 시간 | 지금 단계' ({t1})")
    check("ERPia 로그인" not in page.text_content("#h-line1"), "첫째 줄엔 단계 이름이 없다")
    page.wait_for_timeout(2100)
    t2 = page.text_content("#h-line2")
    check(t2 != t1 and page.evaluate("/^01:(0[6-9]|1\\d) \\|/.test(document.getElementById('h-line2').textContent)"), f"1초마다 올라간다 ({t1} → {t2})")
    db_patch(f"{LIVE}/programs/routine", {"started_at": iso(3725), "current_label": "물류 관리 화면 이동 " * 12})
    page.wait_for_function("/^01:02:0\\d \\|/.test(document.getElementById('h-line2')?.textContent || '')", timeout=10000)
    check(True, f"1시간 넘으면 HH:mm:ss ({page.text_content('#h-line2')[:14]}…)")
    l2css = page.evaluate("(() => { const s = getComputedStyle(document.getElementById('h-line2')); const e = document.getElementById('h-line2'); return [s.textOverflow, s.whiteSpace, e.scrollWidth > e.clientWidth]; })()")
    check(l2css == ["ellipsis", "nowrap", True], f"긴 단계 이름은 한 줄로 … 처리 ({l2css})")
    # 끊긴 시간은 초·분·시간·일 한 단위로 (상태 카드와 연결 칸 둘 다)
    for age, want in ((30, "초"), (7200, "2시간"), (2 * 86400, "2일")):
        db_patch(f"{LIVE}/heartbeat", {"at": int(time.time()) - age})
        page.wait_for_function(f"(document.getElementById('h-line1')?.textContent || '').includes('{want} 전부터 응답 없음')", timeout=10000)
        conn_t = page.text_content("#conn")
        check("끊김 " in conn_t and want in conn_t, f"{age}초 전 끊김 → '{want} 전부터 응답 없음', 연결 칸 '끊김 …{want}' ({conn_t.strip()})")
    db_patch(f"{LIVE}/heartbeat", {"at": NOW + 3600})
    db_patch(f"{LIVE}/programs/routine", routine)
    page.wait_for_function("document.getElementById('h-state')?.textContent === '성공'", timeout=10000)
    # 에이전트가 죽으면 값이 안 바뀐다. 화면이 1초마다 스스로 다시 봐야 끊김이 보인다
    db_patch(f"{LIVE}/heartbeat", {"at": int(time.time()) - 17})   # 아직 20초 안 → 정상, 몇 초 뒤 끊김
    page.wait_for_function("document.getElementById('conn')?.textContent.includes('정상')", timeout=10000)
    page.wait_for_function("document.getElementById('conn')?.textContent.includes('끊김')", timeout=15000)
    check("초" in page.text_content("#conn") and page.get_attribute("#hero", "data-state") == "offline",
          f"값이 안 바뀌어도 5초 안에 끊김으로 바뀐다 ({page.text_content('#conn').strip()})")
    # 아직 안 고친 옛 에이전트(30초 주기, every 없음)는 25초 된 신호로도 끊김이 아니어야 한다
    db_patch(f"{LIVE}/heartbeat", {"at": int(time.time()) - 25, "every": None})
    page.wait_for_function("document.getElementById('conn')?.textContent.includes('정상')", timeout=10000)
    check(page.get_attribute("#hero", "data-state") != "offline", "every 없는 옛 에이전트는 25초 지나도 정상")
    db_patch(f"{LIVE}/heartbeat", {"at": int(time.time()) - 100})
    page.wait_for_function("document.getElementById('conn')?.textContent.includes('끊김')", timeout=15000)
    check(page.get_attribute("#hero", "data-state") == "offline", "옛 에이전트도 100초 넘게 없으면 끊김")
    db_patch(f"{LIVE}/heartbeat", {"at": NOW + 3600, "every": 5})
    page.wait_for_function("document.getElementById('h-state')?.textContent === '성공'", timeout=10000)

    print("4절 명령 투입")
    page.click("#run-routine")
    page.wait_for_selector("#toasts .toast")
    check("보냈습니다" in page.text_content("#toasts") and page.locator('#toasts [data-id="act"].info').count() == 1,
          "보냈다는 안내가 토스트로")
    check(page.locator("#act-alert").count() == 0, "카드 안 안내 상자는 없앴다")
    time.sleep(1.0)
    launched = cmds_of("launch")
    check(len(launched) == 1, "명령이 하나 만들어졌다")
    c = launched[0] if launched else {}
    check(c.get("state") == "queued" and c.get("by") == admin_uid and c.get("args", {}).get("target") == "routine", "launch / queued / by / target")
    check(590 <= c.get("expires_at", 0) - c.get("created_at", 0) <= 610, "만료 10분")
    check(page.is_disabled("#run-routine") and page.is_disabled("#run-all"), "응답 대기 중 버튼 잠금")
    key = next(k for k, v in (db_get(CMDS) or {}).items() if v.get("type") == "launch")
    db_patch(f"{CMDS}/{key}", {"state": "done", "result": "루틴 RPA 을(를) 띄웠습니다", "started_at": 1, "ended_at": 2})
    page.wait_for_function("(document.getElementById('toasts')?.textContent || '').includes('띄웠습니다')", timeout=10000)
    check(page.locator('#toasts [data-id="act"]').count() == 1, "명령 안내는 쌓이지 않고 그 자리에서 바뀐다")
    check(page.locator('#toasts [data-id="act"].ok').count() == 1, "done 이면 초록 토스트")
    page.wait_for_function("document.querySelectorAll('#toasts .toast').length === 0", timeout=10000)
    check(True, "몇 초 뒤 스스로 사라진다 (상태 카드가 보여 주니까)")
    page.wait_for_function("document.getElementById('run-routine')?.disabled === false", timeout=5000)
    check(True, "끝나면 버튼이 풀린다")

    print("5절 실행 모듈 (관리 > 환경설정)")
    goto(page, "settings")
    check(page.text_content("#page-title") == "환경설정" and page.text_content(".app-settings .app-title") == "RPA",
          "환경설정 페이지: 제목과 앱 이름 머리")
    page.wait_for_function("document.getElementById('mod-meta')?.textContent === '4/5 켬'", timeout=10000)
    check(page.is_disabled("#mod-apply"), "바뀐 게 없으면 적용 비활성")
    login_cb = page.locator("#mod-list input[aria-label='로그인']")
    check(login_cb.is_checked() and login_cb.is_disabled(), "로그인 모듈은 켜진 채 잠김 (관리자도 못 끔)")
    page.locator("#mod-list label:nth-child(1)").click(force=True)   # 잠긴 스위치라 Playwright 가 '비활성' 으로 본다
    check(login_cb.is_checked() and "4/5 켬" in page.text_content("#mod-meta"), "눌러도 안 꺼진다")
    page.click("#mod-list label:nth-child(2)")     # 스위치의 input 은 숨겨져 있어 label 을 누른다
    check("5/5 켬" in page.text_content("#mod-meta") and not page.is_disabled("#mod-apply"), "켜면 요약·적용 활성")
    # 운송장 출력은 물류관리가 켜져 있어야 쓸 수 있다 (켜져 있어도 끄는 건 자유)
    out_cb = page.locator("#mod-list input[aria-label='운송장 출력 / 엑셀 생성']")
    logi_row, out_row = "#mod-list label:nth-child(4)", "#mod-list label:nth-child(5)"
    check(out_cb.is_checked() and not out_cb.is_disabled(), "물류관리가 켜져 있으면 출력 스위치는 자유")
    page.click(out_row)
    check(not out_cb.is_checked() and not out_cb.is_disabled(), "물류관리가 켜져 있어도 출력만 끌 수 있다")
    page.click(out_row)
    page.click(logi_row)                                   # 물류관리 끄기 → 출력도 따라 꺼지고 잠긴다
    check(not out_cb.is_checked() and out_cb.is_disabled(), "물류관리를 끄면 출력도 꺼지고 잠긴다")
    check("3/5 켬" in page.text_content("#mod-meta"), f"둘 다 꺼진 개수 ({page.text_content('#mod-meta')})")
    why = page.text_content(f"{out_row} .why") if page.locator(f"{out_row} .why").count() else None
    check(why == "물류관리를 켜야 쓸 수 있습니다" and page.is_visible(f"{out_row} .why"),
          f"잠긴 이유를 줄 아래 글로 보여 준다 - 휴대폰에는 마우스 글(title)이 없다 ({why})")
    if os.environ.get("SHOT_DIR"): page.locator("#mod-card").screenshot(path=os.path.join(os.environ["SHOT_DIR"], "mod_why.png"))
    page.click(out_row, force=True)   # 잠긴 스위치라 Playwright 가 '비활성' 으로 본다
    check(not out_cb.is_checked(), "잠긴 동안은 눌러도 안 켜진다")
    page.click(logi_row)                                   # 물류관리 다시 켜기
    check(not out_cb.is_checked() and not out_cb.is_disabled(), "물류관리를 켜도 출력은 꺼진 채, 잠금만 풀린다")
    page.click(out_row)
    check(out_cb.is_checked() and "5/5 켬" in page.text_content("#mod-meta"), "그 뒤에 출력을 켤 수 있다")
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
    # 업체가 안 쓰는 모듈 (총괄이 meta 에 false 로 적는다) 은 목록에서 숨는다
    db_patch("meta/companies/c_demo/apps/rpa/modules", {"Hold": False})
    reload_to(page, "settings"); page.wait_for_selector("#mod-list label")
    check(page.locator("#mod-list input[aria-label='물류대기 관리']").count() == 0, "안 쓰는 업체면 그 스위치가 아예 없다")
    check(page.locator("#mod-list label").count() == 4 and "4 켬" in page.text_content("#mod-meta"), f"개수도 빼고 센다 ({page.text_content('#mod-meta')})")
    check(page.is_disabled("#mod-apply"), "숨긴 것 때문에 '바뀜' 으로 보이지 않는다")
    page.click("#mod-list label:nth-child(2)"); page.click("#mod-apply"); time.sleep(1.5)
    sent = cmds_of("set_modules")[-1]["args"]
    check(sent["Hold"] is False, f"명령에도 꺼진 값으로 나간다 ({sent})")
    db_patch("meta/companies/c_demo/apps/rpa", {"modules": None})   # null 로 PATCH = 그 자리 지우기 (PUT 은 본문이 비면 400)
    reload_to(page, "settings"); page.wait_for_selector("#mod-list label")
    check(page.locator("#mod-list label").count() == 5, "정책을 지우면 다시 보인다")
    # 웰라이프 업체 (설계 2026-10-07-wellife-gate): 모듈 다섯, '전체' 시각만. 줄 고르기는 v2 PC 에서만 보이니 v2 live 를 먼저 만든다
    rule = page.evaluate("import('./rpa-common.js').then(m => [m.wellifeOn('WELLIFE_x', null), m.wellifeOn('my_wellife', {}), m.wellifeOn('wel_life', null),"
                         "m.wellifeOn('c_demo', {rpa: {features: {wellife: true}}}), m.wellifeOn('c_demo', {rpa: {features: {wellife: false}}})])")
    check(rule == [True, True, False, True, False], f"웹 판정 규칙이 에이전트·관리 화면과 같다 ({rule})")
    sch0 = db_get(f"{LIVE}/schedule") or {}
    db_patch(f"{LIVE}/schedule", {"version": 2, "slots": [{"at": "09:05"}], "times": None})
    reload_to(page, "settings"); page.wait_for_selector("#sch-times select.mode")
    db_patch("meta/companies/c_demo/apps/rpa", {"features": {"wellife": True}})
    reload_to(page, "settings"); page.wait_for_selector("#mod-list label")
    names = [x.strip() for x in page.locator("#mod-list label").all_text_contents()]
    check(len(names) == 5 and any("웰라이프 SAP 연동관리" in n for n in names) and any("웰라이프 WMS 이관관리" in n for n in names)
          and not any("물류관리" == n or "운송장" in n for n in names), f"웰라이프 업체: 모듈 다섯 (물류관리·운송장 없음) ({names})")
    check(not page.is_visible("#sch-add-win") and page.locator("#sch-times select.mode").count() == 0,
          "웰라이프 업체: '전체' 시각만 (고르기·반복 시간대 숨김)")
    # PC 에 반복·고르기 줄이 올라와 있어도 보내는 값은 '전체' 줄뿐 (에이전트가 그런 줄을 거절한다), 모듈은 다섯 키만
    cmds0, mods0, sets0 = db_get(CMDS), db_get(f"{SETTINGS}/modules"), db_get(f"{SETTINGS}/schedule")
    db_patch("meta/companies/c_demo/apps/rpa", {"limits": {"schedule": 4}})
    db_patch(f"{LIVE}/schedule", {"enabled": True, "days": list(range(7)), "slots": [
        {"at": "09:05"}, {"at": "10:00", "run": ["Login", "Logistics"]},
        {"at": "11:00", "until": "12:00", "rest_min": 3, "run": ["Login", "Logistics"]}]})
    reload_to(page, "settings"); page.wait_for_selector("#sch-times .t")
    check(page.locator("#sch-times select").count() == 0 and page.locator("#sch-times .chips").count() == 0
          and page.locator("#sch-times .t").count() == 3, "웰라이프 업체: PC 의 반복·고르기 줄도 '전체' 시각 줄로 보인다")
    first = page.query_selector_all("#sch-times input")[0]
    first.fill("09:10"); first.dispatch_event("change")
    page.click("#sch-apply"); time.sleep(1.5)
    saved = (db_get(f"{SETTINGS}/schedule") or {}).get("slots") or []
    check([s.get("at") for s in saved] == ["09:10", "10:00", "11:00"] and not any("run" in s or "until" in s for s in saved),
          f"웰라이프 업체: 보내는 줄에 run·until 이 없고 시각은 그대로 ({saved})")
    for k, v in (db_get(CMDS) or {}).items():   # 보낸 명령을 닫아야 단추 잠금이 풀린다
        if v.get("state") == "queued": db_patch(f"{CMDS}/{k}", {"state": "done", "result": "ok", "started_at": 1, "ended_at": 2})
    page.wait_for_function("!document.getElementById('sch-apply')?.disabled || document.querySelector('#mod-list input')?.disabled === false", timeout=10000)
    page.click("#mod-list label:nth-child(2)"); page.click("#mod-apply"); time.sleep(1.5)
    keys =sorted((db_get(f"{SETTINGS}/modules") or {}).keys())
    check(keys == ["Hold", "Login", "Sales", "Sap", "Wms"], f"웰라이프 업체: 모듈은 다섯 키만 저장 ({keys})")
    db_patch("meta/companies/c_demo/apps/rpa", {"modules": {"Hold": False}})   # 업체가 끈 모듈은 웰라이프 업체에서도 스위치가 없다 (에이전트가 꺼진 값으로 강제한다)
    reload_to(page, "settings"); page.wait_for_selector("#mod-list label")
    check(page.locator("#mod-list label").count() == 4 and page.locator("#mod-list input[aria-label='물류대기 관리']").count() == 0,
          "웰라이프 업체: 업체가 끈 모듈(물류대기 관리)은 스위치가 없다")
    db_patch("meta/companies/c_demo/apps/rpa", {"modules": None, "limits": None})
    for path, old in ((CMDS, cmds0), (f"{SETTINGS}/modules", mods0), (f"{SETTINGS}/schedule", sets0)):   # 이 블록이 쓴 것을 되돌린다
        if old: db_put(path, old)
        else: db_patch(path, {k: None for k in (db_get(path) or {})})
    db_patch("meta/companies/c_demo/apps/rpa", {"features": None})
    reload_to(page, "settings"); page.wait_for_selector("#mod-list label")
    check(page.locator("#mod-list label").count() == 5 and page.locator("#mod-list input[aria-label='물류관리']").count() == 1,
          "보통 업체로 돌아오면 지금 그대로")
    db_patch(f"{LIVE}/schedule", {**{k: None for k in ("version", "slots", "times")}, **sch0})   # v2 live 를 원래대로

    goto(page, "rpa")
    # RPA 가 도는 동안에는 실행 버튼을 잠근다 (다른 사람이 겹쳐 실행하지 않게). 종료 버튼만 열어 둔다
    db_patch(f"{LIVE}/programs/routine", {"state": "running", "started_at": f"{TODAY}T16:20:00", "updated_at": f"{TODAY}T16:20:28",
                                          "steps_done": 1, "steps_total": 15, "current_label": "주문매핑 화면 이동", "reason": None,
                                          "steps": [{"key": "login", "label": "ERPia 로그인", "state": "done"},
                                                    {"key": "sales", "label": "주문매핑 화면 이동", "state": "running"},
                                                    {"key": "top", "label": "상단 선택", "state": "pending"}]})
    page.wait_for_function("document.getElementById('run-routine')?.disabled === true", timeout=10000)
    page.wait_for_function("(document.getElementById('toasts')?.textContent || '').includes('시작했습니다')", timeout=10000)
    check(page.locator("#toasts .toast.info", has_text="시작했습니다").count() == 1, "RPA 가 시작되면 파란 토스트")
    check(all(page.is_disabled(f"#{i}") for i in ("run-all", "run-prepare", "run-routine")), "도는 중에는 실행 버튼 셋 다 잠김")
    check(not page.is_disabled("#stop-erpia"), "ERPia 종료는 도는 중에도 누를 수 있다")
    check("돌고 있어" in (page.get_attribute("#run-all", "title") or ""), "잠긴 이유를 알려 준다")
    check(page.text_content("#run-routine .t") == "루틴 RPA 실행중" and page.is_hidden("#run-routine .fly")
          and page.text_content("#run-prepare .t") == "프리페어 RPA" and page.is_visible("#run-prepare .fly"),
          f"도는 RPA 의 단추는 '… 실행중' (화살표 없이), 다른 단추는 그대로 ({page.text_content('#run-routine .t')})")
    if os.environ.get("SHOT_DIR"): page.locator("#act-card").screenshot(path=os.path.join(os.environ["SHOT_DIR"], "act_busy.png"))
    # 진행 중 단계 점만 숨쉬고, 로그가 늘어도 애니메이션이 처음부터 다시 돌지 않는다 (목록을 제자리에서 고친다)
    anim = lambda sel: page.evaluate(f"getComputedStyle(document.querySelector({sel!r})).animationName")
    check(anim("#list-routine li.running .mark") == "step-glow", "진행 중 점이 숨쉰다")
    check(anim("#hero .dot") == "hero-glow", "상태 카드 점도 같이 숨쉰다")
    check(anim("#list-routine li.done .mark") == "none" and anim("#list-routine li.pending .mark") == "none", "끝난·대기 단계는 안 움직인다")
    mark_id = "document.querySelector('#list-routine li.running .mark')"
    page.evaluate(f"window.__mark = {mark_id}")
    db_patch(f"{LIVE}/programs/routine", {"updated_at": f"{TODAY}T16:20:30",
                                          "steps": [{"key": "login", "label": "ERPia 로그인", "state": "done"},
                                                    {"key": "sales", "label": "주문매핑 화면 이동", "state": "running", "note": "주문 가져오는 중"},
                                                    {"key": "top", "label": "상단 선택", "state": "pending"}]})
    page.wait_for_function("(document.getElementById('log')?.textContent || '').includes('주문매핑 화면 이동 진행 중')", timeout=10000)
    check(page.evaluate(f"window.__mark === {mark_id}"), "메모가 바뀌어도 진행 중 점은 그대로 (애니메이션이 안 끊긴다)")
    check(page.evaluate("""() => { const n = document.querySelector('#list-routine li.running .note');
      return getComputedStyle(n).textOverflow === 'ellipsis' && n.title === '주문 가져오는 중'; }"""), "긴 메모는 … 로 자르고 제목으로 전체를 보여 준다")
    db_patch(f"{LIVE}/programs/routine", {"steps": [{"key": "login", "label": "ERPia 로그인", "state": "done"},
                                                    {"key": "sales", "label": "주문매핑 화면 이동", "state": "done"},
                                                    {"key": "top", "label": "상단 선택", "state": "running"}]})
    page.wait_for_function("document.querySelectorAll('#list-routine li.done').length === 2", timeout=10000)
    check(anim("#list-routine li.running .mark") == "step-glow" and page.text_content("#list-routine li:nth-child(3) .note") == "진행 중",
          "단계가 넘어가면 다음 줄로 옮겨 간다")
    db_patch(f"{LIVE}/programs/routine", {"state": "crashed", "reason": "프로그램이 사라졌습니다", "finished_at": f"{TODAY}T16:22:00"})
    page.wait_for_function("(document.getElementById('toasts')?.textContent || '').includes('오류')", timeout=10000)
    check(page.locator("#toasts .toast.warn", has_text="오류").count() == 1, "죽으면 노란 토스트 (오류)")
    page.wait_for_function("document.querySelector('#run-routine .t')?.textContent === '루틴 RPA'", timeout=10000)
    check(not page.is_disabled("#run-routine") and page.is_visible("#run-routine .fly"),
          "끝나면 (오류로 끝나도) '→ 루틴 RPA' 로 돌아와 다시 누를 수 있다")
    db_patch(f"{LIVE}/programs/routine", routine)
    page.wait_for_function("(document.getElementById('toasts')?.textContent || '').includes('루틴 RPA 성공')", timeout=10000)
    check(page.locator("#toasts .toast.ok", has_text="루틴 RPA 성공").count() == 1, "끝나면 초록 토스트 (성공 · 소요)")
    page.wait_for_function("document.getElementById('run-routine')?.disabled === false", timeout=10000)
    check(True, "끝나면 다시 눌린다")
    # 띄우자마자 상태 파일에 아직 running 이 안 찍힌 몇 초 (에이전트가 launching 으로 알려 준다)
    db_patch(LIVE, {"launching": True})
    page.wait_for_function("document.getElementById('run-routine')?.disabled === true", timeout=10000)
    check(page.is_disabled("#run-all") and not page.is_disabled("#stop-erpia"), "띄우는 중에도 실행 버튼은 잠긴다")
    db_patch(LIVE, {"launching": False})
    page.wait_for_function("document.getElementById('run-routine')?.disabled === false", timeout=10000)
    check(True, "띄우기가 끝나면 풀린다")

    # 토큰 (2026-10-06, 2부): 실행 단추 아래 늘 보이는 한 줄 - 통장이 없으면 없음, 평소 회색, 모자라면 노랑, 0 이하면 빨강 + 단추 잠금.
    # 예약 칸에도 (지켜볼 사람이 없는 실행이라)
    check(page.is_hidden("#token-line") and page.is_hidden("#usage-card"), "통장이 없는 업체는 토큰 줄도 사용량도 없다")
    # 3부 이번 달 사용량: 통장(이달 1일 시작)과 이번 달 기록 셋 - 끝나면 지운다 (기록 탭 시험이 이 시드를 모른다)
    month = time.strftime("%Y-%m")
    first_day = TODAY == f"{month}-01"
    usage_runs = {"u_month": (f"{month}-01T00:00:01", {"hold": 4}, 4),
                  "u_today1": (f"{TODAY}T08:00:00", {"login": 1, "sales": 1, "logistics": 1}, 2),
                  "u_today2": (f"{TODAY}T09:00:00", {"logistics": 1, "sites": 2}, 3)}
    call("PATCH", f"{FS}/wallet/c_demo", {"fields": {"granted": {"integerValue": "500"}, "since": {"stringValue": f"{month}-01T00:00:00"}}}, OWNER)
    for rid, (started, used, spent) in usage_runs.items():
        call("POST", f"{FS}/runs/c_demo/items?documentId={rid}", {"fields": {
            **fs_fields({"cid": "c_demo", "pcId": "pc_office", "run_id": rid, "program": "routine", "state": "success",
                         "started_at": started, "date": started[:10], "cost": spent, "payload": "{}"}),
            "used": {"mapValue": {"fields": {k: {"integerValue": str(n)} for k, n in used.items()}}}}}, OWNER)
    cost = {"all": 6, "prepare": 2, "routine": 4}
    db_patch(LIVE, {"tokens": {"balance": 120, "cost": cost}})
    page.wait_for_function("document.getElementById('token-line')?.hidden === false", timeout=10000)
    check(page.text_content("#token-line") == "남은 토큰 120개 · 전체 실행 1번에 6개"
          and page.get_attribute("#token-line", "class") == "msg", f"평소: 회색 한 줄 ({page.text_content('#token-line')})")
    page.wait_for_function("!document.getElementById('usage-card')?.classList.contains('hide')", timeout=10000)
    rows = page.evaluate("[...document.querySelectorAll('#usage-list .u-row')].map((r) => r.children[0].textContent + ' ' + r.children[1].textContent)")
    check(rows == ["주문매핑 매출처리 1회", "물류대기 관리 4회", "물류관리 2회", "쇼핑몰·사이트 받기 2회"],
          f"이번 달 사용량: 모듈별 횟수 (모듈 순서, 0회·로그인은 안 보임) ({rows})")
    check(page.text_content("#usage-sum") == f"합계 9개 · 오늘 {9 if first_day else 5}개"
          and page.text_content("#usage-meta") == f"({int(month[5:])}월 1일부터)",
          f"합계·오늘은 서버가 더한 쓴 토큰, 이달 1일부터 ({page.text_content('#usage-meta')} {page.text_content('#usage-sum')})")
    # 토큰 정보(통장)를 이달 중간에 만들었으면 그날부터 - 남은 토큰이 바뀌어야 다시 읽는다 (2026-10-06 이름: 통장 시작 → 토큰 정보 생성)
    call("PATCH", f"{FS}/wallet/c_demo", {"fields": {"granted": {"integerValue": "500"}, "since": {"stringValue": f"{TODAY}T00:00:00"}}}, OWNER)
    db_patch(LIVE, {"tokens": {"balance": 121, "cost": cost}})
    want = f"({int(month[5:])}월 1일부터)" if first_day else f"({int(TODAY[5:7])}월 {int(TODAY[8:10])}일 토큰 정보 생성부터)"
    try:
        page.wait_for_function(f"document.getElementById('usage-meta')?.textContent === {json.dumps(want)}", timeout=10000)
    except Exception:
        pass
    check(page.text_content("#usage-meta") == want, f"토큰 정보를 이달 중간에 만들었으면 그날부터 ({page.text_content('#usage-meta')})")
    db_patch(LIVE, {"tokens": {"balance": 3, "cost": cost}})
    page.wait_for_function("document.getElementById('token-line')?.classList.contains('warn')", timeout=10000)
    check(page.text_content("#token-line") == "남은 토큰 3개 · 전체 실행 1번에 6개 - 마이너스로 떨어질 수 있습니다"
          and not page.is_disabled("#run-all"), f"모자라면 노란 글, 실행은 된다 ({page.text_content('#token-line')})")
    goto(page, "settings")
    page.wait_for_function("(document.getElementById('sch-info')?.textContent || '').includes('남은 3개')", timeout=10000)
    check("다음 예약 실행에 6개 · 남은 3개 - 마이너스로 떨어질 수 있습니다" in page.text_content("#sch-info")
          and "warn" in page.get_attribute("#sch-info", "class"), f"예약 칸에도 노란 글 ({page.text_content('#sch-info')})")
    goto(page, "rpa")
    db_patch(LIVE, {"tokens": {"balance": 0, "cost": cost}})
    page.wait_for_function("document.getElementById('run-all')?.disabled === true", timeout=10000)
    check(page.text_content("#token-line") == "토큰이 없습니다 (남은 0개) - 충전한 뒤 실행하세요"
          and "bad" in page.get_attribute("#token-line", "class")
          and all(page.is_disabled(f"#{i}") for i in ("run-all", "run-prepare", "run-routine")) and not page.is_disabled("#stop-erpia"),
          "0 이하면 빨간 글, 실행 단추 셋 잠김 (ERPia 종료는 그대로)")
    goto(page, "settings")
    page.wait_for_function("(document.getElementById('sch-info')?.textContent || '').includes('토큰이 없어')", timeout=10000)
    check("토큰이 없어 예약 실행을 건너뜁니다" in page.text_content("#sch-info") and "bad" in page.get_attribute("#sch-info", "class"),
          f"예약 칸: 건너뛴다고 빨간 글 ({page.text_content('#sch-info')})")
    goto(page, "rpa")
    db_patch(LIVE, {"tokens": None})                   # PATCH 의 null 이 그 칸을 지운다 (call 은 None 이면 본문 없이 보낸다)
    page.wait_for_function("document.getElementById('token-line')?.hidden === true", timeout=10000)
    check(not page.is_disabled("#run-all") and page.is_hidden("#usage-card"), "통장이 사라지면 (옛 에이전트) 줄도 잠금도 사용량도 없다")
    goto(page, "settings")
    page.wait_for_function("document.getElementById('sch-meta')?.textContent !== ''", timeout=10000)
    check("토큰" not in page.text_content("#sch-info"), "예약 칸의 토큰 글도 없다")
    for rid in usage_runs:
        call("DELETE", f"{FS}/runs/c_demo/items/{rid}", None, OWNER)
    call("DELETE", f"{FS}/wallet/c_demo", None, OWNER)

    print("5-2절 쇼핑몰 프리셋")
    SHOPS = [{"no": 1, "name": "지마켓", "code": "012", "steps": 12, "saved_at": "2026-09-30T18:20:00", "has_login": True, "on": False},
             {"no": 2, "name": "<b>몰</b>", "code": "", "steps": 0, "has_login": False, "on": False}]
    check(page.is_hidden("#shop-card"), "옛 에이전트(프리셋을 안 올림)면 카드가 없다")
    db_patch(LIVE, {"presets": SHOPS})
    page.wait_for_function("document.querySelectorAll('#shop-list label').length === 2", timeout=10000)
    first = page.text_content("#shop-list label:nth-child(1)")
    check("① 지마켓 (012) · 12단계 · 9/30 저장" in first, f"줄 글자 ({first})")
    check(page.text_content("#shop-list label:nth-child(2)").startswith("② <b>몰</b>")
          and page.locator("#shop-list b").count() == 0, "이름의 꺾쇠는 글자 그대로 (태그가 아니다 - Review Focus 5)")
    check(page.locator("#shop-list label:nth-child(2) input").is_disabled()
          and "옵저버에서 기록하고 저장하세요" == (page.text_content("#shop-list label:nth-child(2) .why") or "")
          and page.locator("#shop-list label:nth-child(1) .why").count() == 0,
          "기록이 없는 줄은 스위치가 잠기고 까닭이 줄 아래 글로 보인다 (준비된 줄에는 없다)")
    if os.environ.get("SHOT_DIR"): page.locator("#shop-card").screenshot(path=os.path.join(os.environ["SHOT_DIR"], "shop_why.png"))
    check(page.is_disabled("#shop-apply") and "0/2 켬" in page.text_content("#shop-meta"), "바뀐 게 없으면 적용 비활성")
    page.click("#shop-list label:nth-child(1)")
    check(not page.is_disabled("#shop-apply") and "1/2 켬" in page.text_content("#shop-meta"), "켜면 요약·적용 활성")
    page.click("#shop-apply")
    time.sleep(1.5)
    check(db_get(f"{SETTINGS}/presets") == {"PRESET1": True, "PRESET2": False}, f"settings.presets 에 저장 ({db_get(f'{SETTINGS}/presets')})")
    sent = cmds_of("set_presets")
    check(len(sent) == 1 and sent[0]["args"] == {"PRESET1": True, "PRESET2": False}, f"set_presets 명령 ({sent})")
    key = next(k for k, v in (db_get(CMDS) or {}).items() if v.get("type") == "set_presets")
    db_patch(f"{CMDS}/{key}", {"state": "done", "result": "프리셋을 바꿨습니다 (켬: ① 지마켓)", "started_at": 1, "ended_at": 2})
    db_put(f"{LIVE}/presets/0/on", True)
    page.wait_for_function("document.getElementById('shop-apply')?.disabled === true", timeout=10000)
    check("1/2 켬" in page.text_content("#shop-meta"), "PC 값이 돌아오면 기준값 갱신")

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
    check(page.is_disabled("#sch-add"), "시간은 2개까지 (추가 버튼 잠김)")
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
    check(page.is_visible("#sch-old") and page.locator("#sch-times select").count() == 0,
          "옛 판 PC (live.schedule 에 version 없음): 시각만, 새 판 안내가 보인다 (Review Focus 4)")
    # 새 판 PC (2부): 줄마다 전체/고르기
    db_patch(f"{LIVE}/schedule", {"version": 2, "slots": [{"at": "09:05"}, {"at": "13:30"}], "times": None, "next_slot": "13:30",
                                  "next_run_at": "2026-09-22T13:30:00"})
    page.wait_for_function("document.querySelectorAll('#sch-times select').length === 2", timeout=10000)
    check(page.is_hidden("#sch-old") and page.text_content("#sch-count") == "2/2 사용", "새 판 PC: 줄마다 고르기, 한도 2 중 2 사용")
    check(page.text_content("#sch-full") == "자동 실행 슬롯은 최대 2개까지입니다. 추가를 원하시면 ERPia에 문의해주세요." and page.is_disabled("#sch-add"),
          f"한도에 닿으면 추가 잠김 + 문의 안내 (사용자 문구 2026-10-08) ({page.text_content('#sch-full')})")
    order = page.evaluate("['sch-limit','sch-warn','sch-full'].map(i => document.getElementById(i)).every((e, i, a) => !i || a[i - 1].compareDocumentPosition(e) & Node.DOCUMENT_POSITION_FOLLOWING)")
    check("good" in page.get_attribute("#sch-full", "class") and order,
          "문의 안내는 초록·가장 아래 (빨강 > 호박색 > 초록, 사용자 2026-10-08)")
    check("전체 실행과 '전체 모듈 실행' 예약이 이 모듈을 돌립니다" in page.text_content("#mod-card"), "실행 모듈 카드: '전체 모듈 실행' 의 뜻")
    page.select_option("#sch-times .t:nth-child(2) select", "pick")
    chips = "#sch-times .t:nth-child(2) .chips button"
    check(page.locator(chips).count() == 5 and page.is_disabled("#sch-apply") and "모듈을 하나 이상" in page.text_content("#sch-limit"),
          "고르기: 모듈 단추 다섯, 하나도 안 고르면 적용 안 됨")
    check(page.is_disabled(f"{chips}[data-k='Output']"), "운송장은 물류관리를 고르기 전엔 잠김")
    page.click(f"{chips}[data-k='Logistics']")
    check(not page.is_disabled("#sch-apply") and not page.is_disabled(f"{chips}[data-k='Output']"), "물류관리를 고르면 적용 가능·운송장 풀림")
    page.click("#sch-apply"); time.sleep(1.5)
    asked = []
    def on_dialog(dlg):
        asked.append(dlg.message); dlg.dismiss()
    page.on("dialog", on_dialog)
    page.click("#app-nav a[data-key='rpa']"); page.wait_for_timeout(500)
    page.remove_listener("dialog", on_dialog)
    check(asked == [] and page.text_content("#page-title") == "RPA", f"적용을 누른 뒤 PC 응답 전에 떠나도 '적용 안 한 변경' 으로 묻지 않는다 ({asked})")
    goto(page, "settings")
    saved = db_get(f"{SETTINGS}/schedule") or {}
    check(saved.get("slots") == [{"at": "09:05"}, {"at": "13:30", "run": ["Logistics"]}] and "times" not in saved,
          f"새 모양으로 저장 - '전체' 줄엔 run 없음 ({saved.get('slots')})")
    key = [k for k, v in (db_get(CMDS) or {}).items() if v.get("type") == "set_schedule"][-1]
    db_patch(f"{CMDS}/{key}", {"state": "done", "result": "자동 실행: 매일 09:05, 13:30 물류관리", "started_at": 1, "ended_at": 2})
    db_patch(f"{LIVE}/schedule", {"slots": [{"at": "09:05"}, {"at": "13:30", "run": ["Login", "Logistics"]}]})
    page.wait_for_function("document.getElementById('sch-meta')?.textContent === '매일 09:05, 13:30 물류관리'", timeout=10000)
    check(page.is_disabled("#sch-apply"), "PC 가 로그인을 붙여 돌려줘도 같은 값 (바뀜 없음)")
    check("(물류관리)" in page.text_content("#sch-info"), f"다음 실행 글에 그 줄의 모듈 ({page.text_content('#sch-info')})")
    db_patch("meta/companies/c_demo/apps/rpa", {"limits": {"schedule": 3}})   # 업체 한도는 총괄·관리 도구가 쓴다
    reload_to(page, "settings"); page.wait_for_function("document.querySelectorAll('#sch-times select').length === 2", timeout=10000)
    check(page.text_content("#sch-count") == "2/3 사용" and not page.is_disabled("#sch-add"), "한도 3: 2/3 사용, 추가 가능")
    db_patch("meta/companies/c_demo/apps/rpa", {"limits": {"schedule": 4}})
    try:
        page.wait_for_function("document.getElementById('sch-count')?.textContent === '2/4 사용'", timeout=5000)
        check(True, "업체 한도가 바뀌면 새로고침 없이 바로 (2/4 사용)")
    except Exception:
        check(False, f"업체 한도가 바뀌면 새로고침 없이 바로 ({page.text_content('#sch-count')})")
    db_patch("meta/companies/c_demo/apps/rpa", {"limits": {"schedule": 1}})
    reload_to(page, "settings"); page.wait_for_function("document.querySelectorAll('#sch-times .t.over').length === 1", timeout=10000)
    page.click("#sch-days button:nth-child(7)")
    check("미실행 (한도초과)" in page.text_content("#sch-times .t:nth-child(2)") and page.is_disabled("#sch-apply")
          and "1개까지" in page.text_content("#sch-limit"), "한도를 낮추면 넘는 줄은 '미실행 (한도초과)', 그 상태로 켜 두기는 적용 안 됨")
    page.click("label:has(#sch-enabled)")
    check(not page.is_checked("#sch-enabled") and not page.is_disabled("#sch-apply") and "bad" not in page.get_attribute("#sch-limit", "class"),
          "한도를 넘어도 끄기는 적용할 수 있다")
    db_patch("meta/companies/c_demo/apps/rpa", {"limits": None})
    reload_to(page, "settings")
    db_patch(f"{LIVE}/schedule", {"slots": None})       # 줄이 0개인 새 판 PC - Realtime DB 에선 빈 목록이 사라진다
    page.wait_for_function("document.getElementById('sch-count')?.textContent === '0/2 사용'", timeout=10000)
    check(page.is_hidden("#sch-old"), "줄이 0개여도 version 2 면 새 판으로 본다 (Review Focus 5)")
    db_patch(f"{LIVE}/schedule", {"slots": [{"at": "09:05"}, {"at": "13:30", "run": ["Login", "Logistics"]}]})
    page.wait_for_function("document.querySelectorAll('#sch-times select').length === 2", timeout=10000)
    page.click("label:has(#sch-enabled)")
    page.wait_for_function("document.getElementById('sch-apply')?.disabled === false", timeout=5000)
    page.click("#sch-times .t:nth-child(1) button.del")
    page.click("#sch-times .t:nth-child(1) button.del")
    check(page.is_disabled("#sch-apply") is False, "끄면 시간이 없어도 적용 가능")
    page.click("label:has(#sch-enabled)")
    check(page.is_disabled("#sch-apply"), "켠 채 시간이 없으면 적용 불가")

    # 떠날 때 확인 (1부): 위에서 켬을 다시 켜고 줄을 지운 채 (적용 안 함) 다른 메뉴로 - '아니오' 면 남고, '예' 면 버리고 나간다
    asked = []
    page.once("dialog", lambda dlg: (asked.append(dlg.message), dlg.dismiss()))
    page.click("#app-nav a[data-key='rpa']")
    page.wait_for_timeout(300)
    check(asked == ["적용하지 않은 변경이 있습니다. 버리고 나갈까요?"] and page.text_content("#page-title") == "환경설정"
          and page.is_visible("#sch-card"), f"적용 안 한 변경이 있으면 묻고, 아니오면 남는다 ({asked})")
    asked.clear()
    page.once("dialog", lambda dlg: (asked.append(dlg.message), dlg.dismiss()))
    page.click("#logout-btn")
    page.wait_for_timeout(300)
    check(asked == ["적용하지 않은 변경이 있습니다. 버리고 나갈까요?"] and page.is_visible("#main") and page.is_visible("#sch-card"),
          f"로그아웃도 묻고, 아니오면 남는다 ({asked})")
    check(page.evaluate("() => { const e = new Event('beforeunload', { cancelable: true }); window.dispatchEvent(e); return e.defaultPrevented; }") is True, "탭 닫기·새로고침은 브라우저가 묻는다")
    page.once("dialog", lambda dlg: dlg.accept())
    page.click("#app-nav a[data-key='rpa']")
    page.wait_for_selector("#hero")
    check(page.text_content("#page-title") == "RPA", "예면 버리고 나간다")
    check(page.evaluate("() => { const e = new Event('beforeunload', { cancelable: true }); window.dispatchEvent(e); return e.defaultPrevented; }") is False, "바뀐 것이 없으면 탭을 닫아도 안 묻는다")
    goto(page, "settings")
    page.wait_for_function("document.getElementById('sch-meta')?.textContent === '매일 09:05, 13:30 물류관리'", timeout=10000)
    check(page.is_disabled("#sch-apply") and len(page.query_selector_all("#sch-times input")) == 2, "다시 열면 PC 값 그대로 (버린 변경은 없다)")
    goto(page, "rpa")

    print("6-2절 실행 단추 모양 (RPA 화면)")
    page.wait_for_function("(document.querySelector('#hero .stats')?.textContent || '').includes('물류관리')", timeout=10000)
    check("13:30 · 물류관리" in page.text_content("#hero .stats"), f"상태 띠 다음 자동 실행에 그 줄의 모듈 ({page.text_content('#hero .stats')})")
    check("primary" in (page.get_attribute("#run-all", "class") or "") and "primary" not in (page.get_attribute("#run-routine", "class") or ""), "강조는 전체 실행에")
    check(all(page.locator(f"#{i} svg").count() == 1 for i in ("run-all", "run-prepare", "run-routine")), "실행 버튼은 화살표 아이콘 하나")
    check(page.text_content("#stop-erpia .ic") == "⏼" and page.locator("#stop-erpia svg").count() == 0, "ERPia 종료는 전원 글자 ⏼ (U+23FC)")
    # 표시는 넷 다 동그라미 안 같은 자리 (전원이 화살표보다 오른쪽으로 밀리던 것을 고쳤다)
    spots = page.evaluate("""() => ['run-all', 'run-prepare', 'run-routine', 'stop-erpia'].map((id) => {
      const b = document.getElementById(id), r = b.getBoundingClientRect();
      const i = b.querySelector('.fly').getBoundingClientRect();
      return [Math.round(i.left - r.left), Math.round(i.top - r.top)]; })""")
    check(len({tuple(x) for x in spots}) == 1, f"표시 넷이 같은 자리 ({spots})")
    radius = page.evaluate("""() => [getComputedStyle(document.getElementById('run-routine')).borderRadius,
      getComputedStyle(document.getElementById('act-card')).borderRadius]""")
    check(radius[0] == "12px", f"버튼 모서리는 카드처럼 둥근 네모 ({radius})")
    ic_w = page.evaluate("document.querySelector('#stop-erpia .ic').getBoundingClientRect().width")
    check(ic_w > 10, f"전원 글자가 실제로 그려진다 (폭 {ic_w:.0f}px)")
    check(not page.is_disabled("#stop-erpia"), "종료 버튼 활성")
    stop_bg = page.evaluate("getComputedStyle(document.getElementById('stop-erpia')).backgroundColor")
    check(rgb2hex(stop_bg) == token("--bad-fill"), f"종료 버튼은 빨강 ({stop_bg})")
    check(rgb2hex(page.evaluate("getComputedStyle(document.getElementById('run-routine')).backgroundColor")) == token("--good-fill"),
          "실행 버튼은 초록으로 채워져 있다")
    check(rgb2hex(page.evaluate("getComputedStyle(document.querySelector('#run-routine .t')).color")) == token("--on-fill"),
          "글자는 흰색")
    page.hover("#run-routine"); page.wait_for_timeout(900)
    fly = page.evaluate("""() => { const b = document.getElementById('run-routine'), r = b.getBoundingClientRect();
      const f = b.querySelector('.fly').getBoundingClientRect(), t = b.querySelector('.t');
      return [Math.round(f.left + f.width / 2 - r.left), Math.round(r.width / 2),
              Number(getComputedStyle(t).opacity), getComputedStyle(b.querySelector('.fly')).animationName]; }""")
    check(abs(fly[0] - fly[1]) <= 2 and fly[2] < 0.2, f"올리면 표시가 버튼 한가운데로 가고 글자는 사라진다 ({fly})")
    check(fly[3] == "none", "표시는 떠다니지 않는다 (흔들림 없음)")
    if os.environ.get("SHOT_DIR"):   # 눈으로 볼 때: 실행 카드 (루틴에 올린 상태 / 종료에 올린 상태)
        page.locator("#act-card").screenshot(path=os.path.join(os.environ["SHOT_DIR"], "act_hover_run.png"))
        page.hover("#stop-erpia"); page.wait_for_timeout(800)
        page.locator("#act-card").screenshot(path=os.path.join(os.environ["SHOT_DIR"], "act_hover_stop.png"))
        page.hover("#run-all"); page.wait_for_timeout(800)
        page.locator("#act-card").screenshot(path=os.path.join(os.environ["SHOT_DIR"], "act_hover_all.png"))
    page.mouse.move(0, 0)

    print("6-3절 시간대 반복 (3부)")
    db_patch("meta/companies/c_demo/apps/rpa", {"limits": {"schedule": 3}})
    reload_to(page, "settings")
    page.wait_for_function("document.querySelectorAll('#sch-times select').length === 2", timeout=10000)
    check(page.text_content("#sch-card h2").startswith("자동 실행") and page.text_content("label:has(#sch-enabled)").strip() == "활성화",
          f"카드 이름 '자동 실행'·스위치 '활성화' (사용자 2026-10-08) ({page.text_content('#sch-card h2')})")
    gap = page.evaluate("document.querySelector('#sch-times').previousElementSibling.getBoundingClientRect().top - document.getElementById('sch-days').getBoundingClientRect().bottom")
    check(gap >= 16, f"요일 단추와 '시간' 사이를 띄운다 ({gap}px)")
    was_on = (db_get(f"{LIVE}/schedule") or {}).get("enabled")
    db_patch(f"{LIVE}/schedule", {"enabled": False})
    page.wait_for_function("document.getElementById('sch-meta')?.textContent === '비활성화'", timeout=10000)
    check(True, "자동 실행이 꺼져 있으면 '비활성화' (전 '꺼짐')")
    db_patch(f"{LIVE}/schedule", {"enabled": was_on})
    grps = [x.strip() for x in page.locator("#settings-grid h3.grp").all_text_contents()]
    check(grps == ["프리페어 RPA (사이트 수집)", "루틴 RPA", "자동 실행"], f"환경설정 RPA 는 프리페어·루틴·자동 실행으로 나뉜다 (사용자 2026-10-08) ({grps})")
    check(page.evaluate("import('./rpa-common.js').then(m => m.RUN_NAMES.Prepare)") == "사이트 수집", "자동 실행 단추 이름 '사이트 수집' (전 '쇼핑몰 받기')")
    page.click("#sch-add-win")
    win = "#sch-times .t:nth-child(3)"
    check(page.locator(f"{win} select").count() == 0 and page.locator(f"{win} .chips button[data-k='Prepare']").count() == 1
          and page.locator(f"{win} .chips button").count() == 5, "반복 줄: 전체/고르기 없음, 사이트 수집 단추 있음 (사용자 2026-10-08)")
    modes = [x.strip() for x in page.locator("#sch-times select.mode").first.locator("option").all_text_contents()]
    check(modes == ["전체 모듈 실행", "선택 모듈만 실행"], f"시각 줄 고르기 이름 (사용자 2026-10-08) ({modes})")
    check(page.is_disabled("#sch-apply") and "반복 줄에 모듈을" in page.text_content("#sch-limit"), "모듈을 안 고르면 적용 안 됨")
    page.click(f"{win} .chips button[data-k='Logistics']")

    def set_win(a, b):
        for i, v in ((0, a), (1, b)):
            el = page.query_selector_all(f"{win} input[type=time]")[i]
            el.fill(v); el.dispatch_event("change")

    set_win("10:00", "")   # 끝 시각을 지워도 (백스페이스) 반복 줄은 반복 줄 그대로 - 보통 줄로 바뀌어 '사이트 수집' 이 생기면 안 된다
    check(page.locator(f"{win} input.rest-min").count() == 1 and page.locator(f"{win} select").count() == 0
          and page.is_disabled("#sch-apply") and "반복 끝 시각은" in page.text_content("#sch-limit"),
          f"끝 시각을 지우면 반복 줄 그대로·적용 막음 ({page.text_content('#sch-limit')})")
    check(not page.is_visible("#sch-warn"), "사이트 수집을 안 켜면 경고 없음")
    page.click(f"{win} .chips button[data-k='Prepare']")
    pos = page.evaluate("[document.getElementById('sch-limit').getBoundingClientRect().top, document.getElementById('sch-warn').getBoundingClientRect().top]")
    check(page.is_visible("#sch-warn") and "너무 잦은 사이트 수집은 2차인증을 요구할 수도 있습니다." in page.text_content("#sch-warn")
          and "warn" in page.get_attribute("#sch-warn", "class") and pos[1] > pos[0],
          f"반복 줄에 사이트 수집을 켜면 빨간 글 아래 호박색 경고 (사용자 2026-10-08) ({pos})")
    warn_rgb = page.evaluate("getComputedStyle(document.getElementById('sch-warn')).color")
    check(rgb2hex(warn_rgb) == page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--ecam-amber').trim()"),
          f"경고 글자는 ECAM 호박색 ({warn_rgb})")
    page.click(f"{win} .chips button[data-k='Prepare']")
    check(not page.is_visible("#sch-warn"), "사이트 수집을 끄면 경고도 사라진다")
    set_win("13:00", "14:00")
    check(page.text_content("#sch-limit") == "13:30 은 반복 시간대(13:00~14:00) 와 겹칩니다. 반복 시간대와 겹치지 않도록 수정해주십시오." and page.is_disabled("#sch-apply"),
          f"시각 줄(13:30)이 반복 안에 있으면 거절 ({page.text_content('#sch-limit')})")
    set_win("10:00", "11:00")
    page.fill(f"{win} input.rest-min", "3"); page.dispatch_event(f"{win} input.rest-min", "change")
    check(not page.is_disabled("#sch-apply"), "겹침이 없으면 적용 가능")
    page.click("#sch-apply"); time.sleep(1.5)
    slots = (db_get(f"{SETTINGS}/schedule") or {}).get("slots")
    check(slots == [{"at": "09:05"}, {"at": "10:00", "until": "11:00", "rest_min": 3, "run": ["Logistics"]}, {"at": "13:30", "run": ["Logistics"]}],
          f"반복 줄 저장 ({slots})")
    key = [k for k, v in (db_get(CMDS) or {}).items() if v.get("type") == "set_schedule"][-1]
    db_patch(f"{CMDS}/{key}", {"state": "done", "result": "자동 실행: 매일 09:05, 10:00~11:00 반복 물류관리, 13:30 물류관리", "started_at": 1, "ended_at": 2})
    db_patch(f"{LIVE}/schedule", {"slots": [{"at": "09:05"}, {"at": "10:00", "until": "11:00", "rest_min": 3, "on_fail": "stop", "run": ["Login", "Logistics"]},
                                            {"at": "13:30", "run": ["Login", "Logistics"]}],
                                  "repeat": {"date": TODAY, "at": "10:00", "until": "11:00", "runs": 24, "done": 2, "stopped": None}})
    page.wait_for_function("(document.getElementById('sch-info')?.textContent || '').includes('오늘 반복 24회')", timeout=10000)
    check("오늘 반복 24회 · 처리 2회" in page.text_content("#sch-info") and page.is_disabled("#sch-apply"),
          "PC 가 돌려준 반복 상태: 오늘 횟수·처리 (on_fail·로그인이 붙어도 바뀜 없음)")
    db_patch(f"{LIVE}/schedule/repeat", {"stopped": {"at": f"{TODAY}T10:23:00", "reason": "10:23 물류관리 실패로 반복을 멈췄습니다: 저장 실패"}})
    page.wait_for_function("(document.getElementById('sch-info')?.textContent || '').includes('멈췄습니다')", timeout=10000)
    check("bad" in page.get_attribute("#sch-info", "class"), "멈췄으면 그 까닭을 빨간 글로")
    if os.environ.get("SHOT_DIR"): page.locator("#settings-grid").screenshot(path=os.path.join(os.environ["SHOT_DIR"], "settings_repeat.png"))
    db_patch("meta/companies/c_demo/apps/rpa", {"limits": None})
    # RPA 화면: 지금 열린 시간대가 멈췄으면 까닭과 [반복 다시 시작]. 시간대를 지금 시각 둘레로 (23시 뒤면 건너뜀)
    nw = datetime.datetime.now()
    start = nw.replace(minute=nw.minute - nw.minute % 5, second=0, microsecond=0)
    if start.hour < 23:
        w_at, w_until = start.strftime("%H:%M"), (start + datetime.timedelta(minutes=55)).strftime("%H:%M")
        db_patch(f"{LIVE}/schedule", {"enabled": True, "days": list(range(7)),
                                      "slots": [{"at": w_at, "until": w_until, "rest_min": 2, "on_fail": "stop", "run": ["Login", "Logistics"]}],
                                      "repeat": {"date": TODAY, "at": w_at, "until": w_until, "runs": 3, "done": 1, "stopped": None}})
        goto(page, "rpa")
        page.wait_for_function(f"(document.querySelector('#hero .stats')?.textContent || '').includes('반복 중 · {w_until}까지')", timeout=10000)
        check(page.is_hidden("#repeat-resume"), "반복 중: 상태 띠 '반복 중 · 끝 시각까지', 다시 시작 단추는 없다")
        db_patch(f"{LIVE}/schedule/repeat", {"stopped": {"at": f"{TODAY}T{w_at}:00", "reason": f"{w_at} 물류관리 실패로 반복을 멈췄습니다: 저장 실패"}})
        page.wait_for_selector("#repeat-resume:not([hidden])", timeout=10000)
        check("반복 멈춤" in page.text_content("#hero .stats") and "저장 실패" in page.text_content("#repeat-line"),
              "멈췄으면 상태 띠 '반복 멈춤' + 실행 칸에 까닭")
        page.click("#repeat-resume"); time.sleep(1.0)
        check(len(cmds_of("resume_repeat")) == 1, "[반복 다시 시작] → resume_repeat 명령")
        key = [k for k, v in (db_get(CMDS) or {}).items() if v.get("type") == "resume_repeat"][-1]
        db_patch(f"{CMDS}/{key}", {"state": "done", "result": f"반복을 다시 시작했습니다 ({w_until}까지)", "started_at": 1, "ended_at": 2})
        db_patch(f"{LIVE}/schedule/repeat", {"stopped": None})
        page.wait_for_selector("#repeat-resume[hidden]", state="attached", timeout=10000)
        check(True, "멈춤이 풀리면 단추가 사라진다")
    else:
        print("  (23시 뒤라 지금 열린 시간대 화면 시험은 건너뜀)")
        goto(page, "rpa")
    db_patch(f"{LIVE}/schedule", {"slots": [{"at": "09:05"}, {"at": "13:30", "run": ["Login", "Logistics"]}], "repeat": None})

    print("6-4절 줄마다 요일 (사용자 2026-10-08, 판 3 PC)")
    db_patch("meta/companies/c_demo/apps/rpa", {"limits": {"schedule": 3}})
    db_patch(f"{LIVE}/schedule", {"version": 3, "enabled": True, "days": [0, 1, 2, 3, 4, 5, 6],
                                  "slots": [{"at": "09:00", "days": [0, 1, 2, 3, 4]}], "times": None, "repeat": None,
                                  "next_run_at": None, "next_slot": None})
    goto(page, "settings")
    page.wait_for_selector("#sch-times .t .days-mini button", timeout=10000)
    row1 = "#sch-times .t:nth-child(1)"
    pressed = lambda row: [b.get_attribute("aria-pressed") == "true" for b in page.locator(f"{row} .days-mini button").all()]
    check(page.is_hidden("#sch-days") and page.is_hidden("#sch-presets") and page.is_hidden("#sch-days-lbl"),
          "판 3 PC: 카드의 공통 요일 줄이 없다")
    check(pressed(row1) == [True] * 5 + [False] * 2, f"줄마다 요일 단추 일곱 개 - 저장된 요일이 눌려 있다 ({pressed(row1)})")
    page.click(f"{row1} .days-mini button:nth-child(6)")       # 토
    page.click("#sch-add")
    row2 = "#sch-times .t:nth-child(2)"
    check(pressed(row2) == [True] * 5 + [False] * 2, "[+ 시각] 새 줄은 평일(월~금)로 시작")
    page.click("#sch-add-win")
    row3 = "#sch-times .t:nth-child(3)"
    geo = page.evaluate("""() => [...document.querySelectorAll('#sch-times .t')].map(t => {
        const b = [...t.querySelectorAll('.days-mini button')].map(x => x.getBoundingClientRect());
        return { left: Math.round(b[0].left), oneLine: b.every(x => Math.abs(x.top - b[0].top) < 2),
                 line: getComputedStyle(t).borderTopWidth, head: !!t.querySelector('.t-head .del') }; })""")
    check(len({g["left"] for g in geo}) == 1 and all(g["oneLine"] for g in geo),
          f"시각 줄·반복 줄 모두 요일 단추가 같은 자리에 한 줄로 (사용자 2026-10-08) ({geo})")
    check(all(g["head"] for g in geo) and all(g["line"] != "0px" for g in geo[1:]), f"줄마다 같은 머리(시각·빼기) + 슬롯 사이 가로선 ({geo})")
    vp = page.viewport_size
    page.set_viewport_size({"width": 390, "height": 900}); page.wait_for_timeout(300)
    mob = page.evaluate("""() => { const card = document.getElementById('sch-card');
        const rows = [...document.querySelectorAll('#sch-times .t')].map(t => { const b = [...t.querySelectorAll('.days-mini button')].map(x => x.getBoundingClientRect());
            return { left: Math.round(b[0].left), oneLine: b.every(x => Math.abs(x.top - b[0].top) < 2) }; });
        const vals = [...document.querySelectorAll('#sch-times .t-line .t-val')].map(v => Math.round(v.firstElementChild.getBoundingClientRect().left));
        return { rows, vals, fits: card.scrollWidth <= card.clientWidth + 1 }; }""")
    check(len({r["left"] for r in mob["rows"]}) == 1 and all(r["oneLine"] for r in mob["rows"]) and mob["fits"] and len(set(mob["vals"])) == 1,
          f"휴대폰 폭(390px)에서도 요일 단추가 같은 자리 한 줄·카드 밖으로 안 나감 ({mob})")
    if os.environ.get("SHOT_DIR"): page.locator("#sch-card").screenshot(path=os.path.join(os.environ["SHOT_DIR"], "slots_mobile.png"))
    page.set_viewport_size(vp); page.wait_for_timeout(300)
    if os.environ.get("SHOT_DIR"): page.locator("#sch-card").screenshot(path=os.path.join(os.environ["SHOT_DIR"], "slots_desktop.png"))
    lines = [x.strip() for x in page.locator("#sch-limit > div").all_text_contents()]
    check("같은 시각이 두 번 있습니다" in lines and "반복 줄에 모듈을 하나 이상 고르세요" in lines and page.is_disabled("#sch-apply"),
          f"막는 까닭은 하나씩이 아니라 모두, 한 줄에 하나씩 (사용자 2026-10-08) ({lines})")
    page.click(f"{row3} button.del")
    el = page.query_selector(f"{row2} input[type=time]"); el.fill("09:00"); el.dispatch_event("change")
    check("같은 시각" in page.text_content("#sch-limit") and page.is_disabled("#sch-apply"), "요일이 겹치는 같은 시각은 막는다")
    for i in range(1, 6):
        page.click(f"{row2} .days-mini button:nth-child({i})")  # 월~금 끄기
    check("요일을 하나 이상" in page.text_content("#sch-limit") and page.is_disabled("#sch-apply"), "요일을 하나도 안 고른 줄은 막는다")
    page.click(f"{row2} .days-mini button:nth-child(7)")       # 일
    check(page.text_content("#sch-limit") == "" and not page.is_disabled("#sch-apply"), "요일이 다르면 같은 시각도 된다")
    page.click("#sch-apply"); time.sleep(1.5)
    saved = db_get(f"{SETTINGS}/schedule") or {}
    check(saved.get("slots") == [{"at": "09:00", "days": [0, 1, 2, 3, 4, 5]}, {"at": "09:00", "days": [6]}] and saved.get("days") == list(range(7)),
          f"줄마다 요일을 저장 (공통 요일은 모두 합친 것 - 옛 판 에이전트 대비) ({saved})")
    key = [k for k, v in (db_get(CMDS) or {}).items() if v.get("type") == "set_schedule"][-1]
    db_patch(f"{CMDS}/{key}", {"state": "done", "result": "자동 실행", "started_at": 1, "ended_at": 2})
    db_patch(f"{LIVE}/schedule", {"slots": saved["slots"]})
    page.wait_for_function("document.getElementById('sch-meta')?.textContent === '월·화·수·목·금·토 09:00, 일 09:00'", timeout=10000)
    check(page.is_disabled("#sch-apply"), "PC 가 돌려준 값과 같으면 바뀜 없음 - 카드 옆 요약도 줄마다 요일")
    db_patch(f"{LIVE}/schedule", {"slots": [{"at": "09:00", "days": [0, 1, 2, 3, 4, 5]}, {"at": "09:00", "days": [6], "run": ["Login", "Logistics"]}],
                                  "next_run_at": "2026-10-11T09:00:00", "next_slot": "09:00"})   # 2026-10-11 은 일요일
    page.wait_for_function("(document.getElementById('sch-info')?.textContent || '').includes('다음')", timeout=10000)
    check("(물류관리)" in page.text_content("#sch-info"), f"다음 실행 글은 그날 요일 줄의 모듈 ({page.text_content('#sch-info')})")
    db_patch(f"{LIVE}/schedule", {"version": 2, "days": [0, 1, 2, 3, 4, 5, 6], "slots": [{"at": "09:05"}, {"at": "13:30", "run": ["Login", "Logistics"]}]})
    db_patch("meta/companies/c_demo/apps/rpa", {"limits": None})
    goto(page, "settings")
    page.wait_for_function("document.querySelectorAll('#sch-times select').length === 2", timeout=10000)
    check(page.is_visible("#sch-days") and page.locator("#sch-times .days-mini").count() == 0, "옛 판(2) PC 는 지금처럼 공통 요일")

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
    accent = lambda: page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--accent').trim()")
    check(accent() == "#f29f67" and "기본" in page.text_content("#accent-now"), "강조색 기본은 orange")
    page.click("#accent-swatches .swatch[title='violet']")
    check(accent() == "#6c71c4" and page.text_content("#accent-now") == "#6c71c4", "견본을 누르면 강조색이 바뀐다")
    check(page.evaluate("getComputedStyle(document.getElementById('pw-btn')).backgroundColor") == "rgb(108, 113, 196)", "버튼 색도 따라 바뀐다")
    page.click("#theme")   # 어둡게 → 같은 견본의 어두운 모드용 짝으로 바뀐다
    check(accent() == "#9a9fe0" and page.text_content("#accent-now") == "#6c71c4", "어두운 모드에선 견본의 짝 색을 쓴다 (저장값은 그대로)")
    page.click("#theme")
    check(accent() == "#6c71c4", "다시 밝게 하면 밝음용 값")
    ink = lambda: page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--accent-ink').trim()")
    page.click("#accent-swatches .swatch[title='navy']")
    check(accent() == "#21263a" and ink() == "#fdf6e3", "진한 강조색엔 밝은 글자")
    page.click("#accent-swatches .swatch[title='orange']")
    check(accent() == "#f29f67" and ink() == "#1e1e2c", "주황엔 어두운 글자 (흰 글자는 2:1 도 안 됨)")
    check(page.locator("#accent-swatches .swatch").count() == 3 and page.query_selector("#accent-swatches .swatch[title='yellow']") is None
          and page.query_selector("#accent-swatches .swatch[title='magenta']") is None, "견본에 상태 색(노랑·빨강 계열)은 없다")
    page.fill("#accent-pick", "#b58900"); page.dispatch_event("#accent-pick", "input")
    check(accent() == "#b58900" and ink() == "#1e1e2c", "직접 고른 색 + 글자색은 대비 큰 쪽 자동")
    page.reload(); page.wait_for_selector("#main:not(.hide)", timeout=15000)
    check(accent() == "#b58900", "새로고침해도 강조색이 남는다")
    page.click("#admin-nav a[data-key='account']"); page.wait_for_selector("#accent-reset")
    page.click("#accent-reset")
    check(accent() == "#f29f67" and "기본" in page.text_content("#accent-now"), "기본값으로 되돌린다")
    page.click("#app-nav a[data-key='rpa']")
    page.wait_for_selector("#hero")
    check(page.text_content("#page-title") == "RPA", "RPA 로 돌아온다")

    print("7-2절 기록 탭")
    page.click("#tab-history")
    page.wait_for_function("(document.getElementById('hist-msg')?.textContent || '').endsWith('건')", timeout=15000)
    rows = page.locator("#hist-rows tr.hist")
    check(rows.count() == 6, f"이 PC 기록 6건 (다른 PC 1건 제외) ({rows.count()})")
    check("09/14 13:55" in rows.nth(0).text_content() and "09/12" in rows.nth(4).text_content(), "최신순")
    check("주소를 입력하세요" in rows.nth(1).text_content(), "중단 사유가 처리 칸에")
    # 열 너비: 시각·프로그램·결과·소요는 줄바꿈 없이 한 줄, 알약도 한 줄. 프로그램 이름은 'RPA' 를 뗀다
    # 줄 수는 글자 범위의 사각형 개수로 센다 (칸 높이는 여백 때문에 한 줄이어도 36px)
    one_line = lambda sel: page.evaluate(f"""(() => {{ const el = document.querySelector("{sel}"); const r = document.createRange();
      r.selectNodeContents(el); return r.getClientRects().length; }})()""") == 1
    check(rows.nth(0).locator("td").nth(1).text_content() == "루틴" and rows.nth(2).locator("td").nth(1).text_content() == "프리페어", "프로그램 칸은 루틴/프리페어")
    check(one_line("#view-history thead th:nth-child(2)") and one_line("#hist-rows tr.hist td:nth-child(1)"), "시각·프로그램 칸이 한 줄")
    crash = rows.nth(5).locator(".pill")
    check("crash" in (crash.get_attribute("class") or "") and crash.text_content() == "오류", "죽은 실행은 '오류' 알약")
    check(rows.nth(1).locator(".pill").text_content() == "실패", "단계에서 멈춘 실행은 '실패' 알약 (중단이라 안 쓴다)")
    crash_css = lambda p: rgb2hex(page.evaluate(f"getComputedStyle(document.querySelector('#hist-rows .pill.crash')).{p}"))
    check(crash_css("backgroundColor") == "#e0b50f" and crash_css("color") == "#1e1e2c", "비정상 종료는 노랑 채움 (밝음: 밝은 노랑 + 남색 글자)")
    page.click("#theme"); page.wait_for_timeout(600)
    check(crash_css("backgroundColor") == "#705a00" and crash_css("color") == "#fdf6e3", "어두움: 짙은 올리브 + 크림 글자")
    if os.environ.get("SHOT_DIR"): page.locator("#view-history .card").screenshot(path=os.path.join(os.environ["SHOT_DIR"], "hist_dark.png"))
    page.click("#theme"); page.wait_for_timeout(600)
    stop_pill = page.evaluate("getComputedStyle(document.querySelector('#hist-rows .pill.bad')).backgroundColor")
    check(rgb2hex(stop_pill) == token("--bad-bg"), "중단은 옅은 빨강 (구분됨)")
    page.set_viewport_size({"width": 420, "height": 900}); page.wait_for_timeout(300)
    check(one_line("#hist-rows .pill.crash") and one_line("#hist-rows tr.hist td:nth-child(2)"), "좁은 창에서도 알약·프로그램 칸이 한 줄")
    check(page.evaluate("document.querySelector('#hist-rows tr.hist td:nth-child(5)').getBoundingClientRect().width") >= 200,
          "좁은 창에서 처리 칸은 최소 폭을 지킨다 (표가 옆으로 스크롤)")
    if os.environ.get("SHOT_DIR"):
        page.locator("#view-history .card").screenshot(path=os.path.join(os.environ["SHOT_DIR"], "hist_420.png"))
        page.set_viewport_size({"width": 1280, "height": 720}); page.wait_for_timeout(300)
        page.locator("#view-history .card").screenshot(path=os.path.join(os.environ["SHOT_DIR"], "hist_1280.png"))
    page.set_viewport_size({"width": 1280, "height": 720}); page.wait_for_timeout(300)
    check(page.is_hidden("#hist-rows tr.hist-detail"), "상세는 접혀 있다")
    rows.nth(1).click()
    check(page.is_visible("#hist-rows tr.hist-detail:nth-child(4)"), "행을 누르면 상세가 펼쳐진다")
    detail = page.text_content("#hist-rows tr.hist-detail:nth-child(4)")
    check("물류 관리 저장" in detail and "[13:39:05] 주소를 입력하세요" in detail, "상세에 단계와 로그")
    page.fill("#hist-date", "2026-09-13"); page.dispatch_event("#hist-date", "change")
    page.wait_for_function("document.getElementById('hist-title')?.textContent === '기록 · 2026-09-13'", timeout=15000)
    page.wait_for_function("(document.getElementById('hist-msg')?.textContent || '').endsWith('건')", timeout=15000)
    check(page.locator("#hist-rows tr.hist").count() == 1 and "09/13" in page.text_content("#hist-rows"), "날짜로 거르기")
    page.click("#hist-all")
    page.wait_for_function("document.getElementById('hist-title')?.textContent === '기록'", timeout=15000)
    page.click("#tab-status")
    check(page.is_visible("#hero") and page.is_hidden("#view-history"), "현황으로 돌아온다")
    page.click("#recent-strip .day[data-date='2026-09-14']")
    page.wait_for_function("document.getElementById('hist-title')?.textContent === '기록 · 2026-09-14'", timeout=15000)
    page.wait_for_function("(document.getElementById('hist-msg')?.textContent || '').endsWith('건')", timeout=15000)
    check(page.is_visible("#view-history") and page.locator("#hist-rows tr.hist").count() == 3, "날짜 도넛을 누르면 그 날 기록 3건")
    check(page.input_value("#hist-date") == "2026-09-14", "날짜 칸에 그 날짜")
    page.click("#tab-status")

    print("7-3절 PC 고르기")
    # 키 이름순으로 오므로 pc_z 가 pc_office 뒤에 온다 (기억한 PC 가 없으면 첫 PC)
    db_put("meta/companies/c_demo", {"name": "시연 회사", "pcs": {"pc_office": {"label": "사무실 PC"}, "pc_z": {"label": "창고 PC"}}})
    page.reload(); page.wait_for_selector("#main:not(.hide)", timeout=15000); page.wait_for_selector("#hero")
    check(page.is_visible("#pc-pick") and page.text_content("#pc-pick .selected").strip() == "사무실 PC", "PC 가 둘이면 고르기가 보이고 지금 PC 가 적혀 있다")
    goto(page, "settings")
    check(page.is_visible("#pc-pick") and page.text_content("#page-title") == "환경설정", "환경설정도 PC 마다 - PC 고르기가 보인다")
    goto(page, "rpa")
    check(page.locator("#pc-pick .option").count() == 1 and page.text_content("#pc-pick .option") == "창고 PC", "목록엔 다른 PC 만")
    opts_opacity = lambda: page.evaluate("getComputedStyle(document.querySelector('#pc-pick .options')).opacity")
    check(opts_opacity() == "0", "목록은 접혀 있다")
    page.hover("#pc-pick .selected"); page.wait_for_timeout(450)
    check(opts_opacity() == "1", "올리면 펼쳐진다")
    if os.environ.get("SHOT_DIR"):
        clip = lambda: page.evaluate("(() => { const b = document.getElementById('pc-pick').getBoundingClientRect(); return {x: b.left - 40, y: b.top - 12, width: b.width + 80, height: b.height + 110}; })()")
        page.screenshot(path=os.path.join(os.environ["SHOT_DIR"], "pcpick_light.png"), clip=clip())
        page.click("#theme"); page.hover("#pc-pick .selected"); page.wait_for_timeout(700)
        page.screenshot(path=os.path.join(os.environ["SHOT_DIR"], "pcpick_dark.png"), clip=clip())
        page.click("#theme"); page.hover("#pc-pick .selected"); page.wait_for_timeout(450)
    page.click("#pc-pick .option")
    page.wait_for_function("document.querySelector('#pc-pick .selected')?.textContent.trim() === '창고 PC'", timeout=5000)
    check(page.text_content("#pc-pick .option") == "사무실 PC", "고르면 알약이 바뀌고 목록엔 이전 PC")
    page.wait_for_function("document.getElementById('h-state')?.textContent === 'PC 연결 끊김'", timeout=10000)
    check("기록 없음" in page.text_content("#h-line1"), "고른 PC 의 현황으로 바뀐다 (창고 PC 는 기록 없음)")
    page.mouse.move(0, 0); page.wait_for_timeout(450)
    check(opts_opacity() == "0", "마우스가 떠나면 접힌다")
    page.reload(); page.wait_for_selector("#main:not(.hide)", timeout=15000); page.wait_for_selector("#hero")
    check(page.text_content("#pc-pick .selected").strip() == "창고 PC", "새로고침해도 마지막에 고른 PC 를 기억한다")
    db_put("meta/companies/c_demo", {"name": "시연 회사", "pcs": {"pc_office": {"label": "사무실 PC"}}})
    page.reload(); page.wait_for_selector("#main:not(.hide)", timeout=15000); page.wait_for_selector("#hero")
    check(page.is_hidden("#pc-pick"), "PC 를 하나로 되돌리면 다시 숨는다")

    print("8절 열람자")
    page.click("#logout-btn")
    page.wait_for_selector("#login:not(.hide)")
    login(page, "viewer@t.local")
    check("(유저)" in page.text_content("#who"), "유저로 표시 (전 '열람' - 2026-10-06 이름)")
    page.wait_for_function("document.getElementById('h-state')?.textContent === '성공'", timeout=10000)
    check(page.is_hidden("#act-card") and page.locator("#admin-nav a[data-key='settings']").count() == 0,
          "유저는 실행 카드도 환경설정 메뉴도 없다")
    cols_w = page.evaluate("document.querySelector('.cols').getBoundingClientRect().width")
    main_w = page.evaluate("document.querySelector('.cols > div').getBoundingClientRect().width")
    check(abs(cols_w - main_w) < 2, f"오른쪽 열 자리를 남기지 않는다 (본문 {main_w:.0f} / 전체 {cols_w:.0f})")
    denied = page.evaluate("""async () => {
      const m = await import('https://www.gstatic.com/firebasejs/10.14.1/firebase-database.js');
      const a = await import('https://www.gstatic.com/firebasejs/10.14.1/firebase-app.js');
      const db = m.getDatabase(a.getApp());
      try { await m.push(m.ref(db, 'apps/rpa/commands/c_demo/pc_office'), {type:'launch', by:'x', created_at:1, expires_at:2, state:'queued'}); return 'ok'; }
      catch (e) { return e.code || String(e); }
    }""")
    check(denied == "PERMISSION_DENIED", f"열람자가 우회해 써도 규칙이 거부 ({denied})")
    page.click("#admin-nav a[data-key='account']"); page.wait_for_selector("#acct-role")
    check(page.text_content("#acct-role") == "유저", f"계정 화면의 역할도 '유저' ({page.text_content('#acct-role')})")
    page.reload(); page.wait_for_selector("#main:not(.hide)", timeout=15000)

    print("9절 이스케이프·세 칸 로그인·기계 계정")
    # 공유 계약 예시(agent.py·setup.js 와 같아야 한다) — 같은 URL 의 모듈이라 이미 뜬 app.js 가 돌아온다
    check(page.evaluate("""async () => { const m = await import(location.origin + '/app.js');
      return [m.emailFor('c_demo','agent-pc-office'), m.emailFor('c_demo','admin'), m.emailFor('','super'), m.emailFor('c_a_b','a_b_c'), m.emailFor('c_demo','x@y.z')]; }""")
      == ["agent-pc-office@c-demo.rpa-test-f02e0.firebaseapp.com", "admin@c-demo.rpa-test-f02e0.firebaseapp.com",
          "super@rpa-test-f02e0.firebaseapp.com", "a-b-c@c-a-b.rpa-test-f02e0.firebaseapp.com", "x@y.z"], "emailFor 가 공유 계약 예시 다섯 개와 같다")
    # 에이전트가 올린 값이 HTML 로 실행되면 안 된다. reason 은 기록 표에 innerHTML 로 들어간다
    XSS = '<img src=x onerror="document.title=\'xss\'">'
    seed_run("r_xss", "routine", "stopped", "2026-09-10T09:00:00", 5, reason=XSS)
    page.click("#tab-history")
    page.wait_for_function("(document.getElementById('hist-msg')?.textContent || '').endsWith('건')", timeout=15000)
    rows = page.locator("#hist-rows tr.hist")
    check(rows.count() == 7 and XSS in rows.nth(6).text_content(), "기록 표의 사유가 글자 그대로 보인다")
    check(page.locator("#hist-rows img").count() == 0 and page.title() == "AFTER MARKET", "태그로 해석되지 않는다 (제목이 안 바뀜)")
    page.click("#tab-status")
    db_patch(f"{LIVE}/programs/routine/metrics/0", {"unit": XSS})   # 숫자 타일의 단위도 에이전트 값
    page.wait_for_function("(document.getElementById('tiles')?.textContent || '').includes('<img')", timeout=10000)
    check(page.locator("#tiles img").count() == 0 and page.title() == "AFTER MARKET", "숫자 타일의 단위도 글자 그대로")
    db_patch(f"{LIVE}/programs/routine/metrics/0", {"unit": "건"})
    # 회사 코드 t + 아이디 who → who@t.rpa-test-f02e0.firebaseapp.com (공유 계약)
    make_user("who@t.rpa-test-f02e0.firebaseapp.com", "pw123456", {"cid": "t", "role": "viewer"})
    page.click("#logout-btn"); page.wait_for_selector("#login:not(.hide)")
    login(page, "who", cid="t")
    check("who@t.rpa-test-f02e0.firebaseapp.com (유저)" in page.text_content("#who"), "회사 코드·아이디로 이메일을 조립해 로그인한다")
    page.click("#logout-btn"); page.wait_for_selector("#login:not(.hide)")
    page.reload(); page.wait_for_selector("#login:not(.hide)")
    check(page.input_value("#cid") == "" and page.input_value("#login-id") == "" and not page.is_checked("#remember"), "저장을 안 켜고 로그인하면 다시 열 때 비어 있다")
    page.goto(WEB); page.wait_for_selector("#login:not(.hide)")
    page.fill("#cid", "t"); page.fill("#login-id", "who"); page.fill("#password", "pw123456"); page.check("#remember"); page.click("#login-btn")
    page.wait_for_selector("#main:not(.hide)", timeout=15000)
    page.click("#logout-btn"); page.wait_for_selector("#login:not(.hide)")
    page.reload(); page.wait_for_selector("#login:not(.hide)")
    check(page.input_value("#cid") == "t" and page.input_value("#login-id") == "who" and page.is_checked("#remember") and page.input_value("#password") == "", "저장을 켜고 로그인하면 다시 열 때 업체코드·아이디가 채워져 있다 (비밀번호는 아님)")
    page.fill("#password", "pw123456"); page.uncheck("#remember"); page.click("#login-btn")
    page.wait_for_selector("#main:not(.hide)", timeout=15000)
    page.click("#logout-btn"); page.wait_for_selector("#login:not(.hide)")
    page.reload(); page.wait_for_selector("#login:not(.hide)")
    check(page.input_value("#cid") == "" and page.input_value("#login-id") == "" and not page.is_checked("#remember"), "저장을 끄고 로그인하면 지운다")
    # 기계 계정(role agent)은 화면에 못 들어온다. agent-pc-office@c-demo.… 는 실제 기계 계정과 같은 꼴
    make_user("agent-pc-office@c-demo.rpa-test-f02e0.firebaseapp.com", "pw123456", {"cid": "c_demo", "pcId": "pc_office", "role": "agent"})
    page.fill("#cid", "c_demo"); page.fill("#login-id", "agent-pc-office"); page.fill("#password", "pw123456")
    page.press("#login-id", "Enter")   # 어느 칸에서든 Enter 로 로그인
    page.wait_for_function("(document.getElementById('login-alert')?.textContent || '').includes('에이전트 계정')", timeout=15000)
    check(page.is_visible("#login") and page.is_hidden("#main"), "에이전트 계정은 로그인 화면에 그대로")
    check(page.text_content("#login-alert") == "에이전트 계정으로는 화면에 들어올 수 없습니다", "에이전트 계정 안내 문구 (전 '기계 계정')")
    check(page.evaluate("""async () => {
      const a = await import('https://www.gstatic.com/firebasejs/10.14.1/firebase-auth.js');
      return a.getAuth().currentUser === null; }"""), "기계 계정은 곧바로 로그아웃된다")
    # 삭제(비활성)된 업체(stts=9). setup.js remove 가 계정도 막지만, 이미 받은 토큰이 1시간 사는 동안 화면에서 막는다
    make_user("gone@t.local", "pw123456", {"cid": "c_gone", "role": "admin"})
    db_put("meta/companies/c_gone", {"name": "지운 회사", "stts": 9, "pcs": {"pc_1": {"label": "PC"}}})
    page.fill("#cid", ""); page.fill("#login-id", "gone@t.local"); page.fill("#password", "pw123456")
    page.click("#login-btn")
    page.wait_for_function("(document.getElementById('login-alert')?.textContent || '').includes('중지')", timeout=15000)
    check(page.is_visible("#login") and page.is_hidden("#main"), "삭제된 업체 계정은 로그인 화면에 그대로")
    check(page.text_content("#login-alert") == "사용이 중지된 업체입니다", "삭제된 업체 안내 문구")
    check(page.evaluate("""async () => {
      const a = await import('https://www.gstatic.com/firebasejs/10.14.1/firebase-auth.js');
      return a.getAuth().currentUser === null; }"""), "삭제된 업체 계정은 곧바로 로그아웃된다")
    db_put("meta/companies/c_gone/stts", 0)
    login(page, "gone@t.local")
    check("gone@t.local" in page.text_content("#who") and "지운 회사" in page.text_content("#company"), "되살리면(stts=0) 들어온다")
    page.click("#logout-btn"); page.wait_for_selector("#login:not(.hide)")

    print("10절 버전 표시")
    login(page, "admin@t.local", pw="newpass123")   # 7절에서 이 계정 비밀번호를 바꿨다
    page.wait_for_selector("#hero-side .stat")
    check(page.query_selector(".subnav #ver") is not None and page.is_hidden("#ver"),
          "버전 정보가 없으면 (옛 에이전트) 탭 줄 오른쪽 자리가 비어 있다")
    check(page.locator("#hero-side .stat").count() == 2, "상태 카드에는 연결·다음 자동 실행 두 칸만 (버전은 탭 줄로)")

    def show_ver(v, want):
        """want 가 None 이면 숨는지 기다린다. 마우스 글(title)을 돌려준다."""
        db_patch(LIVE, {"version": v})
        if want is None:
            page.wait_for_function("document.getElementById('ver')?.classList.contains('hide')", timeout=5000)
            return ""
        page.wait_for_function(f"document.getElementById('ver')?.textContent.trim() === {json.dumps(want)}",
                               timeout=5000)
        return page.get_attribute("#ver", "title") or ""

    warn = lambda: page.evaluate("document.getElementById('ver').classList.contains('warn')")
    t = show_ver({"version": "2026.09.29-1", "state": "ok", "changed_count": 0, "checked_at": "2026-09-29T10:00:00"},
                 "버전 2026.09.29-1")
    check(t == "" and not warn() and page.is_visible("#ver"), "맞음이면 '버전 번호' 만, 보통 글씨")
    t = show_ver({"version": "2026.09.29-1", "state": "mixed", "changed": ["rpa_status.py", "firebase/agent/agent.py"],
                  "changed_count": 2, "checked_at": "2026-09-29T10:00:00"}, "버전 2026.09.29-1 · 다른 파일 2")
    check("rpa_status.py" in t and "firebase/agent/agent.py" in t and warn(), f"섞임이면 노란 글씨, 다른 파일은 마우스 글로 ({t})")
    t = show_ver({"version": "2026.09.29-1", "state": "mixed", "changed": [f"f{i}.txt" for i in range(10)],
                  "changed_count": 15, "checked_at": "2026-09-29T10:00:00"}, "버전 2026.09.29-1 · 다른 파일 15")
    check("외 5개" in t, f"이름을 다 못 보냈으면 나머지 개수 ({t})")
    t = show_ver({"state": "error", "error": "ValueError: 판 목록 형식이 다릅니다", "changed_count": 0,
                  "checked_at": "2026-09-29T10:00:00"}, "버전 확인 실패")
    check("형식" in t and warn(), f"확인 실패면 노란 글씨, 이유는 마우스 글로 ({t})")
    db_patch(LIVE, {"update": {"state": "waiting", "target": "2026.10.07-5", "from": "2026.10.07-4", "at": "2026-10-07T15:00:00", "backup": None}})
    page.wait_for_function("(document.getElementById('ver')?.textContent || '').includes('업데이트 대기 중')", timeout=10000)
    check(page.is_disabled("#run-routine") and page.is_disabled("#run-all")
          and page.get_attribute("#run-routine", "title") == "업데이트 중이라 잠시 실행할 수 없습니다", "업데이트 대기 중: 판 옆 글 + 실행 단추 잠금")
    db_patch(LIVE, {"update": {"state": "rolled_back", "target": "2026.10.07-5", "from": "2026.10.07-4", "at": "2026-10-07T15:10:00",
                               "reason": "새 판이 3분 안에 정상으로 켜지지 않았습니다", "backup": "2026.10.07-3"}})
    page.wait_for_function("(document.getElementById('ver')?.textContent || '').includes('이전 버전으로 되돌림')", timeout=10000)
    check("3분" in (page.get_attribute("#ver", "title") or "") and not page.is_disabled("#run-routine"), "되돌림: 까닭은 마우스 글, 실행 단추는 풀린다")
    db_patch(LIVE, {"update": {"state": "done", "target": "2026.10.07-5", "from": "2026.10.07-4", "at": "2026-10-07T14:03:00", "backup": "2026.10.07-4"}})
    page.wait_for_function("(document.getElementById('ver')?.textContent || '').includes('업데이트됨 (10/7 14:03)')", timeout=10000)
    check(True, "업데이트됨 (10/7 14:03)")
    db_patch(LIVE, {"update": None})
    show_ver({"state": "none", "changed_count": 0, "checked_at": "2026-09-29T10:00:00"}, None)
    check(page.is_hidden("#ver"), "목록이 없는 PC (개발 PC 등) 는 안 보인다")
    show_ver({"version": "<b>x</b>", "state": "mixed", "changed": ["<img src=x onerror=alert(1)>"], "changed_count": 1,
              "checked_at": "2026-09-29T10:00:00"}, "버전 <b>x</b> · 다른 파일 1")
    check(page.locator(".subnav img, .subnav b").count() == 0, "버전 이름·파일 이름은 글자로만 (이스케이프)")
    show_ver("이상한 값", None)
    check(page.is_hidden("#ver"), "version 이 객체가 아니어도 안 보인다 (오류 없음)")
    # 폰 폭: 버전은 탭 줄 안에 들고, 상태 카드 칸은 상태 글 아래 한 줄로 왼쪽부터
    show_ver({"version": "2026.09.29-1", "state": "mixed", "changed": ["rpa_status.py"], "changed_count": 1,
              "checked_at": "2026-09-29T10:00:00"}, "버전 2026.09.29-1 · 다른 파일 1")
    page.set_viewport_size({"width": 400, "height": 900}); page.wait_for_timeout(300)
    geo = page.evaluate("""() => { const h = document.getElementById('hero').getBoundingClientRect(),
        st = [...document.querySelectorAll('#hero-side .stat')].map(e => e.getBoundingClientRect()),
        v = document.getElementById('ver').getBoundingClientRect();
      return { sameRow: Math.abs(st[0].top - st[1].top) < 2, leftStart: st[0].left - h.left < 40,
               verIn: v.right <= window.innerWidth && v.left >= 0, noScroll: document.documentElement.scrollWidth <= window.innerWidth,
               heroH: Math.round(h.height) }; }""")
    check(geo["sameRow"] and geo["leftStart"], f"폰 폭에서 상태 카드 칸은 한 줄, 왼쪽부터 {geo}")
    check(geo["verIn"] and geo["noScroll"], f"폰 폭에서 버전 글이 화면 안에 들고 가로 스크롤이 없다 {geo}")
    if os.environ.get("SHOT_DIR"):
        for w in (1280, 400):
            page.set_viewport_size({"width": w, "height": 900}); page.wait_for_timeout(300)
            page.screenshot(path=os.path.join(os.environ["SHOT_DIR"], f"ver_{w}.png"), clip={"x": 0, "y": 0, "width": w, "height": 560})
    page.set_viewport_size({"width": 1280, "height": 720}); page.wait_for_timeout(300)
    db_patch(LIVE, {"version": None})

    print("11절 옵저버 미리보기 기록")
    seed_run("r_rec_0909", "observer", "success", "2026-09-09T08:00:00", 27,
             log=["[08:00:00] === 미리보기: ① 지마켓 (12단계) ==="])
    page.click("#tab-history")
    page.fill("#hist-date", "2026-09-09"); page.dispatch_event("#hist-date", "change")
    page.wait_for_function("document.getElementById('hist-title')?.textContent === '기록 · 2026-09-09'", timeout=15000)
    page.wait_for_function("(document.getElementById('hist-msg')?.textContent || '').endsWith('건')", timeout=15000)
    check(page.text_content("#hist-rows tr.hist td:nth-child(2)") == "옵저버", "기록 표의 프로그램 칸이 '옵저버'")
    seed_run("r_rep_0908", "routine", "success", "2026-09-08T10:24:00", 40, trigger="repeat")
    page.fill("#hist-date", "2026-09-08"); page.dispatch_event("#hist-date", "change")
    page.wait_for_function("document.getElementById('hist-title')?.textContent === '기록 · 2026-09-08'", timeout=15000)
    page.wait_for_function("(document.getElementById('hist-msg')?.textContent || '').endsWith('건')", timeout=15000)
    check(page.text_content("#hist-rows tr.hist td:nth-child(2)") == "루틴 · 반복", "처리한 반복 회차는 기록 표에 '루틴 · 반복'")
    page.click("#logout-btn"); page.wait_for_selector("#login:not(.hide)")

    check(not errors, f"페이지 오류 없음 {errors[:2]}")
    browser.close()

print(f"\n{COUNT - len(FAIL)}/{COUNT} 통과")
if FAIL:
    print("실패:", ", ".join(FAIL))
    sys.exit(1)
