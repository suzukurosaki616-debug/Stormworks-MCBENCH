# AI向けの使い方 — MCBENCH

**Stormworks のマイコン `.xml` を、ゲームの外で生成・読み込み・検証するツール一式**です。

人間向けの説明は [README.md](README.md)。
ここは**AIが最短で正しく使うための要点**だけを書きます。

Python 3 だけで動きます。外部ライブラリは不要です。

> **このファイルの例はすべて作り物です。** どのプロジェクトの実仕様でもありません。
> チャンネル対応は必ず、作業しているプロジェクトのチャンネル表などの
> 一次資料から取ってください。ここの例を写して使わないこと。

---

## 1. できること

| やりたいこと | 使うもの |
|---|---|
| 仕様ファイル + Lua から**マイコンを生成する** | `mccompile.py` |
| 既存のマイコン `.xml` を**読む / 書き戻す** | `mcbench` パッケージ |
| マイコンを**検証する**(実機で壊れる条件を機械的に止める) | `tools/lint.py` |
| マイコンを**1ファイルにまとめて渡す**(`.mcb` バンドル) | `tools/mcb.py` |
| **全部まとめて確かめる** | `tools/selftest.py` |

```bash
python mccompile.py spec/example/averager.mc            # 生成 -> out/
python mccompile.py spec/example/averager.mc --install  # ゲームのフォルダにも置く
python mccompile.py "spec/*.mc" --check                 # 生成せず、通るかだけ見る
python mccompile.py spec/example/averager.mc --props-from 船.xml  # 置いてある同名マイコンの値を既定値に

python tools/lint.py out/*.xml                          # 検証
python tools/lint.py --corpus                           # 保存済みマイコン全部を検証
python tools/roundtrip.py                               # 読み書きの自己往復テスト

python tools/mcb.py pack    "out/なにか.xml"            # .mcb にくるむ -> bundles/
python tools/mcb.py install bundles/なにか.mcb          # ゲームのフォルダへ
python tools/mcb.py sync    bundles/なにか.mcb          # ゲーム側の変更を取り込む
python tools/mcb.py info    bundles/なにか.mcb          # 中身と検証結果

python tools/selftest.py                                # 全部まとめて確認
python tools/make_dist.py                               # 配布用 zip を作る
```

### `.mcb` バンドル

**マイコン1個ぶんを1ファイルにまとめる共有形式**です。中に**ゲームの `.xml` を
そのまま丸ごと**抱えるので、「XMLが正」は保たれたまま、渡すのは1ファイルで済みます。

```
pack -> install -> ゲームで編集 -> sync
```

と回しても、**付箋(キャンバス上の注釈)は残り、回路はゲーム側が正**のままです。
付箋は `.mcb` の中にしか無く、`.xml` には一切書き出されません。

`[xml]` セクションは必ず最後で、そこから先は全部XMLです。Lua の中に `[xml]` という
行が現れても壊れません。**知らないセクションはそのまま持ち回る**ので、新しい版が
足した情報を古い版で開いて落とす、ということが起きません。

`--install` は `%APPDATA%\Stormworks\data\microprocessors` に書くので Windows 限定です。

---

## 2. 仕様ファイル(`.mc`)の文法

```
name  <マイコン名>              必須。出力ファイル名にもなる
desc  <説明>
size  <幅> <奥行>               ボクセル数
out   <出力ファイル名>           省略時は name

lua  [name=<名前>] [base=<供給元>] <.luaへのパス>     必須。複数書ける

in   <kind> <x> <z> <ラベル>  [role=base]        [| 説明]
out  <kind> <x> <z> <ラベル>  ch=<n> [from=<名前>] [| 説明]

map  [<対象>] <num|bool> <元> [<ch範囲>] -> <ch範囲>  [delay=<n>]
prop <プロパティ名> true
slider <プロパティ名> <最小> <最大> <刻み>        数値プロパティをスライダーに(共通の表より優先)
```

`lua` の `name=` を省くとファイル名の幹が名前になります。パスに空白が入っても
よいように、**オプションは先頭に書き、残り全部をパスとして読みます。**

`kind` = `comp` | `num` | `bool` | `vid`。`#` 以降はコメント。

### 最小の例

```
name  Hello Doubler
desc  doubles channel 1
size  1 2
lua   hello.lua

in   num  0 0  In   | value to double
out  num  0 1  Out  ch=1 | doubled value
```

