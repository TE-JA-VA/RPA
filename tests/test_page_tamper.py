# -*- coding: utf-8 -*-
"""자바스크립트 기본 기능을 바꿔치기한 사이트 - 옵저버가 기록하고 재생하는가 (2026-10-14 비즈메카 메일).

비즈메카 메일(ezwebmail)의 jsmap.js 는 `Map = function(){...}` 으로 기본 Map 을 덮는다. Playwright 는 페이지와 값을
주고받을 때 Map.set 을 써서, 옵저버의 보고가 모두 'visited.set is not a function' 으로 사라져 메일 누르기·첨부 받기가
기록되지 않았다. 가짜 메일 화면 (창은 뜨지 않는다):
  A. Map 을 바꿔치기 (비즈메카 그대로)
  B. Map·Set 과 Array.prototype.indexOf·remove (비즈메카 imoxion.js) 까지 바꿔치기
  JSON.stringify 를 바꿔치기하는 사이트는 막지 못한다 - Playwright 가 보고를 감쌀 때 페이지의 JSON.stringify 를 쓴다
  (그것까지 막으려면 옵저버를 격리된 세계에서 돌려야 한다. 비즈메카는 원래 JSON 그대로)
  흐름: 메일 목록 줄(li, onclick)을 눌러 열기 → 첨부 이름 링크(onclick attachDownload) → 파일 받기
    .venv\\Scripts\\python.exe tests\\test_page_tamper.py
"""
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import web_replay as rec  # noqa: E402

JSMAP = """Map = function() { this.map = new Object(); };
Map.prototype = { put: function(k, v) { this.map[k] = v; }, get: function(k) { return (k in this.map) ? this.map[k] : ''; },
                  size: function() { var n = 0; for (var p in this.map) n++; return n; } };"""
WORSE = ("Set = function() {}; Array.prototype.remove = function(a, b) { return 0; };"
         "Array.prototype.indexOf = function(x) { for (var i = 0; i < this.length; i++) if (this[i] == x) return i; return -1; };")
MAIL = """<!doctype html><meta charset="utf-8"><title>메일</title>
<script>{tamper}</script>
<style>li.m_data{{cursor:pointer;padding:6px;border-bottom:1px solid #ddd}} #view{{display:none;padding:10px}}</style>
<ul id="list">
 <li class="m_data" data-key="k1" onclick="openMail('k1')"><span class="m_write">보낸이</span> <p class="m_subject">[주문] 10월 14일 주문서</p></li>
 <li class="m_data" data-key="k2" onclick="openMail('k2')"><span class="m_write">다른이</span> <p class="m_subject">공지</p></li>
</ul>
<div id="view"><h3 id="vt"></h3><a href="javascript:;" onclick="attachDownload(this.dataset.k)" id="att">주문서.xlsx</a></div>
<script>
var opened = new Map(); opened.put('x', 1);        // 사이트는 바꿔치기한 Map 을 쓴다 (원래 Map 이면 put 이 없어 여기서 멈춘다)
function openMail(k) {{ location.hash = 'act=VIEW&ukey=' + k; document.getElementById('vt').textContent = '메일 ' + k;
  document.getElementById('att').dataset.k = k; document.getElementById('view').style.display = 'block'; }}
function attachDownload(k) {{ location.href = '/download?k=' + k; }}
</script>"""


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/download":
            b = b"PK\x03\x04fake-xlsx"
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            self.send_header("Content-Disposition", "attachment; filename=order.xlsx")
        else:
            b = MAIL.format(tamper={"/a": JSMAP, "/b": JSMAP + WORSE}.get(path, "")).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)


srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"
OUT = tempfile.mkdtemp(prefix="page_tamper_")
fails = []


def check(name, ok, detail=""):
    print(("통과 " if ok else "실패 ") + name + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


def human(page):
    page.wait_for_timeout(500)
    page.click("li.m_data[data-key=k1] p.m_subject")
    page.wait_for_timeout(500)
    with page.expect_download():
        page.click("#att")
    page.wait_for_timeout(500)


for label, path in (("A_Map", "/a"), ("B_Map_Set_Array", "/b")):
    r = rec.record(BASE + path, os.path.join(OUT, f"{label}.json"), headless=True, human=human)
    steps = r["steps"]
    print(f"--- {label}: " + " / ".join(rec.describe(s) for s in steps))
    texts = [(s["kind"], (s.get("target") or {}).get("text", "")) for s in steps]
    check(f"{label}: 메일 줄 누르기가 기록된다", any(k == "click" and "주문서" in t for k, t in texts), texts)
    att = [s for s in steps if s["kind"] == "click" and (s.get("target") or {}).get("text") == "주문서.xlsx"]
    check(f"{label}: 첨부 누르기가 기록되고, 받은 파일이 그 단계에 붙는다", len(att) == 1 and att[0].get("download") == "order.xlsx",
          [(s["kind"], (s.get("target") or {}).get("text"), s.get("download")) for s in steps])
    lines = []
    ok, rp = rec.replay(r, {"ID": "", "PW": ""}, os.path.join(OUT, label), "013", log=lines.append, step_timeout=6, step_tries=1)
    check(f"{label}: 재생이 끝까지 가서 파일을 받는다", ok and len(rp.saved) == 1 and os.path.basename(rp.saved[0]) == "(013)order.xlsx",
          (rp.results[-2:], rp.saved))

srv.shutdown()
print("실패:", fails if fails else "없음")
sys.exit(1 if fails else 0)
