"""옵저버 화면 부품 - Ant Design 모양 (설계 2026-11-06). 쓰는 법은 Tkinter 기본 부품과 같게 맞췄다
(config·cget·invoke, textvariable·variable, <<ComboboxSelected>>) - 화면 코드만 바뀌고 로직은 그대로다.

둥근 모양은 Pillow 로 크게 그려 줄인 PNG 를 tk.PhotoImage 로 넣는다. PIL.ImageTk 는 쓰지 않는다 -
exe 의 Tcl/Tk 9 는 DLL 안 zipfs 구조라 _imagingtk 가 위험하다 ([[nuitka-tkinter-tcl9]])."""
import base64
import ctypes
import io
import tkinter as tk
from tkinter import font as tkfont, ttk

from PIL import Image, ImageColor, ImageDraw, PngImagePlugin  # noqa: F401 - PngImagePlugin: Pillow 가 이름으로 불러 Nuitka 가 못 찾는다

UI = "맑은 고딕"
F = (UI, 10)
F_SMALL = (UI, 9)
F_BOLD = (UI, 10, "bold")
PRIMARY, P_HOVER, P_ACTIVE, P_BG = "#1677ff", "#4096ff", "#0958d9", "#e6f4ff"
DANGER, D_HOVER, D_ACTIVE, D_BG = "#ff4d4f", "#ff7875", "#d9363e", "#fff2f0"
TEXT, TEXT2, TEXT3, TEXT4 = "#1f1f1f", "#595959", "#8c8c8c", "#bfbfbf"
BORDER, SPLIT, PAGE, CARD, ROW_HOVER = "#d9d9d9", "#f0f0f0", "#f5f5f5", "#ffffff", "#fafafa"
STEP_INK, STEP_LINE, STEP_MUTE, STEP_DONE, STEP_SKIP = "#0f172a", "#e2e8f0", "#94a3b8", "#16a34a", "#fbbf24"    # 작업 순서 동그라미
UP_TAB, UP_ON, UP_EMPTY, SWITCH_OFF, SWITCH_ON = "#1f9d4d", "#15803d", "#dcf5e3", "#e9e9eb", "#34c759"           # 업로드 프리셋 탭·스위치
SS = 4         # 모서리를 매끄럽게 - 네 배로 그려 줄인다
S = 1.0        # 화면 배율 (init)


def init(scale):
    global S
    S = scale


def px(n):
    return round(n * S)


def _font_of(widget, font):
    fonts = widget._root().__dict__.setdefault("_ant_fonts", {})
    if font not in fonts:
        fonts[font] = tkfont.Font(root=widget._root(), font=font)
    return fonts[font]


def _to_photo(widget, im):
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return tk.PhotoImage(master=widget._root(), data=base64.b64encode(buf.getvalue()), format="png")


def _photo(widget, key, make):
    """같은 그림은 한 번만 만든다. 시험이 창을 여러 번 만들어도 되게 창마다 따로 둔다."""
    cache = widget._root().__dict__.setdefault("_ant_photos", {})
    if key not in cache:
        cache[key] = _to_photo(widget, make())
    return cache[key]


def _box_image(w, h, r, fill, border, bw, ss):
    rgb = ImageColor.getrgb(border or fill)
    im = Image.new("RGBA", (w * ss, h * ss), (*rgb, 0))
    ImageDraw.Draw(im).rounded_rectangle((0, 0, w * ss - 1, h * ss - 1), px(r) * ss, fill=fill, outline=border, width=round(max(1, px(bw)) * ss))
    return im.resize((w, h), Image.LANCZOS)


def box(widget, w, h, r, fill=None, border=None, bw=1):
    return _photo(widget, ("box", w, h, r, fill, border, bw), lambda: _box_image(w, h, r, fill, border, bw, SS))


def glyph(widget, kind, size, color):
    def make():
        n = size * SS
        im = Image.new("RGBA", (n, n), (*ImageColor.getrgb(color), 0))
        d = ImageDraw.Draw(im)
        if kind == "check":
            d.line([(n * .24, n * .52), (n * .43, n * .70), (n * .77, n * .31)], fill=color, width=round(n * .11), joint="curve")
        elif kind == "down":
            d.line([(n * .2, n * .36), (n * .5, n * .66), (n * .8, n * .36)], fill=color, width=round(n * .09), joint="curve")
        elif kind == "x":
            d.line([(n * .25, n * .25), (n * .75, n * .75)], fill=color, width=round(n * .08))
            d.line([(n * .75, n * .25), (n * .25, n * .75)], fill=color, width=round(n * .08))
        elif kind == "dot":
            d.ellipse((n * .3, n * .3, n * .7, n * .7), fill=color)
        elif kind == "plus":
            d.line([(n * .5, n * .2), (n * .5, n * .8)], fill=color, width=round(n * .09))
            d.line([(n * .2, n * .5), (n * .8, n * .5)], fill=color, width=round(n * .09))
        elif kind == "minus":
            d.line([(n * .2, n * .5), (n * .8, n * .5)], fill=color, width=round(n * .09))
        elif kind == "more":
            for x in (.22, .5, .78):
                d.ellipse((n * (x - .08), n * .42, n * (x + .08), n * .58), fill=color)
        return im.resize((size, size), Image.LANCZOS)
    return _photo(widget, ("glyph", kind, size, color), make)


