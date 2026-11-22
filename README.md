# mccompile — データ処理用マイコンのコンパイラ

仕様ファイル + `.lua` から、Stormworksのマイコン `.xml` を生成する。

```bash
python mccompile.py spec/example/averager.mc
python mccompile.py spec/example/averager.mc --install   # ゲームのフォルダにも置く
python mccompile.py "spec/*.mc" --check                  # 通るかどうかだけ見る

python tools/mcb.py pack "out/なにか.xml"                # .mcb にくるむ
python tools/mcb.py install bundles/なにか.mcb           # ゲームのフォルダへ
python tools/mcb.py sync    bundles/なにか.mcb           # ゲーム側の変更を取り込む

python tools/selftest.py                                 # 全部まとめて確認
python tools/make_dist.py                                # 配布用 zip を作る
```

## なぜ仕様ファイルか

マイコンを Python で組み立てると、ノードの並び・型・ラベル・結線を全部コードで書く
ことになり、**マイコンを1個足すたびにコードが増える**。

mccompile はその部分をテキストの仕様ファイルに置き換える。

```
name  Bus Tap
desc  composite bus tap -> localhost HTTP
size  1 1
lua   Telemetry.lua

in  comp 0 0  Tap | Branch the bus to watch here. NEVER in series
```

ブロックを足す作業が「仕様ファイルを1枚書く」だけになり、**diffが取れてレビューできる**。

## 組み立てエンジン

XMLの組み立て・Lua圧縮・ASCII検査・チャンネル範囲検査・ノード配置検査は
`mcbench/make_mc.py` が持つ。mccompile 自身は「仕様ファイルを読んで `MC` クラスを
呼ぶ」ところだけ。

```
仕様ファイル(.mc) ──> [mccompile] ──> mcbench.make_mc.MC ──> .xml
```

**実機で何度も痛い目を見て直された実装なので、書き換えるときは理由をコメントに
残すこと。** `--engine` で別のファイルを指せる。

## 仕様ファイルの書き方

`#` 以降はコメント。空行は無視される。

### ヘッダ

| キーワード | 意味 |
|---|---|
| `name` | マイコン名。出力ファイル名にもなる |
| `desc` | 説明 |
| `size <幅> <奥行>` | ボクセル数。ノードはこの範囲にしか置けない(下記) |
| `lua [name=<名前>] [base=<供給元>] <パス>` | `.lua` への相対パス。**複数書ける**。`name=` を省くとファイル名の幹が名前。オプションは先頭に書き、残り全部がパス |
| `out` | 出力ファイル名(省略時は `name`) |

### 入出力

```
in   <kind> <x> <z>  <ラベル>          [| 説明]
out  <kind> <x> <z>  <ラベル>  ch=<n>  [| 説明]
```

`kind` は `comp` / `num` / `bool` / `vid`。

- **`in comp`** … Lua の composite 入力になる。`map` を使わないなら**1本まで**
  (Lua部品の composite 入力が1本しかないため)。複数束ねたいときは下の `map` を使う
- **`in num` / `in bool`** … composite に詰めてから Lua に渡す。
  `in comp` があればそれを土台にして上書きする
- **`in vid`** … Lua 部品の映像入力(in2)へ直結する。Lua が複数なら **`to=<luaブロック名>`** で行き先を書く。
  `onDraw` の描画はこの映像の上に重なる(カメラ映像へのオーバーレイ)
- **`lua ... vid=<luaブロック名>`** … 別の Lua ブロックの映像出力を、この Lua の映像入力へつなぐ。
  前段が描いた映像の上に、この Lua の `onDraw` が重なる(カメラ → 点群 → 追尾マーク、のような重ね順を作る)
- **`out comp`** … Lua の composite 出力を直結する
- **`out num` / `out bool`** … `ch=` で指定した ch を Composite Read で取り出す。**`ch=` は必須**

`x` は幅方向(0〜幅-1)、`z` は奥行方向(0〜奥行-1)。

