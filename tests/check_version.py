# -*- coding: utf-8 -*-
"""화면 판 번호 띠와 '로그인 풀림' 안내 시험 (8766 시험 서버)."""
import io
import os
import subprocess
import sys
import time
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from playwright.sync_api import sync_playwright  # noqa: E402

BASE = "http://127.0.0.1:8766"
HTML = r"D:\AX\RPA\dashboard.html"
fails = []


def check(cond, what):
    print(("PASS " if cond else "FAIL ") + what)
    if not cond:
        fails.append(what)


with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1280, "height": 900})
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(BASE + "/#now"); pg.wait_for_selector("#login-view:not([hidden])")
    ver = pg.get_attribute('meta[name="page-version"]', "content")
    check(len(ver or "") == 12, f"판 번호 심어짐: {ver}")
    pg.fill("#login-code", "erpiatest2"); pg.fill("#login-id", "user"); pg.fill("#login-pw", "user"); pg.click("#login-btn")
    pg.wait_for_selector("#programs .card"); pg.wait_for_timeout(2500)
    check(pg.is_hidden("#update-banner"), "같은 판이면 띠 없음")
    # 파일 수정 시각만 바꾸면 내용 해시는 같다 → 띠 없음. 내용을 바꾸면 띠가 뜬다.
    os.utime(HTML, None); pg.wait_for_timeout(2600)
    check(pg.is_hidden("#update-banner"), "수정 시각만 바뀌면 띠 없음")
    raw = open(HTML, "rb").read()
    open(HTML, "wb").write(raw + b"\n<!-- v -->\n")
    try:
        pg.wait_for_selector("#update-banner:not([hidden])", timeout=6000)
        check(True, "내용이 바뀌면 '새로고침' 띠")
        pg.click("#update-banner button"); pg.wait_for_selector("#programs .card"); pg.wait_for_timeout(2500)
        check(pg.is_hidden("#update-banner"), "새로고침 뒤 띠 사라짐 (로그인 유지)")
    finally:
        open(HTML, "wb").write(raw)
    # 서버 재시작 → 로그인 풀림 안내
    pid = subprocess.run(["powershell", "-NoProfile", "-Command",
                          "(Get-NetTCPConnection -LocalPort 8766 -State Listen).OwningProcess"], capture_output=True, text=True).stdout.strip()
    subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True)
    srv = subprocess.Popen([r"D:\AX\RPA\.venv\Scripts\python.exe", "rpa_dashboard.py", "--port", "8766", "--host", "127.0.0.1", "--no-scheduler"],
                           cwd=r"D:\AX\RPA", env=dict(os.environ, RPA_DASHBOARD_DRY_RUN="1",
                                                       RPA_STATUS_DIR=os.path.join(os.path.dirname(os.path.abspath(__file__)), "status_sim")),
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(30):
        try:
            urllib.request.urlopen(BASE + "/healthz", timeout=1); break
        except Exception:
            time.sleep(0.3)
    pg.wait_for_selector("#login-view:not([hidden])", timeout=15000)
    msg = pg.inner_text("#login-msg")
    check("로그인이 풀렸습니다" in msg, f"재시작 뒤 안내: {msg!r}")
    pg.fill("#login-pw", "user"); pg.click("#login-btn"); pg.wait_for_selector("#programs .card", timeout=8000)
    check(pg.is_hidden("#login-view") and pg.is_enabled("#tab-history"), "다시 로그인하면 정상")
    srv.terminate()
    b.close()
    check(not errs, f"페이지 오류 없음: {errs[:3]}")

print("\n실패:", fails if fails else "없음")
sys.exit(1 if fails else 0)
