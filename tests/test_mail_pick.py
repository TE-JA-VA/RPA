# -*- coding: utf-8 -*-
"""메일 고르기 (사용자 2026-10-14) - 제목이 정한 글자(기본 '>>>')로 시작하는 메일마다 열어 첨부를 받는다.

가짜 메일함 (비즈메카처럼 Map 을 바꿔치기하고, 메일을 열면 목록 대신 본문이 보이고 뒤로 가면 목록):
  기록: '>>> 주문 A' 를 열어 첨부(메일마다 이름이 다름)를 받는다 → 그 누르기를 '메일 고르기' 로
  기억: 기록할 때 보이던 '>>>' 메일(A·C)은 처리한 것으로 → 새로 온 D 만 받는다 → 다시 돌리면 대상 없음
  미리보기: 기억과 상관없이 1통, 한 번에 최대 수, 시작 글자 바꾸기, 받기 단계가 없는 기록
    .venv\\Scripts\\python.exe tests\\test_mail_pick.py
"""
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import web_replay as rec  # noqa: E402

MAILS = [("k1", ">>> 주문 A"), ("k2", "공지사항"), ("k3", ">>> 주문 C")]
PAGE = """<!doctype html><meta charset="utf-8"><title>메일</title>
<script>Map = function() { this.map = new Object(); }; Map.prototype = { put: function(k, v) { this.map[k] = v; } };</script>
<style>li.m_data{cursor:pointer;padding:6px} li.unread{font-weight:bold} #view{display:none}</style>
<ul id="list">__ROWS__</ul>
<div id="view"><h3 id="vt"></h3><div class="att"><a href="javascript:;" id="att" onclick="location.href='/download?k=' + this.dataset.k"></a></div></div>
<script>
function show() { const m = /ukey=(\\w+)/.exec(location.hash); document.getElementById('list').style.display = m ? 'none' : 'block';
  document.getElementById('view').style.display = m ? 'block' : 'none';
  if (m) { const li = document.querySelector('li[data-key=' + m[1] + ']'); document.getElementById('vt').textContent = li.querySelector('.m_subject').textContent;
    const a = document.getElementById('att'); a.dataset.k = m[1]; a.textContent = 'file_' + m[1] + '.xlsx (3 KB)'; } }
window.addEventListener('hashchange', show); show();
</script>"""


MARKS = {}        # key → 제목 칸 앞에 붙는 것 (비즈메카: 아이콘·숨은 글자 span.blind '중요'·'전달')


def rows():
    return "".join(f'<li class="m_data unread" data-key="{k}" onclick="location.hash=\'act=VIEW&ukey={k}\'">'
                   f'<span class="m_write">보낸이</span> <p class="m_subject">{MARKS.get(k, "")}{t}</p></li>' for k, t in MAILS)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        path, _, q = self.path.partition("?")
        if path == "/download":
            b = b"PK\x03\x04" + q.encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition", f"attachment; filename=file_{q.split('=')[1]}.xlsx")
        else:
            b = PAGE.replace("__ROWS__", rows()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)


srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"
OUT = tempfile.mkdtemp(prefix="mail_pick_")
fails = []


