# -*- coding: utf-8 -*-
"""工具二：清理黑名单里长期不上线的玩家。

流程：
  1. 读取 blacklist_export.json，筛出最后战斗 >= N 天的人；
  2. 写 blacklist_delete_list.json 和 blacklist_delete_go.txt 到游戏根目录；
  3. 启动游戏进车库，MOD 自动逐个删除（约 2 秒/人）；
  4. 删完后本工具把 blacklist_delete_report.json 转成 Excel。

用法：
  python clean_blacklist.py            # 菜单
  python clean_blacklist.py --days 180 --apply
  python clean_blacklist.py --report
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wot_common as wc


def build_list(days: int, apply: bool) -> int:
    src = wc.find_export()
    if not src:
        print("没找到 blacklist_export.json，请先让 MOD 导出一次。")
        return 2

    data = wc.load_export(src)
    players = data.get("players") or []
    targets, seen = [], set()
    for p in players:
        aid = p.get("account_id")
        ts = int(p.get("last_battle_time") or 0)
        if not aid or not ts or aid in seen:
            continue
        d = wc.days_since(ts)
        if d < days:
            continue
        seen.add(aid)
        targets.append({
            "account_id": aid,
            "nickname": p.get("nickname") or "",
            "created_at": int(p.get("created_at") or p.get("reg_timestamp") or 0),
            "created_str": wc.fmt_ts(int(p.get("created_at") or p.get("reg_timestamp") or 0)),
            "last_battle_time": ts,
            "last_battle_str": wc.fmt_ts(ts),
            "days": d,
            "battles": int(p.get("battles") or 0),
            "web_valid": bool(p.get("web_valid")),
        })

    targets.sort(key=lambda x: -x["days"])
    payload = {
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "threshold_days": days,
        "count": len(targets),
        "players": targets,
    }
    out = os.path.join(wc.output_dir(), "blacklist_delete_list.json")
    open(out, "w", encoding="utf-8").write(json.dumps(payload, ensure_ascii=False, indent=1))

    print(f"阈值 {days} 天：共 {len(targets)} 人")
    for t in targets[:10]:
        print(f"  {t['nickname']:<24} {t['days']:>5} 天  {t['last_battle_str']}")
    print(f"名单已写入：{out}")

    if not apply:
        print("\n（预览模式，未部署到游戏目录。加 --apply 才会真正放置文件）")
        return 0

    gdir = wc.game_dir()
    if not gdir:
        print("没有游戏目录，无法部署。")
        return 2

    with open(os.path.join(gdir, "blacklist_delete_list.json"), "w", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False, indent=1))
    with open(os.path.join(gdir, "blacklist_delete_go.txt"), "w", encoding="utf-8") as fh:
        fh.write("GO\n目标 %d 人，阈值 %d 天\n" % (len(targets), days))

    print(f"\n已部署到：{gdir}")
    print("  blacklist_delete_list.json")
    print("  blacklist_delete_go.txt      ← MOD 读到就会开始删，读后自动删除")
    print("\n现在启动游戏，进车库等 10 秒即可。250 人约 8 分钟。")
    return 0


def make_report() -> int:
    gdir = wc.game_dir(ask=False)
    candidates = []
    if gdir:
        candidates.append(os.path.join(gdir, "blacklist_delete_report.json"))
    candidates.append(os.path.join(wc.output_dir(), "blacklist_delete_report.json"))
    src = next((p for p in candidates if os.path.isfile(p)), None)
    if not src:
        print("没找到 blacklist_delete_report.json，请先完成一次删除。")
        return 2

    data = json.loads(open(src, encoding="utf-8").read())
    rows = data.get("rows") or []
    detail = []
    for i, r in enumerate(rows, 1):
        detail.append([
            i, r.get("account_id"), r.get("nickname"),
            r.get("created_str") or "", r.get("last_battle_str") or "",
            r.get("days") or "", r.get("battles") or 0,
            "是" if r.get("web_valid") else "否",
            r.get("result"), round(float(r.get("elapsed") or 0), 1),
            r.get("deleted_at") or "",
        ])

    summary = [
        ["开始时间", data.get("started_at", "")],
        ["结束时间", data.get("finished_at", "")],
        ["总耗时", "%s 秒（%.1f 分钟）" % (data.get("duration_sec", 0), (data.get("duration_sec") or 0) / 60.0)],
        ["目标人数", data.get("total", len(rows))],
        ["成功", data.get("ok", 0)],
        ["失败/未确认", data.get("failed", 0)],
    ]

    out = os.path.join(wc.output_dir(), "黑名单删除报告.xlsx")
    ok = wc.write_xlsx(out, [
        ("汇总", ["项目", "值"], summary),
        ("删除明细",
         ["序号", "用户ID", "昵称", "账号创建时间", "最后战斗时间", "距今天数",
          "总场次", "网页有效", "结果", "耗时(秒)", "执行操作时间"],
         detail),
    ])
    print(f"报告：{out}" + ("" if ok else "（已导出 CSV）"))
    if ok and os.name == "nt":
        try:
            os.startfile(out)
        except Exception:
            pass
    return 0


def menu() -> int:
    print("=" * 52)
    print("  坦克世界 黑名单清理工具")
    print("=" * 52)
    print("1. 预览沉睡玩家（不删）")
    print("2. 部署删除名单到游戏（生成开关，重启游戏后自动删）")
    print("3. 生成删除报告 Excel")
    print("0. 退出")
    choice = input("请选择：").strip()

    if choice == "1":
        return build_list(180, apply=False)
    if choice == "2":
        days = input("阈值天数（回车=180）：").strip() or "180"
        return build_list(int(days), apply=True)
    if choice == "3":
        return make_report()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=180)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()
    if args.report:
        return make_report()
    if len(sys.argv) > 1:
        return build_list(args.days, args.apply)
    return menu()


if __name__ == "__main__":
    raise SystemExit(main())
