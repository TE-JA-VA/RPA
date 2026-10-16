"""옵저버: 주소줄에 친(붙여넣은) 주소가 단계로 기록되는가 - 열리자마자 다른 주소로 넘어가는 링크도 (2026-10-16 사용자).

사람이 주소줄에 치는 것은 CDP Page.navigate(transitionType=typed) 로 흉내 낸다 (브라우저가 시작하는 이동이라 같다).
"""
import http.server
import os
import shutil
import sys
import tempfile
import threading

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import rpa_observer as obs   # noqa: E402
import web_replay as rec     # noqa: E402

PAGES = {
    "/plain": "<a id=a href='/dest'>link</a><form id=f action='/dest'><input name=x></form>"
              "<button id=b onclick=\"location.href='/dest'\">b</button>"
              "<a id=pop href='/dest' target=_blank>pop</a>",
    "/replace": "<script>location.replace('/dest')</script>",
    "/assign": "<script>location.href='/dest'</script>",
    "/meta": "<meta http-equiv=refresh content='0;url=/dest'>",
    "/dest": "<p>dest</p>",
}
LONG = "?q=" + "x" * 3000
fails = []


def check(name, ok, detail=""):
    print(("통과 " if ok else "실패 ") + name + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/302":
            self.send_response(302)
            self.send_header("Location", "/dest")
            self.end_headers()
            return
        body = PAGES.get(path, "<p>?</p>").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_port}"

with rec.sync_playwright() as p:
    prof = tempfile.mkdtemp(prefix="typednav_")
    ctx = rec.edge(p.chromium.launch_persistent_context, prof, headless=True)
    try:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        r = obs.LiveRecorder(ctx, None, lambda steps: None)
        r._page(page)
        cdp = ctx.new_cdp_session(page)

        def did(fn):
            n = len(r.steps)
            fn()
            page.wait_for_timeout(1200)
            return [(s["kind"], s.get("href", "")[len(base):]) for s in r.steps[n:] if s["kind"] in ("goto", "back")]

        def typed(path):
            return lambda: cdp.send("Page.navigate", {"url": base + path, "transitionType": "typed"})

        got = did(typed("/plain"))
        check("짧은 주소를 치면 '이동' 단계", got == [("goto", "/plain")], got)
        got = did(typed("/plain" + LONG))
        check("3000자 긴 주소도 끝까지", got == [("goto", "/plain" + LONG)], str(got)[:80])
        got = did(typed("/replace"))
        check("열리자마자 스크립트로 넘어가는 주소 (replace) 는 친 주소로", got == [("goto", "/replace")], got)
        got = did(typed("/assign" + LONG))
        check("긴 주소 + 스크립트로 넘어감 (href) 도 친 주소로", got == [("goto", "/assign" + LONG)], str(got)[:80])
        got = did(typed("/meta"))
        check("새로고침 태그로 넘어가는 주소도 친 주소 하나만", got == [("goto", "/meta")], got)
        got = did(typed("/302"))
        check("서버가 넘기는 주소는 친 주소 하나만", got == [("goto", "/302")], got)
        did(typed("/plain"))
        got = did(lambda: page.click("#a"))
        check("링크를 누른 이동은 '이동' 단계가 아니다", got == [], got)
        did(typed("/plain"))
        got = did(lambda: page.evaluate("document.getElementById('f').submit()"))
        check("폼 보내기도 아니다", got == [], got)
        did(typed("/plain"))
        got = did(lambda: page.click("#b"))
        check("단추가 스크립트로 옮긴 것도 아니다", got == [], got)
        got = did(lambda: cdp.send("Page.reload"))
        check("새로고침은 아니다", got == [], got)
        got = did(lambda: page.go_back())
        check("뒤로 가기는 '뒤로' 단계", [k for k, _ in got] == ["back"], got)
        did(typed("/plain"))
        n = len(r.steps)
        with ctx.expect_page() as pop:
            page.click("#pop")
        pop.value.wait_for_load_state()
        page.wait_for_timeout(800)
        got = [s for s in r.steps[n:] if s["kind"] == "goto"]
        check("링크가 연 새 창의 첫 이동은 '이동' 단계가 아니다", got == [], got)
    finally:
        ctx.close()
        shutil.rmtree(prof, ignore_errors=True)
srv.shutdown()

print(f"실패: {len(fails)}" if fails else "모두 통과")
sys.exit(1 if fails else 0)
