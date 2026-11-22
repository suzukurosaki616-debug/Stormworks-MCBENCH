# -*- coding: utf-8 -*-
"""マイコン .xml の組み立てエンジン。**MCBENCH が持ち主。**

【由来】`Obj 1872` の `make_mc.py` の汎用部分(1〜703行)をそのまま引き取ったもの。
向こうに残っている `turret_servo()` などの「マイコン1個につきPython関数1本」は
Obj 1872 固有なので連れてきていない。**実機で何度も壊れて直された実装なので、
書き換えるときは理由をコメントに残すこと。**

【二重管理の注意】Obj 1872 側にも同じコードが残っている(向こうは今もこれで自分の
マイコンを生成しているため)。**今後の修正はこちらに入れる。** Obj 1872 が `.mc` 仕様
ファイルへ移行した時点で、向こうの `make_mc.py` は消える予定。
それまでの間、両者は放っておくと食い違う。

--- 以下、引き取り時の元のドキュメント ---

Obj 1872 - .lua から Stormworks のマイコン .xml を生成する(ゲーム外ツール)

%APPDATA%\\Stormworks\\data\\microprocessors\\*.xml の構造を実物から読み取って再現する。
1万字超のLuaをゲーム内エディタへ貼る工程、ノード配置、内部結線、プロパティ入力を省ける。

【実物から確定した型番号】(既存MC 109本 + ビークル 422本を全走査)
  ノード種別      入力ブリッジ  出力ブリッジ
  on/off  (0)          0            1
  number  (1)          2            3
  composite(5)         4            5
  video   (6)          6            7
  type=56  Luaスクリプト部品(script属性にソース。composite in/out を1本ずつ持つ)
  type=40  Composite Write Number  count=ch数 offset=開始ch-1 <inc>=通過元 <in1..inN>=値
  type=41  Composite Write On/Off  同上
  type=31  Composite Read Number   i=読むch-1(0始まり) <in1>=composite元
  type=29  Composite Read On/Off   同上
  type=34  Property Number         n=名前 <v text="値" value="値"/>
  type=33  Property Bool           n=名前 on/off=ラベル
  type=20  ドロップダウン・プロパティ(<items>付き)
(31/29/34は既存MC "Composite Reader Num" / "Composite Reader On Off" から確定)

プロパティの既定値は .lua の pn("名前", 既定値) から直接抽出するので、
コードとプロパティが食い違うことが原理的に起きない。

実行: python make_mc.py
"""

import io
import os
import hashlib
import re
import time

DEST = os.path.join(os.environ.get("APPDATA", ""), "Stormworks", "data", "microprocessors")

BRIDGE = {"bool": (0, 1), "num": (2, 3), "comp": (4, 5), "vid": (6, 7)}
# bool プロパティのうち true で生成するもの。Search only は捜索用インスタンス
# だけ手で入れる(1つのMCが両方の役割を兼ねるため)
TRUE_BOOLS = {"Gamma en", "Has fuse 1"}
NTYPE = {"bool": 0, "num": 1, "comp": 5, "vid": 6}
# 1マスを共有できるかの区分。bool と num だけは別の型なのに干渉する。
SLOT_CLASS = {"bool": "signal", "num": "signal", "comp": "comp",
              "vid": "vid", "audio": "audio"}


def esc(s):
    """XML属性値としてのエスケープ。改行とタブは文字参照にする。

    実物には生の改行を含む属性もあるが、XMLの属性値正規化では改行が空白に潰れうる。
    そうなるとLuaの -- コメントが行末を失って以降を全部飲み込むため、文字参照で書く。
    """
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    s = s.replace('"', "&quot;").replace("'", "&apos;")
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    return s.replace("\n", "&#10;").replace("\t", "&#9;")


# ---------------------------------------------------------------- Lua の圧縮
# ゲーム内エディタへ手で貼る工程を消すために、埋め込む直前に圧縮する。
# ソースの .lua はコメント付きのまま残す: マイコンを開いた人には圧縮後しか
# 見えないので、ソース側のコメントを削る理由がない。平均55%まで落ちるので
# 全ブロックが 8192 に収まり、プレースホルダが不要になった。
BS = chr(92)


def minify(src):
    """コメント・インデント・余分な空白を落とす。文字列リテラル内は触らない。"""
    out = []
    for line in src.replace("\r\n", "\n").split("\n"):
        r, q, i = [], None, 0
        while i < len(line):
            c = line[i]
            if q:
                r.append(c)
                if c == BS and i + 1 < len(line):
                    r.append(line[i + 1])
                    i += 2
                    continue
                if c == q:
                    q = None
            elif c == '"' or c == "'":
                q = c
                r.append(c)
            elif c == "-" and i + 1 < len(line) and line[i + 1] == "-":
                break
            else:
                r.append(c)
            i += 1
        t = "".join(r).strip()
        if t:
            out.append(t)
    s = "\n".join(out)
    # 文字列の外だけ空白を詰める
    parts, q, buf, i = [], None, [], 0
    while i < len(s):
        c = s[i]
        if q:
            buf.append(c)
            if c == BS and i + 1 < len(s):
                buf.append(s[i + 1]); i += 2; continue
            if c == q:
                parts.append(("s", "".join(buf))); buf = []; q = None
        elif c == '"' or c == "'":
            if buf:
                parts.append(("c", "".join(buf))); buf = []
            q = c; buf.append(c)
        else:
            buf.append(c)
        i += 1
    if buf:
        parts.append(("s" if q else "c", "".join(buf)))
    res = []
    for kind, txt in parts:
        if kind == "s":
            res.append(txt)
        else:
            txt = re.sub(r"[ \t]+", " ", txt)
            # .. は詰めない: Lua では 10 .. "km" を 10.."km" と書けない(10. が数値になる)
            txt = re.sub(r" ?(==|~=|<=|>=|[=,{}()\[\]<>+*/%#]) ?", r"\1", txt)
            res.append(txt)
    return "".join(res)


