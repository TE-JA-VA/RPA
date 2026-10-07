# -*- coding: utf-8 -*-
"""요일 + 시간 예약 화면 시험. 시험 서버(8766, DRY_RUN, 복사한 기록 폴더)를 직접 띄우고 끈다."""
import datetime as dt
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from playwright.sync_api import sync_playwright  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "shots")
os.makedirs(OUT, exist_ok=True)
BASE = "http://127.0.0.1:8766"
fails = []


def check(cond, what):
    print(("PASS " if cond else "FAIL ") + what)
    if not cond:
        fails.append(what)


# 계정이 들어 있는 시뮬레이터 폴더를 복사해서 쓴다 (원본은 건드리지 않는다)
sim = tempfile.mkdtemp(prefix="rpa_ui_sched_")
shutil.copytree(os.path.join(HERE, "status_sim"), sim, dirs_exist_ok=True)
cfg = json.load(open(os.path.join(sim, "settings.json"), encoding="utf-8"))
cfg["schedule"] = {"enabled": False, "interval_min": 15, "next_run_at": None}   # 예전 방식 설정에서 넘어오는 경우
json.dump(cfg, open(os.path.join(sim, "settings.json"), "w", encoding="utf-8"), ensure_ascii=False)

srv = subprocess.Popen([r"D:\AX\RPA\.venv\Scripts\python.exe", "rpa_dashboard.py", "--port", "8766", "--host", "127.0.0.1", "--no-scheduler"],
                       cwd=r"D:\AX\RPA", env=dict(os.environ, RPA_DASHBOARD_DRY_RUN="1", RPA_STATUS_DIR=sim),
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
for _ in range(50):
    try:
        urllib.request.urlopen(BASE + "/healthz", timeout=1)
        break
    except Exception:
        time.sleep(0.2)


def pressed(pg, sel):
    return [b.inner_text() for b in pg.query_selector_all(sel) if b.get_attribute("aria-pressed") == "true"]


def login(pg, uid):
    pg.goto(BASE + "/#now"); pg.wait_for_selector("#login-view:not([hidden])")
    pg.fill("#login-code", "erpiatest2"); pg.fill("#login-id", uid); pg.fill("#login-pw", uid); pg.click("#login-btn")
    pg.wait_for_selector("#programs .card")


try:
    with sync_playwright() as p:
        b = p.chromium.launch()
        errs = []
        pg = b.new_page(viewport={"width": 1280, "height": 1000})
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("dialog", lambda d_: d_.accept())
        login(pg, "admin")
        pg.click("#tab-settings"); pg.wait_for_selector("#set-days button"); pg.wait_for_timeout(400)

        print("=== 처음 모양 (예전 설정에서 넘어옴 -> 기본 평일 09:00) ===")
        body = pg.inner_text("#view-settings")
        check("실행 주기" not in body and pg.locator("#set-interval").count() == 0, "'실행 주기' 없어짐")
        check([x.inner_text() for x in pg.query_selector_all("#set-presets button")] == ["매일", "평일", "주말"], "빠른 선택: 매일/평일/주말")
        check([x.inner_text() for x in pg.query_selector_all("#set-days button")] == list("월화수목금토일"), "요일 7개")
        check(pressed(pg, "#set-presets button") == ["평일"] and pressed(pg, "#set-days button") == list("월화수목금"), "평일이 눌린 상태")
        rows = pg.query_selector_all("#set-times .time-row")
        check(len(rows) == 1, f"시간 1줄 ({len(rows)})")
        sels = pg.query_selector_all("#set-times .time-row select")
        check([s.input_value() for s in sels] == ["09", "00"], "09:00")
        check(len(sels[0].query_selector_all("option")) == 24, "시 24개 (00~23)")
        mins = [o.get_attribute("value") for o in sels[1].query_selector_all("option")]
        check(mins == [f"{m:02d}" for m in range(0, 60, 5)], f"분은 5분 단위 12개: {mins[:4]}…{mins[-1]}")
        check(pg.is_disabled("#set-times .time-del"), "시간이 하나면 삭제 잠김")
        check(pg.is_hidden("#set-dirty") and pg.is_disabled("#set-apply"), "바꾸기 전: 경고 없음, 적용 잠김")
        pg.screenshot(path=os.path.join(OUT, "v7_schedule_initial.png"), clip={"x": 0, "y": 60, "width": 660, "height": 520})

        print("\n=== 요일 고르기 ===")
        pg.click("#set-presets button[data-preset='weekend']")
        check(pressed(pg, "#set-presets button") == ["주말"] and pressed(pg, "#set-days button") == ["토", "일"], "주말 -> 토·일")
        check(pg.is_visible("#set-dirty") and pg.is_enabled("#set-apply"), "바꾸면 미적용 경고 + 적용 활성")
        pg.click("#set-days button[data-day='0']")
        check(pressed(pg, "#set-presets button") == [] and pressed(pg, "#set-days button") == ["월", "토", "일"], "월 추가 -> 빠른 선택은 해제")
        pg.click("#set-presets button[data-preset='all']")
        check(pressed(pg, "#set-days button") == list("월화수목금토일"), "매일 -> 7개 모두")
        for i in range(7):
            pg.click(f"#set-days button[data-day='{i}']")
        check(pressed(pg, "#set-days button") == [] and pg.is_disabled("#set-apply"), "요일을 다 빼면 적용 잠김")
        check("요일을 하나 이상" in pg.inner_text("#set-msg"), f"안내: {pg.inner_text('#set-msg')!r}")
        pg.click("#set-presets button[data-preset='weekdays']")
        check(pg.inner_text("#set-msg") == "", "고치면 안내 사라짐")
        pg.click("#set-days button[data-day='5']")   # 평일 + 토

        print("\n=== 시간 고르기 ===")
        pg.click("#set-add-time")
        sels = pg.query_selector_all("#set-times .time-row select")
        check(len(sels) == 4 and [s.input_value() for s in sels[2:]] == ["10", "00"], "시간 추가 -> 한 시간 뒤 10:00")
        check(pg.is_enabled("#set-times .time-row:nth-child(1) .time-del"), "두 줄이면 삭제 가능")
        sels[2].select_option("09")
        check(pg.is_disabled("#set-apply") and "같은 시간" in pg.inner_text("#set-msg"), "같은 시간 두 번 -> 적용 잠김 + 안내")
        pg.query_selector_all("#set-times .time-row select")[3].select_option("35")
        check(pg.is_enabled("#set-apply") and pg.inner_text("#set-msg") == "", "09:35 로 고치면 풀림")
        pg.click("#set-add-time")
        check(len(pg.query_selector_all("#set-times .time-row")) == 3 and pg.is_disabled("#set-add-time"),
              "시간은 3개까지 - 세 개면 '시간 추가' 잠김")
        pg.query_selector_all("#set-times .time-row .time-del")[2].click()
        check(len(pg.query_selector_all("#set-times .time-row")) == 2 and pg.is_enabled("#set-add-time"),
              "세 번째 줄 삭제하면 다시 추가할 수 있음")

        print("\n=== 적용 ===")
        pg.check("#set-enabled")
        pg.click("#set-apply")
        pg.wait_for_selector("#set-msg:has-text('적용했습니다')", timeout=5000)
        view = pg.evaluate("fetch('/api/settings').then(r => r.json())")
        sch = view["schedule"]
        check(sch["enabled"] and sch["days"] == [0, 1, 2, 3, 4, 5] and sch["times"] == ["09:00", "09:35"], f"저장됨: {sch['days']} {sch['times']}")
        nxt = dt.datetime.fromisoformat(sch["next_run_at"])
        check(nxt > dt.datetime.now() and nxt.weekday() in sch["days"] and nxt.strftime("%H:%M") in sch["times"], f"다음 실행 {sch['next_run_at']}")
        check(sch["label"] == "월·화·수·목·금·토 09:00, 09:35", f"서버 이름표: {sch['label']}")
        check(pg.inner_text("#sch-meta") == "월·화·수·목·금·토 09:00, 09:35", f"카드 머리: {pg.inner_text('#sch-meta')}")
        check(pg.is_hidden("#set-dirty") and pg.is_disabled("#set-apply"), "적용 뒤 경고 사라짐")
        pg.screenshot(path=os.path.join(OUT, "v7_schedule_applied.png"), clip={"x": 0, "y": 60, "width": 660, "height": 560})
        pg.click("#tab-now"); pg.wait_for_timeout(2500)
        hero = pg.inner_text("#hero-next")
        check("다음 자동 실행" in hero and "09:00, 09:35" in hero and "마다" not in hero, f"현황 카드: {hero}")

        print("\n=== 새로고침해도 유지 ===")
        pg.reload(); pg.wait_for_selector("#programs .card")
        pg.click("#tab-settings"); pg.wait_for_selector("#set-days button"); pg.wait_for_timeout(400)
        check(pressed(pg, "#set-days button") == list("월화수목금토"), "요일 유지")
        check([s.input_value() for s in pg.query_selector_all("#set-times .time-row select")] == ["09", "00", "09", "35"], "시간 유지")
        check(pg.is_checked("#set-enabled"), "켜짐 유지")

        print("\n=== 일반 사용자 ===")
        u = b.new_page(viewport={"width": 1280, "height": 1000})
        u.on("pageerror", lambda e: errs.append("user: " + str(e)))
        login(u, "user")
        u.click("#tab-settings"); u.wait_for_selector("#set-days button"); u.wait_for_timeout(400)
        check(all(x.is_disabled() for x in u.query_selector_all("#set-days button, #set-presets button, #set-times select")), "요일·시간 모두 잠김")
        check(u.is_hidden("#set-add-time") and u.locator("#set-times .time-del:visible").count() == 0, "시간 추가/삭제 버튼 안 보임")
        ck = {c["name"]: c["value"] for c in u.context.cookies()}
        req = urllib.request.Request(BASE + "/api/settings", data=b'{"schedule":{"enabled":true,"days":[0],"times":["09:00"]}}', method="POST",
                                     headers={"Content-Type": "application/json", "X-RPA-Action": "1", "Cookie": f"rpa_session={ck['rpa_session']}"})
        try:
            urllib.request.urlopen(req, timeout=5); check(False, "일반 사용자 적용 거부")
        except urllib.error.HTTPError as e:
            check(e.code == 403, f"일반 사용자 적용 거부 ({e.code})")

        print("\n=== 서버가 틀린 값 거부 ===")
        ck = {c["name"]: c["value"] for c in pg.context.cookies()}
        for body_, what in ((b'{"schedule":{"enabled":true,"days":[],"times":["09:00"]}}', "요일 없음"),
                            (b'{"schedule":{"enabled":true,"days":[0],"times":["09:07"]}}', "5분 단위 아님"),
                            (json.dumps({"schedule": {"enabled": True, "days": [0], "times": [f"{h:02d}:00" for h in range(13)]}}).encode(), "시간 13개")):
            req = urllib.request.Request(BASE + "/api/settings", data=body_, method="POST",
                                         headers={"Content-Type": "application/json", "X-RPA-Action": "1", "Cookie": f"rpa_session={ck['rpa_session']}"})
            try:
                urllib.request.urlopen(req, timeout=5); check(False, f"거부: {what}")
            except urllib.error.HTTPError as e:
                check(e.code == 400, f"거부: {what} ({e.code}: {json.loads(e.read()).get('error')})")

        print("\n=== 휴대폰 폭 / 어두운 화면 ===")
        m = b.new_page(viewport={"width": 400, "height": 900})
        m.on("pageerror", lambda e: errs.append("mobile: " + str(e)))
        login(m, "admin")
        m.click("#tab-settings"); m.wait_for_selector("#set-days button"); m.wait_for_timeout(400)
        check(m.evaluate("document.documentElement.scrollWidth <= 400"), "휴대폰: 가로 스크롤 없음")
        m.screenshot(path=os.path.join(OUT, "v7_schedule_mobile.png"), clip={"x": 0, "y": 0, "width": 400, "height": 760})
        if pg.evaluate("document.documentElement.getAttribute('data-theme')") != "dark":
            pg.click("#theme-btn")
        pg.wait_for_timeout(300)
        pg.screenshot(path=os.path.join(OUT, "v7_schedule_dark.png"), clip={"x": 0, "y": 60, "width": 660, "height": 560})

        b.close()
        check(not errs, f"페이지 오류 없음: {errs[:3]}")
finally:
    # venv 파이썬은 실행기라 자식까지 같이 끈다
    subprocess.run(["taskkill", "/PID", str(srv.pid), "/T", "/F"], capture_output=True)
    shutil.rmtree(sim, ignore_errors=True)

print("\n실패:", fails if fails else "없음")
sys.exit(1 if fails else 0)
