# -*- coding: utf-8 -*-
"""配布用の zip を作る。

  python tools/make_dist.py               dist/mcbench-<版>.zip を作る
  python tools/make_dist.py --export DIR  同じ中身を DIR へ書き出す(公開リポジトリ用)
  python tools/make_dist.py --no-check    検証を飛ばす(普段は使わない)

**作った zip を一時フォルダへ展開して selftest を走らせる。** 通らなければ zip を
残さない。以前 `dist/mccompile.zip` が中身の古いまま置かれ、それに気づかないまま
「配布できる」と言っていたので、**手で詰めるのをやめて毎回ここから作る。**

同梱しないもの:
- `spec/*.mc` のうち兄弟プロジェクトの `.lua` を参照しているもの
  (配布先にそのフォルダが無いので必ず壊れる)
- `PROJECT_HANDOFF.md` `OPEN.md` などの手元の設計記録(他プロジェクトの話が多いため)
- `out/` `bundles/` `_selftest/` `dist/` などの作業物

**公開リポジトリは手元とは別の履歴にする**(2026-11-22 合意)。`--export` で
書き出したフォルダを公開リポジトリの作業ツリーにし、そこでコミットする。
書き出し先の `.git` 以外は毎回消して作り直すので、向こうで手を入れないこと。
"""
from __future__ import annotations

import argparse
import glob
import io
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from mcbench import __version__  # noqa: E402

TOP = "mcbench"


def collect():
    """(zip内のパス, 実ファイル) の一覧。"""
    items = []

    def add(rel):
        p = os.path.join(HERE, rel)
        if os.path.exists(p):
            items.append((rel.replace("\\", "/"), p))

    add("mccompile.py")
    add("README.md")
    add("AGENTS.md")
    add("LICENSE")
    add(".gitignore")
    for p in sorted(glob.glob(os.path.join(HERE, "mcbench", "*.py"))):
        add(os.path.join("mcbench", os.path.basename(p)))
    for p in sorted(glob.glob(os.path.join(HERE, "tools", "*.py"))):
        add(os.path.join("tools", os.path.basename(p)))
    add(os.path.join("data", "component_catalog.csv"))

    # spec は自己完結しているものだけ。兄弟プロジェクトを参照するものは外す。
    skipped = []
    for p in sorted(glob.glob(os.path.join(HERE, "spec", "**", "*.*"), recursive=True)):
        rel = os.path.relpath(p, HERE)
        if p.lower().endswith(".mc"):
            src = io.open(p, encoding="utf-8", errors="replace").read()
            if "../../" in src:
                skipped.append(rel)
                continue
        elif not p.lower().endswith(".lua"):
            continue
        add(rel)
    return items, skipped


def build(dst):
    items, skipped = collect()
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
        for rel, real in items:
            z.write(real, "%s/%s" % (TOP, rel))
    return items, skipped


def export(dst):
    """dst を配布物と同じ中身にする。dst/.git だけは残す。"""
    items, skipped = collect()
    os.makedirs(dst, exist_ok=True)
    for name in os.listdir(dst):
        if name == ".git":
            continue
        p = os.path.join(dst, name)
        if os.path.isdir(p):
            shutil.rmtree(p)
        else:
            os.remove(p)
    for rel, real in items:
        out = os.path.join(dst, rel)
        os.makedirs(os.path.dirname(out) or dst, exist_ok=True)
        shutil.copyfile(real, out)
    return items, skipped


def verify(zip_path):
    """展開して selftest を走らせる。戻り値は失敗の説明(空なら通過)。"""
    tmp = tempfile.mkdtemp(prefix="mcbench_dist_")
    try:
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(tmp)
        return run_selftest(os.path.join(tmp, TOP), tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run_selftest(root, tmp=None):
    """root で selftest を走らせる。戻り値は失敗の説明(空なら通過)。"""
    own = tmp is None
    if own:
        tmp = tempfile.mkdtemp(prefix="mcbench_dist_")
    try:
        # **%APPDATA% を空のフォルダに差し替えて走らせる。** そうしないと自分の
        # 保存済みマイコンが見えてしまい、「配布先でも通る」の確認にならない。
        env = dict(os.environ)
        empty = os.path.join(tmp, "empty_appdata")
        os.makedirs(empty, exist_ok=True)
        env["APPDATA"] = empty
        r = subprocess.run([sys.executable, os.path.join(root, "tools", "selftest.py")],
                           cwd=root, capture_output=True, text=True, env=env,
                           encoding="utf-8", errors="replace")
        out = (r.stdout or "") + (r.stderr or "")
        for line in out.rstrip().split("\n"):
            print("     | %s" % line)
        # selftest が書く作業物(out/ など)を書き出し先に残さない
        for w in ("out", "_selftest", "bundles", "__pycache__"):
            shutil.rmtree(os.path.join(root, w), ignore_errors=True)
        for d, _, _ in os.walk(root):
            if os.path.basename(d) == "__pycache__":
                shutil.rmtree(d, ignore_errors=True)
        return "" if r.returncode == 0 else "selftest が失敗 (終了コード %d)" % r.returncode
    finally:
        if own:
            shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-check", action="store_true", help="展開しての検証を飛ばす")
    ap.add_argument("--export", metavar="DIR", help="zip ではなく DIR へ書き出す(.git は残す)")
    a = ap.parse_args()

    if a.export:
        dst = os.path.abspath(a.export)
        if dst == HERE:
            print("NG  書き出し先が手元のフォルダそのものです")
            return 1
        items, skipped = export(dst)
        print("書き出し %d ファイル -> %s" % (len(items), dst))
        for r in skipped:
            print("   除外: %s" % r)
        if a.no_check:
            return 0
        print("")
        print("書き出し先で selftest:")
        why = run_selftest(dst)
        if why:
            print("")
            print("NG  %s" % why)
            return 1
        print("")
        print("OK  書き出し先で通りました。そこでコミットしてください。")
        return 0

    outdir = os.path.join(HERE, "dist")
    os.makedirs(outdir, exist_ok=True)
    dst = os.path.join(outdir, "mcbench-%s.zip" % __version__)

    items, skipped = build(dst)
    print("同梱 %d ファイル -> %s" % (len(items), dst))
    if skipped:
        print("除外(兄弟プロジェクトの .lua を参照している):")
        for r in skipped:
            print("   %s" % r)
    if not os.path.exists(os.path.join(HERE, "LICENSE")):
        print("【注意】LICENSE がありません。公開するなら必要です。")

    if a.no_check:
        return 0
    print("")
    print("展開して selftest:")
    why = verify(dst)
    if why:
        os.remove(dst)
        print("")
        print("NG  %s。zip は残していません。" % why)
        return 1
    print("")
    print("OK  配布物として動きます。")
    return 0


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
    sys.exit(main())
