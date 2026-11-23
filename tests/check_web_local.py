# -*- coding: utf-8 -*-
"""스탠드얼론 업체 웹 화면 시험 (계획 ② Task 3·4) - Playwright 로 로컬 서버의 진짜 화면(firebase/web)을 연다.

서버(local_server + local_web)는 이 프로세스의 스레드로 띄운다 - PC(에이전트) 쪽은 store.put/patch 로 흉내 낸다.
임시 폴더·시험 라이선스(dict)만 쓴다. 실제 사이트·Firebase 에는 붙지 않는다 (바깥 요청 0 을 시험이 본다).
    .venv\\Scripts\\python.exe tests\\check_web_local.py
화면 사진: 환경 변수 SHOT_DIR 에 폴더를 주면 계정 관리 카드·현황 화면을 PNG 로 남긴다 (저장소 안 tests/shots 에 두지 말 것).
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "firebase", "agent"))
import local_server  # noqa: E402
import local_web  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

fails = []
TMP = tempfile.mkdtemp(prefix="rpa_wlocal_")
DATA = os.path.join(TMP, "standalone")
WEB = os.path.join(ROOT, "firebase", "web")          # 진짜 웹 파일 (서버는 읽기만 한다)
LIC = {"edition": "standalone", "company": "시험상사", "cid": "c1", "pc_id": "p1", "issued": "2026-11-23",
       "modules": {}, "features": {}, "limits": {"schedule": 3, "presets": None, "parallel": None}}
LIVE, CMDS = "apps/rpa/live/c1/p1", "apps/rpa/commands/c1/p1"
BOSS_PW, STAFF_PW = "boss-pw-0001", "staff-pw-0001"
TODAY = time.strftime("%Y-%m-%d")
SHOT_DIR = os.environ.get("SHOT_DIR")


def check(name, ok, detail=""):
    print(f"  [{'통과' if ok else '실패'}] {name}" + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


def until(p, js, timeout=10000):
    """js 식이 참이 될 때까지 기다린다. Playwright 의 wait_for_function 은 문자열을 eval 로 돌려 이 화면의 CSP(unsafe-eval 없음)에
    막힌다 - evaluate 는 CSP 를 거치지 않으므로 그것으로 되풀이해 본다."""
    end = time.time() + timeout / 1000
    while True:
        try:
            if p.evaluate(js):
                return True
        except Exception:
            pass
        if time.time() > end:
            raise TimeoutError(f"기다림 시간 초과: {js}")
        time.sleep(0.1)


def make_live(orders=30, host="OFFICE-PC"):
    now = int(time.time())
    routine = {
        "program": "routine", "program_label": "PROCESS 오토파일럿", "state": "success",
        "started_at": f"{TODAY}T13:55:49", "updated_at": f"{TODAY}T13:58:22", "finished_at": f"{TODAY}T13:58:22",
        "duration_sec": 153, "steps_done": 2, "steps_total": 2,
        "steps": [{"key": "login", "label": "ERPia 로그인", "state": "done", "started_at": f"{TODAY}T13:55:49", "finished_at": f"{TODAY}T13:56:30"},
                  {"key": "hold", "label": "물류대기 저장", "state": "done", "started_at": f"{TODAY}T13:56:30", "finished_at": f"{TODAY}T13:58:22"}],
        "metrics": [{"key": "bottom_selected", "label": "하단 선택", "value": orders, "unit": "건"}],
    }
    return {
        "host": host,
        "heartbeat": {"at": now + 3600, "every": 5, "host": host, "rpa_running": False},
        "programs": {"routine": routine, "prepare": None},
        "modules": {"Login": True, "Sales": False, "Hold": True, "Logistics": True, "Output": True},
        "schedule": {"enabled": True, "version": 6, "days": [0, 1, 2, 3, 4], "slots": [{"at": "09:05"}], "holidays": True, "off_dates": [],
                     "next_run_at": "2026-12-01T09:05:00", "next_slot": "09:05"},
        "recent": [{"date": TODAY, "success": 1, "failed": 0, "crashed": 0}],
    }


def start_server(web, port=0):
    """같은 포트로 다시 띄울 때 윈도우가 잠깐 자리를 안 내줄 수 있어 몇 번 다시 해 본다."""
    end = time.time() + 30
    while True:
        try:
            s = local_server.make_server(store, runs, LIC, KEYS, port=port, folder=DATA, web=web)
            break
        except OSError:
            if time.time() > end:
                raise
            time.sleep(0.5)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


def stop_server(s):
    s.shutdown()
    s.server_close()


srv = runs = None
try:
    os.makedirs(DATA)
    store = local_server.Store(os.path.join(DATA, "store.json"), volatile=local_server.VOLATILE)
    runs = local_server.Runs(os.path.join(DATA, "runs.db"))
    KEYS = local_server.ensure_keys(DATA)
    web = local_web.Web(store, runs, LIC, DATA, WEB)
    web.accounts.set("boss", BOSS_PW, "admin")
    web.accounts.set("staff", STAFF_PW, "viewer")
    srv = start_server(web)
    PORT = srv.server_address[1]
    BASE = f"http://127.0.0.1:{PORT}"
    store.put(LIVE, make_live())
    runs.create("runs/c1", "items", "r1", {"cid": "c1", "pcId": "p1", "run_id": "r1", "program": "routine", "program_label": "PROCESS 오토파일럿",
                                           "state": "success", "started_at": f"{TODAY}T09:00:00", "duration_sec": 70, "date": TODAY, "cost": 3,
                                           "payload": json.dumps({"steps": [], "log": ["[09:00:00] 시작"], "metrics": []}, ensure_ascii=False)})
    runs.create("runs/c1", "items", "r2", {"cid": "c1", "pcId": "p1", "run_id": "r2", "program": "prepare", "program_label": "ACTOR 오토파일럿",
                                           "state": "stopped", "reason": "엑셀받기 단계에서 대상을 찾지 못했습니다.", "started_at": f"{TODAY}T10:00:00",
                                           "duration_sec": 9, "date": TODAY, "payload": json.dumps({"steps": [], "log": []})})

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1280, "height": 860})
        outside, console_bad, net_errors, page_errors = [], [], [], []
        expect_net = [False]                 # 일부러 거절받는 동안(틀린 비밀번호·서버 다시 켜기)의 '리소스를 못 받음' 콘솔 줄은 세지 않는다

        def watch_page(p):
            p.on("request", lambda r: outside.append(r.url) if not r.url.startswith(BASE + "/") else None)
            p.on("pageerror", lambda e: page_errors.append(str(e)))

            def on_console(m):
                if m.type != "error":
                    return
                if m.text.startswith("Failed to load resource"):
                    if not expect_net[0]:
                        net_errors.append(m.text)
                else:
                    console_bad.append(m.text)
            p.on("console", on_console)
            return p

        page = watch_page(ctx.new_page())

        def login(p, uid, pw_, ok=True):
            p.goto(BASE + "/")
            p.wait_for_selector("#login:not(.hide)")
            p.fill("#login-id", uid)
            p.fill("#password", pw_)
            p.click("#login-btn")
            if ok:
                p.wait_for_selector("#main:not(.hide)", timeout=15000)
            else:
                p.wait_for_selector("#login-alert:not(.hide)", timeout=15000)

        def fresh_page():
            c2 = browser.new_context(viewport={"width": 1280, "height": 860})
            return c2, watch_page(c2.new_page())

        def cmds_of(kind):
            return {k: v for k, v in (store.get(CMDS) or {}).items() if v.get("type") == kind}

        # --------------------------------------------------------------------------------------
        print("로그인 화면")
        page.goto(BASE + "/")
        page.wait_for_selector("#login:not(.hide)")
        check("업체코드 칸이 없다 (PC 하나에 업체 하나)", page.is_hidden("#cid") and "업체코드" not in page.inner_text("#login"),
              page.inner_text("#login"))
        check("'아이디 저장' (업체코드 글 없음)", "아이디 저장" in page.inner_text("#login .remember"))
        check("글꼴은 로컬 사본 (fonts/fonts.css)", page.evaluate("[...document.styleSheets].some((s) => (s.href || '').endsWith('/fonts/fonts.css'))"))
        expect_net[0] = True
        login(page, "boss", "wrong-pw-0000", ok=False)
        check("틀린 비밀번호 문구 (업체코드 없이)", page.text_content("#login-alert") == "아이디 또는 비밀번호가 일치하지 않습니다.", page.text_content("#login-alert"))
        for _ in range(5):
            page.fill("#password", "wrong-pw-0000"); page.click("#login-btn"); page.wait_for_timeout(400)
        until(page, "(document.getElementById('login-alert')?.textContent || '').includes('잠시 잠겼습니다')", timeout=10000)
        check("여러 번 틀리면 잠금 문구 (code 가 아니라 사람 말)", page.text_content("#login-alert") == "로그인 시도가 많아 잠시 잠겼습니다. 1분 뒤 다시 시도하여 주십시오.",
              page.text_content("#login-alert"))
        web.lockout.ok("boss")
        page.wait_for_timeout(300)
        expect_net[0] = False
        login(page, "boss", BOSS_PW)
        check("로그인 → 업체 이름·'(관리자)'", page.text_content("#company") == "시험상사" and page.text_content("#who") == "boss (관리자)",
              f"{page.text_content('#company')} / {page.text_content('#who')}")
        check("세션 토큰은 탭 저장소에만 (쿠키 없음)", bool(page.evaluate("sessionStorage.getItem('ap.session')")) and ctx.cookies() == [])

        # --------------------------------------------------------------------------------------
        print("현황")
        page.wait_for_selector("#hero")
        until(page, "document.getElementById('h-state')?.textContent === '성공'", timeout=10000)
        check("현황 값이 뜬다 (상태·연결·다음 자동 실행)", "정상" in page.text_content("#conn") and "12월 1일" in page.text_content("#hero-side"),
              page.text_content("#hero-side"))
        check("처리 건수 칸", "30" in page.text_content("#tiles"), page.text_content("#tiles"))
        store.put(LIVE, make_live(orders=42))
        until(page, "(document.getElementById('tiles')?.textContent || '').includes('42')", timeout=10000)
        check("PC 값이 바뀌면 화면도 따라 바뀐다", "42" in page.text_content("#tiles"))
        check("안 보이는 것: 토큰·사용량 카드, PC 고르기, 총괄 띠", all(page.is_hidden(s) for s in ("#token-card", "#usage-card", "#pc-pick", "#super-bar")))
        if SHOT_DIR:
            page.screenshot(path=os.path.join(SHOT_DIR, "standalone_status.png"))

        print("[실행]")
        page.evaluate("window.__replyWaitMs = 8000")
        page.click("#run-routine")
        page.wait_for_selector("#toasts .toast")
        ok = False
        for _ in range(40):
            if cmds_of("launch"):
                ok = True
                break
            time.sleep(0.1)
        key, cmd = next(iter(cmds_of("launch").items()), (None, {}))
        check("[실행] → 저장소에 launch 명령 (by = 아이디, 90초, 대기)", ok and cmd.get("by") == "boss" and cmd.get("state") == "queued"
              and cmd.get("args") == {"target": "routine"} and cmd.get("expires_at", 0) - cmd.get("created_at", 0) == 90, repr(cmd))
        check("응답 대기 중 버튼 잠금", page.is_disabled("#run-routine"))
        store.patch(f"{CMDS}/{key}", {"state": "running", "started_at": int(time.time())})
        until(page, "(document.getElementById('toasts')?.textContent || '').includes('진행 중')", timeout=10000)
        check("running → '진행 중' 토스트", True)
        store.patch(f"{CMDS}/{key}", {"state": "done", "result": "PROCESS 오토파일럿을 실행합니다.", "ended_at": int(time.time())})
        until(page, "(document.getElementById('toasts')?.textContent || '').includes('실행합니다')", timeout=10000)
        check("done → 결과 토스트 (초록)", page.locator('#toasts [data-id="act"].ok').count() == 1)
        until(page, "document.getElementById('run-routine')?.disabled === false", timeout=8000)

        # --------------------------------------------------------------------------------------
        print("기록 탭")
        page.click("#tab-history")
        until(page, "(document.getElementById('hist-msg')?.textContent || '').endsWith('건')", timeout=10000)
        heads = page.locator("#view-history thead th").all_text_contents()
        check("기록 두 건이 뜬다 (최근 순)", page.locator("#hist-rows tr.hist").count() == 2
              and "ACTOR" in page.text_content("#hist-rows tr.hist") and "엑셀받기" in page.text_content("#hist-rows tr.hist"), page.text_content("#hist-rows"))
        check("'토큰 사용량' 열이 없다 (머리·칸)", "토큰 사용량" not in heads and len(heads) == 5
              and all(n == 5 for n in page.evaluate("[...document.querySelectorAll('#hist-rows tr.hist')].map((r) => r.children.length)")), repr(heads))
        page.click("#tab-status")

        # --------------------------------------------------------------------------------------
        print("환경설정")
        page.click("#admin-nav a[data-key='settings']")
        page.wait_for_selector("#mod-card")
        until(page, "(document.getElementById('mod-meta')?.textContent || '').includes('켬')", timeout=10000)
        check("안 보이는 것: AI 어시스트·프리셋 복사 카드", page.is_hidden("#ai-card") and page.is_hidden("#copy-card"))
        before = set(store.get(CMDS) or {})
        page.click("#mod-list label:nth-child(2)")
        page.click("#mod-apply")
        page.wait_for_timeout(1200)
        new = {k: v for k, v in (store.get(CMDS) or {}).items() if k not in before}
        mods = [v for v in new.values() if v.get("type") == "set_modules"]
        check("모듈 [적용] → set_modules 명령 하나 (600초)", len(new) == 1 and len(mods) == 1 and mods[0]["args"].get("Sales") is True
              and mods[0]["expires_at"] - mods[0]["created_at"] == 600, repr(new))
        for k, v in new.items():
            store.patch(f"{CMDS}/{k}", {"state": "done", "result": "실행 모듈을 바꿨습니다", "ended_at": int(time.time())})
        live = make_live(orders=42)
        live["modules"]["Sales"] = True
        store.put(LIVE, live)
        until(page, "document.getElementById('mod-apply')?.disabled === true && !document.querySelector('#sch-enabled')?.disabled", timeout=10000)
        before = set(store.get(CMDS) or {})
        page.click("label.switch:has(#sch-enabled)")
        page.click("#sch-apply")
        page.wait_for_timeout(1200)
        new = {k: v for k, v in (store.get(CMDS) or {}).items() if k not in before}
        check("자동 실행 [적용] → set_schedule 명령 하나", len(new) == 1 and next(iter(new.values())).get("type") == "set_schedule"
              and next(iter(new.values()))["args"].get("enabled") is False, repr(new))
        for k in new:
            store.patch(f"{CMDS}/{k}", {"state": "done", "result": "자동 실행을 바꿨습니다", "ended_at": int(time.time())})
        page.wait_for_timeout(500)

        # --------------------------------------------------------------------------------------
        print("탭 단위 로그인")
        p2 = watch_page(ctx.new_page())
        p2.goto(BASE + "/")
        p2.wait_for_selector("#login:not(.hide)")
        check("새 탭(같은 브라우저)은 로그인 화면", p2.is_visible("#login") and p2.is_hidden("#main"))
        p2.close()
        page.reload()
        page.wait_for_selector("#main:not(.hide)", timeout=15000)
        page.wait_for_selector("#hero")
        check("새로고침은 로그인 유지", page.text_content("#who") == "boss (관리자)")

        # --------------------------------------------------------------------------------------
        print("계정 관리 (관리자, Task 4)")
        page.click("#admin-nav a[data-key='account']")
        page.wait_for_selector("#acct-card:not(.hide)", timeout=10000)
        page.wait_for_selector("#acct-rows tr[data-id='staff']")
        check("관리자 계정 화면 아래 '계정 관리' 카드 - 아이디·권한·상태 표", page.locator("#acct-card table thead th").all_text_contents()[:3] == ["아이디", "권한", "상태"]
              and "유저" in page.text_content("#acct-rows tr[data-id='staff']") and "사용 중" in page.text_content("#acct-rows tr[data-id='staff']"))
        check("자기 줄에는 [삭제]·[사용 중지] 가 없다", page.locator("#acct-rows tr[data-id='boss'] button").count() == 0
              and "지금 로그인" in page.text_content("#acct-rows tr[data-id='boss']"))
        check("다른 줄에는 [비밀번호 다시 정하기]·[사용 중지]·[삭제]", page.locator("#acct-rows tr[data-id='staff'] button").all_text_contents()
              == ["비밀번호 다시 정하기", "사용 중지", "삭제"])
        # 서버 거절 글은 토스트로 (400 은 일부러 받는 것)
        expect_net[0] = True
        page.fill("#acct-new-id", "clerk"); page.fill("#acct-new-pw", "1234567"); page.click("#acct-add")
        until(page, "(document.getElementById('toasts')?.textContent || '').includes('8자 이상')", timeout=10000)
        check("서버 거절 글이 토스트로 (짧은 비밀번호)", page.locator("#toasts .toast.bad").count() >= 1 and "clerk" not in [a["id"] for a in web.accounts.list()])
        page.fill("#acct-new-id", "staff"); page.fill("#acct-new-pw", "other-pw-0001"); page.click("#acct-add")
        until(page, "(document.getElementById('toasts')?.textContent || '').includes('이미 있는 아이디')", timeout=10000)
        check("서버 거절 글이 토스트로 (이미 있는 아이디)", True)
        page.wait_for_timeout(300)
        expect_net[0] = False
        page.fill("#acct-new-id", "clerk"); page.fill("#acct-new-pw", "clerk-pw-0001"); page.select_option("#acct-new-role", "viewer"); page.click("#acct-add")
        page.wait_for_selector("#acct-rows tr[data-id='clerk']", timeout=10000)
        check("유저 추가 → 표에 '비밀번호 변경 필요' 줄, 칸은 비워진다", "비밀번호 변경 필요" in page.text_content("#acct-rows tr[data-id='clerk']")
              and page.input_value("#acct-new-id") == "" and page.input_value("#acct-new-pw") == "")
        if SHOT_DIR:
            until(page, "document.querySelectorAll('#toasts .toast').length === 0", timeout=15000)
            page.set_viewport_size({"width": 1280, "height": 1160})      # 카드 전체가 한 화면에 (full_page 는 붙박이 사이드바가 어긋나 찍힌다)
            page.wait_for_timeout(300)
            page.screenshot(path=os.path.join(SHOT_DIR, "standalone_accounts.png"))
            page.set_viewport_size({"width": 1280, "height": 860})

        c2, q = fresh_page()
        login(q, "clerk", "clerk-pw-0001")
        check("추가한 유저로 로그인된다 - 첫 로그인은 계정 화면만 (mustChange)", q.text_content("#page-title") == "계정"
              and q.locator("#app-nav a").count() == 0 and q.locator("#admin-nav a").all_text_contents() == ["계정"] and q.is_visible("#pw-must"))
        check("유저(viewer)에게는 계정 관리 카드가 없다", q.locator("#acct-card").count() == 0)
        q.fill("#pw-cur", "clerk-pw-0001"); q.fill("#pw-new", "clerk-pw-0002"); q.fill("#pw-new2", "clerk-pw-0002"); q.click("#pw-btn")
        until(q, "(document.getElementById('pw-msg')?.textContent || '').includes('바꿨습니다')", timeout=10000)
        check("비밀번호를 바꾸면 잠금이 풀린다 (메뉴가 돌아오고 안내가 사라짐) - 성공 글은 '다른 탭은'",
              q.locator("#app-nav a").count() == 1 and q.is_hidden("#pw-must") and "다른 탭은 다시 로그인해야 합니다" in q.text_content("#pw-msg")
              and q.locator("#admin-nav a[data-key='settings']").count() == 0)
        q.click("#app-nav a[data-key='rpa']")
        q.wait_for_selector("#hero")
        until(q, "document.getElementById('h-state')?.textContent === '성공'", timeout=10000)
        check("유저: 현황은 보이고 [실행]·환경설정 메뉴가 없다", q.is_hidden("#act-card") and q.is_hidden("#sidecol")
              and q.locator("#admin-nav a[data-key='settings']").count() == 0)
        q.click("#logout-btn")
        q.wait_for_selector("#login:not(.hide)")
        expect_net[0] = True
        login(q, "clerk", "clerk-pw-0001", ok=False)
        check("비밀번호를 바꾼 뒤 옛 비밀번호로는 로그인 안 됨", "일치하지 않습니다" in q.text_content("#login-alert"))
        expect_net[0] = False
        login(q, "clerk", "clerk-pw-0002")
        check("새 비밀번호로 다시 로그인 → 바로 현황 (잠금 없음)", q.locator("#app-nav a").count() == 1 and q.text_content("#page-title") == "오토파일럿")
        c2.close()

        # 사용 중지 → 그 계정 로그인 문구
        page.click("#acct-rows tr[data-id='staff'] button[data-act='toggle']")
        until(page, "document.querySelector(\"#acct-rows tr[data-id='staff'] .pill\")?.textContent === '사용 중지'", timeout=10000)
        check("[사용 중지] → 상태 '사용 중지', 단추는 [다시 사용]", "다시 사용" in page.text_content("#acct-rows tr[data-id='staff']")
              and web.accounts.get("staff")["disabled"] is True)
        c2, q = fresh_page()
        expect_net[0] = True
        login(q, "staff", STAFF_PW, ok=False)
        expect_net[0] = False
        check("사용 중지한 계정은 '사용이 중지된 계정입니다.'", q.text_content("#login-alert") == "사용이 중지된 계정입니다.", q.text_content("#login-alert"))
        page.click("#acct-rows tr[data-id='staff'] button[data-act='toggle']")
        until(page, "document.querySelector(\"#acct-rows tr[data-id='staff'] .pill\")?.textContent === '사용 중'", timeout=10000)
        check("[다시 사용] → 상태 '사용 중'", web.accounts.get("staff")["disabled"] is False)
        # 비밀번호 다시 정하기 → 그 비밀번호로 로그인하면 계정 화면만
        page.click("#acct-rows tr[data-id='staff'] button[data-act='reset']")
        page.wait_for_selector("#acct-rows tr.acct-reset input[type=password]")
        page.fill("#acct-rows tr.acct-reset input[type=password]", "short")
        expect_net[0] = True
        page.click("#acct-rows tr.acct-reset button[data-act='reset-ok']")
        until(page, "(document.getElementById('toasts')?.textContent || '').includes('8자 이상')", timeout=10000)
        page.wait_for_timeout(300)
        expect_net[0] = False
        check("다시 정하는 비밀번호도 서버 거절 글이 토스트로, 칸은 남는다", page.locator("#acct-rows tr.acct-reset").count() == 1)
        page.fill("#acct-rows tr.acct-reset input[type=password]", "staff-pw-reset1")
        page.click("#acct-rows tr.acct-reset button[data-act='reset-ok']")
        until(page, "document.querySelectorAll('#acct-rows tr.acct-reset').length === 0", timeout=10000)
        check("비밀번호 다시 정하기 → 상태 '비밀번호 변경 필요'", "비밀번호 변경 필요" in page.text_content("#acct-rows tr[data-id='staff']"))
        login(q, "staff", "staff-pw-reset1")
        check("다시 정한 비밀번호로 로그인하면 계정 화면만 (mustChange)", q.text_content("#page-title") == "계정" and q.locator("#app-nav a").count() == 0
              and q.locator("#admin-nav a").all_text_contents() == ["계정"])
        check("mustChange 계정에게도 계정 관리 카드는 없다 (유저)", q.locator("#acct-card").count() == 0)
        c2.close()
        # 삭제는 확인 창 - 취소하면 그대로, 확인하면 지운다
        page.once("dialog", lambda d: d.dismiss())
        page.click("#acct-rows tr[data-id='clerk'] button[data-act='remove']")
        page.wait_for_timeout(500)
        check("삭제 확인 창에서 취소하면 그대로", page.locator("#acct-rows tr[data-id='clerk']").count() == 1 and "clerk" in [a["id"] for a in web.accounts.list()])
        msgs = []
        page.once("dialog", lambda d: (msgs.append(d.message), d.accept()))
        page.click("#acct-rows tr[data-id='clerk'] button[data-act='remove']")
        until(page, "!document.querySelector(\"#acct-rows tr[data-id='clerk']\")", timeout=10000)
        check("삭제 확인 창에서 확인하면 지운다", "clerk" not in [a["id"] for a in web.accounts.list()] and msgs and "clerk" in msgs[0], repr(msgs))

        # --------------------------------------------------------------------------------------
        print("비밀번호 바꾸기 → 다시 로그인 (관리자)")
        page.fill("#pw-cur", BOSS_PW); page.fill("#pw-new", "boss-pw-0002"); page.fill("#pw-new2", "boss-pw-0002"); page.click("#pw-btn")
        until(page, "(document.getElementById('pw-msg')?.textContent || '').includes('바꿨습니다')", timeout=10000)
        page.click("#logout-btn")
        page.wait_for_selector("#login:not(.hide)")
        check("로그아웃하면 탭 저장소의 토큰도 지운다", page.evaluate("sessionStorage.getItem('ap.session')") is None)
        login(page, "boss", "boss-pw-0002")
        check("바꾼 비밀번호로 다시 로그인", page.text_content("#who") == "boss (관리자)")
        BOSS_PW = "boss-pw-0002"

        # --------------------------------------------------------------------------------------
        print("서버 다시 켜기 (Review Focus 4)")
        page.wait_for_selector("#hero")
        # (1) 웹 창구를 그대로 둔 채 서버만 다시 - 세션이 살아 있으니 스트림이 다시 붙어 현황이 이어진다
        expect_net[0] = True
        stop_server(srv)
        page.wait_for_timeout(1500)
        store.put(LIVE, make_live(orders=55))
        srv = start_server(web, PORT)
        until(page, "(document.getElementById('tiles')?.textContent || '').includes('55')", timeout=40000)
        check("스트림만 끊겼다 붙으면 현황이 이어진다 (로그인 유지)", page.is_visible("#main") and "55" in page.text_content("#tiles"))
        store.put(LIVE, make_live(orders=56))
        until(page, "(document.getElementById('tiles')?.textContent || '').includes('56')", timeout=10000)
        check("다시 붙은 뒤의 변경도 따라온다", True)
        # (2) 서버 프로그램을 다시 켠 것처럼 웹 창구까지 새로 - 세션이 사라졌으니 로그인 화면으로
        stop_server(srv)
        web = local_web.Web(store, runs, LIC, DATA, WEB)
        srv = start_server(web, PORT)
        page.wait_for_selector("#login:not(.hide)", timeout=40000)
        check("세션이 사라졌으면 로그인 화면으로", page.is_hidden("#main") and page.evaluate("sessionStorage.getItem('ap.session')") is None)
        page.wait_for_timeout(500)
        expect_net[0] = False
        login(page, "boss", BOSS_PW)
        check("다시 로그인하면 그대로 쓴다", page.text_content("#who") == "boss (관리자)")
        page.wait_for_selector("#hero")
        until(page, "(document.getElementById('tiles')?.textContent || '').includes('56')", timeout=10000)

        # --------------------------------------------------------------------------------------
        print("바깥 요청 · 콘솔")
        page.wait_for_timeout(500)
        check("바깥 요청 0 (모든 요청이 이 서버 주소)", not outside, repr(outside[:10]))
        check("콘솔 오류 0 (CSP 위반 포함)", not console_bad and not page_errors, repr((console_bad[:5], page_errors[:5])))
        check("일부러 거절받은 때 말고는 '리소스를 못 받음' 도 없다", not net_errors, repr(net_errors[:5]))
        browser.close()
finally:
    try:
        if srv is not None:
            stop_server(srv)
    except Exception:
        pass
    try:
        if runs is not None:
            runs.close()
    except Exception:
        pass
    shutil.rmtree(TMP, ignore_errors=True)

print(f"\n실패: {len(fails)}" + (f" ({', '.join(fails)})" if fails else ""))
sys.exit(1 if fails else 0)
