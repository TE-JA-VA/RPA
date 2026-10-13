# -*- coding: utf-8 -*-
"""마우스를 올려야 열리는 하위 메뉴 - 기록한 대로 재생되는가 (2026-10-13, 옵저버로 고른 하위 메뉴를 미리보기·옵저버가 못 고르던 것).

가짜 사이트 하나에 실제 사이트에서 본 메뉴 네 가지를 둔다 (창은 뜨지 않는다):
  A. 로그인 화면과 다음 화면에 똑같이 있는 글자 없는 아이콘 링크 (erpia.net 2026-10-02: 로그인 뒤 'a' 를 '새로 생긴 것' 으로만 찾다 멈춤)
  B. 스크립트가 class 를 붙여 여는 드롭다운 (erpia.net 고객센터 - Bootstrap) 안의 글자 없는 링크
  C. 하위 메뉴 판이 위 메뉴 밖 다른 자리에 있는 메뉴 (위 칸에 마우스를 올려 짐작으로는 못 연다)
  D. 두 단 메뉴 (CSS :hover) - 설정 > 계정 > 비밀번호
    .venv\\Scripts\\python.exe tests\\test_hover_menu.py
"""
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import web_replay as rec  # noqa: E402

HEAD = """<!doctype html><meta charset="utf-8"><title>{t}</title>
<style>
 body{{font-family:sans-serif;margin:0}} header{{display:flex;gap:20px;padding:10px;background:#234}}
 header a.ico{{display:inline-block;width:24px;height:24px;background:#fc0;border-radius:12px}}
 .nav{{list-style:none;margin:0;padding:0;display:flex;background:#eee}} .nav>li{{position:relative;padding:10px 18px}}
 .dropdown-menu{{display:none;position:absolute;left:0;top:100%;background:#fff;border:1px solid #ccc;list-style:none;padding:6px;margin:0;min-width:140px}}
 .dropdown-menu.show{{display:block}} .dropdown-menu li{{padding:6px}} .dropdown-menu .ico{{display:inline-block;width:20px;height:20px;background:#fc0}}
 .css ul{{display:none;position:absolute;left:0;top:100%;background:#fff;border:1px solid #ccc;list-style:none;padding:6px;margin:0;min-width:120px}}
 .css li{{position:relative}} .css:hover>ul,.css li:hover>ul{{display:block}} .css ul ul{{left:100%;top:0}}
 #mega{{display:none;position:fixed;left:400px;top:200px;background:#fff;border:1px solid #999;padding:12px}} #mega.on{{display:block}}
</style>
<header><a class="ico" href="/help" title=""></a><span style="color:#fff">{t}</span></header>
"""
LOGIN = HEAD.format(t="로그인") + """<button type="button" onclick="location.href='/main'">로그인</button>"""
MAIN = HEAD.format(t="메인") + """
<ul class="nav">
 <li class="dropdown"><a href="#" class="dropdown-toggle">고객센터</a>
  <ul class="dropdown-menu"><li><a href="/notice">공지사항</a></li><li><a href="/chat"><span class="ico"></span></a></li></ul></li>
 <li><a href="#" id="svc">서비스</a></li>
 <li class="css"><a href="#">설정</a><ul><li><a href="#">계정</a><ul><li><a href="/pw">비밀번호</a></li></ul></li></ul></li>
</ul>
<div style="height:400px"></div>
<div id="mega"><a href="/files">자료실</a></div>
<script>
// B: Bootstrap 처럼 마우스를 올리면 class 'show' 를 붙이고 떼면 조금 뒤 뗀다
for (const li of document.querySelectorAll('li.dropdown')) {
  const m = li.querySelector('.dropdown-menu'); let t = null;
  li.addEventListener('mouseenter', () => { clearTimeout(t); m.classList.add('show'); });
  li.addEventListener('mouseleave', () => { t = setTimeout(() => m.classList.remove('show'), 200); });
}
// C: '서비스' 에 올리면 멀리 떨어진 판(#mega)을 연다. 판 위에 있으면 열린 채
const svc = document.getElementById('svc'), mega = document.getElementById('mega'); let mt = null;
const on = () => { clearTimeout(mt); mega.classList.add('on'); }, off = () => { mt = setTimeout(() => mega.classList.remove('on'), 300); };
svc.addEventListener('mouseenter', on); svc.addEventListener('mouseleave', off);
mega.addEventListener('mouseenter', on); mega.addEventListener('mouseleave', off);
</script>"""
PAGES = {"/login": LOGIN, "/main": MAIN}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        body = PAGES.get(self.path.split("?")[0], f"<!doctype html><meta charset='utf-8'><title>{self.path}</title><h1>{self.path}</h1>")
        b = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)


srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"
OUT = tempfile.mkdtemp(prefix="hover_menu_")
fails = []


