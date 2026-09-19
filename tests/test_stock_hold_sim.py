# -*- coding: utf-8 -*-
"""재고검토 배송보류 선별(prepare_bottom_checks) 시뮬레이션 시험 (2026-09-17 개편).

ERPia 없이 돈다. 하단 그리드를 흉내 낸 가짜 그리드에 대고 돌려서,
사용자가 정한 방식(오름차순 정렬 -> 일치 구간 범위선택 -> '선택영역 체크')대로
'상품코드가 일치하는 연속 구간만' 선택·체크하고 우클릭할 셀을 돌려주는지 본다.

새 설계 원칙 (사용자 지시):
  - 정렬은 헤더의 DefaultAction 속성으로 확정한다 (값 추측 안 함, 스크롤 안 함).
  - 정렬이 안 됐거나 범위선택이 어긋나면 '개별 체크로 도망가지 않고' 그 건을 건너뛴다.
  - 하단 그리드를 처음부터 끝까지 훑는 검증(sweep)도, 한 행씩 클릭하는 폴백도 쓰지 않는다.

가짜 그리드는 실제에서 겪은 것들을 흉내 낸다.
  - 행 요소는 '화면 슬롯' 이라 스크롤하면 다른 행을 가리킨다 (가상화)
  - Shift+클릭은 마지막으로 클릭한 행을 기준으로 범위를 잡는다
  - 헤더 클릭은 오름차순 정렬을 '적용' 하고, DefaultAction 이 '내림차순 정렬' 로 바뀐다
  - 우클릭 메뉴에 항목이 없는 경우
"""
import io
import sys
import time as _time
import types

sys.path.insert(0, r"D:\AX\RPA")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import run_routine as rr  # noqa: E402

CODE_COL = "ERP상품코드"
CB_COL = rr.GRID_CHECKBOX_COL
X_CODE, CB_X, TOP_Y, RH = 1700, 380, 400, 20
GEO = (X_CODE, TOP_Y, TOP_Y + 200, RH)

# 실제 헤더 DefaultAction 값과 똑같이 맞춘다 (2026-09-17 실측).
DA_ASC = rr.SORT_DA_ASCENDING      # '내림차순 정렬'  <- 지금 오름차순
DA_NONE = rr.SORT_DA_UNSORTED      # '오름차순 정렬'  <- 정렬 안 됨

fails = []


def check(cond, what):
    print(("PASS " if cond else "FAIL ") + what)
    if not cond:
        fails.append(what)


class Rect:
    def __init__(self, top):
        self.top, self.bottom, self.left, self.right = top, top + RH, 1000, 1100

    def __str__(self):
        return f"(T{self.top}, B{self.bottom})"


class FakeCell:
    """화면 슬롯을 가리키는 셀. 스크롤하면 같은 슬롯이 다른 행을 가리킨다 (가상화)."""

    def __init__(self, grid, slot, kind):
        self.grid, self.slot, self.kind = grid, slot, kind

    @property
    def row(self):
        i = self.grid.top + self.slot
        return i if 0 <= i < len(self.grid.rows) else None

    def window_text(self):
        return f"{CB_COL} 행 {self.slot}" if self.kind == "cb" else f"{CODE_COL} 행 {self.slot}"

    def value(self):
        r = self.row
        if r is None:
            return None
        if self.kind == "cb":
            return "선택" if self.grid.rows[r]["checked"] else ""
        return self.grid.rows[r]["code"]

    def rectangle(self):
        return Rect(TOP_Y + self.slot * RH)

    def click_input(self, button="left", pressed=None):
        r = self.row
        if r is None:
            return
        g = self.grid
        g.clicks.append((self.kind, r, pressed or button))
        if self.kind == "cb":
            g.rows[r]["checked"] = not g.rows[r]["checked"]
            g.anchor, g.selection = r, {r}
            return
        if pressed == "shift" and g.anchor is not None:
            lo, hi = min(g.anchor, r), max(g.anchor, r)
            g.selection = set(range(lo, hi + 1))
            return
        if g.ignore_first_plain_click:
            g.ignore_first_plain_click = False      # 클릭이 먹지 않은 척 (화면 다시 그리는 중)
            return
        g.anchor, g.selection = r, {r}


