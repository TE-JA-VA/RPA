# -*- coding: utf-8 -*-
"""기록·재생 엔진(web_replay) 시험 - 가짜 쇼핑몰(tests/fake_mall.py)에서 기록 → (다음 날) 재생 → 서버 기록으로 확인한다.

사람 역할은 화면 위치를 마우스로 누르고 키보드로 친다 (옵저버는 사람이 한 것만 받는다). 창은 뜨지 않는다.
    .venv\\Scripts\\python.exe tests\\test_web_replay.py
"""
import datetime
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import fake_mall  # noqa: E402
import web_replay as rec  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
OUT = tempfile.mkdtemp(prefix="rpa_replay_")   # 받은 파일·실패 사진 (저장소 밖)
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.join(OUT, "no_browsers")   # 배포판처럼 같이 싣는 브라우저가 없다 - 깔린 Edge 로만 뜬다
DAY = datetime.date(2026, 9, 30)
fails = []


def check(name, ok, detail=""):
    print(f"  [{'통과' if ok else '실패'}] {name}" + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


def hclick(page, loc):
    """사람처럼: 보일 때까지 기다렸다가 그 자리를 마우스로 누른다 (목록이 1초마다 다시 그려져 몇 번 다시 해 본다)."""
    for attempt in range(5):
        try:
            loc.wait_for(state="visible", timeout=10000)
            loc.scroll_into_view_if_needed(timeout=3000)
            b = loc.bounding_box()
            page.mouse.click(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2)
            return
        except Exception:
            if attempt == 4:
                raise
            page.wait_for_timeout(200)


def wait_new_ready(page, mall, fl):
    """사람은 목록에 새 줄이 '완료' 가 될 때까지 본다."""
    for _ in range(80):
        rows = fl.locator(".dl tbody tr")
        if rows.count() == len(mall.requests) and "완료" in rows.first.inner_text():
            return rows.first
        page.wait_for_timeout(250)
    raise RuntimeError("새 파일이 준비되지 않음")


def human(mall, notice, dates=False, enter_login=False, noise=False):
    def run(page):
        hclick(page, page.get_by_placeholder("아이디"))
        page.keyboard.type(fake_mall.USER, delay=15)
        hclick(page, page.get_by_placeholder("비밀번호"))
        page.keyboard.type(fake_mall.PASSWORD, delay=15)
        if enter_login:
            page.keyboard.press("Enter")
        else:
            hclick(page, page.get_by_role("button", name="로그인", exact=True))
        page.wait_for_url("**/main**")
        if notice:
            hclick(page, page.get_by_role("button", name="닫기", exact=True))
        page.get_by_role("link", name="주문관리", exact=True).hover()
        hclick(page, page.get_by_role("link", name="발송처리", exact=True))
        fl = page.frame_locator("iframe[name=content]")
        fl.locator("#btnSearch").wait_for()
        if noise:
            hclick(page, fl.locator("h3"))                 # 사람은 제목·표 칸·빈 곳도 누른다 (적히면 안 된다)
        fl.locator("select").focus()
        page.keyboard.press("ArrowDown")                   # 결제완료
        if not dates:
            page.keyboard.press("ArrowDown")               # 발송대기
            b = fl.get_by_role("button", name="1주일", exact=True).bounding_box()
            page.mouse.dblclick(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2)   # 더블클릭 → 한 단계
        else:
            for loc, d in ((fl.locator("input.date").nth(0), DAY - datetime.timedelta(days=1)),
                           (fl.locator("input.date").nth(1), DAY)):
                hclick(page, loc)
                page.keyboard.press("Control+A")
                page.keyboard.type(d.isoformat(), delay=15)
        hclick(page, fl.locator("#btnSearch"))
        fl.get_by_text("검색 결과").wait_for()
        with page.expect_popup() as pi:
            hclick(page, fl.get_by_role("button", name="엑셀 요청", exact=True))
        pop = pi.value
        pop.wait_for_load_state()
        hclick(pop, pop.get_by_placeholder("사유를 입력하세요"))
        pop.keyboard.type("주문 처리", delay=15)
        with pop.expect_event("close"):
            hclick(pop, pop.get_by_role("button", name="요청", exact=True))
        if noise:
            hclick(page, fl.locator(".dl tbody tr").first.locator("td").nth(2))   # 기다리며 '생성 중' 칸을 누른다
        row = wait_new_ready(page, mall, fl)
        if noise:
            hclick(page, fl.get_by_role("button", name="새로고침", exact=True))   # 다 된 뒤에 새로고침 (진짜 조작)
            hclick(page, row.locator("td").nth(2))                                # '완료' 칸
            page.mouse.click(700, 600)                                            # 빈 곳
        with page.expect_download() as di:
            hclick(page, row.get_by_role("link", name="다운로드"))
        di.value.path()
    return run


def replay_check(srv, url, rec_obj, day, notice, want, label, creds=None, step_timeout=30.0, list_delay=0.0):
    srv.mall = mall = fake_mall.Mall(day, notice)
    mall.list_delay = list_delay
    out_dir = os.path.join(OUT, label)
    print(f"--- 재생 {label}: {day} (공지 {'뜸' if notice else '안 뜸'})")
    ok, r = rec.replay(rec_obj, creds or {"ID": fake_mall.USER, "PW": fake_mall.PASSWORD}, out_dir, "012", today=day,
                       log=print, step_timeout=step_timeout)
    print(f"    {r.elapsed:.1f}초, 찾은 단서: " + ", ".join(sorted({h.split(',')[0] for _, st, h in r.results if st == 'ok'})))
    return ok, r, mall


def main():
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT, exist_ok=True)
    srv, url, _ = fake_mall.start(DAY, True)
    try:
        # ---------------- A: 단추로 기간 (1주일), 공지 뜬 날 기록 ----------------
        print("=== A. 기록 (공지 뜸, 로그인 단추, 1주일 단추)")
        srv.mall = mall = fake_mall.Mall(DAY, True)
        path_a = os.path.join(OUT, "rec_a.json")
        a = rec.record(url + "/login", path_a, headless=True, human=human(mall, True, noise=True), record_date=DAY,
                       sample_dir=os.path.join(OUT, "samples_a"))
        for i, s in enumerate(a["steps"], 1):
            print(f"    {i:2d}. {rec.describe(s)}")
        text = open(path_a, encoding="utf-8").read()
        check("기록에 비밀번호도 아이디도 없다", fake_mall.PASSWORD not in text and fake_mall.USER not in text)
        kinds = [s["kind"] for s in a["steps"]]
        check("단계: 아이디·비밀번호·로그인·공지 닫기·메뉴·고르기·1주일·검색·요청·사유·요청·새로고침·다운로드 (제목·표 칸·빈 곳 누름은 안 적힘)",
              kinds == ["fill", "secret", "click", "click", "click", "select", "click", "click", "click", "fill", "click",
                        "click", "click"], str(kinds))
        check("공지 닫기는 '떠 있을 때만'", any(s.get("optional") for s in a["steps"]))
        check("엑셀 요청이 새 창을 연다, 요청에 알림창, 마지막에 파일", a["steps"][8].get("opens") == 1
              and a["steps"][10].get("dialogs") and a["steps"][12].get("download"), json.dumps(a["steps"][8:], ensure_ascii=False)[:300])
        check("1주일 더블클릭은 한 단계", a["steps"][6].get("double") is True, str(a["steps"][6]))
        check("기록 때 파일도 받았다", mall.downloads == [3] and a["samples"], str(mall.downloads))
        check("다운로드는 '11단계(요청) 뒤에 새로 생긴 것' - 그 뒤 새로고침을 눌러도", a["steps"][12].get("appearsAfter") == 10,
              str([s.get("appearsAfter") for s in a["steps"]]))

        for day, notice, label, settle, delay in ((DAY + datetime.timedelta(days=1), False, "A1_다음날_공지없음", 3000, 0),
                                                  (DAY + datetime.timedelta(days=2), True, "A2_모레_공지뜸", 3000, 0),
                                                  (DAY + datetime.timedelta(days=3), False, "A3_기다림없이", 0, 0),
                                                  (DAY + datetime.timedelta(days=4), False, "A4_목록이늦게_기다림없이", 0, 1.2)):
            rec.SETTLE_MAX_MS = settle
            ok, r, m = replay_check(srv, url, a, day, notice, None, label, list_delay=delay)
            rec.SETTLE_MAX_MS = 3000
            check(f"{label}: 끝까지", ok, str(r.results[-1]))
            check(f"{label}: 로그인 한 번에 성공", m.logins == [(fake_mall.USER, True)], str(m.logins))
            want = {"status": "READY", "d1": (day - datetime.timedelta(days=7)).isoformat(), "d2": day.isoformat()}
            check(f"{label}: 검색 조건 (발송대기, 그날 기준 1주일)", m.searches[-1:] == [want], str(m.searches))
            check(f"{label}: 사유를 넣어 요청", m.requests[-1]["reason"] == "주문 처리", str(m.requests[-1]))
            check(f"{label}: 새로 만든 파일을 받았다 (옛 파일 아님)", m.downloads == [m.requests[-1]["id"]], str(m.downloads))
            names = [os.path.basename(x) for x in r.saved]
            check(f"{label}: 파일 이름 (012)… 로", len(names) == 1 and names[0].startswith("(012)주문목록_")
                  and day.isoformat() in names[0], str(names))

        # ---------------- A 에서 단계를 뺀 기록 (검토 창에서 공지 닫기·새로고침을 끈 것) ----------------
        d = rec.keep_steps(a, [i for i in range(len(a["steps"])) if i not in (3, 11)])
        check("단계를 빼면 뒤 번호도 따라간다 (다운로드는 이제 10단계 뒤)", len(d["steps"]) == 11
              and d["steps"][-1].get("appearsAfter") == 9, str([s.get("appearsAfter") for s in d["steps"]]))
        day = DAY + datetime.timedelta(days=4)
        ok, r, m = replay_check(srv, url, d, day, True, None, "D_단계뺀기록_공지뜸")
        check("D: 끝까지 (뺀 공지 닫기 대신 가로막힐 때 닫고)", ok, str(r.results[-1]))
        check("D: 새 파일", m.downloads == [m.requests[-1]["id"]], str(m.downloads))

        # ---------------- B: 날짜를 직접 치고 Enter 로 로그인, 공지 없는 날 기록 ----------------
        print("=== B. 기록 (공지 없음, Enter 로그인, 날짜 직접 입력)")
        srv.mall = mall = fake_mall.Mall(DAY, False)
        b = rec.record(url + "/login", os.path.join(OUT, "rec_b.json"), headless=True,
                       human=human(mall, False, dates=True, enter_login=True), record_date=DAY)
        for i, s in enumerate(b["steps"], 1):
            print(f"    {i:2d}. {rec.describe(s)}")
        offs = [s["date"]["offset"] for s in b["steps"] if s.get("date")]
        check("직접 친 날짜는 오늘 기준 (-1, 0)", offs == [-1, 0], str(offs))
        check("Enter 로그인이 한 단계 (단추 눌림이 겹치지 않는다)", [s["kind"] for s in b["steps"][:3]] == ["fill", "secret", "enter"],
              str([s["kind"] for s in b["steps"][:4]]))
        day = DAY + datetime.timedelta(days=1)
        ok, r, m = replay_check(srv, url, b, day, True, None, "B1_다음날_예상밖공지")
        check("B1: 끝까지 (기록에 없던 공지를 닫고)", ok, str(r.results[-1]))
        want = {"status": "PAY", "d1": (day - datetime.timedelta(days=1)).isoformat(), "d2": day.isoformat()}
        check("B1: 검색 조건 (결제완료, 어제~오늘을 그날 기준으로)", m.searches[-1:] == [want], str(m.searches))
        check("B1: 새 파일", m.downloads == [m.requests[-1]["id"]], str(m.downloads))

        # ---------------- E: 마우스를 올리는 순간 새로 만들어지는 메뉴 (배송관리 > 송장전송) ----------------
        print("=== E. 기록 (마우스를 올리면 새로 만들어지는 메뉴)")
        srv.mall = mall = fake_mall.Mall(DAY, False)

        def human_e(page):
            hclick(page, page.get_by_placeholder("아이디"))
            page.keyboard.type(fake_mall.USER, delay=15)
            hclick(page, page.get_by_placeholder("비밀번호"))
            page.keyboard.type(fake_mall.PASSWORD, delay=15)
            hclick(page, page.get_by_role("button", name="로그인", exact=True))
            page.wait_for_url("**/main**")
            page.get_by_role("link", name="배송관리", exact=True).hover()
            hclick(page, page.get_by_role("link", name="송장전송", exact=True))
            fl = page.frame_locator("iframe[name=content]")
            with page.expect_download() as di:
                hclick(page, fl.get_by_role("button", name="송장 엑셀 받기", exact=True))
            di.value.path()
        e = rec.record(url + "/login", os.path.join(OUT, "rec_e.json"), headless=True, human=human_e, record_date=DAY)
        for i, s in enumerate(e["steps"], 1):
            print(f"    {i:2d}. {rec.describe(s)}")
        kinds = [s["kind"] for s in e["steps"]]
        check("마우스 올리기가 저절로 들어간다 (로그인 → 배송관리에 마우스 → 송장전송 → 받기)",
              kinds == ["fill", "secret", "click", "hover", "click", "click"] and e["steps"][3]["target"]["text"] == "배송관리",
              str(kinds))
        check("늘 있는 메뉴(주문관리 > 발송처리)에는 안 들어간다", "hover" not in [s["kind"] for s in a["steps"]])
        day = DAY + datetime.timedelta(days=1)
        ok, r, m = replay_check(srv, url, e, day, False, None, "E1_다음날")
        check("E1: 끝까지, 그날 송장 파일", ok and m.ship_downloads == [day.isoformat()]
              and [os.path.basename(x) for x in r.saved] == [f"(012)송장목록_{day.isoformat()}.xlsx"], str(r.results[-1]))
        no_hover = rec.keep_steps(e, [i for i, s in enumerate(e["steps"]) if s["kind"] != "hover"])
        ok, r, m = replay_check(srv, url, no_hover, day, False, None, "E2_마우스올리기뺌", step_timeout=5)
        check("E2: 마우스 올리기를 빼면 '송장전송' 을 못 찾고 멈춘다 (이 단계가 왜 있어야 하는지)",
              not ok and r.results[-1][0] == 4 and m.ship_downloads == [], str(r.results[-1]))

        # ---------------- 실패하는 모습: 비밀번호가 바뀐 날 ----------------
        ok, r, m = replay_check(srv, url, a, day, False, None, "C_비밀번호틀림", creds={"ID": fake_mall.USER, "PW": "wrong"},
                                step_timeout=5)
        check("C: 비밀번호가 틀리면 멈추고 사진을 남긴다", not ok and m.logins == [(fake_mall.USER, False)]
              and any(n.startswith("실패_") for n in os.listdir(os.path.join(OUT, "C_비밀번호틀림"))), str(r.results[-2:]))

        # ---------------- F: 주소줄 단계 (goto·back·newtab) 와 기록 때 창 크기 ----------------
        print("=== F. 주소줄 단계와 창 크기")
        srv.mall = fake_mall.Mall(DAY, False)
        f = {"version": 1, "start_url": "", "record_date": DAY.isoformat(), "viewport": {"width": 900, "height": 640},
             "steps": [{"kind": "goto", "page": 0, "url": "/login", "href": url + "/login", "gap": 0},
                       {"kind": "newtab", "page": 1, "url": "", "gap": 0},
                       {"kind": "goto", "page": 1, "url": "/login", "href": url + "/login?tab=2", "gap": 0},
                       {"kind": "goto", "page": 0, "url": "/login", "href": url + "/login?b=1", "gap": 0},
                       {"kind": "back", "page": 0, "url": "/login", "gap": 0}]}
        with rec.sync_playwright() as p:
            browser = rec.edge(p.chromium.launch)
            ctx = browser.new_context()
            r = rec.Replayer(ctx, f, {"ID": "", "PW": ""}, os.path.join(OUT, "F"), "012", log=print)
            r.fit_viewport = True
            ok = r.run()
            urls = [pg.url for pg in ctx.pages]
            size = ctx.pages[0].viewport_size
            browser.close()
        check("F: 주소 치기·새 탭·뒤로 가기를 따라 한다", ok and len(urls) == 2 and urls[0] == url + "/login"
              and urls[1].endswith("/login?tab=2"), str((ok, urls, r.results)))
        check("F: 기록 때 창 안쪽 크기로 연다 (반응형 사이트의 메뉴 모양)", size == {"width": 900, "height": 640}, str(size))

        # ---------------- G: 대시보드로 가는 설명에는 값이 없다 ----------------
        T = {"tag": "input", "text": "", "label": "", "placeholder": "사유를 입력하세요", "aria": "", "title": "", "name": "",
             "textCount": 1}
        g = [{"kind": "fill", "target": T, "value": "주문 처리 - 비밀아님"},
             {"kind": "goto", "href": "https://shop.example.com/main?sid=abc123&x=1"},
             {"kind": "click", "target": dict(T, tag="a", text="아주아주긴글자가스무자를넘어가는링크이름입니다정말로")}]
        full, hidden = [rec.describe(s) for s in g], [rec.describe(s, hide_values=True) for s in g]
        check("G: 평소 설명에는 친 값·주소가 다 보인다 (옵저버 목록)", "주문 처리 - 비밀아님" in full[0] and "sid=abc123" in full[1])
        check("G: 대시보드용 설명에는 친 값·주소 ? 뒤가 없고 누른 글자는 20자까지", "비밀아님" not in hidden[0]
              and "글자" in hidden[0] and "abc123" not in hidden[1] and "https://shop.example.com/main" in hidden[1]
              and "정말로" not in hidden[2] and "…" in hidden[2], str(hidden))
        check("G: 주소에 세션 값이 있으면 경고 (다음에 깨질 수 있음)", "세션" in full[1])

        # ---------------- H: 모르는 기록 형식 ----------------
        try:
            rec.Replayer(None, {"version": 99, "steps": []}, {}, OUT, "012").run()
            check("H: 모르는 기록 형식은 재생하지 않는다", False)
        except ValueError as err:          # 'e' 는 E 기록 (except ... as 는 끝나면 그 이름을 지운다)
            check("H: 모르는 기록 형식은 재생하지 않는다", "형식" in str(err), str(err))

        # ---------------- I: 눌러도 파일이 안 온다 (Review Focus 3) ----------------
        bad = json.loads(json.dumps(a))
        bad["steps"][7]["download"] = "안 오는 파일.xlsx"            # '검색' 을 눌러도 파일은 안 온다 (사이트가 바뀐 날)
        day = DAY + datetime.timedelta(days=1)
        srv.mall = m = fake_mall.Mall(day, False)
        t0 = time.time()
        with rec.sync_playwright() as p:
            browser = rec.edge(p.chromium.launch)
            ctx = browser.new_context(accept_downloads=True)
            r = rec.Replayer(ctx, bad, {"ID": fake_mall.USER, "PW": fake_mall.PASSWORD}, os.path.join(OUT, "I"), "012",
                             today=day, log=print)
            r.download_timeout_ms = 3000
            ok = r.run()
            browser.close()
        check("I: 파일이 안 오면 정해진 시간 뒤 그 단계 실패 (끝없이 기다리지 않는다)", not ok and r.results[-1][0] == 8
              and "3초 안에 파일이 오지 않았습니다" in r.results[-1][2] and time.time() - t0 < 60, str(r.results[-1]))

        # ---------------- J: 미리보기 중 창을 닫음 (Review Focus 4) ----------------
        ev = threading.Event()
        srv.mall = m = fake_mall.Mall(day, False)
        with rec.sync_playwright() as p:
            browser = rec.edge(p.chromium.launch)
            ctx = browser.new_context(accept_downloads=True)
            r = rec.Replayer(ctx, a, {"ID": fake_mall.USER, "PW": fake_mall.PASSWORD}, os.path.join(OUT, "J"), "012",
                             today=day, log=print)
            r.cancel = ev
            r.progress = lambda i, state, how: ev.set() if (i, state) == (3, "ok") else None
            ok = r.run()
            browser.close()
        check("J: 멈춤(cancel)이 켜지면 다음 단계 전에 멈춘다", not ok and r.results[-1][:2] == (4, "fail")
              and "멈춤" in r.results[-1][2] and m.downloads == [], str(r.results[-2:]))
        creds = {"ID": fake_mall.USER, "PW": fake_mall.PASSWORD}

        # ---------------- K: 단계 안에서 기다리는 중에 중단 (2026-10-02 미리보기 [■ 중단]) ----------------
        lost = json.loads(json.dumps(a))
        lost["steps"][2]["target"].update(id="", text="없는 단추", css="#no-such-button", name="", aria="", title="",
                                          placeholder="")                    # '로그인' 단추가 사라진 날
        ev, t_run = threading.Event(), {}

        def on_k(i, state, how):
            if (i, state) == (3, "run"):
                t_run["t"] = time.time()
                threading.Timer(1.0, ev.set).start()
        srv.mall = fake_mall.Mall(day, False)
        with rec.sync_playwright() as p:
            browser = rec.edge(p.chromium.launch)
            ctx = browser.new_context(accept_downloads=True)
            r = rec.Replayer(ctx, lost, creds, os.path.join(OUT, "K"), "012", today=day, log=print, step_timeout=20)
            r.cancel, r.progress = ev, on_k
            ok = r.run()
            took = time.time() - t_run.get("t", time.time())
            browser.close()
        check("K: 단추를 찾으며 기다리는 중에 중단해도 곧 멈춘다 (20초를 다 기다리지 않는다)", not ok
              and r.results[-1][:2] == (3, "fail") and "멈춤" in r.results[-1][2] and took < 6, f"{took:.1f}초 {r.results[-1:]}")

        # ---------------- L: 일시정지 - 지금 단계를 마치고 다음 단계 앞에서 기다린다 ----------------
        pause, seen, held = threading.Event(), [], {}

        def on_l(i, state, how):
            seen.append((i, state))
            if (i, state) == (2, "ok"):
                pause.set()

                def resume():
                    held["results"] = len(r.results)
                    pause.clear()
                threading.Timer(2.0, resume).start()
        srv.mall = m = fake_mall.Mall(day, False)
        with rec.sync_playwright() as p:
            browser = rec.edge(p.chromium.launch)
            ctx = browser.new_context(accept_downloads=True)
            r = rec.Replayer(ctx, e, creds, os.path.join(OUT, "L"), "012", today=day, log=print)
            r.pause, r.progress = pause, on_l
            ok = r.run()
            browser.close()
        check("L: 일시정지면 다음 단계 앞에서 기다리고 ('paused' 알림), 풀면 끝까지 간다", ok and (3, "paused") in seen
              and held.get("results") == 2 and m.ship_downloads == [day.isoformat()], f"{held} {seen}")

        # ---------------- M: 새 창(팝업)이 내려 주는 파일 (2026-10-02 미룬 것 4) ----------------
        print("=== M. 기록 (팝업이 파일을 내려 주고 스스로 닫힌다)")
        srv.mall = mall = fake_mall.Mall(DAY, False)

        def human_m(page):
            hclick(page, page.get_by_placeholder("아이디"))
            page.keyboard.type(fake_mall.USER, delay=15)
            hclick(page, page.get_by_placeholder("비밀번호"))
            page.keyboard.type(fake_mall.PASSWORD, delay=15)
            hclick(page, page.get_by_role("button", name="로그인", exact=True))
            page.wait_for_url("**/main**")
            page.get_by_role("link", name="배송관리", exact=True).hover()
            hclick(page, page.get_by_role("link", name="송장전송", exact=True))
            hclick(page, page.frame_locator("iframe[name=content]").get_by_role("button", name="팝업으로 받기", exact=True))
            for _ in range(40):
                if mall.ship_downloads:
                    break
                page.wait_for_timeout(250)
            page.wait_for_timeout(500)
        mr = rec.record(url + "/login", os.path.join(OUT, "rec_m.json"), headless=True, human=human_m, record_date=DAY)
        for i, s in enumerate(mr["steps"], 1):
            print(f"    {i:2d}. {rec.describe(s)}")
        check("M: 팝업을 여는 단계에 '새 창' 과 '파일 받기' 가 같이 적힌다", mr["steps"][-1].get("opens") == 1
              and mr["steps"][-1].get("download"), json.dumps(mr["steps"][-1:], ensure_ascii=False)[:300])
        day = DAY + datetime.timedelta(days=1)
        srv.mall = m = fake_mall.Mall(day, False)
        with rec.sync_playwright() as p:
            browser = rec.edge(p.chromium.launch)
            ctx = browser.new_context(accept_downloads=True)
            r = rec.Replayer(ctx, mr, creds, os.path.join(OUT, "M"), "012", today=day, log=print)
            r.download_timeout_ms = 10000
            ok = r.run()
            browser.close()
        check("M: 재생도 팝업이 내려 준 파일을 받는다 (누른 창에서만 기다리지 않는다)", ok
              and [os.path.basename(x) for x in r.saved] == [f"(012)송장목록_{day.isoformat()}.xlsx"]
              and m.ship_downloads == [day.isoformat()], str(r.results[-1:]))
    finally:
        srv.shutdown()
    print()
    print("실패:", fails or "없음")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