```lua
function onTick()
    output.setNumber(1, input.getNumber(1) * 2)
end
```

> `in num` と `out num` はどちらも「信号」枠なので**同じマスには置けません**。
> だから `size 1 2` にして `(0,0)` と `(0,1)` に分けています(§4)。

### `map` — 複数の composite を1本に合流させる

`role=base` を付けた composite を土台に、他の composite から ch を抜いて上書きします。
生成物は **Composite Read 群 + Composite Write の直列**です。

```
in  comp 0 0  Bus   role=base | 土台。ch1-16 はそのまま通る
in  comp 1 0  SrcA
in  comp 0 1  SrcB

map num  SrcA 1-6  -> 17-22
map num  SrcB 9-10 -> 29-30
map bool SrcB 1-5  -> 5-9
map bool SrcA 5    -> 10   delay=1
```

`ch範囲` は `5` か `1-6`。元と先は同じ本数にします。

**`map` の元に書けるもの**は3種類です。

| 元 | ch範囲 | 例 |
|---|---|---|
| `in comp` のラベル | **要る** | `map num SrcA 1-6 -> 17-22` |
| `in num` / `in bool` のラベル | **書かない**(値そのもの) | `map num Wind Speed -> 22` |
| lua ブロックの名前 | **要る** | `map num Stage1 1-3 -> 21-23` |
| `-`(ゼロ埋め) | **書かない** | `map bool - -> 13-14` |

**`map` の対象**は lua ブロックのほか、**composite の出力ノード**も書けます。
出力ノードを対象にすると、Lua の出力から ch を選んで**1本の composite に詰め直す**
回路が生成されます。合流先が2つ以上あるときだけ対象名が要ります。

```
out comp 0 1  Cue
map Cue num  Stage2 1-4 -> 1-4
map Cue bool Stage2 1   -> 1
map Cue bool -          -> 2      # ここは 0
map Cue bool Stage2 9   -> 3
```

`out comp` に `from=` も書くと、それが土台になってその上に重ねます。

同じ読み出しは使い回されるので、段をまたいで同じ ch を使っても部品は増えません。

- **`map` を1行も書かない**仕様ファイルでは、`in num`/`in bool` は宣言順に ch1 から
  自動で詰められます(従来どおり)。**`map` を書いたら、全部を明示してください。**
  暗黙と明示が混ざると、どの ch を誰が取るのか読めなくなるので止めます
- `map` も `base=` も使わない場合、`in comp` は1本までです

### 複数の Lua ブロック

**8192字の制限はスクリプトブロック単位**なので、2本の Lua を別ブロックのまま
同居させれば合計で超えても問題ありません。センサーの読み出し部品を両段で共有でき、
マイコンが1個減るぶん tick も縮みます。

```
lua  name=Stage1  First.lua
lua  name=Stage2  base=Stage1  Second.lua

map Stage1 num  Aux 1-3 -> 17-19      # 対象ブロック名が要る
map Stage2 num  Aux 1-3 -> 21-23      # 読み出しは Stage1 と共有される

out comp 0 1  Result  from=Stage2
out comp 1 1  Debug   from=Stage1     # 段の間を覗くタップ
```

`base=` に前の段の名前を書くと、その出力 composite を土台にできます。
**lua が複数あるとき、`map` には対象ブロック名が必須です。**
`out` の `from=` を省くと最後に宣言したブロックになります。

**lua ブロックと `out comp` が同じ名前なら、`map` の対象は lua 側です。**
その出力ノードへは `map` で詰め直せません。詰め直したいなら名前を分けてください。

---

## 3. `map` で必ず踏む2つの罠

### Composite Write はスパンを丸ごと書き潰す

**スパン内で繋がなかった ch は、素通りせず 0 になります**(実機検証済み)。
そのため **`map` は注入先が連続する塊ごとに Write を分けます。**

```
map num A 1-3 -> 17-19     # 塊1
map num B 7   -> 22        # 塊2 -> Write が別になる
```

これは自動なので間違えようがありませんが、**塊が増えるぶん段が増え、1段=1tick
遅れます。** 生成時に段数が出るので見てください。

**間を意図して 0 にしたいときは、元に `-` と書いてスパンに含めます。**
書かないとその ch は前段の値が素通りします。

```
map bool -   -> 9-11       # ここは 0 で潰す
map bool Per -> 12
map bool -   -> 13-14      # ここも 0。これで ch9-14 が1個の Write になる
```

