# -*- coding: utf-8 -*-
"""지표 카드가 '건수'가 아니라 '경과 시간'을 보여주는지 확인.
   시험 서버(8766, DRY_RUN, 복사한 기록 폴더)를 직접 띄우고 끈다."""
import io, json, os, shutil, subprocess, sys, tempfile, time, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = "http://127.0.0.1:8766"
OUT = os.path.join(HERE, "shots")
os.makedirs(OUT, exist_ok=True)
fails = []
def check(cond, what):
    print(("PASS " if cond else "FAIL ") + what)
    if not cond:
        fails.append(what)

sim = tempfile.mkdtemp(prefix="rpa_ui_metric_")
shutil.copytree(os.path.join(HERE, "status_sim"), sim, dirs_exist_ok=True)

srv = subprocess.Popen([r"D:\AX\RPA\.venv\Scripts\python.exe", "rpa_dashboard.py",
                        "--port", "8766", "--host", "127.0.0.1", "--no-scheduler"],
                       cwd=r"D:\AX\RPA",
                       env=dict(os.environ, RPA_DASHBOARD_DRY_RUN="1", RPA_STATUS_DIR=sim),
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
for _ in range(50):
    try:
        urllib.request.urlopen(BASE + "/healthz", timeout=1); break
    except Exception:
        time.sleep(0.2)

try:
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1280, "height": 1000})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(BASE + "/#now"); pg.wait_for_selector("#login-view:not([hidden])")
        pg.fill("#login-code", "erpiatest2"); pg.fill("#login-id", "admin"); pg.fill("#login-pw", "admin")
        pg.click("#login-btn")
        pg.wait_for_selector("#programs .card")
        pg.wait_for_timeout(800)

        tiles = pg.query_selector_all(".tile")
        print(f"타일 {len(tiles)}개")
        seen = []
        for t in tiles:
            lab = t.query_selector(".tile-label")
            big = t.query_selector(".big")
            note = t.query_selector(".tile-note")
            unit = t.query_selector(".unit")
            label = lab.inner_text() if lab else ""
            bigt = big.inner_text() if big else ""
            notet = note.inner_text() if note else ""
            unitt = unit.inner_text() if unit else ""
            seen.append((label, bigt, unitt, notet))
            print(f"  [{label}] 값='{bigt}' 단위='{unitt}' 노트='{notet}'")

        metric_labels = {"상단 선택", "엑셀 업로드", "하단 선택", "재고검토 보류", "비정상 보류"}
        found = [s for s in seen if s[0] in metric_labels]
        check(len(found) >= 3, f"지표 타일 {len(found)}개 발견")
        import re
        dur_re = re.compile(r"(초|분|시간|–)")
        for label, bigt, unitt, notet in found:
            check(notet == "경과 시간", f"[{label}] 노트가 '경과 시간' (실제 '{notet}')")
            check(bool(dur_re.search(bigt)), f"[{label}] 값이 경과시간 형식 ('{bigt}')")
            check("건" not in unitt and "개" not in unitt, f"[{label}] 단위에 건/개 없음 ('{unitt}')")
        check(not errs, f"페이지 JS 오류 없음: {errs}")
        pg.screenshot(path=os.path.join(OUT, "metric_elapsed.png"), full_page=True)
        print("스크린샷:", os.path.join(OUT, "metric_elapsed.png"))
        b.close()
finally:
    srv.terminate()
    try:
        srv.wait(timeout=5)
    except Exception:
        srv.kill()
    shutil.rmtree(sim, ignore_errors=True)

print("\n실패:", fails if fails else "없음")
sys.exit(1 if fails else 0)
