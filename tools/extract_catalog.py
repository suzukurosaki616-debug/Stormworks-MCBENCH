# -*- coding: utf-8 -*-
"""マイコン内部部品のカタログを、実データから再生成する。

  python tools/extract_catalog.py            data/component_catalog.csv を書き出す
  python tools/extract_catalog.py --check     既存CSVとの差分だけ表示する

【なぜスクリプトにするか】この表を手で書き写すと必ず間違える。ゲームが更新されて
部品が増えたときも、走らせ直せば追随できる。**表そのものではなく、表の作り方を残す。**

【データ源】
  1. `<Stormworks>/rom/graphics/ui/microprocessors/component_icons/atlas_logic.xml`
     … `mp_*` の内部名(46件)。ただし新しい部品は載っていない
  2. `stormworks64.exe` … 部品の表示名と説明文。**マイコン部品名の唯一の一次資料**
  3. `%APPDATA%/Stormworks/data/{microprocessors,vehicles}/*.xml`
     … 実データのコーパス。**type番号ごとのノード構成と属性**を実測する
  4. `%APPDATA%/Stormworks/data/microprocessors/Test.xml`
     … ユーザーが全58部品を1個ずつ並べたもの。**配置順が手がかり**
  5. `%APPDATA%/Stormworks/data/languages/jp.tsv`
     … 【注意】`def_gate_*` は **ビークル設置用ロジック部品**であって、
       マイコン内部部品ではない。名前が一部重なるので混ぜてはいけない。
       ここで一度取り違えて、対応表を丸ごと間違えた。

【確定していないこと】type番号 ↔ 表示名 の対応。属性が決定的な28件は確定、
2入力1出力の一群(And/Or/Add/Subtract/... 全部同じ形)は形から区別できない。
`data/component_catalog.csv` の name 列を人間が埋めて確定させる運用。
"""
from __future__ import annotations

import argparse
import collections
import csv
import glob
import io
import os
import re
import string
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "data", "component_catalog.csv")

GAME = r"C:\Program Files (x86)\Steam\steamapps\common\Stormworks"
APPDATA = os.path.expandvars(r"%APPDATA%\Stormworks\data")