**設計指針**: 上流の部品が使う ch 数を減らして、後ろ側に連続した空き領域を作り、そこへ注入する。
(例: レーダー部品は1目標あたり4ch 使うので、扱う目標数を1つ減らすごとに
4chの連続領域が空く)

### 合流段で位相がずれる

**ロジック部品は1個通るごとに1tick遅延します。** `map` は num の Write と bool の Write を
直列に繋ぐので、こうなります。

| | 遅延 |
|---|---|
| 土台(`role=base`)の ch | 同相 |
| 1段目の注入 | 同相 |
| **2段目以降の注入** | **1段ごとに1tick新しい** |

**対になっているデータが段をまたぐと、片方だけ先に届きます。** 「値が有効かを示す bool」と
「その値の num」が別の段に分かれるのが典型で、bool が立った最初の1tickだけ num が
前の値のまま、という状態が生まれます。

`delay=<n>` を付けると、その注入だけ素通し部品を `n` 個挟んで位相を揃えられます
(num は `Function (1 input)` の `e="x"`、bool は `Or` の片側未接続)。

---

## 4. 【重要】ノードの置き方

`x` は幅方向(0〜幅-1)、`z` は奥行方向(0〜奥行-1)。**マス目からはみ出したノードは、
エラーも出ないまま端子が消えます。**

同じマスは**型の区分ごとに1本ずつ**共有できます。

```
1マスに置けるもの: 信号(bool/num) 1本 + composite 1本 + video 1本 + audio 1本
```

- **入出力の向きは関係ありません。** composite入力と bool出力は同じマスに置けます
- **bool と num は別の型なのに干渉します。** 同じマスには置けません
- したがって `size 1 1` でも「composite入力1本 + bool出力1本」は成立します

---

## 5. 生成時に止まるもの

全部エラーで止まり、メッセージに理由が書いてあります。**エラーを回避しようとせず、
メッセージの指示に従ってください。** どれも実機で壊れた実績のある条件です。

1. ノードが盤面の外
2. 同じマスの同じ枠に2本
3. **すべてASCII** — マイコン名・ラベル・説明・**Luaの文字列リテラルとコメント**まで。
   Stormworks は2バイト文字を扱えません
4. **ノード説明は72字以内**
5. **composite の ch は 1〜32**
6. **圧縮後の Lua は 8192字以内**
7. `out num` / `out bool` に `ch=` が無い
8. `map` の注入先の重なり・本数違い・未宣言の入力ラベル・未宣言の対象名
9. **Stormworks に無い関数**(`select(`, `math.atan2(`, `screen.drawArc(`)

---

## 6. Lua を書くときの注意(Stormworksの実行環境)

- **Lua 5.3**。`math.atan2` と `table.maxn` は**存在しません**。2引数の `math.atan(y, x)` を使う
- `onTick()` の中で `screen.*` は呼べません。`onDraw()` の中で `input.*`/`output.*` は呼べません
- `input.getNumber` / `output.setNumber` のチャンネルは **1〜32** だけ。33以降は32に丸められます
- `screen.drawCircle` は**8角形近似**
- **未定義のプロパティは 0 を返します**(nil ではありません)。次の形が安全です:

```lua
function pn(n, d) local v = property.getNumber(n) if v == 0 then return d end return v end
win = pn("Window", 30)
```

`pn("名前", 既定値)` と書くと、**Property Number 部品が自動で置かれます。**
仕様ファイルに書く必要はありません。

