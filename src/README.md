# MOD 源码说明

这里是与 `mod/blacklist_exporter_2.0.2.wotmod` 内 `.pyc` **一一对应**的源码。

已验证：用 Python 2.7 重新编译本目录的 `.py`，生成的字节码与 wotmod 内的 `.pyc`
逐项比对（co_code / co_names / co_varnames / co_consts）完全一致。

## 目录

```
src/
├─ meta.xml
└─ res/scripts/client/gui/mods/
   ├─ mod_blacklist_exporter.py    入口：导出名单、查档案、写 JSON
   └─ blacklist_delete.py          按名单删除、写删除报告
```

## 重新打包

在发布包根目录执行：

```bash
python build_mod.py
# 或指定 Python 2.7
python build_mod.py --py27 D:\Python27\python.exe
```

`build_mod.py` 会：

1. 用 Python 2.7 的 `py_compile` 把 `src/**/*.py` 编译成 `.pyc`；
2. 校验文件头是否为 `03 f3 0d 0a`；
3. 以 **ZIP_STORED**（不压缩）写入 `dist/blacklist_exporter_<版本>.wotmod`。

## 注意

- 客户端是 Python 2.7，不能用 Python 3 编译；
- 改完代码记得同步 `src/meta.xml` 里的 `<version>` 和 `build_mod.py` 的 `VERSION`；
- 安装时确认 `mods/<版本>/` 的目录名与游戏根目录 `version.xml` 一致。
