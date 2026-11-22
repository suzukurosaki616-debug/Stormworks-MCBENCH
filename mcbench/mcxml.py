# -*- coding: utf-8 -*-
"""マイコン .xml の読み書き。

**ゲームのXMLは規格準拠のXMLではない。** そのまま標準パーサに渡すと、117個中30個が
読めず、残りも Lua スクリプトが壊れる。ここで前処理して吸収する。
詳細は下の PRE_*。
"""
from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET

from .model import Component, El, Link, Microprocessor, Port, Pos, Terminal, fmt_num

# 端子として扱うタグ。**明示列挙にする。** 接頭辞で判定すると Property Slider の
# `<int text=".." value=".."/>` を入力端子と誤認する。列挙から漏れたものは El に
# 落ちて素通しされるだけなので、失敗の仕方が安全側。
PORT = re.compile(r"^(in\d+|out\d+|inc|inoff)$")

# --- 前処理1: 実行時の値キャッシュ。捨てる(合意済み) ------------------------
# `<out1><v bools="0" 01="4025" 02=".."/></out1>` の形で composite 32ch分が入る。
# **属性名が数字で始まる**ためXMLとして不正で、標準パーサでは読めない。
# 117個中30個がこれで落ちていた。
PRE_CACHE = re.compile(r'<v(?:\s+(?:\d\w*|bools)="[^"]*")+\s*/>')
# --- 前処理2: 実行時の状態ブロック。捨てる --------------------------------
PRE_STATES = re.compile(
    r"<(component_states|component_bridge_states|group_states)\b[^>]*?(?:/>|>.*?</\1>)",
    re.S)

DROPPED = ("実行時の値キャッシュ <v 01=../bools=..>",
           "実行時の状態 <component_states>/<component_bridge_states>/<group_states>",
           "入出力端子の v= (最後の値のキャッシュ)")


def _encode_attr_newlines(s):
    """属性値の中の生の改行・タブを文字参照に直す。

    **XMLの規格では、属性値の中の改行は読み込み時に空白へ潰される。** ゲームは
    Lua を `script="..."` に生の改行のまま入れているので、素直に標準パーサへ渡すと
    スクリプトが1行に潰れ、`--` コメントが以降を全部飲み込む。読む前に文字参照へ
    直しておくと、正しく改行として復元される。
    """
    out, i, n, q, intag = [], 0, len(s), None, False
    while i < n:
        ch = s[i]
        if q:
            if ch == q:
                q = None
            elif ch == "\n":
                out.append("&#10;"); i += 1; continue
            elif ch == "\r":
                out.append("&#13;"); i += 1; continue
            elif ch == "\t":
                out.append("&#9;"); i += 1; continue
        elif intag and ch in "\"'":
            q = ch
        elif ch == "<":
            intag = True
        elif ch == ">":
            intag = False
        out.append(ch)
        i += 1
    return "".join(out)


def preprocess(text):
    text = PRE_STATES.sub("", text)
    text = PRE_CACHE.sub("", text)
    return _encode_attr_newlines(text)


# ------------------------------------------------------------------ 読み込み
def _el(e):
    return El(e.tag, dict(e.attrib), [_el(k) for k in e])


def _link(e):
    """(結線, component_id="0" が書いてあったか) を返す。"""
    cid = e.get("component_id")
    if cid is None:
        return None, False
    if int(cid) == 0:
        return None, True      # 未接続の番兵
    return Link(int(cid), int(e.get("node_index", 0))), False


def _component(c):
    o = c.find("object")
    if o is None:
        o = ET.Element("object")
    comp = Component(id=int(o.get("id", 0)), type=int(c.get("type", 0)),
                     attrib=dict((k, v) for k, v in o.attrib.items() if k != "id"))
    for k in o:
        if k.tag == "pos":
            comp.children.append(Pos(float(k.get("x", 0)), float(k.get("y", 0))))
        elif PORT.match(k.tag):
            link, null = _link(k)
            comp.children.append(Port(k.tag, link, null))
        else:
            comp.children.append(_el(k))
    return comp


