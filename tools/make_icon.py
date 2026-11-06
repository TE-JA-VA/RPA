r"""오토파일럿 아이콘을 만든다 (2026-11-06 사용자가 고른 '마. 접힌 날개' - 흰 바탕 + 겹친 두 날개 그라데이션).

    release/AFTER_MARKET.ico          오토파일럿 (파랑)            설치 파일·설정 창·바로 가기·에이전트·감독
    release/AUTOPILOT_PROCESS.ico     PROCESS 오토파일럿 (파랑)    ERPia_RPA.exe
    release/AUTOPILOT_ACTOR.ico       ACTOR 오토파일럿 (분홍·보라) Prepare_RPA.exe (기록대로 엑셀을 받는 쪽)
    release/AFTER_MARKET_PREPARE.ico  옵저버 (주황)                Prepare_Observer.exe·그 창·시작 메뉴 바로 가기 (기록하는 창)
    firebase/web/img/icon.png         웹 대시보드 (민트)           브라우저 탭·휴대폰 홈 화면

    .venv\Scripts\python.exe tools\make_icon.py

도형은 tools/make_icon_mark.svg (앞에서부터 뒤 날개·앞 날개·겹침, 벡터 원본이라 인쇄 등에도 쓴다). 겹침은 투명도가 아니라
교집합 도형에 진한 색을 칠한다 - 작은 크기에서도 그대로. 파일 이름은 옛 것(AFTER_MARKET*)을 그대로 둔다 -
설치된 PC·바로 가기·시험이 그 이름을 본다.
쓰는 곳: build_release.PROGRAM_FILES·ICON*·NUITKA_EXTRA, release/installer.iss, rpa_settings·rpa_observer 의 ICON_NAME.
"""
import os
import re

import numpy as np
from PIL import Image, ImageDraw

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MARK = os.path.join(REPO, "tools", "make_icon_mark.svg")
PINK = ("#FF3DCB", "#8A3FFC", "#2F3CF0", "#1D1A9E")     # 뒤 날개 시작, 두 날개가 만나는 색, 앞 날개 끝, 겹침
BLUE = ("#22C3E6", "#2F7BF0", "#2A35C8", "#16207F")
ORANGE = ("#FF9A3D", "#FF3D81", "#A12BD6", "#6E1296")
MINT = ("#3DE0A8", "#12B5B0", "#1C6FD6", "#0E4F9C")
ICONS = {                              # 파일 → 색 (사용자가 정함 2026-11-06)
    "AFTER_MARKET.ico": BLUE,
    "AUTOPILOT_PROCESS.ico": BLUE,
    "AUTOPILOT_ACTOR.ico": PINK,
    "AFTER_MARKET_PREPARE.ico": ORANGE,
}
WEB_ICON = os.path.join(REPO, "firebase", "web", "img", "icon.png")
WEB_COLOR, WEB_SIZE = MINT, 180
N = 1024                               # 그리는 해상도
SS = 4                                 # 도형은 4배로 그려 줄인다
FILL = 0.78                            # 날개가 네모에서 차지하는 비율 (흰 바탕은 밝은 작업 표시줄에서 사라져 66% 는 작았다)
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def wings():
    """SVG 의 세 도형 [뒤, 앞, 겹침] - 각각 점 목록 하나 (M x y x y ... Z)."""
    with open(MARK, encoding="utf-8") as f:
        paths = re.findall(r' d="M([^"Z]+)Z"', f.read())
    assert len(paths) == 3, len(paths)
    return [np.array(p.split(), dtype=float).reshape(-1, 2) for p in paths]


def color(c):
    return np.array([int(c[i:i + 2], 16) for i in (1, 3, 5)], dtype=float)


def ramp(start, end, a, b):
    """N×N 대각선 그라데이션: 점 a 에서 start, 점 b 에서 end."""
    ys, xs = np.mgrid[0:N, 0:N]
    d = b - a
    t = np.clip(((xs - a[0]) * d[0] + (ys - a[1]) * d[1]) / (d @ d), 0, 1)[..., None]
    return Image.fromarray(np.uint8(color(start) * (1 - t) + color(end) * t + 0.5))


def mask(points):
    im = Image.new("L", (N * SS, N * SS), 0)
    ImageDraw.Draw(im).polygon([tuple(p) for p in points * SS], fill=255)
    return im.reduce(SS)


def draw(palette):
    """N×N RGBA 한 장: 흰 둥근 네모 + 가운데 두 날개."""
    a, b, c, deep = palette
    back, front, over = wings()
    low, high = np.vstack((back, front)).min(0), np.vstack((back, front)).max(0)
    k = FILL * N / (high - low).max()
    shift = (N - (high - low) * k) / 2 - low * k
    back, front, over = (p * k + shift for p in (back, front, over))
    p0, p1 = low * k + shift, high * k + shift
    shape = Image.new("L", (N * SS, N * SS), 0)
    ImageDraw.Draw(shape).rounded_rectangle((0, 0, N * SS - 1, N * SS - 1), radius=int(N * SS * 0.22), fill=255)
    img = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    img.paste(Image.new("RGBA", (N, N), (255, 255, 255, 255)), (0, 0), shape.reduce(SS))
    img.paste(ramp(a, b, p0, p1), (0, 0), mask(back))
    img.paste(ramp(b, c, p0, p1), (0, 0), mask(front))
    img.paste(Image.new("RGB", (N, N), deep), (0, 0), mask(over))
    return img


def build(path, palette):
    """크기별 그림을 담은 .ico 를 쓴다. 크기별로 쓴 그림을 돌려준다 (시험용)."""
    big = draw(palette)
    frames = {s: big.resize((s, s), Image.LANCZOS) for s in SIZES}
    frames[256].save(path, format="ICO", sizes=[(s, s) for s in frames],
                     append_images=[im for s, im in frames.items() if s != 256])
    return frames


if __name__ == "__main__":
    from PIL import ImageChops
    for name, palette in ICONS.items():
        path = os.path.join(REPO, "release", name)
        frames = build(path, palette)
        # 자체 점검: 모든 크기가 들어갔고, 크기마다 우리가 그린 그림이 그대로 들어갔다 (Pillow 가 다시 줄이지 않았다)
        ico = Image.open(path)
        assert set(ico.info["sizes"]) == {(s, s) for s in frames}, ico.info["sizes"]
        for s, im in frames.items():
            got = ico.ico.getimage((s, s)).convert("RGBA")
            assert ImageChops.difference(got, im).getbbox() is None, f"{path} {s}px 가 다르다"
        print(f"ok {path} ({', '.join(str(s) for s in frames)}px)")
    draw(WEB_COLOR).resize((WEB_SIZE, WEB_SIZE), Image.LANCZOS).save(WEB_ICON)
    print(f"ok {WEB_ICON} ({WEB_SIZE}px)")
