@echo off
chcp 65001 >nul
title 行业投资日历系统
cd /d "%~dp0"

:: 优先使用正确的 Python 路径（绕过 Microsoft Store 重定向器）
set "PYTHON_DIR=%LOCALAPPDATA%\Programs\Python\Python312"
if exist "%PYTHON_DIR%\python.exe" (
    "%PYTHON_DIR%\python.exe" launch.py
) else (
    python launch.py
)
pause
