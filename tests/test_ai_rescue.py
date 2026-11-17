# -*- coding: utf-8 -*-
"""ACTOR AI 어시스트 (설계 2026-11-16) - 실제 AI 는 부르지 않는다 (가짜 SDK 클라이언트·가짜 AI).

앞 절(M·K·A·S·U)은 브라우저 없이 ai_rescue 만 본다. 뒤 절(C)은 가짜 쇼핑몰 화면에서 재생기가 후보를 모으는 것을 본다 (headless).
재생 절(R)은 실제 기록기로 옛 화면을 기록하고, 서버가 '오늘은 화면이 다른 날' 을 보여 주며, 가짜 AI 가 글자로 후보를 고른다.
서버가 눌린 것을 센다 - 재생기가 '성공' 이라고 해도 엉뚱한 것을 눌렀으면 잡는다.
    .venv\\Scripts\\python.exe tests\\test_ai_rescue.py
"""
import datetime
import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import anthropic  # noqa: E402
import httpx2  # noqa: E402

from playwright.sync_api import sync_playwright  # noqa: E402

import ai_rescue as ai  # noqa: E402
import web_replay as rec  # noqa: E402

fails = []
BTN = {"tag": "button"}


def check(name, ok, detail=""):
    print(f"  [{'통과' if ok else '실패'}] {name}" + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


def no_browser():
    print("가리기·나누기·거르기")
    m = ai.mask("주문자 010-1234-5678 / a@b.co.kr")
    check("M1 전화·이메일을 가린다", "010" not in m and "@" not in m, m)
    m = ai.mask("주문번호 2026111612345")
    check("M2 긴 숫자 줄을 가리고 짧은 수는 둔다", "2026111612345" not in m and ai.mask("3건") == "3건", m)
    m = ai.mask("pw는 Abc!234", ["Abc!234"])
    check("M3 비밀 값을 가린다", "Abc!234" not in m, m)
    check("M4 띄어 쓴 지역 번호 전화도 가린다", "6789" not in ai.mask("02 345 6789"), ai.mask("02 345 6789"))
    check("M5 빈 글은 빈 글", ai.mask("", ["x"]) == "")

    c = ai.classify
    check("K1 미루기 단추", (c("오늘 하루 보지 않기"), c("90일 후에 보기"), c("×"), c("Excel"))
          == ("defer", "defer", "defer", "substitute"), (c("오늘 하루 보지 않기"), c("90일 후에 보기"), c("×"), c("Excel")))
    check("K2 [확인]은 글 전체가 확인일 때만", (c("확인"), c(" OK "), c("확인하기")) == ("confirm", "confirm", "substitute"))

    al = ai.allowed
    check("A1 미루기 단추는 누른다", al("defer", "닫기", "", "엑셀받기", False, "click", {"tag": "button"})[0])
    check("A2 순수 안내의 [확인]만 누른다", al("confirm", "확인", "공지사항 점검 안내", "엑셀받기", True, "click", BTN)[0]
          and not al("confirm", "확인", "공지사항 점검 안내", "엑셀받기", False, "click", BTN)[0])
    check("A3 신청을 묻는 레이어의 [확인]은 안 누른다", not al("confirm", "확인", "서비스를 신청하시겠습니까?", "엑셀받기", True, "click", BTN)[0])
    check("A4 대신 누를 것도 레이어 글의 위험 낱말로 거른다", not al("substitute", "확인", "서비스를 신청하시겠습니까?", "확인", False, "click", BTN)[0])
    check("A5 기록에 없던 위험 낱말은 안 되고 기록에 있던 낱말은 된다",
          not al("substitute", "주문취소", "", "주문조회", False, "click", BTN)[0] and al("substitute", "저장하기", "", "저장", False, "click", BTN)[0])
    check("A8 [확인] 은 기록 대상 글에 같은 낱말이 있어도 화면 글의 위험 낱말로 막는다 (설계 7번, 최종 검토 I-2)",
          not al("confirm", "확인", "주문을 취소하시겠습니까?", "취소/반품 조회", True, "click", BTN)[0])
    ok, why = al("defer", "동의하고 닫기", "", "엑셀받기", False, "click", BTN)
    check("A6 동의가 섞인 미루기 단추는 안 누른다 (까닭을 돌려준다)", not ok and why, why)
    check("A7 비밀번호 칸에는 안 넣는다", not al("substitute", "", "", "검색어", False, "fill", {"tag": "input", "type": "password"})[0]
          and al("substitute", "", "", "검색어", False, "fill", {"tag": "input", "type": "text"})[0])

    sc = ai.ANSWER_SCHEMA
    check("S1 답 모양은 네 칸 모두 필수, 다른 칸 없음",
          set(sc["required"]) == {"choice", "info_only", "reason", "screen"} and sc["additionalProperties"] is False)

    print("AI 묻기 (가짜 SDK)")
    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")

    def client(fn):
        return SimpleNamespace(messages=SimpleNamespace(create=fn))

    def raise_(e):
        def f(**kw):
            raise e
        return f

    def reply(text, stop="end_turn"):
        def f(**kw):
            return SimpleNamespace(stop_reason=stop, content=[SimpleNamespace(type="text", text=text)],
                                   usage=SimpleNamespace(input_tokens=10, output_tokens=5))
        return f

    def why(fn):
        try:
            ai.Claude("k", client=client(fn)).choose("s", "u")
        except ai.AiUnavailable as e:
            return str(e)
        return "예외 없음"

    good = json.dumps({"choice": -1, "info_only": False, "reason": "없음", "screen": "주문 목록"})
    ans = ai.Claude("k", client=client(reply(good))).choose("s", "u")
    check("U1 사용 한도 → '사용 한도'",
          why(raise_(anthropic.RateLimitError("x", response=httpx2.Response(429, request=req), body=None))) == "사용 한도")
    check("U1 키가 끊김", why(raise_(anthropic.AuthenticationError("x", response=httpx2.Response(401, request=req), body=None))) == "키가 끊김")
    check("U1 AI 서버 오류", why(raise_(anthropic.InternalServerError("x", response=httpx2.Response(500, request=req), body=None))) == "AI 서버 오류")
    check("U1 인터넷 오류", why(raise_(anthropic.APIConnectionError(request=req))) == "인터넷 오류")
    check("U1 시간 초과", why(raise_(anthropic.APITimeoutError(request=req))) == "시간 초과")
    check("U1 거절 → 'AI가 답하지 않음'", why(reply("", stop="refusal")) == "AI가 답하지 않음")
    check("U1 choice -1 → None", ans.choice is None and ans.screen == "주문 목록", ans)
    check("U1 모양이 틀린 답", why(reply('{"choice": "a"}')) == "답 모양 틀림")
    check("U1 JSON 이 아닌 답", why(reply("음...")) == "답 모양 틀림")

    check("U2 설정이 없거나 꺼졌거나 키가 비면 AI 없음",
          ai.from_settings(None) is None and ai.from_settings({"on": True, "key": ""}) is None
          and ai.from_settings({"on": False, "key": "k"}) is None)
    check("U2 켜고 키가 있으면 AI", isinstance(ai.from_settings({"on": True, "key": "k"}), ai.Claude))


PAGES = {
    "/many": "<html><body>" + "".join(f'<a href="/m{k}">메뉴 {k}</a> ' for k in range(200))
             + '<div role="dialog" style="position:fixed;top:0;left:0;width:600px;background:#fff">공지 '
             + "안내 문구 " * 60 + '부가 서비스를 신청하시겠습니까? <button>확인</button> <button>오늘 하루 보지 않기</button></div></body></html>',
    "/c": """<html><head><title>주문 관리</title></head><body><h2>주문 관리</h2>
<input id="q" placeholder="주문자 검색" value="홍길동">
<button id="xl">엑셀받기</button>
<table><tbody><tr><td>김철수 010-1111-2222</td><td><a href="/file?id=n1">다운로드</a></td></tr>
<tr onclick="void 0"><td>박영희 서울시 강남구 테헤란로</td><td><a href="/member?id=7">박영희</a></td></tr></tbody></table>
<button id="mail">평일 오전 9시부터 오후 6시까지 고객 문의 메일 hong.gildong@naver.com</button>
<div role="dialog" style="position:fixed;top:10px;left:10px;width:500px;background:#fff">점검 안내
 <button id="close1">오늘 하루 보지 않기</button></div></body></html>""",
}


UID, PW = "shopuser77", "Secret!9"
MODE, HITS = {}, []
BASE_MODE = {"menu": "주문관리", "btn": "엑셀받기", "layer": "", "dead": False, "cancel": False, "done_layer": "", "ok_here": False}
HIT_JS = ("function hit(x){var r=new XMLHttpRequest();r.open('GET','/hit?x='+x,false);r.send();}"
          "function reveal(){var s=document.getElementById('slot');s.outerHTML=document.getElementById('tpl').innerHTML;}")
LAYERS = {   # 모드 → (레이어 글, 단추 글, 단추가 서버에 남기는 이름, 누르면 레이어가 닫히나)
    "notice": ("점검 안내 - 11월 20일 새벽 점검", "오늘 하루 보지 않기", "close", True),
    "stuck": ("점검 안내 - 11월 20일 새벽 점검", "오늘 하루 보지 않기", "close", False),
    "terms": ("약관 동의 - 개정된 약관에 동의해 주세요", "동의", "agree", True),
    "info": ("공지사항 점검 안내", "확인", "info", True),
    "apply": ("부가 서비스를 신청하시겠습니까?", "확인", "apply", True),
    "apply_yes": ("부가 서비스를 신청하시겠습니까?", "예", "apply", True),
}


def layer_html(kind):
    """레이어가 떠 있는 동안 대상은 화면에 없다 (숨긴 것이 아니라 - 숨기면 재생기가 id 로 찾아 스크립트로 누른다). 닫으면 생긴다."""
    text, btn, name, closes = LAYERS[kind]
    after = "document.getElementById('lay').remove();reveal();" if closes else ""
    return (f'<div id="lay" role="dialog" style="position:fixed;top:20px;left:20px;width:600px;background:#fff;border:1px solid">'
            f'{text}<br><button onclick="hit(\'{name}\');{after}">{btn}</button></div>')


def hidden(target, layer):
    return f'<span id="slot"></span><template id="tpl">{target}</template>{layer_html(layer)}' if layer else target


def orders_html():
    m = MODE
    go = "" if m["dead"] else "location.href='/done';"
    xl = f'<button id="xl" onclick="hit(\'excel\');{go}">{m["btn"]}</button>' 
    return (f"<html><head><title>주문 관리</title><script>{HIT_JS}</script></head><body>"
            f"<h2>{UID}님 주문 관리</h2><h3>고객센터 010-2222-3333 help@mall.co.kr</h3>"
            f'<input id="q" placeholder="검색어"> '
            + hidden(xl, m["layer"]) + " "
            + ('<button onclick="hit(\'cancel\')">주문취소</button>' if m["cancel"] else "")
            + ('<button id="ok" onclick="hit(\'ok_here\')">확인</button>' if m["ok_here"] else "")
            + "<table><tbody><tr><td>김철수 010-1111-2222</td></tr></tbody></table></body></html>")


def done_html():
    m = MODE
    ok = '<button id="ok" onclick="hit(\'ok\')">확인</button>'
    return (f"<html><head><title>완료</title><script>{HIT_JS}</script></head><body><h2>요청 완료</h2>"
            + hidden(ok, m["done_layer"]) + "</body></html>")


def page_html(path):
    if path == "/home":
        return (f"<html><head><title>홈</title></head><body><h2>{UID}님 환영합니다</h2>"
                f'<a href="/orders">{MODE["menu"]}</a></body></html>')
    if path == "/orders":
        return orders_html()
    if path == "/done":
        return done_html()
    return PAGES.get(path, "<html><body>없음</body></html>")


class Shop(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        path, _, q = self.path.partition("?")
        if path == "/hit":
            HITS.append(q.split("=", 1)[1])
        body = page_html(path).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)


def step(path, text, kind="click", **kw):
    return dict({"kind": kind, "page": 0, "frame": {"main": True, "name": "", "path": path}, "url": path,
                 "target": {"text": text}}, **kw)


def public(c):
    return {k: c[k] for k in ("n", "tag", "role", "type", "text", "label", "where", "overlay")}


def candidates_part(base):
    print("후보 모으기 (가짜 쇼핑몰)")
    with sync_playwright() as p:
        b = rec.edge(p.chromium.launch, headless=True)
        ctx = b.new_context()
        page = ctx.new_page()
        page.goto(base + "/c")
        r = rec.Replayer(ctx, {"steps": []}, {"ID": "user1", "PW": "pw!"}, tempfile.gettempdir(), "000", log=lambda m: None)
        r.pages = {0: page}
        s = step("/c", "엑셀받기")
        cands, windows = r._ai_candidates(0, s, page)
        by = {c["text"] or c["label"]: c for c in cands}
        check("C1 후보에 단추·링크·검색 칸·레이어 단추가 있다",
              all(k in by for k in ("엑셀받기", "다운로드", "주문자 검색", "오늘 하루 보지 않기")), list(by))
        check("C1 레이어 단추만 overlay", [c["text"] for c in cands if c["overlay"]] == ["오늘 하루 보지 않기"],
              [(c["text"], c["overlay"]) for c in cands])
        check("C1 레이어 요소가 앞에, 레이어 글을 container 로", cands[0]["text"] == "오늘 하루 보지 않기" and "점검 안내" in cands[0]["container"],
              cands[0])
        sent = json.dumps([public(c) for c in cands] + windows, ensure_ascii=False)
        check("C2 보내는 글에 입력 값·전화·표 둘레 글이 없다",
              not any(x in sent for x in ("홍길동", "010-1111-2222", "김철수")), sent)
        check("C5 표 줄(tr onclick)과 표 안 이름 링크의 글은 보내지 않는다 - 동작 낱말([다운로드])은 둔다 (최종 검토 I-4)",
              "박영희" not in sent and "강남구" not in sent and "tr" not in [c["tag"] for c in cands] and "다운로드" in sent, sent)
        check("C5 40자에서 잘리는 긴 글의 이메일도 가린다 (자르기 전에 가린다)", "hong.gildong" not in sent and "naver" not in sent, sent)
        check("C2 창 정보에 제목과 레이어 글", windows and windows[0]["no"] == 1 and "점검 안내" in windows[0]["screen"]
              and "주문 관리" in windows[0]["screen"], windows)
        hit = by["엑셀받기"]["loc"]
        check("C2 후보 표시로 그 요소를 집는다", hit.count() == 1 and hit.get_attribute("id") == "xl")
        r._ai_clear()
        check("C3 지우면 표시가 남지 않는다", page.evaluate("document.querySelectorAll('[data-ap-ai]').length") == 0)
        sig = [x for x in json.loads(page.evaluate(rec.SNAP_JS)) if x.startswith("/file")]
        r.baseline = {0: set(sig)}
        cands, _ = r._ai_candidates(0, step("/c", "다운로드", download=True), page)
        check("C4 파일 받기 단계는 기준에 있던 줄을 빼고 모은다",
              len(sig) == 1 and "다운로드" not in [c["text"] for c in cands] and "엑셀받기" in [c["text"] for c in cands],
              (sig, [c["text"] for c in cands]))
        r._ai_clear()
        page.goto(base + "/many")
        cands, windows = r._ai_candidates(0, step("/many", "엑셀받기"), page)
        texts = [c["text"] for c in cands]
        check("C6 링크가 많은 화면에서도 끝에 붙은 레이어 단추가 후보에 든다 (최종 검토 I-1)",
              "오늘 하루 보지 않기" in texts and len(cands) <= ai.CANDIDATES_MAX, (len(cands), texts[:5]))
        ok_btn = next((c for c in cands if c["text"] == "확인"), None)
        check("C7 위험 낱말은 잘리기 전 레이어 글 전체에서 본다 (300자 뒤의 '신청', 최종 검토 I-3)",
              ok_btn is not None and not ai.allowed("confirm", "확인", ok_btn["risk"], "엑셀받기", True, "click", ok_btn)[0],
              ok_btn and ok_btn["risk"][-60:])
        r._ai_clear()
        b.close()


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
    page.wait_for_timeout(300)


def record(base):
    """옛 화면: 홈 → [주문관리] → 검색어 '홍길동' → [엑셀받기] → (완료 화면) [확인]"""
    set_mode()
    with sync_playwright() as p:
        b = rec.edge(p.chromium.launch, headless=True)
        ctx = b.new_context(accept_downloads=True)
        rr = rec.Recorder(ctx)
        page = ctx.new_page()
        page.goto(base + "/home")
        page.wait_for_timeout(300)
        hclick(page, page.get_by_text("주문관리", exact=True))
        page.wait_for_load_state()
        hclick(page, page.locator("#q"))
        page.keyboard.type("홍길동", delay=5)
        page.wait_for_timeout(300)
        hclick(page, page.get_by_role("button", name="엑셀받기"))
        page.wait_for_load_state()
        hclick(page, page.get_by_role("button", name="확인"))
        page.wait_for_timeout(300)
        out = rec.finalize([dict(x) for x in rr.steps], datetime.date(2026, 11, 16), base + "/home")
        b.close()
    return out


class FakeAi:
    """choose 가 차례로 답한다. 답 = (고를 후보 글, info_only) | None(-1) | 던질 예외. 받은 user 글을 모은다."""
    def __init__(self, answers):
        self.answers, self.users = list(answers), []

    def choose(self, system, user):
        self.users.append(user)
        a = self.answers.pop(0) if self.answers else None
        if isinstance(a, Exception):
            raise a
        if a is None:
            return ai.Answer(None, False, "모르겠음", "화면을 알 수 없음")
        text, info = a
        n = next((int(ln[1:].split()[0]) for ln in user.splitlines() if ln.startswith("#") and f"'{text}'" in ln), -1)
        return ai.Answer(None if n < 0 else n, info, f"'{text}' 를 고름", "화면 상태 한 줄")


def replay(record_obj, fake, calls=0):
    logs = []
    with sync_playwright() as p:
        b = rec.edge(p.chromium.launch, headless=True)
        ctx = b.new_context(accept_downloads=True)
        r = rec.Replayer(ctx, record_obj, {"ID": UID, "PW": PW}, tempfile.mkdtemp(prefix="rpa_ai_"), "000", log=logs.append,
                         step_timeout=3, step_tries=2)
        r.ai, r.ai_calls = fake, calls
        try:
            ok = r.run()
        except Exception as e:
            ok = False
            logs.append(f"예외: {type(e).__name__}: {e}")
        try:
            ctx.pages[0].wait_for_timeout(400)
        except Exception:
            time.sleep(0.4)
        b.close()
    fail = next((x[2] for x in r.results if x[1] == "fail"), "")
    return ok, r, fail, logs


def results_text(r):
    return " / ".join(x[2] for x in r.results)


def replay_part(base):
    print("AI 어시스트 재생 (가짜 AI)")
    recd = record(base)
    kinds = [x["kind"] for x in recd["steps"]]
    check("기록: 이동·누르기·넣기·누르기·누르기", kinds[-4:] == ["click", "fill", "click", "click"], kinds)

    set_mode(btn="엑셀 다운로드")
    fake = FakeAi([("엑셀 다운로드", False)])
    ok, r, fail, logs = replay(recd, fake)
    check("R1 바뀐 단추 글을 AI가 골라 이어 간다", ok and HITS == ["excel", "ok"] and r.ai_saved == 1
          and "AI가 고름: '엑셀 다운로드' (기록: '엑셀받기')" in results_text(r), (ok, HITS, r.results, logs[-6:]))
    sent = "\n".join(fake.users)
    check("R11 AI 에게 간 글에 아이디·비밀번호·입력 값·전화·이메일이 없다",
          sent and not any(x in sent for x in (UID, PW, "홍길동", "010-2222-3333", "help@mall.co.kr", "010-1111-2222", "김철수")), sent)

    set_mode(layer="notice")
    ok, r, fail, logs = replay(recd, FakeAi([("오늘 하루 보지 않기", False)]))
    check("R2 덮은 공지를 AI가 닫고 기록대로 누른다", ok and HITS == ["close", "excel", "ok"]
          and "AI가 닫음: '오늘 하루 보지 않기'" in results_text(r), (ok, HITS, r.results, logs[-6:]))

    set_mode(layer="terms")
    ok, r, fail, logs = replay(recd, FakeAi([("동의", False)]))
    check("R3 약관 [동의] 는 AI가 골라도 누르지 않는다", not ok and "agree" not in HITS and "(AI:" in fail, (ok, HITS, fail))

    set_mode(layer="info")
    ok, r, fail, logs = replay(recd, FakeAi([("확인", True)]))
    check("R4 순수 안내의 [확인] 은 누르고 이어 간다", ok and HITS == ["info", "excel", "ok"], (ok, HITS, r.results, logs[-6:]))

    set_mode(layer="apply")
    ok, r, fail, logs = replay(recd, FakeAi([("확인", True)]))
    check("R5 신청을 묻는 레이어의 [확인] 은 누르지 않는다", not ok and "apply" not in HITS, (ok, HITS, fail))

    # 레이어 단추가 [확인] 이면 AI 를 부르기 전에 기존 찾기가 글자로 눌러 버린다 (지금도 그렇다 - 끝 보고의 알려진 한계).
    # 여기서는 AI 가 고른 대신 누르기도 레이어 글의 '신청' 으로 막히는지 본다
    set_mode(done_layer="apply_yes")
    ok, r, fail, logs = replay(recd, FakeAi([("예", False)]))
    check("R6 기록 대상이 [확인] 일 때 신청 레이어의 단추를 AI 가 대신 누르기로 골라도 누르지 않는다", not ok and "apply" not in HITS and HITS == ["excel"],
          (ok, HITS, fail))

    set_mode(btn="엑셀 다운로드", cancel=True)
    ok, r, fail, logs = replay(recd, FakeAi([("주문취소", False)]))
    check("R7 기록에 없던 위험 낱말([주문취소])은 누르지 않는다", not ok and "cancel" not in HITS and "(AI:" in fail, (ok, HITS, fail))

    set_mode(layer="stuck")
    fake = FakeAi([("오늘 하루 보지 않기", False)] * 3)
    ok, r, fail, logs = replay(recd, fake)
    check("R8 같은 미루기 단추를 또 고르면 그만한다", not ok and HITS == ["close"] and len(fake.users) == 2, (ok, HITS, len(fake.users), fail))

    set_mode(btn="엑셀 다운로드", dead=True)
    ok, r, fail, logs = replay(recd, FakeAi([("엑셀 다운로드", False)]))
    check("R9 대신 누른 뒤 아무 일도 없으면 실패", not ok and "AI가 고른 것을 눌렀지만 이어지지 않음" in fail and r.ai_saved == 0,
          (ok, HITS, fail))

    set_mode(btn="엑셀 다운로드", dead=True, ok_here=True)
    ok, r, fail, logs = replay(recd, FakeAi([("엑셀 다운로드", False)]))
    check("R9 다음 단계 대상이 누르기 전부터 보였으면 '이어짐' 으로 치지 않는다 (최종 검토 I-5)",
          not ok and "AI가 고른 것을 눌렀지만 이어지지 않음" in fail and "ok_here" not in HITS, (ok, HITS, fail))

    set_mode(menu="주문 관리 바로가기", btn="엑셀 다운로드")
    ok, r, fail, logs = replay(recd, FakeAi([("주문 관리 바로가기", False), ("엑셀 다운로드", False)]))
    check("R10 연달아 바뀐 두 단계를 모두 살린다", ok and r.ai_saved == 2 and r.ai_calls == 2 and HITS == ["excel", "ok"],
          (ok, HITS, r.ai_saved, r.ai_calls, r.results, logs[-6:]))

    steps = [{"kind": "goto", "href": "x"}, {"kind": "fill", "credential": "ID", "target": {"text": ""}},
             {"kind": "click", "target": {"text": "인증번호 받기"}}, {"kind": "otp", "target": {"text": ""}},
             {"kind": "click", "target": {"text": "확인"}}, {"kind": "click", "target": {"text": "주문관리"}}]
    rr = rec.Replayer(None, {"steps": steps}, {}, tempfile.gettempdir(), "000", log=lambda m: None)
    rr.ai = FakeAi([])
    check("R12 인증 구간 안 단계는 AI를 부르지 않고 그 뒤는 부른다",
          [rr._ai_ok(i, x) for i, x in enumerate(steps)] == [False, False, False, False, False, True],
          [rr._ai_ok(i, x) for i, x in enumerate(steps)])

    steps = [{"kind": "click", "page": 0, "target": {"text": "로그인"}, "opens": 1},
             {"kind": "click", "page": 1, "target": {"text": "닫기"}}, {"kind": "click", "page": 0, "target": {"text": "주문관리"}}]
    rr = rec.Replayer(None, {"steps": steps}, {}, tempfile.gettempdir(), "000", log=lambda m: None)
    rr.ai = FakeAi([])
    check("R12 공지 창의 [닫기] 단계는 AI 에 맡기지 않는다 (공지가 안 뜬 날 건너뛰는 단계)",
          [rr._ai_ok(i, x) for i, x in enumerate(steps)] == [True, False, True], [rr._ai_ok(i, x) for i, x in enumerate(steps)])

    set_mode(btn="엑셀 다운로드")
    fake = FakeAi([ai.AiUnavailable("시간 초과")])
    ok, r, fail, logs = replay(recd, fake)
    check("R13 AI를 못 쓰면 실패 사유 끝에 까닭, 그 뒤는 부르지 않는다",
          not ok and fail.endswith("(AI 어시스트를 쓰지 못함: 시간 초과)") and not r._ai_ok(3, recd["steps"][3]) and len(fake.users) == 1,
          (ok, fail, len(fake.users)))

    ok, r, fail, logs = replay(recd, None)
    check("R15 AI가 없으면 지금과 같은 실패 글", not ok and "초씩 2번 찾았으나" in fail and "(AI" not in fail, fail)

    set_mode(menu="주문 관리 바로가기", btn="엑셀 다운로드")
    fake = FakeAi([("주문 관리 바로가기", False), ("엑셀 다운로드", False)])
    ok, r, fail, logs = replay(recd, fake, calls=ai.RUN_CALLS_MAX - 1)
    check("R16 사이트 한 번에 부르는 수를 넘지 않는다", not ok and len(fake.users) == 1 and r.ai_calls == ai.RUN_CALLS_MAX,
          (ok, len(fake.users), r.ai_calls, fail))


def settings_part():
    print("PC 설정 (ai.json)")
    import rpa_status as st
    import web_runner
    tmp = tempfile.mkdtemp(prefix="rpa_ai_cfg_")
    keep = st.data_dir
    st.data_dir = lambda: tmp
    try:
        path = os.path.join(tmp, st.AI_NAME)
        st.set_ai(True, "sk-test")
        raw = open(path, encoding="utf-8").read()
        check("P1 키는 잠가 적고 풀어 읽는다", "sk-test" not in raw and json.loads(raw)["key"].startswith("dpapi:")
              and st.ai_settings() == {"on": True, "key": "sk-test"}, raw)
        t = os.path.getmtime(path)
        st.set_ai(True, "sk-test")
        check("P1 같은 값이면 다시 쓰지 않는다", os.path.getmtime(path) == t)
        st.set_ai(False, None)
        check("P2 끄면 키를 지운다", st.ai_settings() == {"on": False} and "key" not in json.loads(open(path, encoding="utf-8").read()))
        open(path, "w", encoding="utf-8").write("{깨짐")
        check("P3 깨진 파일이면 None", st.ai_settings() is None)
        logs = []
        keep_log = web_runner.log
        web_runner.log = logs.append
        try:
            rp = SimpleNamespace(ai="x")
            st.set_ai(True, "sk-test")
            web_runner.attach_ai(rp, "몰")
            check("P4 켜져 있으면 ACTOR 재생기에 AI 를 붙이고 키는 로그에 없다",
                  isinstance(rp.ai, ai.Claude) and logs == ["  [몰] AI 어시스트 사용"], (rp.ai, logs))
            os.remove(path)
            web_runner.attach_ai(rp, "몰")
            check("P4 설정이 없으면 AI 없음", rp.ai is None)
            keep_fs = web_runner.ai_rescue.from_settings

            def broken(*a, **k):
                raise ModuleNotFoundError("No module named 'httpcore2'")
            web_runner.ai_rescue.from_settings = broken
            logs.clear()
            try:
                web_runner.attach_ai(rp, "몰")
            except Exception as e:
                logs.append(f"예외 {e}")
            finally:
                web_runner.ai_rescue.from_settings = keep_fs
            check("P5 AI 준비가 실패해도 재생은 AI 없이 간다 (최종 검토 I-6)",
                  rp.ai is None and logs and "AI 어시스트를 쓰지 못함" in logs[0], logs)
        finally:
            web_runner.log = keep_log
    finally:
        st.data_dir = keep


if __name__ == "__main__":
    no_browser()
    settings_part()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Shop)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    candidates_part(base)
    replay_part(base)
    srv.shutdown()
    print("\n실패:", fails if fails else "없음")
    sys.exit(1 if fails else 0)
