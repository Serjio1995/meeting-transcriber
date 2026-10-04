"""Генерирует assets/icon.png, icon.ico, icon.icns программной отрисовкой.
Запуск перед сборкой:  python scripts/make_icons.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

ASSETS = Path(__file__).resolve().parents[1] / "assets"
ASSETS.mkdir(exist_ok=True)


def draw(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size / 64
    d.rounded_rectangle([6*s, 6*s, 58*s, 58*s], radius=16*s, fill="#e53935")
    d.rounded_rectangle([25*s, 14*s, 39*s, 34*s], radius=7*s, fill="white")
    d.rectangle([29.5*s, 33*s, 34.5*s, 43*s], fill="white")
    d.arc([21*s, 26*s, 43*s, 48*s], 20, 160, fill="white", width=max(2, int(3*s)))
    d.line([32*s, 47*s, 32*s, 54*s], fill="white", width=max(2, int(3*s)))
    return img


def main():
    img = draw(256)
    img.save(ASSETS / "icon.png")
    img.save(ASSETS / "icon.ico",
             sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                    (64, 64), (128, 128), (256, 256)])
    try:
        img.save(ASSETS / "icon.icns")
    except Exception as exc:
        print("⚠ icns не создан:", exc)
    print("OK:", ASSETS)


if __name__ == "__main__":
    main()