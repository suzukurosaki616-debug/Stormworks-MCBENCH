# -*- coding: utf-8 -*-
"""自己往復テスト。**コアの生命線。**

  python tools/roundtrip.py             保存済みマイコン全部を検査
  python tools/roundtrip.py --dir PATH  対象フォルダを指定
  python tools/roundtrip.py -v          食い違いの中身を出す

XMLが正である以上、**読んで書いて意味が変わらないこと**が全機能の前提になる。
バイト一致は狙わない(ゲームの書き出しは揃っていないので、正規化されて軽くなる)。
代わりに次の2つで判定する。

  A. 意味一致 … 元XMLの木と、書き出したXMLの木が等しい。
                 捨ててよいと合意したもの(WHITELIST)だけは除外して比べる
  B. 不動点   … 書き出したものを読んで書くと、完全に同じものが出る。
                 1回目で正規化が済み、以降は動かない

Aが落ちたら読み違い、Bが落ちたら書き出しが安定していない。
"""
from __future__ import annotations

import argparse
import collections
import glob
import io
import os
import re
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcbench import dumps, loads, preprocess  # noqa: E402

APPMC = os.path.expandvars(r"%APPDATA%\Stormworks\data\microprocessors")

# 落としてよいと合意したもの。**ここに無いものを落としたらバグ。**
#
# ゲームの書き出しは揃っていない。同じ意味を2通りで書くので、比較する前に
# 両側を同じ形に均す。**均すのは「書いても書かなくても同じ」ものだけ。**
PORT = re.compile(r"^(in\d+|out\d+|inc|inoff)$")
# 省略時の既定値と同じなら、書いてあっても無くても同じ
DEFAULTED = {("c", "type"): "0", (None, "node_index"): "0",
             ("pos", "x"): "0", ("pos", "y"): "0"}
# 数値として比べる属性。make_mc.py が書いた古いファイルは "3.00"、
# ゲームは "3" と書く。同じ座標なので差にしない
NUMERIC = {("pos", "x"), ("pos", "y")}
DROP_ATTR = {"v"}          # 入出力端子に残る最後の値のキャッシュ
# 中身が空なら、有る/無いを問わない要素(こちらは常に書き出す)
OPTIONAL_EMPTY = {"components_bridge", "groups", "nodes", "components", "items"}


def canon(e, parent=""):
    """比較用の正規形。属性は辞書、子は順序つき。空白テキストは無視する。"""
    at = {}
    for k, v in e.attrib.items():
        if k in DROP_ATTR:
            continue
        if DEFAULTED.get((e.tag, k)) == v or DEFAULTED.get((None, k)) == v:
            continue
        if (e.tag, k) in NUMERIC:
            try:
                if float(v) == 0.0:
                    continue
                v = "%.6f" % float(v)
            except ValueError:
                pass
        at[k] = v
    kids = []
    for k in e:
        # 端子の中の <v> は実行時の値キャッシュ。<v text= value=> の設定値とは別物
        if k.tag == "v" and PORT.match(e.tag):
            continue
        if k.tag in OPTIONAL_EMPTY and len(k) == 0 and not k.attrib:
            continue
        kids.append(canon(k, e.tag))
    return (e.tag, at, kids)


def diff(a, b, path="", out=None):
    """最初に食い違ったところを返す。"""
    out = out if out is not None else []
    if len(out) >= 3:
        return out
    p = path + "/" + a[0]
    if a[0] != b[0]:
        out.append("%s: タグ %s != %s" % (path, a[0], b[0])); return out
    if a[1] != b[1]:
        ka, kb = a[1], b[1]
        for k in sorted(set(ka) | set(kb)):
            if ka.get(k) != kb.get(k):
                out.append("%s: 属性 %s  元=%r 出力=%r"
                           % (p, k, ka.get(k), kb.get(k)))
    if len(a[2]) != len(b[2]):
        out.append("%s: 子の数 %d != %d  元=%s 出力=%s"
                   % (p, len(a[2]), len(b[2]),
                      [c[0] for c in a[2]][:12], [c[0] for c in b[2]][:12]))
        return out
    for x, y in zip(a[2], b[2]):
        diff(x, y, p, out)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=APPMC)
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()

    files = sorted(p for p in glob.glob(os.path.join(a.dir, "*.xml"))
                   if not os.path.basename(p).startswith("MCBENCH"))
    n_ok = 0
    fail_a, fail_b, fail_read = [], [], []
    stats = collections.Counter()
    for p in files:
        src = io.open(p, encoding="utf-8", errors="replace").read()
        try:
            mc = loads(src)
            out1 = dumps(mc)
        except Exception as e:
            fail_read.append((p, "%s: %s" % (type(e).__name__, e))); continue
        stats["部品"] += len(mc.components)
        stats["bridge"] += len(mc.bridge)
        stats["端子"] += len(mc.terminals)

        try:
            # **両側とも preprocess を通す。** 出力の script は生の改行を含み、
            # 素のパーサに掛けると空白へ潰れて、あるはずの差が出る
            d = diff(canon(ET.fromstring(preprocess(src))),
                     canon(ET.fromstring(preprocess(out1))))
        except Exception as e:
            fail_a.append((p, "比較不能: %s" % e)); continue
        if d:
            fail_a.append((p, d)); continue

        out2 = dumps(loads(out1))
        if out1 != out2:
            fail_b.append((p, "不動点でない"))
            continue
        n_ok += 1

    print("対象 %d ファイル / 合格 %d" % (len(files), n_ok))
    print("  読み込み %d 件 / 部品 %d・bridge %d・端子 %d"
          % (len(files) - len(fail_read), stats["部品"], stats["bridge"], stats["端子"]))
    for title, lst in (("読み込み失敗", fail_read), ("A 意味一致で不一致", fail_a),
                       ("B 不動点でない", fail_b)):
        if not lst:
            continue
        print("\n【%s】%d 件" % (title, len(lst)))
        for p, why in lst[:200 if a.verbose else 10]:
            print("  %s" % os.path.basename(p))
            if a.verbose:
                for line in (why if isinstance(why, list) else [why]):
                    print("      %s" % line)
    return 0 if not (fail_read or fail_a or fail_b) else 1


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
    sys.exit(main())
