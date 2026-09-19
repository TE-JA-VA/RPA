# -*- coding: utf-8 -*-
"""로그인 화면: '업체코드/아이디 저장' 체크박스 + 안내 문구 제거 확인.
   시험 서버(8766, DRY_RUN, 복사한 기록 폴더)를 직접 띄우고 끈다."""
import io, os, shutil, subprocess, sys, tempfile, time, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = "http://127.0.0.1:8766"
OUT = os.path.join(HERE, "shots"); os.makedirs(OUT, exist_ok=True)
fails = []
def check(cond, what):
    print(("PASS " if cond else "FAIL ") + what)
    if not cond: fails.append(what)

sim = tempfile.mkdtemp(prefix="rpa_ui_login_")
shutil.copytree(os.path.join(HERE, "status_sim"), sim, dirs_exist_ok=True)
srv = subprocess.Popen([r"D:\AX\RPA\.venv\Scripts\python.exe", "rpa_dashboard.py",
                        "--port", "8766", "--host", "127.0.0.1", "--no-scheduler"],
                       cwd=r"D:\AX\RPA",
                       env=dict(os.environ, RPA_DASHBOARD_DRY_RUN="1", RPA_STATUS_DIR=sim),
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
for _ in range(50):
    try: urllib.request.urlopen(BASE + "/healthz", timeout=1); break
    except Exception: time.sleep(0.2)

def show_login(pg):
    pg.goto(BASE + "/#now"); pg.wait_for_selector("#login-view:not([hidden])"); pg.wait_for_timeout(200)

def set_remember(pg, want):
    # 입력칸은 숨겨져 있으니 라벨을 눌러 토글한다.
    if pg.is_checked("#login-remember") != want:
        pg.click("label[for=login-remember]"); pg.wait_for_timeout(120)

try:
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 900, "height": 900})
        errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
        show_login(pg)

        # 1) 화면 구성
        check(pg.is_visible(".checkbox-wrapper-46 .cbx"), "'업체코드/아이디 저장' 체크박스 있음")
        check("업체코드/아이디 저장" in (pg.inner_text(".checkbox-wrapper-46") if pg.query_selector(".checkbox-wrapper-46") else ""), "체크박스 라벨 문구")
        # 버튼 위에 있는지 (DOM 순서상 remember가 login-actions 앞)
        order = pg.evaluate("""() => {
          const rem = document.getElementById('login-remember');
          const btn = document.getElementById('login-btn');
          return rem.compareDocumentPosition(btn) & Node.DOCUMENT_POSITION_FOLLOWING ? 'before' : 'after';
        }""")
        check(order == "before", f"체크박스가 로그인 버튼 위(앞)에 있음 ({order})")
        check(pg.query_selector(".login-foot") is None, "'관리자는 지금 실행~' 안내 문구 제거됨")
        check((pg.inner_text("#login-msg") or "").strip() == "", "안내 메시지(로그인 풀림 등) 비어 있음")
        check(pg.is_checked("#login-remember"), "기본값: 저장 체크됨")
        pg.screenshot(path=os.path.join(OUT, "login_screen.png"))

        # 2) 저장 체크 상태로 로그인 -> 쿠키 지우고 다시 오면 값이 채워지고 체크됨
        set_remember(pg, True)
        pg.fill("#login-code", "erpiatest2"); pg.fill("#login-id", "admin"); pg.fill("#login-pw", "admin")
        pg.click("#login-btn"); pg.wait_for_selector("#programs .card")
        code = pg.evaluate("() => localStorage.getItem('rpa.login.code')")
        rem = pg.evaluate("() => localStorage.getItem('rpa.login.remember')")
        check(code == "erpiatest2" and rem == "1", f"저장 체크시 code·remember 저장됨 (code={code}, remember={rem})")
        pg.context.clear_cookies(); show_login(pg)
        check(pg.input_value("#login-code") == "erpiatest2" and pg.input_value("#login-id") == "admin", "다시 오면 업체코드·아이디 채워짐")
        check(pg.is_checked("#login-remember"), "다시 오면 체크박스 유지")
        check((pg.inner_text("#login-msg") or "").strip() == "", "다시 로그인 화면에도 안내 메시지 없음")

        # 3) 저장 해제하고 로그인 -> 쿠키 지우고 다시 오면 값이 비고 체크 해제
        set_remember(pg, False)
        pg.fill("#login-pw", "admin"); pg.click("#login-btn"); pg.wait_for_selector("#programs .card")
        code2 = pg.evaluate("() => localStorage.getItem('rpa.login.code')")
        rem2 = pg.evaluate("() => localStorage.getItem('rpa.login.remember')")
        check(not code2 and rem2 == "0", f"해제시 code 지워지고 remember=0 (code={code2}, remember={rem2})")
        pg.context.clear_cookies(); show_login(pg)
        # 입력칸 값 자체는 브라우저 자동완성이 채울 수 있어 우리 계약(저장 안 함)의 기준으로 삼지 않는다.
        # 우리가 제어하는 것: localStorage 에 저장 안 됨 + 체크박스 꺼짐.
        stored = pg.evaluate("() => localStorage.getItem('rpa.login.code')")
        check(not stored, f"해제 후 우리 저장소에 업체코드 없음 (stored={stored})")
        check(not pg.is_checked("#login-remember"), "해제 후 체크박스 꺼짐")

        check(not errs, f"페이지 JS 오류 없음: {errs}")
        b.close()
finally:
    srv.terminate()
    try: srv.wait(timeout=5)
    except Exception: srv.kill()
    shutil.rmtree(sim, ignore_errors=True)

print("\n실패:", fails if fails else "없음")
sys.exit(1 if fails else 0)
