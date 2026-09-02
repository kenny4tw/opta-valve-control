@echo off
setlocal
cd /d "%~dp0"

if not exist .venv (
  py -m venv .venv
)

call .venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller

pyinstaller --noconfirm --clean --onefile --windowed --name OptaValveDashboardStandalone --add-data "templates;templates" --add-data "static;static" standalone_dashboard_gui.py

echo.
echo Build complete.
echo EXE: %CD%\dist\OptaValveDashboardStandalone.exe
echo.
pause
