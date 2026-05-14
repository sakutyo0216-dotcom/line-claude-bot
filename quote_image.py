"""waywardjoe風 名言画像ジェネレータ(一案)"""
from PIL import Image, ImageDraw, ImageFont

# 「今日ネム」っぽい、短くて脱力系の名言一案
QUOTE = "今日ナマケ"
SIGN  = "— wayward joe (風)"

W, H = 1080, 1080
BG   = (15, 15, 15)
FG   = (240, 235, 220)
SUB  = (130, 125, 115)

FONT_PATH = "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf"

img  = Image.new("RGB", (W, H), BG)
draw = ImageDraw.Draw(img)

# 本文(横幅に収まる最大サイズへ自動調整)
MARGIN = 140
size = 320
while size > 40:
    f = ImageFont.truetype(FONT_PATH, size)
    b = draw.textbbox((0, 0), QUOTE, font=f)
    if (b[2]-b[0]) <= (W - MARGIN*2) and (b[3]-b[1]) <= (H - MARGIN*2):
        break
    size -= 4
font_big  = f
font_sign = ImageFont.truetype(FONT_PATH, 38)

bbox  = draw.textbbox((0, 0), QUOTE, font=font_big)
tw, th = bbox[2]-bbox[0], bbox[3]-bbox[1]
x = (W - tw) // 2 - bbox[0]
y = (H - th) // 2 - bbox[1] - 40
draw.text((x, y), QUOTE, font=font_big, fill=FG)

# 署名(右下)
sbox  = draw.textbbox((0, 0), SIGN, font=font_sign)
sw, sh = sbox[2]-sbox[0], sbox[3]-sbox[1]
draw.text((W - sw - 60, H - sh - 60), SIGN, font=font_sign, fill=SUB)

# 細い枠線
draw.rectangle([(30, 30), (W-30, H-30)], outline=SUB, width=2)

out = "/home/user/line-claude-bot/data/quote_sample.png"
img.save(out, "PNG")
print(f"saved: {out}")
