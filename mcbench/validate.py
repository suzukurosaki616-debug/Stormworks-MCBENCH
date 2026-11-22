# -*- coding: utf-8 -*-
"""検証。**外部でビルドする以上、実機で落ちる条件を機械的に止める。**

規則は保存済み116個で当たりを取ってある。**実機で動いているファイルに error が
出るなら、規則のほうが間違っている。** 追加・変更したら必ず `tools/lint.py` を
全数に掛けて、error が増えていないことを確かめること。
"""
from __future__ import annotations

import collections
import csv
import io
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CATALOG = os.path.join(os.path.dirname(HERE), "data", "component_catalog.csv")

# 端子のデータ型 → 並び順。<components_bridge> の type はここから決まる。
# bridge = 並び順*2 + (入力なら0 / 出力なら1)。保存済み732端子すべてで一致した。
DTYPE_ORDER = {0: 0, 1: 1, 5: 2, 6: 3}
DTYPE_NAME = {0: "bool", 1: "number", 5: "composite", 6: "video", 7: "audio"}

# 1マスに同居できるかを決める区分。**別の区分どうしは同じマスに置ける。**
# bool と number だけは別の型なのに干渉するので、同じ区分に入れる(ユーザー確認)。
# 入出力の向きは関係しない。したがって1マスの容量は
#   信号(bool/number) 1本 + composite 1本 + video 1本 + audio 1本。
# **保存済み116個では区別がつかなかった**(同居しているマスが1件しか無く、
# それは面も型も両方違うので「面ごと」説とも矛盾しない)。実機の挙動を採用している。
SLOT_CLASS = {0: "signal", 1: "signal", 5: "composite", 6: "video", 7: "audio"}

DESC_MAX = 72      # 保存済み116個の最長がちょうど72。150字で実機が落ちるのを確認済み
LUA_MAX = 8192     # 圧縮後の上限
COMPOSITE_CH = 32

LUA_TYPE = 56
CWRITE_TYPES = (40, 41)   # count/offset を持つ 32ch 一括書き込み


class Issue(object):
    __slots__ = ("level", "code", "message", "where")

    def __init__(self, level, code, message, where=""):
        self.level, self.code, self.message, self.where = level, code, message, where

    def __repr__(self):
        w = " [%s]" % self.where if self.where else ""
        return "%-5s %-14s %s%s" % (self.level, self.code, self.message, w)


def load_catalog():
    try:
        rows = list(csv.DictReader(io.open(CATALOG, encoding="utf-8-sig")))
    except OSError:
        return {}
    out = {}
    for r in rows:
        out[int(r["type"])] = (r["name"], int(r["inputs"] or 0), int(r["outputs"] or 0))
    return out


def _position(node):
    if node is None:
        return {}
    for k in node.children:
        if k.tag == "position":
            return k.attrib
    return {}


def _num(d, k):
    try:
        return float(d.get(k, 0) or 0)
    except ValueError:
        return 0.0


