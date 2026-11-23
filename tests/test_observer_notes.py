# -*- coding: utf-8 -*-
"""옵저버 프리셋 칸 아래 안내 - 줄마다 문단 기호(•), 넘어간 줄은 글 칸에 맞춰 들여 쓴다 (사용자 2026-11-23: 글이 많아 보기 안 좋다).
    .venv\\Scripts\\python.exe tests\\test_observer_notes.py
"""
import os
import sys
import tkinter as tk

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import observer_widgets as w  # noqa: E402
import rpa_observer as ob  # noqa: E402

fails = []


def check(name, ok, detail=""):
    print(f"  [{'통과' if ok else '실패'}] {name}" + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


def main():
    root = tk.Tk()
    root.withdraw()
    w.init(1.0)
    n = w.Notes(root, font=("Malgun Gothic", 9), bg="#ffffff", fg="#555555", wrap=300)
    n.pack()
    n.set("저장된 비밀번호가 있습니다.", ["첫째 안내", "둘째 안내가 아주 길어서 " * 6])
    root.update_idletasks()
    cells = n.rows.winfo_children()
    dots = [c for c in cells if int(c.grid_info()["column"]) == 0]
    texts = [c for c in cells if int(c.grid_info()["column"]) == 1]
    check("N1 줄마다 기호 칸과 글 칸", len(dots) == 2 and len(texts) == 2 and all(d.cget("text") == "•" for d in dots),
          [c.cget("text")[:6] for c in cells])
    t0 = texts[1]
    check("N2 글 칸은 기호 칸만큼 좁게 넘긴다 (넘어간 줄이 기호 아래로 가지 않는다)", 0 < int(t0.cget("wraplength")) < 300, t0.cget("wraplength"))
    check("N3 상태 글은 기호 없이 위에", n.status.cget("text") == "저장된 비밀번호가 있습니다." and n.status.winfo_manager() == "pack")
    check("N4 cget('text') 는 상태와 안내 전체 (시험·확인용)", "첫째 안내" in n.cget("text") and "저장된 비밀번호" in n.cget("text"))
    n.set("", ["하나"])
    root.update_idletasks()
    check("N5 상태 글이 없으면 그 줄을 감춘다, 다시 그리면 옛 줄은 없다", not n.status.winfo_manager() and len(n.rows.winfo_children()) == 2)
    root.destroy()

    print("문구 (사용자 2026-11-23)")
    check("T1 엑셀 비밀번호 안내는 언제 넣는지·무엇에 쓰는지·없으면 비우기", ob.XL_PW_HINT.startswith("엑셀 비밀번호:")
          and "열 때 비밀번호를 묻는 경우에만" in ob.XL_PW_HINT and "비워 두십시오" in ob.XL_PW_HINT)
    check("T2 저장 안내 한 줄", ob.PW_SAVE_HINT == "비밀번호와 엑셀 비밀번호는 암호화해 이 PC에만 저장합니다.")
    check("T3 메일 안내는 짧게, 제목 검색 안내는 남김", ob.MAIL_HINT.startswith("'메일 시작 문구'로 시작하는 메일만 받습니다.")
          and "제목으로 검색" in ob.MAIL_HINT)
    print("\n실패:", fails if fails else "없음")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
