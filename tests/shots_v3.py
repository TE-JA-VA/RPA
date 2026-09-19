# -*- coding: utf-8 -*-
"""로그인/권한/지금 실행/강조색 화면 시험. 서버는 RPA_DASHBOARD_DRY_RUN=1 --no-scheduler 로 떠 있어야 한다.
ERPia 종료는 확인창에서 취소한다. 비밀번호는 바꿨다가 되돌린다."""
import io
import json
import os
import sys
import urllib.request

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


def http(path, data=None, headers=None):
    req = urllib.request.Request(BASE + path, data=data, headers=headers or {}, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            body = r.read().decode("utf-8")
            try:
                return r.status, json.loads(body or "{}")
            except ValueError:
                return r.status, {"text": body}
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8") or "{}")
        except Exception:
            return e.code, {}


# 로그인 없이는 API 가 막힌다
check(http("/api/status")[0] == 401, "로그인 없이 /api/status → 401")
check(http("/api/history")[0] == 401, "로그인 없이 /api/history → 401")
check(http("/api/run", b"{}", {"Content-Type": "application/json", "X-RPA-Action": "1"})[0] == 401, "로그인 없이 /api/run → 401")
check(http("/api/login", b'{"admin_code":"x","user_id":"admin","password":"admin"}', {"Content-Type": "application/json"})[0] == 403, "머리글 없는 로그인 → 403")
check(http("/healthz")[0] == 200, "/healthz 는 열려 있음")


def login(pg, code, uid, pw):
    pg.fill("#login-code", code); pg.fill("#login-id", uid); pg.fill("#login-pw", pw)
    pg.click("#login-btn")


with sync_playwright() as p:
    b = p.chromium.launch()
    errors = []
    dialogs = []

    def new_page(w, h_):
        ctx = b.new_context(viewport={"width": w, "height": h_})
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.on("console", lambda m: errors.append(m.text) if m.type == "error" and "401" not in m.text else None)
        return pg

    # --- 로그인 화면 ---
    pg = new_page(1280, 900)
    pg.goto(BASE + "/"); pg.wait_for_selector("#login-view:not([hidden])"); pg.wait_for_timeout(300)
    check(pg.is_hidden("main") or not pg.is_visible("#programs"), "로그인 전에는 본문이 안 보임")
    pg.click("#theme-btn"); pg.wait_for_timeout(150)
    if pg.evaluate("document.documentElement.getAttribute('data-theme')") != "dark":
        pg.click("#theme-btn"); pg.wait_for_timeout(150)
    pg.screenshot(path=os.path.join(OUT, "v3_login_dark.png"))
    login(pg, "erpiatest2", "admin", "wrong"); pg.wait_for_selector("#login-msg:has-text('맞지 않습니다')", timeout=5000)
    check(True, "틀린 비밀번호 안내")
    check(pg.is_visible("#login-view"), "틀리면 로그인 화면 유지")

    # --- 일반 사용자 ---
    login(pg, "erpiatest2", "user", "user"); pg.wait_for_selector("#programs .card", timeout=5000); pg.wait_for_timeout(600)
    conn = pg.inner_text("#conn")
    check("erpiatest2 · user" in conn and "일반 사용자" in conn, f"헤더 계정/역할: {conn!r}")
    check(pg.is_hidden("#hero-actions"), "일반 사용자: 지금 실행 버튼 없음")
    pg.goto(BASE + "/#settings"); pg.wait_for_selector("#account-info b"); pg.wait_for_timeout(400)
    check(pg.is_disabled("#set-enabled") and pg.is_disabled("#set-days button"), "일반 사용자: 자동 실행 읽기 전용")
    check(pg.is_hidden("#set-actions") and pg.is_hidden("#erpia-stop-field"), "일반 사용자: 적용/ERPia 종료 없음")
    check(pg.is_visible("#set-readonly"), "일반 사용자: 관리자만 안내")
    check(pg.is_visible("#logout-btn"), "일반 사용자: 로그아웃 버튼")
    pg.screenshot(path=os.path.join(OUT, "v3_settings_user_dark.png"), full_page=True)
    # 서버 쪽에서도 막히는지 (쿠키는 브라우저 컨텍스트에서 가져온다)
    ck = {c["name"]: c["value"] for c in pg.context.cookies()}
    hdr = {"Content-Type": "application/json", "X-RPA-Action": "1", "Cookie": f"rpa_session={ck.get('rpa_session', '')}"}
    check(http("/api/run", b"{}", hdr)[0] == 403, "일반 사용자 /api/run → 403")
    check(http("/api/settings", b'{"schedule":{"enabled":true,"days":[0],"times":["09:00"]}}', hdr)[0] == 403, "일반 사용자 /api/settings → 403")
    check(http("/api/erpia/stop", b"{}", hdr)[0] == 403, "일반 사용자 /api/erpia/stop → 403")
    # 비밀번호 변경 후 되돌리기
    pg.fill("#pw-cur", "user"); pg.fill("#pw-new", "temp1234"); pg.fill("#pw-new2", "temp1234"); pg.click("#pw-btn")
    pg.wait_for_selector("#pw-msg:has-text('바꿨습니다')", timeout=5000); check(True, "비밀번호 변경")
    pg.fill("#pw-cur", "temp1234"); pg.fill("#pw-new", "user"); pg.fill("#pw-new2", "user"); pg.click("#pw-btn")
    pg.wait_for_selector("#pw-msg:has-text('바꿨습니다')", timeout=5000); check(True, "비밀번호 되돌림")
    pg.fill("#pw-cur", "user"); pg.fill("#pw-new", "abcd"); pg.fill("#pw-new2", "abce"); pg.click("#pw-btn")
    pg.wait_for_selector("#pw-msg:has-text('서로 다릅니다')", timeout=3000); check(True, "두 칸 불일치 안내")
    pg.click("#logout-btn"); pg.wait_for_selector("#login-view:not([hidden])", timeout=5000)
    check(pg.is_visible("#login-view"), "로그아웃 → 로그인 화면")
    check(http("/api/status", headers={"Cookie": hdr["Cookie"]})[0] == 401, "로그아웃 뒤 옛 쿠키 무효")

    # --- 관리자 ---
    pg.goto(BASE + "/#now"); pg.wait_for_selector("#login-view:not([hidden])")
    login(pg, "erpiatest2", "admin", "admin"); pg.wait_for_selector("#programs .card", timeout=5000); pg.wait_for_timeout(600)
    conn = pg.inner_text("#conn")
    check("erpiatest2 · admin" in conn and "관리자" in conn, f"관리자 헤더: {conn!r}")
    check(pg.is_visible("#run-all") and pg.is_enabled("#run-all"), "관리자: 지금 실행 버튼")
    pg.screenshot(path=os.path.join(OUT, "v3_now_admin_dark.png"), full_page=True)
    pg.once("dialog", lambda d_: (dialogs.append(d_.message), d_.accept()))
    pg.click("#run-all"); pg.wait_for_selector("#run-msg:has-text('띄웠습니다')", timeout=5000)
    check(any("지금 실행" in m for m in dialogs), "지금 실행 확인창")
    pg.wait_for_timeout(2500)
    nxt = pg.inner_text("#hero-next")
    check("마지막 실행" in nxt and "수동 (admin)" in nxt, f"마지막 실행 표시: {nxt!r}")

    # 강조색
    pg.goto(BASE + "/#settings"); pg.wait_for_selector("#account-info b"); pg.wait_for_timeout(400)
    check(pg.is_enabled("#set-enabled") and pg.is_visible("#set-actions") and pg.is_visible("#erpia-stop-field"), "관리자: 설정 편집 가능")
    check(pg.is_visible("#pw-default"), "기본 비밀번호 경고")
    pg.click(".swatch[data-k='magenta']"); pg.wait_for_timeout(200)
    acc = pg.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--accent').trim()")
    check(acc == "#d33682" and pg.evaluate("localStorage.getItem('rpa.accent')") == "magenta", f"강조색 자홍 적용: {acc}")
    btnbg = pg.evaluate("getComputedStyle(document.querySelector('#set-refresh')).backgroundColor")
    pg.click("#theme-btn"); pg.wait_for_timeout(200)
    pg.screenshot(path=os.path.join(OUT, "v3_settings_admin_light_magenta.png"), full_page=True)
    pg.goto(BASE + "/#now"); pg.wait_for_selector("#programs .card"); pg.wait_for_timeout(600)
    pg.screenshot(path=os.path.join(OUT, "v3_now_admin_light_magenta.png"), full_page=True)
    pg.click("#theme-btn"); pg.wait_for_timeout(100)
    pg.goto(BASE + "/#settings"); pg.wait_for_selector("#account-info b"); pg.wait_for_timeout(300)
    pg.click(".swatch[data-k='cyan']"); pg.wait_for_timeout(200)
    pg.screenshot(path=os.path.join(OUT, "v3_settings_admin_dark_cyan.png"), full_page=True)
    pg.click(".swatch[data-k='blue']"); pg.wait_for_timeout(100)

    # ERPia 종료: 확인창 취소
    if pg.is_enabled("#erpia-stop-btn"):
        pg.once("dialog", lambda d_: (dialogs.append(d_.message), d_.dismiss()))
        pg.click("#erpia-stop-btn"); pg.wait_for_timeout(400)
        check(any("ERPia 를 종료" in m for m in dialogs), "ERPia 종료 확인창(취소)")

    # 새로고침 뒤에도 로그인 유지 (쿠키)
    pg.goto(BASE + "/#now"); pg.reload(); pg.wait_for_selector("#programs .card", timeout=5000)
    check(pg.is_hidden("#login-view"), "새로고침 뒤 로그인 유지")

    # 휴대폰 폭
    m = new_page(400, 820)
    m.goto(BASE + "/"); m.wait_for_selector("#login-view:not([hidden])"); m.wait_for_timeout(300)
    m.screenshot(path=os.path.join(OUT, "v3_m_login.png"))
    login(m, "erpiatest2", "admin", "admin"); m.wait_for_selector("#programs .card", timeout=5000); m.wait_for_timeout(600)
    check(m.evaluate("document.documentElement.scrollWidth <= 400"), "휴대폰: 가로 스크롤 없음 (현황)")
    m.screenshot(path=os.path.join(OUT, "v3_m_now_admin.png"), clip={"x": 0, "y": 0, "width": 400, "height": 820})
    m.goto(BASE + "/#settings"); m.wait_for_selector("#account-info b"); m.wait_for_timeout(400)
    check(m.evaluate("document.documentElement.scrollWidth <= 400"), "휴대폰: 가로 스크롤 없음 (설정)")
    m.screenshot(path=os.path.join(OUT, "v3_m_settings_admin.png"), full_page=True)

    b.close()
    check(not errors, f"페이지 오류 없음: {errors[:3]}")

print("\n실패:", fails if fails else "없음")
sys.exit(1 if fails else 0)
