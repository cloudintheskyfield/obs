#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageColor, ImageDraw, ImageFilter


CANVAS_SIZE = 1024
BACKGROUND_COLOR = "#071119"
CARD_COLOR = "#08131f"
CARD_BORDER = "#0f2030"
CYAN = "#63e7ff"
BLUE = "#6f8cff"
DOT = "#7befff"


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _mix_hex(start: str, end: str, t: float) -> tuple[int, int, int, int]:
    s = ImageColor.getrgb(start)
    e = ImageColor.getrgb(end)
    return (
        int(_lerp(s[0], e[0], t)),
        int(_lerp(s[1], e[1], t)),
        int(_lerp(s[2], e[2], t)),
        255,
    )


def build_icon(size: int = CANVAS_SIZE) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    margin = int(size * 0.08)
    radius = int(size * 0.2)
    draw.rounded_rectangle(
        (margin, margin, size - margin, size - margin),
        radius=radius,
        fill=BACKGROUND_COLOR,
        outline=CARD_BORDER,
        width=max(4, size // 180),
    )

    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    glow_draw.ellipse(
        (size * 0.16, size * 0.16, size * 0.84, size * 0.84),
        fill=(74, 227, 255, 60),
    )
    glow = glow.filter(ImageFilter.GaussianBlur(radius=size * 0.045))
    image.alpha_composite(glow)

    ring_box = (size * 0.2, size * 0.2, size * 0.8, size * 0.8)
    ring_width = max(16, int(size * 0.055))
    for index, start in enumerate(range(-48, 280, 9)):
        t = index / max(1, ((280 + 48) // 9))
        color = _mix_hex(CYAN, BLUE, min(1.0, t))
        draw.arc(ring_box, start=start, end=start + 22, fill=color, width=ring_width)

    inner_box = (size * 0.315, size * 0.315, size * 0.685, size * 0.685)
    draw.ellipse(inner_box, fill=CARD_COLOR, outline=(19, 39, 59, 255), width=max(4, size // 220))

    tail_points = [
        (size * 0.49, size * 0.205),
        (size * 0.63, size * 0.205),
        (size * 0.765, size * 0.355),
        (size * 0.648, size * 0.348),
        (size * 0.565, size * 0.275),
        (size * 0.498, size * 0.312),
    ]
    draw.polygon(tail_points, fill=CYAN)

    dot_radius = size * 0.033
    dot_center = (size * 0.77, size * 0.23)
    draw.ellipse(
        (
            dot_center[0] - dot_radius,
            dot_center[1] - dot_radius,
            dot_center[0] + dot_radius,
            dot_center[1] + dot_radius,
        ),
        fill=DOT,
    )

    return image


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate desktop icon assets for OBS Code.")
    parser.add_argument("--png", type=Path, help="Output PNG path.")
    parser.add_argument("--ico", type=Path, help="Output ICO path.")
    parser.add_argument("--size", type=int, default=CANVAS_SIZE, help="Canvas size for PNG output.")
    args = parser.parse_args()

    icon = build_icon(args.size)

    if args.png:
        args.png.parent.mkdir(parents=True, exist_ok=True)
        icon.save(args.png, format="PNG")

    if args.ico:
        args.ico.parent.mkdir(parents=True, exist_ok=True)
        icon.save(
            args.ico,
            format="ICO",
            sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
        )


if __name__ == "__main__":
    main()