class FakeHeader:
    """DevExpress 헤더 흉내. legacy_properties()['DefaultAction'] 로 정렬 상태를 알려준다."""

    def __init__(self, grid):
        self.grid = grid

    def rectangle(self):
        return Rect(TOP_Y - RH)

    def legacy_properties(self):
        return {"DefaultAction": DA_ASC if self.grid.sort_applied else DA_NONE}

    def click_input(self, **kw):
        g = self.grid
        g.rows.sort(key=lambda row: row["code"])
        g.selection, g.anchor = set(), None      # 정렬하면 선택이 흐트러진다
        g.sort_applied = True
        g.sorted_clicks += 1


class FakeGrid:
    def __init__(self, codes, page=5, step=3, checked=(), menu_missing=(),
                 ignore_first_plain_click=False, header=True, sort_applied=False,
                 edge_last_none=False):
        self.rows = [{"code": c, "checked": i in set(checked)} for i, c in enumerate(codes)]
        self.page, self.step, self.top = page, step, 0
        self.anchor, self.selection = None, set()
        self.menu_missing = set(menu_missing)
        self.ignore_first_plain_click = ignore_first_plain_click
        self.has_header = header
        # 정렬이 이미 적용돼 있다고 볼지. 헤더가 없으면 정렬을 걸 수 없다.
        self.sort_applied = sort_applied
        # from_top=False probe 가 첫 페이지에서 None 을 주는 상황(데이터 1행이 맨 위)
        self.edge_last_none = edge_last_none
        self.clicks, self.holds, self.sorted_clicks = [], [], 0

    def visible(self):
        return list(range(self.top, min(self.top + self.page, len(self.rows))))

    def checked_rows(self):
        return {i for i, r in enumerate(self.rows) if r["checked"]}

    def codes_checked(self):
        return sorted(r["code"] for r in self.rows if r["checked"])


# ---------------------------------------------------------------- 가짜 화면 함수들
def fake_scan_column(geo, col_name):
    g = CURRENT[0]
    return [(TOP_Y + slot * RH, g.rows[i]["code"], FakeCell(g, slot, "code"))
            for slot, i in enumerate(g.visible())]


def fake_probe_edge_row(geo, col_name, from_top=True):
    g = CURRENT[0]
    # 실제로는 좌표 stride 때문에, 데이터 행이 하나뿐이고 맨 위에 있으면
    # 아래에서부터 읽는(from_top=False) probe 가 그 행을 못 집어 None 을 준다.
    # 그 비대칭을 흉내 내, 위는 값·아래는 None 인 경우를 재현한다.
    if getattr(g, "edge_last_none", False) and not from_top and g.top == 0:
        return None, None
    rows = [(y, v, el) for y, v, el in fake_scan_column(geo, col_name) if v]
    if not rows:
        return None, None
    y, v, el = rows[0] if from_top else rows[-1]
    return v, el


def fake_element_at_point(x, y):
    g = CURRENT[0]
    slot = (y - TOP_Y) // RH
    if slot < 0 or slot >= len(g.visible()):
        raise RuntimeError("그 자리에 요소가 없습니다")
    return FakeCell(g, slot, "cb" if x == CB_X else "code")


def fake_legacy_value(el):
    return el.value()


def fake_scroll_to_top(hwnd, grid, **kw):
    grid.top = 0


def fake_page_down(hwnd, grid, geo=None, col_name=None):
    """'페이지 아래로' 한 번: 한 페이지(page)만큼 내린다. 겹치지 않는다(100%)."""
    if grid.top + grid.page >= len(grid.rows):
        return False
    grid.top = min(grid.top + grid.page, max(0, len(grid.rows) - grid.page))
    return True


def fake_page_up(hwnd, grid):
    """'페이지 위로' 한 번: 한 페이지만큼 올린다."""
    if grid.top <= 0:
        return False
    grid.top = max(0, grid.top - grid.page)
    return True


def fake_find_jump(pid, hwnd, grid, code_col, code, geo):
    """찾기(Ctrl+F) 흉내: 현재 순서에서 code 의 첫 등장 위치가 화면 맨 위에 오게 점프한다.
    (오름차순이면 그게 덩어리 맨 위다.) code 가 없으면 False."""
    idx = next((i for i, r in enumerate(grid.rows) if r["code"] == code), None)
    if idx is None:
        return False
    grid.jumped = idx
    grid.top = min(idx, max(0, len(grid.rows) - grid.page))
    return True


