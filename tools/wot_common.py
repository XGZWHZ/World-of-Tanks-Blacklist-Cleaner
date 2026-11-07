# -*- coding: utf-8 -*-
"""公共工具：定位游戏目录 / 读取导出 JSON / 写 Excel。"""

from __future__ import annotations

import json
import os
import re
import sys
import time

APP_NAME = "WoT清理黑名单工具"
CONFIG_NAME = "config.json"
WOT_EXE = "WorldOfTanks.exe"


# ------------------------------------------------------------------ 配置文件

def script_dir() -> str:
    return os.path.dirname(os.path.abspath(sys.argv[0]))


def output_dir() -> str:
    """结果统一放在工具包根目录（与 .bat 同级），而不是 tools 里。"""
    root = os.path.dirname(script_dir())
    if os.path.isdir(os.path.join(root, 'tools')):
        return root
    return script_dir()


def load_config() -> dict:
    path = os.path.join(script_dir(), CONFIG_NAME)
    if os.path.exists(path):
        try:
            return json.loads(open(path, encoding="utf-8").read())
        except Exception:
            pass
    return {}


def save_config(cfg: dict) -> None:
    path = os.path.join(script_dir(), CONFIG_NAME)
    open(path, "w", encoding="utf-8").write(json.dumps(cfg, ensure_ascii=False, indent=1))


# ------------------------------------------------------------------ 游戏目录

def _norm(text: str) -> str:
    return text.lower().replace(" ", "").replace("_", "").replace("-", "")


def has_exe(path: str) -> bool:
    return (os.path.isfile(os.path.join(path, WOT_EXE))
            or os.path.isfile(os.path.join(path, "win64", WOT_EXE)))


def looks_like_wot(path: str) -> bool:
    name = _norm(os.path.basename(path.rstrip("\\/")))
    if "worldoftanks" not in name:
        return False
    return has_exe(path)


def _exe_version(path: str) -> str:
    """读 WorldOfTanks.exe 的 PE 文件版本（如 2.4.1.1535）。"""
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:
        return ""

    exe = os.path.join(path, WOT_EXE)
    if not os.path.isfile(exe):
        exe = os.path.join(path, "win64", WOT_EXE)
    if not os.path.isfile(exe):
        return ""
    try:
        size = ctypes.windll.version.GetFileVersionInfoSizeW(exe, None)
        if not size:
            return ""
        buf = ctypes.create_string_buffer(size)
        if not ctypes.windll.version.GetFileVersionInfoW(exe, 0, size, buf):
            return ""
        ptr = ctypes.c_void_p()
        length = wintypes.UINT()
        if not ctypes.windll.version.VerQueryValueW(buf, u"\\", ctypes.byref(ptr),
                                                    ctypes.byref(length)):
            return ""

        class FFI(ctypes.Structure):
            _fields_ = [("sig", wintypes.DWORD), ("sv", wintypes.DWORD),
                        ("fms", wintypes.DWORD), ("fls", wintypes.DWORD),
                        ("pms", wintypes.DWORD), ("pls", wintypes.DWORD)]

        info = FFI.from_address(ptr.value)
        return "%d.%d.%d.%d" % (info.fms >> 16, info.fms & 0xFFFF,
                                info.fls >> 16, info.fls & 0xFFFF)
    except Exception:
        return ""


def _xml_version(path: str) -> str:
    """version.xml 里的 v.2.4.1.1 #994 —— 和 mods/<版本> 目录一致。"""
    xml = os.path.join(path, "version.xml")
    if not os.path.isfile(xml):
        return ""
    try:
        text = open(xml, encoding="utf-8-sig", errors="replace").read()
        m = re.search(r"<version>\s*v?\.?([0-9]+(?:\.[0-9]+)+)", text)
        if m:
            return m.group(1)
    except Exception:
        pass
    return ""


def game_version(path: str) -> tuple:
    """返回 (版本号, 来源)。version.xml 最准，其次 exe 文件版本。"""
    v = _xml_version(path)
    if v:
        return v, "version.xml"
    v = _exe_version(path)
    if v:
        return v, "WorldOfTanks.exe"
    return "", ""


