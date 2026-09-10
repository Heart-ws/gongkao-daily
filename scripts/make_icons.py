#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 PWA 图标四件套（纯标准库，不依赖 Pillow）。

运行：python scripts/make_icons.py
输出：icons/icon-192.png  icon-512.png  icon-maskable-512.png  apple-touch-icon.png

视觉：宣纸米白底 + 靛青书卷 + 朱砂印记，呼应网页配色。
"""
import math
import os
import struct
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "icons")

# 配色（宣纸米白 / 靛青 / 朱砂）
PAPER = (247, 243, 235)
INDIGO = (28, 58, 94)
INDIGO_LT = (58, 96, 138)
CINNABAR = (178, 52, 44)
GOLD = (198, 158, 88)


def write_png(path, w, h, rgb_bytes):
    raw = bytearray()
    stride = w * 3
    for y in range(h):
        raw.append(0)  # filter byte
        raw += rgb_bytes[y * stride:(y + 1) * stride]

    def chunk(tag, data):
        return struct.pack('>I', len(data)) + tag + data + \
            struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff)

    ihdr = struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)
    out = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr) + \
        chunk(b'IDAT', zlib.compress(bytes(raw), 9)) + chunk(b'IEND', b'')
    with open(path, 'wb') as f:
        f.write(out)


def blend(base, cover, alpha):
    a = max(0.0, min(1.0, alpha))
    return tuple(int(round(base[i] * (1 - a) + cover[i] * a)) for i in range(3))


def rounded_rect(buf, w, h, x0, y0, x1, y1, r, color, alpha=1.0):
    """在 buf 上画圆角矩形。"""
    for y in range(max(0, int(y0)), min(h, int(math.ceil(y1)))):
        cy = y + 0.5
        for x in range(max(0, int(x0)), min(w, int(math.ceil(x1)))):
            cx = x + 0.5
            if cx < x0 or cx > x1 or cy < y0 or cy > y1:
                continue
            # 圆角判定
            ok = True
            for (px, py) in ((x0 + r, y0 + r), (x1 - r, y0 + r), (x0 + r, y1 - r), (x1 - r, y1 - r)):
                if (cx < x0 + r or cx > x1 - r) and (cy < y0 + r or cy > y1 - r):
                    dx, dy = cx - px, cy - py
                    if dx * dx + dy * dy > r * r:
                        ok = False
            if not ok:
                continue
            i = (y * w + x) * 3
            cur = (buf[i], buf[i + 1], buf[i + 2])
            nxt = blend(cur, color, alpha)
            buf[i], buf[i + 1], buf[i + 2] = nxt


def line(buf, w, h, x0, y0, x1, y1, thick, color, alpha=1.0):
    steps = int(max(abs(x1 - x0), abs(y1 - y0)) * 2) + 1
    for s in range(steps + 1):
        t = s / steps
        cx = x0 + (x1 - x0) * t
        cy = y0 + (y1 - y0) * t
        rounded_rect(buf, w, h, cx - thick / 2, cy - thick / 2,
                     cx + thick / 2, cy + thick / 2, thick / 2, color, alpha)


def disc(buf, w, h, cx, cy, r, color, alpha=1.0):
    for y in range(max(0, int(cy - r - 1)), min(h, int(cy + r + 2))):
        for x in range(max(0, int(cx - r - 1)), min(w, int(cx + r + 2))):
            dx, dy = x + 0.5 - cx, y + 0.5 - cy
            d = math.sqrt(dx * dx + dy * dy)
            if d > r + 0.5:
                continue
            a = alpha * max(0.0, min(1.0, r + 0.5 - d))
            i = (y * w + x) * 3
            cur = (buf[i], buf[i + 1], buf[i + 2])
            nxt = blend(cur, color, a)
            buf[i], buf[i + 1], buf[i + 2] = nxt


def render(size, maskable=False):
    """2 倍超采样再降采样，得到抗锯齿效果。"""
    S = size * 2
    buf = bytearray(PAPER * (S * S))

    if maskable:
        # maskable 安全区：内容缩到画面 45% 以内
        scale = 0.45
    else:
        scale = 0.78

    c = S / 2
    # 背景：极浅靛青圆底，增加层次（仅非 maskable 明显）
    disc(buf, S, S, c, c, S * 0.40, (235, 233, 226), 1.0)

    # 书卷主体（两页打开的册页）
    half_w = S * 0.30 * (scale / 0.78)
    half_h = S * 0.24 * (scale / 0.78)
    thick = S * 0.022 * (scale / 0.78)

    # 左页 & 右页（略微内收，形成翻开书脊）
    rounded_rect(buf, S, S, c - half_w, c - half_h, c - thick * 0.6, c + half_h,
                 S * 0.02, INDIGO, 1.0)
    rounded_rect(buf, S, S, c + thick * 0.6, c - half_h, c + half_w, c + half_h,
                 S * 0.02, INDIGO, 1.0)
    # 书脊高光
    rounded_rect(buf, S, S, c - thick * 0.6, c - half_h, c + thick * 0.6, c + half_h,
                 thick * 0.6, INDIGO_LT, 1.0)

    # 页面横线（文字意象）
    for k in (-0.55, -0.15, 0.25, 0.62):
        y = c + half_h * k
        line(buf, S, S, c - half_w * 0.72, y, c - thick * 1.6, y,
             S * 0.016 * (scale / 0.78), PAPER, 0.92)
        line(buf, S, S, c + thick * 1.6, y, c + half_w * 0.72, y,
             S * 0.016 * (scale / 0.78), PAPER, 0.92)

    # 朱砂印（右下角小方印）
    seal = S * 0.085 * (scale / 0.78)
    sx, sy = c + half_w * 0.72, c + half_h * 0.92
    rounded_rect(buf, S, S, sx - seal, sy - seal, sx + seal, sy + seal,
                 seal * 0.22, CINNABAR, 0.95)
    disc(buf, S, S, sx, sy, seal * 0.42, PAPER, 0.9)

    # 顶部金线（书签）
    line(buf, S, S, c - half_w * 0.98, c - half_h - S * 0.055,
         c + half_w * 0.98, c - half_h - S * 0.055,
         S * 0.017 * (scale / 0.78), GOLD, 0.85)

    # 降采样
    out = bytearray(size * size * 3)
    for y in range(size):
        for x in range(size):
            r = g = b = 0
            for dy in (0, 1):
                for dx in (0, 1):
                    i = ((y * 2 + dy) * S + (x * 2 + dx)) * 3
                    r += buf[i]
                    g += buf[i + 1]
                    b += buf[i + 2]
            o = (y * size + x) * 3
            out[o] = r // 4
            out[o + 1] = g // 4
            out[o + 2] = b // 4
    return bytes(out)


def main():
    os.makedirs(OUT, exist_ok=True)
    jobs = [
        ("icon-192.png", 192, False),
        ("icon-512.png", 512, False),
        ("icon-maskable-512.png", 512, True),
        ("apple-touch-icon.png", 180, False),
    ]
    for name, size, mask in jobs:
        p = os.path.join(OUT, name)
        write_png(p, size, size, render(size, mask))
        print("wrote", p, os.path.getsize(p), "bytes")


if __name__ == "__main__":
    main()