def fake_grid_header(grid, col_name):
    return FakeHeader(grid) if grid.has_header else None


def fake_right_click(pid, hwnd, element, menu_text, wait=1.5):
    g = CURRENT[0]
    if menu_text in g.menu_missing:
        return False
    if menu_text == "선택영역 체크":
        for i in g.selection:
            g.rows[i]["checked"] = True
        return True
    if menu_text == "배송보류":
        g.holds.append(sorted(g.checked_rows()))
        return True
    return False


CURRENT = [None]


def install(grid, cb_x=CB_X):
    CURRENT[0] = grid
    rr.scan_column = fake_scan_column
    rr.probe_edge_row = fake_probe_edge_row
    rr.element_at_point = fake_element_at_point
    rr.legacy_value = fake_legacy_value
    rr.grid_scroll_to_top = fake_scroll_to_top
    rr.grid_page_down = fake_page_down
    rr.grid_page_up = fake_page_up
    rr.find_jump_to_code = fake_find_jump
    rr.grid_header = fake_grid_header
    rr.right_click_element_and_select = fake_right_click
    rr.find_bottom_code_column = lambda grid_, code_: CODE_COL
    rr._column_scan_geometry = lambda grid_, col_: GEO
    rr.ec = types.SimpleNamespace(ensure_foreground=lambda *a, **k: True)
    rr.time = types.SimpleNamespace(sleep=lambda *_: None, time=_time.time, strftime=_time.strftime)
    rr.log = lambda msg="": None        # 시험 출력이 지저분해지지 않게
    return grid


def run(grid, code, cb_x=CB_X):
    install(grid, cb_x)
    anchor, used_fast = rr.prepare_bottom_checks(1, 1, grid, code, CODE_COL, GEO, cb_x)
    return anchor, used_fast


# ---------------------------------------------------------------- 시험
print("=== 1. 정렬 안 된 그리드 -> 헤더로 오름차순 확정 -> 구간 범위선택 ===")
g = FakeGrid(["800", "100", "700", "200", "700", "900", "700"])   # 무순서
anchor, fast = run(g, "700")
check(anchor is not None and fast, f"정렬 후 범위선택 성공 (anchor={anchor is not None}, fast={fast})")
check(g.sorted_clicks >= 1, f"헤더를 눌러 정렬함 (클릭 {g.sorted_clicks}회)")
check(g.codes_checked() == ["700", "700", "700"], f"대상만 체크됨: {g.codes_checked()}")

print("\n=== 2. 이미 오름차순인 그리드 -> 헤더 클릭 없이 바로 범위선택 ===")
g = FakeGrid(["100", "200", "700", "700", "700", "800", "900"], sort_applied=True)
anchor, fast = run(g, "700")
check(anchor is not None and fast, f"범위선택 성공 (fast={fast})")
check(g.sorted_clicks == 0, f"이미 오름차순이라 헤더를 누르지 않음 (클릭 {g.sorted_clicks}회)")
check(g.checked_rows() == {2, 3, 4}, f"체크된 행: {sorted(g.checked_rows())}")

print("\n=== 3. 대상 구간이 여러 페이지에 걸침 ===")
g = FakeGrid(["100", "200", "700", "700", "700", "700", "700", "800", "900"],
             page=4, step=3, sort_applied=True)
anchor, fast = run(g, "700")
check(anchor is not None and fast, "여러 페이지 구간도 범위선택 성공")
check(g.codes_checked() == ["700"] * 5, f"대상만 체크됨: {g.codes_checked()}")

print("\n=== 4. 헤더가 없어 정렬을 걸 수 없음 -> 건너뜀 (개별 체크로 도망가지 않음) ===")
g = FakeGrid(["100", "200", "700", "650", "700", "800"], header=False)
anchor, fast = run(g, "700")
check(anchor is None and not fast, f"배송보류하지 않고 건너뜀 (anchor={anchor})")
check(g.checked_rows() == set(), f"아무 체크도 하지 않음: {sorted(g.checked_rows())}")

