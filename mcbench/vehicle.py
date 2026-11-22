# -*- coding: utf-8 -*-
"""ビークルのセーブ XML から、置いてあるマイコンのプロパティの値を読む。

**読むだけ。セーブには一切書かない。** 置いたマイコンはライブラリのコピーなので、
ライブラリを作り直すと調整済みの値が既定値に戻る(実機で砲塔の旋回が
1/5 になった、2026-11-02)。ここで拾った値を `mccompile --props-from` が
生成時の既定値として埋め込む。

値は**セーブに書かれた文字列のまま**返す(丸めると 0.54 が 0.5400001 になったりする)。
"""
from __future__ import annotations

import io
from xml.etree import ElementTree as ET

from .mcxml import preprocess

# 部品の type と、値の持ち方。どれも「値が 0 / false のときは書かれない」。
#   33 Property Toggle   : <object n=.. v="true">
#   34 Property Number   : <object n=..><v text=.. value=..>
#   19 Property Slider   : <object name=..><v text=.. value=..>
#   20 Property Dropdown : <object name=.. i=..><items><i l=..><v text=.. value=..>
#                          **選択は i(0始まりの項目番号)だけで決まる。v は無視される**
#                          (2026-11-03 実機。tools/make_dropdown_probe.py。i が無ければ先頭)
PROP_TYPES = ("19", "20", "33", "34")


def _value(c):
    o = c.find("object")
    if o is None:
        return None, None
    ty = c.get("type")
    name = o.get("n") or o.get("name")
    if ty == "33":
        return name, "true" if o.get("v") == "true" else "false"
    if ty == "20":
        # v は生成時の値のまま更新されないので読まない(Gun type を HAC と誤って引き継いだ)
        items = o.find("items")
        vals = [] if items is None else [i.find("v") for i in items.findall("i")]
        k = int(o.get("i", "0"))
        if not 0 <= k < len(vals) or vals[k] is None:
            return name, "0"
        return name, vals[k].get("value") or vals[k].get("text") or "0"
    v = o.find("v")
    if v is None:
        return name, "0"
    return name, v.get("value") or v.get("text") or "0"


def placed_props(path):
    """{マイコン名: [{プロパティ名: 値の文字列}, ...]}。置いてある個数ぶん並ぶ。"""
    text = io.open(path, encoding="utf-8").read()
    root = ET.fromstring(preprocess(text))
    out = {}
    for md in root.iter("microprocessor_definition"):
        props = {}
        for c in md.iter("c"):
            if c.get("type") in PROP_TYPES:
                n, v = _value(c)
                if n:
                    props[n] = v
        out.setdefault(md.get("name", ""), []).append(props)
    return out
