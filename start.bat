@echo off
chcp 65001 >nul
title 行业投资日历系统
cd /d "%~dp0"
python launch.py
pause
