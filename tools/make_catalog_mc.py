# -*- coding: utf-8 -*-
"""部品カタログ確認用のマイコンを、ゼロから生成する。

  python tools/make_catalog_mc.py            プロジェクト内に書き出す
  python tools/make_catalog_mc.py --install  ゲームのマイコンフォルダにも置く
  python tools/make_catalog_mc.py --max 59   出す type 番号の上限(既定 59)

【目的】
  1. type番号 ↔ 部品名 の対応を人間が読み取るための治具。**type番号の昇順**に
     並べるので、ゲーム内で上から読めばそのまま対応表になる
  2. **欠番と推定した type 30 / 32 が本当に存在しないかを確かめる。**
     コーパス540ファイルに一度も現れないが、それは「使われていない」ことしか
     意味しない。実際に置いて開けば、存在するのかしないのかが分かる
  3. **こちらのXML生成が正しいかの検証。** ゲームが書いたブロックを流用せず、
     全部こちらで組む。読み込めなければ、こちらの生成が間違っている

【属性の埋め方】部品によっては属性が無いと壊れうる(type 10 の `e` など)。
コーパスから **type ごとに最も多く使われている属性値** を拾って埋める。
実データに存在する組み合わせなので、ゲームが受け付けないことは考えにくい。
"""
from __future__ import annotations

import argparse
import collections
import glob
import io
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
APPDATA = os.path.expandvars(r"%APPDATA%\Stormworks\data")
APPMC = os.path.join(APPDATA, "microprocessors")
NAME = "MCBENCH Catalog"
OUT = os.path.join(ROOT, "out", NAME + ".xml")

PER_COL = 15
DY = 1.25
DX = 3.0
TOP = 9.0
FIRST_ID = 20

OBJ = re.compile(r'<c(?:\s+type="(\d+)")?>\s*<object([^>]*)>(.*?)</object>', re.S)


def scan_corpus():
    """type -> (子要素の集合, 属性名 -> 最頻値)"""
    kids = collections.defaultdict(set)
    vals = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
    files = (glob.glob(os.path.join(APPDATA, "microprocessors", "*.xml"))
             + glob.glob(os.path.join(APPDATA, "vehicles", "*.xml")))
    for p in files:
        try:
            s = io.open(p, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for m in OBJ.finditer(s):
            t = int(m.group(1) or 0)
            for a, v in re.findall(r'(\w+)="([^"]*)"', m.group(2)):
                if a != "id":
                    vals[t][a][v] += 1
            for k in re.findall(r"<(in\d+|out\d+|min|max|items)\b", m.group(3)):
                kids[t].add(k)
    modal = {t: {a: c.most_common(1)[0][0] for a, c in d.items()} for t, d in vals.items()}
    return kids, modal, len(files)


def esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;"))


def component(t, cid, x, y, kids, modal):
    """1部品ぶんの <c> を組み立てる。"""
    attrs = "".join(' %s="%s"' % (a, esc(v)) for a, v in sorted(modal.get(t, {}).items()))
    ins = sorted((k for k in kids.get(t, ()) if k.startswith("in")),
                 key=lambda k: int(k[2:]))
    outs = sorted((k for k in kids.get(t, ()) if k.startswith("out")),
                  key=lambda k: int(k[3:]))
    body = ['\t\t\t\t\t<pos x="%g" y="%g"/>' % (x, y)]
    for k in ins:
        body.append("\t\t\t\t\t<%s/>" % k)
    for k in outs:
        body.append("\t\t\t\t\t<%s/>" % k)
    for k in ("min", "max"):
        if k in kids.get(t, ()):
            body.append('\t\t\t\t\t<%s text="0"/>' % k)
    if "items" in kids.get(t, ()):
        body.append("\t\t\t\t\t<items/>")
    ty = ' type="%d"' % t if t != 0 else ""
    return ("\t\t\t<c%s>\n\t\t\t\t<object id=\"%d\"%s>\n%s\n\t\t\t\t</object>\n\t\t\t</c>"
            % (ty, cid, attrs, "\n".join(body)))


def build(maxtype):
    kids, modal, nfiles = scan_corpus()
    parts, legend, blind = [], [], []
    for i, t in enumerate(range(0, maxtype + 1)):
        col, row = divmod(i, PER_COL)
        x = -6.0 + col * DX
        y = TOP - row * DY
        parts.append(component(t, FIRST_ID + i, x, y, kids, modal))
        legend.append((col + 1, row + 1, t))
        if t not in kids:
            blind.append(t)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<microprocessor name="%s" description="Catalog. Read top to bottom, '
        'left to right. Type numbers ascend." width="1" length="1" '
        'id_counter="%d" id_counter_node="1">\n'
        "\t<nodes/>\n"
        "\t<group>\n\t\t<data>\n\t\t\t<inputs/>\n\t\t\t<outputs/>\n\t\t</data>\n"
        "\t\t<components>\n%s\n\t\t</components>\n\t</group>\n</microprocessor>\n"
        % (NAME, FIRST_ID + maxtype + 10, "\n".join(parts))
    )
    return xml, legend, blind, nfiles


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--install", action="store_true",
                    help="ゲームのマイコンフォルダにもコピーする")
    ap.add_argument("--max", type=int, default=59, help="出す type 番号の上限")
    a = ap.parse_args()

    xml, legend, blind, nfiles = build(a.max)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    io.open(OUT, "w", encoding="utf-8", newline="\r\n").write(xml)
    print("コーパス %d ファイルから属性を採取" % nfiles)
    print("書き出し: %s  (type 0〜%d の %d 部品)" % (OUT, a.max, len(legend)))
    if blind:
        print("【注目】コーパスに実例が無く、子要素・属性を空で出した type: %s"
              % ", ".join(str(t) for t in blind))
        print("        → ゲーム内でこれらが何になるか(あるいは消えるか)が見どころ")

    if a.install:
        dst = os.path.join(APPMC, NAME + ".xml")
        if os.path.exists(dst):
            shutil.copy2(dst, dst + ".bak")
            print("既存を退避: %s.bak" % dst)
        shutil.copy2(OUT, dst)
        print("配置: %s" % dst)

    print("")
    print("読み取り順(列ごとに上から下へ):")
    for col in range(1, (len(legend) + PER_COL - 1) // PER_COL + 1):
        ts = [t for c, r, t in legend if c == col]
        print("  %d列目: type %s" % (col, ", ".join(str(t) for t in ts)))
    return 0


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
    sys.exit(main())
