"""가짜 문자 인증 사이트 (test_otp_replay·test_otp_manual 이 같이 쓴다).

[인증번호 받기] → 서버가 6자리 번호를 만든다 (SENT 에 쌓인다 = 보낸 문자) → '인증번호 6자리' 칸 → [확인] → 맞으면 /done, 틀리면 알림창.
"""
import json
import random
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SENT = []          # 사이트가 보낸 번호들 (문자)
VERIFY = """<!doctype html><meta charset="utf-8"><title>본인 인증</title>
<p>휴대폰으로 받은 인증번호를 넣어 주십시오.</p>
<button type="button" id="send" onclick="fetch('/api/send',{method:'POST'}).then(()=>document.getElementById('msg').textContent='보냈습니다')">인증번호 받기</button>
<input id="otp" placeholder="인증번호 6자리" autocomplete="off">
<button type="button" onclick="fetch('/api/check?c='+document.getElementById('otp').value).then(r=>r.json()).then(j=>{
  if (j.ok) { alert('인증번호가 일치합니다. 다시 로그인 해주세요.'); location.href='/done'; } else { alert('인증번호가 일치하지 않습니다. 다시 받아 주십시오'); document.getElementById('otp').value=''; } })">확인</button>
<p id="msg"></p>"""


# 인증번호 칸이 [인증번호 받기] 뒤 0.5초 지나서 나타나는 사이트 (XHR 뒤에 칸이 뜨는 꼴 - 재생기 사람 인증이 칸을 기다리는지, 검토 2026-11-03)
VERIFY_LATE = VERIFY.replace('<input id="otp" placeholder="인증번호 6자리" autocomplete="off">', '<span id="slot"></span>').replace(
    "document.getElementById('msg').textContent='보냈습니다'",
    "setTimeout(()=>{document.getElementById('slot').innerHTML='<input id=\"otp\" placeholder=\"인증번호 6자리\" autocomplete=\"off\">';"
    "document.getElementById('msg').textContent='보냈습니다'},500)")


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body, ctype="text/html; charset=utf-8"):
        b = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        path, _, q = self.path.partition("?")
        if path == "/verify":
            return self._send(VERIFY)
        if path == "/verify_late":
            return self._send(VERIFY_LATE)
        if path == "/api/check":
            return self._send(json.dumps({"ok": bool(SENT) and q == f"c={SENT[-1]}"}), "application/json")
        self._send(f"<!doctype html><meta charset='utf-8'><title>{path}</title><h1>{path}</h1>")

    def do_POST(self):
        SENT.append(f"{random.randint(0, 999999):06d}")
        self._send("{}", "application/json")


def start():
    """서버를 띄우고 (서버, 주소) 를 돌려준다."""
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def human(page):
    """사람이 인증을 통과하는 손놀림 (기록용)."""
    page.wait_for_timeout(500)
    page.click("#send")
    page.wait_for_function("document.getElementById('msg').textContent === '보냈습니다'")
    page.click("#otp")
    page.keyboard.type(SENT[-1], delay=20)           # 사람이 휴대폰을 보고 친다
    page.get_by_role("button", name="확인").click()
    page.wait_for_url("**/done")
