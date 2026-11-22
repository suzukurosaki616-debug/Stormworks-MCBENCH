# map 行(コンバイナー)の例。
#
# 複数の composite 入力から ch を選んで、base の composite に上書きしていく。
# 生成物は Composite Read 群 + Composite Write の直列。
#
# 【重要】注入先は連続していること。Composite Write はスパン内の未接続 ch を
# 素通しではなく 0 で埋めるので(実機検証済み)、穴があるとそこが 0 になる。
# 穴があればコンパイルが止まる。
#
# 【重要】部品1個につき1tick遅延する。base と1段目(num)の注入は同相だが、
# 2段目(bool)の注入だけ1tick新しく届く。対になっているデータが段をまたぐ場合は
# delay= で位相を揃えること。ここでは Select flag を num と揃えている。

name  MCBENCH Combiner
icon  9902 B
desc  demo of the map (combiner) directive
size  2 2
lua   Combiner.lua

in  comp 0 0  Base   role=base | Base composite. ch1-16 pass through untouched
in  comp 1 0  Pos         | Source of the XYZ triplet
in  comp 0 1  Aux         | Extra number plus the flags

map num  Pos  1-3  -> 17-19
map num  Aux  7    -> 20
map bool Aux  1-2  -> 5-6
map bool Aux  9    -> 7    delay=1

out comp 1 1  Out | base with the merged channels, plus the Lua results
