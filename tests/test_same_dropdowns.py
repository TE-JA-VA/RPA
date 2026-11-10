# -*- coding: utf-8 -*-
"""값이 같은 드롭다운 여럿 (사용자 2026-11-10 '여러 드롭다운이 같은 값을 가지면 정확히 못 찾아간다').

가짜 화면: 드롭다운 A·B 둘 다 칸 글 '전체', 고를 값도 같다 (전체·3개월·6개월). 목록은 화면 맨 끝에 따로 숨겨 둔 ul (id 없음).
기록은 A·B 순서, 재생 날은 B·A 순서로 그려진다 - 위치·몇 번째로 찾으면 다른 드롭다운을 누른다.
창은 뜨지 않는다.  .venv\\Scripts\\python.exe tests\\test_same_dropdowns.py
"""
import datetime
import json
import os
import sys
import tempfile
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import web_replay as rec  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
OUT = tempfile.mkdtemp(prefix="rpa_samedd_")
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.join(OUT, "no_browsers")
fails = []
STATE = {"order": "AB", "picks": []}


def check(name, ok, detail=""):
    print(f"  [{'통과' if ok else '실패'}] {name}" + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


def page_html(order, slow=False, lazy=False, win=1):
    opts = "".join(f'<li role="option" onclick="pick(this)">{v}</li>' for v in ("전체", "3개월", "6개월"))
    # A: 바깥 칸에만 id. B: 현대이지웰(WebSquare) 모양 - 칸 자신에 id, 그 안에 창 번호 (mf_wdc_main_subWindow1_wframe_sbx_dlvStatus,
    # 사용자 2026-11-10 HTML). 창을 연 차례에 따라 subWindow 번호가 바뀐다. 손가락 커서도 role 도 없는 div 라 '바뀜을 보고 누르기' 로 적힌다
    cur = {"A": '<span role="button" class="cur" onclick="openL(\'A\', this)">전체</span>',
           "B": f'<div id="mf_wdc_main_subWindow{win}_wframe_sbx_B" class="cur" tabindex="0" role="combobox" onclick="openL(\'B\', this)">'
                '<div class="lbl">전체</div></div>'}
    dds = "".join(f'<div id="dd_{x}" class="dd"><b>기간{x}</b> {cur[x]}</div>' for x in order)
    # 창 번호가 밀린 날: 먼저 연 창(숨김)이 화면에 남아 있고 거기에도 '전체' 칸이 있다 (WebSquare 는 닫지 않은 창을 숨겨 둔다)
    old_win = ('<div style="display:none"><div id="mf_wdc_main_subWindow1_wframe_sbx_other" class="cur" tabindex="0">'
               '<div class="lbl">전체</div></div></div>') if win != 1 else ""
    dds = old_win + dds
    lists = "".join(f'<ul class="opts" data-for="{x}">{opts}</ul>' for x in order)
    return f"""<!doctype html><meta charset="utf-8"><style>
.dd{{margin:20px;}} .cur{{border:1px solid #888;padding:4px 20px;}}
.opts{{display:none;position:absolute;z-index:20;width:200px;background:#fff;border:1px solid #888;margin:0;padding:0;list-style:none}}
.opts li{{padding:6px}}</style>
<button id="open" onclick="openForm()">조건 열기</button><div id="bar">{"" if lazy else dds}</div><div id="lists">{"" if lazy else lists}</div>
<script>
const DDS = {json.dumps(dds)}, LISTS = {json.dumps(lists)};
function openForm() {{ const b = document.getElementById("bar"); if (!b.children.length) {{ b.innerHTML = DDS; document.getElementById("lists").innerHTML = LISTS; }} }}
let cur = null;
function openL(x, el) {{
  document.querySelectorAll('.opts').forEach(u => u.style.display = 'none');
  const u = document.querySelector('.opts[data-for="' + x + '"]'), r = el.getBoundingClientRect();
  const show = () => {{ u.style.left = r.left + 'px'; u.style.top = (r.bottom + scrollY) + 'px'; u.style.display = 'block'; cur = x; }};
  if ({'true' if slow else 'false'}) setTimeout(show, 1500); else show();     // 목록이 늦게 펼쳐지는 사이트
}}
function pick(li) {{
  const u = li.parentElement, x = u.dataset.for;
  fetch('/pick?dd=' + x + '&v=' + encodeURIComponent(li.textContent));
  document.querySelector('#dd_' + x + ' .cur').textContent = li.textContent; u.style.display = 'none';
}}
</script>"""


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == "/pick":
            q = urllib.parse.parse_qs(u.query)
            STATE["picks"].append((q["dd"][0], q["v"][0]))
            body = b"ok"
        else:
            body = page_html(STATE["order"], STATE.get("slow"), STATE.get("lazy"), STATE.get("win", 1)).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)