print("\n=== 5. 우클릭 메뉴에 '선택영역 체크'가 없음 -> 건너뜀 ===")
g = FakeGrid(["100", "200", "700", "700", "700", "800", "900"], sort_applied=True,
             menu_missing=["선택영역 체크"])
anchor, fast = run(g, "700")
check(anchor is None and not fast, f"건너뜀 (anchor={anchor})")
check(g.checked_rows() == set(), f"아무 체크도 하지 않음: {sorted(g.checked_rows())}")

print("\n=== 6. 대상 행이 아예 없음 -> 건너뜀 ===")
g = FakeGrid(["100", "200", "300", "800", "900"], sort_applied=True)
anchor, fast = run(g, "700")
check(anchor is None, "배송보류하지 않음")
check(g.checked_rows() == set(), f"체크도 남지 않음: {sorted(g.checked_rows())}")

print("\n=== 7. 상품코드 칸 위치를 못 잡음(geo=None, 헤더로도 못 찾음) -> 건너뜀 ===")
g = FakeGrid(["700", "700"], sort_applied=True)
install(g)
rr.find_bottom_code_column = lambda grid_, code_: None
anchor, fast = rr.prepare_bottom_checks(1, 1, g, "700", None, None, CB_X)
check(anchor is None and g.checked_rows() == set(), "위치를 못 잡으면 아무것도 하지 않음")

print("\n=== 8. 빈 상품코드 행(배송비 등)이 섞여 있음 ===")
g = FakeGrid(["", "", "700", "700", "800"], sort_applied=True)
anchor, fast = run(g, "700")
check(anchor is not None, "처리됨")
check(g.checked_rows() == {2, 3}, f"빈 행은 건드리지 않음: {sorted(g.checked_rows())}")

print("\n=== 9. 대상이 그리드 맨 끝까지 이어짐 ===")
g = FakeGrid(["100", "200", "300", "700", "700", "700", "700"], sort_applied=True)
anchor, fast = run(g, "700")
check(anchor is not None, "처리됨")
check(g.checked_rows() == {3, 4, 5, 6}, f"끝까지 체크됨: {sorted(g.checked_rows())}")

print("\n=== 10. 무순서 + 대상이 흩어져 있음 -> 정렬하면 한 덩어리가 됨 ===")
g = FakeGrid(["700", "100", "900", "700", "200", "700", "800"])   # 정렬 안 됨
anchor, fast = run(g, "700")
check(anchor is not None and g.sorted_clicks >= 1, "정렬 후 처리됨")
check(g.codes_checked() == ["700", "700", "700"], f"흩어진 대상이 모두 체크됨: {g.codes_checked()}")
# 정렬됐으니 체크된 행들은 연속이어야 한다
cr = sorted(g.checked_rows())
check(cr == list(range(cr[0], cr[-1] + 1)), f"체크된 행이 연속 구간: {cr}")

print("\n=== 11. 헤더는 '오름차순' 이라는데 데이터는 실제로 안 정렬됨 -> page_order_problem 이 잡음 ===")
# sort_applied=True 라 헤더 DefaultAction 은 '내림차순 정렬'(=asc)로 거짓 보고하지만
# 실제 rows 는 무순서다. sort_grid_ascending_by 는 헤더만 보고 True 를 주지만,
# select_code_range_and_check 안의 page_order_problem 이 실제 값 순서를 훑어 포기해야 한다.
# (2026-09-16 '다른 상품 행이 끼어 체크됨' 사고의 마지막 방어선)
g = FakeGrid(["100", "700", "200", "700", "900", "700"], sort_applied=True)
anchor, fast = run(g, "700")
check(anchor is None, f"거짓 헤더 + 미정렬 데이터 -> 배송보류하지 않음 (anchor={anchor})")
check(g.sorted_clicks == 0, f"헤더가 asc 라 보고해 클릭도 안 함 (클릭 {g.sorted_clicks}회)")
check(g.checked_rows() == set(), f"아무 체크도 하지 않음: {sorted(g.checked_rows())}")

