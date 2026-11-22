# -*- coding: utf-8 -*-
"""1コマンドで全部確かめる。**配布物が壊れていないかの最終確認はこれ。**

  python tools/selftest.py

**保存済みマイコンのコーパスが無くても通る**ように作ってある(配布先には無いため)。
コーパスがあれば、それを使った検査も追加で走る。
"""
from __future__ import annotations

import glob
import io
import os
import sys
import traceback

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import mccompile  # noqa: E402
from mcbench import bundle, dumps, load, loads, make_mc  # noqa: E402
from mcbench.model import Note  # noqa: E402
from mcbench.validate import validate  # noqa: E402

APPMC = os.path.expandvars(r"%APPDATA%\Stormworks\data\microprocessors")
OUT = os.path.join(HERE, "_selftest")

_fails = []


def check(name, fn):
    try:
        detail = fn()
    except Exception:
        _fails.append(name)
        print("NG   %s" % name)
        for line in traceback.format_exc().rstrip().split("\n")[-3:]:
            print("       %s" % line)
        return
    if detail:
        _fails.append(name)
        print("NG   %-40s %s" % (name, detail))
    else:
        print("ok   %s" % name)


def t_compile():
    """同梱の仕様ファイルが全部通り、生成物の検証が error 0 であること。"""
    os.makedirs(OUT, exist_ok=True)
    specs = sorted(glob.glob(os.path.join(HERE, "spec", "example", "*.mc")))
    if not specs:
        return "spec/example/*.mc が無い"
    bad = []
    for p in specs:
        sp = mccompile.parse_spec(p)
        xml, m = mccompile.compile_spec(sp, make_mc)
        dst = os.path.join(OUT, (sp.out or sp.name) + ".xml")
        io.open(dst, "w", encoding="utf-8", newline="\r\n").write(xml)
        n = sum(1 for i in validate(loads(xml)) if i.level == "error")
        if n:
            bad.append("%s: error %d" % (sp.name, n))
    return "; ".join(bad)


def t_layout():
    """自動配置: 固定・グループの矩形・区分違いの重なり・形の指定・収まらない時の停止。"""
    from mcbench.layout import place
    N = lambda k, x=None, z=None, g=None, s=None: dict(kind=k, x=x, z=z, group=g, shape=s)
    bad = []
    # 4+4 の区分違いグループは 2x2 に重なり、固定ノードは動かない
    nodes = [N("num", g="L") for _ in range(4)] + [N("comp", g="L") for _ in range(4)] + [N("bool", 1, 2)]
    size, pos = place(nodes)
    if pos[8] != (1, 2):
        bad.append("固定ノードが動いた %r" % (pos[8],))
    if pos[:4] != pos[4:8] or sorted(pos[:4]) != sorted(pos[:4]) or len(set(pos[:4])) != 4:
        bad.append("区分違いが重ならない %r" % (pos[:8],))
    xs = {p[0] for p in pos[:4]}; zs = {p[1] for p in pos[:4]}
    if (max(xs) - min(xs), max(zs) - min(zs)) != (1, 1):
        bad.append("2x2 のブロックでない %r" % (pos[:4],))
    # 形の指定
    size, pos = place([N("num", g="L", s=(4, 1)) for _ in range(4)])
    if len({p[1] for p in pos}) != 1:
        bad.append("4x1 指定が守られない %r" % (pos,))
    # size auto: 13 本は面積最小
    size, pos = place([N("comp") for _ in range(13)])
    if size != (5, 3):
        bad.append("面積最小でない %r" % (size,))
    # 入らなければ止まる
    try:
        place([N("num") for _ in range(7)], size=(3, 2))
        bad.append("収まらないのに止まらない")
    except ValueError:
        pass
    return "; ".join(bad)


