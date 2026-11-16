# -*- coding: utf-8 -*-
"""기록 때 id 가 있던 대상을 오늘 id 로 못 찾고 글자로만 찾았는데, 그 단추가 위험 낱말(신청·동의…)이 든 레이어 안에 있으면 누르지 않는다
(사용자 승인 2026-11-16 - 신청 레이어의 [확인] 을 원래 [확인] 대신 눌러 '성공' 으로 보고하던 것). 창은 뜨지 않는다 (headless).
    .venv\\Scripts\\python.exe tests\\test_risky_layer.py
"""
import datetime
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from playwright.sync_api import sync_playwright  # noqa: E402

import web_replay as rec  # noqa: E402

fails, MODE, HITS = [], {}, []
HIT_JS = "function hit(x){var r=new XMLHttpRequest();r.open('GET','/hit?x='+x,false);r.send();}"


def check(name, ok, detail=""):
    print(f"  [{'통과' if ok else '실패'}] {name}" + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


def page():
    m = MODE
    ok = f'<button id="{m["id"]}" onclick="hit(\'ok\')">확인</button>' if m["id"] else '<button onclick="hit(\'ok\')">확인</button>'
    if m["layer"]:      # 레이어가 떠 있는 동안 원래 [확인] 은 화면에 없다
        ok = (f'<div role="dialog" style="position:fixed;top:20px;left:20px;width:600px;background:#fff">{m["layer"]}'
              f'<br><button onclick="hit(\'layer\')">확인</button></div>')
    return f"<html><head><script>{HIT_JS}</script></head><body><h2>요청 완료</h2>{ok}</body></html>"


class Shop(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        path, _, q = self.path.partition("?")
        if path == "/hit":
            HITS.append(q.split("=", 1)[1])
        body = page().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)


def set_mode(**kw):
    MODE.clear()
    MODE.update({"id": "ok", "layer": ""}, **kw)
    HITS.clear()


def record(url, layer_button=False):
    with sync_playwright() as p:
        b = rec.edge(p.chromium.launch, headless=True)
        ctx = b.new_context()
        rr = rec.Recorder(ctx)
        pg = ctx.new_page()
        pg.goto(url)
        pg.wait_for_timeout(300)
        loc = pg.get_by_role("button", name="확인")
        loc.wait_for(state="visible")
        bb = loc.bounding_box()
        pg.mouse.click(bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2)
        pg.wait_for_timeout(400)
        out = rec.finalize([dict(s) for s in rr.steps], datetime.date(2026, 11, 16), url)
        b.close()
    return out


def replay(record_obj):
    logs = []
    with sync_playwright() as p:
        b = rec.edge(p.chromium.launch, headless=True)
        ctx = b.new_context()
        r = rec.Replayer(ctx, record_obj, {}, tempfile.mkdtemp(prefix="rpa_risky_"), "000", log=logs.append,
                         step_timeout=2, step_tries=1)
        ok = r.run()
        b.close()
    fail = next((x[2] for x in r.results if x[1] == "fail"), "")
    return ok, fail, logs


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Shop)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/done"
    try:
        set_mode()
        recd = record(url)
        t = next(s for s in recd["steps"] if s["kind"] == "click")["target"]
        check("기록: [확인] 을 id 와 함께 적는다", t.get("id") == "ok" and t["text"] == "확인", t)

        set_mode(layer="부가 서비스를 신청하시겠습니까?")
        ok, fail, logs = replay(recd)
        check("신청 레이어의 [확인] 은 원래 [확인] 대신 누르지 않는다", not ok and "layer" not in HITS, (ok, HITS, fail))
        check("실패 사유에 까닭이 남는다", "'신청'" in fail, fail)

        set_mode(layer="개인정보 수집·이용에 동의하십니까?")
        ok, fail, logs = replay(recd)
        check("동의 레이어도 같다", not ok and "layer" not in HITS, (ok, HITS, fail))

        set_mode(layer="공지사항 - 11월 20일 점검 안내")
        ok, fail, logs = replay(recd)
        check("위험 낱말이 없는 안내 레이어의 [확인] 은 지금처럼 글자로 찾아 누른다", ok and HITS == ["layer"], (ok, HITS, fail))

        set_mode()
        ok, fail, logs = replay(recd)
        check("원래 [확인] 이 있으면 지금처럼 누른다", ok and HITS == ["ok"], (ok, HITS, fail))

        set_mode(id="wq_uuid_591")
        auto = record(url)
        set_mode(id="wq_uuid_777", layer="부가 서비스를 신청하시겠습니까?")
        ok, fail, logs = replay(auto)
        check("날마다 바뀌는 자동 id 는 'id 없음' 으로 본다 (지금처럼 글자로 누른다)", ok and HITS == ["layer"], (ok, HITS, fail))

        set_mode(id="", layer="운송장번호를 전송하시겠습니까?")
        legit = record(url)
        set_mode(id="", layer="운송장번호를 전송하시겠습니까?")
        ok, fail, logs = replay(legit)
        check("기록할 때부터 그 레이어의 [확인] 을 누른 흐름(id 없음)은 막지 않는다", ok and HITS == ["layer"], (ok, HITS, fail))
    finally:
        srv.shutdown()
    print("\n실패:", fails if fails else "없음")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