print("\n=== 12. 일치 행 사이에 다른 코드가 끼어 있음(미정렬) -> 끼어든 행이 체크되지 않음 ===")
g = FakeGrid(["700", "701", "700"], sort_applied=True)
anchor, fast = run(g, "700")
check(anchor is None, f"범위선택 포기 (anchor={anchor})")
check(not g.rows[1]["checked"], f"끼어든 701 행이 체크되지 않음 (checked={g.rows[1]['checked']})")
check(g.checked_rows() == set(), f"아무 체크도 하지 않음: {sorted(g.checked_rows())}")

print("\n=== 13. 데이터가 한 행뿐이고 아래에서부터 못 읽음(edge_last=None) -> 예외 없이 처리 ===")
# 2026-09-17 라이브 버그: probe_edge_row(from_top=False)가 None 을 주는데 그걸 문자열과
# 비교해 '<=' TypeError 가 나 재고검토가 통째로 중단됐다. 지름길을 건너뛰고 처리해야 한다.
g = FakeGrid(["700"], sort_applied=True, edge_last_none=True)
anchor, fast = run(g, "700")
check(anchor is not None, f"예외 없이 처리됨 (anchor={anchor is not None})")
check(g.codes_checked() == ["700"], f"그 한 행이 체크됨: {g.codes_checked()}")

print("\n=== 14. 첫 페이지 edge_last=None 이어도 예외 없이 대상 구간 체크 (겹치는 페이지) ===")
g = FakeGrid(["100", "200", "700", "700"], page=3, step=2, sort_applied=True, edge_last_none=True)
anchor, fast = run(g, "700")
check(anchor is not None, f"예외 없이 대상 도달 (anchor={anchor is not None})")
check(g.codes_checked() == ["700", "700"], f"대상만 체크됨: {g.codes_checked()}")

print("\n=== 15. 앞에 무관한 행이 많고, 덩어리가 화면 여러 장에 걸침 -> 찾기로 점프 후 끝까지 선택 ===")
# 사용자 확인 사항: 하단 그리드에 보이는 행보다 처리할 건수가 더 많을 수 있다.
# 찾기로 덩어리 맨 위로 점프한 뒤, 화면을 넘는 덩어리도 아래로 훑어 전부 선택해야 한다.
g = FakeGrid(["1", "2", "3", "4", "5", "700", "700", "700", "700", "700", "800", "900"],
             page=3, step=2, sort_applied=True)
anchor, fast = run(g, "700")
check(anchor is not None and fast, f"찾기 점프 후 범위선택 성공 (anchor={anchor is not None})")
check(g.codes_checked() == ["700"] * 5, f"화면을 넘는 덩어리 5건 모두 체크됨: {g.codes_checked()}")
check(g.checked_rows() == {5, 6, 7, 8, 9}, f"체크된 행: {sorted(g.checked_rows())}")
# 찾기가 덩어리(index 5)로 바로 점프했는지 (앞의 1~5 를 하나씩 안 지나감)
check(getattr(g, "jumped", None) == 5, f"찾기가 덩어리 첫 행(index 5)으로 점프: jumped={getattr(g, 'jumped', None)}")

print("\n=== 16. 찾기해도 화면에 code 가 없으면(=대상 없음) 건너뜀 ===")
g = FakeGrid(["100", "200", "300"], sort_applied=True)
anchor, fast = run(g, "700")
check(anchor is None, f"대상 없으면 배송보류하지 않음 (anchor={anchor})")
check(g.checked_rows() == set(), f"아무 체크도 하지 않음: {sorted(g.checked_rows())}")

print("\n=== 17. 덩어리 끝이 '페이지 경계'에 딱 걸림 -> 한 페이지 올라가 마지막 행을 다시 잡음 ===")
# 페이지 단위(겹침 없음) 이동이라, 끝이 페이지 경계면 다음 페이지엔 일치 행이 없다.
# 그때 한 페이지 위로 올라가 마지막 일치 행을 잡아야 한다.
g = FakeGrid(["1", "2", "700", "700", "700", "800", "900", "901"], page=3, sort_applied=True)
anchor, fast = run(g, "700")
check(anchor is not None, f"경계 걸림에도 처리됨 (anchor={anchor is not None})")
check(g.codes_checked() == ["700", "700", "700"], f"덩어리 3건 모두 체크됨: {g.codes_checked()}")
check(g.checked_rows() == {2, 3, 4}, f"체크된 행(경계 마지막까지): {sorted(g.checked_rows())}")

