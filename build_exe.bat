@echo off
rem Aura Motion EXE Builder
echo ------------------------------------------
echo   Aura Motion EXE Builder
echo ------------------------------------------

rem 1. Install dependencies
echo [*] Installing requirements...
python -m pip install flask requests pyinstaller --quiet

rem 2. Cleanup
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

rem 3. Build EXE
echo [*] Building EXE... This may take a minute...
python -m pyinstaller --onefile --add-data "templates;templates" --add-data "wan_api_aura.json;." --name Aura_Motion app.py

if %errorlevel% neq 0 (
    echo [!] ERROR: Build failed.
) else (
    echo ------------------------------------------
    echo   SUCCESS! 
    echo   Aura_Motion.exe is in the "dist" folder.
    echo ------------------------------------------
)
pause