より詳しい知見は [Stormworks-Reference](https://github.com/suzukurosaki616-debug/Stormworks-Reference)(MC Lua API と部品仕様の資料集)。
**`.lua` を書き終えたら、使った関数が実在するか、罠まとめに抵触していないか
突き合わせてください。**

---

## 7. 既存マイコンを読む / 書く

```python
import mcbench

mc = mcbench.load(path)          # .xml -> モデル
mc.name, mc.width, mc.length
mc.terminals                     # 外部端子(<nodes>)
mc.components                    # 内部の部品
mc.bridge                        # 端子の盤面上の実体(<components_bridge>)
mc.all_components()              # 上2つ。id を引くときは必ずこちら

for c in mc.components:
    c.id, c.type, c.attrib       # type は data/component_catalog.csv を引く
    for p in c.ports():
        p.name, p.link           # p.link.source = 供給元の component_id

xml = mcbench.dumps(mc)          # モデル -> .xml
mcbench.dump(mc, path)
```

```python
from mcbench.validate import validate
for issue in validate(mc):
    print(issue.level, issue.code, issue.message, issue.where)
```

### 知っておくこと

- **`component_id="0"` は「未接続」の番兵**です。参照切れではありません。
  モデルでは `p.link is None` に倒れます
- **`<components_bridge>` の `type` は部品カタログとは別体系**(端子の種別 0〜7)です。
  `component_catalog.csv` を引いてはいけません。対応は
  `並び順(bool0/num1/comp2/vid3) * 2 + (入力0 / 出力1)`
- **ゲームの `.xml` は規格準拠のXMLではありません。** 標準パーサに直接渡すと
  117個中30個が読めず、残りも Lua が壊れます。必ず `mcbench` 経由で読んでください
  (`mcbench.preprocess()` が吸収しています)
- 知らない要素・属性は `El` という袋に入れて素通しするので、**書き戻しても情報は落ちません**

---

## 8. 変更するときの決まり

### 部品の type 番号を推測で埋めない

`data/component_catalog.csv` は60部品すべて確定済みです。根拠は**ゲーム内エディタの
読み上げ**(一次資料)。`%APPDATA%/.../languages/jp.tsv` の `def_gate_*` は
**ビークル設置用のロジック部品であって、マイコン内部部品ではありません。**
名前が一部重なる(And, Or, Not…)ので、ここを混ぜて対応表を丸ごと間違えた前科があります。

### 検証規則はコーパスで較正する

`tools/lint.py --corpus` が**保存済みマイコンすべてで error 0**(作者の手元では143個、2026-11-22) になることを保てば、
規則が実機と食い違っていないことの担保になります。**実機で動いているファイルに error が
出たら、規則のほうが間違っている可能性を先に疑ってください。** 実際にそれで2件直っています。

### コーパスが黙っているところを推定で埋めない

116個では確かめられない規則があります(例: マスの共有規則は、端子が同居しているマスが
731マス中1件しか無く、複数の仮説を区別できませんでした)。**「コーパスと矛盾しない」は
「正しい」ではありません。** 確かめられないなら、確かめられないと書いてください。

### 読み書きを変えたら必ず往復テスト

```bash
python tools/roundtrip.py     # 作者の手元では 143/143 合格(2026-11-22)。1つでも落ちたら直すまで進まない
```

判定は**バイト一致ではなく**、①元の木と出力の木が等しい ②書き出しを読んで書くと
同じものが出る(不動点)、の2本です。捨ててよいものはホワイトリストに明示してあり、
**それ以外を落とすとテストが落ちます。**

---

## 9. 今できないこと

- ロジック部品(AND/PID/Timer 等)を任意のグラフとして組むこと
- GUI、サブアセンブリの保存展開、ライブ実行、diff

データ処理は Lua に寄せる前提の作りです。`map` が面倒を見るのは
**composite の合流と分配**だけで、演算は Lua の中でやります。

---

## 10. 中身

```
mccompile.py                仕様ファイル -> .xml のコンパイラ
mcbench/model.py            文書モデル
mcbench/mcxml.py            .xml の読み書き(ゲーム側の非準拠を吸収するのはここ)
mcbench/validate.py         検証規則
mcbench/make_mc.py          XML組み立てエンジン
data/component_catalog.csv  部品カタログ(60種、確定済み)
tools/roundtrip.py          自己往復テスト
tools/lint.py               検証のCLI
tools/extract_catalog.py    カタログをコーパスから再生成
tools/make_catalog_mc.py    type番号確認用のマイコンを生成
tools/mcb.py                .mcb バンドルの pack / install / sync / info
tools/selftest.py           全部まとめて確認(コーパスが無ければその項目は飛ばす)
tools/make_dist.py          配布用 zip を作る(展開して selftest まで通す)
mcbench/bundle.py           .mcb の読み書き
mcbench/vehicle.py          ビークルのセーブからプロパティ値を読む(--props-from)
mcbench/layout.py           ノードの自動配置
spec/example/               仕様ファイルの例
```

`mcbench/make_mc.py` は作者の別プロジェクト(`Obj 1872`)の生成スクリプトから、
汎用部分を 2026-08-31 に引き取ったものです。**実機で何度も壊れて直された実装なので、
書き換えるときは理由をコメントに残してください。**
