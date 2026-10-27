# -*- coding: utf-8 -*-
"""메일 고르기 (사용자 2026-10-14) - 제목이 정한 글자(기본 '>>>')로 시작하는 메일마다 열어 첨부를 받는다.

가짜 메일함 (비즈메카처럼 Map 을 바꿔치기하고, 메일을 열면 목록 대신 본문이 보이고 뒤로 가면 목록):
  기록: '>>> 주문 A' 를 열어 첨부(메일마다 이름이 다름)를 받는다 → 그 누르기를 '메일 고르기' 로
  기억: 기록할 때 보이던 '>>>' 메일(A·C)은 처리한 것으로 → 새로 온 D 만 받는다 → 다시 돌리면 대상 없음
  미리보기: 기억과 상관없이 1통, 한 번에 최대 수, 시작 글자 바꾸기, 받기 단계가 없는 기록
    .venv\\Scripts\\python.exe tests\\test_mail_pick.py
"""
import datetime
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import web_replay as rec  # noqa: E402
from fake_mall import xlsx_bytes  # noqa: E402

MAILS = [("k1", ">>> 주문 A"), ("k2", "공지사항"), ("k3", ">>> 주문 C")]
PAGE = """<!doctype html><meta charset="utf-8"><title>메일</title>
<script>Map = function() { this.map = new Object(); }; Map.prototype = { put: function(k, v) { this.map[k] = v; } };</script>
<style>li.m_data{cursor:pointer;padding:6px} li.unread{font-weight:bold} #view{display:none}</style>
<ul id="list">__ROWS__</ul>
<div id="view"><h3 id="vt"></h3><div class="att"><a href="javascript:;" id="att" onclick="location.href='/download?k=' + this.dataset.k"></a></div></div>
<script>
const ATT = document.querySelector('.att').innerHTML, NOATT = __NOATT__;
function show() { const m = /ukey=(\\w+)/.exec(location.hash); document.getElementById('list').style.display = m ? 'none' : 'block';
  document.getElementById('view').style.display = m ? 'block' : 'none';
  if (m && NOATT.includes(m[1])) { document.querySelector('.att').innerHTML = ''; document.getElementById('vt').textContent = 'no'; return; }
  if (m && !document.getElementById('att')) document.querySelector('.att').innerHTML = ATT;
  if (m) { const li = document.querySelector('li[data-key=' + m[1] + ']') || [...document.querySelectorAll('li.m_data')].find(l => l.getAttribute('onclick').includes('ukey=' + m[1] + "'")); document.getElementById('vt').textContent = li.querySelector('.m_subject').textContent;
    const a = document.getElementById('att'); a.dataset.k = m[1]; a.textContent = 'file_' + m[1] + '.xlsx (3 KB)'; } }
window.addEventListener('hashchange', show); show();
</script>"""


MARKS = {}        # key → 제목 칸 앞에 붙는 것 (비즈메카: 아이콘·숨은 글자 span.blind '중요'·'전달')


NOATT = []        # 첨부 없는 메일의 key (BugBuster M13)


KEYLESS = {}      # 켜면 네이버 메일처럼: 줄에 고유 표시가 없고, 제목 칸 앞에 숨은 글자 '메일 제목', 뒤에 받은 시각 (사용자 2026-10-20)


def rows():
    if KEYLESS:
        return "".join(f'<li class="m_data unread" onclick="location.hash=\'act=VIEW&ukey={k}\'">'
                       f'<span class="m_write">김창민</span> <p class="m_subject"><span class="blind">메일 제목</span>{t}</p>'
                       f' <span class="m_time">{KEYLESS.get(k, "")}</span></li>' for k, t in MAILS)
    return "".join(f'<li class="m_data unread" data-key="{k}" onclick="location.hash=\'act=VIEW&ukey={k}\'">'
                   f'<span class="m_write">보낸이</span> <p class="m_subject">{MARKS.get(k, "")}{t}</p></li>' for k, t in MAILS)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        path, _, q = self.path.partition("?")
        if path == "/download":
            b = xlsx_bytes(q)
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition", f"attachment; filename=file_{q.split('=')[1]}.xlsx")
        else:
            b = PAGE.replace("__ROWS__", rows()).replace("__NOATT__", json.dumps(NOATT)).encode("utf-8")
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
      and [x["k"] for x in steps[i]["row"]["mine"]] == ["k1"], steps[i].get("row") if i is not None else steps)
