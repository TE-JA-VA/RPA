# -*- coding: utf-8 -*-
"""환경설정 정리 확인 (DRY_RUN 서버 8766). 지운 문구가 없고, 남은 기능은 그대로인지 본다."""
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from playwright.sync_api import sync_playwright  # noqa: E402

BASE = "http://127.0.0.1:8766"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shots")
os.makedirs(OUT, exist_ok=True)
fails = []


def check(cond, what):
    print(("PASS " if cond else "FAIL ") + what)
    if not cond:
        fails.append(what)


GONE = [
    ("ERPia 는 프로그램을 닫는 것이 곧 로그아웃입니다", "ERPia 종료 설명"),
    ("현황·이력에서 프리페어와 루틴을 구분하는 색입니다", "프로그램 색 설명"),
    ("이 브라우저에서 대시보드 로그인을 끝냅니다", "로그아웃 설명"),
    ("아래에서 비밀번호를 바꿔 두세요", "기본 비밀번호 안내 문구"),
    ("정해진 주기로 Run_All.bat", "자동 실행 켜기 설명"),
    ("앞 실행이 아직 돌고 있으면", "실행 주기 설명"),
]

with sync_playwright() as p:
    b = p.chromium.launch()
    errs = []
    pg = b.new_page(viewport={"width": 1280, "height": 1000})
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(BASE + "/#now"); pg.wait_for_selector("#login-view:not([hidden])")
    pg.fill("#login-code", "erpiatest2"); pg.fill("#login-id", "admin"); pg.fill("#login-pw", "admin"); pg.click("#login-btn")
    pg.wait_for_selector("#programs .card"); pg.wait_for_timeout(600)

    pg.click("#tab-settings"); pg.wait_for_selector("#view-settings:not([hidden])"); pg.wait_for_timeout(500)
    body = pg.inner_text("#view-settings")
    for needle, what in GONE:
        check(needle not in body, f"지워짐: {what}")

    check(pg.locator("#prog-colors").count() == 0, "프로그램 색 항목 자체가 없음")
    check("프로그램 색" not in body, "'프로그램 색' 제목도 없음")

    # 남아야 하는 것
    check(pg.is_visible("#set-enabled"), "자동 실행 켜기 스위치는 그대로")
    check(pg.is_visible("#set-interval"), "실행 주기 선택은 그대로")
    opts = pg.locator("#set-interval option").count()
    check(opts > 3, f"실행 주기 항목 {opts}개")
    check(pg.is_visible("#logout-btn"), "로그아웃 버튼 그대로")
    check(pg.is_visible("#erpia-stop-btn"), "ERPia 종료 버튼 그대로")
    check(pg.is_visible("#swatches"), "강조색 고르기는 그대로")
    for label in ("자동 실행 켜기", "실행 주기", "로그아웃", "ERPia 종료", "강조색", "비밀번호 바꾸기"):
        check(label in body, f"항목 이름 남음: {label}")

    pg.screenshot(path=os.path.join(OUT, "v6_settings.png"), full_page=True)

    # 기본 비밀번호 경고는 제목만 남고 여전히 보인다
    check(pg.is_visible("#pw-default") and "기본 비밀번호를 쓰고 있습니다" in pg.inner_text("#pw-default"),
          "기본 비밀번호 경고 제목은 남음")

    # 프로그램 색은 현황 카드 제목 앞 색 표시로 계속 바꿀 수 있어야 한다
    pg.click("#tab-now"); pg.wait_for_selector("#programs .card"); pg.wait_for_timeout(400)
    key = pg.locator("article.hue-prepare .key-btn").first
    check(key.count() == 1, "현황 카드에 색 표시 버튼 있음")
    key.click(); pg.wait_for_selector(".popover", timeout=3000)
    check(pg.is_visible(".popover"), "색 표시를 누르면 팔레트가 뜬다")
    sw = pg.locator(".popover button[data-k='violet']")
    if sw.count() == 1 and sw.is_enabled():
        sw.click(); pg.wait_for_timeout(300)
        got = pg.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--prepare').trim()")
        check(got.lower() == "#6c71c4", f"고른 색이 적용됨: {got}")
        pg.keyboard.press("Escape"); pg.wait_for_timeout(200)
        pg.locator("article.hue-prepare .key-btn").first.click(); pg.wait_for_selector(".popover")
        pg.locator(".popover .popover-foot button").first.click(); pg.wait_for_timeout(300)
        back = pg.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--prepare').trim()")
        check(back == "" or back.lower() == "#268bd2", f"되돌리기 동작: {back!r}")
    else:
        check(False, "팔레트에서 색을 고를 수 없음")
    pg.keyboard.press("Escape")

    # 휴대폰 폭
    m = b.new_page(viewport={"width": 400, "height": 900})
    m.goto(BASE + "/#now"); m.wait_for_selector("#login-view:not([hidden])")
    m.fill("#login-code", "erpiatest2"); m.fill("#login-id", "admin"); m.fill("#login-pw", "admin"); m.click("#login-btn")
    m.wait_for_selector("#programs .card")
    m.click("#tab-settings"); m.wait_for_selector("#view-settings:not([hidden])"); m.wait_for_timeout(400)
    check(m.evaluate("document.documentElement.scrollWidth <= 400"), "휴대폰: 가로 스크롤 없음")
    m.screenshot(path=os.path.join(OUT, "v6_settings_m.png"), full_page=True)

    b.close()
    check(not errs, f"페이지 오류 없음: {errs[:3]}")

print("\n실패:", fails if fails else "없음")
sys.exit(1 if fails else 0)
