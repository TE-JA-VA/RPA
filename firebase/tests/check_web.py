"""화면 시험 (Playwright + 에뮬레이터). 실제 프로젝트를 건드리지 않는다.

실행 (firebase/tests 에서, emu_env.ps1 을 읽은 창):
  firebase emulators:exec --config ../firebase.json --only auth,database,hosting --project rpa-test-f02e0 "python check_web.py"

에뮬레이터 REST 는 'Authorization: Bearer owner' 로 규칙을 우회한다 (시드용).
"""
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
    "heartbeat": {"at": NOW + 3600, "host": "OFFICE-PC", "rpa_running": False},   # 시험 내내 '정상' 이도록 미래 시각 (20초면 끊김)
    "programs": {"routine": routine, "prepare": None},
    "modules": {"Login": True, "Sales": False, "Hold": True, "Logistics": True, "Output": True},
    "schedule": {"enabled": True, "days": [0, 1, 2, 3, 4], "times": ["09:05"], "next_run_at": "2026-09-22T09:05:00",
                 "last_launch_at": f"{TODAY}T13:55:40", "last_launch_by": "cloud", "last_error": None},
    # 최근 20일 (에이전트가 history.jsonl 에서 센다). 8/26~9/4 는 실행 없음, 9/10~9/14 성공 5 · 실패 3
    "recent": [{"date": f"2026-08-{d:02d}", "success": 0, "failed": 0} for d in range(26, 32)]
              + [{"date": f"2026-09-{d:02d}", "success": s, "failed": f}
                 for d, s, f in [(1, 0, 0), (2, 0, 0), (3, 0, 0), (4, 0, 0), (5, 0, 0), (6, 0, 0), (7, 0, 0), (8, 0, 0), (9, 0, 0),
                                 (10, 1, 0), (11, 1, 0), (12, 1, 0), (13, 1, 1), (14, 1, 2)]],
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