check("목록 줄 정보에 다른 줄의 글자를 담지 않는다 - 누른 줄과 위치만 (BugBuster I4)", "list" not in steps[i]["row"]
      and steps[i]["row"]["at"] == 0 and "공지사항" not in json.dumps(steps, ensure_ascii=False), steps[i]["row"])
check("받기 단계가 없으면 묶음이 없다 (저장을 막는 데 쓴다)", rec.pick_body(steps[:i + 1], i) is None)
check("메일 시작 문구로 '메일마다' 단계를 스스로 찾는다 (프리셋 칸 - 사용자 2026-10-14)", rec.auto_pick(steps, ">>>") == i
      and rec.auto_pick(steps, "[긴급]") is None and rec.auto_pick(steps, "") is None, rec.auto_pick(steps, ">>>"))
rec.set_pick(steps, i, ">>>")
check("설정한 줄의 설명", rec.describe(steps[i]) == "제목이 '>>>' 로 시작하는 메일마다 ↓", rec.describe(steps[i]))
end = rec.pick_body(steps, i)
check("묶음은 받기 단계까지", end is not None and steps[end].get("download"), end)
mem_path = os.path.join(OUT, "mem", "PRESET1.json")      # 기록 때 보이던 메일을 '이미 처리' 로 채우지 않는다 - 빈 기억에서 시작 (사용자 2026-10-20)
MAILS.insert(0, ("k4", ">>> 주문 D"))      # 새로 온 메일 (맨 위)


def replay(label, memory=None, preview=False, progress=None):
    lines = []
    orig = rec.Replayer.__init__

    def init(self, *a, **kw):
        orig(self, *a, **kw)
        self.mail_memory, self.pick_preview = memory, preview
        if progress is not None:
            self.progress = lambda *x: progress.append(x)
    rec.Replayer.__init__ = init
    try:
        ok, rp = rec.replay(r, {"ID": "", "PW": ""}, os.path.join(OUT, label), "013", log=lines.append, step_timeout=6, step_tries=1)
    finally:
        rec.Replayer.__init__ = orig
    return ok, rp, lines


ok, rp, lines = replay("new", rec.MailMemory(mem_path))
check("첫 실행은 기록 때 보이던 메일(A·C, 기록 중 연 A 포함)과 새로 온 D 를 모두 받는다 (사용자 2026-10-20)",
      ok and [os.path.basename(x) for x in rp.saved] == ["(013)file_k4.xlsx", "(013)file_k1.xlsx", "(013)file_k3.xlsx"], (rp.results[-2:], rp.saved))
check("로그: 고른 결과·메일마다", any("제목이 '>>>' 로 시작하는 메일 3통 중 새 메일 3통" in x for x in lines)
      and any("[1/3] 메일 열기: >>> 주문 D" in x for x in lines), [x for x in lines if "메일" in x])
check("받은 메일을 기억한다", {"k1", "k3", "k4"} <= set(rec.MailMemory(mem_path).keys))

ok, rp, lines = replay("again", rec.MailMemory(mem_path))
check("다시 돌리면 대상 없음 (성공·받은 것 없음·no_target)", ok and not rp.saved and rp.no_target
      and any("다운로드할 새 메일이 없습니다. (대상 없음)" in x for x in lines), (rp.results, lines[-3:]))

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

rec.set_pick(steps, i, "[긴급]")
ok, rp, lines = replay("prefix", rec.MailMemory(mem_path))
check("시작 글자를 바꾸면 그 글자로 고른다 (맞는 메일 없음 → 대상 없음)", ok and rp.no_target and not rp.saved, rp.results)
rec.set_pick(steps, i, None)
check("해제하면 보통 누르기로", "pick" not in steps[i] and rec.describe(steps[i]).startswith("'"), rec.describe(steps[i]))

m = rec.MailMemory(mem_path)
n = len(m.keys)
m.clear()
check("기억 지우기", n >= 4 and not rec.MailMemory(mem_path).keys, n)

