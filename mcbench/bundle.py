# -*- coding: utf-8 -*-
"""`.mcb` バンドル — マイコン1個ぶんを1ファイルにまとめる共有形式。

**バンドルは容器であって、ゲームのXMLのライバル形式ではない。** 中に
**ゲームが書いた `.xml` をそのまま丸ごと**抱える。だから「XMLが正」は保たれたまま、
共有は1ファイルで済む。

  ゲームから取り込む = `[xml]` を差し替える。付箋はそのまま残る
  ゲームへ出す       = `[xml]` をマイコンフォルダに書き出す

## 形式

```
MCBENCH-BUNDLE 1
name: MCBENCH Averager

[note 1]
x: 4
y: -2
w: 6
h: 3
text:
  付箋の本文
  複数行も書ける

[xml]
<?xml version="1.0" encoding="UTF-8"?>
...
```

- **`[xml]` は必ず最後。** そこから先は行末まで全部XMLとして扱う。
  Lua の中に `[xml]` という行が現れても壊れないのはこのため
- **知らないセクションはそのまま持ち回る。** 後から台帳などを足したバンドルを
  古い版で開いても、黙って落とさない
- テキストは2スペース字下げ。字下げが切れたところで終わり
"""
from __future__ import annotations

import io
import re

from .model import Note
from . import mcxml

MAGIC = "MCBENCH-BUNDLE"
VERSION = 1
XML_SECTION = "[xml]"

_SECTION = re.compile(r"^\[([^\]]+)\]\s*$")


class Bundle(object):
    """`.mcb` の中身。"""

    def __init__(self, xml="", meta=None, notes=None, extra=None):
        self.xml = xml
        self.meta = dict(meta or {})
        self.notes = list(notes or [])
        # 知らないセクション。(見出し, 本文行のリスト) を順序のまま持つ
        self.extra = list(extra or [])

    def microprocessor(self):
        """抱えているXMLをモデルにして返す。"""
        return mcxml.loads(self.xml)

    def next_note_id(self):
        return max([n.id for n in self.notes], default=0) + 1


def _parse_note(header, lines):
    m = re.match(r"^note\s+(\d+)$", header)
    if not m:
        raise ValueError("付箋の見出しが読めない: [%s]" % header)
    n = Note(id=int(m.group(1)))
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("text:"):
            body = []
            i += 1
            while i < len(lines) and (lines[i].startswith("  ") or not lines[i].strip()):
                body.append(lines[i][2:])
                i += 1
            # 末尾の空行は落とす(セクション間の空行を巻き込まないため)
            while body and not body[-1].strip():
                body.pop()
            n.text = "\n".join(body)
            continue
        if ":" in line:
            k, _, v = line.partition(":")
            k, v = k.strip(), v.strip()
            if k in ("x", "y", "w", "h"):
                try:
                    setattr(n, k, float(v))
                except ValueError:
                    raise ValueError("付箋 %d の %s が数値でない: %r" % (n.id, k, v))
        i += 1
    return n


def loads(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    head, _, rest = text.partition("\n")
    parts = head.split()
    if not parts or parts[0] != MAGIC:
        raise ValueError("先頭行が %s ではない。.mcb ではないかもしれない" % MAGIC)
    try:
        ver = int(parts[1])
    except (IndexError, ValueError):
        raise ValueError("先頭行に版番号がない: %r" % head)
    if ver > VERSION:
        raise ValueError("版 %d のバンドル。このツールが読めるのは %d まで" % (ver, VERSION))

    # **[xml] から先は丸ごとXML。** 最初に見つかったところで切る。
    idx = rest.find("\n" + XML_SECTION + "\n")
    if rest.startswith(XML_SECTION + "\n"):
        before, xml = "", rest[len(XML_SECTION) + 1:]
    elif idx >= 0:
        before, xml = rest[:idx], rest[idx + len(XML_SECTION) + 2:]
    else:
        raise ValueError("%s のセクションがない" % XML_SECTION)

    b = Bundle(xml=xml)
    cur_head, cur_lines = None, []

    def flush():
        if cur_head is None:
            return
        # セクション間の空行を本文に巻き込むと、書き出すたびに空行が増えて
        # 不動点にならない。末尾の空行はここで落とす。
        while cur_lines and not cur_lines[-1].strip():
            cur_lines.pop()
        if cur_head.startswith("note "):
            b.notes.append(_parse_note(cur_head, cur_lines))
        else:
            b.extra.append((cur_head, list(cur_lines)))

    for line in before.split("\n"):
        m = _SECTION.match(line)
        if m:
            flush()
            cur_head, cur_lines = m.group(1), []
            continue
        if cur_head is None:
            if ":" in line:
                k, _, v = line.partition(":")
                b.meta[k.strip()] = v.strip()
        else:
            cur_lines.append(line)
    flush()
    return b


def dumps(b):
    out = ["%s %d" % (MAGIC, VERSION)]
    for k, v in b.meta.items():
        out.append("%s: %s" % (k, v))
    for n in b.notes:
        out.append("")
        out.append("[note %d]" % n.id)
        for k in ("x", "y", "w", "h"):
            out.append("%s: %s" % (k, _num(getattr(n, k))))
        out.append("text:")
        for line in (n.text or "").split("\n"):
            out.append(("  " + line).rstrip())
    for head, lines in b.extra:
        out.append("")
        out.append("[%s]" % head)
        out.extend(lines)
    out.append("")
    out.append(XML_SECTION)
    xml = b.xml if b.xml.endswith("\n") else b.xml + "\n"
    return "\n".join(out) + "\n" + xml


def _num(v):
    s = "%.6f" % float(v)
    s = s.rstrip("0").rstrip(".")
    return s if s not in ("", "-") else "0"


def load(path):
    return loads(io.open(path, encoding="utf-8", errors="replace").read())


def dump(b, path):
    io.open(path, "w", encoding="utf-8", newline="\n").write(dumps(b))


def from_xml(path_or_text, name=None):
    """`.xml` を1個くるんだバンドルを作る。"""
    text = path_or_text
    if "\n" not in text and text.lower().endswith(".xml"):
        text = io.open(text, encoding="utf-8", errors="replace").read()
    b = Bundle(xml=text)
    if name is None:
        try:
            name = mcxml.loads(text).name
        except Exception:
            name = ""
    if name:
        b.meta["name"] = name
    return b
