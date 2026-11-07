#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 mod/src 打包成 .wotmod。

客户端只认 .pyc，所以这里会调用本机 Python 2.7 把 .py 编译成 .pyc 再打包。
没有 2.7 时会退而打包 .py（大概率不会被加载），并给出提示。

用法：
  python build_mod.py                    # 自动找 mod/build/python27/python.exe
  python build_mod.py --py27 D:\\py27\\python.exe
"""

import argparse
import subprocess
import sys
import zipfile
from pathlib import Path

VERSION = "2.0.2"
ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
DIST = ROOT / "dist"
BUILD = ROOT / "build"

PYC_MAGIC_27 = b"\x03\xf3\r\n"


def find_py27(explicit: str) -> Path | None:
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    candidates += [
        BUILD / "py27home" / "python.exe",
        BUILD / "python27" / "python.exe",
        Path("C:/Python27/python.exe"),
        Path.home() / "AppData/Local/Programs/Python/Python27/python.exe",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def compile_pyc(py27: Path, src: Path, dst: Path) -> bool:
    dst.parent.mkdir(parents=True, exist_ok=True)
    code = (
        "import py_compile,sys;"
        "py_compile.compile(sys.argv[1], cfile=sys.argv[2], doraise=True);"
        "print('ok')"
    )
    proc = subprocess.run(
        [str(py27), "-c", code, str(src), str(dst)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        print(proc.stdout, proc.stderr)
        return False
    with open(dst, "rb") as fh:
        magic = fh.read(4)
    if magic != PYC_MAGIC_27:
        print(f"[错误] {dst.name} 魔数 {magic.hex()} 不是 Python 2.7 ({PYC_MAGIC_27.hex()})")
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--py27", default="", help="Python 2.7 解释器路径")
    args = parser.parse_args()

    if not (SRC / "meta.xml").exists():
        print(f"[错误] 找不到 {SRC / 'meta.xml'}")
        return 2

    py27 = find_py27(args.py27)
    if py27 is None:
        print("[错误] 没找到 Python 2.7，无法生成 .pyc。")
        print("       下载 https://www.python.org/ftp/python/2.7.18/python-2.7.18.amd64.msi")
        print("       解压到 mod/build/python27/ 后重试，或加 --py27 指定路径。")
        return 3
    print(f"[Python 2.7] {py27}")

    DIST.mkdir(exist_ok=True)
    out = DIST / f"blacklist_exporter_{VERSION}.wotmod"
    if out.exists():
        out.unlink()

    count = 0
    # 关键：客户端加载器不支持 deflate，必须 ZIP_STORED（不压缩）
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as zf:
        for path in sorted(SRC.rglob("*")):
            if path.is_dir():
                continue
            arc = path.relative_to(SRC).as_posix()
            if not (arc == "meta.xml" or arc.startswith("res/")):
                continue

            if path.suffix == ".py":
                # 编译成同名 .pyc，原 .py 不打包
                dst = BUILD / "pyc" / arc
                if not compile_pyc(py27, path, dst):
                    print(f"[错误] 编译失败：{arc}")
                    return 4
                if dst.read_bytes()[:4] != PYC_MAGIC_27:
                    print(f"[错误] 魔数不对：{arc}")
                    return 4
                zf.write(dst, arc + "c")
                print(f"  + {arc}c")
            elif path.suffix == ".pyc":
                continue
            else:
                zf.write(path, arc)
                print(f"  + {arc}")
            count += 1

    print(f"\n[完成] {out}  ({out.stat().st_size / 1024:.1f} KB, {count} 个文件)")
    print("安装：复制到 World_of_Tanks/mods/<客户端版本>/ 后重启游戏。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
