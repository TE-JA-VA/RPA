# -*- coding: utf-8 -*-
"""재생이 글자로 찾기 (2026-10-16, 프리셋 3·6 비즈메카·빙에서 2분씩 못 찾고 멈춤) - 창은 뜨지 않는다.

1. 글자가 안쪽 칸(div·span)에 든 링크: 빙 광고 제목 <a><div>비즈메카이지</div></a> - :text-is 는 못 잡는다
2. 숫자가 따로 칸에 든 메뉴: 비즈메카 '메일 5' <a><span>메일</span> <em>5</em></a> (기록 때 '메일 1')
3. 예전 단서로 찾던 것은 예전 단서 그대로 (새 단서는 맨 뒤)
4. 화면이 넘어간 바로 뒤 마우스만 올린 단계 뒤로 '새로 생긴 것' 이 적힌 것 (늦게 그려진 카드) - 원래 있던 것에서도 찾는다.
   다른 단계 뒤로 적힌 것은 예전처럼 새로 생긴 것만
5. 글자가 숫자뿐인 받기 링크: 현대이지웰 주문 수 '3' → '6' (2026-11-05 27단계에서 멈춤). 쪽 번호는 예전처럼 다른 것으로 본다
    .venv\\Scripts\\python.exe tests\\test_find_nested_text.py
"""
import json
import os
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from playwright.sync_api import sync_playwright  # noqa: E402

import web_replay as rec  # noqa: E402

fails = []


