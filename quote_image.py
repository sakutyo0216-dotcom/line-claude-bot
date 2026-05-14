"""今日ネム風テロップ画像ジェネレータ

LINES に複数行で名言本文を入れる。CLI第1引数 "line1|line2" でも上書き可。
出力: data/quote_sample.png
"""
import os
import sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont

LINES = [
    "笑いたい奴には笑わせとけ。",
    "お前が黙る理由には1ミリもならねぇ。",
]

if len(sys.argv) > 1:
    LINES = sys.argv[1].split("|")

W, H = 1280, 720
BG = (0, 0, 0)
FONT_PATH = "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf"

img  = Image.new("RGB", (W, H), BG)
draw = ImageDraw.Draw(img)

# ── 左上: 今日ネム ♡ / チェンマイ編
logo_font  = ImageFont.truetype(FONT_PATH, 38)
heart_font = ImageFont.truetype(FONT_PATH, 30)
sub_font   = ImageFont.truetype(FONT_PATH, 18)
draw.text((30, 22), "今日ネム", font=logo_font, fill=(255, 255, 255))
logo_bb = draw.textbbox((30, 22), "今日ネム", font=logo_font)
draw.text((logo_bb[2] + 6, 30), "♡", font=heart_font, fill=(255, 130, 180))
draw.line([(40, 70), (185, 70)], fill=(255, 110, 160), width=2)
draw.text((52, 76), "チェンマイ編", font=sub_font, fill=(255, 255, 255))

# ── 右上: タグライン
tag_font = ImageFont.truetype(FONT_PATH, 22)
tagline  = "都合のいい奇跡はない。"
tb = draw.textbbox((0, 0), tagline, font=tag_font)
draw.text((W - (tb[2] - tb[0]) - 30, 28), tagline, font=tag_font, fill=(255, 255, 255))

# ── 字幕本文(横幅に応じて自動縮小)
def fit_font(lines, max_size=64, min_size=28, max_w=W - 80):
    size = max_size
    while size > min_size:
        f = ImageFont.truetype(FONT_PATH, size)
        if all((draw.textbbox((0, 0), s, font=f)[2] - draw.textbbox((0, 0), s, font=f)[0]) <= max_w for s in lines):
            return f, size
        size -= 2
    return ImageFont.truetype(FONT_PATH, min_size), min_size

big_font, qsize = fit_font(LINES)
line_h  = int(qsize * 1.35)
total_h = line_h * len(LINES)
y_start = H - total_h - 70

# (a) 黒の太い縁取り(stroke + fill 黒で文字より一回り太い黒塊を作る)
y = y_start
for line in LINES:
    draw.text(
        (W // 2, y), line,
        font=big_font, fill=(0, 0, 0),
        stroke_width=5, stroke_fill=(0, 0, 0),
        anchor="mt",
    )
    y += line_h

# (b) ピンク→シアンの縦グラデを字幕領域に生成
text_top = y_start
text_bot = y_start + total_h
grad = np.zeros((H, W, 3), dtype=np.uint8)
for yy in range(H):
    if yy <= text_top:
        t = 0.0
    elif yy >= text_bot:
        t = 1.0
    else:
        t = (yy - text_top) / max(1, (text_bot - text_top))
    r = int(255 * (1 - t) + 150 * t)
    g = int(180 * (1 - t) + 240 * t)
    b = int(225 * (1 - t) + 230 * t)
    grad[yy, :] = (r, g, b)
grad_img = Image.fromarray(grad)

# (c) 文字内側の白マスク
mask = Image.new("L", (W, H), 0)
mdraw = ImageDraw.Draw(mask)
y = y_start
for line in LINES:
    mdraw.text((W // 2, y), line, font=big_font, fill=255, anchor="mt")
    y += line_h

# (d) マスク経由でグラデを貼る
img.paste(grad_img, (0, 0), mask)

out = os.path.join(os.path.dirname(__file__), "data", "quote_sample.png")
img.save(out, "PNG")
print(f"saved: {out}")
