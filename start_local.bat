@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo LINE Bot ローカル起動中...
python start_local.py
pause
