# 出力側の合流・飛び飛びの注入・明示的なゼロ埋め・プロパティ上書きの例。
#
# `map` の対象には lua ブロックのほか、**composite の出力ノード**も書ける。
# 出力ノードを対象にすると、Lua の出力から ch を選んで1本の composite に詰め直す
# 回路が生成される(ゲーム内で手で組むと部品が並ぶところ)。
#
# 注入先が飛び飛びのときは、**連続する塊ごとに Composite Write が分かれる。**
# 1個の Write でまたぐと間の ch が黙って 0 になるため。塊が増えるぶん tick も増える
# ので、生成時に段数が表示される。
#
# 間を意図して 0 にしたいときは、元に `-` と書いてスパンに含める。
# これを書かないと、その ch は前段の値が素通りする。

name  MCBENCH PackOut
icon  9902 D
desc  output-side packing, scattered injection, explicit zero fill
size  2 2
lua   Combiner.lua

prop  Search only  true

in  comp 0 0  Bus  role=base | Base composite
in  comp 1 0  Aux            | Everything else comes from here

# --- 入力側。ch17-19 と ch24 は離れているので Write が2段に分かれる
map Combiner num  Aux 1-3 -> 17-19
map Combiner num  Aux 7   -> 24

# --- bool9-14 のうち、値を入れるのは ch12 だけ。残りは明示的に 0 で潰す
map Combiner bool -       -> 9-11
map Combiner bool Aux 1   -> 12
map Combiner bool -       -> 13-14

# --- 出力側。Lua の出力から選んで1本に詰め直す
out comp 0 1  Cue | packed composite built from the Lua output

map Cue num  Combiner 1-4 -> 1-4
map Cue bool Combiner 1   -> 1
map Cue bool -            -> 2
map Cue bool Combiner 9   -> 3

out comp 1 1  Raw | the Lua output as-is, for comparison
