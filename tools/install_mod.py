# -*- coding: utf-8 -*-
"""安装 MOD：按客户端真实版本，把 wotmod 放进 <游戏>/mods/<版本>/。

版本判定顺序：
  1. version.xml（与 mods/<版本> 目录完全一致，最准）
  2. WorldOfTanks.exe 的 PE 文件版本（如 2.4.1.1535）
  3. 都没有则退回“mods 下最大版本目录”

用法：
  python install_mod.py                 # 自动找游戏目录
  python install_mod.py --game-dir "D:\\World_of_Tanks_CN"
  python install_mod.py --dry-run       # 只打印不复制
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wot_common as wc


def version_tuple(name: str):
    parts = []
    for p in name.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return parts


def list_mod_versions(mods_root: str):
    if not os.path.isdir(mods_root):
        return []
    out = []
    for d in os.listdir(mods_root):
        if os.path.isdir(os.path.join(mods_root, d)) and d[:1].isdigit():
            out.append(d)
    return sorted(out, key=version_tuple)


def pick_version_dir(mods_root: str, version: str) -> tuple:
    """返回 (目录名, 原因)。"""
    dirs = list_mod_versions(mods_root)
    if not dirs:
        return version, "mods 为空，新建"

    if version in dirs:
        return version, "与客户端版本完全一致"

    # exe 版本可能是 2.4.1.1535，mods 目录是 2.4.1.1 → 用前三段匹配
    prefix = ".".join(version.split(".")[:3])
    same = [d for d in dirs if d == prefix or d.startswith(prefix + ".")]
    if same:
        return same[-1], "匹配主版本 %s.*" % prefix

    if version:
        return version, "没有匹配目录，新建"

    return dirs[-1], "版本未知，退回最新目录"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--game-dir", default="")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    gdir = args.game_dir or wc.game_dir()
    if not gdir or not os.path.isdir(gdir):
        print("没有游戏目录。")
        return 2

    xml_ver = wc._xml_version(gdir)
    exe_ver = wc._exe_version(gdir)
    version, source = wc.game_version(gdir)

    print("游戏目录：%s" % gdir)
    print("  含 WorldOfTanks.exe：%s" % ("是" if wc.has_exe(gdir) else "否"))
    print("  version.xml 版本：%s" % (xml_ver or "无"))
    print("  exe 文件版本    ：%s" % (exe_ver or "读不到"))
    print("  采用版本        ：%s（来源：%s）" % (version or "未知", source or "-"))

    mods_root = os.path.join(gdir, "mods")
    if not os.path.isdir(mods_root):
        print("没有找到 mods 目录：%s" % mods_root)
        return 2

    target_name, reason = pick_version_dir(mods_root, version)
    target = os.path.join(mods_root, target_name)
    print("  选择目录        ：mods\\%s（%s）" % (target_name, reason))

    src_dir = ''
    for cand in (os.path.join(os.path.dirname(wc.script_dir()), "mod"),
                 os.path.join(wc.script_dir(), "mod")):
        if os.path.isdir(cand):
            src_dir = cand
            break
    if not src_dir:
        print("工具包里没有 mod 目录。")
        return 2
    mods = [f for f in os.listdir(src_dir) if f.endswith(".wotmod")]
    if not mods:
        print("工具包里没有 .wotmod 文件。")
        return 2

    if args.dry_run:
        for name in mods:
            print("[dry-run] %s -> %s" % (name, target))
        return 0

    os.makedirs(target, exist_ok=True)
    for name in mods:
        src = os.path.join(src_dir, name)
        dst = os.path.join(target, name)
        shutil.copy2(src, dst)
        print("  已安装 %s -> %s" % (name, dst))

    print("\n重启游戏，进车库约 20 秒会自动导出黑名单。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