def loads(text):
    root = ET.fromstring(preprocess(text))
    if root.tag != "microprocessor":
        found = root.find(".//microprocessor")
        if found is None:
            raise ValueError("<microprocessor> が見つからない (tag=%s)" % root.tag)
        root = found

    mc = Microprocessor(
        name=root.get("name", ""), description=root.get("description"),
        width=int(root.get("width", 1)), length=int(root.get("length", 1)),
        attrib=dict((k, v) for k, v in root.attrib.items()
                    if k not in ("name", "description", "width", "length")))

    for n in root.findall("./nodes/n"):
        node = n.find("node")
        mc.terminals.append(Terminal(
            id=int(n.get("id", 0)), component_id=int(n.get("component_id", 0)),
            attrib=dict((k, v) for k, v in n.attrib.items()
                        if k not in ("id", "component_id")),
            node=_el(node) if node is not None else None))

    g = root.find("group")
    if g is not None:
        mc.group_attrib = dict(g.attrib)
        d = g.find("data")
        mc.data = _el(d) if d is not None else None
        for k in g:
            if k.tag in ("data", "components", "components_bridge", "groups"):
                continue
            mc.group_extra.append(_el(k))
        for c in g.findall("./components/c"):
            mc.components.append(_component(c))
        for c in g.findall("./components_bridge/c"):
            mc.bridge.append(_component(c))
    return mc


def load(path):
    return loads(io.open(path, encoding="utf-8", errors="replace").read())


# ------------------------------------------------------------------ 書き出し
def esc(v):
    """属性値のエスケープ。**改行はそのまま出す**(ゲームがそう書いているため)。"""
    return (str(v).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _attrs(d):
    return "".join(' %s="%s"' % (k, esc(v)) for k, v in d.items())


def _write_el(out, e, depth):
    t = "\t" * depth
    if e.children:
        out.append("%s<%s%s>" % (t, e.tag, _attrs(e.attrib)))
        for k in e.children:
            _write_el(out, k, depth + 1)
        out.append("%s</%s>" % (t, e.tag))
    else:
        out.append("%s<%s%s/>" % (t, e.tag, _attrs(e.attrib)))


def _write_component(out, c, depth):
    t = "\t" * depth
    ty = ' type="%d"' % c.type if c.type else ""
    out.append("%s<c%s>" % (t, ty))
    out.append('%s\t<object id="%d"%s>' % (t, c.id, _attrs(c.attrib)))
    for k in c.children:
        if isinstance(k, Pos):
            # ゲームは 0 の座標を書かない。同じ形にして無駄な差分を出さない。
            a = ""
            if k.x:
                a += ' x="%s"' % fmt_num(k.x)
            if k.y:
                a += ' y="%s"' % fmt_num(k.y)
            out.append("%s\t\t<pos%s/>" % (t, a))
        elif isinstance(k, Port):
            a = ""
            if k.link:
                a = ' component_id="%d"' % k.link.source
                if k.link.index:
                    a += ' node_index="%d"' % k.link.index
            elif k.null_id:
                a = ' component_id="0"'   # 元が番兵表記だったので再現する
            out.append("%s\t\t<%s%s/>" % (t, k.name, a))
        else:
            _write_el(out, k, depth + 2)
    out.append("%s\t</object>" % t)
    out.append("%s</c>" % t)


def dumps(mc):
    out = ['<?xml version="1.0" encoding="UTF-8"?>']
    head = {"name": mc.name}
    if mc.description is not None:
        head["description"] = mc.description
    head["width"] = str(mc.width)
    head["length"] = str(mc.length)
    head.update(mc.attrib)
    out.append("<microprocessor%s>" % _attrs(head))

    if mc.terminals:
        out.append("\t<nodes>")
        for n in mc.terminals:
            a = {"id": str(n.id), "component_id": str(n.component_id)}
            a.update(n.attrib)
            if n.node is None:
                out.append("\t\t<n%s/>" % _attrs(a))
                continue
            out.append("\t\t<n%s>" % _attrs(a))
            _write_el(out, n.node, 3)
            out.append("\t\t</n>")
        out.append("\t</nodes>")
    else:
        out.append("\t<nodes/>")

    out.append("\t<group%s>" % _attrs(mc.group_attrib))
    # <group> は `pos` を子に持つことがある。data より前に出るので順序を合わせる。
    for e in mc.group_extra:
        _write_el(out, e, 2)
    if mc.data is not None:
        _write_el(out, mc.data, 2)
    for tag, items in (("components", mc.components), ("components_bridge", mc.bridge)):
        if items:
            out.append("\t\t<%s>" % tag)
            for c in items:
                _write_component(out, c, 3)
            out.append("\t\t</%s>" % tag)
        else:
            out.append("\t\t<%s/>" % tag)
    out.append("\t\t<groups/>")
    out.append("\t</group>")
    out.append("</microprocessor>")
    return "\n".join(out) + "\n"


def dump(mc, path):
    io.open(path, "w", encoding="utf-8", newline="\r\n").write(dumps(mc))
