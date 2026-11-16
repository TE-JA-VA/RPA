# -*- coding: utf-8 -*-
"""기록과 다른 창에 뜬 대상을 찾아 이어 가기 (설계 2026-11-16) - 창은 뜨지 않는다 (headless).

가짜 쇼핑몰 서버에서 실제 기록기(Recorder)로 기록하고, '오늘은 사이트가 다르게 구는 날' 여러 가지로 재생한다.
서버가 진짜 단추와 엉뚱한 단추가 눌린 횟수를 센다 - 재생기가 '성공' 이라고 해도 엉뚱한 것을 눌렀으면 잡는다.
    .venv\\Scripts\\python.exe tests\\test_popup_relocate.py [경우 이름 앞부분, 쉼표로 여럿]
"""
import datetime
import json
import os
import sys
import tempfile
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from playwright.sync_api import sync_playwright  # noqa: E402

import web_replay as rec  # noqa: E402

DAY = datetime.date(2026, 11, 16)
MODE, HITS = {}, []
BASE_MODE = {"login": [], "orders": [], "alert": False, "cover": "", "event_fake": "", "old_rows": 1, "new_id": "n1",
             "main_fake": False, "main_icon": False, "frames": 0}   # 처음 창에: 같은 이름 단추 / 글자 없는 단추 / 안쪽 틀 n개   # new_id: 새 파일의 주소 (날마다 다르다)
fails = []


