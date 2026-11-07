# -*- coding: utf-8 -*-
"""工具一：读取 MOD 导出的黑名单，生成 Excel 并展示。

用法：
  双击 工具1_查看黑名单.bat
  或 python view_blacklist.py [--days 180]
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wot_common as wc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=180)
    ap.add_argument("--input", default="")
    args = ap.parse_args()

    path = args.input or wc.find_export()
    if not path:
        print("没找到 blacklist_export.json。")
        print("请先安装 MOD 并进一次车库，让 MOD 导出文件；")
        print("文件通常在：%APPDATA%\\Wargaming.net\\WorldOfTanks\\ 或 游戏根目录。")
        return 2

    data = wc.load_export(path)
    players = data.get("players") or []

    seen = {}
    for p in players:
        key = p.get("account_id") or p.get("nickname")
        if key not in seen:
            seen[key] = p
    uniq = list(seen.values())

    rows, active, dormant = [], 0, 0
    for p in sorted(uniq, key=lambda x: -(wc.days_since(x.get("last_battle_time") or 0))):
        ts = p.get("last_battle_time") or 0
        days = wc.days_since(ts)
        if ts and days >= args.days:
            state = "沉睡"
            dormant += 1
        elif ts:
            state = "活跃"
            active += 1
        else:
            state = "无数据"
        rows.append([
            p.get("account_id"), p.get("nickname"),
            ",".join(p.get("tags") or []),
            "在线" if p.get("online") else "离线",
            wc.fmt_ts(ts), days if days >= 0 else "",
            p.get("battles") or 0, state,
        ])

    out = os.path.join(wc.output_dir(), "黑名单列表.xlsx")
    ok = wc.write_xlsx(out, [(
        "黑名单",
        ["用户ID", "昵称", "标签", "在线", "最后战斗时间", "距今天数", "总场次", "状态"],
        rows,
    )])

    print("=" * 60)
    print(f"导出文件：{path}")
    print(f"记录 {len(players)} 条，去重后 {len(uniq)} 人")
    print(f"活跃 {active} ｜ 沉睡(≥{args.days}天) {dormant} ｜ 无数据 {len(uniq) - active - dormant}")
    print(f"结果：{out}" + ("" if ok else "（没装 openpyxl，已导出 CSV）"))
    print("=" * 60)

    print("\n最久未战斗的 10 个：")
    for r in rows[:10]:
        print(f"  {str(r[1]):<24} {str(r[5]):>6} 天  {r[4]}")

    if ok and os.name == "nt":
        try:
            os.startfile(out)
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
