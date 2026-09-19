"""find_mail_row 시험 - 메일 목록에서 data-key 로 행을 다시 찾는 부분.

브라우저 없이 가짜 페이지로만 돌린다. 실제 메일함에 접속하지 않는다.

배경: collect_unread_mails 는 '안읽음' 으로 거른 목록을 여러 쪽 훑어 key 를 모은다.
      그런데 메일을 열려고 MailURL 로 돌아오면 걸러보기가 풀린 1쪽이다.
      읽은 '>>>' 메일이 쌓인 메일함에서는 거기에 대상이 없어서 못 찾았다.
      (2026-09-18 시연 PC, 2건 모두 실패)

    .venv\\Scripts\\python.exe tests\\test_mail_find.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

import web_runner as wr

PWTimeout = wr.PWTimeout


class FakeLocator:
    def __init__(self, n, on_click=None):
        self._n = n
        self._on_click = on_click

    def count(self):
        return self._n

    def click(self):
        if self._on_click:
            self._on_click()


class FakePage:
    """쪽마다 보이는 key 목록을 들고 있는 가짜 목록 화면.

    pages: 걸러보기를 걸기 전/후로 나눠 넣는다.
      {"plain": [[key,...], ...], "unread": [[key,...], ...]}
    """

    def __init__(self, plain, unread, rows_render=True):
        self.plain = plain
        self.unread = unread
        self.filtered = False
        self.page_no = 0
        self.rows_render = rows_render
        self.clicks = []          # 무엇을 눌렀는지 기록
        self.waited = 0

    # --- 지금 화면에 보이는 key 들 ---
    def _visible(self):
        book = self.unread if self.filtered else self.plain
        if self.page_no >= len(book):
            return []
        return book[self.page_no]

    # --- Playwright 흉내 ---
    def wait_for_selector(self, sel, timeout=None):
        if not self.rows_render or not self._visible():
            raise PWTimeout("li.m_data 가 안 나타났다")
        return object()

    def locator(self, sel):
        key = sel.split('data-key="')[1].rstrip('"]')
        return FakeLocator(1 if key in self._visible() else 0)

    def wait_for_load_state(self, state, timeout=None):
        pass

    def wait_for_timeout(self, ms):
        self.waited += ms

    # --- 버튼 ---
    def click_filter(self):
        self.clicks.append("안읽음")
        self.filtered = True
        self.page_no = 0

    def click_next(self):
        self.clicks.append("다음")
        self.page_no += 1


def fake_find_clickable(page, texts):
    """web_runner.find_clickable_by_texts 를 대신한다."""
    if "안읽음" in texts:
        if page.filtered:
            return None, "이미 걸러져 있음"
        return FakeLocator(1, page.click_filter), "가짜 안읽음"
    # 다음 쪽
    book = page.unread if page.filtered else page.plain
    if page.page_no + 1 >= len(book):
        return None, "마지막 쪽"
    return FakeLocator(1, page.click_next), "가짜 다음"


wr.find_clickable_by_texts = fake_find_clickable
wr.log = lambda *a, **k: None     # 시험 중에는 조용히

fails = []


def check(no, name, cond, detail=""):
    mark = "통과" if cond else "실패"
    print(f"  {no:2d}. [{mark}] {name}" + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(f"{no}. {name} {detail}")


print("=== find_mail_row 시험 ===")

# 1. 걸러보기 없이 1쪽에 바로 있다
p = FakePage(plain=[["K1", "K2"]], unread=[["K1"]])
check(1, "1쪽에 있으면 바로 찾는다", wr.find_mail_row(p, "T", "K1") is True)
check(2, "그때는 아무것도 누르지 않는다", p.clicks == [], f"눌린 것: {p.clicks}")

# 3. 1쪽에 없고 '안읽음' 을 걸면 나온다 (읽은 메일이 1쪽을 채운 경우)
p = FakePage(plain=[["R1", "R2", "R3"]], unread=[["K9"]])
check(3, "1쪽에 없으면 '안읽음' 을 걸어 찾는다", wr.find_mail_row(p, "T", "K9") is True)
check(4, "'안읽음' 을 한 번 눌렀다", p.clicks == ["안읽음"], f"눌린 것: {p.clicks}")

# 5. 걸러도 1쪽에 없고 2쪽에 있다
p = FakePage(plain=[["R1"]], unread=[["U1", "U2"], ["K7"]])
check(5, "걸러진 2쪽까지 넘겨서 찾는다", wr.find_mail_row(p, "T", "K7") is True)
check(6, "'안읽음' 다음 '다음' 순서로 눌렀다", p.clicks == ["안읽음", "다음"], f"눌린 것: {p.clicks}")

# 7. 걸러진 3쪽에 있다
p = FakePage(plain=[["R1"]], unread=[["U1"], ["U2"], ["K3"]])
check(7, "3쪽까지도 넘어간다", wr.find_mail_row(p, "T", "K3") is True)
check(8, "'다음' 을 두 번 눌렀다", p.clicks.count("다음") == 2, f"눌린 것: {p.clicks}")

# 9. 어디에도 없다
p = FakePage(plain=[["R1"]], unread=[["U1"], ["U2"]])
check(9, "없으면 False 를 돌려준다", wr.find_mail_row(p, "T", "없는키") is False)
check(10, "마지막 쪽에서 멈춘다 (무한 반복 안 함)", p.clicks.count("다음") == 1, f"눌린 것: {p.clicks}")

# 11. 쪽 수가 아주 많아도 MAIL_MAX_PAGES 에서 멈춘다
many = [[f"U{i}"] for i in range(100)]
p = FakePage(plain=[["R1"]], unread=many)
check(11, "쪽이 많아도 끝난다", wr.find_mail_row(p, "T", "없는키") is False)
check(12, f"{wr.MAIL_MAX_PAGES}쪽 넘게 넘기지 않는다",
      p.clicks.count("다음") <= wr.MAIL_MAX_PAGES - 1, f"넘긴 횟수: {p.clicks.count('다음')}")

# 13. 목록이 아예 안 그려지는 경우 (화면이 안 뜨거나 로그인이 풀린 경우)
p = FakePage(plain=[["K1"]], unread=[["K1"]], rows_render=False)
check(13, "목록이 안 그려지면 False", wr.find_mail_row(p, "T", "K1") is False)

# 14. 이미 걸러진 상태로 들어와도 동작한다
p = FakePage(plain=[["R1"]], unread=[["U1"], ["K5"]])
p.filtered = True
check(14, "이미 걸러져 있으면 '다음' 만으로 찾는다", wr.find_mail_row(p, "T", "K5") is True)
check(15, "'안읽음' 을 다시 누르지 않는다", "안읽음" not in p.clicks, f"눌린 것: {p.clicks}")

print()
print(f"실패: {'없음' if not fails else fails}")
sys.exit(1 if fails else 0)