# ---------------------------------------------------------------- 識別子リネーム
# Lua予約語と、ストワ/標準ライブラリの入口になる名前。ここに載っている名前は絶対に
# 変えない。逆に言うと、ここに漏れがあると実機で "attempt to call a nil value" になる。
KEEP = set("""and break do else elseif end false for function goto if in local nil not
or repeat return then true until while
math table string pairs ipairs next type tostring tonumber select error assert pcall
xpcall setmetatable getmetatable rawget rawset rawequal rawlen unpack tointeger _ENV _G
input output screen property map async onTick onDraw httpReply""".split())

# 生成名に使う文字。数字は先頭に置けないので2文字目以降のみ
# 先頭に _ は使わない。hoist の仮名 _h0.. と紛れると追跡が面倒になるだけ
_HEAD = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
_TAIL = _HEAD + "0123456789"


def _namegen():
    """a, b, ... z, A, ... , aa, ab, ... を順に。予約語とぶつかるものは飛ばす"""
    import itertools
    n = 1
    while True:
        for tup in itertools.product(_HEAD, *([_TAIL] * (n - 1))):
            nm = "".join(tup)
            if nm not in KEEP:
                yield nm
        n += 1


def _split_strings(s):
    """[(is_string, text), ...] に分ける。長括弧 [[...]] は使っていないので扱わない"""
    parts, q, buf, i = [], None, [], 0
    while i < len(s):
        c = s[i]
        if q:
            buf.append(c)
            if c == BS and i + 1 < len(s):
                buf.append(s[i + 1]); i += 2; continue
            if c == q:
                parts.append((True, "".join(buf))); buf = []; q = None
        elif c == chr(34) or c == chr(39):
            if buf:
                parts.append((False, "".join(buf))); buf = []
            q = c; buf.append(c)
        else:
            buf.append(c)
        i += 1
    if buf:
        parts.append((q is not None, "".join(buf)))
    return parts


# 別名に畳んでよいライブラリ表。これらは実行中に差し替わらないので、
# sN = output.setNumber のように一度捕まえてしまってよい。
# ユーザー定義のテーブルは対象外(再代入されうるため)。
HOISTABLE = {"input", "output", "screen", "math", "property", "table", "string",
             "map", "async"}
MEMBER = re.compile(r"([A-Za-z_][A-Za-z_0-9]*)\.([A-Za-z_][A-Za-z_0-9]*)")


def hoist_members(src):
    """output.setNumber のような参照を先頭で1つの名前に束ねる。

    呼び出し1回あたり len("output.setNumber") - len(新名) を節約し、宣言1行を払う。
    元が取れるものだけ畳む。リネームより先に走らせると、新名も一緒に1文字化される。
    """
    parts = _split_strings(src)
    freq = {}
    for is_s, txt in parts:
        if is_s:
            continue
        for m in MEMBER.finditer(txt):
            if m.group(1) in HOISTABLE:
                freq[m.group(0)] = freq.get(m.group(0), 0) + 1

    chosen, i = {}, 0
    for full in sorted(freq, key=lambda k: (-freq[k] * len(k), k)):
        # 新名は2文字と仮定(リネーム後にそうなる)。宣言は "名前=full;" で len+2
        gain = freq[full] * (len(full) - 2) - (len(full) + 4)
        if gain > 0:
            chosen[full] = "_h%d" % i
            i += 1
    if not chosen:
        return src

    res = []
    for is_s, txt in parts:
        if is_s:
            res.append(txt); continue
        res.append(MEMBER.sub(
            lambda m: chosen.get(m.group(0), m.group(0)), txt))
    head = "".join("%s=%s " % (v, k) for k, v in chosen.items())
    return head + "".join(res)


# 【数値を先に食わせること】そうしないと 1e-6 の "e" を識別子と誤認して潰し、
# 1cp-6 のような壊れた数値になる(実際にやらかした)。0x1F / .5 / 1.5e+10 も同じ。
IDENT = re.compile(r"0[xX][0-9a-fA-F]+"
                   r"|(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?"
                   r"|(?P<id>[A-Za-z_][A-Za-z_0-9]*)")


