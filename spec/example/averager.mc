# 数値/bool の入出力を使う例。
# 入力の num/bool は composite に詰めてから Lua に渡され、
# 出力の num/bool は Lua の composite 出力から ch= で取り出される。
#
# 【注意】マス目は **型の区分ごとに1本ずつ**共有できる。入出力の向きは関係しない。
#   信号(bool/number) 1本 + composite 1本 + video 1本 + audio 1本 = 1マスに最大4本
# bool と number は別の型なのに干渉するので、同じマスに同居できない。
# ここは 2x2 = 4マスに信号4本(num2 + bool2)なので、ちょうど埋まっている。
name  MCBENCH Averager
icon  9902 A
desc  rolling average with deviation tap
size  2 2
lua   Averager.lua

in   num  0 0  Signal    | The value to average
in   bool 1 0  Arm       | Enables the ready output

out  num  0 1  Average   ch=1  | Rolling mean
out  num  1 1  Deviation ch=2  | Input minus mean
