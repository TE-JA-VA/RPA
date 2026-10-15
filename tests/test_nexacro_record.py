# -*- coding: utf-8 -*-
"""Nexacro 처럼 div 로 그린 화면 - 기록·재생 (2026-10-15 농협몰 PSCM 기록에서 본 것).

가짜 사이트 (창은 뜨지 않는다):
  /login  : 칸 이름표가 칸 위에 따로 놓인 글자('관리자 아이디'·'비밀번호' - <label> 아님), 그림으로 그린 체크박스
            '아이디 저장' (손가락 커서 아님, 누르면 그림이 바뀐다), LOGIN -> /search?save=0|1
  /search : div 로 그린 드롭다운 (누르면 목록이 펼쳐지고, 항목을 누르면 닫히며 글자가 바뀐다), 조회 -> /result?period=..&save=..
  /otp    : 인증번호 칸 (id 에 '인증' 단서 없음 - edtAttcInput, 위 글자도 없음) + 확인 -> 알림 '인증되었습니다.' -> /done
    .venv\\Scripts\\python.exe tests\\test_nexacro_record.py
"""
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import web_replay as rec  # noqa: E402

CSS = """<style>body{font-family:sans-serif;margin:0} .c{position:absolute} .lbl{cursor:default}
 .btn{cursor:pointer;background:#2a6;color:#fff;text-align:center;padding:6px} .chk img{width:14px;height:14px}
 .list{display:none;background:#fff;border:1px solid #999} .list.on{display:block} .list div{padding:4px}</style>"""
PNG = "data:image/svg+xml;utf8,%3Csvg xmlns=%27http://www.w3.org/2000/svg%27 width=%2714%27 height=%2714%27%3E%3Crect width=%2714%27 height=%2714%27 fill=%27%23{}%27/%3E%3C/svg%3E"
LOGIN = """<!doctype html><meta charset="utf-8"><title>로그인</title>__CSS__
<div class="c lbl" id="form_Static00" tabindex="0" style="left:40px;top:40px;width:120px"><div>관리자 아이디</div></div>
<div class="c" id="form_edtId" tabindex="0" style="left:40px;top:64px"><input id="form_edtId_input" style="width:200px"></div>
<div class="c lbl" id="form_Static01" tabindex="0" style="left:40px;top:104px;width:120px"><div>비밀번호</div></div>
<div class="c" id="form_edtPasswd" tabindex="0" style="left:40px;top:128px"><input id="form_edtPasswd_input" type="password" style="width:200px"></div>
<div class="c chk" id="form_chkIdSave" tabindex="0" style="left:40px;top:170px;width:140px" data-on="0">
  <div id="form_chkIdSave_chkimg"><img src="__OFF__"></div><div id="form_chkIdSaveTextBoxElement" style="position:absolute;left:20px;top:0">아이디 저장</div></div>
<div class="c btn" id="form_btnLogin" tabindex="0" style="left:40px;top:210px;width:200px">LOGIN</div>
<script>
const chk = document.getElementById('form_chkIdSave');
chk.addEventListener('click', () => { const on = chk.dataset.on === '1' ? '0' : '1'; chk.dataset.on = on;
  chk.querySelector('img').src = on === '1' ? '__ON__' : '__OFF__'; });
document.getElementById('form_btnLogin').addEventListener('click', () => location.href = '/search?save=' + chk.dataset.on);
</script>"""
SEARCH = """<!doctype html><meta charset="utf-8"><title>조회</title>__CSS__
<div class="c" id="form_cboPeriod" tabindex="0" style="left:40px;top:40px;width:160px;border:1px solid #999;padding:4px">
  <div id="form_cboPeriodTextBoxElement">3개월</div></div>
<div class="c list" id="form_cboPeriod_combolist" style="left:40px;top:70px;width:160px">
  <div id="form_cboPeriod_item0">3개월</div><div id="form_cboPeriod_item1">1년</div></div>
<div class="c btn" id="form_btnSearch" tabindex="0" style="left:240px;top:40px;width:80px">조회</div>
<script>
const cbo = document.getElementById('form_cboPeriod'), list = document.getElementById('form_cboPeriod_combolist');
cbo.addEventListener('click', () => list.classList.toggle('on'));
for (const it of list.children) it.addEventListener('click', () => {
  document.getElementById('form_cboPeriodTextBoxElement').textContent = it.textContent; list.classList.remove('on'); });
document.getElementById('form_btnSearch').addEventListener('click', () => location.href = '/result?period=' +
  encodeURIComponent(document.getElementById('form_cboPeriodTextBoxElement').textContent) + '&' + location.search.slice(1));
</script>"""
OTP = """<!doctype html><meta charset="utf-8"><title>인증</title>__CSS__
<div class="c" id="form_edtAttcInput" tabindex="0" style="left:40px;top:40px"><input id="form_edtAttcInput_input" style="width:120px"></div>
<div class="c btn" id="form_btnOk" tabindex="0" style="left:180px;top:40px;width:60px">확인</div>
<script>document.getElementById('form_btnOk').addEventListener('click', () => { alert('인증되었습니다.'); location.href = '/done'; });</script>"""
fix = lambda h: h.replace("__CSS__", CSS).replace("__OFF__", PNG.format("fff")).replace("__ON__", PNG.format("2a6"))
PAGES = {"/login": fix(LOGIN), "/search": fix(SEARCH), "/otp": fix(OTP)}


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
OUT = tempfile.mkdtemp(prefix="nexacro_")
fails = []


