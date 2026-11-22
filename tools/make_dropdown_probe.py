# -*- coding: utf-8 -*-
"""Property Dropdown (type 20) の i / v の意味を確かめる治具(2026-11-03)。

  python tools/make_dropdown_probe.py            プロジェクト内に書き出す
  python tools/make_dropdown_probe.py --install  ゲームのマイコンフォルダにも置く

i は0始まりの項目番号だと実機で確定した(Obj 1872)。残る疑問は2つ:
  * 部品の出力と Lua の property.getNumber が返すのは v か、i が指す項目の値か
  * i が無いとき何が選ばれるか

3個のドロップダウンは、どれも項目 A=10 / B=20 / C=30 で、i と v をわざと食い違わせてある。

  DD1  v=10  i=2    i が効けば C(30)、v が効けば 10
  DD2  v=30  i なし  i の既定が0なら A(10)、v が効けば 30
  DD3  v なし i=1    i が効けば B(20)、v(=0)が効けば 0

ツールチップは各ドロップダウンにつき2つ:
  "DDn out" = 部品の出力をそのまま / "DDn lua" = Lua の property.getNumber("DDn")

見るもの: エディタでの選択表示(置いた直後)と、ビークル上でマイコンにカーソルを当てたときの6つの値。
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

NAME = "MCBENCH Dropdown Probe"
ITEMS = [("A=10", 10), ("B=20", 20), ("C=30", 30)]
CASES = [("DD1", 10, 2), ("DD2", 30, None), ("DD3", None, 1)]

# Game Lua: comments must stay ASCII (the in-game editor cannot handle 2-byte text)
LUA = """-- Dropdown probe: report what property.getNumber returns for each dropdown
function onTick()
\toutput.setNumber(1, property.getNumber("DD1") or -1)
\toutput.setNumber(2, property.getNumber("DD2") or -1)
\toutput.setNumber(3, property.getNumber("DD3") or -1)
end
"""


def dropdown(m, name, v, i):
    attrs = [("name", name)]
    if v is not None:
        attrs.append(("v", "%g" % v))
    if i is not None:
        attrs.append(("i", i))
    out1 = '<out1 v="%g"/>' % v if v is not None else "<out1/>"
    items = "<items>" + "".join('<i l="%s"><v%s/></i>' % (lb, make_mc._num(val))
                                for lb, val in ITEMS) + "</items>"
    return m.comp(20, attrs, ['<pos/>', out1, items])


def tip(m, label, src):
    m.comp(43, [("l", label)], ['<pos/>', '<in1 component_id="%d"/>' % src, "<in2/>"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--install", action="store_true")
    a = ap.parse_args()

    m = make_mc.MC(NAME, "dropdown i/v probe: hover the MC on a vehicle and read the 6 tooltips",
                   1, 1)
    m.icon = make_mc.thumbnail("9902")
    lua = m.comp(56, [("script", make_mc.esc(make_mc.stamp(make_mc.compress(LUA))))],
                 ['<pos/>', "<in1/>", "<out1/>"])
    for k, (name, v, i) in enumerate(CASES, 1):
        tip(m, "%s out" % name, dropdown(m, name, v, i))
        tip(m, "%s lua" % name, m.read_num(lua, k, 0.0, 0.0))
    # one output node so the MC has a terminal; the tooltips are what matter
    m.src[m.node("Lua", "comp", False, 0, 0, "Lua output: num1-3 = getNumber of DD1-3")] = lua
    xml = m.build()

    dst = os.path.join(ROOT, "out", NAME + ".xml")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    io.open(dst, "w", encoding="utf-8", newline="\r\n").write(xml)
    print("-> %s" % dst)
    if a.install:
        gdst = os.path.join(make_mc.DEST, os.path.basename(dst))
        shutil.copy2(dst, gdst)
        print("-> %s" % gdst)


if __name__ == "__main__":
    main()