def rename_idents(src, report=False):
    """変数名を1-2文字に潰す。文字列の中と、'.'/':' の直後(フィールド名)は触らない。

    全出現を一律に置き換える【全単射】なので、スコープは保たれる。ローカルとグローバル
    に同名があっても、両方が同じ新名になるだけで意味は変わらない。
    """
    parts = _split_strings(src)

    def targets(txt):
        out = []
        for m in IDENT.finditer(txt):
            if not m.group("id"):          # 数値リテラル
                continue
            j = m.start() - 1
            while j >= 0 and txt[j] == " ":
                j -= 1
            # 【".." は連結であってフィールド参照ではない】これを見落とすと
            # x .. name の形の name だけリネームされずに残る(実際にやらかした)
            if j >= 0 and txt[j] in ".:" and not (txt[j] == "." and j > 0
                                                  and txt[j - 1] == "."):
                continue
            if m.group("id") in KEEP:
                continue
            out.append(m)
        return out

    # 【フィールド名になりうる名前は、どこに出てきても一切リネームしない】
    # '.'/':' の後ろ(t.x)は元から触らないが、テーブル構築子のキー({x = 1})は
    # ただの識別子に見えるのでリネームされていた。すると {x=...} で作った表を t.x で
    # 読むと nil になる(Obj 1882 の Main が実機で落ちた。2026-09-24)。
    # キーだけを文脈で見分けてリネームを揃えるのはスコープ解析が要って危ういので、
    # フィールドとして使われる名前は丸ごと除外する。誤検出しても名前が長いまま残る
    # だけで、意味は壊れない。
    # キーらしき名前({k= / ,k=)は多重代入の左辺(a, b = ...)とも見分けがつかない。
    # 除外が要るのは「フィールドや文字列として読み戻されるキー」だけなので、
    # フィールド参照に出る名前は全部、キーらしき名前は文字列リテラルと一致するものだけ除外する。
    # (キーらしき名前を全部除外すると多重代入の変数まで長いまま残り、Obj 1882 Main が
    #  8192字を超えた)
    fields, keyish = set(), set()
    for is_s, txt in parts:
        if not is_s:
            for m in re.finditer(r'(?<!\.)[.:]\s*([A-Za-z_]\w*)', txt):
                fields.add(m.group(1))
            for m in re.finditer(r'[{,;]\s*([A-Za-z_]\w*)\s*=(?!=)', txt):
                keyish.add(m.group(1))
    fields |= keyish & {t[1:-1] for is_s, t in parts if is_s}

    freq = {}
    for is_s, txt in parts:
        if not is_s:
            for m in targets(txt):
                if m.group("id") in fields:
                    continue
                freq[m.group("id")] = freq.get(m.group("id"), 0) + 1
    # 出現の多い名前から短い新名を配る。同数なら元の名前順で結果を安定させる
    order = sorted(freq, key=lambda k: (-freq[k], k))
    # ソース中の文字列リテラルと同じ名前は避ける。実害は無い(Luaの定数プールが
    # 統合されるだけで値は同じ)が、バイトコード比較での検証が効かなくなるため。
    lits = {t[1:-1] for is_s, t in parts if is_s}
    gen = _namegen()
    # 除外した名前はソースにそのまま残るので、新名として配ってはいけない
    # (配ると別の変数と同じ名前になって衝突する)
    used = set(lits) | fields
    mapping = {}
    for name in order:
        nm = next(gen)
        while nm in used:
            nm = next(gen)
        used.add(nm)
        mapping[name] = nm

    res = []
    for is_s, txt in parts:
        if is_s:
            res.append(txt); continue
        buf, last = [], 0
        for m in targets(txt):
            if m.group("id") in fields:
                continue
            buf.append(txt[last:m.start()]); buf.append(mapping[m.group("id")])
            last = m.end()
        buf.append(txt[last:])
        res.append("".join(buf))
    out = "".join(res)
    if report:
        return out, mapping, freq
    return out


# ---------------------------------------------------------------- 自動レイアウト
# エディタのグリッドは 1マス = 0.25(実物の座標分布の最小刻みから確認)。
# 部品は「幅4マス、高さ = 入力と出力の多いほう + 1マス」で、左が入力・右が出力。
# 配線から依存の深さを出して列に割り当てれば、データが左から右へ流れる並びになり、
# 線の交差もほぼ消える。手で座標を振ると必ずどこかで重なる。
CELL = 0.25
COMP_W = 4          # マス
COL_GAP = 2         # マス。ユーザーの手組みに合わせる
ROW_GAP = 1


def _ports(ctype, children):
    """(入力数, 出力数) をマス数の計算用に返す"""
    ni = len([c for c in children if re.match(r'<in\d|<inc', c)])
    no = 2 if ctype == 56 else 1
    return ni, no


def _height(ctype, children):
    ni, no = _ports(ctype, children)
    return max(ni, no) + 1


def autolayout(mc):
    """comps と bridges に <pos> を振り直す。既存の <pos> は捨てる。

    列は配線の依存の深さ、列内は生成順。ビルダーは Composite Write の in1..inN と
    同じ順に read を作っているので、生成順に積めばポート順と一致して線が交差しない。
    重心法やポート番号での並べ替えを足すと、既に正しい順序を壊して逆に増える(実測)。
    【Y+ は上】なので、上から下へ流すには負方向へ積む。
    """
    kids = {cid: ch for _, cid, _, ch in mc.comps}
    ctypes = {cid: t for t, cid, _, _ in mc.comps}
    inb, outb = [], []
    for nid, cid, label, kind, is_in, x, z, d in mc.nodes:
        (inb if is_in else outb).append(cid)

    def deps(cid):
        if cid in mc.src:
            return [mc.src[cid]]
        out = []
        for c in kids.get(cid, []):
            out += [int(m) for m in re.findall(r'component_id="(\d+)"', c)]
        return out

    depth, seen = {}, set()

    def dep_of(cid):
        if cid in depth:
            return depth[cid]
        if cid in seen:
            return 0
        seen.add(cid)
        d = deps(cid)
        depth[cid] = 0 if not d else 1 + max(dep_of(x) for x in d)
        return depth[cid]

    for _, cid, _, _ in mc.comps:
        dep_of(cid)
    for cid in outb:
        dep_of(cid)

    isprop = lambda c: ctypes.get(c) in (19, 20, 33, 34)
    col = {}
    for cid in inb:
        col[cid] = 0
    for _, cid, _, _ in mc.comps:
        col[cid] = -1 if isprop(cid) else depth[cid] + 1
    for cid in outb:
        col[cid] = max(depth.values(), default=0) + 2

    # 【重要】<pos> はブロックの【下辺】。ブロックはそこから上へ伸びる。
    # だから下へ積むときは「高さを引いてからアンカーを置く」順でないと、前より背の
    # 高いブロックが上へはみ出して前のブロックに突き刺さる(実機で確認)。
    rows, pos = {}, {}
    for cid in sorted(c for c in col if not isprop(c)):
        k = col[cid]
        h = _height(ctypes.get(cid), kids.get(cid, [])) if cid in ctypes else 2
        y = rows.get(k, 0) - h
        rows[k] = y - ROW_GAP
        pos[cid] = ((k * (COMP_W + COL_GAP)) * CELL, y * CELL)

    # プロパティは【縦1列】。ゲームのプロパティ欄は「右上から下へ、次は1列左」の
    # 順(日本語の縦書きと同じ)で拾うので、1列にすれば欄の並び = 上から下 = ソース順に
    # なる。多列にすると列の折り返し位置でソース順と欄の順がズレて探しにくい。
    py = 0
    for cid in sorted(c for c in col if isprop(c)):
        py -= _height(ctypes.get(cid), kids.get(cid, []))
        pos[cid] = (-(COMP_W + COL_GAP) * 2 * CELL, py * CELL)
        py -= ROW_GAP
    return pos


