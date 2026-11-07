@echo off
chcp 65001 >nul
title 坦克世界黑名单 - 清理长期不在线玩家
cd /d "%~dp0"
set "PY=python"
python --version >nul 2>nul
if errorlevel 1 set "PY=py -3"
%PY% --version >nul 2>nul
if errorlevel 1 (
  echo 没有找到 Python，请先双击 1_环境检查.bat 一键安装。
  pause
  exit /b 1
)
%PY% "%~dp0tools\clean_blacklist.py" %*
echo.
pause