def click(page, loc):
    loc.wait_for(state="visible", timeout=5000)
    b = loc.bounding_box()
    page.mouse.click(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2)
    page.wait_for_timeout(300)


def human(page):
    click(page, page.locator("#open"))
    click(page, page.locator("#dd_B .cur"))
    click(page, page.locator('.opts[data-for="B"] li', has_text="3개월"))
    click(page, page.locator("#dd_A .cur"))
    click(page, page.locator('.opts[data-for="A"] li', has_text="6개월"))
    page.wait_for_timeout(500)


def pure_checks():
    print("=== 옛 기록의 id 끝 (브라우저 없이)")
    t = dict(tag="div", id="mf_wdc_main_subWindow1_wframe_sbx_dlvStatus", text="전체", textCount=14, textIndex=3, name="", aria="",
             title="", placeholder="", label="", labelKind="", labelIndex=0, href="", css="x")
    check("idTail 이 없던 옛 기록은 id 의 마지막 두 마디로 찾는다 (현대이지웰 배송상태)",
          ("id 끝", '[id$="_sbx_dlvStatus"]', None) in rec.candidates(t), str(rec.candidates(t)))
    check("화면마다 바뀌는 id (wq_uuid_591) 는 id 끝으로 쓰지 않는다",
          not any(h == "id 끝" for h, _, _ in rec.candidates(dict(t, id="mf_wdc_main_subWindow1_wframe_wq_uuid_591"))))
    check("기록기가 하나로 정해지는 끝이 없다고 적었으면 (빈 글자) 만들지 않는다",
          not any(h == "id 끝" for h, _, _ in rec.candidates(dict(t, idTail=""))))


def main():
    pure_checks()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_port}/list"
    try:
        STATE["lazy"] = True     # 기록 날은 [조건 열기] 를 눌러야 드롭다운이 생긴다 - 드롭다운이 '1단계 뒤에 새로 생긴 것' 으로 적힌다
        print("=== 기록 (A·B 순서, [조건 열기] 뒤에 생기는 드롭다운): B 를 열어 3개월, A 를 열어 6개월")
        r = rec.record(url, os.path.join(OUT, "rec.json"), headless=True, human=human, record_date=datetime.date(2026, 11, 10))
        for i, s in enumerate(r["steps"], 1):
            print(f"    {i:2d}. {rec.describe(s)}")
        check("기록 때 고른 것", STATE["picks"] == [("B", "3개월"), ("A", "6개월")], str(STATE["picks"]))
        # 마지막: 재생 날은 드롭다운이 처음부터 그려져 있다 (사용자 2026-11-10 미리보기 - 같은 기록이 한 번은 못 찾고 한 번은 [id] 로 찾았다)
        b_target = r["steps"][1]["target"]
        check("B 칸은 칸 자신의 id 와 id 끝을 적는다 (창 번호가 바뀌어도 찾게)",
              b_target["id"] == "mf_wdc_main_subWindow1_wframe_sbx_B" and b_target.get("idTail") == "_sbx_B", str(b_target))
        # 마지막 둘: 재생 날은 드롭다운이 처음부터 그려져 있다 (사용자 2026-11-10 미리보기 - 같은 기록이 한 번은 못 찾고 한 번은 [id] 로 찾았다),
        # 창 번호가 바뀌었다 (subWindow1 → 2)
        for order, slow, lazy, win in (("AB", False, True, 1), ("BA", False, True, 1), ("BA", True, True, 1), ("BA", False, False, 1),
                                       ("AB", False, True, 2)):
            STATE["order"], STATE["slow"], STATE["lazy"], STATE["win"], STATE["picks"] = order, slow, lazy, win, []
            what = (f"{order}{' 늦은 목록' if slow else ''}{'' if lazy else ' 처음부터 있는 드롭다운'}"
                    f"{f' 창 번호 {win}' if win != 1 else ''}")
            print(f"=== 재생 {what}")
            ok, rr = rec.replay(r, {}, os.path.join(OUT, what), "001", log=print, step_timeout=5, step_tries=1)
            print("    찾은 단서: " + " / ".join(h for _, st, h in rr.results if st == "ok"))
            check(f"재생 {what}: 같은 드롭다운의 같은 값을 고른다 (B 3개월, A 6개월)",
                  STATE["picks"] == [("B", "3개월"), ("A", "6개월")], f"{ok} {STATE['picks']} {rr.results[-1:]}")
    finally:
        srv.shutdown()
    print("\n실패:", fails if fails else "없음")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