def _repos(children, xy):
    out = [c for c in children if not c.startswith("<pos")]
    return ['<pos x="%.2f" y="%.2f"/>' % xy] + out


# ---------------------------------------------------------------- プロパティの形式
# 名前で引いて、列挙できるものはドロップダウン、範囲と刻みが自然なものはスライダー
# にする。数値入力より誤設定が減るのが狙いで、特に Gun type と El mode は「値の意味」
# を覚えていないと設定できなかったもの。
# 【型19(スライダー)と型20(ドロップダウン)は name= 属性、型33/34 は n= 属性】
# Stormworks 側の不統一なので間違えると読まれない。
DROPDOWN = {
    "Gun type": [("Machine Gun", 1), ("Light Autocannon", 2), ("Rotary Autocannon", 3),
                 ("Heavy Autocannon", 4), ("Battle Cannon", 5), ("Artillery Cannon", 6),
                 ("Bertha Cannon", 7)],
    "El mode": [("Velocity pivot", 0), ("Robotic pivot", 1)],
    "Fb source": [("Joint angle", 0), ("Muzzle reference", 1)],
    "Wind mode": [("Disabled", 0), ("Raw reading", 1),
                  ("Minus own velocity", 2), ("Plus own velocity", 3)],
    }

# 名前 -> (最小, 最大, 刻み)
SLIDER = {
    "Az centre": (-180, 180, 5), "Az span": (0, 360, 5),
    "Dir az centre": (-180, 180, 5), "Dir az span": (0, 360, 5),
    "Search az centre": (-180, 180, 5), "Search az span": (0, 360, 5),
    "Mask az centre": (-180, 180, 5), "Mask az span": (0, 360, 5),
    "Stow az": (-180, 180, 5),
    "El min": (-90, 90, 1), "El max": (-90, 90, 1), "Stow el": (-90, 90, 1),
    "Gimbal pitch lim": (0, 45, 1), "Search step": (1, 45, 0.1),
    "Search el": (-45, 45, 1),
    "Turret zero yaw": (-180, 180, 1), "Turret zero pitch": (-90, 90, 1),
    "Pivot max speed": (0.05, 20, 0.05),
    "El pos scale": (10, 180, 5),
    "KP yaw": (0, 10, 0.5), "KP el": (0, 10, 0.5),
    "KD yaw": (0, 2, 0.1), "KD el": (0, 2, 0.1),
    "T lat": (0, 20, 1), "Servo delay": (0, 12, 1), "Fuse lead": (0, 12, 1),
    "Aim tol": (0, 5, 0.05), "Miss gate": (0, 100, 5), "Track qual min": (0, 1, 0.1),
    "Alpha x10": (0.1, 3, 0.1), "Gamma scale x10": (0, 10, 0.5),
    "Adapt gain max": (1, 10, 0.5),
    "Start range": (1, 4, 1), "Ring count": (1, 6, 1),
}


def _num(v):
    """0 のとき value 属性を落とす。実物がそうなっている"""
    v = ("%g" % float(v))
    return ' text="%s"%s' % (v, "" if float(v) == 0 else ' value="%s"' % v)

