# -*- coding: utf-8 -*-
"""프로그램 색 팔레트 시험: 카드 제목 앞 색 표시 → 팔레트 → 색 선택/경고/같은 색 비활성/기본색/저장."""
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from playwright.sync_api import sync_playwright  # noqa: E402

BASE = "http://127.0.0.1:8766"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shots")
fails = []


def check(cond, what):
    print(("PASS " if cond else "FAIL ") + what)
    if not cond:
        fails.append(what)


with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1280, "height": 900})
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(BASE + "/#now"); pg.wait_for_selector("#login-view:not([hidden])")
    pg.fill("#login-code", "erpiatest2"); pg.fill("#login-id", "admin"); pg.fill("#login-pw", "admin"); pg.click("#login-btn")
    pg.wait_for_selector("#programs .card"); pg.wait_for_timeout(500)
    if pg.evaluate("document.documentElement.getAttribute('data-theme')") != "dark":
        pg.click("#theme-btn")
    prepare_var = lambda: pg.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--prepare').trim()")
    check(prepare_var() == "#268bd2", f"기본 프리페어 색 {prepare_var()}")

    pg.click("article.hue-prepare .key-btn"); pg.wait_for_selector(".popover"); pg.wait_for_timeout(200)
    check(pg.is_visible(".popover"), "색 표시 누르면 팔레트")
    check(pg.is_disabled(".popover .swatch[data-k='orange']"), "루틴이 쓰는 주황은 비활성")
    pg.screenshot(path=os.path.join(OUT, "v4_palette_open.png"), clip={"x": 0, "y": 180, "width": 700, "height": 420})
    pg.click(".popover .swatch[data-k='violet']"); pg.wait_for_timeout(200)
    check(prepare_var() == "#6c71c4", f"보라 선택 → --prepare {prepare_var()}")
    ring = pg.evaluate("getComputedStyle(document.querySelector('article.hue-prepare .ring .arc')).stroke")
    check(ring == "rgb(108, 113, 196)", f"프리페어 고리 색 반영 {ring}")
    check(pg.evaluate("localStorage.getItem('rpa.color.prepare')") == "violet", "저장")
    check(pg.is_hidden(".popover-warn"), "보라-주황은 경고 없음")
    pg.click(".popover .swatch[data-k='red']"); pg.wait_for_timeout(200)
    check(pg.is_visible(".popover-warn"), "빨강-주황은 구분 경고")
    pg.screenshot(path=os.path.join(OUT, "v4_palette_warn.png"), clip={"x": 0, "y": 180, "width": 700, "height": 460})
    pg.keyboard.press("Escape"); pg.wait_for_timeout(150)
    check(pg.locator(".popover").count() == 0, "Esc 로 닫힘")
    pg.reload(); pg.wait_for_selector("#programs .card"); pg.wait_for_timeout(500)
    check(prepare_var() == "#dc322f", "새로고침 뒤에도 유지")

    # 이력·환경설정에도 반영
    pg.goto(BASE + "/#history"); pg.wait_for_selector("#hist-body tr"); pg.wait_for_timeout(300)
    k = pg.evaluate("getComputedStyle(document.querySelector('#hist-body .hue-prepare .key')).backgroundColor")
    check(k == "rgb(220, 50, 47)", f"이력 표 색 반영 {k}")
    pg.goto(BASE + "/#settings"); pg.wait_for_selector("#prog-colors .key-btn"); pg.wait_for_timeout(300)
    check("빨강" in pg.inner_text("#prog-colors"), "환경설정 화면 카드에 현재 색 이름")
    pg.click("#prog-colors .key-btn >> nth=0"); pg.wait_for_selector(".popover")
    pg.click(".popover button:has-text('기본색으로')"); pg.wait_for_timeout(200)
    check(prepare_var() == "#268bd2" and pg.evaluate("localStorage.getItem('rpa.color.prepare')") is None, "기본색으로 되돌림")
    pg.click(".popover button:has-text('닫기')"); pg.wait_for_timeout(100)
    pg.screenshot(path=os.path.join(OUT, "v4_settings_look.png"), full_page=True)

    # 휴대폰 폭에서 팔레트가 화면 안에 들어오는지
    m = b.new_page(viewport={"width": 400, "height": 820})
    m.goto(BASE + "/#now"); m.wait_for_selector("#login-view:not([hidden])")
    m.fill("#login-code", "erpiatest2"); m.fill("#login-id", "user"); m.fill("#login-pw", "user"); m.click("#login-btn")
    m.wait_for_selector("#programs .card"); m.wait_for_timeout(400)
    m.click("article.hue-routine .key-btn"); m.wait_for_selector(".popover"); m.wait_for_timeout(200)
    box = m.evaluate("(() => { const r = document.querySelector('.popover').getBoundingClientRect(); return [r.left, r.right]; })()")
    check(box[0] >= 0 and box[1] <= 400, f"휴대폰: 팔레트가 화면 안 {box}")
    m.screenshot(path=os.path.join(OUT, "v4_m_palette.png"), clip={"x": 0, "y": 0, "width": 400, "height": 820})
    b.close()
    check(not errors, f"페이지 오류 없음: {errors[:3]}")

print("\n실패:", fails if fails else "없음")
sys.exit(1 if fails else 0)