def at_once(root, fn):
    """창 그리기를 멈추고 fn 을 끝낸 뒤 한 번에 그린다 - 여러 곳이 차례로 바뀌어 끊겨 보이지 않게."""
    user, hwnd = ctypes.windll.user32, root.winfo_id()
    user.SendMessageW(hwnd, 0x000B, 0, 0)        # WM_SETREDRAW 끔
    try:
        fn()
        root.update_idletasks()
    finally:
        user.SendMessageW(hwnd, 0x000B, 1, 0)
        user.RedrawWindow(hwnd, None, None, 0x0001 | 0x0004 | 0x0080 | 0x0100)   # INVALIDATE·ERASE·ALLCHILDREN·UPDATENOW


class Btn(tk.Canvas):
    """단추. kind: primary·danger·default·danger_ghost. [평소, 올림, 누름] 마다 (바탕, 테두리, 글자)."""
    KINDS = {"primary": ((PRIMARY, None, "white"), (P_HOVER, None, "white"), (P_ACTIVE, None, "white")),
             "danger": ((DANGER, None, "white"), (D_HOVER, None, "white"), (D_ACTIVE, None, "white")),
             "default": ((CARD, BORDER, TEXT), (CARD, P_HOVER, P_HOVER), (CARD, P_ACTIVE, P_ACTIVE)),
             "danger_ghost": ((CARD, "#ffccc7", DANGER), (D_BG, D_HOVER, D_HOVER), (D_BG, D_ACTIVE, D_ACTIVE))}
    OFF = (PAGE, BORDER, TEXT4)

    def __init__(self, parent, text, kind="default", command=None, width=0, h=32, pad=15, font=F):
        self._text, self._kind, self._command, self._state, self._look = text, kind, command, "normal", 0
        self._min, self._h, self._pad, self._font = width, px(h), px(pad), font
        super().__init__(parent, height=self._h, bg=parent.cget("bg"), highlightthickness=0, cursor="hand2")
        self.bind("<Enter>", lambda e: self._set_look(1))
        self.bind("<Leave>", lambda e: self._set_look(0))
        self.bind("<ButtonPress-1>", lambda e: self._set_look(2))
        self.bind("<ButtonRelease-1>", self._release)
        self._paint()

    def _release(self, e):
        self._set_look(1)
        if 0 <= e.x < self.winfo_width() and 0 <= e.y < self.winfo_height():
            self.invoke()

    def _set_look(self, look):
        self._look = look
        self._paint()

    def _paint(self):
        f = _font_of(self, self._font)
        w = max(f.measure(self._text) + self._pad * 2, f.measure("0") * self._min + self._pad)
        fill, line, fg = self.OFF if self._state == "disabled" else self.KINDS[self._kind][self._look]
        super().configure(width=w, cursor="arrow" if self._state == "disabled" else "hand2")
        self.delete("all")
        self.create_image(0, 0, anchor="nw", image=box(self, w, self._h, 6, fill, line))
        self.create_text(w / 2, self._h / 2, text=self._text, fill=fg, font=self._font)

    def configure(self, cnf=None, **kw):
        for key in ("text", "kind", "command", "state"):
            if key in kw:
                setattr(self, "_" + key, kw.pop(key))
        if kw or cnf:
            super().configure(cnf, **kw)
        self._paint()

    config = configure

    def cget(self, key):
        return getattr(self, "_" + key) if key in ("text", "kind", "command", "state") else super().cget(key)

    def invoke(self):
        if self._state != "disabled" and self._command:
            self._command()


class Link(tk.Label):
    """글자 단추. state 는 Label 것을 그대로 쓴다."""
    def __init__(self, parent, text, command, fg=PRIMARY, font=F_SMALL, hover=P_HOVER):
        super().__init__(parent, text=text, fg=fg, bg=parent.cget("bg"), font=font, cursor="hand2", disabledforeground=TEXT4)
        self._command, self._fg, self._hover = command, fg, hover
        self.bind("<Button-1>", lambda e: self.invoke())
        self.bind("<Enter>", lambda e: self.config(fg=self._hover), add="+")
        self.bind("<Leave>", lambda e: self.config(fg=self._fg), add="+")

    def invoke(self):
        if str(self.cget("state")) != "disabled":
            self._command()


class Icon(tk.Label):
    """그림 단추 (✕·＋·⋯)."""
    def __init__(self, parent, kind, command, size=14, color=TEXT4, hover=P_HOVER):
        self._on, self._hover = glyph(parent, kind, px(size), color), glyph(parent, kind, px(size), hover)
        super().__init__(parent, image=self._on, bg=parent.cget("bg"), cursor="hand2", bd=0)
        self._command, self._state = command, "normal"
        self.bind("<Button-1>", lambda e: self.invoke())
        self.bind("<Enter>", lambda e: self.config(image=self._hover) if self._state == "normal" else None, add="+")
        self.bind("<Leave>", lambda e: self.config(image=self._on), add="+")

    def set_state(self, state):
        self._state = state
        self.config(cursor="hand2" if state == "normal" else "arrow")

    def invoke(self):
        if self._state == "normal":
            self._command()


