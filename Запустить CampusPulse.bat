@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  py -3.11 -m venv .venv
  if errorlevel 1 goto failure
  .venv\Scripts\python.exe -m pip install -r requirements.lock
  if errorlevel 1 goto failure
)
.venv\Scripts\python.exe -c "import reportlab, tzdata" >nul 2>nul
if errorlevel 1 (
  .venv\Scripts\python.exe -m pip install -r requirements.lock
  if errorlevel 1 goto failure
)
if not exist .env copy .env.example .env >nul
.venv\Scripts\python.exe scripts\start_web.py
if errorlevel 1 goto failure
exit /b 0
:failure
echo Не удалось запустить CampusPulse. Сохраните текст ошибки выше.
pause
exit /b 1