### `map` — 複数の composite を1本に合流させる

```
in   comp  <x> <z>  <ラベル>  role=base            土台にする composite。1本だけ
map  num   <入力ラベル> <ch範囲> -> <ch範囲>  [delay=<n>]
map  bool  <入力ラベル> <ch範囲> -> <ch範囲>  [delay=<n>]
```

`ch範囲` は `5` か `1-6`。元と先は同じ本数にする。生成物は **Composite Read 群 +
Composite Write の直列**で、`role=base` の composite を土台に上書きしていく。

`map` の元には4種類書ける。**`in comp` のラベル**(ch範囲が要る)、
**`in num`/`in bool` のラベル**(値そのものなので ch範囲は書かない)、
**lua ブロックの名前**(ch範囲が要る)、**`-`**(その ch を 0 で潰す)。
同じ読み出しは使い回されるので、段をまたいで同じ ch を使っても部品は増えない。

`map` の対象には lua ブロックのほか **composite の出力ノード**も書ける。
Lua の出力から ch を選んで1本の composite に詰め直す回路が生成される。

**注入先が飛び飛びなら、連続する塊ごとに Composite Write が分かれる。**
1個の Write でまたぐと間の ch が 0 になるため。塊が増えるぶん tick も増えるので、
生成時に段数が表示される。

`prop <プロパティ名> true` で、bool プロパティを true で生成できる(既定は false)。

### 複数の Lua ブロック

**8192字の制限はスクリプトブロック単位**なので、2本の Lua を別ブロックのまま
同居させれば合計で超えても問題ない。センサーの読み出しを両段で共有でき、
マイコンが1個減るぶん tick も縮む。

```
lua  name=Stage1  First.lua
lua  name=Stage2  base=Stage1  Second.lua

map Stage1 num  Aux 1-3 -> 17-19
map Stage2 num  Aux 1-3 -> 21-23

out comp 0 1  Result  from=Stage2
out comp 1 1  Debug   from=Stage1
```

`base=` で前の段の出力 composite を土台にできる。**lua が複数あるとき `map` には
対象ブロック名が必須。** `out` の `from=` を省くと最後に宣言したブロックになる。

```
map num  Pos  1-3  -> 17-19      # Pos の ch1-3 を ch17-19 へ
map bool Aux  9    -> 7  delay=1 # 1tick遅らせてから ch7 へ
```

Composite Write は自分のスパンを丸ごと書き潰し、**スパン内で繋がなかった ch は
素通りせず 0 になる**(実機検証済み)。そのため注入先の連続する塊ごとに Write を
自動で分ける(上記)。間を意図して 0 にしたいときは、元に `-` と書いてスパンに含める。
重なり・本数違い・存在しない入力はコンパイル時に止まる。

**`delay=` は位相合わせ用。** 部品1個につき1tick遅延するので、土台と1段目の注入は
同相だが、**2段目の注入だけ1tick新しく届く**。対になっているデータが段をまたぐときに使う。

### 【重要】ノードの置き方

`x` は幅方向(0〜幅-1)、`z` は奥行方向(0〜奥行-1)。**マス目からはみ出したノードは
エラーも出ないまま端子が消える**ので、生成時に止める。

同じマスは**型の区分ごとに1本ずつ**共有できる —— 1マスに `信号(bool/number) 1本 +
composite 1本 + video 1本 + audio 1本`。入出力の向きは関係しない。bool と number は
別の型なのに干渉するので同居できない。

つまり `size 1 1` のマイコンでも、composite入力1本と bool出力1本を両方 `(0,0)` に
置ける。同じ区分どうし(例: `in num` と `out bool`)を重ねるとコンパイルが止まる。

## 例

`spec/example/averager.mc` — 数値/bool の入出力を使う例。

```
name  MCBENCH Averager
desc  rolling average with deviation tap
size  2 2
lua   Averager.lua

in   num  0 0  Signal    | The value to average
in   bool 1 0  Arm       | Enables the ready output

out  num  0 1  Average   ch=1  | Rolling mean
out  num  1 1  Deviation ch=2  | Input minus mean
```

