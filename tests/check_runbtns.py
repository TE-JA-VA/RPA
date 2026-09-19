# -*- coding: utf-8 -*-
"""실행 버튼 세 개 시험 (DRY_RUN 서버, 8766). 띄운 뒤 3초 동안 '실행 중' 잠금이 유지되는지 본다."""
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
    errors = []
    dialogs = []
    pg = b.new_page(viewport={"width": 1280, "height": 900})
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(BASE + "/#now"); pg.wait_for_selector("#login-view:not([hidden])")
    pg.fill("#login-code", "erpiatest2"); pg.fill("#login-id", "admin"); pg.fill("#login-pw", "admin"); pg.click("#login-btn")
    pg.wait_for_selector("#programs .card"); pg.wait_for_timeout(600)
    btns = ["#run-all", "article.hue-prepare .run-btn", "article.hue-routine .run-btn"]
    texts = [pg.inner_text(x) for x in btns]
    check(texts == ["전체 실행", "프리페어 실행", "루틴 실행"], f"버튼 세 개: {texts}")
    check(all(pg.is_enabled(x) for x in btns), "처음엔 셋 다 활성")
    if pg.evaluate("document.documentElement.getAttribute('data-theme')") != "dark":
        pg.click("#theme-btn")
    pg.screenshot(path=os.path.join(OUT, "v5_runbtns.png"), clip={"x": 0, "y": 60, "width": 1280, "height": 330})

    pg.once("dialog", lambda d_: (dialogs.append(d_.message), d_.accept()))
    pg.click("article.hue-prepare .run-btn"); pg.wait_for_selector("#run-msg:has-text('띄웠습니다')", timeout=5000); pg.wait_for_timeout(300)
    check("프리페어" in dialogs[-1], f"프리페어 확인창: {dialogs[-1][:40]}")
    check(all(pg.is_disabled(x) for x in btns), "띄운 뒤 셋 다 잠김")
    check("시작하는 중" in pg.inner_text("article.hue-prepare .run-btn") and pg.locator("article.hue-prepare .run-btn.is-running").count() == 1, f"프리페어 버튼 = {pg.inner_text('article.hue-prepare .run-btn')!r}")
    check("실행" in pg.inner_text("#run-all") and "중" not in pg.inner_text("#run-all"), "전체 실행 버튼은 이름 그대로(잠김)")
    check("시작하는 중" in pg.inner_text("#hero-title"), f"현황 제목: {pg.inner_text('#hero-title')!r}")
    pg.screenshot(path=os.path.join(OUT, "v5_runbtns_locked.png"), clip={"x": 0, "y": 60, "width": 1280, "height": 330})
    pg.wait_for_timeout(4500)   # DRY_RUN 은 3초 뒤 '끝남'
    check(all(pg.is_enabled(x) for x in btns), "끝나면 셋 다 풀림")

    pg.once("dialog", lambda d_: (dialogs.append(d_.message), d_.accept()))
    pg.click("#run-all"); pg.wait_for_selector("#run-msg:has-text('띄웠습니다')", timeout=5000); pg.wait_for_timeout(300)
    check("전체 실행" in dialogs[-1] and pg.locator("#run-all.is-running").count() == 1 and all(pg.is_disabled(x) for x in btns), "전체 실행: 잠김 + 실행 중 표시")
    pg.wait_for_timeout(4500)
    pg.once("dialog", lambda d_: (dialogs.append(d_.message), d_.accept()))
    pg.click("article.hue-routine .run-btn"); pg.wait_for_selector("#run-msg:has-text('띄웠습니다')", timeout=5000); pg.wait_for_timeout(300)
    check(pg.locator("article.hue-routine .run-btn.is-running").count() == 1 and all(pg.is_disabled(x) for x in btns), "루틴 실행: 잠김 + 실행 중 표시")
    # 잠긴 동안 서버에 직접 요청해도 거부
    ck = {c["name"]: c["value"] for c in pg.context.cookies()}
    import json, urllib.request
    req = urllib.request.Request(BASE + "/api/run", data=b'{"target":"all"}', method="POST",
                                 headers={"Content-Type": "application/json", "X-RPA-Action": "1", "Cookie": f"rpa_session={ck['rpa_session']}"})
    try:
        urllib.request.urlopen(req, timeout=5); check(False, "잠긴 동안 서버도 거부")
    except urllib.error.HTTPError as e:
        check(e.code == 409, f"잠긴 동안 서버도 거부 ({e.code}: {json.loads(e.read()).get('error')})")
    pg.wait_for_timeout(4500)

    # 휴대폰 폭 배치
    m = b.new_page(viewport={"width": 400, "height": 820})
    m.goto(BASE + "/#now"); m.wait_for_selector("#login-view:not([hidden])")
    m.fill("#login-code", "erpiatest2"); m.fill("#login-id", "admin"); m.fill("#login-pw", "admin"); m.click("#login-btn")
    m.wait_for_selector("#programs .card"); m.wait_for_timeout(500)
    check(m.evaluate("document.documentElement.scrollWidth <= 400"), "휴대폰: 가로 스크롤 없음")
    m.screenshot(path=os.path.join(OUT, "v5_m_runbtns.png"), clip={"x": 0, "y": 0, "width": 400, "height": 420})
    u = b.new_page(viewport={"width": 1280, "height": 900})
    u.goto(BASE + "/#now"); u.wait_for_selector("#login-view:not([hidden])")
    u.fill("#login-code", "erpiatest2"); u.fill("#login-id", "user"); u.fill("#login-pw", "user"); u.click("#login-btn")
    u.wait_for_selector("#programs .card"); u.wait_for_timeout(500)
    check(u.is_hidden("#hero-actions") and u.locator("article .run-btn:visible").count() == 0, "일반 사용자: 카드 실행 버튼도 없음")
    b.close()
    check(not errors, f"페이지 오류 없음: {errors[:3]}")

print("\n실패:", fails if fails else "없음")
sys.exit(1 if fails else 0)
