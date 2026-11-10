@echo off
REM Genera dist\PVEInventory.exe (GUI) y dist\pveinventory-cli.exe (linea de comandos).
REM Requiere Python 3.10+ para Windows (python.org) instalado y en el PATH. Solo hace falta para compilar.
setlocal
cd /d "%~dp0"
python -m venv .venv || goto :error
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip >nul
pip install -r requirements.txt pyinstaller || goto :error
pyinstaller --noconfirm --clean --onefile --windowed --name PVEInventory pveinventory_gui.py || goto :error
pyinstaller --noconfirm --clean --onefile --console --name pveinventory-cli pveinventory_cli.py || goto :error
echo.
echo Listo: dist\PVEInventory.exe y dist\pveinventory-cli.exe
goto :eof
:error
echo Error durante la compilacion.
exit /b 1
