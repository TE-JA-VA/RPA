# -*- coding: utf-8 -*-
"""쇼핑몰 아이디·비밀번호는 기록한 사이트의 https 화면에만 넣는다 (보안 진단 2026-11-23 D-1·C10).
실행 중 끼어든 다른 도메인 창·광고 틀로 단계가 옮겨 가도, 넣기 직전에 그 칸이 있는 문서의 주소를 본다.
    .venv\\Scripts\\python.exe tests\\test_cred_site.py
"""
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from playwright.sync_api import sync_playwright  # noqa: E402

import web_replay as rec  # noqa: E402

fails = []


def check(name, ok, detail=""):
    print(f"  [{'통과' if ok else '실패'}] {name}" + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


PORT = [0]


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/frame"):      # 다른 사이트(localhost)의 로그인 틀을 품은 화면
            body = f'<html><body><iframe id="f" src="http://localhost:{PORT[0]}/login"></iframe></body></html>'
        else:
            body = '<html><body><input id="id"><input id="pw" type="password"></body></html>'
        b = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(b)


def main():
    ok = rec.cred_site_ok
    print("주소 판정 (브라우저 없이)")
    check("S1 같은 사이트 https 는 넣는다", ok("https://shop.example.co.kr/login", "shop.example.co.kr", False)
          and ok("https://login.example.co.kr/x", "shop.example.co.kr", False))
    check("S2 다른 사이트는 안 넣는다", not ok("https://shop.example.co.kr.evil.invalid/login", "shop.example.co.kr", False)
          and not ok("https://evil.invalid/member/login", "shop.example.co.kr", False))
    check("S3 http 는 기록도 http 였을 때만", not ok("http://shop.example.co.kr/login", "shop.example.co.kr", False)
          and ok("http://shop.example.co.kr/login", "shop.example.co.kr", True))
    check("S4 기록에 사이트가 없는 옛 기록은 막지 않는다", ok("https://a.b/x", "", False))
    check("S5 about:blank·data: 같은 문서에는 안 넣는다", not ok("about:blank", "shop.example.co.kr", False)
          and not ok("data:text/html,x", "shop.example.co.kr", False))

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    PORT[0] = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    here, other = f"http://127.0.0.1:{PORT[0]}", f"http://localhost:{PORT[0]}"
    steps = [{"kind": "fill", "credential": "ID", "page": 0, "target": {"text": ""}},
             {"kind": "secret", "host": "127.0.0.1", "page": 0, "target": {"text": ""}}]
    print("넣기 직전 검사 (가짜 화면)")
    with sync_playwright() as p:
        b = rec.edge(p.chromium.launch, headless=True)
        ctx = b.new_context()
        page = ctx.new_page()
        r = rec.Replayer(ctx, {"steps": steps}, {"ID": "shopuser", "PW": "S3cret!x"}, tempfile.gettempdir(), "000", log=lambda m: None)
        r.pages = {0: page}

        def try_act(url, sel, s, frame=False):
            page.goto(url)
            root = page.frame_locator("#f") if frame else page
            loc = root.locator(sel)
            try:
                r._act(page, loc, s)
                err = None
            except rec.SiteFail as e:
                err = str(e)
            return err, loc.input_value()

        err, val = try_act(here + "/login", "#pw", steps[1])
        check("P1 기록한 사이트면 비밀번호를 넣는다", err is None and val == "S3cret!x", (err, val))
        err, val = try_act(other + "/login", "#pw", steps[1])
        check("P2 다른 사이트 창이면 비밀번호를 넣지 않고 멈춘다", err and "기록" in err and val == "", (err, val))
        err, val = try_act(here + "/frame", "#pw", steps[1], frame=True)
        check("P3 기록한 사이트 화면 안의 다른 사이트 틀에도 넣지 않는다", err is not None and val == "", (err, val))
        err, val = try_act(other + "/login", "#id", steps[0])
        check("P4 아이디도 비밀번호 단계의 사이트가 아니면 넣지 않는다", err is not None and val == "", (err, val))
        err, val = try_act(here + "/login", "#id", steps[0])
        check("P5 아이디는 비밀번호 단계의 사이트면 넣는다", err is None and val == "shopuser", (err, val))
        check("P6 실패 글에 비밀번호·아이디가 없다", "S3cret" not in str(err) and "shopuser" not in str(err))
        two = [{"kind": "secret", "host": "localhost", "page": 0, "target": {"text": ""}}] + steps     # 앞 사이트 로그인 + 뒤 사이트 로그인
        r.rec = {"steps": two}
        err, val = try_act(here + "/login", "#id", two[1])
        check("P7 두 사이트에 로그인하는 기록은 아이디를 그 뒤 비밀번호 단계의 사이트와 견준다", err is None and val == "shopuser", (err, val))
        b.close()
    srv.shutdown()
    print("\n실패:", fails if fails else "없음")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