def check(name, ok, detail=""):
    print(("통과 " if ok else "실패 ") + name + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


def move(page, loc):
    """사람처럼 그 자리로 마우스를 천천히 옮긴다 (지나가는 칸에도 mouseover 가 간다)."""
    b = loc.bounding_box()
    page.mouse.move(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2, steps=10)
    page.wait_for_timeout(400)


def click(page, loc):
    move(page, loc)
    page.mouse.down()
    page.mouse.up()
    page.wait_for_timeout(800)


def replay(label, r, want_path):
    """재생해서 want_path 에 닿는지. 스크립트로 몰래 누르지 않고 (메뉴를 열어) 눌렀는지도 본다."""
    got, lines = {}, []
    orig = rec.Replayer._act

    def act(self, page, loc, s):
        orig(self, page, loc, s)
        page.wait_for_timeout(500)
        got["url"] = page.url
    rec.Replayer._act = act
    try:
        ok, rp = rec.replay(r, {"ID": "", "PW": ""}, os.path.join(OUT, label), "000", log=lines.append, step_timeout=6)
    finally:
        rec.Replayer._act = orig
    check(f"{label}: 재생이 끝까지 가서 {want_path} 에 닿는다", ok and got.get("url", "").endswith(want_path),
          f"{rp.results[-1] if rp.results else None} {got.get('url')}")
    check(f"{label}: 메뉴를 열어 눌렀다 (스크립트로 몰래 누르지 않음)", not any("스크립트로 누름" in x for x in lines),
          [x for x in lines if "스크립트" in x or "가려진" in x])


def scenario(label, start, human, want_path):
    """기록 → 재생. 기록을 돌려준다."""
    r = rec.record(BASE + start, os.path.join(OUT, f"{label}.json"), headless=True, human=human)
    print(f"--- {label}: " + " / ".join(rec.describe(s) for s in r["steps"]))
    replay(label, r, want_path)
    return r


# A. 로그인 → (다음 화면) 머리 띠의 글자 없는 아이콘. 같은 아이콘이 로그인 화면에도 있었다
def human_a(page):
    click(page, page.get_by_role("button", name="로그인"))
    page.wait_for_url("**/main")
    page.wait_for_timeout(500)
    click(page, page.locator("header a.ico"))
r = scenario("A_로그인뒤_아이콘", "/login", human_a, "/help")
check("A: 넘어간 화면의 것은 '새로 생긴 것' 으로 적지 않는다", "appearsAfter" not in r["steps"][1], r["steps"][1].get("appearsAfter"))
old = dict(r, steps=[dict(r["steps"][0]), dict(r["steps"][1], appearsAfter=0)])   # 옛 옵저버가 만든 기록 (프리셋에 이미 있는 것)
replay("A_옛기록", old, "/help")


# B. 고객센터 드롭다운 (스크립트 class) 안의 글자 없는 링크
def human_b(page):
    page.wait_for_timeout(1000)          # 사람은 화면이 뜬 뒤에 움직인다 (뜨는 동안 지나간 칸은 기록이 거른다)
    move(page, page.get_by_role("link", name="고객센터"))
    click(page, page.locator(".dropdown-menu.show a[href='/chat']"))
r = scenario("B_드롭다운_아이콘", "/main", human_b, "/chat")
check("B: 기록에 '고객센터' 에 마우스 올리기가 들어간다", any(s["kind"] == "hover" and s["target"]["text"] == "고객센터" for s in r["steps"]),
      [s["kind"] for s in r["steps"]])


# C. 서비스 → 멀리 떨어진 판의 자료실
def human_c(page):
    page.wait_for_timeout(1000)
    move(page, page.locator("#svc"))
    click(page, page.locator("#mega a"))
r = scenario("C_떨어진_판", "/main", human_c, "/files")
check("C: 기록에 '서비스' 에 마우스 올리기가 들어간다", any(s["kind"] == "hover" and s["target"]["text"] == "서비스" for s in r["steps"]),
      [s["kind"] for s in r["steps"]])


# D. 두 단 메뉴 설정 > 계정 > 비밀번호
def human_d(page):
    page.wait_for_timeout(1000)
    move(page, page.get_by_role("link", name="설정"))
    move(page, page.get_by_role("link", name="계정"))
    click(page, page.get_by_role("link", name="비밀번호"))
r = scenario("D_두단", "/main", human_d, "/pw")
hv = [s["target"]["text"] for s in r["steps"] if s["kind"] == "hover"]
check("D: 기록에 '설정' → '계정' 마우스 올리기가 차례로 들어간다", hv[-2:] == ["설정", "계정"], hv)

srv.shutdown()
print("실패:", fails if fails else "없음")
sys.exit(1 if fails else 0)