def check(name, ok, detail=""):
    print(f"  [{'통과' if ok else '실패'}] {name}" + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


def target(text, index=0, count=1, css="body > div:nth-of-type(9) > a"):
    return {"tag": "a", "id": "", "name": "", "type": "", "text": text, "textIndex": index, "textCount": count, "aria": "",
            "title": "", "placeholder": "", "label": "", "labelIndex": 0, "labelKind": "", "href": "#a", "css": css}


def step(t, kind="click", url="/main", after=None):
    s = {"kind": kind, "page": 0, "frame": {"main": True, "name": "", "path": url}, "url": url, "target": t}
    if after is not None:
        s["appearsAfter"] = after
    return s


HTML = """<!doctype html><meta charset="utf-8">
<div><a href="#a" id="ad1"><div>비즈메카! kt 비즈오피스</div></a></div>
<div><a href="#a" id="ad2"><div>비즈메카이지</div></a> <a href="#a" id="ad3"><div>비즈메카이지</div></a></div>
<div><a href="#a" id="top"><i></i><span>메일</span> <em>5</em></a> <a href="#a" id="card"><span>메일</span>
   <em>5</em></a> <a href="#a" id="plain">확인</a></div>"""

print("=== 1~3. 글자로 찾기")
with sync_playwright() as p:
    b = rec.edge(p.chromium.launch, headless=True)
    ctx = b.new_context()
    page = ctx.new_page()
    page.set_content(HTML)
    rp = rec.Replayer(ctx, {"steps": []}, {}, tempfile.mkdtemp(), "000", log=lambda m: None, step_timeout=3, step_tries=1)
    rp.pages[0] = page

    took = [0.0]

    def find(t, prev=None, loose=False):
        s = step(t)
        t0 = time.time()
        try:
            _, loc, how = rp._find(page, s, prev, loose)
            return loc.evaluate("e => e.id"), how
        except rec.NotFound:
            return None, None
        finally:
            took[0] = time.time() - t0

    got = find(target("비즈메카이지", 1, 2))
    check("안쪽 칸에 든 글자 - 같은 글자 둘 중 기록한 2번째", got == ("ad3", "글자(안쪽 포함)"), str(got))
    check(f"새 단서는 {rec.LATE_CLUE_WAIT:.0f}초 찾아도 없을 때부터 (화면이 덜 뜬 사이 옛 화면의 다른 것을 집지 않게)",
          took[0] >= rec.LATE_CLUE_WAIT, f"{took[0]:.1f}초")
    got = find(target("메일 1", 1, 2))
    check("숫자가 바뀌고 따로 칸에 든 '메일 N' - 둘 중 2번째(카드)", got[0] == "card" and got[1].startswith("숫자 뺀 글자"), str(got))
    got = find(target("확인"))
    check("글자가 바로 든 것은 예전 단서 '글자' 그대로 - 기다리지 않고", got == ("plain", "글자") and took[0] < 1, f"{got} {took[0]:.1f}초")
    got = find(target("없는 글자"))
    check("없는 것은 그대로 못 찾는다", got == (None, None), str(got))

    print("=== 4. 마우스만 올린 뒤의 '새로 생긴 것'")
    base = set(json.loads(page.evaluate(rec.SNAP_JS)))      # 카드가 이미 있는 화면 = 원래 있던 것
    got = find(target("메일 1", 1, 2), base, loose=False)
    check("예전 방식(새로 생긴 것만)은 못 찾는다", got == (None, None), str(got))
    got = find(target("메일 1", 1, 2), base, loose=True)
    check("loose 면 원래 있던 것에서도 찾는다", got[0] == "card" and got[1].startswith("숫자 뺀 글자"), str(got))

    print("=== 5. 숫자뿐인 글자가 바뀐 받기 링크")
    page.set_content('<div><a href="#a" id="cnt">6</a></div><div><a href="#a" class="n">6</a></div><div><a href="#a" id="st">처리중</a></div>')

    def num(text, id_="", css="body > div:nth-of-type(9) > a", download=None):
        s = step(dict(target(text, css=css), id=id_, href=""))
        if download:
            s["download"] = download
        try:
            _, loc, how = rp._find(page, s, None)
            return loc.evaluate("e => e.id || e.className"), how
        except rec.NotFound:
            return None, None

    got = num("3", "cnt")
    check("id 가 같으면 주문 수 '3' → '6' 이어도 그것", got == ("cnt", "id"), str(got))
    got = num("3", css="body > div:nth-of-type(2) > a", download="주문목록.xlsx")
    check("받기 단계는 위치가 같아도 그것", got == ("n", "위치"), str(got))
    got = num("3", css="body > div:nth-of-type(2) > a")
    check("받기가 아니면 위치만으로는 안 된다 (쪽 번호 '3' 자리의 '6' 을 누르면 안 된다)", got == (None, None), str(got))
    got = num("3", "st")
    check("숫자가 글자로 바뀐 것은 id 가 같아도 다른 것", got == (None, None), str(got))
    b.close()

t2 = target("메일 1", 1, 2)
login = step(target("로그인"), url="/login")
hover = step(target("게시판 삭제"), kind="hover")
check("로그인(화면 넘김) → 마우스 올리기 → '마우스 올리기 뒤 새로 생긴 것' 이면 loose",
      rec.loose_new([login, hover, step(t2, after=1)], 2))
check("마우스 올리기 둘이어도", rec.loose_new([login, hover, hover, step(t2, after=2)], 3))
check("누르기 뒤 새로 생긴 것은 예전 그대로 (새로 생긴 것만)",
      not rec.loose_new([login, step(target("조회")), step(t2, after=1)], 2))
mail = step(target("메일"), url="/main")
mail["opens"] = 2
hv2, t3 = dict(hover, page=2, url="/list"), dict(step(t2, url="/list", after=1), page=2)
check("새 창을 연 누르기 → 그 창에서 마우스 올리기 → 그 창의 '새로 생긴 것' 이면 loose (네이버 메일 목록)", rec.loose_new([mail, hv2, t3], 2))
check("다른 창을 연 누르기 뒤면 예전 그대로", not rec.loose_new([dict(mail, opens=3), hv2, t3], 2))
check("같은 화면 안의 마우스 올리기 뒤 (화면 넘김 없음)은 예전 그대로",
      not rec.loose_new([step(target("메뉴")), hover, step(t2, after=1)], 2))

print()
print("실패:", fails or "없음")
sys.exit(1 if fails else 0)