# 첨부 없는 '>>>' 메일 (BugBuster M13·L7·I5)
rec.set_pick(steps, i, ">>>")
MAILS[:] = [("m1", ">>> 첨부 없음"), ("m2", ">>> 주문 M")]
NOATT[:] = ["m1"]
mem3 = os.path.join(OUT, "mem", "PRESET3.json")
prog = []
ok, rp, lines = replay("noatt", rec.MailMemory(mem3), progress=prog)
check("M13: 첨부 없는 메일은 그 메일만 건너뛰고 기억, 다음 메일은 받는다", ok and [os.path.basename(x) for x in rp.saved] == ["(013)file_m2.xlsx"]
      and any("건너뜀(첨부 없음)" in x for x in lines) and {"m1", "m2"} <= set(rec.MailMemory(mem3).keys), (rp.results, rp.saved, lines[-6:]))
last = {}
for no, state, how in prog:
    last[no] = state
check("L7: 메일 고르기·묶음 단계의 진행 표시가 끝난다 (마지막 표시가 run 이 아니다)", len(last) == len(steps)
      and all(v in ("ok", "skip") for v in last.values()), last)
check("I5: 화면 마지막 줄까지 새 메일이면 '다음 쪽에 더 있을 수 있습니다'", any(rec.MAIL_MORE in x for x in lines)
      and rec.MAIL_MORE in next(h for n_, st_, h in rp.results if n_ == i + 1), rp.results)
MAILS[:] = [("m3", ">>> 첨부 없음 2"), ("m2", ">>> 주문 M")]
NOATT[:] = ["m3"]
prog = []
ok, rp, lines = replay("noatt_only", rec.MailMemory(mem3), progress=prog)
check("M13: 받은 메일이 하나도 없으면 실패, 기억하지 않는다 (사이트가 바뀌었을 수 있다)", not ok and "m3" not in rec.MailMemory(mem3).keys
      and not any(rec.MAIL_MORE in x for x in lines), (rp.results, lines[-4:]))
check("L7: 실패 번호는 묶음 안의 실제 단계", rp.results[-1][:2] == (end + 1, "fail") and prog[-1][:2] == (end + 1, "fail"), (rp.results[-1], prog[-1:]))
NOATT[:] = []
rec.set_pick(steps, i, None)

# 네이버 메일처럼 줄에 고유 표시가 없는 목록 (사용자 2026-10-20): 저장 때 연 메일 제목은 숨은 글자 없이, 같은 제목 메일은 줄마다 따로
MAILS[:] = [("n1", "[창민사이트]"), ("n2", "[공통사이트]"), ("n3", "[창민사이트]")]
KEYLESS.update(n1="오후 01:57", n2="오후 01:57", n3="오후 01:57")      # n1·n3 은 보이는 줄 글자까지 같다


def human2(page):
    page.wait_for_timeout(500)
    page.locator("li.m_data").nth(0).locator("p.m_subject").click()
    page.wait_for_timeout(500)
    with page.expect_download():
        page.click("#att")
    page.wait_for_timeout(500)


r = rec.record(BASE + "/mail", os.path.join(OUT, "rec2.json"), headless=True, human=human2)
steps2 = r["steps"]
i2 = next((n for n, x in enumerate(steps2) if x["kind"] == "click" and x.get("row")), None)
row2 = steps2[i2]["row"] if i2 is not None else {}
check("고유 표시 없는 목록: 줄 key 는 비고 누른 줄 번호(at)를 남긴다, 누른 칸 글자에는 숨은 '메일 제목' 이 붙는다",
      row2.get("key") == "" and row2.get("at") == 0 and "메일 제목[창민사이트]" in steps2[i2]["target"]["text"],
      (row2.get("key"), row2.get("at"), steps2[i2].get("target", {}).get("text") if i2 is not None else None))
check("시작 문구 '[창민사이트' 로 그 단계를 찾는다 - 보이는 제목으로 (예전엔 '메일 제목[창민사이트]' 로 봐 저장을 막았다)",
      rec.auto_pick(steps2, "[창민사이트") == i2, rec.auto_pick(steps2, "[창민사이트"))
