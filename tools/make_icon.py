r"""AFTER MARKET 아이콘(release/AFTER_MARKET.ico)을 만든다 (2026-09-30 사용자가 고른 '크림 반투명 잔상' 시안).

    .venv\Scripts\python.exe tools\make_icon.py

짙은 청록 둥근 사각형 위에 앞으로 기운 크림색 A, 그 뒤를 흐린 M 이 따라온다 (AFTER = 뒤따르는).
글자는 글꼴 없이 다각형으로 그린다 (글꼴 라이선스와 무관). 16·20·24px 은 M 이 뭉개져서 A 만 넣는다.
설정 창·설치 파일·바로 가기·두 exe 가 이 파일을 쓴다 (build_release.PROGRAM_FILES·NUITKA_COMMON, release/installer.iss).
"""
import os

from PIL import Image, ImageChops, ImageDraw, ImageFilter

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ICO_PATH = os.path.join(REPO, "release", "AFTER_MARKET.ico")

N = 1024                       # 그리는 해상도
BG = (0x00, 0x2B, 0x36)        # 웹 대시보드 다크 바탕
CREAM = (0xFD, 0xF6, 0xE3)     # 웹 대시보드 밝은 바탕
M_ALPHA = 0.30                 # M 잔상 농도
SHEAR = 0.21                   # 약 12도 앞으로
FILL = 0.70                    # 글자 묶음이 네모에서 차지하는 비율
M_SHIFT = -190                 # A 기준 M 이 뒤로 물러난 거리 (글자 높이 480 기준)
SMALL = (16, 20, 24)           # A 만
LARGE = (32, 40, 48, 64, 128, 256)

# 똑바로 선 글자 (글자 왼쪽 위 기준, 높이 480)
A_OUT = [(0, 480), (170, 0), (250, 0), (420, 480), (310, 480), (271, 370), (149, 370), (110, 480)]
A_HOLE = [(184, 270), (210, 198), (236, 270)]
A_HULL = [(0, 480), (170, 0), (250, 0), (420, 480)]      # M 을 가리는 A 의 겉윤곽
M_OUT = [(0, 480), (0, 0), (110, 0), (240, 230), (370, 0), (480, 0), (480, 480),
         (380, 480), (380, 190), (270, 380), (210, 380), (100, 190), (100, 480)]
_k = (420 - 250) / 480                                    # A 오른쪽 바깥 선 기울기
RIGHT_OF_A = [(250 - 2000 * _k, -2000), (250 + 3000 * _k, 3000), (9000, 3000), (9000, -2000)]  # M 이 A 앞으로 삐지지 않게


def _shear(poly, dx=0):
    return [(x + dx + SHEAR * (240 - y), y) for x, y in poly]


def _mask(polys, holes=()):
    m = Image.new("L", (N, N), 0)
    d = ImageDraw.Draw(m)
    for p in polys:
        d.polygon(p, fill=255)
    for h in holes:
        d.polygon(h, fill=0)
    return m


def draw(with_m=True):
    """N×N RGBA 아이콘 한 장."""
    polys = {"a": _shear(A_OUT), "hole": _shear(A_HOLE), "hull": _shear(A_HULL),
             "m": _shear(M_OUT, M_SHIFT), "clip": _shear(RIGHT_OF_A)}
    pts = [p for k in (("a", "m") if with_m else ("a",)) for p in polys[k]]
    x0, x1 = min(p[0] for p in pts), max(p[0] for p in pts)
    y0, y1 = min(p[1] for p in pts), max(p[1] for p in pts)
    s = FILL * N / max(x1 - x0, y1 - y0)
    ox, oy = N / 2 - (x0 + x1) / 2 * s, N / 2 - (y0 + y1) / 2 * s
    P = {k: [(x * s + ox, y * s + oy) for x, y in v] for k, v in polys.items()}

    img = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    base = Image.new("L", (N, N), 0)
    ImageDraw.Draw(base).rounded_rectangle((0, 0, N - 1, N - 1), radius=int(N * 0.22), fill=255)
    img.paste(Image.new("RGBA", (N, N), BG + (255,)), (0, 0), base)
    if with_m:
        cover = _mask([P["hull"], P["clip"]]).filter(ImageFilter.MaxFilter(int(N * 0.03) | 1))   # A 둘레에 틈
        m = ImageChops.subtract(_mask([P["m"]]), cover).point(lambda v: int(v * M_ALPHA))
        img.paste(Image.new("RGBA", (N, N), CREAM + (255,)), (0, 0), m)
    img.paste(Image.new("RGBA", (N, N), CREAM + (255,)), (0, 0), _mask([P["a"]], [P["hole"]]))
    return img


def build(path=ICO_PATH):
    """크기별 그림을 담은 .ico 를 쓴다. 크기별로 쓴 그림을 돌려준다 (시험용)."""
    full, a_only = draw(True), draw(False)
    frames = {s: (a_only if s in SMALL else full).resize((s, s), Image.LANCZOS) for s in SMALL + LARGE}
    frames[256].save(path, format="ICO", sizes=[(s, s) for s in frames],
                     append_images=[im for s, im in frames.items() if s != 256])
    return frames


if __name__ == "__main__":
    frames = build()
    # 자체 점검: 모든 크기가 들어갔고, 크기마다 우리가 그린 그림이 그대로 들어갔다 (Pillow 가 다시 줄이지 않았다)
    ico = Image.open(ICO_PATH)
    assert set(ico.info["sizes"]) == {(s, s) for s in frames}, ico.info["sizes"]
    for s, im in frames.items():
        got = ico.ico.getimage((s, s)).convert("RGBA")
        assert ImageChops.difference(got, im).getbbox() is None, f"{s}px 가 다르다"
    print(f"ok {ICO_PATH} ({', '.join(str(s) for s in frames)}px)")
