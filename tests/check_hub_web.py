# -*- coding: utf-8 -*-
"""옵저버 관제 화면 (hub/) 시험 - Playwright headless (창 없음). observer_hub 를 DRY_RUN 으로 이 프로세스 안에 띄우고
가짜 프리셋·상태 파일을 둔다.
    .venv\\Scripts\\python.exe tests\\check_hub_web.py
"""
import io
import json
import os
import sys
import tempfile
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
TMP = tempfile.mkdtemp(prefix="rpa_hub_web_")
os.environ["RPA_STANDALONE"] = "1"
os.environ["RPA_STATUS_DIR"] = os.path.join(TMP, "status")
os.environ["RPA_PROGRAMDATA"] = os.path.join(TMP, "programdata")
os.environ["RPA_USER_CONFIG"] = os.path.join(TMP, "config", "RPA_UserConfig.json")
os.environ["RPA_DASHBOARD_DRY_RUN"] = "1"
os.environ["RPA_OBSERVER_LOCK"] = rf"Local\AFTER_MARKET_OBSERVER_SA_HUBWEB_TEST_{os.getpid()}"
os.makedirs(os.path.join(TMP, "config"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from playwright.sync_api import sync_playwright  # noqa: E402
import rpa_status as st  # noqa: E402
import rpa_dashboard as d  # noqa: E402
import observer_hub as hub  # noqa: E402
import web_replay  # noqa: E402

fails = []


def check(cond, what, detail=""):
    print(("PASS " if cond else "FAIL ") + what + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(what)


REC = {"version": 1, "start_url": "https://shop.example.com/login", "record_date": "2026-11-03",
       "steps": [{"kind": "goto", "page": 0, "url": "/login", "href": "https://shop.example.com/login", "gap": 0}]}
st.write_user_config({"LogIn": {"AdminCode": "", "ID": "", "PW": ""}, "Sites": {}})
st.write_presets([dict(st.blank_preset(1), name="가몰", code="011", record=REC), dict(st.blank_preset(2), name="나몰", code="012", record=REC)])
st.save_preset_sites(st.read_presets(), {1: ("a", "pw"), 2: ("b", "pw")})
st.set_preset_switches({"1": True, "2": False})
httpd = hub.start(range(18785, 18795))
BASE = f"http://127.0.0.1:{httpd.server_address[1]}"


def write_status(note):
    os.makedirs(st.status_dir(), exist_ok=True)
    with open(st.status_path("prepare"), "w", encoding="utf-8") as f:
        json.dump({"run_id": "r1", "program": "prepare", "state": "running", "pid": os.getpid(), "pid_created": st.process_created(os.getpid()),
                   "started_at": st.now_iso(), "updated_at": st.now_iso(), "current": "PRESET1:replay", "note": note,
                   "steps": [{"key": "PRESET1:replay", "label": "가몰 엑셀 받기", "state": "running", "note": note}], "metrics": [], "log_tail": []}, f)


errs = []
with sync_playwright() as p:
    b = web_replay.edge(p.chromium.launch, headless=True)
    # 화면의 CSP 는 eval 을 막는다 (script-src 'self') - Playwright 의 evaluate·wait_for_function 이 eval 을 쓰므로 시험만 CSP 를 끈다
    pg = b.new_context(bypass_csp=True, viewport={"width": 1280, "height": 900}).new_page()
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("dialog", lambda dlg: dlg.accept())
    pg.goto(BASE + "/#now")
    try:
        pg.wait_for_selector("#presets-table tbody tr", state="attached", timeout=10000)
    except Exception:
        print("페이지 오류:", errs)
        raise
    print("=== 1. 메뉴 ===")
    menus = [a.inner_text() for a in pg.query_selector_all("#nav a")]
    check(menus == ["현황", "프리셋", "예약", "기록", "설정"], "메뉴 다섯", menus)
    check(pg.inner_text("#hero-title") == "실행 기록 없음", "현황: 기록 없음", pg.inner_text("#hero-title"))

    print("=== 2. 프리셋 ===")
    pg.click("a[data-view=presets]")
    rows = pg.query_selector_all("#presets-table tbody tr")
    cells = [[td.inner_text() for td in r.query_selector_all("td")] for r in rows]
    check(len(rows) == 2 and cells[0][1:5] == ["1", "가몰", "011", "켬"] and cells[1][1:5] == ["2", "나몰", "012", "끔"], "프리셋 표 (번호·이름·사이트코드·켬/끔)", cells)
    pg.check("#presets-table tbody tr:nth-child(1) input[type=checkbox]")
    check(pg.inner_text("#run-btn") == "지금 실행 (1)", "고르면 단추에 번호", pg.inner_text("#run-btn"))
    pg.click("#run-btn")
    pg.wait_for_function("document.getElementById('presets-msg').textContent.includes('띄웠습니다')", timeout=10000)
    check(d.LAUNCHED == ["prepare:manual:hub"] and d.LAUNCHED_ENV[-1]["RPA_RUN_PRESETS"] == "1", "[지금 실행] → 그 번호로 ACTOR",
          (d.LAUNCHED, d.LAUNCHED_ENV[-1:], pg.inner_text("#presets-msg")))
    d._active["until"] = 0; d._active["proc"] = None

    print("=== 3. 예약 ===")
    pg.click("a[data-view=schedule]")
    pg.wait_for_selector("#sch-add")
    check(pg.is_disabled("#sch-apply"), "처음엔 [적용] 비활성")
    pg.click("#sch-add")
    pg.fill("#sch-times .t:last-child input[type=time]", "10:30")     # 기본 줄 09:00 과 겹치지 않게
    pg.select_option("#sch-times .t:last-child select.mode", "pick")
    pg.click("#sch-times .t:last-child .chips button[data-no='1']")
    if not pg.is_checked("#sch-enabled"):
        pg.click("#sch-enabled + .knob")          # 스위치 입력은 숨겨져 있다 - 손잡이를 누른다
    check(not pg.is_disabled("#sch-apply"), "줄 추가·프리셋 고르면 [적용] 활성", pg.inner_text("#sch-msg"))
    pg.click("#sch-apply")
    pg.wait_for_function("document.getElementById('sch-info').textContent.includes('저장') || document.getElementById('sch-msg').textContent.length > 0")
    check("저장" in pg.inner_text("#sch-info"), "[적용] 됨", pg.inner_text("#sch-msg"))
    saved = st.read_settings()["schedule"]
    check(saved["enabled"] and any(s.get("presets") == [1] for s in saved["slots"]), "[적용] → 서버 설정에 presets [1]", saved["slots"])
    pg.wait_for_timeout(3500)      # 다시 읽어도
    check(pg.is_disabled("#sch-apply"), "다시 읽어도 바뀜 없음 → [적용] 비활성")
    pg.click("#sch-add")
    pg.wait_for_timeout(3500)
    check(len(pg.query_selector_all("#sch-times .t")) == len(saved["slots"]) + 1 and not pg.is_disabled("#sch-apply"), "적용 안 한 변경은 다시 읽어도 안 덮는다")
    texts = [x.inner_text() for x in pg.query_selector_all("#sch-times .t select.mode option")]
    check(texts[:2] == ["모든 켠 프리셋", "고른 프리셋만"], "프리셋 고르기 글", texts)

    print("=== 4. 사람 인증 대기 띠 ===")
    write_status("인증번호 입력 대기 - 가몰")
    pg.click("a[data-view=now]")
    pg.wait_for_selector("#otp-band:not(.hide)", timeout=8000)
    check(pg.inner_text("#otp-band") == "인증번호 입력 대기 - 가몰. 열린 브라우저 창에 번호를 넣고 [확인]을 눌러 주십시오. (5분)", "띠 글", pg.inner_text("#otp-band"))
    check(pg.inner_text("#hero-title") == "ACTOR 실행 중", "현황 머리 '실행 중'", pg.inner_text("#hero-title"))
    write_status("")
    pg.wait_for_selector("#otp-band.hide", state="attached", timeout=8000)
    check(True, "대기가 끝나면 띠가 사라진다")

    print("=== 5. 설정 ===")
    pg.click("a[data-view=settings]")
    pg.fill("#set-dir", "Q:\\없는드라이브\\x")
    pg.click("#set-apply")
    pg.wait_for_function("document.getElementById('set-msg').textContent.length > 0")
    check(pg.inner_text("#set-msg") == "받은 파일 폴더를 만들 수 없습니다: Q:\\없는드라이브\\x" and "bad" in pg.get_attribute("#set-msg", "class"), "잘못된 경로면 빨간 글",
          pg.inner_text("#set-msg"))
    good = os.path.join(TMP, "받은파일")
    pg.fill("#set-dir", good)
    pg.click("#set-apply")
    pg.wait_for_function("document.getElementById('set-msg').textContent.includes('저장')")
    check(st.download_dir_choice() == good and os.path.isdir(good), "받은 파일 폴더 저장")

    print("=== 6. 폰 폭 ===")
    pg.set_viewport_size({"width": 390, "height": 800})
    for v in ("now", "presets", "schedule", "history", "settings"):
        pg.click(f"a[data-view={v}]")
        pg.wait_for_timeout(200)
        w = pg.evaluate("() => document.documentElement.scrollWidth")
        check(w <= 390, f"390px 에서 가로 스크롤 없음: {v}", w)
    check(not errs, "페이지 오류 없음", errs)
    b.close()

httpd.shutdown()
print("\n실패:", fails if fails else "없음")
sys.exit(1 if fails else 0)
