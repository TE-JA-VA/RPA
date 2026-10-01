# -*- coding: utf-8 -*-
"""[시험용 · 버리는 코드] 가짜 쇼핑몰 관리자 화면. 실제 쇼핑몰에서 흔한 함정을 일부러 넣었다.

  - 단추·칸의 id 가 접속할 때마다 새로 만들어진다 (검색 단추 #btnSearch 만 고정)
  - '로그인' 단추 앞에 '로그인 정책' 링크 (부분 일치로 찾으면 이걸 누른다)
  - 메뉴 주소에 접속마다 바뀌는 세션 값 (기록한 주소로 바로 가면 막힌다)
  - 마우스를 올려야 열리는 하위 메뉴
  - 가끔 뜨는 공지 레이어 (닫기 / 오늘 하루 보지 않기)
  - 주문 화면은 iframe 안
  - 기간 칸(오늘 날짜) + 오늘·어제·1주일 단추, 주문상태 고르기
  - 엑셀 요청 → 새 창에서 다운로드 사유 + 확인 알림창 → 목록에 '생성 중' 이 몇 초 뒤 '다운로드' 로
    (어제 받은 옛 파일도 목록에 있다 - 너무 일찍 누르면 옛 파일을 받는다)

손으로 해 볼 때:  python fake_mall.py [--port 8800] [--notice on|off|random]
아이디 seller01 / 비밀번호 pw1234
"""
import argparse
import datetime
import json
import random
import secrets
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

USER, PASSWORD = "seller01", "pw1234"
READY_SECONDS = 3.0


def rid(prefix="x"):
    return f"{prefix}_{secrets.token_hex(3)}"


class Mall:
    def __init__(self, today, notice="random"):
        self.today = today
        self.notice = notice          # True / False / "random"
        self.sid = None
        self.logins, self.searches, self.downloads, self.ship_downloads = [], [], [], []
        y = (today - datetime.timedelta(days=1)).isoformat()
        self.requests = [   # 어제 받은 옛 파일 둘 (목록 아래에 깔린다)
            {"id": 1, "at": f"{y} 17:40", "range": f"{y}~{y}", "ready_at": 0, "reason": "옛 요청"},
            {"id": 2, "at": f"{y} 18:05", "range": f"{y}~{y}", "ready_at": 0, "reason": "옛 요청"},
        ]
        self.last_search = None
        self.list_delay = 0.0         # 다운로드 목록 응답을 늦춘다 (느린 사이트·바쁜 PC 흉내)

    def show_notice(self):
        return random.random() < 0.5 if self.notice == "random" else bool(self.notice)


LOGIN = """<!doctype html><meta charset="utf-8"><title>셀러오피스 로그인</title>
<style>body{{font-family:sans-serif;margin:40px}} .box{{width:320px}} input{{display:block;margin:6px 0;width:100%;padding:6px}}</style>
<div class="box"><h2>셀러오피스</h2>
<input id="{a}" type="text" placeholder="아이디" autocomplete="off">
<input id="{b}" type="password" placeholder="비밀번호" onkeydown="if(event.key==='Enter')login()">
<p><a href="#" id="{c}" onclick="alert('로그인 정책: 비밀번호는 90일마다 바꿉니다');return false">로그인 정책</a></p>
<button id="{d}" type="button" onclick="login()">로그인</button>
<p id="msg"></p></div>
<script>
function login(){{
  const [u,p]=document.querySelectorAll('input');
  fetch('/api/login',{{method:'POST',body:JSON.stringify({{id:u.value,pw:p.value}})}})
   .then(r=>r.json()).then(j=>{{ if(j.ok) location.href='/main?sid='+j.sid; else document.getElementById('msg').textContent='아이디 또는 비밀번호가 틀립니다'; }});
}}
</script>"""