print("\n=== 18. 페이지 단위로 내려간다(한 줄씩 아님): 큰 덩어리도 page_down 호출이 덩어리 크기에 비례 ===")
# page=4. 앞 6행 무관 + 700 이 8행 연속 + 뒤 2행. find_jump 로 700 첫 행으로 점프하므로
# 앞 6행은 건너뛴다. 아래로는 page_down 으로만 이동(한 줄씩 아님).
codes = ["10", "11", "12", "13", "14", "15"] + ["700"] * 8 + ["800", "900"]
g = FakeGrid(codes, page=4, sort_applied=True)
# install() 이 rr.grid_page_down 을 다시 덮으므로, install 이 참조하는 전역 fake_page_down 을 바꿔 센다.
pd_calls = {"n": 0}
_orig_pd = fake_page_down


def fake_page_down(hwnd, grid, geo=None, col_name=None):  # noqa: F811
    pd_calls["n"] += 1
    return _orig_pd(hwnd, grid)


anchor, fast = run(g, "700")
fake_page_down = _orig_pd
check(anchor is not None, f"큰 덩어리 처리됨 (anchor={anchor is not None})")
check(g.codes_checked() == ["700"] * 8, f"700 8건 모두 체크됨: {len(g.codes_checked())}건")
check(1 <= pd_calls["n"] <= 3, f"page_down 호출 {pd_calls['n']}회 (덩어리 8행/페이지 4 = 소수, 한 줄씩 아님)")


# ---------------------------------------------------------------- 상단 그리드 (부족수량 목록)
class FakeTopCell:
    def __init__(self, grid, slot, col):
        self.grid, self.slot, self.col = grid, slot, col

    def value(self):
        i = self.grid.top + self.slot
        return self.grid.rows[i][self.col] if i < len(self.grid.rows) else None


class FakeTopGrid:
    """rows: [(상품코드, 부족수량)]. 자체코드는 상품코드와 같게 둔다."""

    def __init__(self, rows, page=3):
        self.rows = [{"상품코드": c, "자체코드": c, "부족수량": q} for c, q in rows]
        self.page, self.top, self.to_top_calls, self.pd_calls = page, 0, 0, 0


def install_top(grid):
    install(grid)
    rr.grid_rows = lambda g: {
        s: {col: FakeTopCell(g, s, col) for col in ("상품코드", "자체코드", "부족수량")}
        for s in range(min(g.page, len(g.rows) - g.top))}
    rr.grid_vertical_scrollbar = lambda g: object() if len(g.rows) > g.page else None

    def to_top(hwnd, g, **kw):
        g.to_top_calls += 1
        g.top = 0

    def page_down(hwnd, g, geo=None, col_name=None):
        g.pd_calls += 1
        return fake_page_down(hwnd, g)
    rr.grid_scroll_to_top = to_top
    rr.grid_page_down = page_down


print("\n=== 19. 상단 부족수량 수집: 페이지 단위로 끝까지, 빠짐없이 ===")
top = FakeTopGrid([("A", ""), ("B", "2"), ("C", ""), ("D", ""), ("E", "1"), ("F", ""),
                   ("G", ""), ("H", "5"), ("I", ""), ("J", "3")], page=3)
install_top(top)
targets, bottom = rr.collect_shortage_rows(1, top)
check([k[0] for k, _q in targets] == ["B", "E", "H", "J"], f"부족수량 행 모두 수집: {[k[0] for k, _q in targets]}")
check(bottom, "마지막 행까지 확인됨")
check(not hasattr(rr, "grid_scroll_down_step"), "한 줄씩 내리는 함수가 더 이상 없음")
check(top.pd_calls <= 4, f"page_down {top.pd_calls}회 (10행/페이지 3)")

print("\n=== 20. 대상 행 다시 찾기: 맨 위로 안 올라가고 지금 자리에서 아래로 ===")
top.top, top.to_top_calls, top.pd_calls = 3, 0, 0          # 방금 E(3~5행 화면)를 처리한 상태
cell = rr.find_row_cell_by_key(1, top, ("H", "H"), "부족수량")
check(cell is not None and cell.value() == "5", f"H 행의 부족수량 셀을 찾음 ({cell and cell.value()})")
check(top.to_top_calls == 0, f"맨 위로 올라가지 않음 ({top.to_top_calls}회)")
check(top.pd_calls == 1, f"한 페이지만 내려감 ({top.pd_calls}회)")