old = [dict(x, row={k: v for k, v in x["row"].items() if k != "at"}) if x.get("row") else x for x in steps2]
check("at 이 없는 옛 기록도 누른 칸 글자와 같은 줄의 보이는 제목으로 찾는다", rec.auto_pick(old, "[창민사이트") == i2)
D23 = datetime.date(2026, 10, 23)
check("줄 기억 표시: 고유 표시가 없으면 보이는 줄 글자(받은 시각은 날짜로), 똑같은 줄은 아래부터 몇 번째로 가른다",
      rec.row_ids([("", "t", "[창민사이트]", "김창민 [창민사이트] 오후 01:57"), ("k", "t", "x", "y"), ("", "t", "[창민사이트]", "김창민 [창민사이트] 오후 01:57")], D23)
      == ["줄:김창민 [창민사이트] 2026-10-23#2", "k", "줄:김창민 [창민사이트] 2026-10-23"])
day = lambda s, today=D23: rec.mail_day_line(s, today)   # noqa: E731
check("받은 때를 날짜로: 오늘은 시각, 다음 날은 날짜·어제로 보여도 같은 표시 (BugBuster K5)",
      day("a 13:57") == day("a 10.23", datetime.date(2026, 10, 24)) == day("a 어제 오후 01:57", datetime.date(2026, 10, 24))
      == day("a 2026.10.23 13:57") == day("a 10-23 (금)") == day("a 10월 23일") == day("a 3분 전") == "a 2026-10-23",
      [day("a 13:57"), day("a 10.23", datetime.date(2026, 10, 24)), day("a 어제 오후 01:57", datetime.date(2026, 10, 24))])
check("날짜가 아닌 숫자는 그대로, 연도 없는 12.31 을 1월에 보면 지난해",
      day("첨부 1.2MB 010-1234-5678 13.45") == "첨부 1.2MB 010-1234-5678 13.45"
      and day("a 12.31", datetime.date(2027, 1, 2)) == "a 2026-12-31", (day("첨부 1.2MB 010-1234-5678 13.45"),))
rec.set_pick(steps2, i2, "[창민사이트")
MAILS.insert(0, ("n4", "[창민사이트]"))
KEYLESS["n4"] = "오후 01:58"
mem2 = os.path.join(OUT, "mem", "PRESET2.json")
ok, rp, lines = replay("keyless", rec.MailMemory(mem2))
check("같은 제목 메일 셋(n4·n1·n3)을 줄마다 따로 연다 - 예전엔 제목으로 찾아 첫 줄만 세 번",
      ok and [os.path.basename(x) for x in rp.saved] == ["(013)file_n4.xlsx", "(013)file_n1.xlsx", "(013)file_n3.xlsx"], (rp.saved, [x for x in lines if "메일" in x]))
ok, rp, lines = replay("keyless_again", rec.MailMemory(mem2))
check("다시 돌리면 셋 다 기억해 대상 없음", ok and rp.no_target and not rp.saved, (rp.saved, rp.results[-2:]))
times, today = dict(KEYLESS), datetime.date.today()
KEYLESS.update({k: f"{today.month:02d}.{today.day:02d} {v}" for k, v in times.items()})   # 자정이 지나 시각 대신 날짜로 보인다
ok, rp, lines = replay("keyless_nextday", rec.MailMemory(mem2))
check("받은 시각이 날짜로 바뀌어 보여도 같은 메일 - 대상 없음 (BugBuster K5)", ok and rp.no_target and not rp.saved, (rp.saved, rp.results[-2:]))
KEYLESS.update(times)
new_ids, rec.row_ids = rec.row_ids, lambda rows, today=None: rec.old_row_ids(rows)   # 옛 버전이 받은 기억
mem3 = os.path.join(OUT, "mem", "PRESET3.json")
ok, rp, lines = replay("keyless_oldver", rec.MailMemory(mem3))
rec.row_ids = new_ids
ok2, rp2, lines = replay("keyless_upgraded", rec.MailMemory(mem3))
check("옛 버전이 받아 기억한 메일은 업데이트 뒤에도 다시 받지 않는다",
      ok and len(rp.saved) == 3 and ok2 and rp2.no_target and not rp2.saved, (rp.saved, rp2.saved))

srv.shutdown()
print("실패:", fails if fails else "없음")
sys.exit(1 if fails else 0)
