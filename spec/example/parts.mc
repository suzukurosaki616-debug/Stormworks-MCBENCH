# part / wire / tip の例(2026-11-03)。
#
#   part <名前> type=<番号> [<属性>=<値> ...]   カタログの部品をそのまま置く
#   wire <部品名> <端子> [num|bool] <供給元>    端子へつなぐ。composite の ch から読むときだけ型を書く
#   tip  num|bool <供給元> [on= off=] | <見出し>  ツールチップ(ビークル上でカーソルを当てると見える)
#
# 部品の名前はその部品の out1 を指し、map の供給元や out の from= に書ける。
# 端子の本数はカタログから引く。属性は書いたものだけ付く(省略時にゲームが補うかは未検証)。
# Lua で書けることを部品にしても速くはならない(どちらも1tick)。Lua の 8192 字を
# 節約したいときと、Lua からはできないこと(ツールチップ)に使う。

name  MCBENCH Parts
icon  9902 J
desc  catalog parts placed by part/wire, plus tooltips
size  2 2
lua   Combiner.lua

in  comp 0 0  Bus  role=base | Base composite
in  bool 1 0  Arm            | arm switch

# Memory Register: in1 = set, in2 = reset, in3 = value
part Hold  type=13
wire Hold in1 Arm
wire Hold in2 bool Combiner 2
wire Hold in3 num  Bus 5

map Combiner num Hold -> 1
map Combiner bool Arm -> 1

out num  0 1  Held  from=Hold | held value
out bool 1 1  Armed from=Arm  | the arm switch passed through

tip num  Hold            | Held value
tip num  Combiner 1      | Lua out num1
tip bool Arm on=ARMED off=safe | Arm
