#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""打包可发布版本到 dist/

只拷贝线上真正需要的文件，把开发脚手架（_dev/、scripts/、README.md、
.github/）和人工补录模板排除在外，发布出来的目录更干净、体积更小。

用法：
    python scripts/build_dist.py
    python scripts/build_dist.py --out dist        # 自定义输出目录
"""
from __future__ import annotations

import argparse
import glob
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# 线上必需：网页本身 + PWA 三件套 + 图标 + 数据
INCLUDE_FILES = ["index.html", "manifest.json", "sw.js"]
INCLUDE_DIRS = ["icons", "data"]
# 数据目录里不需要上线的
EXCLUDE_NAMES = {"manual"}          # 人工补录模板，属维护用，不必公开


def build(out_root: str) -> int:
    if not os.path.exists(os.path.join(ROOT, "index.html")):
        print("找不到 index.html，请在项目根目录下运行本脚本。")
        return 1

    if os.path.exists(out_root):
        shutil.rmtree(out_root, ignore_errors=True)
    os.makedirs(out_root, exist_ok=True)

    copied = 0
    for f in INCLUDE_FILES:
        src = os.path.join(ROOT, f)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(out_root, f))
            copied += 1
            print("  + %s" % f)

    for d in INCLUDE_DIRS:
        src_dir = os.path.join(ROOT, d)
        if not os.path.isdir(src_dir):
            continue
        dst_dir = os.path.join(out_root, d)
        os.makedirs(dst_dir, exist_ok=True)
        for name in sorted(os.listdir(src_dir)):
            if name in EXCLUDE_NAMES:
                print("  - %s/（维护用，跳过）" % name)
                continue
            s = os.path.join(src_dir, name)
            if os.path.isfile(s):
                shutil.copy2(s, os.path.join(dst_dir, name))
                copied += 1
                print("  + %s/%s" % (d, name))

    # 关键校验：线上版本不能有任何 http(s) 外部引用，否则 file:// 与离线都会退化
    html = open(os.path.join(out_root, "index.html"), encoding="utf-8").read()
    import re
    ext = re.findall(r'(?:src|href)\s*=\s*["\']https?://', html)
    if ext:
        print("\n❌ index.html 中仍存在 %d 处外部引用，请先清理。" % len(ext))
        return 1

    # 关键校验：manifest 里的日期必须都在 dist 里真实存在
    man = open(os.path.join(out_root, "data", "manifest.js"), encoding="utf-8").read()
    m = re.search(r"dates\s*:\s*\[([^\]]*)\]", man)
    dates = re.findall(r"\d{4}-\d{2}-\d{2}", m.group(1)) if m else []
    missing = [d for d in dates if not os.path.exists(os.path.join(out_root, "data", d + ".js"))]
    if missing:
        print("\n❌ manifest 里这些日期缺少对应数据文件：%s" % ", ".join(missing))
        return 1

    total = sum(os.path.getsize(os.path.join(dp, f))
                for dp, _, fs in os.walk(out_root) for f in fs)
    print("\n✅ 打包完成：%s" % os.path.relpath(out_root, ROOT))
    print("   文件 %d 个 · 共 %.1f KB · 含 %d 期数据" % (copied, total / 1024.0, len(dates)))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="打包可发布版本")
    ap.add_argument("--out", default=os.path.join(ROOT, "dist"), help="输出目录")
    args = ap.parse_args()
    return build(args.out)


if __name__ == "__main__":
    sys.exit(main())