class Field(tk.Canvas):
    """입력칸 - 테두리 없는 Entry 를 둥근 틀 위에. 올리면 파란 테두리, 누르면 연한 파란 빛. 다른 옵션은 Entry 로 간다."""
    def __init__(self, parent, width=0, h=32, font=F, **entry):
        self.h, self.ring = px(h), px(2)
        self._over = self._focus = False
        f = _font_of(parent, font)
        extra = {"width": f.measure("0") * width + px(14) + self.ring * 2} if width else {}
        super().__init__(parent, height=self.h + self.ring * 2, bg=parent.cget("bg"), highlightthickness=0, **extra)
        self.entry = tk.Entry(self, relief="flat", bd=0, highlightthickness=0, bg=CARD, fg=TEXT, font=font, insertbackground=TEXT, **entry)
        self._item = None
        self.bind("<Configure>", lambda e: self._paint())
        for x in (self, self.entry):
            x.bind("<Enter>", lambda e: self._look(_over=True), add="+")
            x.bind("<Leave>", lambda e: self._look(_over=False), add="+")
        self.bind("<Button-1>", lambda e: self.entry.focus_set())
        self.entry.bind("<FocusIn>", lambda e: self._look(_focus=True), add="+")
        self.entry.bind("<FocusOut>", lambda e: self._look(_focus=False), add="+")

    def _look(self, **kw):
        self.__dict__.update(kw)
        self._paint()

    def _paint(self):
        w, r = self.winfo_width(), self.ring
        if w < 10:
            return
        self.delete("frame")
        if self._focus:
            self.create_image(0, 0, anchor="nw", image=box(self, w, self.h + r * 2, 8, None, P_BG, 2), tags="frame")
        line = PRIMARY if self._focus else P_HOVER if self._over else BORDER
        self.create_image(r, r, anchor="nw", image=box(self, w - r * 2, self.h, 6, CARD, line), tags="frame")
        self.tag_lower("frame")
        pad = px(10 if self.h >= px(30) else 5)
        if self._item is None:
            self._item = self.create_window(r + pad, r + 1, anchor="nw", window=self.entry, width=w - 2 * (r + pad), height=self.h - 2)
        else:
            self.itemconfigure(self._item, width=w - 2 * (r + pad))


class DropList:
    """옵저버 드롭다운 공통 - 줄 사이를 띄운 목록, ROWS 줄을 넘으면 스크롤 (tk.Menu 자리, 사용자 2026-11-09).
    items = [(글, 글자색, 고를 수 있나)]. 고르면 on_pick(번호), 바깥·Esc·다른 프로그램이면 그냥 닫는다."""
    ROWS = 10

    def __init__(self, owner, items, cur, on_pick, font, x, y, width, top_y):
        self.on_pick, self.ok = on_pick, [it[2] for it in items]
        top = self.top = tk.Toplevel(owner, bg=BORDER)
        top.overrideredirect(True)
        top.attributes("-topmost", True)
        inner = tk.Frame(top, bg=CARD)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        style = ttk.Style(owner)        # Listbox 는 줄 간격을 못 준다 - Treeview 는 rowheight
        style.configure("Drop.Treeview", background=CARD, fieldbackground=CARD, foreground=TEXT, font=font, borderwidth=0,
                        rowheight=tkfont.Font(font=font).metrics("linespace") + px(6))
        style.layout("Drop.Treeview", [("Drop.Treeview.treearea", {"sticky": "nswe"})])
        # 마우스 올린 줄은 선택(윈도우 흰 글자)이 아니라 'hot' 꼬리표 배경으로 - 글자색(초록·흐림)은 그대로 (사용자 2026-11-09)
        tree = self.tree = ttk.Treeview(inner, style="Drop.Treeview", show="tree", selectmode="none",
                                        height=max(1, min(self.ROWS, len(items))))
        tree.column("#0", width=10, stretch=True)
        if len(items) > self.ROWS:
            bar = tk.Scrollbar(inner, orient="vertical", command=tree.yview)
            tree.configure(yscrollcommand=bar.set)
            bar.pack(side="right", fill="y")
        tree.pack(side="left", fill="both", expand=True, padx=(px(6), 0), pady=px(4))
        for i, (text, color, ok) in enumerate(items):
            tree.insert("", "end", iid=str(i), text=text, tags=(f"c{i}",))
            tree.tag_configure(f"c{i}", foreground=color if ok else TEXT4)
        tree.tag_configure("hot", background=P_BG)
        self.hot = None
        if cur is not None and 0 <= cur < len(items):
            self._light(cur)
            tree.see(str(cur))

        def row(y):
            r = tree.identify_row(y)
            return int(r) if r and self.ok[int(r)] else None

        def hover(e):
            r = row(e.y)
            if r is not None and r != self.hot:
                self._light(r)
        tree.bind("<Motion>", hover)
        tree.bind("<ButtonRelease-1>", lambda e: self.close(row(e.y)) if row(e.y) is not None else None)
        tree.bind("<Return>", lambda e: self.close(self.hot))
        top.bind("<Escape>", lambda e: self.close())
        top.bind("<ButtonPress-1>", lambda e: self.close() if e.widget is top else None)   # 잡은 동안 바깥 누름은 top 으로 온다
        tree.bind("<FocusOut>", lambda e: self.close())                                      # 다른 프로그램으로 가면 닫는다
        top.update_idletasks()
        h = top.winfo_reqheight()
        if y + h > owner.winfo_screenheight():
            y = top_y - h
        x = max(0, min(x, owner.winfo_screenwidth() - width))
        top.geometry(f"{width}x{h}+{x}+{y}")
        tree.focus_set()
        try:
            top.grab_set()
        except tk.TclError:             # 창이 아직 안 보일 때 (시험)
            pass

    def _light(self, i):
        if self.hot is not None:
            self.tree.item(str(self.hot), tags=(f"c{self.hot}",))
        self.hot = i
        self.tree.item(str(i), tags=(f"c{i}", "hot"))

    def close(self, i=None):
        top, self.top = self.top, None
        if top is None or not top.winfo_exists():
            return
        top.grab_release()
        top.destroy()
        if i is not None and self.ok[i]:
            self.on_pick(i)


