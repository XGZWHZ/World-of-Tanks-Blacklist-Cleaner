# 坦克世界黑名单清理工具（WoT Blacklist Cleaner）

一个面向《坦克世界》（World of Tanks）的本地工具：把游戏内黑名单导出成表格，按“最后战斗时间”找出长期不上线的人，按名单批量清理，并输出可审计的删除报告。

> ⚠️ 仅操作“黑名单（忽略列表）”，不会影响好友。所有数据保存在本地，不上传。
> 批量删除有风险，建议先用小名单验证。

---

## 功能

| 步骤 | 工具 | 说明 |
| --- | --- | --- |
| 1 | `1_环境检查.bat` | 检测 Python；没有则调用包内安装包静默安装；打印环境报告 |
| 2 | `2_安装MOD.bat` | 自动识别游戏目录与客户端版本，把 MOD 装进 `mods/<版本>/` |
| 3 | `3_在线查询黑名单最后战斗时间.bat` | 用官网公开页面补全最后战斗时间（国服/美服/欧服/亚服） |
| 4 | `4_查看黑名单.bat` | 生成 `黑名单列表.xlsx` |
| 5 | `5_清理黑名单中长期不在线玩家.bat` | 筛选 / 部署删除 / 生成删除报告 |

- 支持区服：国服 `wotgame.cn`、美服 `worldoftanks.com`、欧服 `worldoftanks.eu`、亚服 `worldoftanks.asia`
- 外部工具**零第三方依赖**：Python 3.8+ 即可；没有 openpyxl 时用内置 `mini_xlsx` 直接写 xlsx
- 查询调度：异步 IO + 全局令牌桶 + AIMD 动态调速 + 随机抖动

---

## 目录结构

```
.
├─ 1_环境检查.bat / 2_安装MOD.bat / 3_... / 4_... / 5_...
├─ mod/blacklist_exporter_2.0.2.wotmod   游戏内 MOD（已编译）
├─ src/                                  MOD 源码（与 .pyc 对应）
│  ├─ meta.xml
│  └─ res/scripts/client/gui/mods/*.py
├─ build_mod.py                          重新编译并打包 wotmod
├─ tools/                                外部脚本源码
├─ docs/
│  ├─ 坦克世界黑名单工具说明.docx        使用说明（含 .wotmod 打包）
│  └─ 代码原理详解.docx                  逐函数算法说明
├─ 使用效果/                             界面截图
└─ ——使用前请先阅读——.txt
```

---

## 快速开始

1. 解压，双击 `1_环境检查.bat`（没装 Python 会自动安装）。
2. 双击 `2_安装MOD.bat`，启动游戏进车库，等约 20 秒，生成 `blacklist_export.json`。
3. 双击 `3_在线查询黑名单最后战斗时间.bat`，首次选择区服，等待查询完成。
4. 双击 `4_查看黑名单.bat` 查看结果。
5. 双击 `5_清理黑名单中长期不在线玩家.bat`，先预览，再部署删除。

详细步骤见 `docs/坦克世界黑名单工具说明.docx`。

---

## MOD 源码与打包

`src/` 是 `mod/*.wotmod` 内 `.pyc` 的源码，二者字节码逐项比对一致。修改后重新打包：

```bash
# 需要 Python 2.7（客户端同版本）
python build_mod.py --py27 D:\Python27\python.exe
```

打包要点（详见使用说明第七章）：

1. 客户端只加载 `.pyc`（Python 2.7，magic `03 f3 0d 0a`）；
2. ZIP 必须 **STORED（不压缩）**，deflate 会报 `compression not supported`；
3. `meta.xml` 必须在包根目录，描述建议纯 ASCII；
4. 安装目录名必须等于 `version.xml` 的版本（如 `2.4.1.1`）。

---

## 技术要点

- 黑名单存在服务器联系人服务（XMPP block list），本地只有加密缓存；
- 客户端接口：`descriptor._STORAGE[UsersStorage]` 取联系人，
  `Account.requestPlayerInfo` 取档案，`contacts.removeIgnored(dbID, False)` 删除；
- 档案时间：`dossiers2.getAccountDossierDescr(dossier)['total']['lastBattleTime']`。

详见 `docs/代码原理详解.docx`。

---

## 免责声明

本项目仅供学习与个人管理使用。客户端 MOD 属非官方修改，存在版本失效与规则风险；使用造成的任何后果由使用者自行承担。