def validate(mc):
    """Issue のリストを返す。level は "error" か "warn"。"""
    out = []
    cat = load_catalog()

    def err(code, msg, where=""):
        out.append(Issue("error", code, msg, where))

    def warn(code, msg, where=""):
        out.append(Issue("warn", code, msg, where))

    # ---------------------------------------------------------- 外部端子
    bridge = dict((c.id, c) for c in mc.bridge)
    seen = collections.defaultdict(dict)
    for t in mc.terminals:
        n = t.node
        label = (n.attrib.get("label", "") if n else "") or ("端子 id=%d" % t.id)
        if n is None:
            err("TERM-NONODE", "<node> が無い", label)
            continue
        desc = n.attrib.get("description", "")
        if len(desc) > DESC_MAX:
            err("DESC-LEN", "説明が %d 字。%d 字を超えると実機が落ちる"
                % (len(desc), DESC_MAX), label)
        for name, s in (("ラベル", n.attrib.get("label", "")), ("説明", desc)):
            if any(ord(ch) > 127 for ch in s):
                err("NONASCII", "%sに非ASCII文字。端子が選択できなくなる" % name, label)

        pos = _position(n)
        x, y, z = _num(pos, "x"), _num(pos, "y"), _num(pos, "z")
        if y:
            err("TERM-Y", "y=%g。端子面は x-z 平面で、y は必ず 0" % y, label)
        if not (0 <= x < mc.width and 0 <= z < mc.length):
            err("TERM-OUT", "位置 (%g,%g) が盤面 %dx%d の外。エラーも出ずに端子が消える"
                % (x, z, mc.width, mc.length), label)
        mode = n.attrib.get("mode", "0")
        face = "入力" if mode == "1" else "出力"
        dt = int(n.attrib.get("type", 0) or 0)
        cls = SLOT_CLASS.get(dt, "signal")
        key = (x, z)
        if key in seen[cls]:
            err("TERM-DUP", "(%g,%g) で %s と重なっている(%s枠は1マスに1本)"
                % (x, z, seen[cls][key], "信号(bool/number)" if cls == "signal" else cls),
                label)
        seen[cls][key] = label

        # 端子の実体が <components_bridge> にあるか、型が合っているか
        b = bridge.get(t.component_id)
        if b is None:
            err("TERM-NOBRIDGE",
                "component_id=%d の実体が <components_bridge> に無い" % t.component_id,
                label)
        else:
            if dt not in DTYPE_ORDER:
                warn("TERM-DTYPE", "見たことのないデータ型 %d" % dt, label)
            else:
                want = DTYPE_ORDER[dt] * 2 + (0 if mode == "1" else 1)
                if b.type != want:
                    err("TERM-BRIDGE",
                        "%s の %s なら bridge type=%d のはずだが %d"
                        % (DTYPE_NAME[dt], face, want, b.type), label)

    # ---------------------------------------------------------- 部品と結線
    ids = set(c.id for c in mc.all_components())
    counts = collections.Counter(c.id for c in mc.all_components())
    for i in sorted(k for k, n in counts.items() if n > 1):
        err("ID-DUP", "component_id=%d が重複している" % i)

    for c in mc.components:
        who = "%s id=%d" % (cat.get(c.type, ("type%d" % c.type,))[0], c.id)
        if c.type not in cat:
            warn("UNKNOWN-TYPE", "カタログに無い type=%d" % c.type, who)
        for p in c.ports():
            if not p.is_input:
                continue
            if p.link is None:
                warn("IN-OPEN", "%s が未接続" % p.name, who)
            elif p.link.source not in ids:
                err("LINK-DEAD", "%s の接続先 component_id=%d が存在しない"
                    % (p.name, p.link.source), who)

        if c.type == LUA_TYPE:
            script = c.attrib.get("script", "")
            if len(script) > LUA_MAX:
                err("LUA-LEN", "スクリプトが %d 字。上限 %d 字"
                    % (len(script), LUA_MAX), who)
        if c.type in CWRITE_TYPES:
            try:
                count = int(c.attrib.get("count", 1) or 1)
                offset = int(c.attrib.get("offset", 0) or 0)
            except ValueError:
                continue
            # offset=-1 は「位置を inoff 入力から取る」動的指定。範囲は実行時に決まる
            if offset == -1:
                if not any(p.name == "inoff" and p.link for p in c.ports()):
                    err("CH-DYNAMIC", "offset=-1 (動的)なのに inoff が未接続", who)
                continue
            if offset < 0 or count < 1 or offset + count > COMPOSITE_CH:
                err("CH-RANGE", "ch %d〜%d は composite の 1〜%d に収まらない"
                    % (offset + 1, offset + count, COMPOSITE_CH), who)

    return out


def summary(issues):
    n = collections.Counter(i.level for i in issues)
    return "error %d / warn %d" % (n["error"], n["warn"])
