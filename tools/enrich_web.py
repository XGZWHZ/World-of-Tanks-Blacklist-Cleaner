# -*- coding: utf-8 -*-
"""工具三：用官网公开玩家页补全“最后战斗时间 / 注册时间 / 场次”。

v3.0 重写：异步 IO + 全局令牌桶限速 + 动态调速（AIMD）+ 随机抖动。

设计要点
--------
1. 异步 IO：asyncio 调度，HTTP 走线程池执行器（纯标准库，不引入 aiohttp）；
2. 全局速率：所有请求共享一个令牌桶，跨协程串行排队，不会因为并发叠加而超速；
3. 动态调速：成功按 +0.05 加性提升，失败按 ×0.5 乘性回退，并进入冷却；
4. 随机抖动：每次取令牌后在 [0, 0.35/rate] 内随机等待，避免固定节奏被识别。

支持区服：cn 国服 / com 美服 / eu 欧服 / asia 亚服。

用法：
  python enrich_web.py --region cn
  python enrich_web.py --limit 5 --rate 1.5
  python enrich_web.py --probe 7047820277
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import re
import ssl
import sys
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wot_common as wc

PORTALS = {
    "cn": ("https://wotgame.cn", "/zh-cn", "国服"),
    "com": ("https://worldoftanks.com", "/en", "美服"),
    "eu": ("https://worldoftanks.eu", "/en", "欧服"),
    "asia": ("https://worldoftanks.asia", "/en", "亚服"),
}

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

USER_DATA_RE = re.compile(r"USER_DATA\s*=\s*(\{.*?\})\s*,\s*VEHICLES_PARAMETERS", re.S)
LAST_BATTLE_RE = re.compile(r'"last_battle_at"\s*:\s*(\d+)')
NICK_RE = re.compile(r'"nickname"\s*:\s*"([^"]*)"')
REG_RE = re.compile(r'"reg_timestamp"\s*:\s*(\d+)')
VALID_RE = re.compile(r'"is_valid"\s*:\s*(true|false)')

_CTX = None
_REFERER = ""


def _ctx():
    global _CTX
    if _CTX is None:
        try:
            _CTX = ssl.create_default_context()
        except Exception:
            _CTX = ssl._create_unverified_context()
    return _CTX


def fetch(url: str, timeout: float = 25.0):
    """阻塞式 HTTP，由线程池调用。"""
    headers = {
        "User-Agent": UA,
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "X-Requested-With": "XMLHttpRequest",
    }
    if _REFERER:
        headers["Referer"] = _REFERER
    req = urllib.request.Request(url, headers=headers)
    for ctx in (_ctx(), ssl._create_unverified_context()):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                return resp.read().decode("utf-8", "replace")
        except ssl.SSLError:
            continue
        except Exception:
            return None
    return None


def parse_profile(html: str) -> dict:
    data = {}
    if not html:
        return data
    m = USER_DATA_RE.search(html)
    if m:
        try:
            user = json.loads(m.group(1))
            data["nickname"] = user.get("nickname")
            data["spa_id"] = user.get("spa_id")
            data["reg_timestamp"] = user.get("reg_timestamp") or 0
            summary = user.get("summary") or {}
            data["is_valid"] = bool(summary.get("is_valid"))
            data["last_battle_at"] = int(summary.get("last_battle_at") or 0)
            clan = user.get("clan_info") or {}
            data["clan_tag"] = clan.get("tag") or ""
            return data
        except Exception:
            pass

    lb = LAST_BATTLE_RE.search(html)
    if lb:
        data["last_battle_at"] = int(lb.group(1))
    nick = NICK_RE.search(html)
    if nick:
        data["nickname"] = nick.group(1)
    reg = REG_RE.search(html)
    if reg:
        data["reg_timestamp"] = int(reg.group(1))
    valid = VALID_RE.search(html)
    if valid:
        data["is_valid"] = valid.group(1) == "true"
    return data


def fetch_battles(search_url: str, nickname: str) -> int:
    html = fetch(search_url.format(name=urllib.parse.quote(nickname)))
    if not html:
        return 0
    try:
        payload = json.loads(html)
        for item in payload.get("response") or []:
            if (item.get("account_name") or "").lower() == nickname.lower():
                return int(item.get("account_battles") or 0)
    except Exception:
        pass
    return 0


class RateLimiter:
    """全局令牌桶 + AIMD 动态调速。"""

    def __init__(self, rate: float, min_rate: float, max_rate: float, jitter: float = 0.35):
        self.rate = max(min_rate, min(max_rate, rate))
        self.min_rate = min_rate
        self.max_rate = max_rate
        self.jitter = jitter
        self._next = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self):
        async with self._lock:
            now = asyncio.get_running_loop().time()
            wait = max(0.0, self._next - now)
            self._next = max(now, self._next) + 1.0 / self.rate
        if wait > 0:
            await asyncio.sleep(wait)
        if self.jitter:
            await asyncio.sleep(random.uniform(0.0, self.jitter / self.rate))

    def on_success(self):
        self.rate = min(self.max_rate, self.rate + 0.05)

    def on_failure(self):
        self.rate = max(self.min_rate, self.rate * 0.5)


class Progress:
    def __init__(self, total: int, use_cr: bool):
        self.total = total
        self.done = 0
        self.start = time.time()
        self.current = ""
        self.rate = 0.0
        self.use_cr = use_cr
        self._lock = threading.Lock()

    def _fmt(self, sec: float) -> str:
        sec = int(max(0, sec))
        if sec >= 3600:
            return "%d小时%02d分" % (sec // 3600, (sec % 3600) // 60)
        if sec >= 60:
            return "%d分%02d秒" % (sec // 60, sec % 60)
        return "%d秒" % sec

    def render(self, final: bool = False):
        with self._lock:
            done = self.done
            cur = self.current
            rate = self.rate
        elapsed = time.time() - self.start
        avg = (elapsed / done) if done else 0.0
        eta = avg * (self.total - done)
        pct = int(done * 100 / self.total) if self.total else 100
        eta_txt = self._fmt(eta) if done else "计算中"
        line = "[%d/%d %d%%] 当前: %-16s 剩余 %d | 速率 %.1f/s | 已用 %s | 预计 %s" % (
            done, self.total, pct, (cur[:16] if cur else "-"),
            self.total - done, rate, self._fmt(elapsed), eta_txt)
        if self.use_cr and not final:
            sys.stdout.write("\r" + line.ljust(96))
            sys.stdout.flush()
        else:
            print(line, flush=True)


def choose_region(arg: str) -> str:
    region = (arg or wc.load_config().get("region") or "").strip().lower()
    if region in PORTALS:
        return region
    if region:
        print("未知区服 %s，使用国服。" % region)
    print("请选择区服：1 国服   2 美服   3 欧服   4 亚服")
    pick = input("序号（回车=1）：").strip() or "1"
    region = {"1": "cn", "2": "com", "3": "eu", "4": "asia"}.get(pick, "cn")
    cfg = wc.load_config()
    cfg["region"] = region
    wc.save_config(cfg)
    return region


async def run(todo, players, cache, cache_path, args, urls, progress, limiter, concurrency):
    loop = asyncio.get_running_loop()
    executor = ThreadPoolExecutor(max_workers=max(1, concurrency))
    streak = {"n": 0}
    lock = asyncio.Lock()

    async def worker(player):
        sid = str(player.get("account_id"))
        nick = (player.get("nickname") or "").strip()

        for _ in range(max(1, args.retries)):
            await limiter.acquire()

            with progress._lock:
                progress.current = nick or sid
                progress.rate = limiter.rate
            progress.render()

            html = await loop.run_in_executor(
                executor, fetch, urls["profile"].format(sid=sid))

            if html is None:
                limiter.on_failure()
                streak["n"] += 1
                if streak["n"] >= 3:
                    await asyncio.sleep(args.retry_wait * random.uniform(0.8, 1.2))
                    streak["n"] = 0
                continue

            info = parse_profile(html)

            # 兜底：id-only 拿不到时换 id-昵称 形式
            if not info.get("last_battle_at") and nick:
                await limiter.acquire()
                slug = urllib.parse.quote(nick.replace(" ", "_"))
                html2 = await loop.run_in_executor(
                    executor, fetch, urls["profile_nick"].format(sid=sid, nick=slug))
                if html2:
                    info2 = parse_profile(html2)
                    if info2.get("last_battle_at") or not info:
                        info = info2

            if args.battles and info.get("nickname") and not info.get("battles"):
                await limiter.acquire()
                info["battles"] = await loop.run_in_executor(
                    executor, fetch_battles, urls["search"], info["nickname"])

            if info.get("last_battle_at"):
                streak["n"] = 0
                limiter.on_success()
            else:
                info["error"] = "nodata"

            async with lock:
                cache[sid] = info
                progress.done += 1
                if progress.done % 20 == 0:
                    with open(cache_path, "w", encoding="utf-8") as fh:
                        json.dump(cache, fh, ensure_ascii=False)
            progress.render()
            return

        async with lock:
            progress.done += 1
        progress.render()

    tasks = [asyncio.create_task(worker(p)) for p in todo]
    await asyncio.gather(*tasks, return_exceptions=True)
    executor.shutdown(wait=True)

    with open(cache_path, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, ensure_ascii=False)

    got = 0
    for p in players:
        rec = cache.get(str(p.get("account_id"))) or {}
        if rec.get("last_battle_at"):
            p["last_battle_time"] = int(rec["last_battle_at"])
            got += 1
        if rec.get("reg_timestamp"):
            p["created_at"] = int(rec["reg_timestamp"])
        if rec.get("battles"):
            p["battles"] = int(rec["battles"])
        if rec.get("is_valid"):
            p["web_valid"] = True
        if rec.get("nickname"):
            p["nickname"] = rec["nickname"]
    return got


def main() -> int:
    global _REFERER

    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--input", default="")
    ap.add_argument("-o", "--output", default="")
    ap.add_argument("--region", default="", help="cn / com / eu / asia")
    ap.add_argument("--rate", type=float, default=1.5, help="初始速率 请求/秒")
    ap.add_argument("--min-rate", type=float, default=0.2)
    ap.add_argument("--max-rate", type=float, default=4.0)
    ap.add_argument("--concurrency", type=int, default=0, help="并发数，默认按速率推导")
    ap.add_argument("--retries", type=int, default=3)
    ap.add_argument("--retry-wait", type=float, default=120.0)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--battles", action="store_true")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--fast", action="store_true")
    ap.add_argument("--probe", default="")
    args = ap.parse_args()

    region = choose_region(args.region)
    host, lang, label = PORTALS[region]
    base = host + lang
    urls = {
        "profile": base + "/community/accounts/{sid}/",
        "profile_nick": base + "/community/accounts/{sid}-{nick}/",
        "search": base + "/community/accounts/search/?name={name}&name_gt=",
    }
    _REFERER = base + "/community/accounts/"

    if args.fast:
        args.rate = max(args.rate, 3.0)
        args.max_rate = max(args.max_rate, 6.0)

    if args.probe:
        pid = args.probe.strip()
        for key in ("profile", "profile_nick"):
            url = urls[key].format(sid=pid, nick="x")
            html = fetch(url)
            print("[%s] %s" % (key, url))
            print("  len=%s" % (len(html) if html else None))
            print("  %r" % (parse_profile(html or {}),))
        return 0

    src = args.input or wc.find_export(prefer_enriched=False)
    if not src:
        print("没找到 blacklist_export.json，请先让 MOD 导出一次。")
        return 2

    payload = wc.load_export(src)
    players = payload.get("players") or []
    if not players:
        print("导出文件里没有 players。")
        return 2

    out = args.output or os.path.join(wc.output_dir(), "blacklist_enriched.json")
    cache_path = out + ".cache.json"
    cache = {}
    if os.path.exists(cache_path):
        try:
            cache = json.loads(open(cache_path, encoding="utf-8").read())
        except Exception:
            cache = {}

    todo, seen = [], set()
    for p in players:
        sid = p.get("account_id")
        if not sid or sid in seen:
            continue
        seen.add(sid)
        if p.get("last_battle_time") and not args.refresh:
            continue
        if str(sid) in cache:
            continue
        todo.append(p)
    if args.limit:
        todo = todo[: args.limit]

    concurrency = args.concurrency or max(2, int(round(args.rate)) + 1)
    limiter = RateLimiter(args.rate, args.min_rate, args.max_rate)
    progress = Progress(len(todo), sys.stdout.isatty())

    print("=" * 60)
    print("  官网补数据  （%s %s）" % (label, base))
    print("=" * 60)
    print("输入：%s" % src)
    print("待补：%d 人（缓存 %d）" % (len(todo), len(cache)))
    print("策略：异步 IO ｜ 初始 %.1f 请求/秒（%.1f~%.1f 动态）｜并发 %d ｜随机抖动"
          % (limiter.rate, args.min_rate, args.max_rate, concurrency))
    if not todo:
        print("没有需要补的人。")
        return 0

    got = asyncio.run(run(todo, players, cache, cache_path, args, urls,
                          progress, limiter, concurrency))

    if progress.use_cr:
        print()
    progress.render(final=True)

    payload["players"] = players
    payload["phase"] = "web_enriched"
    payload["source"] = base
    payload["region"] = region
    payload["fetched"] = sum(1 for p in players if p.get("last_battle_time"))
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)

    rows = []
    for p in sorted(players, key=lambda x: -(wc.days_since(x.get("last_battle_time") or 0))):
        ts = p.get("last_battle_time") or 0
        rows.append([
            p.get("account_id"), p.get("nickname") or "",
            wc.fmt_ts(int(p.get("created_at") or 0)),
            wc.fmt_ts(ts), wc.days_since(ts) if ts else "",
            p.get("battles") or 0, "是" if p.get("web_valid") else "否",
        ])
    xlsx = os.path.join(wc.output_dir(), "黑名单最后战斗时间表.xlsx")
    ok = wc.write_xlsx(xlsx, [("黑名单", [
        "用户ID", "昵称", "账号创建时间", "最后战斗时间", "距今天数", "总场次", "网页有效"], rows)])

    print("\n完成：本次成功 %d，累计有最后战斗时间 %d / %d"
          % (got, payload["fetched"], len(players)))
    print("时间表：%s%s" % (xlsx, "" if ok else "（已导出 CSV）"))
    print("输出：%s" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
