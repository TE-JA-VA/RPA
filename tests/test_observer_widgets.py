# -*- coding: utf-8 -*-
"""옵저버 화면 부품이 Tkinter 기본 부품과 같은 쓰는 법을 지키는지 (설계 2026-11-06). 창은 화면 밖에 뜬다."""
import io
import os
import sys
import tkinter as tk

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import observer_widgets as w  # noqa: E402

root = tk.Tk()
root.geometry("10x10+-3000+-3000")     # 화면 밖 - 숨긴 창에는 가상 이벤트가 안 온다
w.init(1.0)
hits = []
b = w.Btn(root, "저장", "primary", lambda: hits.append("b"))
assert b.cget("text") == "저장" and b.cget("state") == "normal"
b.config(text="중단", kind="danger", state="disabled")
b.invoke()
assert not hits and b.cget("text") == "중단" and b.cget("state") == "disabled"
b.config(state="normal")
b.invoke()
assert hits == ["b"]
v = tk.BooleanVar(root, value=False)
c = w.Check(root, variable=v, command=lambda: hits.append("c"), text="글")
c._click()
assert v.get() is True and hits[-1] == "c"
c.destroy()
v.set(False)                                      # 사라진 체크를 다시 그리지 않는다
s = tk.StringVar(root, value="shop")
r = w.Radio(root, "메일", "mail", s, lambda: hits.append("r"))
r._click()
assert s.get() == "mail" and hits[-1] == "r"
sel = w.Select(root, values=["(없음)"])
assert sel.current() == -1 and sel.get() == ""
sel.config(values=["(없음)", "휴대폰"])
got = []
sel.bind("<<ComboboxSelected>>", lambda e: got.append(sel.get()))
sel.pack()
root.update()
sel._pick(1)
root.update()
assert sel.current() == 1 and got == ["휴대폰"]
sel._open()                                       # 짧은 목록: 스크롤바 없이 딱 그 줄 수
assert int(sel._list["height"]) == 2 and not any(isinstance(c, tk.Scrollbar) for c in sel._list.master.winfo_children())
sel._close(0)
assert sel.get() == "(없음)" and got[-1] == "(없음)" and not sel._list.winfo_exists()
t = tk.StringVar(root, value="")
fld = w.Field(root, width=4, h=24, textvariable=t, justify="right", validate="key",
            validatecommand=(root.register(lambda x: not x or x.isdecimal()), "%P"))
fld.entry.insert(0, "12")
fld.entry.insert(0, "x")
assert t.get() == "12"
tabs = w.Tabs(root, hits.append)
tabs.show([(f"{i}", i % 2 == 0) for i in range(50)], 0, None, False)
assert len(tabs.tabs) == 50 and tabs.texts()[49] == "49"
tabs.show([("a", True), ("b", False)], 1, None, True)
assert len(tabs.tabs) == 2
tabs._click(0)                                    # 기록·미리보기 중에는 다른 탭을 못 고른다
assert hits[-1] != 0
tabs._click(1)
assert hits[-1] == 1
tabs._open()                                      # '더보기' 목록도 같은 드롭다운, 바쁠 때 다른 탭은 못 고른다
d = tabs._drop
assert len(d.tree.get_children()) == 2 and d.ok == [False, True]
d.close(0)
assert hits[-1] == 1 and not d.tree.winfo_exists()
tabs.show([(f"{i}", i % 2 == 0) for i in range(50)], 3, None, False)
tabs._open()
d = tabs._drop
assert int(d.tree["height"]) == 10 and d.hot == 3 and "hot" in d.tree.item("3", "tags")
d.close(7)
assert hits[-1] == 7
root.destroy()
assert w.self_check()
print("PASS observer_widgets")
