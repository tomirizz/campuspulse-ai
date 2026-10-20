@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Сначала откройте «Запустить CampusPulse.bat».
  pause
  exit /b 1
)
.venv\Scripts\python.exe -m scripts.configure_gemini_gui
pause
