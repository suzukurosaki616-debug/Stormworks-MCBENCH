# -*- coding: utf-8 -*-
"""データ処理用マイコンのコンパイラ。仕様ファイル + .lua -> マイコン .xml

  python mccompile.py spec/example/averager.mc
  python mccompile.py spec/example/averager.mc --install
  python mccompile.py spec/*.mc --check

【なぜ仕様ファイルか】
マイコンを Python で組み立てると、ノードの並び・型・ラベル・結線を全部コードで書く
ことになり、**新しいマイコンを足すたびにコードが増える**。
このツールは、その部分を**テキストの仕様ファイル**に置き換える。ブロックを足す作業が
「仕様ファイルを1枚書く」だけになり、diffが取れてレビューできる。

【エンジンは同梱】XMLの組み立て・Lua圧縮・ASCII検査・チャンネル範囲検査は
`mcbench/make_mc.py` が持つ。
ここが持つのは「仕様ファイルを読んで MC クラスを呼ぶ」ところだけ。

  仕様ファイル(.mc) ──> [このツール] ──> make_mc.MC ──> .xml
"""
from __future__ import annotations

import argparse
import copy
import glob
import importlib.util
import io
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
APPMC = os.path.expandvars(r"%APPDATA%\Stormworks\data\microprocessors")

KINDS = ("comp", "num", "bool", "vid")


