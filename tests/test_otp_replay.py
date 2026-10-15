# -*- coding: utf-8 -*-
"""기록한 프리셋의 2차인증 (휴대폰 중계 설계 13절) - 재생기만, 서버 없이 (중계는 흉내).

가짜 사이트: [인증번호 받기] → 서버가 6자리 번호를 만든다 → '인증번호 6자리' 칸 → [확인] → 맞으면 /done, 틀리면 알림창.
  기록: 사람이 번호를 받아 치는 대로 → 그 칸은 'otp' (값 없음), 바로 앞 누르기는 '인증번호 받기' (otpSend).
  재생: 흉내 중계가 번호를 준다 / 처음엔 틀린 번호 / 안 준다 / 늘 틀린 번호 / 중계 없음.
    .venv\\Scripts\\python.exe tests\\test_otp_replay.py
"""
import json
import os
import random
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import web_replay as rec  # noqa: E402

SENT = []          # 사이트가 보낸 번호들 (문자)
VERIFY = """<!doctype html><meta charset="utf-8"><title>본인 인증</title>
<p>휴대폰으로 받은 인증번호를 넣어 주십시오.</p>
<button type="button" id="send" onclick="fetch('/api/send',{method:'POST'}).then(()=>document.getElementById('msg').textContent='보냈습니다')">인증번호 받기</button>
<input id="otp" placeholder="인증번호 6자리" autocomplete="off">
<button type="button" onclick="fetch('/api/check?c='+document.getElementById('otp').value).then(r=>r.json()).then(j=>{
  if (j.ok) { alert('인증번호가 일치합니다. 다시 로그인 해주세요.'); location.href='/done'; } else { alert('인증번호가 일치하지 않습니다. 다시 받아 주십시오'); document.getElementById('otp').value=''; } })">확인</button>
<p id="msg"></p>"""


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
        if path == "/api/check":
            return self._send(json.dumps({"ok": bool(SENT) and q == f"c={SENT[-1]}"}), "application/json")
        self._send(f"<!doctype html><meta charset='utf-8'><title>{path}</title><h1>{path}</h1>")

    def do_POST(self):
        SENT.append(f"{random.randint(0, 999999):06d}")
        self._send("{}", "application/json")


srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"
OUT = tempfile.mkdtemp(prefix="otp_replay_")
fails = []


def check(name, ok, detail=""):
    print(("통과 " if ok else "실패 ") + name + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


class FakeRelay:
    """휴대폰 중계 흉내. how: 'ok' 사이트가 보낸 번호 / 'wrong_first' 처음 한 번은 틀린 번호 / 'none' 안 옴 / 'wrong' 늘 틀린 번호."""

    def __init__(self, how):
        self.how, self.opened, self.closed, self.waits = how, 0, 0, 0

    def open(self):
        self.opened += 1
        return f"req{self.opened}"

    def wait(self, req, seconds, tick, field=None):
        self.waits += 1
        tick(0.3)
        if self.how == "none":
            return None
        if self.how == "wrong" or (self.how == "wrong_first" and self.waits == 1):
            return "000000" if SENT[-1] != "000000" else "111111"
        return SENT[-1]

    def close(self, req):
        self.closed += 1


def human(page):
    page.wait_for_timeout(500)
    page.click("#send")
    page.wait_for_function("document.getElementById('msg').textContent === '보냈습니다'")
    page.click("#otp")
    page.keyboard.type(SENT[-1], delay=20)           # 사람이 휴대폰을 보고 친다
    page.get_by_role("button", name="확인").click()
    page.wait_for_url("**/done")


r = rec.record(BASE + "/verify", os.path.join(OUT, "rec.json"), headless=True, human=human)
print("--- 기록: " + " / ".join(rec.describe(s) for s in r["steps"]))
kinds = [s["kind"] for s in r["steps"]]
check("인증번호 칸은 'otp' 단계, 바로 앞 누르기는 '인증번호 받기'", kinds == ["click", "otp", "click"] and r["steps"][0].get("otpSend") is True,
      [(s["kind"], s.get("otpSend")) for s in r["steps"]])
text = open(os.path.join(OUT, "rec.json"), encoding="utf-8").read()
check("기록 파일에 인증번호 숫자가 없다 (한 번 쓰는 번호)", SENT[-1] not in text and "value" not in r["steps"][1])
check("단계 설명", "문자로 받은 인증번호" in rec.describe(r["steps"][1]) and "인증번호 문자 요청" in rec.describe(r["steps"][0]),
      [rec.describe(s) for s in r["steps"]])


for msg, rej in (("인증번호가 일치합니다. 로그인 해주세요.", False), ("인증번호가 일치하지 않습니다.", True),   # 비즈메카 2026-10-14
                 ("인증번호가 확인되었습니다.", False), ("인증번호 불일치", True), ("인증 시간이 만료되었습니다", True)):
    check(f"알림창 '{msg}' → {'거절' if rej else '통과'}", bool(rec.OTP_REJECT.search(msg)) == rej)


def replay(label, relay, wait=2):
    lines = []
    ctx = {}
    orig = rec.Replayer.__init__

    def init(self, *a, **kw):
        orig(self, *a, **kw)
        self.otp, self.otp_wait = relay, wait
        ctx["rp"] = self
    rec.Replayer.__init__ = init
    try:
        ok, rp = rec.replay(r, {"ID": "", "PW": ""}, os.path.join(OUT, label), "000", log=lines.append, step_timeout=5, step_tries=1)
    finally:
        rec.Replayer.__init__ = orig
    return ok, rp, lines


n0 = len(SENT)
ok, rp, lines = replay("ok", FakeRelay("ok"))
rl = rp.otp
check("번호가 오면 넣고 [확인] → 끝까지", ok and len(rp.results) == 3, rp.results[-1:])
check("요청은 [인증번호 받기] 누르기 전에 한 번 열고, 끝나면 닫는다", rl.opened == 1 and rl.closed >= 1 and len(SENT) - n0 == 1, (rl.opened, rl.closed))

n0 = len(SENT)
ok, rp, lines = replay("wrong_first", FakeRelay("wrong_first"))
check("처음 번호를 사이트가 거절하면 [인증번호 받기] 부터 다시 → 통과", ok and rp.otp.opened == 2 and len(SENT) - n0 == 2, (rp.results, rp.otp.opened))
check("다시 시도는 로그에 남는다", any("다시" in x and "2/3" in x for x in lines), [x for x in lines if "인증" in x])

ok, rp, lines = replay("none", FakeRelay("none"), wait=1)
check("번호가 3번 다 안 오면 실패 - '인증번호를 3번 받지 못했습니다'", not ok and rp.otp.opened == 3
      and "인증번호를 3번 받지 못했습니다" in rp.results[-1][2] and rp.otp.closed >= 1, rp.results[-1:])

ok, rp, lines = replay("wrong", FakeRelay("wrong"))
check("사이트가 3번 다 거절하면 실패 - '사이트가 인증번호를 3번 거절했습니다'", not ok and rp.otp.opened == 3
      and "3번 거절" in rp.results[-1][2], rp.results[-1:])

ok, rp, lines = replay("no_relay", None)
check("인증 휴대폰이 없으면 그 단계에서 까닭과 함께 멈춘다", not ok and "인증 휴대폰" in rp.results[-1][2], rp.results[-1:])

srv.shutdown()
print("실패:", fails if fails else "없음")
sys.exit(1 if fails else 0)
