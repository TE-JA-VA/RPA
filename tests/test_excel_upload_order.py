"""엑셀 연속 업로드의 팝업 순서 (2026-10-16) - 가짜 ERPia 로 run_routine.run_excel_upload_step 만 돌린다.

파일 열기 창이 닫히면 기다리지 않고 다음 파일로 간다. 앞 파일이 실패해 결과 팝업이 떠 있으면 그리드를 넘기는 클릭도 막히므로
사이트코드를 찾기 전에 닫아야 하고, 찾는 동안 늦게 뜬 팝업도 앞 파일의 결과로 봐야 한다.
"""
import os
import sys
import tempfile
from types import SimpleNamespace

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import run_routine as rr  # noqa: E402

fails = []


def check(name, ok, detail=""):
    print(f"  [{'통과' if ok else '실패'}] {name}" + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


def run(bad, when="now"):
    """bad: 결과 팝업이 뜨는 사이트코드. when: 팝업이 뜨는 때 - now 창이 닫히자마자, find 다음 파일의 사이트코드를 찾는 동안,
    wait 그보다 늦게 (결과를 기다릴 때에야). 반환: (옮긴 곳 {파일: 까닭}, 팝업이 떠 있는 채로 사이트코드를 찾은 횟수)"""
    popup, delayed, later, moved, blocked = [], [], [], {}, []

    def find(hwnd, grid, code):
        blocked.append(bool(popup))
        popup.extend(delayed)
        delayed.clear()
        if blocked[-1]:
            return None, None       # 팝업에 막혀 그리드를 못 넘겼다
        return SimpleNamespace(rectangle=lambda: (0, 0, 1, 1)), rr.EXCEL_UPLOAD_ENABLED

    def dismiss(app, hwnd, label="", **_):
        texts = popup[:]
        popup.clear()
        return texts

    def upload(dlg, path, pid=None):
        if os.path.basename(path)[0] in bad:
            {"now": popup, "find": delayed, "wait": later}[when].append("업로드 오류")
        return True

    def wait_result(app, hwnd, timeout=None, **_):
        popup.extend(later)
        later.clear()
        return dismiss(app, hwnd)

    rr.log = lambda m: None
    rr.excel_upload_dir = tempfile.gettempdir
    rr.collect_upload_files = lambda folder: ({c: f"{c}.xlsx" for c in "ABC"}, [], [])
    rr.find_site_upload_cell = find
    rr.dismiss_popups = dismiss
    rr.wait_upload_result = wait_result
    rr.open_upload_dialog = lambda pid, hwnd, cell: 1
    rr.upload_file_in_dialog = upload
    rr.win32gui = SimpleNamespace(IsWindow=lambda h: False, IsWindowVisible=lambda h: False)
    rr.wait_file_unlocked = lambda path, **_: True
    rr.move_file_to = lambda path, dest, reason="": moved.__setitem__(path, reason) or True
    rr.run_excel_upload_step(None, 0, 0, None)
    return moved, blocked.count(True)


done = {"A.xlsx": "업로드 완료", "B.xlsx": "업로드 완료", "C.xlsx": "업로드 완료"}
moved, blocked = run("")
check("팝업이 없으면 셋 다 완료", moved == done, str(moved))

moved, blocked = run("A")
check("앞 파일 결과 팝업은 다음 파일의 사이트코드를 찾기 전에 닫는다", blocked == 0, f"막힌 찾기 {blocked}번")
check("팝업이 뜬 앞 파일만 실패, 다음 파일은 완료", moved == {**done, "A.xlsx": "업로드 실패"}, str(moved))

moved, blocked = run("A", when="find")
check("찾는 동안 늦게 뜬 팝업도 앞 파일의 결과로 본다", moved == {**done, "A.xlsx": "업로드 실패"}, str(moved))

moved, blocked = run("A", when="wait")
check("그보다 늦게 뜬 팝업도 다음 칸을 누르기 전에 기다려 앞 파일의 결과로 본다 (실패한 파일이 완료로 가지 않는다)",
      moved == {**done, "A.xlsx": "업로드 실패"}, str(moved))

moved, blocked = run("C")
check("마지막 파일은 결과 팝업을 기다려 본다", moved == {**done, "C.xlsx": "업로드 실패"}, str(moved))

print()
print("실패:", fails or "없음")
sys.exit(1 if fails else 0)