技术支持：DeepSeek DSH














# WoT Blacklist Cleaner

A local tool for *World of Tanks*: export your in-game blacklist to a spreadsheet, identify players who have been offline for a long time based on their "last battle time", clean them up in batches by list, and output an auditable deletion report.

> ⚠️ This tool only operates on the "blacklist (ignore list)" and will not affect friends. All data stays local and is not uploaded.
> Batch deletion carries risks. It is recommended to verify with a small list first.

---

## Features

| Step | Tool | Description |
| --- | --- | --- |
| 1 | `1_环境检查.bat` | Checks for Python; if missing, silently installs it using the bundled installer; prints an environment report |
| 2 | `2_安装MOD.bat` | Automatically detects the game directory and client version, and installs the MOD into `mods/<version>/` |
| 3 | `3_在线查询黑名单最后战斗时间.bat` | Uses official public pages to fill in last battle time (CN/NA/EU/ASIA) |
| 4 | `4_查看黑名单.bat` | Generates `黑名单列表.xlsx` |
| 5 | `5_清理黑名单中长期不在线玩家.bat` | Filters / deploys deletions / generates a deletion report |

- Supported regions: CN `wotgame.cn`, NA `worldoftanks.com`, EU `worldoftanks.eu`, ASIA `worldoftanks.asia`
- External tools have **zero third-party dependencies**: Python 3.8+ is sufficient; when `openpyxl` is unavailable, the built-in `mini_xlsx` is used to write xlsx directly
- Query scheduling: async I/O + global token bucket + AIMD dynamic rate adjustment + random jitter

---

## Directory Structure

```
.
├─ 1_环境检查.bat / 2_安装MOD.bat / 3_... / 4_... / 5_...
├─ mod/blacklist_exporter_2.0.2.wotmod   In-game MOD (compiled)
├─ src/                                  MOD source code (corresponds to .pyc)
│  ├─ meta.xml
│  └─ res/scripts/client/gui/mods/*.py
├─ build_mod.py                          Recompile and package the wotmod
├─ tools/                                External script source code
├─ docs/
│  ├─ 坦克世界黑名单工具说明.docx        User guide (including .wotmod packaging)
│  └─ 代码原理详解.docx                  Function-by-function algorithm explanation
├─ 使用效果/                             UI screenshots
└─ ——使用前请先阅读——.txt
```

---

## Quick Start

1. Extract the archive and double-click `1_环境检查.bat` (Python will be installed automatically if missing).
2. Double-click `2_安装MOD.bat`, launch the game and enter the garage, then wait about 20 seconds for `blacklist_export.json` to be generated.
3. Double-click `3_在线查询黑名单最后战斗时间.bat`, select your region on first run, and wait for the query to finish.
4. Double-click `4_查看黑名单.bat` to view the results.
5. Double-click `5_清理黑名单中长期不在线玩家.bat`; preview first, then deploy deletions.

For detailed steps, see `docs/坦克世界黑名单工具说明.docx`.

---

## MOD Source and Packaging

`src/` contains the source code for the `.pyc` files inside `mod/*.wotmod`; the bytecode has been compared item by item and matches. To repackage after modification:

```bash
# Requires Python 2.7 (same version as the client)
python build_mod.py --py27 D:\Python27\python.exe
```

Packaging notes (see Chapter 7 of the user guide for details):

1. The client only loads `.pyc` files (Python 2.7, magic `03 f3 0d 0a`);
2. The ZIP must use **STORED (no compression)**; deflate will cause `compression not supported`;
3. `meta.xml` must be in the package root; the description should preferably be pure ASCII;
4. The installation directory name must equal the version in `version.xml` (e.g. `2.4.1.1`).

---

## Technical Notes

- The blacklist is stored in the server-side contacts service (XMPP block list); locally there is only an encrypted cache;
- Client APIs: use `descriptor._STORAGE[UsersStorage]` to get contacts,
  `Account.requestPlayerInfo` to get profiles, and `contacts.removeIgnored(dbID, False)` to delete;
- Dossier time: `dossiers2.getAccountDossierDescr(dossier)['total']['lastBattleTime']`.

See `docs/代码原理详解.docx` for details.

---

## Disclaimer

This project is for learning and personal management purposes only. Client MODs are unofficial modifications and carry risks of version breakage and rule violations; any consequences arising from use are borne solely by the user.

Powered by DeepSeek DSH
```

