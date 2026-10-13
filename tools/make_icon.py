r"""오토파일럿 아이콘 넷을 만든다 (2026-10-13 사용자가 고른 'AP 나' - 바탕 + Cloud Dancer 글자).

    release/AFTER_MARKET.ico          오토파일럿 (Blue Fusion)   설치 파일·설정 창·바로 가기·에이전트·감독
    release/AUTOPILOT_PROCESS.ico     PROCESS 오토파일럿 (Hematite)      ERPia_RPA.exe
    release/AUTOPILOT_OBSERVER.ico    옵저버 (Cloud Cover)               Prepare_RPA.exe
    release/AFTER_MARKET_PREPARE.ico  ACTOR 오토파일럿 (Quiet Violet)    Prepare_Observer.exe·그 창·시작 메뉴 바로 가기

    .venv\Scripts\python.exe tools\make_icon.py

글자 모양은 사용자가 준 그림에서 뽑은 tools/make_icon_AP.png (회색조 = 덮는 정도). 바탕색은 사용자가 준 팬톤 표
(PANTONE 18-4218 Blue Fusion·17-5800 Hematite·16-1523 Cloud Cover·16-3610 Quiet Violet)에서 뽑았고, 흰 글씨 대비가
3:1 이 되게 Cloud Cover 는 7%, Quiet Violet 은 9% 짙게 했다. 파일 이름은 옛 것(AFTER_MARKET*)을 그대로 둔다 -
설치된 PC·바로 가기·시험이 그 이름을 본다.
쓰는 곳: build_release.PROGRAM_FILES·ICON*·NUITKA_EXTRA, release/installer.iss, rpa_settings·rpa_observer 의 ICON_NAME.
"""
import os

from PIL import Image, ImageDraw

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LETTERS = os.path.join(REPO, "tools", "make_icon_AP.png")
DANCER = (0xF0, 0xEF, 0xEB)            # PANTONE 11-4201 Cloud Dancer - 글자
ICONS = {                              # 파일 → 바탕
    "AFTER_MARKET.ico": (0x49, 0x62, 0x76),          # Blue Fusion
    "AUTOPILOT_PROCESS.ico": (0x74, 0x6F, 0x69),     # Hematite
    "AUTOPILOT_OBSERVER.ico": (0x8E, 0x88, 0x88),    # Cloud Cover 7% 짙게
    "AFTER_MARKET_PREPARE.ico": (0x99, 0x82, 0x9F),  # Quiet Violet 9% 짙게
}
N = 1024                               # 그리는 해상도
FILL = 0.74                            # 글자 폭이 네모에서 차지하는 비율
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def draw(bg):
    """N×N RGBA 한 장: 둥근 네모 (위가 6% 밝고 아래가 6% 짙은 결) + 가운데 글자."""
    top, bot = tuple(min(255, int(v * 1.06)) for v in bg), tuple(int(v * 0.94) for v in bg)
    grad = Image.new("RGBA", (N, N))
    d = ImageDraw.Draw(grad)
    for y in range(N):
        k = y / (N - 1)
        d.line([(0, y), (N, y)], fill=tuple(int(a + (b - a) * k) for a, b in zip(top, bot)) + (255,))
    mask = Image.new("L", (N, N), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, N - 1, N - 1), radius=int(N * 0.22), fill=255)
    img = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    img.paste(grad, (0, 0), mask)
    a = Image.open(LETTERS).convert("L")
    s = FILL * N / a.width
    a = a.resize((round(a.width * s), round(a.height * s)), Image.LANCZOS)
    img.paste(Image.new("RGBA", a.size, DANCER + (255,)), ((N - a.width) // 2, (N - a.height) // 2), a)
    return img


def build(path, bg):
    """크기별 그림을 담은 .ico 를 쓴다. 크기별로 쓴 그림을 돌려준다 (시험용)."""
    big = draw(bg)
    frames = {s: big.resize((s, s), Image.LANCZOS) for s in SIZES}
    frames[256].save(path, format="ICO", sizes=[(s, s) for s in frames],
                     append_images=[im for s, im in frames.items() if s != 256])
    return frames


if __name__ == "__main__":
    from PIL import ImageChops
    for name, bg in ICONS.items():
        path = os.path.join(REPO, "release", name)
        frames = build(path, bg)
        # 자체 점검: 모든 크기가 들어갔고, 크기마다 우리가 그린 그림이 그대로 들어갔다 (Pillow 가 다시 줄이지 않았다)
        ico = Image.open(path)
        assert set(ico.info["sizes"]) == {(s, s) for s in frames}, ico.info["sizes"]
        for s, im in frames.items():
            got = ico.ico.getimage((s, s)).convert("RGBA")
            assert ImageChops.difference(got, im).getbbox() is None, f"{path} {s}px 가 다르다"
        print(f"ok {path} ({', '.join(str(s) for s in frames)}px)")
