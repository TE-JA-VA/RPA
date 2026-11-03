r"""옵저버(Stand Alone) 아이콘 - 등대에서 불빛 하나가 나오는 모습 (사용자 2026-11-03).

    release/OBSERVER_SA.ico     단독 설치 파일·바로 가기·옵저버 창·관제 서버(Observer_Hub.exe)
    hub/favicon.png             관제 화면 탭 아이콘 (64px)

    .venv\Scripts\python.exe tools\make_icon_lighthouse.py

모양은 오토파일럿 아이콘(tools/make_icon.py)과 같은 둥근 네모에 밤바다 바탕. 등대 몸통은 Cloud Dancer, 띠와 지붕은 붉은색,
등불 칸에서 오른쪽 위로 불빛 한 줄기. 16px 에서도 등대와 불빛이 보이게 굵게 그린다 (작은 크기는 물결을 뺀다).
"""
import os

from PIL import Image, ImageChops, ImageDraw, ImageFilter

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
N = 1024
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
SKY_TOP, SKY_BOT = (0x1F, 0x2E, 0x4A), (0x2E, 0x4A, 0x6E)   # 밤하늘 → 바다 쪽
DANCER = (0xF0, 0xEF, 0xEB)        # 등대 몸통 (오토파일럿 글자색과 같다)
BAND = (0xC8, 0x4B, 0x3C)          # 몸통 띠·지붕 (붉은 띠 - 밤하늘과 갈리게)
LAMP = (0xFF, 0xD5, 0x4F)          # 등불
SEA = (0x3E, 0x63, 0x8C)


def _bg():
    grad = Image.new("RGBA", (N, N))
    d = ImageDraw.Draw(grad)
    for y in range(N):
        k = y / (N - 1)
        d.line([(0, y), (N, y)], fill=tuple(int(a + (b - a) * k) for a, b in zip(SKY_TOP, SKY_BOT)) + (255,))
    mask = Image.new("L", (N, N), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, N - 1, N - 1), radius=int(N * 0.22), fill=255)
    return grad, mask


def draw(small=False):
    """N×N RGBA 한 장. small 이면 물결을 빼고 선을 굵게 (24px 이하)."""
    grad, mask = _bg()
    img = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    img.paste(grad, (0, 0), mask)
    cx = int(N * 0.40)                       # 등대 가운데 (불빛이 오른쪽으로 나갈 자리를 둔다)
    lamp_y = int(N * 0.30)                   # 등불 높이
    # 불빛 한 줄기 - 등불에서 오른쪽 위로 넓어지는 부채꼴, 끝은 흐리게
    beam = Image.new("L", (N, N), 0)
    ImageDraw.Draw(beam).polygon([(cx, lamp_y - 22), (N * 1.02, lamp_y - (230 if not small else 300)),
                                  (N * 1.02, lamp_y + (70 if not small else 120)), (cx, lamp_y + 22)], fill=255)
    fade = Image.linear_gradient("L").rotate(90).resize((N, N))          # 왼쪽 밝고 오른쪽 흐림
    beam = ImageChops.multiply(beam, ImageChops.invert(fade).point(lambda v: 170 + v * 85 // 255))
    beam = beam.filter(ImageFilter.GaussianBlur(6 if not small else 2))
    beam = ImageChops.multiply(beam, mask)
    img.paste(Image.new("RGBA", (N, N), LAMP + (255,)), (0, 0), beam)
    d = ImageDraw.Draw(img)
    # 바다
    sea_y = int(N * 0.80)
    d.rectangle((0, sea_y, N, N), fill=SEA + (255,))
    if not small:
        for i, y in enumerate((sea_y + 60, sea_y + 120)):
            for x in range(-40 + i * 60, N, 160):
                d.arc((x, y - 24, x + 120, y + 24), 200, 340, fill=DANCER + (150,), width=14)
    img = Image.composite(img, Image.new("RGBA", (N, N), (0, 0, 0, 0)), mask)
    d = ImageDraw.Draw(img)
    # 몸통 (아래가 넓은 사다리꼴) + 띠 둘
    top_w, bot_w, body_top, body_bot = 150, 250, lamp_y + 70, sea_y + 10
    body = [(cx - top_w // 2, body_top), (cx + top_w // 2, body_top), (cx + bot_w // 2, body_bot), (cx - bot_w // 2, body_bot)]
    d.polygon(body, fill=DANCER + (255,))

    def band(y0, y1):
        def half(y):
            return top_w / 2 + (bot_w - top_w) / 2 * (y - body_top) / (body_bot - body_top)
        d.polygon([(cx - half(y0), y0), (cx + half(y0), y0), (cx + half(y1), y1), (cx - half(y1), y1)], fill=BAND + (255,))
    h = body_bot - body_top
    band(body_top + int(h * 0.22), body_top + int(h * 0.38))
    band(body_top + int(h * 0.60), body_top + int(h * 0.76))
    # 난간·등불 칸·지붕
    d.rectangle((cx - 115, lamp_y + 48, cx + 115, lamp_y + 76), fill=DANCER + (255,))
    d.rectangle((cx - 72, lamp_y - 52, cx + 72, lamp_y + 48), fill=LAMP + (255,))
    d.line((cx, lamp_y - 52, cx, lamp_y + 48), fill=BAND + (255,), width=10 if not small else 0)
    d.polygon([(cx - 100, lamp_y - 52), (cx + 100, lamp_y - 52), (cx, lamp_y - 150)], fill=BAND + (255,))
    d.ellipse((cx - 18, lamp_y - 178, cx + 18, lamp_y - 142), fill=BAND + (255,))
    # 등불 둘레 빛
    glow = Image.new("L", (N, N), 0)
    ImageDraw.Draw(glow).ellipse((cx - 120, lamp_y - 100, cx + 120, lamp_y + 100), fill=120)
    glow = ImageChops.multiply(glow.filter(ImageFilter.GaussianBlur(40)), mask)
    lit = Image.new("RGBA", (N, N), LAMP + (0,))
    lit.putalpha(glow)
    return Image.alpha_composite(img, lit)


def build(path):
    big, small = draw(), draw(small=True)
    frames = {s: (small if s <= 24 else big).resize((s, s), Image.LANCZOS) for s in SIZES}
    frames[256].save(path, format="ICO", sizes=[(s, s) for s in frames],
                     append_images=[im for s, im in frames.items() if s != 256])
    return frames, big


if __name__ == "__main__":
    ico_path = os.path.join(REPO, "release", "OBSERVER_SA.ico")
    frames, big = build(ico_path)
    ico = Image.open(ico_path)
    assert set(ico.info["sizes"]) == {(s, s) for s in frames}, ico.info["sizes"]
    os.makedirs(os.path.join(REPO, "hub"), exist_ok=True)
    big.resize((64, 64), Image.LANCZOS).save(os.path.join(REPO, "hub", "favicon.png"))
    print(f"ok {ico_path} ({', '.join(str(s) for s in frames)}px), hub/favicon.png")
