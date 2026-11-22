# 1つのマイコンに Lua ブロックを2つ載せる例。
#
# 8192字の制限は**スクリプトブロック単位**なので、2本のLuaを別ブロックのまま
# 同居させれば合計で超えても問題にならない。センサーの読み出し部品を両段で
# 共有できるのと、マイコンが1個減るぶんtickが縮むのが利点。
#
# 段の繋ぎ方は `lua ... base=<前の段の名前>`。前の段の出力 composite を土台にして、
# その上に次の段が必要とする値を重ねる。map の対象はブロック名で指定する。
#
# ここではマスの共有も見せている。1マスに 信号1本 + composite1本 まで置けるので、
# ノード7本が 2x2 = 4マスに収まっている。

name  MCBENCH TwoStage
icon  9902 E
desc  demo of two Lua blocks in one microcontroller
size  2 2

lua  name=Stage1  Combiner.lua
lua  name=Stage2  base=Stage1  Averager.lua

in   comp 0 0  Bus   role=base | Base composite for the first stage
in   comp 1 0  Aux             | Extra source read by both stages
in   num  0 0  Gain            | Scalar node used as a map source
in   bool 1 0  Arm             | Scalar node used as a map source

# 第1段: Bus を土台に、Aux と Gain を重ねる
map Stage1 num  Aux  1-3 -> 17-19
map Stage1 num  Gain     -> 20
map Stage1 bool Aux  1-2 -> 5-6
map Stage1 bool Arm      -> 7

# 第2段: Stage1 の出力を土台に、Aux の別の ch を重ねる
# Aux 1-3 の読み出しは第1段と共有され、部品は増えない
map Stage2 num  Aux  1-3 -> 21-23
map Stage2 bool Arm      -> 8

out  comp 0 1  Result  from=Stage2 | final composite
out  comp 1 1  Debug   from=Stage1 | tap between the stages
out  num  0 1  Value   ch=1 from=Stage2 | a number from the second stage
out  bool 1 1  Ready   ch=1 from=Stage1 | a flag from the first stage
