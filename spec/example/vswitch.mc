# Video Switchbox (type 57) の例。2つの Lua の映像を切り替え、切り替えた後の映像に
# 3つ目の Lua を重ねて出す(PPI / リスト / 状態表示の構成を縮めたもの)。
#
#   switch vid <名前> on=<映像> off=<映像> sel=<bool の供給元>
#
# on= / off= に書けるのは 映像入力のラベル / lua の名前(その映像出力)/ 映像 switch の名前。
# 名前は out vid の from= と、lua 行の vid= に書ける。
# **ON 側が in1 なのは未検証**(Composite Switchbox からの類推)。

name  MCBENCH VSwitch
icon  9902 I
desc  video switchbox between two Lua screens, overlay on the result
size  2 2
lua   name=PPI      Combiner.lua
lua   name=List     Combiner.lua
lua   name=Overlay  vid=Screen  Combiner.lua

in  comp 0 0  Bus  role=base | Base composite
in  vid  1 0  Cam  to=PPI    | camera under the PPI
in  bool 0 0  Mode           | on = list page

map PPI     bool Mode -> 1
map List    bool Mode -> 1
map Overlay bool Mode -> 1

switch vid Screen on=List off=PPI sel=Mode
switch vid Raw    on=Cam  off=PPI sel=Mode

out vid 0 1  Monitor  from=Overlay | switched screen with the overlay on top
out vid 1 1  Direct   from=Raw     | switched without overlay
