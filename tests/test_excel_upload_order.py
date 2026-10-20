"""엑셀 연속 업로드의 팝업 순서 (2026-10-16) - 가짜 ERPia 로 run_routine.run_excel_upload_step 만 돌린다.

파일 열기 창이 닫히면 기다리지 않고 다음 파일로 간다. 앞 파일이 실패해 결과 팝업이 떠 있으면 그리드를 넘기는 클릭도 막히므로
사이트코드를 찾기 전에 닫아야 하고, 찾는 동안 늦게 뜬 팝업도 앞 파일의 결과로 봐야 한다.
"""
import os
import sys
import tempfile
import time
from types import SimpleNamespace

import win32con

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import run_routine as rr  # noqa: E402

REAL_FIND = rr.find_site_upload_cell     # 아래 run() 이 가짜로 바꾸기 전에
REAL_POPUPS, REAL_WAIT = rr.upload_popups, rr.wait_upload_result
REAL_OPEN, REAL_IN_DIALOG = rr.open_upload_dialog, rr.upload_file_in_dialog

fails = []


def check(name, ok, detail=""):
    print(f"  [{'통과' if ok else '실패'}] {name}" + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


def run(bad, when="now", unknown=False):
    """bad: 결과 팝업이 뜨는 사이트코드. when: 팝업이 뜨는 때 - now 창이 닫히자마자, block 다음 파일의 사이트코드를 찾기 시작할 때
    (그리드를 못 넘긴다), find 찾는 동안, wait 그보다 늦게 (결과를 기다릴 때에야). unknown: 그 팝업이 누를 단추를 모르는 창.
    반환: (옮긴 곳 {파일: 까닭}, 팝업이 떠 있는 채로 사이트코드를 찾은 횟수, 멈췄는가)"""
    popup, blocking, delayed, later, moved, blocked = [], [], [], [], {}, []

    def find(hwnd, grid, code):
        popup.extend(blocking)
        blocking.clear()
        blocked.append(bool(popup))
        popup.extend(delayed)
        delayed.clear()
        if blocked[-1]:
            return None, None       # 팝업에 막혀 그리드를 못 넘겼다
        return SimpleNamespace(rectangle=lambda: (0, 0, 1, 1)), rr.EXCEL_UPLOAD_ENABLED

    def dismiss(*_, **__):
        if unknown and popup:
            raise rr.UploadStop("처리할 수 있는 버튼이 없습니다.")
        texts = popup[:]
        popup.clear()
        return texts

    def upload(dlg, path, pid=None):
        if os.path.basename(path)[0] in bad:
            {"now": popup, "block": blocking, "find": delayed, "wait": later}[when].append("업로드 오류")
        return True

    def wait_result(*_, **__):
        popup.extend(later)
        later.clear()
        return dismiss()

    rr.log = lambda m: None
    rr.excel_upload_dir = tempfile.gettempdir
    rr.collect_upload_files = lambda folder: ({c: f"{c}.xlsx" for c in "ABC"}, [], [])
    rr.find_site_upload_cell = find
    rr.find_popup_windows = lambda pid, hwnd: []
    rr.upload_popups = dismiss
    rr.wait_upload_result = wait_result
    rr.open_upload_dialog = lambda pid, hwnd, cell: 1
    rr.upload_file_in_dialog = upload
    rr.win32gui = SimpleNamespace(IsWindow=lambda h: False, IsWindowVisible=lambda h: False)
    rr.wait_file_unlocked = lambda path, **_: True
    rr.move_file_to = lambda path, dest, reason="": moved.__setitem__(path, reason) or True
    try:
        rr.run_excel_upload_step(None, 0, 0, None)
    except rr.UploadStop:
        return moved, blocked.count(True), True
    return moved, blocked.count(True), False


done = {"A.xlsx": "업로드 완료", "B.xlsx": "업로드 완료", "C.xlsx": "업로드 완료"}
moved, blocked, _ = run("")
check("팝업이 없으면 셋 다 완료", moved == done, str(moved))

moved, blocked, _ = run("A")
check("앞 파일 결과 팝업은 다음 파일의 사이트코드를 찾기 전에 닫는다", blocked == 0, f"막힌 찾기 {blocked}번")
check("팝업이 뜬 앞 파일만 실패, 다음 파일은 완료", moved == {**done, "A.xlsx": "업로드 실패"}, str(moved))

moved, blocked, _ = run("A", when="block")
check("찾기 시작할 때 뜬 팝업에 막히면 닫고 한 번 더 찾는다 (다음 파일이 '사이트코드 없음' 으로 가지 않는다)",
      moved == {**done, "A.xlsx": "업로드 실패"}, str(moved))

moved, blocked, _ = run("A", when="find")
check("찾는 동안 늦게 뜬 팝업도 앞 파일의 결과로 본다", moved == {**done, "A.xlsx": "업로드 실패"}, str(moved))

moved, blocked, _ = run("A", when="wait")
check("그보다 늦게 뜬 팝업도 다음 칸을 누르기 전에 기다려 앞 파일의 결과로 본다 (실패한 파일이 완료로 가지 않는다)",
      moved == {**done, "A.xlsx": "업로드 실패"}, str(moved))

moved, blocked, _ = run("C")
check("마지막 파일은 결과 팝업을 기다려 본다", moved == {**done, "C.xlsx": "업로드 실패"}, str(moved))

moved, blocked, stopped = run("A", unknown=True)
check("누를 단추를 모르는 창이면 멈추고, 결과를 못 본 앞 파일은 옮기지 않는다", stopped and moved == {}, f"멈춤 {stopped} {moved}")


print("--- 팝업은 ERPia 가 따로 띄운 창 목록으로 (2026-10-19: 실패 팝업은 메인 창이 소유한 별도 창)")
wins, pressed = {}, []      # hwnd: (class, 누르면 닫히는가, 누를 단추가 있는가)


def press(h):
    pressed.append(h)
    _cls, closes, known = wins[h]
    if not known:
        return False, "처리할 수 있는 버튼이 없습니다.", ""
    if closes:
        wins.pop(h)
    return True, f"[ERPia] 팝업{h} -> '확인(O)' 클릭", f"팝업{h} 문구"


def stops(fn):
    try:
        fn()
    except rr.UploadStop:
        return True
    return False


rr.find_popup_windows = lambda pid, hwnd: list(wins)
rr.invoke_popup_window = press
rr.win32gui = SimpleNamespace(GetClassName=lambda h: wins[h][0], IsWindow=lambda h: h in wins,
                              IsWindowVisible=lambda h: h in wins)
rr.upload_popups, rr.wait_upload_result = REAL_POPUPS, REAL_WAIT

wins.update({1: ("popup", True, True), 2: (rr.SAVE_DIALOG_CLASS, True, True), 3: ("popup", True, True)})
texts = rr.upload_popups(0, 0, before={1})
check("업로드 전부터 있던 창과 파일 열기 창은 두고 새로 뜬 팝업만 닫는다", pressed == [3] and texts == ["팝업3 문구"],
      f"{pressed} {texts}")

wins.clear()
wins[4] = ("popup", True, False)
check("누를 단추가 없는 창이면 멈춘다", stops(lambda: rr.upload_popups(0, 0)))

wins.clear()
pressed.clear()
wins[5] = ("popup", False, True)
check("눌러도 안 닫히면 거듭 누르지 않고 멈춘다", stops(lambda: rr.upload_popups(0, 0)) and pressed == [5], str(pressed))

wins.clear()
calls = []


def appear(pid, hwnd):
    calls.append(1)
    if len(calls) == 3:
        wins[6] = ("popup", True, True)
    return list(wins)


rr.find_popup_windows = appear
t = time.time()
texts = rr.wait_upload_result(0, 0, timeout=3)
check("결과 팝업이 뜨면 기다리기를 바로 끝낸다", texts == ["팝업6 문구"] and time.time() - t < 1,
      f"{texts} {time.time() - t:.1f}초")
rr.find_popup_windows = lambda pid, hwnd: []
t = time.time()
texts = rr.wait_upload_result(0, 0, timeout=0.3)
check("안 뜨면 기다린 뒤 빈 목록 (정상 업로드)", texts == [] and 0.3 <= time.time() - t < 1, f"{texts} {time.time() - t:.1f}초")


print("--- 함께 실행: 파일 열기 창을 키보드·마우스 없이, 덮인 칸은 누르지 않는다 (2026-10-19)")
sent, box = [], {}
rr.find_open_dialog_filename_edit = lambda dlg: 77
rr.read_save_filename = lambda edit: box.get(edit, "")
rr.double_click_file_in_dialog = lambda *a: sent.append("목록 더블클릭") or True
rr.win32gui = SimpleNamespace(SendMessage=lambda h, m, w, l: box.__setitem__(h, l) or sent.append(("send", h, m)),
                              PostMessage=lambda h, m, w, l: sent.append(("post", h, m, w)))
rr.UPLOAD_NO_KEYS = True
ok = REAL_IN_DIALOG(5, r"C:\x\(107)a.xlsx")
check("경로는 WM_SETTEXT, [열기] 는 IDOK 메시지 - 목록 더블클릭·키 입력 없이",
      ok and sent == [("send", 77, win32con.WM_SETTEXT), ("post", 5, win32con.WM_COMMAND, win32con.IDOK)], str(sent))
sent.clear()
box.clear()
rr.win32gui.SendMessage = lambda *a: sent.append("send")
check("넣은 값이 다르면 [열기] 를 보내지 않는다", REAL_IN_DIALOG(5, r"C:\x\(107)a.xlsx") is False and sent == ["send"], str(sent))
rr.UPLOAD_NO_KEYS = False
clicked = []
cell = SimpleNamespace(rectangle=lambda: SimpleNamespace(left=0, top=0, right=10, bottom=10),
                       click_input=lambda: clicked.append("클릭"), double_click_input=lambda: clicked.append("더블클릭"))
rr.ec = SimpleNamespace(ensure_foreground=lambda h: True)
rr.wait_save_dialog = lambda *a, **k: 1
rr.win32gui = SimpleNamespace(WindowFromPoint=lambda pt: 99, GetAncestor=lambda h, f: h, GetWindowText=lambda h: "Edge")
check("누를 자리를 다른 창이 덮고 있으면 누르지 않는다 (클릭이 그 창에 떨어진다)", REAL_OPEN(0, 2, cell) is None and not clicked,
      str(clicked))
rr.win32gui.WindowFromPoint = lambda pt: 2
check("ERPia 메인 창이면 누른다", REAL_OPEN(0, 2, cell) == 1 and clicked == ["클릭"], str(clicked))


print("--- 업로드 칸이 사이트코드와 같은 줄인지 (행 번호, 2026-10-19: 108 을 눌렀는데 109 에 올라갔다)")


class El:
    def __init__(self, name):
        self.name = name

    def window_text(self):
        return self.name


cells = []
rr.find_site_upload_cell = REAL_FIND        # 다시 찾을 때 이 이름으로 부른다
rr._header_onscreen =lambda grid, col: True
rr._column_scan_geometry = lambda grid, col: (10, 0, 100, 24)
rr.scan_column = lambda geo, col: [(460, "108", El("사이트코드 행 14"))]
rr.element_at_point = lambda x, y: cells.pop(0)
rr.legacy_value = lambda el: rr.EXCEL_UPLOAD_ENABLED
cells[:] = [El("엑셀업로드 행 14")]
check("같은 줄이면 그 칸", REAL_FIND(0, None, "108")[0].name == "엑셀업로드 행 14")
cells[:] = [El("엑셀업로드 행 15"), El("엑셀업로드 행 14")]
check("줄이 움직였으면 처음부터 다시 찾아 맞는 칸", REAL_FIND(0, None, "108")[0].name == "엑셀업로드 행 14")
cells[:] = [El("엑셀업로드 행 15"), El("엑셀업로드 행 15")]
check("다시 찾아도 다르면 누르지 않는다 (못 찾음)", REAL_FIND(0, None, "108") == (None, None))
cells[:] = [El("엑셀업로드")]
check("행 번호가 없는 이름이면 예전처럼 그 칸", REAL_FIND(0, None, "108")[0].name == "엑셀업로드")

print()
print("실패:", fails or "없음")
sys.exit(1 if fails else 0)