def find_game_dirs(max_depth: int = 3) -> list:
    """扫描各盘/Steam 库，返回所有含 WorldOfTanks.exe 的安装目录。"""
    cfg = load_config()
    found = []
    if cfg.get("game_dir") and os.path.isdir(cfg["game_dir"]) and has_exe(cfg["game_dir"]):
        found.append(cfg["game_dir"])

    skip = {"windows", "programdata", "$recycle.bin", "system volume information",
            "perflogs", "recovery", "msocache"}

    roots = []
    for letter in "CDEFGH":
        root = letter + ":\\"
        if os.path.isdir(root):
            roots.append(root)

    for steam in ("C:\\Program Files (x86)\\Steam", "C:\\Program Files\\Steam",
                  "D:\\Steam", "D:\\SteamLibrary", "E:\\SteamLibrary"):
        vdf = os.path.join(steam, "steamapps", "libraryfolders.vdf")
        if os.path.isfile(vdf):
            try:
                text = open(vdf, encoding="utf-8", errors="replace").read()
                for m in re.finditer(r'"path"\s+"([^"]+)"', text):
                    roots.append(m.group(1).replace("\\\\", "\\") + "\\")
            except Exception:
                pass

    seen_roots = set()
    for root in roots:
        key = root.lower()
        if key in seen_roots:
            continue
        seen_roots.add(key)
        base_depth = root.rstrip("\\").count(os.sep)
        for dirpath, dirnames, filenames in os.walk(root):
            depth = dirpath.count(os.sep) - base_depth
            if depth >= max_depth:
                dirnames[:] = []
            dirnames[:] = [d for d in dirnames
                           if _norm(d) not in skip and not d.startswith(".")]
            if WOT_EXE in filenames and looks_like_wot(dirpath):
                if dirpath not in found:
                    found.append(dirpath)
    return found


def game_dir(ask: bool = True) -> str:
    cfg = load_config()
    if cfg.get("game_dir") and os.path.isdir(cfg["game_dir"]):
        return cfg["game_dir"]

    dirs = find_game_dirs()
    if len(dirs) == 1:
        cfg["game_dir"] = dirs[0]
        save_config(cfg)
        return dirs[0]

    if len(dirs) > 1:
        print("找到多个可能的游戏目录：")
        for i, d in enumerate(dirs, 1):
            ver, src = game_version(d)
            print("  %d) %s   版本 %s（%s）" % (i, d, ver or "未知", src or "-"))
        if not ask:
            return dirs[0]
        idx = input("请选择序号（回车=1）：").strip() or "1"
        try:
            chosen = dirs[int(idx) - 1]
        except Exception:
            chosen = dirs[0]
        cfg["game_dir"] = chosen
        save_config(cfg)
        return chosen

    if not ask:
        return ""
    print("没有自动找到游戏目录（需要包含 WorldOfTanks.exe）。")
    path = input("请输入游戏根目录，例如 D:\\World_of_Tanks_CN ：").strip().strip('"')
    if path and os.path.isdir(path):
        cfg["game_dir"] = path
        save_config(cfg)
        return path
    return ""


# ------------------------------------------------------------------ 导出文件

def candidate_dirs() -> list:
    out = []
    cfg = load_config()
    if cfg.get("game_dir"):
        out.append(cfg["game_dir"])
    appdata = os.environ.get("APPDATA")
    if appdata:
        out.append(os.path.join(appdata, "Wargaming.net", "WorldOfTanks"))
    out.append(script_dir())
    out.append(os.getcwd())
    return out


def find_export(prefer_enriched: bool = True):
    order = ("blacklist_enriched.json", "blacklist_export.json") if prefer_enriched \
        else ("blacklist_export.json",)
    for name in order:
        for base in candidate_dirs():
            path = os.path.join(base, name)
            if os.path.isfile(path):
                return path
    return None


def load_export(path: str) -> dict:
    return json.loads(open(path, encoding="utf-8-sig").read())


def days_since(ts: int) -> int:
    return max(0, int((time.time() - ts) // 86400)) if ts else -1


def fmt_ts(ts: int) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if ts else ""


# ------------------------------------------------------------------ Excel

def write_xlsx(path: str, sheets: list) -> bool:
    """写 xlsx：优先 openpyxl，没有就用内置 mini_xlsx（纯标准库）。"""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter
    except ImportError:
        try:
            import mini_xlsx
            mini_xlsx.write(path, sheets)
            return True
        except Exception:
            import csv
            base = os.path.splitext(path)[0]
            for title, headers, rows in sheets:
                with open("%s_%s.csv" % (base, title), "w", encoding="utf-8-sig", newline="") as fh:
                    writer = csv.writer(fh)
                    writer.writerow(headers)
                    writer.writerows(rows)
            return False

    wb = Workbook()
    first = True
    for title, headers, rows in sheets:
        ws = wb.active if first else wb.create_sheet()
        ws.title = title
        first = False
        fill = PatternFill("solid", fgColor="1F3864")
        for c, h in enumerate(headers, 1):
            cell = ws.cell(1, c, h)
            cell.fill = fill
            cell.font = Font(color="FFFFFF", bold=True)
            cell.alignment = Alignment(horizontal="center")
        for r, row in enumerate(rows, 2):
            for c, v in enumerate(row, 1):
                ws.cell(r, c, v)
        ws.freeze_panes = "A2"
        for c in range(1, len(headers) + 1):
            width = min(max(len(str(headers[c - 1])) * 2, 10), 36)
            ws.column_dimensions[get_column_letter(c)].width = width
        if rows:
            ws.auto_filter.ref = "A1:%s%d" % (get_column_letter(len(headers)), len(rows) + 1)
    wb.save(path)
    return True
