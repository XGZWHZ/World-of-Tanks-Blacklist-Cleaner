# -*- coding: utf-8 -*-
"""环境自检：确认另一台电脑上到底是缺 Python、缺库，还是 MOD 没装好。"""

from __future__ import annotations

import json
import os
import platform
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wot_common as wc


def line(title):
    print("\n" + "=" * 56)
    print("  " + title)
    print("=" * 56)


def main() -> int:
    line("Python")
    print("版本：%s" % sys.version.replace("\n", " "))
    print("位数：%d 位" % (64 if sys.maxsize > 2 ** 32 else 32))
    print("路径：%s" % sys.executable)
    if sys.version_info < (3, 8):
        print("[!] 版本太低，需要 Python 3.8 及以上")

    line("依赖库")
    try:
        import openpyxl
        print("openpyxl：有（%s）" % openpyxl.__version__)
    except Exception:
        print("openpyxl：没有 —— 不影响，内置 mini_xlsx 照样能出 xlsx")
    try:
        import mini_xlsx  # noqa: F401
        print("mini_xlsx：有（内置，纯标准库）")
    except Exception as exc:
        print("mini_xlsx：缺失！(%s) 请确认 tools 目录完整" % exc)

    line("游戏目录")
    dirs = wc.find_game_dirs()
    if not dirs:
        print("[!] 没找到。请确认已安装客户端，且目录里有 WorldOfTanks.exe")
    for d in dirs:
        ver, src = wc.game_version(d)
        print("  %s" % d)
        print("    版本：%s（来源：%s）" % (ver or "未知", src or "-"))
        mods = os.path.join(d, "mods")
        if os.path.isdir(mods):
            vers = sorted([x for x in os.listdir(mods) if os.path.isdir(os.path.join(mods, x))])
            print("    mods 目录：%s" % (", ".join(vers[-3:]) if vers else "空"))
            target = os.path.join(mods, ver) if ver else ""
            found = []
            if target and os.path.isdir(target):
                found = [f for f in os.listdir(target) if f.endswith(".wotmod")]
            if found:
                print("    已装 MOD：%s" % ", ".join(found))
            else:
                print("    [!] 目标目录里没有 .wotmod，请运行 安装MOD.bat")
        else:
            print("    [!] 没有 mods 目录，先启动一次游戏")

    line("导出文件")
    for base in wc.candidate_dirs():
        for name in ("blacklist_export.json", "blacklist_enriched.json",
                     "blacklist_delete_report.json"):
            path = os.path.join(base, name)
            if os.path.isfile(path):
                try:
                    data = json.loads(open(path, encoding="utf-8-sig").read())
                    count = len(data.get("players") or data.get("rows") or [])
                    print("  %s（%d 条）" % (path, count))
                except Exception:
                    print("  %s（读取失败）" % path)
    if not wc.find_export(prefer_enriched=False):
        print("[!] 还没有 blacklist_export.json —— 说明 MOD 没导出，先看 game.log 里的 [BLX]")

    line("结论")
    print("· MOD 不加载：与 Python 无关，看 游戏根目录\\game.log 里 “Mod package” 那行；")
    print("  常见原因是版本目录不对、包内是 .py、或 zip 用了压缩。")
    print("· 工具双击没反应：多半是没装 Python；装 3.8+ 并勾选 Add to PATH。")
    print("· 只出 CSV 不出 xlsx：装不装 openpyxl 都行，v1.4 起内置写入器。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
