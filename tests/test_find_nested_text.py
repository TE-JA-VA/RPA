# -*- coding: utf-8 -*-
"""재생이 글자로 찾기 (2026-10-16, 프리셋 3·6 비즈메카·빙에서 2분씩 못 찾고 멈춤) - 창은 뜨지 않는다.

1. 글자가 안쪽 칸(div·span)에 든 링크: 빙 광고 제목 <a><div>비즈메카이지</div></a> - :text-is 는 못 잡는다
2. 숫자가 따로 칸에 든 메뉴: 비즈메카 '메일 5' <a><span>메일</span> <em>5</em></a> (기록 때 '메일 1')
3. 예전 단서로 찾던 것은 예전 단서 그대로 (새 단서는 맨 뒤)
4. 화면이 넘어간 바로 뒤 마우스만 올린 단계 뒤로 '새로 생긴 것' 이 적힌 것 (늦게 그려진 카드) - 원래 있던 것에서도 찾는다.
   다른 단계 뒤로 적힌 것은 예전처럼 새로 생긴 것만
    .venv\\Scripts\\python.exe tests\\test_find_nested_text.py
"""
import json
import os
import sys
import tempfile

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
    rp = rec.Replayer(ctx, {"steps": []}, {}, tempfile.mkdtemp(), "000", log=lambda m: None, step_timeout=1, step_tries=1)
    rp.pages[0] = page

    def find(t, prev=None, loose=False):
        s = step(t)
        try:
            _, loc, how = rp._find(page, s, prev, loose)
            return loc.evaluate("e => e.id"), how
        except rec.NotFound:
            return None, None

    got = find(target("비즈메카이지", 1, 2))
    check("안쪽 칸에 든 글자 - 같은 글자 둘 중 기록한 2번째", got == ("ad3", "글자(안쪽 포함)"), str(got))
    got = find(target("메일 1", 1, 2))
    check("숫자가 바뀌고 따로 칸에 든 '메일 N' - 둘 중 2번째(카드)", got[0] == "card" and got[1].startswith("숫자 뺀 글자"), str(got))
    got = find(target("확인"))
    check("글자가 바로 든 것은 예전 단서 '글자' 그대로", got == ("plain", "글자"), str(got))
    got = find(target("없는 글자"))
    check("없는 것은 그대로 못 찾는다", got == (None, None), str(got))

    print("=== 4. 마우스만 올린 뒤의 '새로 생긴 것'")
    base = set(json.loads(page.evaluate(rec.SNAP_JS)))      # 카드가 이미 있는 화면 = 원래 있던 것
    got = find(target("메일 1", 1, 2), base, loose=False)
    check("예전 방식(새로 생긴 것만)은 못 찾는다", got == (None, None), str(got))
    got = find(target("메일 1", 1, 2), base, loose=True)
    check("loose 면 원래 있던 것에서도 찾는다", got[0] == "card" and got[1].startswith("숫자 뺀 글자"), str(got))
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
