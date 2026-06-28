@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul

set "VERSION=1.1.0"
set "EXE_NAME=VIDEO-TOOLS-RUNNING.IN.TH-v%VERSION%"

echo ============================================
echo   Build: VIDEO-TOOLS - RUNNING.IN.TH v%VERSION%
echo ============================================
echo.

echo [1/3] Installing PyInstaller...
py -m pip install pyinstaller --quiet
if errorlevel 1 (
    echo ERROR: pip install failed.
    pause
    exit /b 1
)

echo [2/3] Building .exe...

set ADD_DATA=
if exist "logo.png"    set ADD_DATA=%ADD_DATA% --add-data "logo.png;."
if exist "favicon.ico" set ADD_DATA=%ADD_DATA% --add-data "favicon.ico;."

set ICON_FLAG=
if exist "favicon.ico" set ICON_FLAG=--icon "favicon.ico"

py -m PyInstaller ^
    --onefile ^
    --windowed ^
    %ICON_FLAG% ^
    %ADD_DATA% ^
    --name "!EXE_NAME!" ^
    video_rotator.py

if errorlevel 1 (
    echo.
    echo ERROR: Build failed.
    pause
    exit /b 1
)

echo.
echo [3/4] Signing .exe...

:: Find signtool.exe from Windows SDK
set "SIGNTOOL="
for /f "delims=" %%i in ('where signtool 2^>nul') do (
    if "!SIGNTOOL!"=="" set "SIGNTOOL=%%i"
)
if "!SIGNTOOL!"=="" (
    for /f "delims=" %%i in ('dir /b /s "C:\Program Files (x86)\Windows Kits\10\bin\*\x64\signtool.exe" 2^>nul') do (
        if "!SIGNTOOL!"=="" set "SIGNTOOL=%%i"
    )
)
if "!SIGNTOOL!"=="" (
    for /f "delims=" %%i in ('dir /b /s "C:\Program Files\Windows Kits\10\bin\*\x64\signtool.exe" 2^>nul') do (
        if "!SIGNTOOL!"=="" set "SIGNTOOL=%%i"
    )
)

if "!SIGNTOOL!"=="" (
    echo [SKIP] signtool.exe not found. Skipping signing.
    echo        Install Windows SDK to enable code signing.
    goto :done
)

if not exist "signing_cert.pfx" (
    echo [SKIP] signing_cert.pfx not found. Skipping signing.
    echo        Run create_cert.ps1 first to create a signing certificate.
    goto :done
)

set /p "SIGN_PASS=Enter signing_cert.pfx password (Enter to skip): "
if "!SIGN_PASS!"=="" (
    echo [SKIP] No password entered. Skipping signing.
    goto :done
)

"!SIGNTOOL!" sign ^
    /f "signing_cert.pfx" ^
    /p "!SIGN_PASS!" ^
    /fd SHA256 ^
    /td SHA256 ^
    /tr http://timestamp.sectigo.com ^
    /d "RUNNING.IN.TH Video Rotate" ^
    "dist\!EXE_NAME!.exe"

if errorlevel 1 (
    echo [WARN] Signing failed. .exe is still usable but unsigned.
) else (
    echo [OK] Signed successfully. Publisher: running.in.th
)

:done
echo.
echo [4/4] Done!
echo Output: dist\!EXE_NAME!.exe
echo.
pause