def check(name, ok, detail=""):
    print(("통과 " if ok else "실패 ") + name + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


def click(page, loc):
    b = loc.bounding_box()
    page.mouse.move(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2, steps=5)
    page.mouse.down()
    page.mouse.up()
    page.wait_for_timeout(700)


def human_login(page):
    page.wait_for_timeout(800)
    click(page, page.get_by_text("관리자 아이디", exact=True))          # 이름표 글자를 누름 - 아무것도 안 바뀌니 기록하지 않는다
    page.mouse.click(600, 400); page.wait_for_timeout(700)            # 빈 곳
    page.click("#form_edtId_input"); page.keyboard.type("me@x.com")
    page.click("#form_edtPasswd_input"); page.keyboard.type("pw1234")
    click(page, page.locator("#form_chkIdSaveTextBoxElement"))      # 꾸민 체크박스 (글자 쪽을 누름)
    click(page, page.locator("#form_btnLogin"))
    page.wait_for_url("**/search**")
    page.wait_for_timeout(800)
    click(page, page.locator("#form_cboPeriodTextBoxElement"))      # 드롭다운 펼치기
    click(page, page.locator("#form_cboPeriod_item1"))              # '1년'
    click(page, page.get_by_text("조회", exact=True))
    page.wait_for_url("**/result**")
    page.wait_for_timeout(500)


r = rec.record(BASE + "/login", os.path.join(OUT, "a.json"), headless=True, human=human_login)
print("--- 기록: " + " / ".join(rec.describe(s) for s in r["steps"]))
fill = next((s for s in r["steps"] if s["kind"] == "fill"), None)
secret = next((s for s in r["steps"] if s["kind"] == "secret"), None)
check("이름표가 칸 위에 따로 있어도 칸 이름은 '관리자 아이디'", fill is not None and rec.name_of(fill) == "관리자 아이디",
      fill and fill["target"])
check("비밀번호 칸 이름은 '비밀번호'", secret is not None and rec.name_of(secret) == "비밀번호", secret and secret["target"])
clicks = [s["target"]["text"] for s in r["steps"] if s["kind"] == "click"]
check("손가락 커서가 아닌 그림 체크박스를 누른 것도 기록한다", "아이디 저장" in clicks, clicks)
check("div 드롭다운: 펼치기와 항목 '1년' 누르기를 기록한다", "3개월" in clicks and "1년" in clicks, clicks)
check("빈 곳·이름표 글자를 누른 것은 아니다 (기록 단계에 이름표 없음)", "관리자 아이디" not in clicks and "비밀번호" not in clicks, clicks)

got = {}
orig = rec.Replayer._act


def act(self, page, loc, s):
    orig(self, page, loc, s)
    page.wait_for_timeout(400)
    got["url"] = page.url


rec.Replayer._act = act
try:
    ok, rp = rec.replay(r, {"ID": "me@x.com", "PW": "pw1234"}, os.path.join(OUT, "a"), "000", log=lambda m: None, step_timeout=6)
finally:
    rec.Replayer._act = orig
check("재생: 체크박스를 켜고 드롭다운에서 '1년' 을 골라 조회까지 간다",
      ok and "period=1%EB%85%84" in got.get("url", "") and "save=1" in got.get("url", ""),
      f"{rp.results[-1] if rp.results else None} {got.get('url')}")


def human_otp(page):
    page.wait_for_timeout(800)
    page.click("#form_edtAttcInput_input"); page.keyboard.type("4821")
    page.once("dialog", lambda d: d.accept())
    click(page, page.locator("#form_btnOk"))
    page.wait_for_url("**/done")


r = rec.record(BASE + "/otp", os.path.join(OUT, "b.json"), headless=True, human=human_otp)
print("--- 기록: " + " / ".join(rec.describe(s) for s in r["steps"]))
otp = [s for s in r["steps"] if s["kind"] == "otp"]
check("숫자 4자리를 넣고 '인증' 알림이 뜨면 단서가 없어도 인증번호 칸 (옛 번호는 남기지 않는다)",
      len(otp) == 1 and "value" not in otp[0] and not any(s.get("value") == "4821" for s in r["steps"]), [s["kind"] for s in r["steps"]])

srv.shutdown()
print("실패:", fails if fails else "없음")
sys.exit(1 if fails else 0)
