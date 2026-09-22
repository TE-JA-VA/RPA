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
seed_run("r_0911_0900", "routine", "crashed", "2026-09-11T09:00:00", 26,
         reason="프로그램이 도중에 꺼졌습니다 (강제 종료되었거나 오류로 멈췄습니다). 마지막 로그를 확인하세요.")
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

    rgb2hex = lambda s: "#%02x%02x%02x" % tuple(int(x) for x in s[4:-1].split(",")[:3])

    def contrast_ok(theme):
        card = tok("--card")
        pairs = {"글자": contrast(tok("--ink"), card), "회색 글자": contrast(tok("--muted"), card), "제목": contrast(tok("--strong"), card)}
        for st_ in ["good", "warn", "bad", "run"]:
            pairs[f"채운 카드 {st_}"] = contrast(tok("--on-fill"), tok(f"--{st_}-fill"))
        low = {k: round(v, 2) for k, v in pairs.items() if v < 4.5}
        check(not low, f"{theme} 대비 4.5:1 이상 {low or ''}")
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
    check(page.evaluate("getComputedStyle(document.getElementById('run-routine')).color") != card_bg, "어두운 모드에서 테두리 버튼 글자가 카드색과 다르다")
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
    legend = page.text_content("#recent-donut .legend")
    check("성공 1" in legend and "실패 2" in legend and "오류 0" in legend, f"오늘 도넛 범례 세 가지 ({legend.strip()})")
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
    page.wait_for_selector("#act-alert.hide", state="attached", timeout=8000)
    check(page.is_hidden("#act-alert"), "성공 결과 안내는 몇 초 뒤 스스로 사라진다 (상태 카드가 보여 주니까)")
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
    check(page.get_attribute(out_row, "title") == "물류관리를 켜야 쓸 수 있습니다", f"잠긴 이유를 알려 준다 ({page.get_attribute(out_row, 'title')})")
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
    page.reload(); page.wait_for_selector("#main:not(.hide)", timeout=15000); page.wait_for_selector("#mod-list label")
    check(page.locator("#mod-list input[aria-label='물류대기 관리']").count() == 0, "안 쓰는 업체면 그 스위치가 아예 없다")
    check(page.locator("#mod-list label").count() == 4 and "4 켬" in page.text_content("#mod-meta"), f"개수도 빼고 센다 ({page.text_content('#mod-meta')})")
    check(page.is_disabled("#mod-apply"), "숨긴 것 때문에 '바뀜' 으로 보이지 않는다")
    page.click("#mod-list label:nth-child(2)"); page.click("#mod-apply"); time.sleep(1.5)
    sent = cmds_of("set_modules")[-1]["args"]
    check(sent["Hold"] is False, f"명령에도 꺼진 값으로 나간다 ({sent})")
    db_patch("meta/companies/c_demo/apps/rpa", {"modules": None})   # null 로 PATCH = 그 자리 지우기 (PUT 은 본문이 비면 400)
    page.reload(); page.wait_for_selector("#main:not(.hide)", timeout=15000); page.wait_for_selector("#mod-list label")
    check(page.locator("#mod-list label").count() == 5, "정책을 지우면 다시 보인다")

    # RPA 가 도는 동안에는 실행 버튼을 잠근다 (다른 사람이 겹쳐 실행하지 않게). 종료 버튼만 열어 둔다
    db_patch(f"{LIVE}/programs/routine", {"state": "running", "started_at": f"{TODAY}T16:20:00", "updated_at": f"{TODAY}T16:20:28",
                                          "steps_done": 1, "steps_total": 15, "current_label": "주문매핑 화면 이동", "reason": None,
                                          "steps": [{"key": "login", "label": "ERPia 로그인", "state": "done"},
                                                    {"key": "sales", "label": "주문매핑 화면 이동", "state": "running"},
                                                    {"key": "top", "label": "상단 선택", "state": "pending"}]})
    page.wait_for_function("document.getElementById('run-routine')?.disabled === true", timeout=10000)
    check(all(page.is_disabled(f"#{i}") for i in ("run-all", "run-prepare", "run-routine")), "도는 중에는 실행 버튼 셋 다 잠김")
    check(not page.is_disabled("#stop-erpia"), "ERPia 종료는 도는 중에도 누를 수 있다")
    check("돌고 있어" in (page.get_attribute("#run-all", "title") or ""), "잠긴 이유를 알려 준다")
    # 진행 중 단계 점만 숨쉬고, 로그가 늘어도 애니메이션이 처음부터 다시 돌지 않는다 (목록을 제자리에서 고친다)
    anim = lambda sel: page.evaluate(f"getComputedStyle(document.querySelector({sel!r})).animationName")
    check(anim("#list-routine li.running .mark") == "step-glow", "진행 중 점이 숨쉰다")
    check(anim("#hero .dot") == "hero-glow", "상태 카드 점도 같이 숨쉰다")
    check(anim("#list-routine li.done .mark") == "none" and anim("#list-routine li.pending .mark") == "none", "끝난·대기 단계는 안 움직인다")
    mark_id = "document.querySelector('#list-routine li.running .mark')"
    page.evaluate(f"window.__mark = {mark_id}")
    db_patch(f"{LIVE}/programs/routine", {"log_tail": ["[16:20:30] 새 줄"], "updated_at": f"{TODAY}T16:20:30"})
    page.wait_for_function("(document.getElementById('log')?.textContent || '').includes('새 줄')", timeout=10000)
    check(page.evaluate(f"window.__mark === {mark_id}"), "로그가 늘어도 진행 중 점은 그대로 (애니메이션이 안 끊긴다)")
    db_patch(f"{LIVE}/programs/routine", {"steps": [{"key": "login", "label": "ERPia 로그인", "state": "done"},
                                                    {"key": "sales", "label": "주문매핑 화면 이동", "state": "done"},
                                                    {"key": "top", "label": "상단 선택", "state": "running"}]})
    page.wait_for_function("document.querySelectorAll('#list-routine li.done').length === 2", timeout=10000)
    check(anim("#list-routine li.running .mark") == "step-glow" and page.text_content("#list-routine li:nth-child(3) .note") == "진행 중",
          "단계가 넘어가면 다음 줄로 옮겨 간다")
    db_patch(f"{LIVE}/programs/routine", routine)
    page.wait_for_function("document.getElementById('run-routine')?.disabled === false", timeout=10000)
    check(True, "끝나면 다시 눌린다")
    # 띄우자마자 상태 파일에 아직 running 이 안 찍힌 몇 초 (에이전트가 launching 으로 알려 준다)
    db_patch(LIVE, {"launching": True})
    page.wait_for_function("document.getElementById('run-routine')?.disabled === true", timeout=10000)
    check(page.is_disabled("#run-all") and not page.is_disabled("#stop-erpia"), "띄우는 중에도 실행 버튼은 잠긴다")
    db_patch(LIVE, {"launching": False})
    page.wait_for_function("document.getElementById('run-routine')?.disabled === false", timeout=10000)
    check(True, "띄우기가 끝나면 풀린다")

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
    check(all(page.locator(f"#{i} svg").count() == 1 for i in ("run-all", "run-prepare", "run-routine")), "실행 버튼은 화살표 아이콘 하나")
    check(page.text_content("#stop-erpia .ic") == "⏼" and page.locator("#stop-erpia svg").count() == 0, "ERPia 종료는 전원 글자 ⏼ (U+23FC)")
    ic_w = page.evaluate("document.querySelector('#stop-erpia .ic').getBoundingClientRect().width")
    check(ic_w > 10, f"전원 글자가 실제로 그려진다 (폭 {ic_w:.0f}px)")
    check(not page.is_disabled("#stop-erpia"), "종료 버튼 활성")
    page.hover("#stop-erpia"); page.wait_for_timeout(800)
    stop_bg = page.evaluate("getComputedStyle(document.getElementById('stop-erpia')).backgroundColor")
    check(rgb2hex(stop_bg) == token("--bad-fill"), f"종료 버튼은 올리면 빨강 ({stop_bg})")
    page.hover("#run-routine"); page.wait_for_timeout(800)
    run_bg = page.evaluate("getComputedStyle(document.getElementById('run-routine')).backgroundColor")
    check(rgb2hex(run_bg) == token("--accent"), f"실행 버튼은 올리면 강조색 ({run_bg})")
    if os.environ.get("SHOT_DIR"):   # 눈으로 볼 때: 실행 카드 (루틴에 올린 상태 / 종료에 올린 상태)
        page.locator("#act-card").screenshot(path=os.path.join(os.environ["SHOT_DIR"], "act_hover_run.png"))
        page.hover("#stop-erpia"); page.wait_for_timeout(800)
        page.locator("#act-card").screenshot(path=os.path.join(os.environ["SHOT_DIR"], "act_hover_stop.png"))
        page.hover("#run-all"); page.wait_for_timeout(800)
        page.locator("#act-card").screenshot(path=os.path.join(os.environ["SHOT_DIR"], "act_hover_all.png"))
    page.mouse.move(0, 0)
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
    check(accent() == "#1e1e2c" and ink() == "#fdf6e3", "진한 강조색엔 밝은 글자")
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
