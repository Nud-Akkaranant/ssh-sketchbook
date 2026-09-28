"""Rebuild the Windows icon from the sketchbook logo (requires Pillow)."""

from pathlib import Path
from PIL import Image, ImageDraw


SCALE = 8
INK = "#30454d"
YELLOW = "#f7c681"


def point(x, y):
    return (round(x * SCALE), round(y * SCALE))


layer = Image.new("RGBA", point(64, 64), (0, 0, 0, 0))
draw = ImageDraw.Draw(layer)
draw.rounded_rectangle((*point(10, 12), *point(57, 59)), radius=11 * SCALE, fill=INK)
draw.rounded_rectangle((*point(8, 9), *point(55, 56)), radius=11 * SCALE, fill=YELLOW, outline=INK, width=round(2.5 * SCALE))
draw.rounded_rectangle((*point(17, 19), *point(46, 45)), radius=4 * SCALE, outline=INK, width=round(2.8 * SCALE))
draw.line([point(23, 27), point(28, 32), point(23, 37)], fill=INK, width=round(2.8 * SCALE), joint="curve")
draw.line([point(32, 37), point(40, 37)], fill=INK, width=round(2.8 * SCALE))
draw.arc((*point(18, 45), *point(45, 49)), 185, 355, fill=INK, width=round(1.8 * SCALE))
layer = layer.rotate(5, resample=Image.Resampling.BICUBIC)
icon = layer.resize((256, 256), Image.Resampling.LANCZOS)
target = Path(__file__).resolve().parent.parent / "static" / "icon.ico"
icon.save(target, format="ICO", sizes=[(size, size) for size in (16, 24, 32, 48, 64, 128, 256)])
print(target)
