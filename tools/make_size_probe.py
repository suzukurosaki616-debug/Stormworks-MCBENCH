# -*- coding: utf-8 -*-
"""マイコンの大きさの上限を確かめる治具(2026-09-28)。

  python tools/make_size_probe.py                 7x7 をプロジェクト内に書き出す
  python tools/make_size_probe.py 7 7 --install   ゲームのマイコンフォルダにも置く

ゲーム内エディタは 6x6 まで(保存済みの最大も 6x6)。XML で書けばそれを超えられるかを見る。
中身は無く、全マスに number 入力ノードを1個ずつ置く。ラベルは座標(x3z5 など)なので、
端子が消えた・ずれたマスがどこかを画面で読み取れる。

見るもの: 読み込めるか / エディタでの見た目の大きさ / 端子が全部出るか / ビークルに置けるか
"""
from __future__ import annotations

import argparse
import io
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from mcbench import make_mc  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("width", type=int, nargs="?", default=7)
    ap.add_argument("length", type=int, nargs="?", default=7)
    ap.add_argument("--install", action="store_true")
    a = ap.parse_args()

    name = "MCBENCH Size %dx%d" % (a.width, a.length)
    m = make_mc.MC(name, "size limit probe: one number input per cell, label = coordinate",
                   a.width, a.length)
    m.icon = make_mc.thumbnail("9902")
    for z in range(a.length):
        for x in range(a.width):
            m.node("x%dz%d" % (x, z), "num", True, x, z)
    xml = m.build()
    print(m.grid())

    dst = os.path.join(ROOT, "out", name + ".xml")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    io.open(dst, "w", encoding="utf-8", newline="\r\n").write(xml)
    print("-> %s" % dst)
    if a.install:
        gdst = os.path.join(make_mc.DEST, os.path.basename(dst))
        shutil.copy2(dst, gdst)
        print("-> %s" % gdst)


if __name__ == "__main__":
    main()
