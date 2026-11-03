# -*- coding: utf-8 -*-
"""로그인 때 사이트가 스스로 연 공지 창 (O2, 2026-11-03) - 창은 뜨지 않는다 (headless).

기록에는 로그인 단계가 '새 창을 연다' 로 남고 그 창에서는 [닫기] 만 눌렀다. 공지가 내려간 날 재생이 그 창을 15초 기다린 뒤
실패했다. 이제 그 창이 공지 창(notice_popup - 한 일이 마우스 올리기·닫기류뿐)이면 짧게(NOTICE_WAIT 8초) 기다리고 없으면 넘어간다.
일하는 창(주문 누르기 등)을 여는 단계는 예전처럼 기다리고 실패한다.
    .venv\\Scripts\\python.exe tests\\test_notice_popup.py
"""
import os
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from playwright.sync_api import sync_playwright  # noqa: E402

import web_replay as rec  # noqa: E402

fails = []


def check(name, ok, detail=""):
    print(f"  [{'통과' if ok else '실패'}] {name}" + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


def target(text, tag="a"):
    return {"tag": tag, "id": "", "name": "", "type": "", "text": text, "textIndex": 0, "textCount": 1, "aria": "",
            "title": "", "placeholder": "", "label": "", "labelIndex": 0, "labelKind": "", "href": "", "css": "", "inOverlay": False}


def step(text, page=0, tag="a", **kw):
    return dict({"kind": "click", "page": page, "frame": {"main": True, "name": "", "path": "/"}, "url": "/", "target": target(text, tag)}, **kw)


NOTICE = [step("로그인", opens=1), step("닫기", page=1, tag="button"), step("확인")]
WORK = [step("로그인", opens=1), step("주문", page=1, tag="button"), step("확인")]
check("공지 창: 그 창에서 [닫기] 만 눌렀다", rec.notice_popup(NOTICE, 1))
check("일하는 창: 그 창에서 '주문' 을 눌렀다", not rec.notice_popup(WORK, 1))
check("마우스만 올린 창도 공지 창", rec.notice_popup([step("로그인", opens=1), dict(step("배너", page=1), kind="hover")], 1))

SCRIPT = ("<script>function notice() { const w = window.open(''); "
          "w.document.write('<button onclick=window.close()>닫기</button> <button>주문</button>'); }</script>")


def page_html(opens):
    return (f"<!doctype html><meta charset='utf-8'>{SCRIPT}<a href='#' onclick='{'notice(); ' if opens else ''}return false;'>로그인</a>"
            " <a href='#' onclick='return false;'>확인</a>")


def run(steps, opens):
    with sync_playwright() as p:
        b = rec.edge(p.chromium.launch, headless=True)
        ctx = b.new_context()
        page = ctx.new_page()
        page.set_content(page_html(opens))
        rp = rec.Replayer(ctx, {"steps": steps}, {}, tempfile.mkdtemp(), "000", log=lambda m: None, step_timeout=3, step_tries=1)
        rp.pages[0] = page
        rp.needs, rp.loose = {}, set()
        out, t0 = [], time.time()
        for i, s in enumerate(steps):
            try:
                rp._step(i, s)
                out.append("ok")
            except rec.Skip:
                out.append("skip")
            except Exception as e:
                out.append(type(e).__name__)
                break
        b.close()
        return out, time.time() - t0


got, took = run(NOTICE, opens=True)
check("공지 창이 뜬 날: 셋 다 그대로", got == ["ok", "ok", "ok"], str(got))
got, took = run(NOTICE, opens=False)
check(f"공지 창이 안 뜬 날: 그 창의 단계만 건너뛰고 이어 간다, 15초를 기다리지 않는다 ({took:.1f}초)",
      got == ["ok", "skip", "ok"] and took < 12, str(got))
got, took = run(WORK, opens=False)
check(f"일하는 창이 안 뜨면 예전처럼 실패 ({took:.1f}초)", got and got[0] == "TimeoutError" and took >= 14, str(got))

print("\n실패:", fails if fails else "없음")
sys.exit(1 if fails else 0)