MAIN = """<!doctype html><meta charset="utf-8"><title>셀러오피스</title>
<style>
 body{{font-family:sans-serif;margin:0}} .top{{background:#234;color:#fff;padding:10px}}
 .gnb{{list-style:none;margin:0;padding:0;display:flex;background:#eee}} .gnb>li{{position:relative;padding:10px 18px}}
 .gnb .sub{{display:none;position:absolute;left:0;top:100%;background:#fff;border:1px solid #ccc;list-style:none;padding:6px;margin:0;min-width:120px;z-index:5}}
 .gnb>li:hover .sub{{display:block}} .sub li{{padding:6px}}
 iframe{{width:100%;height:640px;border:0}}
 .layer{{position:fixed;left:0;top:0;right:0;bottom:0;background:rgba(0,0,0,.4);z-index:100}}
 .layer .in{{background:#fff;width:360px;margin:120px auto;padding:20px}}
</style>
<div class="top">셀러오피스 · {user}</div>
<ul class="gnb">
 <li><a href="#" id="{m1}">상품관리</a><ul class="sub"><li><a href="/goods?sid={sid}" target="content" id="{s1}">상품조회</a></li></ul></li>
 <li><a href="#" id="{m2}">주문관리</a><ul class="sub"><li><a href="/orders?sid={sid}" target="content" id="{s2}">발송처리</a></li><li><a href="/goods?sid={sid}" target="content" id="{s3}">취소관리</a></li></ul></li>
 <li><a href="#" id="{m3}">정산관리</a></li>
 <li><a href="#" id="{m4}" class="lazy">배송관리</a></li>
</ul>
<iframe name="content" id="{f}" src="/home?sid={sid}"></iframe>
<div id="portal"></div>
{notice}
<script>
// 요즘 방식 메뉴: 마우스를 올리는 순간 하위 메뉴를 새로 만들어 화면 다른 곳(portal)에 붙이고, 떼면 지운다
const trig = document.querySelector('a.lazy');
let menu = null, hideT = null;
function openMenu() {{ clearTimeout(hideT); if (menu) return; const r = trig.getBoundingClientRect();
  menu = document.createElement('div');
  menu.style.cssText = 'position:fixed;left:' + r.left + 'px;top:' + (r.bottom + 6) + 'px;background:#fff;border:1px solid #999;padding:8px;z-index:50';
  menu.innerHTML = '<a href="/ship?sid={sid}" target="content">송장전송</a>';
  menu.addEventListener('mouseenter', () => clearTimeout(hideT));
  menu.addEventListener('mouseleave', closeLater);
  document.getElementById('portal').appendChild(menu); }}
function closeLater() {{ hideT = setTimeout(() => {{ if (menu) {{ menu.remove(); menu = null; }} }}, 300); }}
trig.addEventListener('mouseenter', openMenu); trig.addEventListener('mouseleave', closeLater);
</script>"""

SHIP = """<!doctype html><meta charset="utf-8"><body style="font-family:sans-serif;padding:12px">
<h3>송장전송</h3><p>오늘 보낼 송장 2건</p>
<button type="button" id="{a}" onclick="location.href='/shipfile?sid={sid}'">송장 엑셀 받기</button>"""

NOTICE = """<div class="layer" id="{a}"><div class="in"><b>[공지] 추석 연휴 배송 안내</b><p>10월 3일~9일 택배사 휴무</p>
<button type="button" id="{b}" onclick="this.closest('.layer').remove()">오늘 하루 보지 않기</button>
<button type="button" id="{c}" onclick="this.closest('.layer').remove()">닫기</button></div></div>"""

HOME = """<!doctype html><meta charset="utf-8"><body style="font-family:sans-serif;padding:12px"><h3>대시보드</h3><p>오늘 신규 주문 3건</p>"""

