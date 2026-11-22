# -*- coding: utf-8 -*-
"""`.mcb` バンドルを作る / 開く / ゲームと行き来する。

  python tools/mcb.py pack    "out/MCBENCH Averager.xml"    -> bundles/*.mcb
  python tools/mcb.py unpack  bundles/Averager.mcb          -> .xml を書き出す
  python tools/mcb.py install bundles/Averager.mcb          -> ゲームのフォルダへ
  python tools/mcb.py sync    bundles/Averager.mcb          <- ゲーム側の変更を取り込む
  python tools/mcb.py info    bundles/Averager.mcb          中身と検証結果

**バンドルは容器。** 中にゲームの `.xml` をそのまま抱える。だから
`pack` -> `install` -> ゲームで編集 -> `sync` と回しても、付箋は残り、
回路はゲーム側が正のまま保たれる。
"""
from __future__ import annotations

import argparse
import io
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcbench import bundle, loads  # noqa: E402
from mcbench.validate import validate  # noqa: E402

APPMC = os.path.expandvars(r"%APPDATA%\Stormworks\data\microprocessors")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLES = os.path.join(HERE, "bundles")


def _report(mc, quiet=False):
    issues = validate(mc)
    n_err = sum(1 for i in issues if i.level == "error")
    if not quiet:
        for i in issues:
            if i.level == "error":
                print("  %r" % i)
    return n_err


def cmd_pack(a):
    rc = 0
    os.makedirs(a.outdir, exist_ok=True)
    for p in a.files:
        xml = io.open(p, encoding="utf-8", errors="replace").read()
        name = os.path.splitext(os.path.basename(p))[0]
        dst = a.out or os.path.join(a.outdir, name + ".mcb")
        if os.path.exists(dst):
            # **既にあるバンドルは付箋を残す。** 差し替えるのはXMLだけ。
            b = bundle.load(dst)
            b.xml = xml
            kept = len(b.notes)
        else:
            b = bundle.from_xml(xml)
            kept = 0
        bundle.dump(b, dst)
        n_err = _report(loads(xml))
        print("%s  %s%s" % ("NG " if n_err else "OK ", dst,
                            "  (付箋 %d 件を保持)" % kept if kept else ""))
        rc = rc or (1 if n_err else 0)
    return rc


def cmd_unpack(a):
    b = bundle.load(a.file)
    dst = a.out or os.path.join(os.path.dirname(a.file) or ".",
                                (b.meta.get("name") or "microprocessor") + ".xml")
    io.open(dst, "w", encoding="utf-8", newline="\r\n").write(b.xml)
    print("-> %s" % dst)
    return 0


def cmd_install(a):
    b = bundle.load(a.file)
    mc = b.microprocessor()
    n_err = _report(mc)
    if n_err and not a.force:
        print("NG  検証で error %d 件。--force で無視できます" % n_err)
        return 1
    if not os.path.isdir(APPMC):
        print("NG  マイコンフォルダが見つかりません: %s" % APPMC)
        return 1
    dst = os.path.join(APPMC, mc.name + ".xml")
    if os.path.exists(dst):
        shutil.copy2(dst, dst + ".bak")
        print("    既存を退避: %s.bak" % os.path.basename(dst))
    io.open(dst, "w", encoding="utf-8", newline="\r\n").write(b.xml)
    print("OK  -> %s" % dst)
    return 0


def cmd_sync(a):
    """ゲーム側で編集されたXMLをバンドルに取り込む。付箋はそのまま残る。"""
    b = bundle.load(a.file)
    name = b.meta.get("name") or b.microprocessor().name
    src = os.path.join(APPMC, name + ".xml")
    if not os.path.exists(src):
        print("NG  ゲーム側に %s がありません" % os.path.basename(src))
        return 1
    new = io.open(src, encoding="utf-8", errors="replace").read()
    if new == b.xml:
        print("変更なし  %s" % name)
        return 0
    old_n = len(loads(b.xml).components)
    b.xml = new
    bundle.dump(b, a.file)
    mc = b.microprocessor()
    print("OK  取り込み  部品 %d -> %d / 付箋 %d 件は保持"
          % (old_n, len(mc.components), len(b.notes)))
    return 1 if _report(mc) else 0


def cmd_info(a):
    b = bundle.load(a.file)
    mc = b.microprocessor()
    print("名前     %s" % mc.name)
    print("盤面     %dx%d" % (mc.width, mc.length))
    print("端子     %d" % len(mc.terminals))
    print("部品     %d (bridge %d)" % (len(mc.components), len(mc.bridge)))
    print("付箋     %d" % len(b.notes))
    for n in b.notes:
        first = (n.text or "").split("\n")[0]
        print("  #%-3d (%g,%g) %s" % (n.id, n.x, n.y, first[:50]))
    if b.extra:
        print("その他のセクション: %s" % ", ".join(h for h, _ in b.extra))
    issues = validate(mc)
    n_err = sum(1 for i in issues if i.level == "error")
    n_warn = len(issues) - n_err
    print("検証     error %d / warn %d" % (n_err, n_warn))
    for i in issues:
        if i.level == "error":
            print("  %r" % i)
    return 1 if n_err else 0


def main():
    ap = argparse.ArgumentParser(prog="mcb", description=".mcb バンドルを扱う")
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("pack", help=".xml をバンドルにくるむ")
    p.add_argument("files", nargs="+")
    p.add_argument("-o", "--out", help="出力先のファイル名")
    p.add_argument("--outdir", default=BUNDLES, help="出力先(既定: bundles/)")
    p.set_defaults(fn=cmd_pack)

    p = sub.add_parser("unpack", help="バンドルから .xml を取り出す")
    p.add_argument("file")
    p.add_argument("-o", "--out")
    p.set_defaults(fn=cmd_unpack)

    p = sub.add_parser("install", help="ゲームのマイコンフォルダへ書き出す")
    p.add_argument("file")
    p.add_argument("--force", action="store_true", help="検証の error を無視する")
    p.set_defaults(fn=cmd_install)

    p = sub.add_parser("sync", help="ゲーム側の変更をバンドルに取り込む")
    p.add_argument("file")
    p.set_defaults(fn=cmd_sync)

    p = sub.add_parser("info", help="中身と検証結果を出す")
    p.add_argument("file")
    p.set_defaults(fn=cmd_info)

    a = ap.parse_args()
    if not getattr(a, "fn", None):
        ap.print_help()
        return 2
    return a.fn(a)


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
    sys.exit(main())