def check(name, ok, detail=""):
    print(f"  [{'통과' if ok else '실패'}] {name}" + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


MAIN = """<!doctype html><meta charset=utf-8><title>가짜몰</title>
<a href="#" id="login">로그인</a> <a href="#" id="orders">주문관리</a> <a href="#" id="ok">확인</a>
__EXTRA__<div id="box"></div>
<script>
const M = __MODE__;
const ORD = '<button onclick="fetch(\\'/hit?what=excel\\').then(() => { document.title = \\'받음\\'; })">엑셀받기</button>';
document.getElementById('login').onclick = (e) => { e.preventDefault(); if (M.alert) alert('비밀번호 변경 안내');
  for (const [path, ms] of M.login) setTimeout(() => window.open(path), ms); };
document.getElementById('orders').onclick = (e) => { e.preventDefault();
  for (const a of M.orders) {
    if (a[0] === 'popup') setTimeout(() => window.open(a[1]), a[2]);
    if (a[0] === 'layer') document.getElementById('box').innerHTML = ORD;
    if (a[0] === 'iframe') document.getElementById('box').innerHTML = '<iframe name="inner" src="/orders" width="400" height="200"></iframe>';
    if (a[0] === 'nav') location.href = '/orders';
    if (a[0] === 'alert') alert('기간을 선택하세요');
  } };
document.getElementById('ok').onclick = (e) => { e.preventDefault(); fetch('/hit?what=confirm'); };
if (M.cover) { const d = document.createElement('div'); d.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:9';
  d.innerHTML = '<div style="background:#fff;margin:40px;padding:20px">공지사항 <button>' + M.cover + '</button></div>';
  d.querySelector('button').onclick = () => d.remove(); document.body.append(d); }
</script>"""
ORDERS = ("<!doctype html><meta charset=utf-8><title>주문</title>"
          "<button onclick=\"fetch('/hit?what=excel').then(() => { document.title = '받음'; })\">엑셀받기</button>")
NOTICE = "<!doctype html><meta charset=utf-8><title>공지</title><p>오늘의 공지</p><button onclick='window.close()'>닫기</button>"
DL = "<!doctype html><meta charset=utf-8><title>받기</title><a href='/file?which=excel'>엑셀받기</a>"
ROW = "<tr><td><a href='/file?which={which}'>다운로드</a></td></tr>"      # 줄마다 링크 주소가 다르다 (실제 쇼핑몰·fake_mall 과 같이)
LIST = """<!doctype html><meta charset=utf-8><title>받기 목록</title>
<button onclick="add()">요청</button>
<table><tbody id="rows">__OLD__</tbody></table>
<script>function add() { setTimeout(() => {      // 실제 쇼핑몰처럼 서버에 다녀온 뒤에 줄이 생긴다 (누르는 순간에 그리면 기록기가 '요청 뒤에 생긴 것' 으로 못 본다)
  const t = document.createElement('tbody'); t.innerHTML = __NEW__; document.getElementById('rows').append(t.firstChild); }, 300); }</script>"""
# 끼어든 창의 같은 이름 단추 (눌리면 서버가 wrong 으로 센다) - 재생기는 태그와 글자가 같아야 같은 것으로 본다
FAKES = {"": "", "button": "<button onclick=\"fetch('/hit?what=wrong')\">엑셀받기</button>",
         "a": "<a href='#' onclick=\"fetch('/hit?what=wrong'); return false;\">엑셀받기</a>",
         "confirm": "<a href='#' onclick=\"fetch('/hit?what=wrong'); return false;\">확인</a>",
         "close": "<button onclick=\"fetch('/hit?what=wrong')\">닫기</button>"}
WRONG_BTN = "<button onclick=\"fetch('/hit?what=wrong')\">엑셀받기</button>"
ICON = "<button style='width:40px;height:30px' onclick=\"fetch('/hit?what={what}')\"></button>"      # 글자 없는 단추


class Shop(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        headers = [("Content-Type", "text/html; charset=utf-8")]
        if u.path == "/hit":
            HITS.append(q.get("what", ["?"])[0])
            body = "ok"
        elif u.path == "/file":
            which = q.get("which", ["?"])[0]
            HITS.append(f"file:{which}")
            body = f"주문번호,상품\n1,{which}\n"
            headers = [("Content-Type", "text/csv"), ("Content-Disposition", f"attachment; filename=\"orders_{which}.csv\"")]
        elif u.path == "/" and q.get("popup"):            # 처음 창과 경로가 같은 팝업 (?mode=... 하나로 다 처리하는 옛 관리자 사이트)
            body = ORDERS
        elif u.path == "/":
            extra = ((ICON.format(what="wrong") if MODE.get("main_icon") else "") + (WRONG_BTN if MODE.get("main_fake") else "")
                     + "".join("<iframe src='/blank' width='10' height='10'></iframe>" for _ in range(MODE.get("frames", 0))))
            body = MAIN.replace("__MODE__", json.dumps(MODE, ensure_ascii=False)).replace("__EXTRA__", extra)
        elif u.path == "/blank":
            body = "<!doctype html><meta charset=utf-8>"
        elif u.path == "/redirect":                         # 잠깐 다른 주소를 거쳐 뜨는 팝업
            body = "<!doctype html><meta charset=utf-8><script>setTimeout(() => { location.href = '/?popup=orders'; }, 800)</script>"
        elif u.path == "/selfclose":                        # 뜨자마자 스스로 닫히는 팝업
            body = "<!doctype html><meta charset=utf-8><script>setTimeout(() => window.close(), 300)</script>"
        elif u.path == "/notice2":                          # 닫기 글이 바뀐 공지
            body = "<!doctype html><meta charset=utf-8><title>공지</title><p>오늘의 공지</p><button onclick='window.close()'>오늘은 그만 보기</button>"
        elif u.path == "/orders_icon":
            body = "<!doctype html><meta charset=utf-8><title>주문</title>" + ICON.format(what="excel")
        elif u.path == "/orders":
            body = ORDERS
        elif u.path == "/notice":
            body = NOTICE
        elif u.path == "/dl":
            body = DL
        elif u.path == "/list":
            old = "".join(ROW.format(which=f"old{k}") for k in range(1, MODE.get("old_rows", 1) + 1))
            body = LIST.replace("__OLD__", old).replace("__NEW__", json.dumps(ROW.format(which=MODE.get("new_id", "n1"))))
        elif u.path == "/event":
            body = ("<!doctype html><meta charset=utf-8><title>이벤트</title><p>이벤트 안내 (기록에 없던 창)</p>"
                    + FAKES[MODE.get("event_fake", "")])
        else:
            self.send_response(404)
            self.end_headers()
            return
        data = body.encode("utf-8")
        self.send_response(200)
        for k, v in headers:
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def set_mode(**kw):
    MODE.clear()
    MODE.update(BASE_MODE)
    MODE.update(kw)
    HITS.clear()


def hclick(page, loc):
    """사람처럼 그 자리를 마우스로 누른다 (기록기는 사람이 한 것만 받는다)."""
    loc.wait_for(state="visible", timeout=10000)
    b = loc.bounding_box()
    page.mouse.click(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2)
    try:
        page.wait_for_timeout(250)
    except Exception:
        time.sleep(0.25)            # 누르자 닫힌 창 ([닫기])


def record(url, human):
    with sync_playwright() as p:
        b = rec.edge(p.chromium.launch, headless=True)
        ctx = b.new_context(accept_downloads=True)
        rr = rec.Recorder(ctx)
        page = ctx.new_page()
        page.goto(url)
        page.wait_for_timeout(300)
        human(ctx, page)
        page.wait_for_timeout(300)
        out = rec.finalize([dict(s) for s in rr.steps], DAY, url)
        b.close()
    return out


def popup(ctx, page, text):
    with ctx.expect_page() as pi:
        hclick(page, page.get_by_text(text, exact=True))
    pop = pi.value
    pop.wait_for_load_state()
    pop.wait_for_timeout(400)
    return pop


def close_notice(ctx, page):
    pop = popup(ctx, page, "로그인")
    with pop.expect_event("close"):
        hclick(pop, pop.get_by_role("button", name="닫기"))


def human_a(ctx, page):
    """기록 A: 로그인 → 공지 창 [닫기] → 주문관리 → (일하는 창) 엑셀받기 → 확인"""
    close_notice(ctx, page)
    work = popup(ctx, page, "주문관리")
    hclick(work, work.get_by_role("button", name="엑셀받기"))
    hclick(page, page.get_by_text("확인", exact=True))


def human_b(ctx, page):
    """기록 B: 로그인 한 번에 공지 창 + 일하는 창이 함께 뜬다 → 공지 [닫기] → (일하는 창) 엑셀받기 → 확인"""
    hclick(page, page.get_by_text("로그인", exact=True))
    for _ in range(40):
        if len(ctx.pages) == 3:
            break
        page.wait_for_timeout(100)
    notice = next(pg for pg in ctx.pages if "/notice" in pg.url)
    work = next(pg for pg in ctx.pages if "/orders" in pg.url)
    for pg in (notice, work):
        pg.wait_for_load_state()
        pg.wait_for_timeout(400)
    with notice.expect_event("close"):
        hclick(notice, notice.get_by_role("button", name="닫기"))
    hclick(work, work.get_by_role("button", name="엑셀받기"))
    hclick(page, page.get_by_text("확인", exact=True))


def human_f(ctx, page):
    """기록 F: 로그인 한 번에 공지 창 + 일하는 창, 일하는 창의 단추는 글자가 없다 (아이콘)"""
    hclick(page, page.get_by_text("로그인", exact=True))
    for _ in range(40):
        if len(ctx.pages) == 3:
            break
        page.wait_for_timeout(100)
    notice = next(pg for pg in ctx.pages if "/notice" in pg.url)
    work = next(pg for pg in ctx.pages if "/orders_icon" in pg.url)
    for pg in (notice, work):
        pg.wait_for_load_state()
        pg.wait_for_timeout(400)
    with notice.expect_event("close"):
        hclick(notice, notice.get_by_role("button", name="닫기"))
    hclick(work, work.locator("button"))
    hclick(page, page.get_by_text("확인", exact=True))


def human_c(ctx, page):
    """기록 C: 일하는 창의 [엑셀받기] 가 진짜 파일을 내려 준다"""
    close_notice(ctx, page)
    work = popup(ctx, page, "주문관리")
    with work.expect_download() as di:
        hclick(work, work.get_by_text("엑셀받기", exact=True))
    di.value.path()
    hclick(page, page.get_by_text("확인", exact=True))


def human_d(ctx, page):
    """기록 D: 일하는 창에서 [요청] 을 누르면 새 [다운로드] 줄이 생기고 그것을 받는다 (옛 줄도 있다)"""
    close_notice(ctx, page)
    work = popup(ctx, page, "주문관리")
    hclick(work, work.get_by_role("button", name="요청"))
    work.wait_for_function("document.querySelectorAll('#rows a').length === 2")
    with work.expect_download() as di:
        hclick(work, work.locator("#rows a").last)
    di.value.path()
    hclick(page, page.get_by_text("확인", exact=True))


def replay(record_obj, tune=None):
    logs = []
    with sync_playwright() as p:
        b = rec.edge(p.chromium.launch, headless=True)
        ctx = b.new_context(accept_downloads=True)
        r = rec.Replayer(ctx, record_obj, {}, tempfile.mkdtemp(prefix="rpa_relocate_"), "000", today=DAY, log=logs.append,
                         step_timeout=3, step_tries=2)
        if tune:
            tune(r)
        t0 = time.time()
        try:
            ok = r.run()
        except Exception as e:
            ok = False
            logs.append(f"예외: {type(e).__name__}: {e}")
        took = time.time() - t0
        try:
            ctx.pages[0].wait_for_timeout(400)      # 누른 것이 서버에 닿을 틈
        except Exception:
            time.sleep(0.4)
        b.close()
    return ok, r, took, logs


def judge(ok, results, hits):
    excel, wrong, conf = hits.count("excel"), hits.count("wrong"), hits.count("confirm")
    if wrong:
        return "잘못 누름" + (" (성공으로 보고)" if ok else "")
    if ok and excel == 1 and conf == 1:
        return "성공"
    if ok:
        return f"성공 보고인데 받기 {excel}회·확인 {conf}회"
    f = next((x for x in results if x[1] == "fail"), None)
    return f"실패 ({f[0]}단계 {str(f[2])[:40]})" if f else "실패 (중단)"


P = lambda path, ms=0: ["popup", path, ms]   # noqa: E731
A_BASE = dict(login=[["/notice", 0]], orders=[P("/orders")])
B_BASE = dict(login=[["/notice", 0], ["/orders", 200]])
INTRUDE = [P("/event"), P("/orders", 300)]
E_BASE = dict(A_BASE, orders=[P("/?popup=orders")], main_fake=True)
F_BASE = dict(login=[["/notice", 0], ["/orders_icon", 200]], main_icon=True)
# (이름, 기록, 오늘의 사이트, 맞는 결과, 결과 글에 있어야 할 말 {단계: 말})
CASES = [
    ("A1 기록대로", "A", A_BASE, "성공", {}),
    ("A2 공지가 안 뜬 날", "A", dict(A_BASE, login=[]), "성공", {}),
    ("A3 로그인 때 공지가 둘 (하나는 기록에 없던 것)", "A", dict(A_BASE, login=[["/notice", 0], ["/event", 200]]), "성공", {}),
    ("A4 주문관리 때 이벤트 창이 먼저 끼어듦", "A", dict(A_BASE, orders=INTRUDE), "성공", {4: "다른 창에서 찾음"}),
    ("A5 끼어든 창에 같은 이름 단추 [엑셀받기]", "A", dict(A_BASE, orders=INTRUDE, event_fake="button"), "성공", {4: "다른 창에서 찾음"}),
    ("A6 이벤트 창 먼저, 일하는 창은 5초 뒤", "A", dict(A_BASE, orders=[P("/event"), P("/orders", 5000)]), "성공", {4: "다른 창에서 찾음"}),
    ("A7 이벤트 창만 뜨고 일하는 창은 끝내 안 뜸", "A", dict(A_BASE, orders=[P("/event")]), "실패", {}),
    ("A8 끼어든 창이 둘, 일하는 창은 세 번째", "A", dict(A_BASE, orders=[P("/event"), P("/event?2", 200), P("/orders", 400)]), "성공",
     {4: "다른 창에서 찾음"}),
    ("A9 일하는 창이 두 번 뜸 (같은 창 중복)", "A", dict(A_BASE, orders=[P("/orders"), P("/orders", 200)]), "성공", {}),
    ("A10 팝업 대신 같은 창의 레이어로 열림", "A", dict(A_BASE, orders=[["layer"]]), "성공", {3: "새 창 대신 같은 창"}),
    ("A11 팝업 대신 같은 창의 안쪽 틀(iframe)로 열림", "A", dict(A_BASE, orders=[["iframe"]]), "성공",
     {3: "새 창 대신 같은 창", 4: "안쪽 틀에서 찾음"}),
    ("A12 팝업 대신 같은 창이 그 주소로 넘어감", "A", dict(A_BASE, orders=[["nav"]]), "실패", {}),
    ("A12b 위와 같은데 [확인] 이 있는 공지 창이 열려 있음 - 그 [확인] 을 누르면 안 된다", "A",
     dict(A_BASE, login=[["/notice", 0], ["/event", 200]], orders=[["nav"]], event_fake="confirm"), "실패", {}),
    ("A13 기록에 없던 레이어 공지가 화면을 가림 ([닫기])", "A", dict(A_BASE, cover="닫기"), "성공", {}),
    ("A14 가리는 레이어의 단추가 낯선 글 ([다음에 보기])", "A", dict(A_BASE, cover="다음에 보기"), "성공", {}),
    ("A15 로그인 때 알림창(alert)이 뜸", "A", dict(A_BASE, alert=True), "성공", {}),
    ("B1 기록대로 (로그인 한 번에 공지+일하는 창)", "B", B_BASE, "성공", {3: "다른 창에서 찾음"}),
    ("B2 두 창의 뜨는 순서가 뒤바뀜", "B", dict(login=[["/orders", 0], ["/notice", 200]]), "성공", {}),
    ("B3 공지 없이 일하는 창만", "B", dict(login=[["/orders", 0]]), "성공", {}),
    ("B4 공지 + 기록에 없던 이벤트 창 + 일하는 창", "B", dict(login=[["/notice", 0], ["/event", 100], ["/orders", 300]]), "성공", {}),
    ("B5 공지만 뜨고 일하는 창은 안 뜸", "B", dict(login=[["/notice", 0]]), "실패", {}),
    # 알려진 한계 (설계): 끼어든 창에 글자까지 같은 단추가 있고 진짜 창이 3초 넘게 늦거나 없으면 지금 재생기처럼 그 단추를 누른다.
    # 실제 프리셋에서는 그 단계가 파일 받기라 실패로 잡힌다 (D2)
    ("A16 (알려진 한계) 같은 이름 단추 + 일하는 창은 5초 뒤", "A",
     dict(A_BASE, orders=[P("/event"), P("/orders", 5000)], event_fake="button"), "잘못 누름", {}),
    ("A17 (알려진 한계) 같은 이름 단추만 있고 일하는 창은 안 뜸", "A", dict(A_BASE, orders=[P("/event")], event_fake="button"), "잘못 누름", {}),
    # 최종 검토 (2026-11-16): 창 고쳐 잡기가 예전에 없던 잘못 누름을 만들면 안 된다 - 예전에 분명히 실패하던 날은 그대로 실패
    ("A18 공지의 닫기 글이 바뀐 날 - 다른 창의 [닫기] 를 누르면 안 된다 (공지는 건너뛴다)", "A",
     dict(A_BASE, login=[["/notice2", 0], ["/event", 200]], event_fake="close"), "성공", {}),
    ("A19 A7 과 같은데 처음 창에 안쪽 틀이 8개 - 실패가 늦어지지 않는다", "A", dict(A_BASE, orders=[P("/event")], frames=8), "실패", {}),
    ("E0 기록대로 (팝업의 경로가 처음 창과 같고, 처음 창에 같은 이름 단추)", "E", E_BASE, "성공", {}),
    ("E1 팝업이 잠깐 다른 주소를 거쳐 뜸 - 경로가 같은 처음 창으로 옮기면 안 된다", "E", dict(E_BASE, orders=[P("/redirect")]), "성공", {}),
    ("E2 일하는 창이 스스로 닫힌 날 - 처음 창의 같은 이름 단추를 누르면 안 된다", "E", dict(E_BASE, orders=[P("/selfclose")]), "실패", {}),
    ("E3 팝업 대신 알림창만 뜬 날 - 처음 창에 원래 있던 같은 이름 단추로 넘어가면 안 된다", "E", dict(E_BASE, orders=[["alert"]]), "실패", {}),
    ("F0 기록대로 (글자 없는 단추, 한 클릭에 창 둘)", "F", F_BASE, "성공", {}),
    ("F1 글자 없는 단추: 일하는 창이 안 뜬 날 처음 창의 글자 없는 단추를 누르면 안 된다", "F", dict(F_BASE, login=[["/notice", 0]]), "실패", {}),
]

if __name__ == "__main__":
    only = [x for x in (sys.argv[1] if len(sys.argv) > 1 else "").split(",") if x]
    want = lambda name: not only or any(name.startswith(x + " ") or name == x for x in only)   # noqa: E731
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Shop)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    recs = {}
    print("기록 (실제 기록기)")
    for key, human, mode in (("A", human_a, A_BASE), ("B", human_b, B_BASE), ("C", human_c, dict(A_BASE, orders=[P("/dl")])),
                             ("D", human_d, dict(A_BASE, orders=[P("/list")])), ("E", human_a, E_BASE), ("F", human_f, F_BASE)):
        set_mode(**mode)
        recs[key] = record(url, human)
        print(f"  기록 {key}: " + " / ".join(f"창{s['page']} {rec.describe(s)}" for s in recs[key]["steps"]))
    a, b = recs["A"]["steps"], recs["B"]["steps"]
    check("기록 A: 창 0·1·0·2·0, 여는 창 1·2", [s["page"] for s in a] == [0, 1, 0, 2, 0] and [s.get("opens") for s in a] == [1, None, 2, None, None],
          str([(s["page"], s.get("opens")) for s in a]))
    check("기록 B: 한 클릭이 연 두 번째 창(2)에는 '여는 창' 표시가 없다 (기록기 - 재생기가 찾아 잡아야 한다)",
          [s["page"] for s in b] == [0, 1, 2, 0] and [s.get("opens") for s in b] == [1, None, None, None], str([(s["page"], s.get("opens")) for s in b]))
    d = recs["D"]["steps"]
    check("기록 D: 새로 생긴 [다운로드] 는 '요청 뒤에 새로 생긴 것' 으로 기록된다", d[-2].get("download") and d[-2].get("appearsAfter") == 3,
          str({k: v for k, v in d[-2].items() if k != "target"}))

    print("\n누르기 경우")
    for name, key, mode, expect, notes in CASES:
        if not want(name.split(" ")[0]):
            continue
        set_mode(**mode)
        ok, r, took, logs = replay(recs[key])
        hits = list(HITS)
        got = judge(ok, r.results, hits)
        hows = {i: how for i, state, how in r.results}
        good = got.startswith(expect) and (expect == "잘못 누름" or "wrong" not in hits)
        good = good and all(text in str(hows.get(i, "")) for i, text in notes.items())
        check(f"{name}  → {got}  ({took:.0f}초)", good, f"맞는 결과: {expect} {notes}, 서버={sorted(hits)}, 결과={r.results}, 로그={logs[-6:]}")
        if name.startswith(("A7 ", "A19 ")):       # 3초(주소 맞는 창 기다림) + 3초씩 2번 + 훑기 - 틀이 많아도 (최종 검토 5)
            check(f"  {name.split(' ')[0]}: 못 찾는 날의 실패가 늦어지지 않는다 ({took:.0f}초 < 14초)", took < 14)

    print("\n파일 받기 경우")
    if want("D1"):
        set_mode(**dict(A_BASE, orders=[P("/event"), P("/dl", 300)]))
        ok, r, took, logs = replay(recs["C"])
        check(f"D1 끼어든 창이 있어도 일하는 창에서 파일을 받는다 ({took:.0f}초)",
              ok and len(r.saved) == 1 and r.saved[0].endswith("orders_excel.csv") and HITS.count("file:excel") == 1,
              f"ok={ok} saved={r.saved} 서버={HITS} 결과={r.results}")
    if want("D2"):
        set_mode(**dict(A_BASE, orders=[P("/event")], event_fake="a"))
        ok, r, took, logs = replay(recs["C"], tune=lambda r: setattr(r, "download_timeout_ms", 4000))
        why = next((x[2] for x in r.results if x[1] == "fail"), "")
        check(f"D2 같은 이름 단추만 있는 창이면 파일이 안 와 실패로 잡힌다 - 성공으로 보고하지 않는다 ({took:.0f}초)",
              not ok and not r.saved and "파일 다운로드가 시작되지 않았습니다" in why, f"ok={ok} saved={r.saved} 결과={r.results}")
    for name, orders in (("D3", [P("/event"), P("/list", 300)]), ("D4", [P("/event"), P("/list", 5000)])):
        if want(name):
            set_mode(**dict(A_BASE, orders=orders, old_rows=3, new_id="n2"))
            ok, r, took, logs = replay(recs["D"])
            files = [h for h in HITS if h.startswith("file:")]
            check(f"{name} 창을 고쳐 잡아도 새로 생긴 파일만 받는다 - 옛 줄 셋이 있어도 ({took:.0f}초)",
                  ok and files == ["file:n2"] and len(r.saved) == 1, f"ok={ok} 받은 것={files} saved={r.saved} 결과={r.results} 로그={logs[-8:]}")
    if want("D5"):
        r = rec.Replayer(None, {"steps": []}, {}, tempfile.gettempdir(), "000", log=lambda m: None)
        r.loose, r.baseline = set(), {0: {"옛 창에서 잡은 기준"}}
        s = dict(d[-2], page=2)
        check("D5 기준이 이미 다른 창에서 잡힌 파일 받기 단계는 고쳐 잡지 않는다 (옛 파일 위험)", r._elsewhere(0, s, None) is None)

    srv.shutdown()
    print("\n실패:", fails if fails else "없음")
    sys.exit(1 if fails else 0)
