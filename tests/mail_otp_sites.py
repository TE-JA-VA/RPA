# -*- coding: utf-8 -*-
"""메일 2차인증 시험용 가짜 쇼핑몰(A, http://127.0.0.1:포트/a/…) + 가짜 메일함(B, http://localhost:포트/mail/…) - 한 서버.
A 와 B 는 호스트가 달라 서로 다른 사이트로 보인다 (메일 계정 구분). start() → (A 주소, B 주소, 상태).
  A: /a/login → /a/verify ([인증 메일 보내기] → 번호 칸·[확인], 또는 링크 방식이면 [인증 완료]) → /a/done
  B: /mail/login → (/mail/mfa - 상태가 켜면, 기록에 없던 확인 화면) → /mail/list (새 메일이 위) → /mail/read?id=
"""
import html
import json
import random
import string
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class State:
    def __init__(self):
        self.reset()

    def reset(self, mode="code"):
        self.mode = mode                  # "code" 번호 / "link" 인증 링크
        self.mails = []                   # {id, subject, at(초), code, token} - 받은 시각 순
        self.codes, self.tokens = [], []  # A 가 보낸 것 (마지막 것만 맞다)
        self.confirmed = False
        self.delay, self.never = 0.0, False
        self.mfa_on_mailbox, self.show_time, self.subject_with_code, self.alnum = False, True, False, False
        self.bad_links = False            # 링크를 눌러도 늘 '만료' (링크로 3번 실패)
        self.sent = 0
        for i, subj in enumerate(("[공지] 서비스 점검 안내", "주문하신 상품이 발송되었습니다")):   # 상관없는 메일 (목록 줄 알아보기에 두 줄 이상)
            self.mails.append({"id": i + 1, "at": time.time() - 86400 * (i + 1), "code": "", "token": "", "subject": subj})

    def _code(self):
        if self.alnum:
            return "".join(random.choice(string.ascii_uppercase) for _ in range(4)) + f"{random.randint(0, 9999):04d}"
        return f"{random.randint(0, 999999):06d}"

    def _deliver(self, code, token, at):
        mid = len(self.mails) + 1
        self.mails.append({"id": mid, "at": at, "code": code, "token": token,
                           "subject": "[가짜몰] 인증번호 안내" + (f" [{code}]" if self.subject_with_code and code else "")})

    def send(self):
        """A 의 [인증 메일 보내기] - 새 번호(또는 표)를 만들고 delay 초 뒤 메일함에 넣는다 (never 면 안 넣는다)."""
        self.sent += 1
        code, token = self._code(), "".join(random.choice(string.ascii_letters) for _ in range(16))
        self.codes.append(code)
        self.tokens.append(token)
        self.confirmed = False
        if self.never:
            return
        at = time.time()
        if self.delay:
            threading.Timer(self.delay, self._deliver, (code, token, at + self.delay)).start()
        else:
            self._deliver(code, token, at)

    def add_old(self, hours=2):
        """예전에 받은 인증 메일 (번호·표가 지금 것과 다르다) - 새 메일이 오기 전에는 목록 맨 위."""
        self._deliver(self._code(), "old" + str(random.randint(0, 9999)), time.time() - hours * 3600)


def start():
    st = State()
    port = []

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

        def _page(self, title, body):
            self._send(f"<!doctype html><meta charset='utf-8'><title>{title}</title>{body}")

        def do_POST(self):
            if self.path.startswith("/api/a/send"):
                st.send()
            self._send("{}", "application/json")

        def do_GET(self):
            path, _, q = self.path.partition("?")
            arg = dict(x.split("=", 1) for x in q.split("&") if "=" in x)
            a = f"http://127.0.0.1:{port[0]}"
            if path == "/a/login":
                return self._page("쇼핑몰 로그인", "<input id=uid placeholder='아이디'><input id=upw type=password placeholder='비밀번호'>"
                                  "<button onclick=\"location.href='/a/verify'\">로그인</button>")
            if path == "/a/verify":
                send = ("<button id=send onclick=\"fetch('/api/a/send',{method:'POST'}).then(()=>document.getElementById('msg')"
                        ".textContent='보냈습니다')\">인증 메일 보내기</button><p id=msg></p>")
                if st.mode == "link":
                    return self._page("메일 인증", send + "<button onclick=\"fetch('/api/a/state').then(r=>r.json()).then(j=>{"
                                      "if(j.ok)location.href='/a/done';else alert('인증이 완료되지 않았습니다. 메일의 링크를 눌러 주십시오.')})\">"
                                      "인증 완료</button>")
                return self._page("메일 인증", send + "<input id=otp placeholder='인증번호' autocomplete=off>"
                                  "<button onclick=\"fetch('/api/a/check?c='+encodeURIComponent(document.getElementById('otp').value))"
                                  ".then(r=>r.json()).then(j=>{if(j.ok)location.href='/a/done';else{alert('인증번호가 일치하지 않습니다.');"
                                  "document.getElementById('otp').value=''}})\">확인</button>")
            if path == "/api/a/check":
                return self._send(json.dumps({"ok": bool(st.codes) and arg.get("c") == st.codes[-1]}), "application/json")
            if path == "/api/a/state":
                return self._send(json.dumps({"ok": st.confirmed}), "application/json")
            if path == "/a/confirm":
                st.confirmed = not st.bad_links and bool(st.tokens) and arg.get("t") == st.tokens[-1]
                return self._page("인증", "<p>인증되었습니다.</p>" if st.confirmed else "<p>만료된 링크입니다.</p>")
            if path == "/a/done":
                return self._page("주문 관리", "<h1>주문 관리</h1><button>주문 엑셀</button>")
            if path == "/mail/login":
                nxt = "/mail/mfa" if st.mfa_on_mailbox else "/mail/list"
                return self._page("메일 로그인", "<input id=mid placeholder='메일 아이디'><input id=mpw type=password placeholder='메일 비밀번호'>"
                                  f"<button onclick=\"location.href='{nxt}'\">로그인</button>")
            if path == "/mail/mfa":
                return self._page("새 기기 확인", "<p>새 기기에서 로그인하였습니다. 휴대폰으로 받은 번호를 입력하여 주십시오.</p><input placeholder='확인 번호'>")
            if path == "/mail/list":
                rows = sorted(st.mails, key=lambda m: -m["at"])         # 실제 메일함처럼 받은 시각 최신순
                lis = "".join(
                    f"<li><a href='/mail/read?id={m['id']}'><span class=subj>{html.escape(m['subject'])}</span>"
                    + (f" <span class=time>{time.strftime('%H:%M', time.localtime(m['at']))}</span>" if st.show_time else "")
                    + "</a></li>" for m in rows)
                return self._page("받은 메일함", f"<button id=refresh onclick='location.reload()'>새로 고침</button><ul class=mails>{lis}</ul>")
            if path == "/mail/read":
                m = next((x for x in st.mails if str(x["id"]) == arg.get("id")), None)
                if m is None:
                    return self._page("메일", "<p>없는 메일입니다.</p>")
                if st.mode == "link":
                    return self._page("메일", f"<h2>{html.escape(m['subject'])}</h2><p>아래 링크를 눌러 인증을 마쳐 주십시오.</p>"
                                      f"<a href='{a}/a/confirm?t={m['token']}' target='_blank'>인증하기</a>")
                return self._page("메일", f"<h2>{html.escape(m['subject'])}</h2><p>인증번호는 <b id=code>{m['code']}</b> 입니다.</p>")
            self._page(path, f"<h1>{path}</h1>")

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    port.append(srv.server_address[1])
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{port[0]}", f"http://localhost:{port[0]}", st
