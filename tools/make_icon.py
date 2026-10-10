"""生成 `assets/auto_type.ico`（多尺寸应用图标）。

构建期一次性工具，需要 Pillow；**运行期与打包期都不需要它**——
产物 `assets/auto_type.ico` 已提交入库，`build.py` 只读不生成。

用法：
    C:\\Python314\\python.exe tools\\make_icon.py

图形含义：深蓝圆角底 + 三行白色文本行 + 行尾一枚琥珀色光标，就是"自动打字"。
笔画刻意画粗，保证缩到 16x16 还能认出来。
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "assets" / "auto_type.ico"

# 画布按 512 设计，再由 Pillow 逐尺寸 LANCZOS 缩小
CANVAS = 512
SIZES = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)]

BG_TOP = (59, 130, 246)  # #3B82F6
BG_BOTTOM = (29, 78, 216)  # #1D4ED8
BAR = (255, 255, 255)
CARET = (251, 191, 36)  # #FBBF24


def _gradient(size: int) -> Image.Image:
    """从左上到右下的线性渐变。"""
    base = Image.new("RGB", (size, size))
    pixels = base.load()
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * (size - 1))
            pixels[x, y] = tuple(
                round(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(3)
            )
    return base


def render() -> Image.Image:
    # 渐变铺满后再用圆角遮罩抠出圆角方块
    canvas = _gradient(CANVAS).convert("RGBA")

    mask = Image.new("L", (CANVAS, CANVAS), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, CANVAS - 1, CANVAS - 1), radius=112, fill=255
    )
    icon = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    icon.paste(canvas, (0, 0), mask)

    draw = ImageDraw.Draw(icon)

    # 三行文本行：从上到下依次变短
    bar_height = 56
    left = 96
    widths = [320, 250, 190]
    tops = [116, 228, 340]
    for width, top in zip(widths, tops):
        draw.rounded_rectangle(
            (left, top, left + width, top + bar_height),
            radius=bar_height // 2,
            fill=BAR,
        )

    # 行尾光标：只比文本行高一点，压在第三行中心线上
    caret_width = 42
    caret_height = 104
    caret_left = left + widths[-1] + 44
    caret_top = tops[-1] + bar_height // 2 - caret_height // 2
    draw.rounded_rectangle(
        (caret_left, caret_top, caret_left + caret_width, caret_top + caret_height),
        radius=caret_width // 2,
        fill=CARET,
    )

    return icon


def main() -> int:
    icon = render()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    icon.save(OUTPUT, format="ICO", sizes=SIZES)
    size_kb = OUTPUT.stat().st_size / 1024
    print(f"已生成 {OUTPUT.relative_to(ROOT)}")
    print(f"  尺寸: {', '.join(f'{w}x{h}' for w, h in SIZES)}")
    print(f"  大小: {size_kb:.1f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
