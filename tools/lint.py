# -*- coding: utf-8 -*-
"""マイコンXMLを検証する。

  python tools/lint.py FILE...        指定したファイルを検証
  python tools/lint.py --corpus       保存済みマイコン全部に掛ける(規則の当たり取り)
  python tools/lint.py --corpus -w    warn も出す

**保存済みのファイルは実機で動いている。** そこに error が出たら、規則のほうが
間違っている可能性を先に疑うこと。
"""
from __future__ import annotations

import argparse
import collections
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcbench import load  # noqa: E402
from mcbench.validate import validate  # noqa: E402

APPMC = os.path.expandvars(r"%APPDATA%\Stormworks\data\microprocessors")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*")
    ap.add_argument("--corpus", action="store_true", help="保存済みマイコン全部")
    ap.add_argument("-w", "--warn", action="store_true", help="warn も出す")
    a = ap.parse_args()

    files = list(a.files)
    if a.corpus:
        files += [p for p in sorted(glob.glob(os.path.join(APPMC, "*.xml")))
                  if not os.path.basename(p).startswith("MCBENCH")]
    if not files:
        ap.error("ファイルを指定するか --corpus を付ける")

    codes = collections.Counter()
    nerr = nfile = 0
    for p in files:
        try:
            issues = validate(load(p))
        except Exception as e:
            print("%s: 読めない (%s: %s)" % (os.path.basename(p), type(e).__name__, e))
            nerr += 1
            continue
        show = [i for i in issues if a.warn or i.level == "error"]
        for i in issues:
            codes[(i.level, i.code)] += 1
        if show:
            nfile += 1
            print("")
            print("=== %s" % os.path.basename(p))
            for i in show[:30]:
                print("  %r" % i)
            if len(show) > 30:
                print("  ... 他 %d 件" % (len(show) - 30))
        nerr += sum(1 for i in issues if i.level == "error")

    print("")
    print("%d ファイル / 指摘のあったファイル %d / error %d" % (len(files), nfile, nerr))
    for (lv, code), n in codes.most_common():
        print("   %-5s %-14s %d" % (lv, code, n))
    return 1 if nerr else 0


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
    sys.exit(main())