ORDERS = """<!doctype html><meta charset="utf-8"><style>body{{font-family:sans-serif;padding:12px}} th{{text-align:left;padding:4px 8px}} td{{padding:4px 8px}}</style>
<h3>발송처리</h3>
<table class="search">
 <tr><th>주문상태</th><td><select id="{a}"><option value="">전체</option><option value="PAY">결제완료</option><option value="READY">발송대기</option><option value="SHIP">배송중</option></select></td></tr>
 <tr><th>기간</th><td><input id="{b}" class="date" value="{today}" size="10"> ~ <input id="{c}" class="date" value="{today}" size="10">
   <button type="button" id="{d}" onclick="range(0,0)">오늘</button> <button type="button" id="{e}" onclick="range(1,1)">어제</button> <button type="button" id="{g}" onclick="range(7,0)">1주일</button></td></tr>
</table>
<button id="btnSearch" type="button" onclick="search()">검색</button>
<p id="{h}" class="result"></p>
<button type="button" id="{i}" onclick="openReq()">엑셀 요청</button>
<h4>다운로드 목록 <button type="button" id="{k}" onclick="load()">새로고침</button></h4>
<table class="dl" id="{j}"><thead><tr><th>요청 시각</th><th>기간</th><th>상태</th><th></th></tr></thead><tbody></tbody></table>
<script>
const TODAY='{today}', SID='{sid}';
function fmt(d){{return d.toISOString().slice(0,10)}}
function range(a,b){{ const t=new Date(TODAY+'T00:00:00Z'); const d1=new Date(t), d2=new Date(t);
  d1.setUTCDate(t.getUTCDate()-a); d2.setUTCDate(t.getUTCDate()-b); const [i1,i2]=document.querySelectorAll('input.date'); i1.value=fmt(d1); i2.value=fmt(d2); }}
function search(){{ const [i1,i2]=document.querySelectorAll('input.date'); const st=document.querySelector('select').value;
  fetch('/api/search?sid='+SID,{{method:'POST',body:JSON.stringify({{status:st,d1:i1.value,d2:i2.value}})}}).then(r=>r.json())
   .then(j=>{{document.querySelector('.result').textContent='검색 결과 '+j.count+'건'}}) }}
function openReq(){{ window.open('/req?sid='+SID,'req','width=420,height=320') }}
function load(){{ fetch('/api/list?sid='+SID).then(r=>r.json()).then(j=>{{ document.querySelector('.dl tbody').innerHTML=j.items.map(it=>
  '<tr><td>'+it.at+'</td><td>'+it.range+'</td><td>'+(it.ready?'완료':'생성 중')+'</td><td>'+(it.ready?'<a href="/file/'+it.id+'?sid='+SID+'">다운로드</a>':'')+'</td></tr>').join('') }}) }}
load(); setInterval(load,1000);
</script>"""

REQ = """<!doctype html><meta charset="utf-8"><title>엑셀 다운로드 요청</title><body style="font-family:sans-serif;padding:12px">
<h4>다운로드 사유</h4><p>개인정보가 포함된 파일은 사유를 적어야 받을 수 있습니다.</p>
<textarea id="{a}" placeholder="사유를 입력하세요" rows="3" cols="40"></textarea><br>
<button type="button" id="{b}" onclick="send()">요청</button> <button type="button" id="{c}" onclick="window.close()">취소</button>
<script>
function send(){{ const r=document.querySelector('textarea').value.trim(); if(!r){{alert('사유를 입력하세요');return;}}
 if(!confirm('개인정보가 포함된 파일입니다. 요청하시겠습니까?')) return;
 fetch('/api/request?sid={sid}',{{method:'POST',body:JSON.stringify({{reason:r}})}}).then(()=>window.close()) }}
</script>"""