# Thumbnail glyphs. Digits 3x5 (four fit in 15 columns), letters 5x7.
_DIGITS = {
    "0": ("###", "#.#", "#.#", "#.#", "###"), "1": (".#.", "##.", ".#.", ".#.", "###"),
    "2": ("###", "..#", "###", "#..", "###"), "3": ("###", "..#", "###", "..#", "###"),
    "4": ("#.#", "#.#", "###", "..#", "..#"), "5": ("###", "#..", "###", "..#", "###"),
    "6": ("###", "#..", "###", "#.#", "###"), "7": ("###", "..#", "..#", "..#", "..#"),
    "8": ("###", "#.#", "###", "#.#", "###"), "9": ("###", "#.#", "###", "..#", "###"),
}
_LETTERS = dict(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ", [g.split() for g in """
.###. #...# #...# ##### #...# #...# #...#|####. #...# #...# ####. #...# #...# ####.
.###. #...# #.... #.... #.... #...# .###.|####. #...# #...# #...# #...# #...# ####.
##### #.... #.... ####. #.... #.... #####|##### #.... #.... ####. #.... #.... #....
.###. #...# #.... #.### #...# #...# .###.|#...# #...# #...# ##### #...# #...# #...#
.###. ..#.. ..#.. ..#.. ..#.. ..#.. .###.|..### ...#. ...#. ...#. #..#. #..#. .##..
#...# #..#. #.#.. ##... #.#.. #..#. #...#|#.... #.... #.... #.... #.... #.... #####
#...# ##.## #.#.# #.#.# #...# #...# #...#|#...# ##..# #.#.# #..## #...# #...# #...#
.###. #...# #...# #...# #...# #...# .###.|####. #...# #...# ####. #.... #.... #....
.###. #...# #...# #...# #.#.# #..#. .##.#|####. #...# #...# ####. #.#.. #..#. #...#
.#### #.... #.... .###. ....# ....# ####.|##### ..#.. ..#.. ..#.. ..#.. ..#.. ..#..
#...# #...# #...# #...# #...# #...# .###.|#...# #...# #...# #...# #...# .#.#. ..#..
#...# #...# #...# #.#.# #.#.# ##.## #...#|#...# #...# .#.#. ..#.. .#.#. #...# #...#
#...# #...# .#.#. ..#.. ..#.. ..#.. ..#..|##### ....# ...#. ..#.. .#... #.... #####
""".strip().replace(chr(10), "|").strip("|").split("|")]))


def thumbnail(number, letter=None):
    """16x16 icon rows: the number right-aligned on rows 1-5, the letter on rows 7-13.

    Always top-aligned, also for a single MC (agreed 2026-09-25).
    """
    num = str(number)
    if not (num.isdigit() and 1 <= len(num) <= 4):
        raise SystemExit("icon: number must be 1-4 digits: %r" % number)
    rows = [0] * 16
    for k, d in enumerate(reversed(num)):
        col = 12 - 4 * k                     # rightmost digit at columns 12-14
        for r, line in enumerate(_DIGITS[d]):
            for c, px in enumerate(line):
                if px == "#":
                    rows[1 + r] |= 1 << (15 - col - c)
    if letter:
        g = _LETTERS.get(letter.upper() if len(letter) == 1 else None)
        if g is None:
            raise SystemExit("icon: letter must be one of A-Z: %r" % letter)
        for r, line in enumerate(g):
            for c, px in enumerate(line):
                if px == "#":
                    rows[7 + r] |= 1 << (15 - 5 - c)
    # Drawn above as screen rows (top first, MSB = left). The game stores the
    # icon rotated 180 deg: sym0 is the BOTTOM row and bit 0 is the LEFT column
    # (seen in game 2026-09-26: the first build came out upside down).
    return [int(format(v, "016b")[::-1], 2) for v in reversed(rows)]


class MC:
    """マイコン1個ぶんの組み立て。"""

    def __init__(self, name, desc, width, length):
        self.name, self.desc = name, desc
        self.width, self.length = width, length
        self.nodes = []      # (node_id, comp_id, label, kind, is_in, x, z, desc)
        self.comps = []      # (type, id, attrs, children)
        self.src = {}        # 出力ノードのcomp_id -> 供給元のcomp_id
        self.src_ni = {}     # 出力ノードのcomp_id -> 供給元の node_index(省略時は下の既定)
        self.next_node = 1
        self.next_comp = 20
        self.icon = [0] * 16   # sym0..sym15 (sym0 = bottom row, bit 0 = left)

    def node(self, label, kind, is_in, x, z, desc=""):
        """x=幅方向(0..width-1) / z=奥行き方向(0..length-1)。

        【重要】ノード面は x-z 平面。y は高さ軸なので使うとノードが面から外れ、
        ビークルに設置したときに端子が一切表示されなくなる(実機で踏んだ)。

        マス目からはみ出したノードは、エラーも出ないまま端子が消える。Charge ノードを
        幅6のMCの x=6 に置いて実際にやらかしたので、ここで止める。
        """
        # 【説明文は短く】保存済みマイコン115個を調べた実例の最長が72字。それを大きく
        # 超える説明を入れたマイコンでゲームが落ちた(150字)。上限は未検証だが、
        # 実例の範囲を出ないことにしておく。詳しい話は IOSpec.csv 側に書く。
        # 【説明はASCIIのみ・72字以内】保存済みマイコン115個を走査した結果、非ASCIIを
        # 含むものは1つも無く、説明の最長は72字だった。日本語を入れたら実機で文字列と
        # して選択できなくなり、長い説明(150字=UTF-8で約450バイト)では読み込んだ瞬間に
        # ゲームが落ちた。Luaのコメントを英語に限る理由(2バイト文字非対応)と同じ話で、
        # ノードの説明も同じテキスト系に乗っている。詳しい説明は IOSpec.csv 側へ書く。
        if any(ord(c) > 127 for c in desc + label):
            raise SystemExit("%s: ノード %r の説明に非ASCII文字。ゲームが壊れる"
                             % (self.name, label))
        if len(desc) > 72:
            raise SystemExit("%s: ノード %r の説明が %d 字。72字以内にすること"
                             % (self.name, label, len(desc)))
        if not (0 <= x < self.width and 0 <= z < self.length):
            raise SystemExit(
                "%s: ノード %r が %dx%d の外 (x=%s, z=%s)。"
                "有効範囲は x=0..%d / z=0..%d"
                % (self.name, label, self.width, self.length, x, z,
                   self.width - 1, self.length - 1))
        # 【同じマスは型の区分ごとに1本ずつ共有できる】(ユーザーが実機で確認、2026-08-31)
        # 1マスに 信号(bool/number) 1本 + composite 1本 + video 1本 + audio 1本。
        # **入出力の向きは関係しない。** bool と number は別の型なのに干渉するので、
        # 同じ区分に入れて同居させない。
        # 【注意】保存済みマイコン116個ではこの規則を確かめられない。端子が同居して
        # いるマスが731マス中1件(composite入力 + video出力)しか無く、面も型も両方
        # 違うため、「入力面と出力面で別グリッド」という誤った仮説とも矛盾しない。
        # 以前ここは型を見ずに「同じマスに2つ置けない」で止めていた。安全側ではあるが、
        # 実機より厳しいぶんマイコンが無駄に大きくなっていた。
        cls = SLOT_CLASS.get(kind, "signal")
        for _, _, ol, okind, _, ox, oz, _ in self.nodes:
            if (ox, oz) == (x, z) and SLOT_CLASS.get(okind, "signal") == cls:
                raise SystemExit(
                    "%s: ノード %r と %r が同じマスの同じ枠 (x=%s, z=%s, %s)。"
                    "1マスに置けるのは %s 1本まで"
                    % (self.name, label, ol, x, z, cls,
                       "信号(bool/num)" if cls == "signal" else cls))
        nid, cid = self.next_node, self.next_comp
        self.next_node += 1
        self.next_comp += 1
        self.nodes.append((nid, cid, label, kind, is_in, x, z, desc))
        return cid

    def comp(self, ctype, attrs, children):
        cid = max(40, self.next_comp)
        self.next_comp = cid + 1
        self.comps.append((ctype, cid, attrs, children))
        return cid

    def read_num(self, src, ch, x, y):
        """composite の ch 番(1始まり)を数値として取り出す"""
        return self.comp(31, [("i", ch - 1)],
                         ['<pos x="%.2f" y="%.2f"/>' % (x, y),
                          '<in1 component_id="%d"/>' % src, '<out1/>'])

    def read_bool(self, src, ch, x, y):
        return self.comp(29, [("i", ch - 1)],
                         ['<pos x="%.2f" y="%.2f"/>' % (x, y),
                          '<in1 component_id="%d"/>' % src, '<out1/>'])

    def pack(self, nums=(), bools=(), base=None, x=0.0, y=0.0):
        """数値/boolの部品出力から composite を1本組み立てる。

        MC間の通信はできる限りこれでまとめる。IOノード数が全体のボトルネックで、
        composite 1本 = ノード1個に対し、数値を個別に出すとノードが本数分要る。
        base=None なら空のcompositeから作る。
        """
        c = base
        if nums:
            c = self.comp(40, [("count", len(nums)), ("offset", 0)],
                          ['<pos x="%.2f" y="%.2f"/>' % (x, y),
                           '<inc component_id="%d"/>' % c if c else '<inc><v/></inc>']
                          + ['<in%d component_id="%d"/>' % (i + 1, s) for i, s in enumerate(nums)
                             if s] + ['<out1/>'])
        if bools:
            c = self.comp(41, [("count", len(bools)), ("offset", 0)],
                          ['<pos x="%.2f" y="%.2f"/>' % (x + 1.5, y),
                           '<inc component_id="%d"/>' % c if c else '<inc><v/></inc>']
                          + ['<in%d component_id="%d"/>' % (i + 1, s) for i, s in enumerate(bools)
                             if s] + ['<out1/>'])
        return c

    def props_from_lua(self, lua):
        """.lua の pn("名前", 既定値) を拾って Property Number 部品にする。

        【重要】エディタのキャンバスは2次元なので、同じ <pos> に置くと部品が重なって
        見えなくなる。複数のLuaを載せるMCではこのメソッドが複数回呼ばれるため、
        配置カウンタはインスタンスに持たせて呼び出しをまたいで連番にすること。
        名前が重複するプロパティは1個にまとめる(同名を2個置くと値が食い違う)。

        **置く順は名前のアルファベット順。** ゲーム内のプロパティ一覧は部品を作った順に
        並ぶので、`.lua` の出現順のままだと、数十個あるとき目当ての1個を探すのが苦痛になる。
        数値・真偽・ドロップダウン・スライダーを混ぜて1つの順序にする(種類で分けると
        結局2箇所を探すことになる)。
        """
        if not hasattr(self, "_pn"):
            self._pn, self._pnames = 0, set()
        drop = getattr(self, "drop_props", ())
        items = []
        for n, v in re.findall(r'pn\("([^"]+)",\s*(-?[\d.]+)\)', lua):
            if n in self._pnames or n in drop:
                continue
            self._pnames.add(n)
            items.append((n, "num", v))
        for n in re.findall(r'property\.getBool\("([^"]+)"\)', lua):
            if n in self._pnames or n in drop:
                continue
            self._pnames.add(n)
            items.append((n, "bool", None))
        items.sort(key=lambda t: t[0].lower())

        # Values carried over from a vehicle save (mccompile --props-from) replace the
        # .lua defaults. A placed MC is a copy, so rebuilding the library otherwise
        # resets every tuned value (Obj 1872: Pivot max speed 1 -> 5 made the turret
        # turn at a fifth of the commanded rate, 2026-11-02).
        ov = getattr(self, "prop_values", None) or {}
        if not hasattr(self, "prop_defaults"):
            self.prop_defaults = {}
        added = 0
        for n, kind, v in items:
            self._pn += 1
            self.prop_defaults[n] = (
                ("true" if n in TRUE_BOOLS or n in getattr(self, "true_props", ()) else "false")
                if kind == "bool" else v)
            if kind != "bool" and n in ov:
                v = ov[n]
            if kind == "bool":
                # Bool property: v="true" is the whole story. The game drops the on/off
                # label overrides and the empty <out1/>, and omitting v entirely means
                # false. Without this the generated MC came up with every bool OFF, which
                # silently disabled the acceleration estimator and the fuse output.
                on = (ov[n] == "true" if n in ov
                      else n in TRUE_BOOLS or n in getattr(self, "true_props", ()))
                a = [("n", esc(n))] + ([("v", "true")] if on else [])
                self.comp(33, a, ['<pos/>'])
                continue
            spec_dd = getattr(self, "dropdowns", {})
            if n in spec_dd or n in DROPDOWN:
                items = spec_dd.get(n) or DROPDOWN[n]
                sel = next((k for k, (_, val) in enumerate(items)
                            if float(val) == float(v)), None)
                if sel is None:
                    if n in spec_dd:
                        # A value that matches no item silently selected the first one
                        raise SystemExit("%s: dropdown %s の値 %s がどの項目にもありません (%s)"
                                         % (self.name, n, v, ", ".join(
                                             "%s=%g" % (lb, val) for lb, val in items)))
                    sel = 0
                # i is the 0-based item index and the ONLY thing the game reads; v is
                # ignored (in-game probe 2026-11-03). i = sel + 1 put every dropdown one
                # item past its default. v is still written to match, for readability.
                self.comp(20, [("name", esc(n)), ("v", "%g" % items[sel][1]),
                               ("i", sel)],
                          ['<pos/>', '<out1 v="%g"/>' % items[sel][1],
                           '<items>' + "".join(
                               '<i l="%s"><v%s/></i>' % (esc(lb), _num(val))
                               for lb, val in items) + '</items>'])
            elif n in getattr(self, "sliders", {}) or n in SLIDER:
                # a spec's own slider line wins over the shared table
                lo, hi, st = getattr(self, "sliders", {}).get(n) or SLIDER[n]
                self.comp(19, [("name", esc(n))],
                          ['<pos/>', '<out1 v="%s"/>' % v,
                           '<min%s/>' % _num(lo), '<max%s/>' % _num(hi),
                           '<int%s/>' % _num(st), '<v%s/>' % _num(v)])
            else:
                self.comp(34, [("n", esc(n))],
                          ['<pos/>', '<out1 v="%s"/>' % v,
                           '<v text="%s" value="%s"/>' % (v, v)])
            added += 1
        return added

    # ------------------------------------------------------------------ 出力
    def _nodes_xml(self):
        out = []
        for nid, cid, label, kind, is_in, x, z, d in self.nodes:
            mode = ' mode="1"' if is_in else ""
            pos = ""
            if x or z:
                pos = '\n\t\t\t\t<position%s%s/>\n\t\t\t' % (
                    ' x="%d"' % x if x else "", ' z="%d"' % z if z else "")
            body = '<node label="%s"%s type="%d" description="%s"%s' % (
                esc(label), mode, NTYPE[kind], esc(d), (">" + pos + "</node>") if pos else "/>")
            out.append('\t\t<n id="%d" component_id="%d">\n\t\t\t%s\n\t\t</n>' % (nid, cid, body))
        return "\n".join(out)

    def _bridges_xml(self, states):
        out = []
        for i, (nid, cid, label, kind, is_in, x, z, d) in enumerate(self.nodes):
            bt = BRIDGE[kind][0 if is_in else 1]
            # 映像出力はLua部品の out2 なので node_index="1" が必須。
            # 付けないと out1(composite) を拾って映像が出ない(Hello World.xml の実物準拠)
            # 供給元が Video Switchbox などの out1 なら src_ni で 0 を指定する。
            k = self.src_ni.get(cid, 1 if kind == "vid" else 0)
            ni = ' node_index="%d"' % k if k else ""
            inner = "" if is_in else (
                '\n\t\t\t\t\t<in1 component_id="%d"%s/>' % (self.src[cid], ni))
            bx, by = self._bpos[cid]
            body = '<pos x="%.2f" y="%.2f"/>%s' % (bx, by, inner)
            if states:
                out.append('\t\t\t<c%d id="%d">\n\t\t\t\t%s\n\t\t\t</c%d>' % (i, cid, body, i))
            else:
                out.append('\t\t\t<c type="%d">\n\t\t\t\t<object id="%d">\n\t\t\t\t\t%s'
                           '\n\t\t\t\t</object>\n\t\t\t</c>' % (bt, cid, body))
        return "\n".join(out)

    def _comps_xml(self, states):
        out = []
        for i, (ctype, cid, attrs, children) in enumerate(self.comps):
            a = "".join(' %s="%s"' % kv for kv in attrs)
            ch = "\n\t\t\t\t\t".join(children)
            if states:
                out.append('\t\t\t<c%d id="%d"%s>\n\t\t\t\t\t%s\n\t\t\t</c%d>' % (i, cid, a, ch, i))
            else:
                out.append('\t\t\t<c type="%d">\n\t\t\t\t<object id="%d"%s>\n\t\t\t\t\t%s'
                           '\n\t\t\t\t</object>\n\t\t\t</c>' % (ctype, cid, a, ch))
        return "\n".join(out)

    def audit(self, sources):
        """生成物の自己点検。プロパティ部品と Lua が要求する名前が食い違っていないか。

        部品が無い名前を読むと nil ではなく【0】が返る(6章 罠12)。射界の全幅が0に
        なればビームが1方向に固縛される、というように【エラーを出さずに機能が死ぬ】。
        名前を変えたのに部品側を直し忘れる事故を、ここで必ず捕まえる。
        """
        want = set()
        for src in sources:
            want |= set(re.findall(r'pn\("([^"]+)"', src))
            want |= set(re.findall(r'property\.getBool\("([^"]+)"', src))
        have = set()
        for ctype, _, attrs, _ in self.comps:
            if ctype in (19, 20, 33, 34):
                for k, v in attrs:
                    if k in ("name", "n"):
                        have.add(v)
        miss = sorted(want - have)
        if miss:
            raise SystemExit("%s: Lua が読むのに部品が無いプロパティ %s "
                             "(0が返って静かに壊れる)" % (self.name, miss))
        return sorted(have - want)

    def check(self, lua, label):
        """ch33以降を触っていないか検査する。

        【罠】Luaの input.get*/output.set* は1-32のみ有効で、33番以降は32番に
        クランプされる(共通資料2章、実機検証済み)。Composite Write 部品自体には
        この上限が無いので、offsetを32以上にすると「書けているのにLuaが読めない」
        という気づきにくい壊れ方をする。実際にPPIで踏んだので機械的に弾く。
        """
        bad = []
        for m in re.finditer(r'(?:input\.get|output\.set)(?:Number|Bool)\((\d+)', lua):
            if int(m.group(1)) > 32:
                bad.append("Lua ch%s" % m.group(1))
        for ctype, cid, attrs, ch in self.comps:
            if ctype in (40, 41):
                a = dict(attrs)
                hi = int(a.get("offset", 0)) + int(a.get("count", 0))
                if hi > 32:
                    bad.append("Write id=%d が ch%d まで書く" % (cid, hi))
            if ctype in (29, 31):
                if int(dict(attrs).get("i", 0)) + 1 > 32:
                    bad.append("Read id=%d が ch33以降" % cid)
        if bad:
            raise SystemExit("%s: チャンネル範囲違反 -> %s" % (label, ", ".join(sorted(set(bad)))))

    def grid(self, cell=9):
        """Occupancy map of the node grid, one panel per slot class.

        Each cell holds at most one node per class (signal / comp / vid / audio),
        and in game same-cell nodes are drawn on top of each other, so a node
        hidden under another is invisible by hand. This shows every layer.
        '>' = input, '<' = output, '.' = free. z is printed as stored
        (MCs can be rotated when placed, so which side z=0 faces does not matter).
        Returns the text; the caller decides where to print it.
        """
        panels = []
        for cls in ("signal", "comp", "vid", "audio"):
            at = {(x, z): (">" if is_in else "<") + label
                  for _, _, label, kind, is_in, x, z, _ in self.nodes
                  if SLOT_CLASS.get(kind, "signal") == cls}
            if not at:
                continue
            free = self.width * self.length - len(at)
            lines = ["  [%s] %d used / %d free" % (cls, len(at), free),
                     "      " + "".join(("x=%d" % x).ljust(cell) for x in range(self.width))]
            for z in range(self.length):
                lines.append("  z=%d " % z + "".join(
                    at.get((x, z), ".")[:cell - 1].ljust(cell) for x in range(self.width)).rstrip())
            panels.append(chr(10).join(lines))
        return chr(10).join(panels)

    def build(self):
        pos = autolayout(self)
        self.comps = [(t, cid, a, _repos(ch, pos[cid])) for t, cid, a, ch in self.comps]
        self._bpos = pos
        return self._ascii(self._xml())

    def _ascii(self, xml):
        """生成物【全体】がASCIIであることを保証する。

        Stormworks は2バイト文字を扱えない。保存済みマイコン115個を走査して非ASCIIを
        含むものは1つも無く、実際に入れたら日本語部分が描画されず、ドラッグ選択が壊れ、
        長いものではゲームが読み込み時に落ちた(描画されないのにバイト位置は占めるので
        表示と内部オフセットがズレる)。
        ノード説明だけを見張っても足りない。マイコン名・プロパティ名・ドロップダウンの
        項目、そして【Lua本文の文字列リテラル】も同じ穴に落ちる。だから最後に一度、
        出力そのものを検査する。
        """
        for i, c in enumerate(xml):
            if ord(c) > 127:
                raise SystemExit(
                    "%s: 生成物に非ASCII文字 %r (位置 %d)。Stormworks は2バイト文字を"
                    "扱えず、表示崩れかクラッシュになる。周辺: %r"
                    % (self.name, c, i, xml[max(0, i - 50):i + 20]))
        return xml

    def _xml(self):
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<microprocessor name="%s" description="%s" width="%d" length="%d"'
            ' id_counter="%d" id_counter_node="%d"%s>\n'
            '\t<nodes>\n%s\n\t</nodes>\n'
            '\t<group>\n\t\t<data>\n\t\t\t<inputs/>\n\t\t\t<outputs/>\n\t\t</data>\n'
            '\t\t<components>\n%s\n\t\t</components>\n'
            '\t\t<components_bridge>\n%s\n\t\t</components_bridge>\n'
            '\t\t<groups/>\n'
            '\t\t<component_states>\n%s\n\t\t</component_states>\n'
            '\t\t<component_bridge_states>\n%s\n\t\t</component_bridge_states>\n'
            '\t\t<group_states/>\n\t</group>\n</microprocessor>\n'
            % (esc(self.name), esc(self.desc), self.width, self.length,
               self.next_comp + 1, self.next_node + 1,
               "".join(' sym%d="%d"' % (i, v) for i, v in enumerate(self.icon) if v),
               self._nodes_xml(),
               self._comps_xml(False), self._bridges_xml(False),
               self._comps_xml(True), self._bridges_xml(True))
        )


# --- 以下も Obj 1872 の make_mc.py から引き取った汎用部分 ---

def stamp(body):
    """埋め込むLuaの先頭にビルド印を刺す。

    実機で「置いてあるマイコンが最新か」を確かめる手段がこれしか無い。生成ログの
    差し替えリストは【前回の生成からの差分】なので、数回ぶん飛ばして反映すると
    取りこぼす。実際に古いThreatEvalを掴んだまま2件を誤診した。
    文字列リテラルはリネームも圧縮も素通りするので、マイコンを開いて BUILD= を
    探せばそのまま読める。日付 + 中身のハッシュなので、中身が変われば必ず変わる。
    """
    h = hashlib.sha1(body.encode("utf-8")).hexdigest()[:4]
    return 'BUILD="%s-%s" %s' % (time.strftime("%m%d"), h, body)


# Stormworks の Lua は標準ライブラリが丸ごとは載っていない。ここに挙げたものは
# 実機で「nil を呼んだ」になる。まれにしか通らない分岐に潜むと、書いてから何日も
# 経って初めて落ちる(select は Mask az span を設定するまで一度も実行されなかった)。
# 目視レビューでは繰り返し取り逃がしているので、ビルドで機械的に止める。
# 実際に踏んだもの、または一次資料で裏が取れているものだけ。憶測で足さない -
# 使えるものを誤って禁止すると、後から書く人が理由の分からない壁にぶつかる。
#   select      実機で nil。Lua標準だが Stormworks には無い(2026-08-22)
#   math.atan2  Lua 5.3 で削除。2引数の math.atan を使う
#   drawArc     存在しない screen 関数。過去に呼んで実機で即エラー
BANNED = ("select(", "math.atan2(", "screen.drawArc(")


def check_banned(src, name):
    """Stormworks の Lua は標準ライブラリが丸ごとは載っていない。ここに挙げたものは
    実機で「nil を呼んだ」になる。まれにしか通らない分岐に潜むと、書いてから何日も
    経って初めて落ちる - select() は Mask az span を設定するまで一度も実行されず、
    そのあいだ何度もレビューを通り抜けた。目視では繰り返し取り逃がしているので、
    ビルドで機械的に止める。リファレンス3章の関数一覧が一次資料。
    """
    for b in BANNED:
        k = src.find(b)
        if k >= 0:
            line = src.count(chr(10), 0, k) + 1
            raise SystemExit(
                "%s: %d行目に Stormworks では使えない %s があります。"
                "リファレンス3章の関数一覧と突き合わせてください。" % (name, line, b))


def compress(src):
    """埋め込み用に潰す。3段で効く:

      minify        コメント・インデント・余分な空白
      hoist_members output.setNumber のような参照を先頭で1つの名前に束ねる
      rename_idents 変数名を1-2文字に潰す

    等価性は Compress_Verify.py がバイトコードで確認している。
    圧縮をいじったら必ず走らせること(これで既に3件のバグを捕まえている)。
    """
    # コメントを落としてから見る。禁止関数の【説明】を書いたコメントで自分の検査に
    # 引っかかった。
    mini = minify(src)
    check_banned(mini, "compress")
    return rename_idents(hoist_members(mini))
