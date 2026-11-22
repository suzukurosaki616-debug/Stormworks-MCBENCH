"""ノードの自動配置(2026-09-28 合意)。

規則:
  * x z を書いたノードはそこに固定。書かないノードだけ自動で置く
  * `group=名前` のノードは矩形ブロックにまとめる。`group=名前:WxH` で形を固定できる
  * ブロックの中は左上から右へ、書いた順。区分(信号/comp/vid/audio)ごとに数えるので、
    区分違いのノードは同じマスの別の段に重なる(LidarD1 と LidarP1 が同じマス)
  * ブロックの余りマスに別グループは入れない。単独ノードは入れてよい
  * 形の自動選択: ブロック内の空きマス最小 → 正方形寄り
  * 大きさ: `size W L` 固定 / `size auto` 面積最小 → 正方形寄り / `size auto w=5` 幅固定で奥行き最小
  * 入らなければ止めて、区分ごとの数を示す

1マスに置けるのは区分ごとに1本(§2.3b)。区分は make_mc.SLOT_CLASS と同じ。
"""

SLOT_CLASS = {"bool": "signal", "num": "signal", "comp": "comp",
              "vid": "vid", "audio": "audio"}
MAX_SIDE = 6   # size auto default: the in-game editor max. Bigger only with max=


def _cls(kind):
    return SLOT_CLASS.get(kind, "signal")


def _shapes(need, fixed=None):
    """グループの形の候補を優先順に返す。"""
    if fixed:
        return [fixed]
    out = []
    for w in range(1, need + 1):
        h = -(-need // w)
        waste = w * h - need
        # 丸ごと空いた行・列ができる形は候補にしない
        if waste >= w or waste >= h:
            continue
        out.append((waste, abs(w - h), -w, (w, h)))
    return [s for *_, s in sorted(out)]


def _sizes(size, width, need, top):
    """試す (W, L) を優先順に返す。"""
    if size:
        return [size]
    ws = [width] if width else range(1, top + 1)
    cand = [(w * l, abs(w - l), -w, (w, l))
            for w in ws for l in range(1, top + 1) if w * l >= need]
    return [s for *_, s in sorted(cand)]


def place(nodes, size=None, width=None, top=MAX_SIDE):
    """nodes: [dict(kind, x, z, group, shape)] 宣言順。x z が None のものを埋める。

    group は None か名前、shape は None か (w, h)。
    返り値: ((W, L), [(x, z), ...] nodes と同じ順)。入らなければ ValueError。
    """
    groups = {}          # 名前 -> [ノード番号] 宣言順
    shape = {}
    for i, n in enumerate(nodes):
        g = n.get("group")
        if g is None:
            continue
        if n["x"] is not None:
            raise ValueError("%s: group= のノードに x z は書けません" % g)
        groups.setdefault(g, []).append(i)
        if n.get("shape"):
            if shape.get(g, n["shape"]) != n["shape"]:
                raise ValueError("group %s の形の指定が食い違っています" % g)
            shape[g] = n["shape"]

    # グループ内の区分ごとの並び順 -> ブロック内のセル番号
    slot = {}
    need = {}
    for g, idx in groups.items():
        seen = {}
        for i in idx:
            c = _cls(nodes[i]["kind"])
            slot[i] = seen.get(c, 0)
            seen[c] = slot[i] + 1
        need[g] = max(seen.values())
        s = shape.get(g)
        if s and s[0] * s[1] < need[g]:
            raise ValueError("group %s は %d マス要るのに %dx%d が指定されています"
                             % (g, need[g], s[0], s[1]))

    count = {}
    for n in nodes:
        count[_cls(n["kind"])] = count.get(_cls(n["kind"]), 0) + 1
    lower = max(count.values()) if count else 1

    order = sorted(groups, key=lambda g: -need[g])   # 大きいグループから
    cands = {g: _shapes(need[g], shape.get(g)) for g in groups}

    if width and width > top:
        raise ValueError("w=%d は上限 %d を超えます。max= で上限を上げてください" % (width, top))
    for W, L in _sizes(size, width, lower, top):
        res = _try(nodes, W, L, groups, order, cands, slot)
        if res:
            return (W, L), res
    if size:
        where = "%dx%d" % size
    elif width:
        where = "幅 %d(奥行き %d まで)" % (width, top)
    else:
        where = "%dx%d まで" % (top, top)
    raise ValueError("%s に収まりません。区分ごとのノード数: %s" % (
        where, ", ".join("%s %d" % kv for kv in sorted(count.items()))))


def _try(nodes, W, L, groups, order, cands, slot):
    used = {}            # 区分 -> set((x, z))
    pos = [None] * len(nodes)
    for i, n in enumerate(nodes):
        if n["x"] is None:
            continue
        x, z = n["x"], n["z"]
        if not (0 <= x < W and 0 <= z < L):
            return None
        s = used.setdefault(_cls(n["kind"]), set())
        if (x, z) in s:
            return None
        s.add((x, z))
        pos[i] = (x, z)

    reserved = set()     # 他グループが使えないマス

    def put(k):
        if k == len(order):
            return True
        g = order[k]
        for w, h in cands[g]:
            if w > W or h > L:
                continue
            for z0 in range(L - h + 1):
                for x0 in range(W - w + 1):
                    block = {(x0 + dx, z0 + dz) for dz in range(h) for dx in range(w)}
                    if block & reserved:
                        continue
                    cells = []
                    for i in groups[g]:
                        c = slot[i]
                        cell = (x0 + c % w, z0 + c // w)
                        if cell in used.get(_cls(nodes[i]["kind"]), ()):
                            break
                        cells.append((i, cell))
                    else:
                        for i, cell in cells:
                            used.setdefault(_cls(nodes[i]["kind"]), set()).add(cell)
                            pos[i] = cell
                        reserved.update(block)
                        if put(k + 1):
                            return True
                        reserved.difference_update(block)
                        for i, cell in cells:
                            used[_cls(nodes[i]["kind"])].discard(cell)
                            pos[i] = None
        return False

    if not put(0):
        return None

    # 単独ノード: 空いているマスへ左上から
    for i, n in enumerate(nodes):
        if pos[i] is not None:
            continue
        s = used.setdefault(_cls(n["kind"]), set())
        free = [(x, z) for z in range(L) for x in range(W) if (x, z) not in s]
        if not free:
            return None
        s.add(free[0])
        pos[i] = free[0]
    return pos
