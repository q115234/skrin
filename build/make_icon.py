"""Рисует значок программы skrin.ico (синяя «камера», как в трее)."""
from pathlib import Path

from PIL import Image, ImageDraw

S = 256
im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(im)
k = S / 64
blue = (10, 132, 255, 255)
d.rounded_rectangle([4 * k, 10 * k, 60 * k, 54 * k], radius=10 * k, fill=blue)
d.ellipse([20 * k, 20 * k, 44 * k, 44 * k], fill=(255, 255, 255, 255))
d.ellipse([26 * k, 26 * k, 38 * k, 38 * k], fill=blue)
out = Path(__file__).with_name("skrin.ico")
im.save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print(out)
