# -*- coding: utf-8 -*-
"""マイコンの文書モデル。

**設計の前提: ゲームのXMLが正。** MCBENCHはXMLを読み、編集し、同じ形で書き戻す。
階層(サブ回路)はモデルに持たない。持つとXMLへ書き出した時点で失われ、
ゲーム内エディタと往復できなくなるため。

**知らないものは捨てずに袋(El)に入れて持ち回る。** ゲームが将来属性や要素を
増やしても、こちらが黙って落とさないようにするため。落としてよいものは
`mcxml.py` のホワイトリストに明示されているものだけ。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


def fmt_num(v: float) -> str:
    """ゲームと同じ数値表記。6 は "6"、-0.25 は "-0.25"。"""
    s = "%.6f" % v
    s = s.rstrip("0").rstrip(".")
    return s if s not in ("", "-") else "0"


@dataclass
class El:
    """素性を解釈しない要素。属性と子をそのまま保持する。

    `<min text="0" value="0"/>` や `<items><i l=".."><v ../></i></items>` のような、
    部品ごとに意味が違う設定値をここで受ける。**部品ごとの知識を持たずに
    往復できる**ようにするのが狙い。
    """
    tag: str
    attrib: dict = field(default_factory=dict)
    children: list = field(default_factory=list)


@dataclass
class Link:
    """結線。**入力が供給元を指す**というStormworksのモデルそのまま。

    `index` は供給元の何本目の出力か(`node_index`)。0 は属性ごと省略される。
    """
    source: int
    index: int = 0


@dataclass
class Port:
    """部品の入出力端子。`in1` `in2` `out1` のほか `inc` `inoff` もある。

    **`component_id="0"` は「どこにも繋がっていない」を表す番兵。** 参照先が
    存在しないのではなく、未接続。保存済み116個に91件あって全部これだった。
    モデルでは `link=None` に倒し、書き出しで元の書き方を再現するために
    `null_id` を立てておく。
    """
    name: str
    link: Optional[Link] = None
    null_id: bool = False

    @property
    def is_input(self) -> bool:
        return self.name.startswith("in")


@dataclass
class Pos:
    x: float = 0.0
    y: float = 0.0


@dataclass
class Component:
    """マイコン内部の部品1個。

    `children` に Pos / Port / El を **ファイル上の順序のまま** 並べる。
    順序を保つのは、読んで書いたときにゲームの出力と一致させるため。
    """
    id: int
    type: int = 0
    attrib: dict = field(default_factory=dict)
    children: list = field(default_factory=list)

    @property
    def pos(self) -> Pos:
        for c in self.children:
            if isinstance(c, Pos):
                return c
        p = Pos()
        self.children.insert(0, p)
        return p

    def ports(self):
        return [c for c in self.children if isinstance(c, Port)]

    def port(self, name: str) -> Optional[Port]:
        for c in self.children:
            if isinstance(c, Port) and c.name == name:
                return c
        return None


@dataclass
class Terminal:
    """マイコンの外部端子(`<nodes>` の `<n>`)。

    `component_id` が指す先は、盤面に置かれた入出力部品。
    `node` は `<node label=.. type=.. mode=..>` をそのまま持つ袋で、
    中に `<position x y z/>` が入ることがある。
    """
    id: int
    component_id: int
    attrib: dict = field(default_factory=dict)
    node: Optional[El] = None


@dataclass
class Note:
    """キャンバスに浮かぶ付箋。**XMLには一切書き出さない。**

    部品には紐づけない(2026-08-30 合意)。紐づけないので、ゲーム内で何をされても
    迷子にならない。座標は部品と同じ空間。
    """
    id: int
    x: float = 0.0
    y: float = 0.0
    w: float = 6.0
    h: float = 3.0
    text: str = ""


@dataclass
class Microprocessor:
    name: str = ""
    # None は「属性そのものが無い」。空文字列("")とは区別する
    description: Optional[str] = None
    width: int = 1
    length: int = 1
    attrib: dict = field(default_factory=dict)   # sym0..15 / transform_index など
    terminals: list = field(default_factory=list)
    components: list = field(default_factory=list)
    # <components_bridge> にある、外部端子の盤面上の実体。
    # **`type` は部品カタログとは別体系**(端子の種別を表す 0〜7)。
    # `data/component_catalog.csv` を引いてはいけない。
    bridge: list = field(default_factory=list)
    data: Optional[El] = None                    # <data><inputs/><outputs/></data>
    group_attrib: dict = field(default_factory=dict)  # <group id="0"> がある
    group_extra: list = field(default_factory=list)  # components_bridge / groups
    notes: list = field(default_factory=list)    # MCBENCH側だけ

    def all_components(self):
        """盤面上の部品すべて。結線の参照先は bridge にもあるので、
        id を引くときは必ずこちらを使う。"""
        return self.components + self.bridge

    def by_id(self, cid: int) -> Optional[Component]:
        for c in self.all_components():
            if c.id == cid:
                return c
        return None

    def next_component_id(self) -> int:
        ids = [c.id for c in self.all_components()]
        return max(ids) + 1 if ids else 1

    def next_terminal_id(self) -> int:
        return max([t.id for t in self.terminals], default=0) + 1
