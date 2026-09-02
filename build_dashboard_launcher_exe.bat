@echo off
setlocal
cd /d "%~dp0"

if not exist .venv (
  py -m venv .venv
)

call .venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install pyinstaller

pyinstaller --noconfirm --clean --onefile --windowed --name OptaValveDashboardLauncher dashboard_launcher_gui.py

echo.
echo Build complete.
echo EXE: %CD%\dist\OptaValveDashboardLauncher.exe
echo.
pause
