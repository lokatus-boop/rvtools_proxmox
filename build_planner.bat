@echo off
REM Genera dist\PVEMigrationPlanner.exe (GUI) y dist\pvemigplan-cli.exe (linea de comandos).
REM Requiere Python 3.10+ para Windows (python.org) instalado y en el PATH. Solo hace falta para compilar.
setlocal
cd /d "%~dp0"
python -m venv .venv-planner || goto :error
call .venv-planner\Scripts\activate.bat
python -m pip install --upgrade pip >nul
pip install -r requirements-planner.txt pyinstaller || goto :error
pyinstaller --noconfirm --clean --onefile --windowed --name PVEMigrationPlanner --icon pvetools/assets/fsas.ico --add-data "pvetools/assets;pvetools/assets" --exclude-module requests pvemigplan_gui.py || goto :error
pyinstaller --noconfirm --clean --onefile --console --name pvemigplan-cli --icon pvetools/assets/fsas.ico --add-data "pvetools/assets;pvetools/assets" --exclude-module requests pvemigplan_cli.py || goto :error
echo.
echo Listo: dist\PVEMigrationPlanner.exe y dist\pvemigplan-cli.exe
goto :eof
:error
echo Error durante la compilacion.
exit /b 1