生成される部品: `40`(数値pack) `41`(boolpack) → `56`(Lua) → `31`×2(Composite Read) と、
各ノードのブリッジ、`pn()` から起こした `34`(Property Number)。

## プロパティ

`.lua` の中の `pn("名前", 既定値)` を拾って、Property Number 部品を自動で置く。
仕様ファイルに書く必要はない。

```lua
function pn(n, d) local v = property.getNumber(n) if v == 0 then return d end return v end
win = pn("Window", 30)     -- これが Property Number "Window" (既定30) になる
```

**実機では未定義のプロパティは 0 を返す**([Stormworks-Reference](https://github.com/suzukurosaki616-debug/Stormworks-Reference) §6)。上の `pn` の形なら 0 のときに既定値へ
落ちるので安全。`property.getNumber` を直に使うと、未設定時に静かに 0 で動く。

### 置いてあるマイコンの値を引き継ぐ(`--props-from`)

**ビークルに置いたマイコンはライブラリのコピー**なので、作り直して置き直すと、
調整したプロパティが全部 `.lua` の既定値に戻る。`--props-from` にビークルのセーブを渡すと、
そこに置いてある**同名のマイコンの値**を既定値として埋め込む。セーブは読むだけ。

```bash
python mccompile.py spec/なにか.mc --install --props-from "%APPDATA%/Stormworks/data/vehicles/船.xml"
```

- 引き継いだ数、既定値と違うもの、セーブに無いので既定値にしたもの、`.lua` から消えたので
  捨てたものを毎回一覧で出す
- **同じマイコンを値を変えて複数置いている**(前後の砲塔など)ときは、組ごとに
  `名前 #1` / `名前 #2` の別名で作り、どの値が違うかを出す
- 数値・スライダー・ドロップダウン・トグルの4種を読む。値はセーブに書かれた文字列のまま

## ビルド時に止まる条件

`make_mc.py` 由来のものを含む。**どれも実機で実際に壊れた事例がある。**

- 圧縮後の Lua が **8192字**を超える
- 生成物に**非ASCII文字**が混ざる(マイコン名・ノードラベル・説明・**Luaの文字列リテラル**まで見る)
- ノード説明が **72字**を超える
- ノードが**マス目の外**、または**同じマスに2つ**
- composite の ch が **33以降**
- `select(` / `math.atan2(` / `screen.drawArc(` など**実機に無い関数**

## 制限

- ロジック部品(AND/PID/Timer 等)をグラフとして書く機能はまだ無い。
  データ処理は Lua に寄せる前提。`map` が面倒を見るのは composite の合流と分配だけ
- `--install` は `%APPDATA%\Stormworks\data\microprocessors` に書くので Windows 限定
- **lua ブロックと `out comp` に同じ名前を付けると、`map` の対象は lua 側になる。**
  その出力ノードへは `map` で詰め直せないので、詰め直したいなら名前を分ける

## 関連

- [AGENTS.md](AGENTS.md) — AI 向けの使い方(文法・罠・止まる条件の要点)
- [Stormworks-Reference](https://github.com/suzukurosaki616-debug/Stormworks-Reference) — MC Lua API と部品仕様の資料集(実機検証済みの知見)
- `mcbench/make_mc.py` — XML生成エンジン

## ライセンス

[MIT License](LICENSE) — Copyright (c) 2026 Suzu Kurosaki

改造・再配布・商用利用いずれも自由。**著作権表示とライセンス文を残すことだけが条件**で、
無保証。自分のビルド環境に組み込んで、その環境を公開しないのも構わない。

**同梱している `data/component_catalog.csv` は Stormworks の部品の type 番号と名前の
対応表**で、ゲームのファイルそのものではなく、こちらで調べて作った事実の一覧。
ゲームのアセットは一切同梱していない。