def seed_run(run_id, program, state, started, dur_sec, reason=None, steps=None, log=None, metrics=None):
    payload = {"run_id": run_id, "program": program, "state": state, "started_at": started, "duration_sec": dur_sec,
               "reason": reason, "steps": steps or [], "log": log or [], "metrics": metrics or []}
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
seed_run("r_other_pc", "routine", "success", "2026-09-14T10:00:00", 10)
call("PATCH", f"{FS}/runs/c_demo/items/r_other_pc?updateMask.fieldPaths=pcId", {"fields": {"pcId": {"stringValue": "pc_other"}}}, OWNER)
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
    def lum(hex6):
        ch = [int(hex6[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        ch = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in ch]
        return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]

    def contrast(a, b):
        la, lb = lum(a), lum(b)
        return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)

    def tok(name):
        return page.evaluate(f"getComputedStyle(document.documentElement).getPropertyValue('{name}').trim()")

    def contrast_ok(theme):
        card = tok("--card")
        pairs = {"글자": contrast(tok("--ink"), card), "회색 글자": contrast(tok("--muted"), card), "제목": contrast(tok("--strong"), card)}
        for st_ in ["good", "warn", "bad", "run"]:
            pairs[f"채운 카드 {st_}"] = contrast(tok("--on-fill"), tok(f"--{st_}-fill"))
        low = {k: round(v, 2) for k, v in pairs.items() if v < 4.5}
        check(not low, f"{theme} 대비 4.5:1 이상 {low or ''}")
    check(page.evaluate("getComputedStyle(document.body).fontFamily").startswith('"Pretendard Variable"'), "본문 서체 Pretendard")
    contrast_ok("밝음")
    before = page.evaluate("getComputedStyle(document.body).backgroundColor")
    page.click("#theme")
    after = page.evaluate("getComputedStyle(document.body).backgroundColor")
    check(before != after and page.evaluate("document.documentElement.dataset.theme") == "dark", "어둡게 토글이 바탕색을 바꾼다")
    check("밝게" in page.text_content("#theme"), "버튼 글자가 바뀐다")
    contrast_ok("어두움")
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
    tiles = page.text_content("#tiles")
    flat = tiles.replace(" ", "").replace("\n", "")
    check("처리주문30건" in flat and "재고검토보류8/8" in flat, f"숫자 타일 ({flat[:60]})")
    check("≈376" in tiles.replace(" ", ""), "추정치는 ≈")
    check(page.evaluate("getComputedStyle(document.querySelector('.tile .v')).fontFamily").startswith('"Pretendard Variable"'), "숫자 칸도 같은 서체")
    check("정상" in page.text_content("#conn"), "연결 정상")
    check("9월 22일" in tiles and "09:05" in tiles, "다음 자동 실행")
    check(page.is_visible("#list-routine li"), "단계 목록은 항상 펼쳐져 있다")
    check("성공 · 3/3 · 2분 33초" in page.text_content("#meta-routine"), "단계 요약")
    check("기록 없음" in page.text_content("#meta-prepare"), "프리페어 없음")
    pair = page.evaluate("""() => { const p = document.querySelector('.pair'); const [a, b] = p.children;
      return [a.id, b.id, a.getBoundingClientRect().top === b.getBoundingClientRect().top, a.getBoundingClientRect().left < b.getBoundingClientRect().left]; }""")
    check(pair[0] == "steps-prepare" and pair[1] == "steps-routine" and pair[2] and pair[3], f"프리페어가 왼쪽, 루틴이 오른쪽에 나란히 ({pair})")
    check("2줄" in page.text_content("#log-meta"), "로그 줄 수")
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
    d14 = page.get_attribute("#recent-strip .day[data-date='2026-09-14'] svg circle:nth-child(2)", "stroke-dasharray")
    check(d14 and abs(float(d14.split()[0]) - 33.33) < 0.1, f"9/14 도넛은 성공 1/3 ({d14})")
    check("09/14" in page.text_content("#recent-strip"), "날짜 표시")
    check(page.text_content("#recent-meta") == "오늘 성공 1 · 실패 2", f"큰 도넛은 오늘 ({page.text_content('#recent-meta')})")
    check(page.locator("#recent-donut svg text").count() == 0, "도넛에 퍼센트 글자 없음")
    dash = page.get_attribute("#recent-donut svg circle:nth-child(2)", "stroke-dasharray")
    check(dash and abs(float(dash.split()[0]) - 33.33) < 0.1, f"오늘 도넛 호 길이 1/3 ({dash})")
    check("성공 1" in page.text_content("#recent-donut .legend") and "실패 2" in page.text_content("#recent-donut .legend"), "오늘 도넛 범례")

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
    db_patch(f"{LIVE}/heartbeat", {"at": NOW - 900})
    page.wait_for_function("document.getElementById('h-state')?.textContent === 'PC 연결 끊김'", timeout=10000)
    check(page.get_attribute("#hero", "data-state") == "offline" and hero_hex() == token("--warn-fill"), "연결 끊김도 노랑")
    check("15분 전부터" in page.text_content("#h-line1"), "끊긴 시간")
    db_patch(f"{LIVE}/heartbeat", {"at": NOW + 3600})
    db_patch(f"{LIVE}/programs/routine", routine)
    page.wait_for_function("document.getElementById('h-state')?.textContent === '성공'", timeout=10000)
    # 에이전트가 죽으면 값이 안 바뀐다. 화면이 5초마다 스스로 다시 봐야 끊김이 보인다
    db_patch(f"{LIVE}/heartbeat", {"at": int(time.time()) - 17})   # 아직 20초 안 → 정상, 몇 초 뒤 끊김
    page.wait_for_function("document.getElementById('conn')?.textContent.includes('정상')", timeout=10000)
    page.wait_for_function("document.getElementById('conn')?.textContent.includes('끊김')", timeout=15000)
    check("초" in page.text_content("#conn") and page.get_attribute("#hero", "data-state") == "offline",
          f"값이 안 바뀌어도 5초 안에 끊김으로 바뀐다 ({page.text_content('#conn').strip()})")
    db_patch(f"{LIVE}/heartbeat", {"at": NOW + 3600})
    page.wait_for_function("document.getElementById('h-state')?.textContent === '성공'", timeout=10000)

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
    check(page.is_disabled("#run-routine") and page.is_disabled("#run-all"), "응답 대기 중 버튼 잠금")
    key = next(k for k, v in (db_get(CMDS) or {}).items() if v.get("type") == "launch")
    db_patch(f"{CMDS}/{key}", {"state": "done", "result": "루틴 RPA 을(를) 띄웠습니다", "started_at": 1, "ended_at": 2})
    page.wait_for_function("document.getElementById('act-alert')?.textContent?.includes('띄웠습니다')", timeout=10000)
    check(True, "done 이 되면 결과 문장")
    page.wait_for_function("document.getElementById('run-routine')?.disabled === false", timeout=5000)
    check(True, "끝나면 버튼이 풀린다")

    print("5절 실행 모듈")
    page.wait_for_function("document.getElementById('mod-meta')?.textContent === '4/5 켬'", timeout=10000)
    check(page.is_disabled("#mod-apply"), "바뀐 게 없으면 적용 비활성")
    login_cb = page.locator("#mod-list input[aria-label='로그인']")
    check(login_cb.is_checked() and login_cb.is_disabled(), "로그인 모듈은 켜진 채 잠김 (관리자도 못 끔)")
    page.locator("#mod-list label:nth-child(1)").click(force=True)   # 잠긴 스위치라 Playwright 가 '비활성' 으로 본다
    check(login_cb.is_checked() and "4/5 켬" in page.text_content("#mod-meta"), "눌러도 안 꺼진다")
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
    check(page.is_disabled("#sch-add"), "시간은 2개까지 (추가 버튼 잠김)")
    check("primary" in (page.get_attribute("#run-all", "class") or "") and "primary" not in (page.get_attribute("#run-routine", "class") or ""), "강조는 전체 실행에")
    check("▶▶" not in page.text_content("#run-all") and "▶" in page.text_content("#run-all"), "전체 실행 화살표 하나")
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
    accent = lambda: page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--accent').trim()")
    check(accent() == "#2aa198" and "기본" in page.text_content("#accent-now"), "강조색 기본은 cyan")
    page.click("#accent-swatches .swatch[title='violet']")
    check(accent() == "#6c71c4" and page.text_content("#accent-now") == "#6c71c4", "견본을 누르면 강조색이 바뀐다")
    check(page.evaluate("getComputedStyle(document.getElementById('pw-btn')).backgroundColor") == "rgb(108, 113, 196)", "버튼 색도 따라 바뀐다")
    check(page.locator("#accent-swatches .swatch").count() == 4 and page.query_selector("#accent-swatches .swatch[title='yellow']") is None, "견본에 상태 색(노랑 등)은 없다")
    page.fill("#accent-pick", "#b58900"); page.dispatch_event("#accent-pick", "input")
    check(accent() == "#b58900" and page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--accent-ink').trim()") == "#fdf6e3", "직접 고른 색 + 글자색 자동")
    page.reload(); page.wait_for_selector("#main:not(.hide)", timeout=15000)
    check(accent() == "#b58900", "새로고침해도 강조색이 남는다")
    page.click("#admin-nav a[data-key='account']"); page.wait_for_selector("#accent-reset")
    page.click("#accent-reset")
    check(accent() == "#2aa198" and "기본" in page.text_content("#accent-now"), "기본값으로 되돌린다")
    page.click("#app-nav a[data-key='rpa']")
    page.wait_for_selector("#hero")
    check(page.text_content("#page-title") == "RPA", "RPA 로 돌아온다")

    print("7-2절 기록 탭")
    page.click("#tab-history")
    page.wait_for_function("(document.getElementById('hist-msg')?.textContent || '').endsWith('건')", timeout=15000)
    rows = page.locator("#hist-rows tr.hist")
    check(rows.count() == 5, f"이 PC 기록 5건 (다른 PC 1건 제외) ({rows.count()})")
    check("09/14 13:55" in rows.nth(0).text_content() and "09/12" in rows.nth(4).text_content(), "최신순")
    check("주소를 입력하세요" in rows.nth(1).text_content(), "중단 사유가 처리 칸에")
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

    print("8절 열람자")
    page.click("#logout-btn")
    page.wait_for_selector("#login:not(.hide)")
    login(page, "viewer@t.local")
    check("(열람)" in page.text_content("#who"), "열람자로 표시")
    page.wait_for_function("document.getElementById('h-state')?.textContent === '성공'", timeout=10000)
    check(page.is_hidden("#act-card") and page.is_hidden("#mod-card") and page.is_hidden("#sch-card"), "열람자는 실행·모듈·자동 실행 카드가 없다")
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

    check(not errors, f"페이지 오류 없음 {errors[:2]}")
    browser.close()

print(f"\n{COUNT - len(FAIL)}/{COUNT} 통과")
if FAIL:
    print("실패:", ", ".join(FAIL))
    sys.exit(1)
