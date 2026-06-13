@echo off
setlocal
cd /d "%~dp0"

echo =============================================
echo Video Rotate - Windows Setup
echo =============================================

py --version >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Python Launcher py not found.
  echo Install Python first: https://www.python.org/downloads/windows/
  pause
  exit /b 1
)

set "FFMPEG_LOCAL="
for %%F in ("%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_*\*\bin\ffmpeg.exe") do set "FFMPEG_LOCAL=%%~fF"

where ffmpeg >nul 2>&1
if errorlevel 1 (
  if not defined FFMPEG_LOCAL (
    echo ffmpeg not found. Installing via winget...
    winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
  )
)

echo.
echo Running self-check...
py -m py_compile "video_rotator.py"
if errorlevel 1 (
  echo [ERROR] Script check failed.
  pause
  exit /b 1
)

py "video_rotator.py" --help >nul
if errorlevel 1 (
  echo [ERROR] Program check failed.
  pause
  exit /b 1
)

py "video_rotator.py" --input "." --direction right >nul
if errorlevel 1 (
  echo [ERROR] ffmpeg check failed. Try opening a new terminal and run setup again.
  pause
  exit /b 1
)

echo.
echo [OK] Setup complete.
echo You can now run: run_rotate.bat
pause
