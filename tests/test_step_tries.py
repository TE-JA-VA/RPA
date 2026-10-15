"""옵저버 재생: 못 찾으면 STEP_WAIT 초씩 STEP_TRIES 번 다시 찾고 포기 (사용자 2026-10-15 - 20초씩 6번). 브라우저 없이 가짜 창으로."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import web_replay as rec

fails = []


def check(name, ok, info=""):
    print(("통과 " if ok else "실패 ") + name + ("" if ok else f"  ({info})"))
    ok or fails.append(name)


class Loc:
    def __init__(self, page):
        self.page = page

    def count(self):
        return 1 if time.time() >= self.page.show_at else 0

    def nth(self, i):
        return self


class Frame:
    def __init__(self, page):
        self.page = page

    def locator(self, sel):
        return Loc(self.page)


class Page:
    def __init__(self, show_after):
        self.show_at = time.time() + show_after
        self.main_frame = Frame(self)

    def wait_for_timeout(self, ms):
        time.sleep(ms / 1000)


rec.candidates = lambda t: [("아이디", "#x", None)]
STEP = {"kind": "click", "target": {}, "frame": {"main": True}}


def run(show_after, tries):
    lines = []
    rp = rec.Replayer(None, {"steps": []}, {}, ".", "000", log=lines.append, step_timeout=0.3, step_tries=tries)
    rp._same = lambda loc, t, digits=False: True
    try:
        rp._find(Page(show_after), STEP, None)
        return "찾음", lines
    except rec.NotFound as e:
        return str(e), lines


check("기본값은 20초씩 6번", (rec.STEP_WAIT, rec.STEP_TRIES) == (20.0, 6) and
      rec.Replayer(None, {"steps": []}, {}, ".", "000").step_tries == 6)
res, lines = run(99, 3)
check("끝내 없으면 3번 찾고 포기, 사이에 '다시 찾습니다 (2/3)·(3/3)' 를 남긴다",
      "0초씩 3번 찾아도 못 찾음" in res and [l.strip() for l in lines] ==
      ["0초 안에 못 찾음 - 다시 찾습니다 (2/3)", "0초 안에 못 찾음 - 다시 찾습니다 (3/3)"], f"{res} {lines}")
res, lines = run(0.7, 3)
check("두 번째 기다림 중에 나타나면 찾고 이어간다", res == "찾음" and len(lines) == 1, f"{res} {lines}")
res, lines = run(99, 1)
check("step_tries=1 이면 예전처럼 한 번만 (시험용)", "1번 찾아도 못 찾음" in res and not lines, f"{res} {lines}")

print(f"\n{'모두 통과' if not fails else f'실패 {len(fails)}건'}")
sys.exit(1 if fails else 0)