# ---------------------------------------------------------------- エンジン
def load_engine(path=None):
    """組み立てエンジンを返す。既定は同梱の `mcbench/make_mc.py`。

    `--engine` を指定したときだけ、その場所のファイルを動的に読み込む。
    別のエンジンと突き合わせたいとき用の逃げ道。
    """
    if not path:
        from mcbench import make_mc
        return make_mc
    if not os.path.exists(path):
        raise SystemExit("make_mc.py が見つかりません: %s" % path)
    spec = importlib.util.spec_from_file_location("_mcbench_engine", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for need in ("MC", "compress", "esc", "stamp"):
        if not hasattr(mod, need):
            raise SystemExit("%s に %s がありません" % (path, need))
    return mod


def parse_span(tok, what, die):
    """`5` か `1-6` を (lo, hi) にする。"""
    if "-" in tok[1:]:
        a, _, b = tok.partition("-")
        try:
            lo, hi = int(a), int(b)
        except ValueError:
            die("%s の ch 範囲が読めません: %r" % (what, tok))
    else:
        try:
            lo = hi = int(tok)
        except ValueError:
            die("%s の ch 範囲が読めません: %r" % (what, tok))
    if not (1 <= lo <= hi <= 32):
        die("%s の ch は 1〜32 の範囲で、昇順に書いてください: %r" % (what, tok))
    return lo, hi


# ---------------------------------------------------------------- 仕様ファイル
class Spec(object):
    """.mc ファイルの中身。

    name  <マイコン名>
    desc  <説明>
    size  <幅> <奥行>          ボクセル数。ノードはこの範囲にしか置けない
    lua   <.luaへの相対パス>
    out   <出力ファイル名>      省略時は name

    io 行:
      in   comp  <x> <z>  <ラベル>  [| 説明]
      in   num   <x> <z>  <ラベル>  [| 説明]
      out  num   <x> <z>  <ラベル>  ch=<n>  [| 説明]

    コンバイナー(複数の composite 入力を1本に合流させる):
      in   comp  <x> <z>  <ラベル>  role=base  土台にする composite。1本だけ
      map  num   <ラベル> <ch範囲> -> <ch範囲>  [delay=<n>]
      map  bool  <ラベル> <ch範囲> -> <ch範囲>  [delay=<n>]

    * `in comp` は Lua の composite 入力になる
    * `in num` / `in bool` は composite へ詰めてから Lua に渡す
      (`in comp` があればそれを土台にする)
    * `out comp` は Lua の composite 出力を直結する
    * `out num` / `out bool` は `ch=` で指定した ch を取り出す
    """

    def __init__(self):
        self.name = None
        self.desc = ""
        self.size = (1, 1)     # None = size auto(parse_spec の最後で決まる)
        self.size_w = None     # size auto w=<幅>
        self.size_max = 6      # size auto max=<一辺> 既定はエディタの上限
        self.lua = None        # 後方互換: 単一 lua のときのパス
        self.luas = []         # [(名前, パス, base名 or None)] 宣言順
        self.vidfrom = {}      # {lua名: 映像入力の供給元 lua名}(lua 行の vid=)
        self.out = None
        self.ios = []          # (is_in, kind, x, z, label, desc, ch, opts)
        self.maps = []         # (対象, kind, 元トークン列, dst_lo, n, delay)
        self.props = []        # true で生成する bool プロパティ名
        self.sliders = {}      # slider 行: {プロパティ名: (最小, 最大, 刻み)}
        self.dropdowns = {}    # dropdown 行: {プロパティ名: [(ラベル, 値)]} 書いた順
        self.fixes = []        # (トークン列) fix 行。--bake のときだけ効く
        self.parts = []        # (名前, type, [(属性, 値)]) part 行
        self.wires = []        # (部品名, 端子, "num"|"bool"|None, 供給元トークン列) wire 行
        self.tips = []         # ("num"|"bool", 供給元トークン列, 見出し, on, off) tip 行
        self.bake = False      # main が --bake で立てる
        self.icon = None       # (番号, 英字 or None) サムネイル
        self.switches = []     # (名前, on名, off名, sel トークン列, "comp"|"vid")
        self.path = None

    @property
    def inputs(self):
        return [i for i in self.ios if i[0]]

    @property
    def outputs(self):
        return [i for i in self.ios if not i[0]]


def parse_spec(path):
    sp = Spec()
    sp.path = path
    base = os.path.dirname(os.path.abspath(path))
    for lineno, raw in enumerate(io.open(path, encoding="utf-8"), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        head, _, rest = line.partition(" ")
        head = head.lower()
        rest = rest.strip()

        def die(msg):
            raise SystemExit("%s:%d: %s\n  > %s" % (path, lineno, msg, raw.rstrip()))

        if head == "name":
            sp.name = rest
        elif head == "desc":
            sp.desc = rest
        elif head == "switch":
            # switch <名前> on=<comp> off=<comp> sel=<bool 供給元...>
            # Composite Switchbox (type 53)。sel が on のとき on=、off のとき off= を通す。
            # sel= は map の供給元と同じ書き方で、空白を含みうるので行末まで食う。
            t = rest.split()
            # switch vid <名前> ... で Video Switchbox (type 57)。省略時は composite
            skind = "comp"
            if t and t[0].lower() in ("comp", "vid"):
                skind = t.pop(0).lower()
            if not t or "=" in t[0]:
                die("switch は「switch [vid] <名前> on=<供給元> off=<供給元> sel=<bool>」の形です")
            kv, sel = {}, None
            for k2, tok in enumerate(t[1:], 1):
                key, _, val = tok.partition("=")
                if key.lower() == "sel":
                    sel = ([val] if val else []) + t[k2 + 1:]
                    break
                if key.lower() not in ("on", "off") or not val:
                    die("switch に書けるのは on= off= sel= です")
                kv[key.lower()] = val
            if "on" not in kv or "off" not in kv or not sel:
                die("switch には on= off= sel= が全部要ります")
            sp.switches.append((t[0], kv["on"], kv["off"], sel, skind))
        elif head == "part":
            # part <名前> type=<N> [<属性>=<値> ...] — カタログの部品をそのまま置く
            t = rest.split()
            if len(t) < 2 or "=" in t[0]:
                die("part は「part <名前> type=<番号> [<属性>=<値> ...]」の形です")
            ptype, attrs = None, []
            for tok in t[1:]:
                key, eq, val = tok.partition("=")
                if not eq or not key:
                    die("part の %r は <属性>=<値> の形ではありません" % tok)
                if key.lower() == "type":
                    if not val.isdigit():
                        die("type= には部品の番号を書いてください")
                    ptype = int(val)
                else:
                    attrs.append((key, val))
            if ptype is None:
                die("part に type= がありません")
            sp.parts.append((t[0], ptype, attrs))
        elif head == "wire":
            # wire <部品名> <端子> [num|bool] <供給元...>
            # num/bool は composite の ch から読むときだけ要る(カタログに端子の型が無いため)
            t = rest.split()
            if len(t) < 3:
                die("wire は「wire <部品名> <端子> [num|bool] <供給元>」の形です")
            if not re.fullmatch(r"[a-z]+\d*", t[1]):
                die("端子名は in1 / in2 / inc / inoff のような形です (%r)" % t[1])
            kind = t[2].lower() if t[2].lower() in ("num", "bool") else None
            src = t[3:] if kind else t[2:]
            if not src:
                die("wire に供給元がありません")
            sp.wires.append((t[0], t[1], kind, src))
        elif head == "tip":
            # tip num|bool <供給元...> [on=<文字> off=<文字>] | <見出し>
            # Tooltip Number (43) / On/Off (44)。ビークル上でカーソルを当てると値が見える
            body, _, label = rest.partition("|")
            t = body.split()
            if not t or t[0].lower() not in ("num", "bool"):
                die("tip は「tip num|bool <供給元> | <見出し>」の形です")
            kind, on, off, src = t[0].lower(), "on", "off", []
            for tok in t[1:]:
                if tok.lower().startswith("on="):
                    on = tok[3:]
                elif tok.lower().startswith("off="):
                    off = tok[4:]
                else:
                    src.append(tok)
            if kind == "num" and ("on=" in body or "off=" in body):
                die("on= / off= は tip bool にだけ書けます")
            if not src or not label.strip():
                die("tip に供給元か見出しがありません")
            sp.tips.append((kind, src, label.strip(), on, off))
        elif head == "fix":
            # fix <プロパティ名> [<値>] — 配布版で定数に焼く(--bake のときだけ)。
            # 行末の1語が値か名前の一部かは、Lua が読む名前を見てから決める(bake_lua)
            if not rest:
                die("fix は「fix <プロパティ名> [<値>]」の形です")
            sp.fixes.append(rest.split())
        elif head == "icon":
            # icon <番号> [英字] — サムネイル。渡されたものをそのまま描く
            t = rest.split()
            if not 1 <= len(t) <= 2:
                die("icon は「icon <番号> [英字]」の形で書いてください (例: icon 9902 A)")
            sp.icon = (t[0], t[1] if len(t) > 1 else None)
        elif head == "out" and not rest.split()[0].lower() in KINDS:
            sp.out = rest
        elif head == "size":
            t = rest.split()
            if t and t[0].lower() == "auto":
                # size auto [w=<幅>] — 面積最小(同面積なら正方形寄り)/ 幅固定で奥行き最小
                sp.size = None
                for tok in t[1:]:
                    if tok.lower().startswith("w=") and tok[2:].isdigit():
                        sp.size_w = int(tok[2:])
                    elif tok.lower().startswith("max=") and tok[4:].isdigit():
                        # 6 を超えるとエディタで開いて保存した時点で 6x6 に戻る(§3.9)
                        sp.size_max = int(tok[4:])
                    else:
                        die("size auto に書けるのは w=<幅> と max=<一辺> だけです")
            else:
                try:
                    w, l = t
                    sp.size = (int(w), int(l))
                except ValueError:
                    die("size は「size <幅> <奥行>」か「size auto [w=<幅>]」です")
        elif head == "lua":
            # lua [name=<名前>] [base=<供給元>] [vid=<映像の供給元lua>] <パス>
            # パスに空白が入りうる(例: ../My Project/X.lua)ので、
            # 先頭の key=value だけ options として食い、残り全部をパスにする。
            toks = rest.split()
            lname = lbase = lvid = None
            k = 0
            while k < len(toks) and "=" in toks[k].split("/")[0]:
                key, _, val = toks[k].partition("=")
                key = key.lower()
                if key == "name":
                    lname = val
                elif key == "base":
                    lbase = val
                elif key == "vid":
                    lvid = val
                else:
                    die("lua 行に書けるのは name= と base= と vid= だけです")
                k += 1
            lrel = " ".join(toks[k:])
            if not lrel:
                die("lua 行に .lua のパスがありません")
            full = os.path.join(base, lrel)
            if lname is None:
                lname = os.path.splitext(os.path.basename(lrel))[0]
            if any(n == lname for n, _, _ in sp.luas):
                die("lua の名前 %r が重複しています。name= で分けてください" % lname)
            sp.luas.append((lname, full, lbase))
            if lvid:
                sp.vidfrom[lname] = lvid
            sp.lua = full
        elif head in ("in", "out"):
            body, _, desc = rest.partition("|")
            parts = body.split()
            if len(parts) < 2:
                die("io 行は「%s <kind> [<x> <z>] <ラベル>」の形で書いてください" % head)
            kind = parts[0].lower()
            if kind not in KINDS:
                die("kind は %s のどれかです" % "/".join(KINDS))
            # x z は省略可(自動配置)。整数が2つ続くときだけ座標とみなす
            if len(parts) >= 4 and parts[1].isdigit() and parts[2].isdigit():
                x, z = int(parts[1]), int(parts[2])
                rest_toks = parts[3:]
            elif parts[1].isdigit():
                die("x と z は両方書くか、両方省くかです")
            else:
                x = z = None
                rest_toks = parts[1:]
            ch = None
            opts = {}
            label_parts = []
            for tok in rest_toks:
                if tok.lower().startswith("ch="):
                    try:
                        ch = int(tok[3:])
                    except ValueError:
                        die("ch= には整数を書いてください")
                elif tok.lower().startswith("role="):
                    role = tok[5:].lower()
                    if role != "base":
                        die("role= に書けるのは base だけです")
                    opts["base"] = True
                elif tok.lower().startswith("from="):
                    opts["from"] = tok[5:]
                elif tok.lower().startswith("to="):
                    # in vid ... to=<lua>: which Lua block's video input (in2) it feeds
                    opts["to"] = tok[3:]
                elif tok.lower().startswith("group="):
                    # group=<名前>[:<W>x<H>] — 矩形ブロックにまとめて自動配置
                    g, _, shp = tok[6:].partition(":")
                    if not g:
                        die("group= に名前がありません")
                    opts["group"] = g
                    if shp:
                        m_ = re.fullmatch(r"(\d+)[xX](\d+)", shp)
                        if not m_ or "0" in (m_.group(1), m_.group(2)):
                            die("group の形は group=名前:WxH (例: group=LiDAR:2x2)")
                        opts["shape"] = (int(m_.group(1)), int(m_.group(2)))
                else:
                    label_parts.append(tok)
            label = " ".join(label_parts)
            if not label:
                die("ラベルが空です")
            sp.ios.append((head == "in", kind, x, z, label, desc.strip(), ch, opts))
        elif head == "prop":
            # prop <プロパティ名> true
            # bool プロパティは既定 false で生成される。true で置きたいものだけ書く。
            toks = rest.rsplit(None, 1)
            if len(toks) != 2 or toks[1].lower() not in ("true", "false"):
                die("prop は「prop <プロパティ名> true」の形で書いてください")
            if toks[1].lower() == "true":
                sp.props.append(toks[0])
        elif head == "dropdown":
            # dropdown <プロパティ名> | <ラベル>=<値> | <ラベル>=<値> ...
            # 名前もラベルも空白や括弧を含むので、区切りは | 。ラベルと値は最後の = で分ける。
            # 書いた順に並ぶ。エンジン側の DROPDOWN 表より優先する。
            parts = [x.strip() for x in rest.split("|")]
            if len(parts) < 3 or not parts[0]:
                die("dropdown は「dropdown <名前> | <ラベル>=<値> | <ラベル>=<値> ...」の形です(項目は2つ以上)")
            items = []
            for it in parts[1:]:
                lb, eq, val = it.rpartition("=")
                if not eq or not lb.strip():
                    die("dropdown の項目 %r は <ラベル>=<値> の形ではありません" % it)
                try:
                    num = float(val)
                except ValueError:
                    die("dropdown の項目 %r の値が数値ではありません" % it)
                if any(num == v for _, v in items):
                    die("dropdown %s: 値 %s が2回あります" % (parts[0], val.strip()))
                items.append((lb.strip(), num))
            sp.dropdowns[parts[0]] = items
        elif head == "slider":
            # slider <プロパティ名> <最小> <最大> <刻み>
            # pn("名前", 既定値) の数値プロパティをスライダーにする。名前は空白を含んでよいので、
            # 末尾の3語を数値として取る。エンジン側の SLIDER 表より優先する。
            toks = rest.rsplit(None, 3)
            try:
                lo, hi, st = float(toks[1]), float(toks[2]), float(toks[3])
            except (IndexError, ValueError):
                die("slider は「slider <プロパティ名> <最小> <最大> <刻み>」の形で書いてください")
            if not (hi > lo and st > 0):
                die("slider %s: 最大は最小より大きく、刻みは正にしてください" % toks[0])
            sp.sliders[toks[0]] = (lo, hi, st)
        elif head == "map":
            # map [<対象luaブロック>] <num|bool> <元...> [<ch範囲>] -> <ch範囲> [delay=<n>]
            # 元のラベルには空白が入りうるので、ここではトークン列のまま持ち、
            # ラベルが出揃ってからコンパイル側で解決する。
            if "->" not in rest:
                die("map 行には -> が要ります")
            left, _, right = rest.partition("->")
            lp, rp = left.split(), right.split()
            if not lp:
                die("map の左辺が空です")
            target = None
            if lp[0].lower() not in ("num", "bool"):
                target = lp[0]
                lp = lp[1:]
            if len(lp) < 2:
                die("map は「map [対象] <num|bool> <元> [ch範囲] -> <ch範囲>」の形です")
            kind = lp[0].lower()
            if kind not in ("num", "bool"):
                die("map の kind は num か bool です")
            delay = 0
            for tok in rp[1:]:
                if tok.lower().startswith("delay="):
                    try:
                        delay = int(tok[6:])
                    except ValueError:
                        die("delay= には整数を書いてください")
                else:
                    die("知らない指定 %r" % tok)
            if not rp:
                die("map の注入先がありません")
            dlo, dhi = parse_span(rp[0], "先", die)
            sp.maps.append((target, kind, lp[1:], dlo, dhi - dlo + 1, delay))
    if not sp.name:
        raise SystemExit("%s: name がありません" % path)
    if sp.icon is None:
        sys.stderr.write("%s: 警告: icon がありません。サムネイルは白紙になります"
                         " (icon <Obj番号> [英字])\n" % path)
    if not sp.lua:
        raise SystemExit("%s: lua がありません" % path)
    if not os.path.exists(sp.lua):
        raise SystemExit("%s: lua が見つかりません: %s" % (path, sp.lua))
    auto_layout(sp)
    if max(sp.size) > 6:
        sys.stderr.write("%s: 注意: %dx%d はエディタの上限 6x6 を超えます。ビークルには置けますが、"
                         "エディタで開いて保存すると 6x6 に戻ります(ゲーム内で編集しないこと)\n"
                         % (path, sp.size[0], sp.size[1]))
    return sp


def auto_layout(sp):
    """x z を省いたノードと size auto を埋める。全部書いてあれば何もしない。"""
    if sp.size is not None and all(i[2] is not None for i in sp.ios):
        return
    from mcbench import layout
    nodes = [dict(kind=k, x=x, z=z, group=o.get("group"), shape=o.get("shape"))
             for _, k, x, z, _, _, _, o in sp.ios]
    try:
        sp.size, pos = layout.place(nodes, sp.size, sp.size_w, sp.size_max)
    except ValueError as e:
        raise SystemExit("%s: 自動配置できません: %s" % (sp.path, e))
    sp.ios = [(i, k, p[0], p[1], l, d, c, o)
              for (i, k, _, _, l, d, c, o), p in zip(sp.ios, pos)]


# ---------------------------------------------------------------- 組み立て
class Source(object):
    """map の供給元。composite か、値そのもの(num/bool ノード)か。"""

    def __init__(self, cid, is_comp):
        self.cid, self.is_comp = cid, is_comp


def resolve_src(tokens, sources, name, die):
    """`<ラベル...> [<ch範囲>]` を (Source, (lo,hi) or None) にする。

    ラベルに空白が入るので、**ラベル全体での一致を先に試す。** 例えば "Axis 1" が
    宣言されていれば `map num Axis 1 -> 22` は「ラベル Axis 1」と読む。
    "Axis" も宣言されていて両方に読めるときは、そう言って止める。
    """
    whole = " ".join(tokens)
    if whole == "-":
        return None, None          # 明示的なゼロ埋め
    head = " ".join(tokens[:-1]) if len(tokens) > 1 else None
    if whole in sources:
        if head in sources:
            die("%s: map の元 %r が %r + ch とも読めます。ラベルを変えてください"
                % (name, whole, head))
        return sources[whole], None
    if head and head in sources:
        lo, hi = parse_span(tokens[-1], "元", lambda msg: die("%s: %s" % (name, msg)))
        return sources[head], (lo, hi)
    die("%s: map の元 %r がありません。`in` で宣言したラベルか lua の名前を書いてください"
        % (name, whole))


def build_stage(sp, m, target, sources, base, cache, die):
    """`target` へ入れる composite を組み立てて返す。(comp_id, 段数)

    生成物は Composite Read 群 + Composite Write の直列。

    【重要】Composite Write は**自分が担当するスパンを丸ごと書き潰す**(実機検証済み)。
    スパン内で入力を繋がなかった ch は素通りせず 0 で埋まる。だから
    **注入先が飛び飛びなら、連続する塊ごとに Write を分ける。** 1個の Write で
    またいでしまうと、間の ch が黙って 0 になる。

    【重要】部品1個につき1tick遅延する。ベースと1段目の注入は同相になるが、
    **後の段の注入ほど1tickずつ新しくなる。** 対になっているデータが段をまたぐと
    片方だけ先に届く。`delay=` はそれを揃えるためのパススルー段。

    間を意図的に 0 にしたいときは、元に `-` と書いてスパンに含める。
    """
    dest = {"num": {}, "bool": {}}
    for tgt, kind, tokens, dlo, n, delay in sp.maps:
        if tgt is not None and tgt != target:
            continue
        if tgt is None and target is not None:
            die("%s: 対象が複数あるので、map には対象名を書いてください "
                "(map <対象> %s ...)" % (sp.name, kind))
        src, span = resolve_src(tokens, sources, sp.name, die)
        if src is None:                      # ゼロ埋め
            slo = None
        elif src.is_comp:
            if span is None:
                die("%s: composite が元なので ch 範囲が要ります: %r"
                    % (sp.name, " ".join(tokens)))
            slo, shi = span
            if shi - slo + 1 != n:
                die("%s: 元(%d本)と先(%d本)の本数が違います"
                    % (sp.name, shi - slo + 1, n))
        else:
            if span is not None:
                die("%s: %r は num/bool ノードなので ch 範囲は書けません"
                    % (sp.name, " ".join(tokens[:-1])))
            if n != 1:
                die("%s: %r は値1本なので、先も1chにしてください"
                    % (sp.name, " ".join(tokens)))
            slo = None
        for k in range(n):
            d = dlo + k
            if d in dest[kind]:
                die("%s: %s の ch%d に2つの map が重なっています" % (sp.name, kind, d))
            dest[kind][d] = (src, (slo + k) if slo is not None else None, delay)

    feed, stages, col = base, 0, 0
    for kind in ("num", "bool"):
        want = dest[kind]
        if not want:
            continue
        # 連続する塊に切る。飛び飛びを1個の Write でまたぐと間が 0 になるため。
        runs, run = [], []
        for ch in sorted(want):
            if run and ch != run[-1] + 1:
                runs.append(run)
                run = []
            run.append(ch)
        runs.append(run)

        for run in runs:
            wired = []
            for i, d in enumerate(run):
                src, sch, delay = want[d]
                if src is None:
                    wired.append(None)       # 未接続 = 0
                    continue
                x = -14.0 + col * 2.0
                y = 8.0 - (i % 16) * 0.5
                # 同じ読み出しは使い回す。段をまたいでも部品が増えない。
                key = (src.cid, kind, sch, delay)
                cid = cache.get(key)
                if cid is None:
                    cid = src.cid
                    if sch is not None:
                        cid = (m.read_num(cid, sch, x, y) if kind == "num"
                               else m.read_bool(cid, sch, x, y))
                    for j in range(delay):
                        # 数値は Function(1入力) の e="x"、bool は Or の片側未接続。
                        if kind == "num":
                            cid = m.comp(45, [("e", "x")],
                                         ['<pos x="%.2f" y="%.2f"/>' % (x + 1.0 + j, y),
                                          '<in1 component_id="%d"/>' % cid, '<out1/>'])
                        else:
                            cid = m.comp(2, [],
                                         ['<pos x="%.2f" y="%.2f"/>' % (x + 1.0 + j, y),
                                          '<in1 component_id="%d"/>' % cid,
                                          '<in2/>', '<out1/>'])
                    cache[key] = cid
                wired.append(cid)
            col += 1

            ctype = 40 if kind == "num" else 41
            kids = ['<pos x="%.2f" y="%.2f"/>' % (-14.0 + col * 2.0, 4.0)]
            kids.append('<inc component_id="%d"/>' % feed if feed else '<inc><v/></inc>')
            kids += ['<in%d component_id="%d"/>' % (i + 1, c)
                     for i, c in enumerate(wired) if c is not None]
            kids.append('<out1/>')
            feed = m.comp(ctype, [("count", len(wired)), ("offset", run[0] - 1)], kids)
            stages += 1
            col += 1
    return feed, stages


PN_RE = r'pn\("%s",\s*(-?[\d.]+)\)'


def _lua_props(src):
    """Lua が読むプロパティ名 -> (種類, .lua の既定値 or None)。"""
    out = {}
    for n, v in re.findall(PN_RE % '([^"]+)', src):
        out.setdefault(n, ("num", v))
    for n in re.findall(r'property\.getNumber\("([^"]+)"\)', src):
        out.setdefault(n, ("num", None))
    for n in re.findall(r'property\.getBool\("([^"]+)"\)', src):
        out.setdefault(n, ("bool", None))
    return out


def resolve_fixes(sp, eng, props, die):
    """fix 行を {名前: 焼く値の文字列} にする。

    優先順位: fix に書いた値 > --props-from のセーブの値 > .lua の既定値(2026-11-03 合意)。
    """
    known = {}
    for _, lpath, _ in sp.luas:
        for n, kv in _lua_props(io.open(lpath, encoding="utf-8").read()).items():
            known.setdefault(n, kv)
    out = {}
    for toks in sp.fixes:
        whole, head = " ".join(toks), " ".join(toks[:-1])
        if whole in known and head in known:
            die("%s: fix %r は「%s を値なしで」とも「%s を %s に」とも読めます"
                % (sp.name, whole, whole, head, toks[-1]))
        if whole in known:
            name, val = whole, None
        elif head in known:
            name, val = head, toks[-1]
        else:
            die("%s: fix %r のプロパティをどの Lua も読んでいません"
                "(名前違いか、廃止済みのプロパティ)" % (sp.name, whole))
        kind, dflt = known[name]
        if val is None:
            val = props.get(name)
        if val is None:
            if kind == "bool":
                val = "true" if (name in eng.TRUE_BOOLS or name in sp.props) else "false"
            else:
                val = dflt
        if val is None:
            die("%s: fix %s に値がありません(.lua に既定値が無く、セーブにも無い)" % (sp.name, name))
        if kind == "bool":
            if val not in ("true", "false"):
                die("%s: fix %s は bool なので true か false です (%r)" % (sp.name, name, val))
        else:
            try:
                float(val)
            except ValueError:
                die("%s: fix %s は数値です (%r)" % (sp.name, name, val))
        out[name] = val
    return out


def bake_lua(src, baked, hits):
    """焼くプロパティの読み出しを定数に置き換える。

    **部品を消すだけでは駄目。** 無いプロパティは 0 を返し、pn() は 0 をそのまま
    使うので、既定値ではなく 0 で黙って動いてしまう。だから読み出しそのものを消す。
    置き換えきれない読み方(名前を変数で渡す等)が残ったらビルドを止める。
    """
    for n, v in baked.items():
        q = re.escape(n)
        lit = v if v in ("true", "false") else "(%s)" % v
        src, k1 = re.subn(PN_RE % q, lambda _: lit, src)
        src, k2 = re.subn(r'property\.get(?:Number|Bool)\("%s"\)' % q, lambda _: lit, src)
        hits[n] = hits.get(n, 0) + k1 + k2
        rest = eng_strip_comments(src)
        if '"%s"' % n in rest or "'%s'" % n in rest:
            raise SystemExit("fix %s: 置き換えられない読み方が Lua に残っています"
                             "(名前を変数で渡している等)。焼くと 0 で動くので止めます" % n)
    return src


def eng_strip_comments(src):
    """-- コメントを落とす(説明に名前を書いただけで止まらないように)。"""
    return re.sub(r'--\[\[.*?\]\]|--[^\n]*', '', src, flags=re.S)


# 出力が composite の部品(part の名前を composite の供給元として扱う)
COMP_OUT = {30, 32, 40, 41, 53, 54}


def load_catalog():
    """{type: (入力の本数, 出力の本数)}。tools/extract_catalog.py が作る表。"""
    import csv
    out = {}
    with io.open(os.path.join(HERE, "data", "component_catalog.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            out[int(r["type"])] = (int(r["inputs"] or 0), int(r["outputs"] or 0))
    return out


def compile_spec(sp, eng, props=None):
    """仕様どおりにマイコンを組む。返り値は (XML文字列, MC)。

    props: {プロパティ名: 値の文字列}。.lua の既定値の代わりに埋め込む(--props-from)。
    """
    def die(msg):
        raise SystemExit(msg)

    m = eng.MC(sp.name, sp.desc, sp.size[0], sp.size[1])
    if sp.icon:
        m.icon = eng.thumbnail(*sp.icon)
    # **props_from_lua() より前に置くこと。** あれが呼ばれた時点で
    # bool プロパティの v="true" が決まるので、後から代入しても効かない。
    if sp.props:
        m.true_props = set(sp.props)
    if sp.sliders:
        m.sliders = dict(sp.sliders)
    if sp.dropdowns:
        m.dropdowns = dict(sp.dropdowns)
    if props:
        m.prop_values = dict(props)

    # --- 焼き込み(--bake のときだけ) ---
    baked, hits = None, {}
    if sp.bake and sp.fixes:
        baked = resolve_fixes(sp, eng, props or {}, die)

    # --- 入力ノード。ラベルがそのまま map の供給元になる ---
    sources = {}
    base_label = None
    for is_in, kind, x, z, label, desc, ch, opts in sp.inputs:
        if label in sources:
            die("%s: 入力ラベル %r が重複しています" % (sp.name, label))
        cid = m.node(label, kind, True, x, z, desc)
        sources[label] = Source(cid, kind == "comp")
        if opts.get("base"):
            if kind != "comp":
                die("%s: role=base は composite にだけ付けられます (%r)" % (sp.name, label))
            if base_label is not None:
                die("%s: role=base は1本だけにしてください" % sp.name)
            base_label = label

    if not sp.luas:
        die("%s: lua がありません" % sp.name)
    comp_labels = [l for l, v in sources.items() if v.is_comp]

    # map の対象になれるもの: lua ブロック名と、composite の出力ノード名。
    # 対象が1つしかないときだけ、map の対象名を省ける。
    out_comp = set(l for i, k, x, z, l, d, c, o in sp.ios if not i and k == "comp")
    lua_names = [n for n, _, _ in sp.luas]
    named = set(t for t, _, _, _, _, _ in sp.maps if t is not None)
    for t in sorted(named):
        if t not in out_comp and t not in lua_names:
            die("%s: map の対象 %r がありません。lua の名前か、composite 出力の"
                "ラベルを書いてください" % (sp.name, t))
    # **合流先が2つ以上あるときだけ、map に対象名が要る。**
    # map から名指しされていない出力ノードは合流先として数えない(素通しなので)。
    # **lua と出力ノードが同名なら、map の対象は lua 側。** 以前は両方に数えられ、
    # その lua 向けの map が出力ノード側にも重ねて書かれていた(2026-11-03)。
    targets = lua_names + sorted(t for t in named if t in out_comp and t not in lua_names)
    # 合流先が1つだけのときは対象名を省けるが、**書いてあっても同じ意味にする。**
    # 以前は対象名付きの map が「対象なし」扱いの段と一致せず、黙って捨てられていた。
    # composite 入力が1本なら Lua に直結されるので症状が隠れ、
    # 数値入力だけのマイコンで Lua の入力が丸ごと未接続になった(2026-09-25)。
    if len(targets) == 1:
        sp.maps = [(None if t == targets[0] else t,) + tuple(rest) for t, *rest in sp.maps]

    # --- 個別の num/bool 入力の扱い ---
    # map を1行も書かない仕様ファイルでは、宣言順に ch1 から詰める(従来の pack と
    # 同じ挙動)。**map を書いた仕様ファイルでは、全部を明示させる。** 暗黙の詰め方と
    # 明示の注入が混ざると、どちらが ch を取るのか読めなくなるため。
    scalars = [(label, kind) for _, kind, _, _, label, _, _, _ in sp.inputs
               if kind in ("num", "bool")]
    if scalars and not sp.maps:
        first = sp.luas[0][0] if len(sp.luas) > 1 else None
        for kind in ("num", "bool"):
            n = 0
            for label, k in scalars:
                if k != kind:
                    continue
                n += 1
                sp.maps.append((first, kind, [label], n, 1, 0))
    elif scalars:
        named = set()
        for tgt, kind, tokens, dlo, n, delay in sp.maps:
            named.add(" ".join(tokens))
        loose = [l for l, _ in scalars if l not in named]
        if loose:
            die("%s: num/bool 入力 %s が map で使われていません。"
                "map を使う仕様ファイルでは、どの ch に入れるかを全部書いてください。"
                % (sp.name, ", ".join(repr(x) for x in loose)))

    # --- Lua ブロックは2パスで組む ---
    #
    # **1パス目で部品だけ先に全部作り、2パス目で配線する。** こうしないと、後ろで
    # 宣言したブロックを前のブロックが参照できない。後続から上流へデータを戻す
    # (フィードバック)構成が書けなくなるので、順序に依存しない作りにしてある。
    #
    # 後方参照した値は**前tickのもの**になる。ロジック部品はどれも1tick遅延するので、
    # 閉路は「1tick遅れの戻り」として素直に成立する。生成時に一覧を出して見えるようにする。
    cache, lua_cids, lua_kids, last, stages = {}, {}, {}, None, 0
    # プロパティはブロックごとではなく、全ブロックを集めてから1回で置く。
    # ゲーム内の一覧は部品を作った順に並ぶので、ここでまとめないと
    # 「ブロックごとにアルファベット順」という探しにくい並びになる。
    lua_srcs = []
    for idx, (lname, lpath, lbase) in enumerate(sp.luas):
        if lname in sources:
            die("%s: lua の名前 %r が入力ラベルと衝突しています" % (sp.name, lname))
        lua_src = io.open(lpath, encoding="utf-8").read()
        if baked is not None:
            lua_src = bake_lua(lua_src, baked, hits)
        body = eng.stamp(eng.compress(lua_src))
        # README の「ビルド時に止まる条件」に書いてあるのに止まっていなかった。
        # lint だけが LUA-LEN で拾い、超過したマイコンがインストールされた(2026-09-25)
        if len(body) > 8192:
            die("%s: lua %s が圧縮後 %d 字で、上限 8192 字を超えています" % (sp.name, lname, len(body)))
        kids = ['<pos x="%.2f" y="0.00"/>' % (idx * 3.0), "<in1/>", "<out1/>"]
        cid = m.comp(56, [("script", eng.esc(body))], kids)
        lua_srcs.append(lua_src)
        sources[lname] = Source(cid, True)
        lua_cids[lname] = cid
        lua_kids[lname] = kids
        last = cid

    if baked is not None:
        unread = sorted((n for n in baked if not hits.get(n)), key=str.lower)
        if unread:
            die("%s: fix したプロパティ %s をどの Lua も読んでいません"
                "(名前違いか、廃止済みのプロパティ)" % (sp.name, unread))
        m.mcbench_baked = [(n, baked[n]) for n in sorted(baked, key=str.lower)]
    m.props_from_lua("\n".join(lua_srcs))
    # dropdown / slider 行の名前を Lua が pn() で読んでいなければ、部品にならず黙って消える。
    # 焼いたもの(--bake の fix)は部品を作らないので除く
    placed = set(getattr(m, "prop_defaults", {})) | set(baked or ())
    for what, names in (("dropdown", sp.dropdowns), ("slider", sp.sliders)):
        miss = sorted((n for n in names if n not in placed), key=str.lower)
        if miss:
            die("%s: %s %s を Lua が pn() で読んでいません(名前違いか、廃止済みのプロパティ)"
                % (sp.name, what, miss))

    # --- Composite Switchbox (type 53) ---
    # in1 = sel が on のとき通す / in2 = off のとき / in3 = sel(bool)。保存済み43件の実例で、
    # in3 v="true" のとき out1 が in1 と同じ値。**通過は1tick**(ロジック部品と同じ)。
    # Lua と同じく、部品を先に全部作ってから配線する。スイッチ同士や lua base= から
    # 順序に依存せず参照できるように。
    #
    # Video Switchbox (type 57) も同じ端子構成(in1/in2 = 映像、in3 = sel)。
    # **ON 側が in1 なのは Composite からの類推で未検証**(映像は値が残らずコーパスで判別できない)。
    # 出力を Lua の映像入力(in2)へ繋ぐ例は保存済みに23件ある(2026-11-03 確認)。
    vid_in = set(l for i, k, x, z, l, d, c, o in sp.ios if i and k == "vid")
    sw_kids, vsw = {}, {}          # vsw: 映像スイッチ名 -> cid
    for sname, _, _, _, skind in sp.switches:
        if sname in sources or sname in vsw:
            die("%s: switch の名前 %r が入力ラベルか lua の名前と衝突しています" % (sp.name, sname))
        kids = ['<pos x="0.00" y="0.00"/>', "<in1/>", "<in2/>", "<in3/>", "<out1/>"]
        cid = m.comp(57 if skind == "vid" else 53, [], kids)
        if skind == "vid":
            vsw[sname] = cid
        else:
            sources[sname] = Source(cid, True)
        sw_kids[sname] = kids

    def vid_ref(frm):
        """映像の供給元を in 端子の属性にする。無ければ None。"""
        if frm in vid_in:
            return 'component_id="%d"' % sources[frm].cid
        if frm in lua_cids:            # Lua の映像出力は out2
            return 'component_id="%d" node_index="1"' % lua_cids[frm]
        if frm in vsw:
            return 'component_id="%d"' % vsw[frm]
        return None

    for sname, on, off, sel, skind in sp.switches:
        kids = sw_kids[sname]
        for slot, frm in ((1, on), (2, off)):
            side = "on" if slot == 1 else "off"
            if skind == "vid":
                ref = vid_ref(frm)
                if ref is None:
                    die("%s: switch %s の %s=%r という映像がありません。映像入力のラベル、"
                        "lua の名前、映像 switch の名前のどれかです" % (sp.name, sname, side, frm))
                kids[slot] = '<in%d %s/>' % (slot, ref)
                continue
            if frm not in sources or not sources[frm].is_comp:
                die("%s: switch %s の %s=%r という composite がありません"
                    % (sp.name, sname, side, frm))
            kids[slot] = '<in%d component_id="%d"/>' % (slot, sources[frm].cid)
        src, span = resolve_src(sel, sources, sp.name, die)
        if src is None:
            die("%s: switch %s の sel= に - は書けません" % (sp.name, sname))
        if span is None:
            if src.is_comp:
                die("%s: switch %s の sel= は bool です。composite なら ch も書いてください"
                    " (例: sel=Pack 1)" % (sp.name, sname))
            kids[3] = '<in3 component_id="%d"/>' % src.cid
        else:
            if span[0] != span[1] or not src.is_comp:
                die("%s: switch %s の sel= は bool 1本です" % (sp.name, sname))
            kids[3] = '<in3 component_id="%d"/>' % m.read_bool(src.cid, span[0], 0.0, 0.0)

    # --- part / wire / tip: カタログの部品をそのまま置く ---
    # 端子の本数はカタログ(data/component_catalog.csv)から引く。属性は書いたものだけ付ける
    # (省略した属性をゲームが既定値で補うかは未検証)。部品を先に全部作ってから配線するので、
    # 部品同士は宣言順に関係なく参照できる。名前は out1 を指す。
    cat = load_catalog()
    part_kids = {}
    for pname, ptype, attrs in sp.parts:
        if pname in sources or pname in vsw:
            die("%s: part の名前 %r が他の名前と衝突しています" % (sp.name, pname))
        if ptype not in cat:
            die("%s: part %s の type=%d はカタログにありません" % (sp.name, pname, ptype))
        n_in, n_out = cat[ptype]
        kids = (['<pos x="0.00" y="0.00"/>'] + ["<in%d/>" % (i + 1) for i in range(n_in)]
                + ["<out%d/>" % (i + 1) for i in range(n_out)])
        cid = m.comp(ptype, [(k, eng.esc(v)) for k, v in attrs], kids)
        sources[pname] = Source(cid, ptype in COMP_OUT)
        part_kids[pname] = kids

    def feed_ref(tokens, kind, what):
        """供給元トークン列を component_id にする。composite の ch は Read を挟む。"""
        src, span = resolve_src(tokens, sources, sp.name, die)
        if src is None:
            die("%s: %s に - は書けません" % (sp.name, what))
        if span is None:
            return src.cid
        if span[0] != span[1] or not src.is_comp:
            die("%s: %s の供給元は1本です" % (sp.name, what))
        if kind is None:
            die("%s: %s は composite の ch から読むので、num か bool を書いてください"
                % (sp.name, what))
        rd = m.read_num if kind == "num" else m.read_bool
        return rd(src.cid, span[0], 0.0, 0.0)

    for pname, port, kind, tokens in sp.wires:
        if pname not in part_kids:
            die("%s: wire の %r という part がありません" % (sp.name, pname))
        kids = part_kids[pname]
        ref = '<%s component_id="%d"/>' % (port, feed_ref(tokens, kind, "wire %s %s" % (pname, port)))
        for i, k in enumerate(kids):
            if k == "<%s/>" % port:
                kids[i] = ref
                break
            if k.startswith("<%s " % port):
                die("%s: %s の %s を2回つないでいます" % (sp.name, pname, port))
        else:
            kids.insert(len(kids) - 1, ref)     # inc / inoff などカタログに無い名前の端子

    # Tooltip Number (43) は in1 = 値、Tooltip On/Off (44) は in1 = bool。属性 l = 見出し、
    # 44 は on/off = 表示文字列(保存済みの実例どおり)。43 の in2 と m 属性は意味が未確定なので触らない
    for kind, tokens, label, on, off in sp.tips:
        ref = feed_ref(tokens, kind, "tip %s" % label)
        if kind == "num":
            m.comp(43, [("l", eng.esc(label))],
                   ['<pos x="0.00" y="0.00"/>', '<in1 component_id="%d"/>' % ref, "<in2/>"])
        else:
            m.comp(44, [("l", eng.esc(label)), ("on", eng.esc(on)), ("off", eng.esc(off))],
                   ['<pos x="0.00" y="0.00"/>', '<in1 component_id="%d"/>' % ref])

    order = {n: i for i, (n, _, _) in enumerate(sp.luas)}
    back = []
    for idx, (lname, lbase_path, lbase) in enumerate(sp.luas):
        if lbase is not None:
            if lbase not in sources:
                die("%s: lua %s の base=%r がありません" % (sp.name, lname, lbase))
            if not sources[lbase].is_comp:
                die("%s: lua %s の base=%r は composite ではありません"
                    % (sp.name, lname, lbase))
            base_cid = sources[lbase].cid
            if lbase in order and order[lbase] >= idx:
                back.append("%s の base=%s" % (lname, lbase))
        elif base_label is not None:
            base_cid = sources[base_label].cid
        elif len(comp_labels) == 1:
            base_cid = sources[comp_labels[0]].cid
        elif not comp_labels:
            base_cid = None
        else:
            die("%s: lua %s に流し込む composite を決められません。"
                "`role=base` か lua 行の `base=` で示してください" % (sp.name, lname))

        target = lname if len(targets) > 1 else None
        for tgt, kind, tokens, dlo, n, delay in sp.maps:
            if (tgt or target) != target:
                continue
            src_name = " ".join(tokens)
            for cand in (src_name, " ".join(tokens[:-1])):
                if cand in order and order[cand] >= idx:
                    back.append("%s <- %s" % (lname, cand))
                    break

        feed, nst = build_stage(sp, m, target, sources, base_cid, cache, die)
        stages += nst
        if feed:
            lua_kids[lname][1] = '<in1 component_id="%d"/>' % feed

    m.mcbench_back = back

    # --- 映像入力 → Lua 部品の in2 ---
    # Lua 部品は in1 = composite、in2 = 映像。実機の保存XMLで確認済み
    # (カメラ映像に重ね描きする Lua 部品が <in1 .../><in2 component_id=映像ブリッジ/>)。
    # `to=` を省けるのは Lua ブロックが1つのときだけ。
    fed = set()
    for is_in, kind, x, z, label, desc, ch, opts in sp.inputs:
        if kind != "vid":
            continue
        to = opts.get("to") or (lua_names[0] if len(lua_names) == 1 else None)
        if to is None:
            die("%s: 映像入力 %r に to=<luaブロック名> がありません" % (sp.name, label))
        if to not in lua_kids:
            die("%s: 映像入力 %r の to=%r という lua ブロックがありません" % (sp.name, label, to))
        if to in fed:
            die("%s: lua %s に映像入力が2本あります(Lua 部品の映像入力は1本)" % (sp.name, to))
        fed.add(to)
        lua_kids[to].insert(2, '<in2 component_id="%d"/>' % sources[label].cid)
    # 別の Lua ブロックの映像出力(out2)を受ける。out2 を指すので node_index="1"
    # (映像出力ノードのブリッジと同じ書き方。make_mc の出力ノード参照)。
    # 前段の Lua が描いた映像に、後段の onDraw が重なる。
    # 映像 switch の出力も受けられる(切り替えた映像の上に重ねる)。
    for to, frm in sp.vidfrom.items():
        ref = vid_ref(frm) if frm not in vid_in else None
        if ref is None:
            die("%s: lua %s の vid=%r がありません。lua の名前か映像 switch の名前です"
                % (sp.name, to, frm))
        if to in fed:
            die("%s: lua %s に映像入力が2本あります(Lua 部品の映像入力は1本)" % (sp.name, to))
        fed.add(to)
        lua_kids[to].insert(2, '<in2 %s/>' % ref)

    # --- 出力ノード ---
    for is_in, kind, x, z, label, desc, ch, opts in sp.outputs:
        cid = m.node(label, kind, False, x, z, desc)
        frm = opts.get("from")
        if frm is None:
            src = last
        elif kind == "vid" and frm in vsw:
            src = vsw[frm]
            m.src_ni[cid] = 0          # Video Switchbox の out1
        elif kind == "vid" and frm in vid_in:
            src = sources[frm].cid
            m.src_ni[cid] = 0
        elif frm in lua_cids:
            src = lua_cids[frm]
        elif frm in sources and sources[frm].is_comp:
            # 入力 composite / switch をそのまま出す、または土台にする
            src = sources[frm].cid
        elif frm in sources and kind in ("num", "bool"):
            # part の出力や個別の num/bool 入力を、そのまま出す
            if ch is not None:
                die("%s: 出力 %r の from=%r は composite ではないので ch= は書けません"
                    % (sp.name, label, frm))
            m.src[cid] = sources[frm].cid
            continue
        else:
            die("%s: 出力 %r の from=%r がありません。lua の名前、composite 入力の"
                "ラベル、switch の名前のどれかです" % (sp.name, label, frm))
        if kind == "comp" and label not in lua_names and any(
                (t or (targets[0] if len(targets) == 1 else None)) == label
                for t, _, _, _, _, _ in sp.maps):
            # この出力ノード向けの map があるので、composite を組み立てる。
            # from= を書いていればそれが土台、無ければ空から作る。
            base = src if opts.get("from") else None
            feed, n = build_stage(sp, m, label if len(targets) > 1 else None,
                                  sources, base, cache, die)
            stages += n
            m.src[cid] = feed
        elif kind in ("comp", "vid"):
            m.src[cid] = src
        else:
            if ch is None:
                die("%s: 出力 %r に ch= がありません" % (sp.name, label))
            m.src[cid] = (m.read_num(src, ch, 14.0, -1.0 * len(m.src)) if kind == "num"
                          else m.read_bool(src, ch, 14.0, -1.0 * len(m.src)))

    m.mcbench_stages = stages
    return m.build(), m


# ---------------------------------------------------------------- CLI
def _same(a, b):
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return a == b


def main():
    ap = argparse.ArgumentParser(
        prog="mccompile",
        description="仕様ファイルと .lua から、データ処理用マイコンの .xml を作る")
    ap.add_argument("specs", nargs="+", help="仕様ファイル(.mc)")
    ap.add_argument("-o", "--outdir", default=os.path.join(HERE, "out"),
                    help="出力先(既定: out/)")
    ap.add_argument("--engine",
                    help="別の make_mc.py を使う(既定は同梱の mcbench/make_mc.py)")
    ap.add_argument("--install", action="store_true",
                    help="ゲームのマイコンフォルダにもコピーする")
    ap.add_argument("--check", action="store_true",
                    help="書き出さず、通るかどうかだけ見る")
    ap.add_argument("--bake", "--dist", dest="bake", action="store_true",
                    help="配布版: fix 行のプロパティを定数に焼く(付けなければ fix は無効)")
    ap.add_argument("--props-from", metavar="VEHICLE.xml",
                    help="ビークルのセーブに置いてある同名マイコンのプロパティの値を、"
                         "生成時の既定値にする(セーブは読むだけ)")
    a = ap.parse_args()

    eng = load_engine(a.engine)
    paths = []
    for pat in a.specs:
        got = sorted(glob.glob(pat))
        if not got:
            raise SystemExit("見つかりません: %s" % pat)
        paths.extend(got)

    placed = None
    if a.props_from:
        from mcbench.vehicle import placed_props
        placed = placed_props(a.props_from)
        print("プロパティの引き継ぎ元: %s" % a.props_from)

    os.makedirs(a.outdir, exist_ok=True)
    rc = 0
    jobs = []
    for p in paths:
        sp = parse_spec(p)
        if placed is None:
            jobs.append((p, sp, None))
            continue
        sets = []
        for d in placed.get(sp.name, []):
            if d not in sets:
                sets.append(d)
        if not sets:
            print("    %s はセーブに置かれていません。.lua の既定値のまま作ります" % sp.name)
            jobs.append((p, sp, None))
        elif len(sets) == 1:
            jobs.append((p, sp, sets[0]))
        else:
            # 同じマイコンを値を変えて複数置いている(前後の砲塔など)。既定値は1つしか
            # 持てないので、置いてある組ごとに別名の版を作る
            diff = sorted({k for d in sets for k in d if len({x.get(k) for x in sets}) > 1},
                          key=str.lower)
            print("    %s は値の違う組が %d 個あります。別名で作ります" % (sp.name, len(sets)))
            for k, d in enumerate(sets, 1):
                v = copy.copy(sp)
                v.name = "%s #%d" % (sp.name, k)
                v.out = "%s #%d" % (sp.out or sp.name, k)
                print("      #%d: %s" % (k, ", ".join("%s=%s" % (n, d.get(n)) for n in diff)))
                jobs.append((p, v, d))

    for p, sp, props in jobs:
        sp.bake = a.bake
        if sp.fixes and not a.bake:
            print("    %s: fix %d 件は無効(開発版。配布版は --bake)" % (sp.name, len(sp.fixes)))
        try:
            xml, m = compile_spec(sp, eng, props)
        except SystemExit as e:
            print("NG  %s\n    %s" % (p, e))
            rc = 1
            continue
        if props is not None:
            dflt = getattr(m, "prop_defaults", {})
            changed = [n for n in sorted(dflt, key=str.lower)
                       if n in props and not _same(props[n], dflt[n])]
            dropped = sorted((n for n in props if n not in dflt), key=str.lower)
            fresh = sorted((n for n in dflt if n not in props), key=str.lower)
            print("    %s: 引き継ぎ %d 個(うち既定値と違う %d 個)"
                  % (sp.name, len(dflt) - len(fresh), len(changed)))
            for n in changed:
                print("      %-22s %s  (既定 %s)" % (n, props[n], dflt[n]))
            if fresh:
                print("    セーブに無いので既定値: %s" % ", ".join(fresh))
            if dropped:
                print("    今の .lua に無いので捨てた: %s" % ", ".join(dropped))
        n_lua = max(len(eng.compress(io.open(p2, encoding="utf-8").read()))
                    for _, p2, _ in sp.luas)
        st = getattr(m, "mcbench_stages", 0)
        for w in getattr(m, "mcbench_back", []):
            print("    後方参照 %s  (前tickの値になります)" % w)
        print("OK  %-28s ノード%2d / Lua %d字 / %dx%d%s"
              % (sp.name, len(sp.ios), n_lua, sp.size[0], sp.size[1],
                 (" / 合流%d段(=%dtick)" % (st, st)) if st else ""))
        baked = getattr(m, "mcbench_baked", [])
        if baked:
            print("    焼き込み %d 件: %s" % (len(baked), ", ".join("%s=%s" % kv for kv in baked)))
            kept = sorted(getattr(m, "prop_defaults", {}), key=str.lower)
            print("    焼かずに残したプロパティ %d 件: %s" % (len(kept), ", ".join(kept) or "なし"))
        print(m.grid())
        if a.check:
            continue
        dst = os.path.join(a.outdir, (sp.out or sp.name) + ".xml")
        io.open(dst, "w", encoding="utf-8", newline="\r\n").write(xml)
        print("    -> %s" % dst)
        if a.install:
            gdst = os.path.join(APPMC, os.path.basename(dst))
            if os.path.exists(gdst):
                shutil.copy2(gdst, gdst + ".bak")
            shutil.copy2(dst, gdst)
            print("    -> %s" % gdst)
    return rc


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
    sys.exit(main())
