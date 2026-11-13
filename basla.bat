@echo off
rem Tralala serverini başladır. Bu fayla iki dəfə klikləmək kifayətdir.
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo .venv tapilmadi. Bu faylin Tralala qovlugunda oldugunu yoxlayin.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" main.py
pause