def _ids(n="abcdefghijk"):
    return {k: rid(k) for k in n}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    @property
    def mall(self):
        return self.server.mall

    def _send(self, body, status=200, ctype="text/html; charset=utf-8", headers=()):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _json(self, obj, headers=()):
        self._send(json.dumps(obj, ensure_ascii=False), ctype="application/json; charset=utf-8", headers=headers)

    def _authed(self, q):
        cookie = self.headers.get("Cookie") or ""
        sid = (q.get("sid") or [""])[0]
        return bool(sid) and sid == self.mall.sid and f"sess={sid}" in cookie

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        m = self.mall
        if u.path in ("/", "/login"):
            return self._send(LOGIN.format(**_ids()))
        if not self._authed(q):
            return self._send("<meta charset='utf-8'><h3>세션이 만료되었습니다. 다시 로그인하세요.</h3>", 403)
        sid = m.sid
        if u.path == "/main":
            notice = NOTICE.format(**_ids()) if m.show_notice() else ""
            return self._send(MAIN.format(user=USER, sid=sid, notice=notice, f=rid("f"),
                                          **{k: rid(k) for k in ("m1", "m2", "m3", "m4", "s1", "s2", "s3")}))
        if u.path in ("/home", "/goods"):
            return self._send(HOME)
        if u.path == "/ship":
            return self._send(SHIP.format(sid=sid, **_ids()))
        if u.path == "/shipfile":
            m.ship_downloads.append(m.today.isoformat())
            name = urllib.parse.quote(f"송장목록_{m.today.isoformat()}.xlsx")
            return self._send(b"FAKE-XLSX ship", ctype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                              headers=[("Content-Disposition", f"attachment; filename=\"ship.xlsx\"; filename*=UTF-8''{name}")])
        if u.path == "/orders":
            return self._send(ORDERS.format(today=m.today.isoformat(), sid=sid, **_ids()))
        if u.path == "/req":
            return self._send(REQ.format(sid=sid, **_ids()))
        if u.path == "/api/list":
            time.sleep(m.list_delay)
            now = time.time()
            items = [{"id": r["id"], "at": r["at"], "range": r["range"], "ready": now >= r["ready_at"]}
                     for r in reversed(m.requests)]
            return self._json({"items": items})
        if u.path.startswith("/file/"):
            rq = next((r for r in m.requests if str(r["id"]) == u.path[6:]), None)
            if not rq or time.time() < rq["ready_at"]:
                return self._send("not ready", 404)
            m.downloads.append(rq["id"])
            name = f"주문목록_{rq['range'].replace('~', '_')}_{rq['id']}.xlsx"
            disp = f"attachment; filename=\"orders.xlsx\"; filename*=UTF-8''{urllib.parse.quote(name)}"
            return self._send(f"FAKE-XLSX request={rq['id']} range={rq['range']}".encode(),
                              ctype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                              headers=[("Content-Disposition", disp)])
        return self._send("not found", 404)

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        m = self.mall
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        if u.path == "/api/login":
            ok = body.get("id") == USER and body.get("pw") == PASSWORD
            m.logins.append((body.get("id"), ok))
            if not ok:
                return self._json({"ok": False})
            m.sid = secrets.token_hex(8)       # 접속마다 새 세션 값
            return self._json({"ok": True, "sid": m.sid}, headers=[("Set-Cookie", f"sess={m.sid}; Path=/")])
        if not self._authed(q):
            return self._json({"ok": False}, )
        if u.path == "/api/search":
            m.last_search = {"status": body.get("status"), "d1": body.get("d1"), "d2": body.get("d2")}
            m.searches.append(dict(m.last_search))
            return self._json({"count": 3})
        if u.path == "/api/request":
            s = m.last_search or {"d1": "?", "d2": "?"}
            m.requests.append({"id": len(m.requests) + 1, "at": time.strftime("%H:%M:%S"), "range": f"{s['d1']}~{s['d2']}",
                               "ready_at": time.time() + READY_SECONDS, "reason": body.get("reason")})
            return self._json({"ok": True})
        return self._json({"ok": False})


def start(today=None, notice="random", port=0):
    """서버를 띄운다. (서버, 주소, Mall) - 끝나면 server.shutdown()."""
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    srv.mall = Mall(today or datetime.date.today(), notice)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}", srv.mall


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8800)
    ap.add_argument("--notice", default="random", choices=("on", "off", "random"))
    a = ap.parse_args()
    srv, url, _ = start(notice={"on": True, "off": False}.get(a.notice, "random"), port=a.port)
    print(f"가짜 쇼핑몰: {url}/login  (아이디 {USER} / 비밀번호 {PASSWORD})  - 끝내려면 Ctrl+C")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        srv.shutdown()
