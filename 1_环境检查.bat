@echo off
chcp 65001 >nul
title 坦克世界黑名单 - 环境检查
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "PY="
python --version >nul 2>nul && set "PY=python"
if not defined PY (
  py -3 --version >nul 2>nul && set "PY=py -3"
)
if defined PY goto run_check

echo ================================================
echo   没有检测到 Python，正在用工具包里的安装包安装
echo ================================================
set "INSTALLER="
for %%f in ("%~dp0python-*-amd64.exe") do set "INSTALLER=%%~ff"
if not defined INSTALLER (
  echo [错误] 根目录没有 python-*-amd64.exe
  echo 请手动安装 https://www.python.org/downloads/
  echo 安装时务必勾选 Add python.exe to PATH
  pause
  exit /b 1
)
echo 安装包：!INSTALLER!
echo 正在静默安装（约 1-3 分钟）...
"!INSTALLER!" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0 Include_pip=1
if errorlevel 1 (
  echo [错误] 安装失败，请手动安装。
  pause
  exit /b 1
)

echo 安装完成，重新检测...
set "PY="
python --version >nul 2>nul && set "PY=python"
if not defined PY (
  for /d %%d in ("%LOCALAPPDATA%\Programs\Python\Python3*") do set "PY=%%~d\python.exe"
)
if not defined PY (
  py -3 --version >nul 2>nul && set "PY=py -3"
)
if not defined PY (
  echo [提示] 已安装，但当前窗口还读不到 PATH。
  echo        请关掉本窗口重新双击；如果还不行，重启一次电脑。
  pause
  exit /b 1
)

:run_check
echo ================================================
echo   环境检查
echo ================================================
%PY% "%~dp0tools\doctor.py"
echo.
pause