# -*- coding: utf-8 -*-
"""브라우저 시험 - 배포판처럼 같이 싣는 브라우저(ms-playwright) 없이 PC 에 깔린 Edge 로 뜨는가 (2026-10-06).

기록·재생 엔진(web_replay), 프리페어 자체 시험(web_runner), 옵저버 브라우저(rpa_observer)의 명령줄·프로필·--check,
Edge 가 없는 PC. 창은 뜨지 않는다 (옵저버 브라우저도 창만 숨겨 띄운다).
    .venv\\Scripts\\python.exe tests\\test_edge.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="rpa_edge_")
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.join(TMP, "no_browsers")   # 배포판처럼 - Edge 가 아닌 것을 띄우면 죽는다
os.environ["RPA_USER_CONFIG"] = os.path.join(TMP, "config", "RPA_UserConfig.json")
os.environ["RPA_PROGRAMDATA"] = os.path.join(TMP, "programdata")
os.environ["RPA_STATUS_DIR"] = os.path.join(TMP, "status")
os.environ["RPA_OBSERVER_LOCK"] = rf"Local\AFTER_MARKET_RPA_OBSERVER_EDGE_TEST_{os.getpid()}"   # 개발 PC 의 진짜 에이전트가 기다리지 않게
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

import rpa_observer as rr  # noqa: E402
import web_replay as rec  # noqa: E402

fails = []


def check(name, ok, detail=""):
    print(f"  [{'통과' if ok else '실패'}] {name}" + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


def attempt(fn):
    """(값, 오류 글). 예외도 그 항목의 실패로만 센다 - 한 항목이 죽어도 뒤 항목은 본다."""
    try:
        return fn(), ""
    except Exception as e:
        return None, f"{type(e).__name__}: {(str(e).splitlines() or [''])[0]}"


def run(args, **env):
    r = subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True, timeout=180,
                       env=dict(os.environ, PYTHONIOENCODING="utf-8", **env))
    return r.returncode, (r.stdout + r.stderr).decode("utf-8", "replace")


class Headless:
    """시험: 옵저버 launch 를 그대로 부르되 창만 띄우지 않는다 (Edge·명령줄·프로필은 진짜 그대로)."""

    def __init__(self, p):
        self.chromium, self._p = self, p

    def launch_persistent_context(self, *a, **k):
        return self._p.chromium.launch_persistent_context(*a, **dict(k, headless=True))


print("=== 1. 같이 싣는 브라우저 없이 ===")
made, err = attempt(lambda: rec.record("about:blank", os.path.join(TMP, "rec.json"), headless=True, human=lambda page: None))
check("기록 엔진이 깔린 Edge 로 뜬다", isinstance(made, dict) and "steps" in made, err)
got, err = attempt(lambda: rec.replay(made, {"ID": "", "PW": ""}, os.path.join(TMP, "dl"), "012"))
check("재생 엔진이 깔린 Edge 로 뜬다", bool(got) and got[0] is True, err or str(got))
code, out = run(["web_runner.py", "--selftest", "--headless"])
check("프리페어 자체 시험 (내장 로그인 폼)이 깔린 Edge 로 돈다", code == 0 and "자체 테스트 통과" in out, out[-400:])

print("=== 2. 옵저버 브라우저 ===")


def observer_browser():
    with rec.sync_playwright() as p:
        ctx, prof = rr.launch(Headless(p))
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto("about:blank")
            webdriver = page.evaluate("navigator.webdriver")
            page.goto("edge://version")
            about = page.inner_text("body")
        finally:
            ctx.close()
    with open(os.path.join(prof, "Default", "Preferences"), encoding="utf-8") as f:
        prefs = json.load(f)
    shutil.rmtree(prof, ignore_errors=True)
    return about, prefs, webdriver


got, err = attempt(observer_browser)
about, prefs, webdriver = got or ("", {}, None)
check("옵저버 브라우저는 깔린 Edge 이고, 경고 띠를 띄우는 명령줄(--no-sandbox·--enable-automation)이 없다",
      "Microsoft Edge" in about and "--no-sandbox" not in about and "--enable-automation" not in about,
      err or about[:600])
check("옵저버 브라우저는 사이트에 자동 조종 브라우저라고 알리지 않는다 (navigator.webdriver - 2026-10-12 봇을 막는 사이트가 막았다), "
      "그 옵션이 띄우는 '지원되지 않는 명령줄 플래그' 띠는 --test-type 으로 끈다",
      webdriver is False and "--test-type" in about, err or f"webdriver={webdriver}")
check("옵저버 프로필은 파일을 받을 때 Edge 다운로드 창을 띄우지 않는다 (기록 중 화면을 가린다)",
      prefs.get("browser", {}).get("show_hub_popup_on_download_start") is False, err or str(prefs.get("browser")))
code, out = run(["rpa_observer.py", "--check"])
check("옵저버 --check 가 Edge 를 띄워 판을 찍는다 (샌드박스가 이 줄을 본다)",
      bool(re.search(r"브라우저: Microsoft Edge \d+\.", out)) and rr.CHECK_DONE in out, out[-400:])

print("=== 3. 브라우저 자체 페이지는 사이트가 연 창이 아니다 (옵저버 기록기) ===")


def browser_pages():
    with rec.sync_playwright() as p:
        b = rec.edge(p.chromium.launch, headless=True)
        try:
            ctx = b.new_context(accept_downloads=True)
            r = rr.LiveRecorder(ctx, None, lambda steps: None)
            page = ctx.new_page()
            page.goto("about:blank")
            r.steps.append({"kind": "click", "page": 0})      # 사람이 방금 '엑셀 받기' 를 눌렀다 치고
            with page.expect_download():
                page.evaluate("() => { const a = document.createElement('a'); a.href = 'data:text/csv,a,b';"
                              " a.download = 'x.csv'; document.body.append(a); a.click(); }")
            page.wait_for_timeout(1500)                        # Edge 는 다운로드 창(edge://downloads-hub)을 페이지로 연다
            after_download = dict(r.steps[0]), [pg.url for pg in ctx.pages]
            tab = ctx.new_page()                               # 주소 없이 생겼다가 새 탭 주소가 붙는 탭
            tab.goto("edge://newtab")
            page.wait_for_timeout(500)
            return after_download, [dict(s) for s in r.steps]
        finally:
            b.close()


got, err = attempt(browser_pages)
(click, urls), steps = got or (({}, []), [{}])
check("파일을 받을 때 Edge 가 여는 다운로드 창은 앞 동작이 연 새 창으로 적지 않는다 (재생이 오지 않을 창을 기다렸다)",
      "edge://downloads-hub/" in urls and "opens" not in click, err or f"{click} {urls}")
check("주소 없이 생겼다가 새 탭 주소가 붙은 탭은 '새 탭' 단계로 (앞 동작이 연 창이 아니다)",
      steps[-1].get("kind") == "newtab" and steps[-1].get("page") == 2 and "opens" not in steps[0], err or str(steps))

NTP = "https://ntp.msn.com/edge/ntp?locale=ko&title=%EC%83%88%20%ED%83%AD&dsp=1&sp=Bing"   # 사람이 Ctrl+T·+ 로 연 Edge 새 탭 (2026-10-06 실측)


class HumanTab:
    """사람이 연 Edge 새 탭 흉내 - opener 없고, 생기는 순간 (또는 나중에 framenavigated 로) MSN 새 탭 주소. 진짜 탭은 [+ 새 탭] 을
    UIA 로 눌러 확인했다. 그 주소를 route 로 흉내 낸 진짜 탭은 headless Edge 를 가끔 통째로 끊어 (2026-10-06) 주소·이벤트만 흉내 낸다."""

    def __init__(self, url):
        self.url, self.main_frame, self.handlers = url, self, {}

    def opener(self):
        return None

    def on(self, name, fn):
        self.handlers.setdefault(name, []).append(fn)

    def remove_listener(self, name, fn):
        self.handlers[name].remove(fn)

    def navigate(self, url):
        self.url = url
        for fn in list(self.handlers.get("framenavigated", [])):
            fn(self)


def msn_new_tabs():
    with rec.sync_playwright() as p:
        b = rec.edge(p.chromium.launch, headless=True)
        try:
            ctx = b.new_context()
            r = rr.LiveRecorder(ctx, None, lambda steps: None)
            ctx.new_page()                                     # 첫 탭 (0)
            r.steps.append({"kind": "click", "page": 0})
            r._page(HumanTab(NTP))                             # 생기는 순간 MSN 새 탭 주소
            at_once = [dict(s) for s in r.steps]
            r.steps.append({"kind": "click", "page": 0})
            tab = HumanTab("")                                 # 주소 없이 생겼다가
            r._page(tab)
            tab.navigate(NTP)                                  # MSN 새 탭 주소가 붙는다
            return at_once, [dict(s) for s in r.steps[len(at_once):]]
        finally:
            b.close()


got, err = attempt(msn_new_tabs)
at_once, late = got or ([{}], [{}])
check("사람이 연 Edge 새 탭 (MSN 새 탭 주소로 바로 생김) 은 '새 탭' 단계로, 앞 동작이 연 창이 아니다 (재생이 오지 않을 창을 기다린다)",
      [s.get("kind") for s in at_once] == ["click", "newtab"] and "opens" not in at_once[0], err or str(at_once))
check("주소 없이 생겼다가 MSN 새 탭 주소가 붙은 탭도 '새 탭' 단계로",
      [s.get("kind") for s in late] == ["click", "newtab"] and "opens" not in late[0], err or str(late))

print("=== 4. Alt+Tab 에 탭을 올리지 않는다 (2026-11-03 다른 PC 에 '메일' 빈 항목 수십 개) ===")


def disabled_features():
    import http.server
    import threading

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"<p>x")

        def log_message(self, *a):
            pass
    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with rec.sync_playwright() as p:
            b = rec.edge(p.chromium.launch, headless=True, args=["--disable-features=WebShare"])   # 함께 실행이 넘기는 것처럼
            try:
                page = b.new_page()
                page.goto(f"http://127.0.0.1:{srv.server_port}/")          # navigator.share 는 안전한 주소에서만 있다
                share = page.evaluate("'share' in navigator")
                page.goto("edge://version")
                return page.inner_text("body"), share
            finally:
                b.close()
    finally:
        srv.shutdown()


pw = rec._playwright_disabled()
check("Playwright 가 넘기는 --disable-features 목록을 읽는다 (Playwright 를 올려 못 읽으면 Alt+Tab 을 못 끈다)",
      bool(pw) and "PaintHolding" in pw, str(pw))
got, err = attempt(disabled_features)
about, share = got or ("", None)
line = re.findall(r"--disable-features=(\S+)", about)
feats = line[-1].split(",") if line else []
check("Edge 명령줄의 마지막 --disable-features 에 Playwright 것·넘겨받은 것·Alt+Tab 기능이 모두 있다 (마지막 하나만 먹는다)",
      rec.NO_ALT_TAB in feats and "WebShare" in feats and set(pw or ["?"]) <= set(feats), err or str(line))
check("넘겨받은 기능도 실제로 꺼진다 (navigator.share 없음)", share is False, err or f"share={share}")

print("=== 5. Edge 가 없는 PC ===")
EDGE_GONE = r"""
import os, sys, tempfile
sys.path.insert(0, os.getcwd())
import web_replay
try:
    web_replay.record("about:blank", os.path.join(tempfile.gettempdir(), "edge_gone.json"), headless=True, human=lambda page: None)
    print("떴다")
except RuntimeError as e:
    print(e)
"""
nowhere = os.path.join(TMP, "nowhere")    # Playwright 는 이 아래 Microsoft\Edge\Application\msedge.exe 를 찾는다 (HOMEDRIVE 는
os.makedirs(nowhere)                      # 그 아래 Program Files 두 곳)
code, out = run(["-c", EDGE_GONE], LOCALAPPDATA=nowhere, PROGRAMFILES=nowhere, HOMEDRIVE=nowhere,
                **{"PROGRAMFILES(X86)": nowhere})
check("Edge 가 없으면 'Microsoft Edge 가 없습니다' 로 멈춘다 (playwright install 같은 개발자 말 대신)",
      "Microsoft Edge가 설치되어 있지 않습니다" in out and "playwright install" not in out, out[-400:])

shutil.rmtree(TMP, ignore_errors=True)
print()
print(f"실패: {'없음' if not fails else fails}")
sys.exit(1 if fails else 0)