# ---------------------------------------------------------------- コーパス
def scan_corpus():
    """type番号ごとの (入力ノード数, 出力ノード数, 追加要素, 属性, 出現回数)

    【罠1】`<object id="92"/>` のように **自己閉じの object がある**。`</object>` を
    前提に非貪欲マッチすると、そこから先のファイル全体を1個の部品として飲み込み、
    無関係なタグが `in3` などとして混入する。実際これで type 4 を3入力と誤認した。

    【罠2】**自分が生成した MCBENCH 系のファイルをコーパスに入れてはいけない。**
    ゲームのマイコンフォルダに置いてあるので、除外しないと自分の誤りを再入力する。

    【罠3】**未接続の `<inN/>` / `<outN/>` は保存されない。** 入出力数は最頻値では
    なく **コーパス全体での最大** を採ること。type 30/32 が `(0,0)` に見えるのも同じ理由。
    """
    shape = collections.defaultdict(collections.Counter)
    arity = collections.defaultdict(lambda: {"in": 0, "out": 0})
    attrs = collections.defaultdict(collections.Counter)
    count = collections.Counter()
    files = [p for p in (glob.glob(os.path.join(APPDATA, "microprocessors", "*.xml"))
                         + glob.glob(os.path.join(APPDATA, "vehicles", "*.xml")))
             if not os.path.basename(p).startswith("MCBENCH")]
    pat = re.compile(r'<c(?:\s+type="(\d+)")?>\s*<object([^>]*?)(?:/>|>(.*?)</object>)', re.S)
    for p in files:
        try:
            s = io.open(p, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for m in pat.finditer(s):
            t = int(m.group(1) or 0)
            count[t] += 1
            for a in re.findall(r'(\w+)="', m.group(2)):
                if a != "id":
                    attrs[t][a] += 1
            body = m.group(3) or ""
            for n in re.findall(r"<(min|max|items)\b", body):
                shape[t][n] += 1
            # 【罠4】古い保存形式は 2本目の出力を `<out2/>` ではなく **`<out1/>` を
            # 2回** 書くことがある(Boiler Remote Controller.xml)。添字の最大だけ見ると
            # 取りこぼすので、添字と出現本数の両方の最大を採る。
            for kind in ("in", "out"):
                ns = [int(x) for x in re.findall(r"<%s(\d+)\b" % kind, body)]
                if ns:
                    arity[t][kind] = max(arity[t][kind], max(ns), len(ns))
    return shape, attrs, count, len(files), arity


def placement_order(path):
    """Test.xml の配置順。左列を上から、次に右列を上から。

    pos の y は上が正。x でまず列に分け、列ごとに y の降順で読む。
    """
    s = io.open(path, encoding="utf-8", errors="replace").read()
    items = []
    pat = re.compile(r'<c(?:\s+type="(\d+)")?>\s*<object([^>]*)>(.*?)</object>', re.S)
    for m in pat.finditer(s):
        t = int(m.group(1) or 0)
        pos = re.search(r"<pos([^/]*)/>", m.group(3))
        x = y = 0.0
        if pos:
            mx = re.search(r'x="(-?[\d.]+)"', pos.group(1))
            my = re.search(r'y="(-?[\d.]+)"', pos.group(1))
            x = float(mx.group(1)) if mx else 0.0
            y = float(my.group(1)) if my else 0.0
        items.append((round(x, 1), -y, t))
    items.sort()
    out, col, n = [], None, 0
    for x, ny, t in items:
        if col != x:
            col = x
            n = 0
        n += 1
        out.append(("L" if x < 0 else "R", n, t))
    return out


# ---------------------------------------------------------------- exe / atlas
def icon_names():
    p = os.path.join(GAME, "rom", "graphics", "ui", "microprocessors",
                     "component_icons", "atlas_logic.xml")
    if not os.path.exists(p):
        return []
    s = io.open(p, encoding="utf-8", errors="replace").read()
    return re.findall(r'region name="(mp_[a-z0-9_]+)"', s)


def exe_display_names():
    """exe内の、部品表示名らしき短い文字列。説明文の近傍にあるものを拾う。

    文字列プールは並びが保証されないので、**候補集合として**しか使えない。
    type番号との対応はここからは決まらない。
    """
    p = os.path.join(GAME, "stormworks64.exe")
    if not os.path.exists(p):
        return []
    d = io.open(p, "rb").read()
    lo, hi = 0xB63000, 0xB68000
    ss = [m.group(0).decode() for m in re.finditer(rb"[ -~]{3,}", d[lo:hi])]

    def isname(s):
        return (3 <= len(s) <= 30 and not s.endswith(".") and s[0].isupper()
                and all(c in string.ascii_letters + " /()-+" for c in s))

    return sorted({s for s in ss if isname(s)})


# 属性やノード構成から確実に決まるもの。ここに書いてあるものは根拠つきで確定。
# 根拠を必ず添えること。根拠の無い断定を混ぜると表全体が信用できなくなる。
# 【一次資料】2026-08-30、ユーザーがゲーム内エディタで「MCBENCH Catalog」
# (type昇順 15段x4列) を上から読み上げたもの。**60件すべてこれで確定。**
# 属性・ノード構成から独立に確定していた26件と一つも矛盾しなかったので、
# 読み上げ全体の整合が取れている。
READOUT = "ゲーム内エディタの読み上げ (2026-08-30)"
CONFIRMED = {
    0:  ("Not", READOUT),
    1:  ("And", READOUT),
    2:  ("Or", READOUT),
    3:  ("Xor", READOUT),
    4:  ("Nand", READOUT),
    5:  ("Nor", READOUT),
    6:  ("Add", READOUT),
    7:  ("Subtract", READOUT),
    8:  ("Multiply", READOUT),
    9:  ("Divide", READOUT + " / 実データに in1=1800, in2=60, out1=30。out2 はゼロ除算フラグらしく in2=0 の実例で true"),
    10: ("Function (3 inputs)", READOUT + " / e,p1,p2,p3 属性、3入力"),
    11: ("Clamp", READOUT + " / min,max を持つ 1入力1出力"),
    12: ("Threshold", READOUT + " / min,max を持つ 1入力1出力。Clamp と対"),
    13: ("Memory Register", READOUT + " / memory 属性"),
    14: ("Abs", READOUT),
    15: ("Constant Number", READOUT),
    16: ("Constant On Signal", READOUT),
    17: ("Greater Than", READOUT),
    18: ("Less Than", READOUT),
    19: ("Property Slider", READOUT + " / min,max + name 属性"),
    20: ("Property Dropdown", READOUT + " / items + name 属性"),
    21: ("Numerical Junction", READOUT + " / 2入力2出力(古い保存は out1 を2回書く)"),
    22: ("Numerical Switchbox", READOUT + " / 3入力1出力"),
    23: ("PID Controller", READOUT + " / pe,pes,te 属性、3入力"),
    24: ("SR Latch", READOUT + " / 2入力2出力"),
    25: ("JK Flip Flop", READOUT + " / 2入力2出力"),
    26: ("Capacitor", READOUT + " / ct,dt = 充電時間/放電時間"),
    27: ("Blinker", READOUT + " / on,off = 点灯/消灯の秒数"),
    28: ("Push To Toggle", READOUT),
    29: ("Composite Read (on/off)", READOUT + " / make_mc.py が実機で確認済み"),
    30: ("Composite Write (on/off) [1ch・旧式]", READOUT
         + " / 29と対の旧式。1chしか書けないためエディタ上は使わない"),
    31: ("Composite Read (number)", READOUT + " / make_mc.py が実機で確認済み"),
    32: ("Composite Write (number) [1ch・旧式]", READOUT
         + " / 31と対の旧式。1chしか書けないためエディタ上は使わない"),
    33: ("Property Toggle", READOUT + " / n,on,off 属性"),
    34: ("Property Number", READOUT + " / n 属性"),
    35: ("Delta", READOUT + " / vp=前tick値, ip=初回パスか。実例が Delta.xml"),
    36: ("Function (8 inputs)", READOUT + " / e 属性、8入力"),
    37: ("Up/Down Counter", READOUT + " / min,max + is,m 属性"),
    38: ("Modulo (fmod)", READOUT),
    39: ("PID Controller (Advanced)", READOUT + " / 6入力=ゲイン3本がノード化"),
    40: ("Composite Write (number) [32ch]", READOUT + " / count,offset 属性。inc=ベースcomposite入力, inoff=動的オフセット, in1..inN=書き込む値"),
    41: ("Composite Write (on/off) [32ch]", READOUT + " / count,offset 属性。inc/inoff/in1..inN は 40 と同じ"),
    42: ("Equal", READOUT),
    43: ("Tooltip Number", READOUT + " / l,m 属性、2入力0出力"),
    44: ("Tooltip On/Off", READOUT + " / l,m,on,off 属性、1入力0出力"),
    45: ("Function (1 input)", READOUT + " / e 属性、1入力"),
    46: ("Logic Function (4 inputs)", READOUT + " / e 属性、4入力"),
    47: ("Logic Function (8 inputs)", READOUT + " / e 属性、8入力"),
    48: ("Pulse (Toggle to Push)", READOUT + " / m,p 属性"),
    49: ("Timer (TON)", READOUT + " / t,u 属性"),
    50: ("Timer (TOF)", READOUT + " / u 属性"),
    51: ("Timer (RTO)", READOUT + " / 51と52はどちらも rto と読まれたが、ID順から 51=RTO / 52=RTF とユーザーが確定"),
    52: ("Timer (RTF)", READOUT + " / 同上。3入力1出力、属性 u"),
    53: ("Composite Switchbox", READOUT
         + " / 入出力が子要素<v/>を持つ非スカラー型。供給元が Composite Write(40/41)"),
    54: ("Number To Composite Binary", READOUT),
    55: ("Composite Binary To Number", READOUT),
    56: ("Lua Script", READOUT + " / script 属性。out2は映像出力"),
    57: ("Video Switchbox", READOUT
         + " / データ入力の供給元が Lua Script の node_index=1(映像出力)のみ"),
    58: ("Property Text", READOUT + " / n,v 属性でノード0本"),
    59: ("Audio Switchbox", READOUT),
}

GUESS = {}


def build():
    shape, attrs, count, nfiles, arity = scan_corpus()
    # Test.xml の配置順ではなく、type 番号の総当たりにする。
    # Test.xml には「エディタに出ない部品」(30/32)が入らないため、順序を基準にすると
    # 取りこぼす。実際それで 30/32 を欠番と誤認した。
    rows = []
    for t in sorted(set(list(shape) + list(arity) + list(CONFIRMED) + list(GUESS) + list(range(60)))):
        extra = ",".join(sorted(v for v in shape[t] if v in ("min", "max", "items")))
        name, why = CONFIRMED.get(t, (GUESS.get(t, ""), ""))
        rows.append({
            "slot": "type%d" % t,
            "type": t,
            "name": name,
            "confidence": "confirmed" if t in CONFIRMED else ("guess" if name else "unknown"),
            "basis": why,
            "inputs": arity[t]["in"],
            "outputs": arity[t]["out"],
            "extra_nodes": extra,
            "attrs": ",".join(sorted(attrs[t])),
            "corpus_count": count[t],
        })
    return rows, nfiles


FIELDS = ["slot", "type", "name", "confidence", "basis", "inputs", "outputs",
          "extra_nodes", "attrs", "corpus_count"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="書き出さず、既存CSVとの差分だけ表示する")
    a = ap.parse_args()

    rows, nfiles = build()
    print("コーパス %d ファイルを走査 / 部品 %d 件" % (nfiles, len(rows)))
    n_ok = sum(1 for r in rows if r["confidence"] == "confirmed")
    n_g = sum(1 for r in rows if r["confidence"] == "guess")
    n_u = sum(1 for r in rows if r["confidence"] == "unknown")
    print("  確定 %d / 推定 %d / 不明 %d" % (n_ok, n_g, n_u))
    print("  アイコン内部名: %d 件 / exe内の表示名候補: %d 件"
          % (len(icon_names()), len(exe_display_names())))

    if a.check:
        if not os.path.exists(OUT):
            print("既存CSVが無い")
            return 1
        old = {r["slot"]: r for r in csv.DictReader(io.open(OUT, encoding="utf-8-sig"))}
        diff = 0
        for r in rows:
            o = old.get(r["slot"])
            if o and o.get("name", "") != r["name"]:
                print("  差分 %s: CSV=%r スクリプト=%r" % (r["slot"], o.get("name"), r["name"]))
                diff += 1
        print("差分 %d 件" % diff)
        return 0

    with io.open(OUT, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print("書き出し: %s" % OUT)
    print("")
    print("【運用】name 列の confidence が guess / unknown の行を人間が確認して直すこと。")
    print("      直したら confidence を confirmed に、basis に根拠を書く。")
    return 0


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
    sys.exit(main())