def check(name, ok, detail=""):
    print(("통과 " if ok else "실패 ") + name + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


def human(page):
    page.wait_for_timeout(500)
    page.click("li[data-key=k1] p.m_subject")
    page.wait_for_timeout(500)
    with page.expect_download():
        page.click("#att")
    page.wait_for_timeout(500)


r = rec.record(BASE + "/mail", os.path.join(OUT, "rec.json"), headless=True, human=human)
steps = r["steps"]
print("--- 기록: " + " / ".join(rec.describe(s) for s in steps))
i = next((n for n, s in enumerate(steps) if s["kind"] == "click" and s.get("row")), None)
check("메일 줄 누르기에 목록 줄 정보가 붙는다 (같은 모양의 줄·기록 때 보이던 줄)", i is not None
      and steps[i]["row"]["sel"] == "li.m_data" and steps[i]["row"]["key"] == "k1"
      and [x["k"] for x in steps[i]["row"]["list"]] == ["k1", "k2", "k3"], steps[i].get("row") if i is not None else steps)
check("받기 단계가 없으면 묶음이 없다 (저장을 막는 데 쓴다)", rec.pick_body(steps[:i + 1], i) is None)
rec.set_pick(steps, i, ">>>")
check("설정한 줄의 설명", rec.describe(steps[i]) == "제목이 '>>>' 로 시작하는 메일마다 ↓", rec.describe(steps[i]))
end = rec.pick_body(steps, i)
check("묶음은 받기 단계까지", end is not None and steps[end].get("download"), end)
seed = rec.pick_seed(steps[i])
check("기록할 때 보이던 '>>>' 메일 (A·C) 을 처리한 것으로", sorted(seed) == ["k1", "k3"], seed)

mem_path = os.path.join(OUT, "mem", "PRESET1.json")
mem = rec.MailMemory(mem_path)
mem.add_all(seed)
mem.save()
MAILS.insert(0, ("k4", ">>> 주문 D"))      # 새로 온 메일 (맨 위)


def replay(label, memory=None, preview=False):
    lines = []
    orig = rec.Replayer.__init__

    def init(self, *a, **kw):
        orig(self, *a, **kw)
        self.mail_memory, self.pick_preview = memory, preview
    rec.Replayer.__init__ = init
    try:
        ok, rp = rec.replay(r, {"ID": "", "PW": ""}, os.path.join(OUT, label), "013", log=lines.append, step_timeout=6)
    finally:
        rec.Replayer.__init__ = orig
    return ok, rp, lines


ok, rp, lines = replay("new", rec.MailMemory(mem_path))
check("새로 온 메일 D 만 받는다", ok and [os.path.basename(x) for x in rp.saved] == ["(013)file_k4.xlsx"], (rp.results[-2:], rp.saved))
check("로그: 고른 결과·메일마다", any("제목이 '>>>' 로 시작하는 메일 3통 중 새 메일 1통" in x for x in lines)
      and any("[1/1] 메일 열기: >>> 주문 D" in x for x in lines), [x for x in lines if "메일" in x])
check("받은 메일을 기억한다", "k4" in rec.MailMemory(mem_path).keys)

ok, rp, lines = replay("again", rec.MailMemory(mem_path))
check("다시 돌리면 대상 없음 (성공·받은 것 없음·no_target)", ok and not rp.saved and rp.no_target
      and any("받을 새 메일이 없습니다 (대상 없음)" in x for x in lines), (rp.results, lines[-3:]))

ok, rp, lines = replay("preview", rec.MailMemory(mem_path), preview=True)
check("미리보기는 기억과 상관없이 맞는 메일 1통 (맨 위)", ok and [os.path.basename(x) for x in rp.saved] == ["(013)file_k4.xlsx"], rp.saved)

MAILS.insert(0, ("k5", ">>> 주문 E"))
MAILS.insert(0, ("k6", ">>> 주문 F"))
rec.MAIL_PICK_MAX, old_max = 1, rec.MAIL_PICK_MAX
ok, rp, lines = replay("max", rec.MailMemory(mem_path))
rec.MAIL_PICK_MAX = old_max
check("한 번에 최대 수를 넘으면 그만큼만 받고 알린다", ok and len(rp.saved) == 1
      and any("한 번에 최대 1개까지 처리할 수 있습니다" in x for x in lines), (rp.saved, [x for x in lines if "최대" in x]))
ok, rp, lines = replay("rest", rec.MailMemory(mem_path))
check("나머지는 다음 실행 때 (둘째 메일로 돌아가 받는다)", ok and len(rp.saved) == 1 and rp.saved[0] != "", rp.saved)

MAILS.insert(0, ("k7", ">>> 주문 G"))
MAILS.insert(2, ("k8", ">>> 주문 H"))      # 사이에 다른 메일 (공지 아님 - 위치가 섞여도)
ok, rp, lines = replay("two", rec.MailMemory(mem_path))
check("한 번에 두 통 - 첫 메일을 받고 목록으로 돌아가 다음 메일", ok and sorted(os.path.basename(x) for x in rp.saved)
      == ["(013)file_k7.xlsx", "(013)file_k8.xlsx"] and any("[2/2] 메일 열기" in x for x in lines), (rp.saved, rp.results[-2:]))

MAILS.insert(0, ("k9", ">>> 주문 I"))
MARKS["k9"] = '<span class="ico_imp on"></span><span class="blind">중요</span><img alt="중요" src="data:,">'
MAILS.insert(0, ("k10", ">>> 주문 J"))
MARKS["k10"] = '<span class="blind">전달</span> '
MAILS.insert(0, ("k11", "＞＞＞ 주문 K"))      # 전각 꺾쇠 - 사람이 보기엔 같은 글자
ok, rp, lines = replay("marks", rec.MailMemory(mem_path))
check("중요·전달 표시(아이콘·숨은 글자)가 제목 칸 앞에 있어도 '>>>' 로 알아본다", ok and sorted(os.path.basename(x) for x in rp.saved)
      == ["(013)file_k10.xlsx", "(013)file_k11.xlsx", "(013)file_k9.xlsx"], (rp.saved, [x for x in lines if "메일" in x]))
check("한 메일이 중요 표시를 두 군데 가져도 제목 기억은 같은 메일 하나", rec.pick_seed({"pick": {"prefix": ">>>"}, "row": {"list": [
      {"k": "", "t": "중요 >>> 주문", "s": ">>> 주문"}]}}) == ["제목:>>> 주문"])

rec.set_pick(steps, i, "[긴급]")
ok, rp, lines = replay("prefix", rec.MailMemory(mem_path))
check("시작 글자를 바꾸면 그 글자로 고른다 (맞는 메일 없음 → 대상 없음)", ok and rp.no_target and not rp.saved, rp.results)
rec.set_pick(steps, i, None)
check("해제하면 보통 누르기로", "pick" not in steps[i] and rec.describe(steps[i]).startswith("'"), rec.describe(steps[i]))

m = rec.MailMemory(mem_path)
n = len(m.keys)
m.clear()
check("기억 지우기", n >= 4 and not rec.MailMemory(mem_path).keys, n)

srv.shutdown()
print("실패:", fails if fails else "없음")
sys.exit(1 if fails else 0)