class Select(tk.Canvas):
    """읽기 전용 선택 상자 (ttk.Combobox state=readonly 자리). 고르면 <<ComboboxSelected>>."""
    def __init__(self, parent, values=(), font=F):
        self.h, self.ring, self._font = px(32), px(2), font
        self._values, self._i, self._over = list(values), -1, False
        super().__init__(parent, height=self.h + self.ring * 2, bg=parent.cget("bg"), highlightthickness=0, cursor="hand2")
        self.bind("<Configure>", lambda e: self._paint())
        self.bind("<Enter>", lambda e: self._hover(True))
        self.bind("<Leave>", lambda e: self._hover(False))
        self.bind("<Button-1>", lambda e: self._open())

    def _hover(self, on):
        self._over = on
        self._paint()

    def _open(self):
        r = self.ring
        self._drop = DropList(self, [(v, TEXT, True) for v in self._values], self._i, self._pick, self._font,
                              self.winfo_rootx() + r, self.winfo_rooty() + self.h + r * 2, self.winfo_width() - r * 2, self.winfo_rooty())
        self._list = self._drop.tree

    def _close(self, i=None):
        self._drop.close(i)

    def _pick(self, i):
        self.current(i)
        self.event_generate("<<ComboboxSelected>>")

    def _paint(self):
        w, r = self.winfo_width(), self.ring
        if w < 10:
            return
        self.delete("all")
        self.create_image(r, r, anchor="nw", image=box(self, w - r * 2, self.h, 6, CARD, P_HOVER if self._over else BORDER))
        self.create_text(r + px(10), r + self.h / 2, anchor="w", text=self.get(), fill=TEXT, font=self._font)
        n = px(12)
        self.create_rectangle(w - r - px(26), r + 2, w - r - 2, r + self.h - 2, fill=CARD, outline="")   # 긴 글이 화살표를 덮지 않게
        self.create_image(w - r - px(22), r + (self.h - n) // 2, anchor="nw", image=glyph(self, "down", n, TEXT4))

    def configure(self, cnf=None, **kw):
        if "values" in kw:
            self._values = list(kw.pop("values"))
        if kw or cnf:
            super().configure(cnf, **kw)
        self._paint()

    config = configure

    def current(self, i=None):
        if i is None:
            return self._i
        self._i = i
        self._paint()

    def get(self):
        return self._values[self._i] if 0 <= self._i < len(self._values) else ""


class _Mark(tk.Frame):
    """체크·라디오 공통 - 칸은 그림, 글자는 Label. 변수가 바뀌면 다시 그린다."""
    def __init__(self, parent, text, variable, command, font):
        super().__init__(parent, bg=parent.cget("bg"), cursor="hand2")
        self.var, self.command, self.n, self._over = variable, command, px(16), False
        self.mark = tk.Canvas(self, width=self.n, height=self.n, bg=self.cget("bg"), highlightthickness=0, cursor="hand2")
        self.mark.pack(side="left")
        self.parts = [self, self.mark]
        if text:
            lab = tk.Label(self, text=text, font=font, bg=self.cget("bg"), fg=TEXT, cursor="hand2")
            lab.pack(side="left", padx=(px(6), 0))
            self.parts.append(lab)
        for x in self.parts:
            x.bind("<Button-1>", lambda e: self._click())
            x.bind("<Enter>", lambda e: self._hover(True), add="+")
            x.bind("<Leave>", lambda e: self._hover(False), add="+")
        self._trace = variable.trace_add("write", lambda *a: self._paint())
        self.bind("<Destroy>", self._gone)           # 변수는 다시 그려도 남는다 - 사라진 부품을 부르지 않게
        self._paint()

    def _gone(self, e):
        if e.widget is self:
            try:
                self.var.trace_remove("write", self._trace)
            except tk.TclError:
                pass

    def _hover(self, on):
        self._over = on
        self._paint()

    def configure(self, cnf=None, **kw):
        if "bg" in kw:                               # 단계 줄 올림 색이 칸 뒤까지
            for x in self.parts[1:]:
                x.configure(bg=kw["bg"])
        super().configure(cnf, **kw)

    config = configure


class Check(_Mark):
    def __init__(self, parent, variable=None, command=None, text="", font=F):
        super().__init__(parent, text, variable or tk.BooleanVar(parent, value=False), command, font)

    def _click(self):
        self.var.set(not self.var.get())
        if self.command:
            self.command()

    def _paint(self):
        m, n = self.mark, self.n
        m.delete("all")
        if self.var.get():
            m.create_image(0, 0, anchor="nw", image=box(self, n, n, 4, P_HOVER if self._over else PRIMARY))
            m.create_image(0, 0, anchor="nw", image=glyph(self, "check", n, "#ffffff"))
        else:
            m.create_image(0, 0, anchor="nw", image=box(self, n, n, 4, CARD, PRIMARY if self._over else BORDER))


class Radio(_Mark):
    def __init__(self, parent, text, value, variable, command=None, font=F):
        self.value = value
        super().__init__(parent, text, variable, command, font)

    def _click(self):
        self.var.set(self.value)
        if self.command:
            self.command()

    def _paint(self):
        m, n = self.mark, self.n
        m.delete("all")
        if self.var.get() == self.value:
            m.create_image(0, 0, anchor="nw", image=box(self, n, n, 8, PRIMARY))
            m.create_image(0, 0, anchor="nw", image=glyph(self, "dot", n, "#ffffff"))
        else:
            m.create_image(0, 0, anchor="nw", image=box(self, n, n, 8, CARD, PRIMARY if self._over else BORDER))


class Card(tk.Canvas):
    """둥근 카드. fill 이면 자리를 다 쓰고(단계 목록), 아니면 안쪽 내용 높이에 맞춘다. 내용은 .inner 에."""
    def __init__(self, parent, pad, fill=False):
        super().__init__(parent, bg=parent.cget("bg"), highlightthickness=0)
        self.pad, self.fill = pad, fill
        self.inner = tk.Frame(self, bg=CARD)
        self._win = self.create_window(pad, pad, anchor="nw", window=self.inner)
        self._img = None
        self.bind("<Configure>", self._paint)
        if not fill:
            self.inner.bind("<Configure>", lambda e: self.config(height=self.inner.winfo_reqheight() + pad * 2))

    def _paint(self, e):
        self._img = _to_photo(self, _box_image(e.width, e.height, 8, CARD, SPLIT, 1, 2))     # 큰 그림이라 두 배만
        self.delete("bg")
        self.create_image(0, 0, anchor="nw", image=self._img, tags="bg")
        self.tag_lower("bg")
        self.itemconfigure(self._win, width=e.width - self.pad * 2)
        if self.fill:
            self.itemconfigure(self._win, height=e.height - self.pad * 2)


class Bar(tk.Canvas):
    """얇은 스크롤바. Scrollbar 처럼 set(처음, 끝) 을 받고 command('moveto', 비율) 을 부른다. 넘치지 않으면 안 보인다."""
    def __init__(self, parent, orient="vertical", command=None):
        self.vertical, self.command, self.t = orient == "vertical", command, px(6)
        self.first, self.last, self._grab, self._over = 0.0, 1.0, None, False
        super().__init__(parent, bg=parent.cget("bg"), highlightthickness=0, **({"width": self.t + px(4)} if self.vertical else {"height": self.t + px(4)}))
        self.bind("<Configure>", lambda e: self._paint())
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<B1-Motion>", self._drag)
        self.bind("<ButtonRelease-1>", lambda e: setattr(self, "_grab", None))
        self.bind("<Enter>", lambda e: self._hover(True))
        self.bind("<Leave>", lambda e: self._hover(False))

    def _size(self):
        return self.winfo_height() if self.vertical else self.winfo_width()

    def _hover(self, on):
        self._over = on
        self._paint()

    def set(self, first, last):
        self.first, self.last = float(first), float(last)
        self._paint()

    def _paint(self):
        self.delete("all")
        n = self._size()
        if n < 10 or (self.first <= 0 and self.last >= 1):
            return
        a, b = self.first * n + self.t / 2, max(self.last * n - self.t / 2, self.first * n + self.t)
        mid = (self.t + px(4)) / 2
        xy = (mid, a, mid, b) if self.vertical else (a, mid, b, mid)
        self.create_line(*xy, width=self.t, capstyle="round", fill=TEXT4 if self._over or self._grab is not None else BORDER)

    def _at(self, e):
        return (e.y if self.vertical else e.x) / max(self._size(), 1)

    def _press(self, e):
        at = self._at(e)
        self._grab = at - self.first if self.first <= at <= self.last else (self.last - self.first) / 2
        self._drag(e)

    def _drag(self, e):
        if self._grab is not None and self.command:
            self.command("moveto", self._at(e) - self._grab)


class Tabs(tk.Frame):
    """프리셋 탭 줄. 넘치면 얇은 가로 스크롤바·휠, 오른쪽 ⋯ 로 전체 목록. 고른 탭은 보이는 자리로 온다."""
    def __init__(self, parent, on_select, font=F, bold=F_BOLD):
        super().__init__(parent, bg=parent.cget("bg"))
        self.on_select, self.font, self.bold = on_select, font, bold
        self.tabs, self.items, self.cur, self.busy = [], [], None, False
        self.columnconfigure(0, weight=1)
        self.view = tk.Canvas(self, bg=self.cget("bg"), highlightthickness=0, height=px(36), xscrollincrement=px(30))
        self.view.grid(row=0, column=0, sticky="we")
        self.strip = tk.Frame(self.view, bg=self.cget("bg"))
        self.view.create_window(0, 0, anchor="nw", window=self.strip)
        self.more = Icon(self, "more", self._open, size=16, color=TEXT3)
        self.bar = Bar(self, "horizontal", self.view.xview)
        self.bar.grid(row=1, column=0, sticky="we")
        self.view.configure(xscrollcommand=self.bar.set)
        self.strip.bind("<Configure>", self._fit)
        self.view.bind("<Configure>", self._fit)
        self._wheel(self.view)
        self._wheel(self.strip)

    def _wheel(self, w):
        w.bind("<MouseWheel>", self._roll)

    def _roll(self, e):
        self.view.xview_scroll(int(-e.delta / 120) * 3, "units")
        return "break"                              # 단계 목록까지 굴리지 않게

    def _fit(self, e=None):
        self.view.configure(scrollregion=(0, 0, self.strip.winfo_reqwidth(), 0), height=self.strip.winfo_reqheight())
        over = self.strip.winfo_reqwidth() > self.view.winfo_width() > 1
        if over and not self.more.winfo_ismapped():
            self.more.grid(row=0, column=1, padx=(px(6), 0))
        elif not over and self.more.winfo_ismapped():
            self.more.grid_remove()

    def _open(self):
        items = [(text, UP_ON if up and up[0] else TEXT, not self.busy or i == self.cur) for i, (text, _, *up) in enumerate(self.items)]
        f, m = tkfont.Font(font=self.font), self.more
        width = max([f.measure(t) for t, *_ in items] + [px(160)]) + px(40)
        self._drop = DropList(self, items, self.cur, self.on_select, self.font,
                              m.winfo_rootx(), m.winfo_rooty() + m.winfo_height(), width, m.winfo_rooty())

    def _new_tab(self, i):
        t = tk.Frame(self.strip, bg=self.cget("bg"))
        t.pack(side="left", padx=(0, px(20)))
        row = tk.Frame(t, bg=self.cget("bg"))
        row.pack(pady=(px(2), px(7)))
        lab = tk.Label(row, font=self.font, bg=self.cget("bg"))
        lab.pack(side="left")
        n = px(6)
        dot = tk.Canvas(row, width=n, height=n, bg=self.cget("bg"), highlightthickness=0)
        dot.create_image(0, 0, anchor="nw", image=box(self, n, n, 3, PRIMARY))
        line = tk.Frame(t, bg=self.cget("bg"), height=px(2))
        line.pack(fill="x")
        for x in (t, row, lab, dot):
            x.bind("<Button-1>", lambda e, i=i: self._click(i))
            self._wheel(x)
        self.tabs.append((t, lab, dot, line))

    def _click(self, i):
        if not self.busy or i == self.cur:
            self.on_select(i)

    def show(self, items, cur, recording, busy):
        """items: [(글자, 기록 있음, 업로드)]. 선택 파랑, 기록 중 빨강, 기록 있음 파란 점, 비어 있음 흐린 글자. 업로드 프리셋은 초록 둥근 바탕."""
        while len(self.tabs) < len(items):
            self._new_tab(len(self.tabs))
        while len(self.tabs) > len(items):
            self.tabs.pop()[0].destroy()
        moved = cur != self.cur
        self.items, self.cur, self.busy = items, cur, busy
        for i, ((text, has, *up), (t, lab, dot, line)) in enumerate(zip(items, self.tabs)):
            if up and up[0] and recording != i:
                on = i == cur
                shown, font = text + ("  •" if has and not on else ""), self.bold if on else self.font
                fill = UP_ON if on else UP_TAB if has else UP_EMPTY
                lab.config(text=shown, image=box(lab, _font_of(lab, font).measure(shown) + px(20), px(24), px(6), fill), compound="center",
                           fg="#ffffff" if on or has else UP_ON, font=font, cursor="arrow" if busy and not on else "hand2")
                line.config(bg=UP_ON if on else self.cget("bg"))
                dot.pack_forget()
                continue
            lab.config(image="", compound="none")
            color = DANGER if recording == i else PRIMARY if i == cur else TEXT if has else TEXT3
            lab.config(text=text, fg=color, font=self.bold if i == cur or recording == i else self.font,
                       cursor="arrow" if busy and i != cur else "hand2")
            line.config(bg=color if i == cur or recording == i else self.cget("bg"))
            if has and i != cur and recording != i:
                dot.pack(side="left", padx=(px(4), 0))
            else:
                dot.pack_forget()
        if moved:
            self.after_idle(self._reveal)

    def _reveal(self):
        """고른 탭이 보이는 자리로."""
        if self.cur is None or self.cur >= len(self.tabs) or not self.winfo_exists():
            return
        self.update_idletasks()
        t, total = self.tabs[self.cur][0], max(self.strip.winfo_reqwidth(), 1)
        left, right = t.winfo_x(), t.winfo_x() + t.winfo_width()
        first, last = (v * total for v in self.view.xview())
        if left < first:
            self.view.xview_moveto(left / total)
        elif right > last:
            self.view.xview_moveto((right - (last - first)) / total)

    def texts(self):
        return [text for text, *_ in self.items]


class Status(tk.Label):
    """상태 줄. '●' 로 시작하는 글(기록 중)은 굵게."""
    def configure(self, cnf=None, **kw):
        if "text" in kw:
            kw["font"] = F_BOLD if kw["text"].startswith("●") else F
        super().configure(cnf, **kw)

    config = configure


class Switch(tk.Canvas):
    """켜고 끄는 스위치 36x20, 손잡이 16, 0.2초 ease-out. 놓을 때 command(켬) - 화면을 먼저 바꾸고 손잡이가 움직인다."""
    W, H, K, FRAMES = 36, 20, 16, 10

    def __init__(self, parent, command):
        super().__init__(parent, width=px(self.W), height=px(self.H), bg=parent.cget("bg"), highlightthickness=0, cursor="hand2")
        self.on, self.t, self.command, self.job = False, 0.0, command, None
        self.item = self.create_image(0, 0, anchor="nw")
        self.bind("<Button-1>", lambda e: self.command(not self.on))
        self._paint()

    def _frame(self, n):
        def make():
            ss, t = 4, n / self.FRAMES
            W, H, K = px(self.W) * ss, px(self.H) * ss, px(self.K) * ss
            im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            d = ImageDraw.Draw(im)
            d.rounded_rectangle((0, 0, W - 1, H - 1), H // 2, fill=tuple(round(a + (b - a) * t) for a, b in zip(ImageColor.getrgb(SWITCH_OFF), ImageColor.getrgb(SWITCH_ON))))
            x, y = round((W - K) / 2 + (t * 2 - 1) * ((W - K) / 2 - 2 * ss)), (H - K) // 2
            d.ellipse((x, y, x + K, y + K), fill="#ffffff")
            return im.resize((W // ss, H // ss), Image.LANCZOS)
        return _photo(self, ("switch", n, self.W), make)

    def _paint(self):
        self.itemconfigure(self.item, image=self._frame(round(self.t * self.FRAMES)))

    def set(self, on, animate=False):
        """animate 가 아니면 바로 그 자리로 (프리셋을 옮겼을 때)."""
        self.on = on
        if self.job:
            self.after_cancel(self.job)
            self.job = None
        if not animate:
            self.t = 1.0 if on else 0.0
            return self._paint()

        def step(k, start):
            e = 1 - (1 - (k + 1) / self.FRAMES) ** 3             # ease-out
            self.t = start + ((1.0 if on else 0.0) - start) * e
            self._paint()
            self.job = self.after(20, step, k + 1, start) if k + 1 < self.FRAMES else None
        step(0, self.t)


def mark(widget, kind, size, color="#ffffff"):
    """동그라미 안 표시: x·minus·skip. 얇은 획을 줄이면 자글자글해 굵게, 끝을 둥글게, 8배로 그려 줄인다."""
    def make():
        ss = 8
        n = size * ss
        im = Image.new("L", (n, n), 0)
        d = ImageDraw.Draw(im)
        if kind == "skip":                      # 삼각형 + 막대 하나
            tri = [(n * .2, n * .22), (n * .2, n * .78), (n * .62, n * .5)]
            d.polygon(tri, fill=255)
            d.line(tri + tri[:2], fill=255, width=round(n * .08), joint="curve")
            d.rounded_rectangle((n * .7, n * .18, n * .84, n * .82), round(n * .04), fill=255)
        else:
            strokes = [((.22, .22), (.78, .78)), ((.78, .22), (.22, .78))] if kind == "x" else [((.2, .5), (.8, .5))]
            width = round(n * .15)
            for a, b in strokes:
                ends = ((a[0] * n, a[1] * n), (b[0] * n, b[1] * n))
                d.line(ends, fill=255, width=width)
                for x, y in ends:
                    d.ellipse((x - width / 2, y - width / 2, x + width / 2, y + width / 2), fill=255)
        out = Image.new("RGBA", (size, size), (*ImageColor.getrgb(color), 0))
        out.putalpha(im.resize((size, size), Image.BOX))
        return out
    return _photo(widget, ("mark", kind, size, color), make)


def spin_frames(widget, n=30):
    """진행 중 고리: 굵기 3, 지름 20, 왼쪽 1/4 비움, 1초에 한 바퀴. 바탕이 비치게 (줄 올림 색)."""
    def frame(f):
        def make():
            ss, size = 4, px(StepDot.SIZE)
            big, inset = size * ss, px(2) * ss
            mask = Image.new("L", (big, big), 0)
            turn = 360 * f / n
            ImageDraw.Draw(mask).arc((inset, inset, big - 1 - inset, big - 1 - inset), 225 + turn, 135 + turn + 360, fill=255, width=px(3) * ss)
            out = Image.new("RGBA", (size, size), (*ImageColor.getrgb(STEP_INK), 0))
            out.putalpha(mask.resize((size, size), Image.BOX))
            return out
        return _photo(widget, ("spin", f, n), make)
    return [frame(f) for f in range(n)]


class StepDot(tk.Canvas):
    """작업 순서의 단계 동그라미와 잇는 줄. 상태만 바꾸면 그 동그라미만 다시 그린다 (목록을 새로 만들지 않아 반짝이지 않는다).
    idle 평소 / wait 대기 / run 진행 중 / done 완료 / off 체크 해제 / auto 화면에 없어 건너뜀 / stop 사람이 중단 / fail 실패."""
    SIZE, OFF = 24, 6        # OFF: 같은 줄의 체크·대기 칸과 가운데를 맞춘다
    FILLS = {"idle": STEP_INK, "done": STEP_DONE, "off": STEP_SKIP, "auto": STEP_MUTE, "stop": STEP_MUTE, "fail": "#cf1322"}
    MARKS = {"off": "skip", "auto": "minus", "fail": "x"}

    def __init__(self, parent, n, state, first, last):
        size, off = px(self.SIZE), px(self.OFF)
        super().__init__(parent, width=size, height=size + 2 * off, bg=parent.cget("bg"), highlightthickness=0)
        self.n, self.state, self.first, self.last, self.job = n, state, first, last, None
        self.bind("<Configure>", lambda e: self._draw())

    def set_state(self, state):
        if state != self.state:
            self.state = state
            self._draw()

    def _draw(self):
        size, off, state = px(self.SIZE), px(self.OFF), self.state
        mid = off + size / 2
        self.delete("all")
        if self.job:
            self.after_cancel(self.job)
            self.job = None
        top, bottom = off + size if self.first else 0, off if self.last else self.winfo_height()
        if top < bottom:
            self.create_rectangle(size // 2 - 1, top, size // 2 + 1, bottom, fill=STEP_LINE, outline="")
        if state == "run":
            frames = spin_frames(self)
            item = self.create_image(0, off, anchor="nw", image=frames[0])

            def spin(k):
                if not self.winfo_exists():          # 목록을 새로 그렸다
                    return
                self.itemconfigure(item, image=frames[k % len(frames)])
                self.job = self.after(1000 // len(frames), spin, k + 1)
            return spin(0)
        fill = self.FILLS.get(state)
        self.create_image(0, off, anchor="nw", image=box(self, size, size, size // 2, fill) if fill else box(self, size, size, size // 2, "#ffffff", STEP_LINE, 2))
        if state == "done":
            self.create_image(size / 2, mid, image=glyph(self, "check", px(14), "#ffffff"))
        elif state == "stop":
            q = px(4)
            self.create_rectangle(size / 2 - q, mid - q, size / 2 + q, mid + q, fill="#ffffff", outline="")
        elif state in self.MARKS:
            self.create_image(size / 2, mid, image=mark(self, self.MARKS[state], px(16 if state == "off" else 14)))
        else:
            self.create_text(size / 2, mid, text=str(self.n), font=(UI, 8, "bold"), fill="#ffffff" if state == "idle" else STEP_MUTE)


def hover_row(row, *more):
    """줄과 그 안 부품에 올림 색. 부품끼리 옮겨 다녀도 깜빡이지 않게 나가자마자 다시 들어온다. more: 줄 안 틀의 부품."""
    parts = [row, *row.winfo_children(), *more]

    def tint(color):
        for x in parts:
            x.configure(bg=color)
    for x in parts:
        x.bind("<Enter>", lambda e: tint(ROW_HOVER), add="+")
        x.bind("<Leave>", lambda e: tint(CARD), add="+")


def self_check():
    """exe 에서 그림이 나오는지 (--check). 창을 띄우지 않는다."""
    root = tk.Tk()
    root.withdraw()
    init(1.0)
    try:
        ok = (box(root, 32, 32, 6, PRIMARY).width() == 32 and glyph(root, "check", 16, "#ffffff").height() == 16
              and mark(root, "skip", 16).width() == 16 and len(spin_frames(root)) == 30)
    finally:
        root.destroy()
    return ok
