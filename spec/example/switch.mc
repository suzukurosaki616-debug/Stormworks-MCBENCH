# Composite Switchbox (type 53) の例。武器用 / センサー用の素通しを
# パイロンごとに切り替える構成を縮めたもの。
#
#   switch <名前> on=<composite> off=<composite> sel=<bool の供給元>
#
# sel が on のとき on=、off のとき off= を通す。**通過は1tick。**
# sel= は map の供給元と同じ書き方: bool 入力のラベルか、`<lua名> <ch>`。
# lua の出力から取るときは Composite Read が1個挟まるので、sel 側はさらに1tick遅れる。
# スイッチの名前は out の from=、lua の base=、map の供給元に書ける。
#
# out の from= には入力 composite のラベルも書ける(Pass をそのまま出す例が Raw)。

name  MCBENCH Switch
icon  9902 H
desc  composite switchbox per lane, selected by Lua output or a bool input
size  3 2
lua   Combiner.lua

in  comp 0 0  Pass    role=base | weapon lane
in  comp 1 0  Sensor            | sensor lane
in  bool 0 0  Force             | force lane 2 to sensor

switch Lane1 on=Sensor off=Pass sel=Combiner 1
switch Lane2 on=Sensor off=Pass sel=Force

map Combiner bool Force -> 1

out comp 0 1  Down1  from=Lane1 | lane 1, plus one bool from the Lua on top
out comp 1 1  Down2  from=Lane2 | lane 2 as-is
out comp 2 1  Raw    from=Pass  | the input composite passed straight through

map Down1 bool Combiner 2 -> 30
