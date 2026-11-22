# 後続のブロックから上流へデータを戻す例(フィードバック)。
#
# `map` と `base=` は**宣言順に縛られない**。後ろで宣言したブロックを前のブロックが
# 参照してよい。マイコンを分けずに「下流の結果を上流へ返す」構成が書ける。
#
# 【重要】後方参照した値は**前tickのもの**になる。ロジック部品はどれも1tick遅延するので、
# 閉路は「1tick遅れの戻り」として素直に成立する。生成時に後方参照の一覧が出るので確認すること。
#
# 閉路がゲームで動くことは確認済み: 保存済みマイコン122個のうち16個が閉路を含んでいて、
# いずれも実機で動いている(Function が自分の入力に戻る蓄積器が定番)。

name  MCBENCH Feedback
icon  9902 C
desc  demo of a downstream block feeding back upstream
size  2 2
lua   name=Stage1  Combiner.lua
lua   name=Stage2  base=Stage1  Averager.lua

in  comp 0 0  Bus  role=base | Base composite

# 第1段は土台に加えて、**第2段(後で宣言)の出力**を読む。これが戻り。
map Stage1 num Bus    1-3 -> 17-19
map Stage1 num Stage2 1-2 -> 21-22

# 第2段は第1段の出力を土台にして、その上に自分の入力を重ねる
map Stage2 num Bus 1-3 -> 21-23

out comp 1 1  Out    from=Stage2 | Output of the last stage
out comp 0 1  Inner  from=Stage1 | Tap between the stages