def t_bake():
    """焼き込み: pn / getNumber / getBool を定数に置き換え、置き換えきれない読み方では止まる。"""
    bad = []
    src = ('a = pn("Gain", 2)\n'
           'b = property.getNumber("Gain")\n'
           'c = property.getBool("Arm")\n'
           '-- "Gain" in a comment is fine\n')
    hits = {}
    out = mccompile.bake_lua(src, {"Gain": "-1.5", "Arm": "true"}, hits)
    if "a = (-1.5)" not in out or "b = (-1.5)" not in out or "c = true" not in out:
        bad.append("置き換え結果が違う: %r" % out)
    if hits != {"Gain": 2, "Arm": 1}:
        bad.append("数え間違い %r" % hits)
    try:
        mccompile.bake_lua('k = "Gain"\nv = property.getNumber(k)\n', {"Gain": "1"}, {})
        bad.append("名前を変数で渡す読み方で止まらない")
    except SystemExit:
        pass
    return "; ".join(bad)


def t_roundtrip_out():
    """生成物を読んで書くと同じものが出る(不動点)。"""
    bad = []
    for p in sorted(glob.glob(os.path.join(OUT, "*.xml"))):
        one = dumps(load(p))
        if one != dumps(loads(one)):
            bad.append(os.path.basename(p))
    return "不動点でない: " + ", ".join(bad) if bad else ""


def t_bundle():
    """バンドルが付箋ごと往復すること。**`[xml]` を含む本文でも壊れないこと。**"""
    xmls = sorted(glob.glob(os.path.join(OUT, "*.xml")))
    if not xmls:
        return "生成物が無い"
    b = bundle.from_xml(io.open(xmls[0], encoding="utf-8").read())
    b.notes.append(Note(id=1, x=1.5, y=-2, w=6, h=3,
                        text="1行目\n[xml] を含む行\n\n空行のあと"))
    b.extra.append(("future thing", ["a: 1"]))
    text = bundle.dumps(b)
    b2 = bundle.loads(text)
    if b2.xml != b.xml:
        return "XML が変わった"
    if len(b2.notes) != 1 or b2.notes[0].text != b.notes[0].text:
        return "付箋が壊れた: %r" % (b2.notes[0].text if b2.notes else None)
    if not b2.extra or b2.extra[0][0] != "future thing":
        return "知らないセクションが落ちた"
    if bundle.dumps(b2) != text:
        return "不動点でない"
    return ""


def t_corpus():
    """コーパスがあれば、読み書きと検証を全数に掛ける(無ければ飛ばす)。"""
    files = [p for p in sorted(glob.glob(os.path.join(APPMC, "*.xml")))
             if not os.path.basename(p).startswith("MCBENCH")]
    if not files:
        print("     (コーパスが無いので飛ばす)")
        return ""
    bad_rt, bad_v = [], []
    for p in files:
        try:
            mc = load(p)
            one = dumps(mc)
            if one != dumps(loads(one)):
                bad_rt.append(os.path.basename(p))
            if any(i.level == "error" for i in validate(mc)):
                bad_v.append(os.path.basename(p))
        except Exception as e:
            bad_rt.append("%s(%s)" % (os.path.basename(p), type(e).__name__))
    msg = []
    if bad_rt:
        msg.append("往復NG %d件: %s" % (len(bad_rt), ", ".join(bad_rt[:3])))
    if bad_v:
        msg.append("検証NG %d件: %s" % (len(bad_v), ", ".join(bad_v[:3])))
    if not msg:
        print("     (コーパス %d 件、往復も検証も通過)" % len(files))
    return " / ".join(msg)


def main():
    print("MCBENCH selftest")
    print("")
    check("ノードの自動配置", t_layout)
    check("プロパティの焼き込み", t_bake)
    check("仕様ファイルの生成と検証", t_compile)
    check("生成物の往復(不動点)", t_roundtrip_out)
    check("バンドルの往復", t_bundle)
    check("保存済みマイコンのコーパス", t_corpus)
    print("")
    if _fails:
        print("失敗 %d 件: %s" % (len(_fails), ", ".join(_fails)))
        return 1
    print("すべて通過")
    return 0


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
    sys.exit(main())