print("\n=== 21. 대상이 지금 화면보다 위에 있으면 끝까지 본 뒤 맨 위에서 한 번 더 ===")
top.top, top.to_top_calls = 6, 0
cell = rr.find_row_cell_by_key(1, top, ("B", "B"), "부족수량")
check(cell is not None and cell.value() == "2", f"B 행을 찾음 ({cell and cell.value()})")
check(top.to_top_calls == 1, f"맨 위로는 한 번만 ({top.to_top_calls}회)")
cell = rr.find_row_cell_by_key(1, top, ("Z", "Z"), "부족수량")
check(cell is None, "없는 행이면 None (무한 반복 없음)")


# ---------------------------------------------------------------- 일반 탭 상품상태 내림차순
class FakeStatusHeader:
    DA = {"none": rr.SORT_DA_UNSORTED, "asc": rr.SORT_DA_ASCENDING, "desc": rr.SORT_DA_DESCENDING}
    NEXT = {"none": "asc", "asc": "desc", "desc": "none"}

    def __init__(self, g):
        self.g = g

    def window_text(self):
        return "상품상태"

    def legacy_properties(self):
        return {"DefaultAction": self.DA[self.g.state]}

    def click_input(self, **kw):
        g = self.g
        g.clicks += 1
        g.state = self.NEXT[g.state]
        if not g.fake_order:
            g.vals = sorted(g.orig, reverse=g.state == "desc") if g.state != "none" else list(g.orig)


class FakeStatusGrid:
    def __init__(self, vals, state="none", fake_order=False):
        self.orig, self.vals, self.state = list(vals), list(vals), state
        self.fake_order, self.clicks = fake_order, 0

    def descendants(self, control_type=None):
        return [FakeStatusHeader(self)]


def sort_status(g):
    install(FakeGrid([]))
    rr.get_status_column_geometry = lambda grid, col: (100, 380)
    rr.get_row_height = lambda grid: 20
    rr.grid_usable_bottom = lambda grid, rh: 600
    rr.scroll_grid_to_top = lambda hwnd, grid, **kw: None
    rr.scan_view_statuses = lambda x, t, b, col="상품상태", step=None: [(0, v, None) for v in g.vals]
    return rr.sort_grid_by_status_desc(1, g)


print("\n=== 22. 일반 탭: 정렬 안 됨 -> 헤더 상태로 내림차순 확정 (2클릭) ===")
g = FakeStatusGrid(["정상", "단종", "정상", "일시품절", "정상"])
check(sort_status(g) is True, "내림차순 확정")
check(g.clicks == 2 and g.state == "desc", f"헤더 {g.clicks}회 클릭, 상태={g.state}")

print("\n=== 23. 일반 탭: 맨 위가 '정상'이어도 정렬 안 된 상태를 믿지 않는다 ===")
# 9/16 사고 유형: 정렬 안 됐는데 화면 첫 페이지가 전부 정상이라 정렬된 걸로 보는 경우
g = FakeStatusGrid(["정상", "정상", "정상"], state="none")
check(sort_status(g) is True and g.state == "desc", f"헤더를 눌러 실제로 내림차순으로 만듦 (클릭 {g.clicks}회)")

print("\n=== 24. 일반 탭: 이미 내림차순이면 누르지 않음 / 전부 비정상이어도 확정 ===")
g = FakeStatusGrid(["일시품절", "단종"], state="desc")
check(sort_status(g) is True and g.clicks == 0, f"클릭 {g.clicks}회, 전부 비정상도 통과")

print("\n=== 25. 일반 탭: 헤더는 내림차순이라는데 값이 뒤섞임 -> 실패 처리 ===")
g = FakeStatusGrid(["단종", "정상", "일시품절"], state="desc", fake_order=True)
check(sort_status(g) is False, "값 순서가 틀리면 확정하지 않음")

print("\n실패:", fails if fails else "없음")
sys.exit(1 if fails else 0)
