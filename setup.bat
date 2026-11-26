@echo off
title ARJUN Setup
color 0A
echo.
echo  =============================================
echo   ARJUN Local AI Assistant - Windows Setup
echo  =============================================
echo.

REM ── 1. Check Python ──
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python 3.10+ not found. Install from python.org
    pause & exit /b 1
)
echo [OK] Python found.

REM ── 2. Check Ollama ──
ollama --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Ollama not found. Download from https://ollama.com
    pause & exit /b 1
)
echo [OK] Ollama found.

REM ── 3. Install pip packages ──
echo.
echo [1/7] Installing Python packages...
pip install -r requirements.txt
pip install Pillow
if errorlevel 1 ( echo [ERROR] pip failed. & pause & exit /b 1 )
echo [OK] Packages installed.

REM ── 4. Create Ollama model ──
echo.
echo [2/7] Creating Arjun model in Ollama (downloads ~4GB if first time)...
ollama create arjun -f Modelfile
echo [OK] Arjun model ready.

REM ── 5. Download Piper voice model ──
echo.
echo [3/7] Downloading Piper TTS voice...
if not exist "piper_models" mkdir piper_models
curl -L -o piper_models\en_US-lessac-medium.onnx ^
  "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx"
curl -L -o piper_models\en_US-lessac-medium.onnx.json ^
  "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json"
echo [OK] Voice model downloaded.

REM ── 6. Download openwakeword model ──
echo.
echo [4/7] Downloading wake word model...
python -c "from openwakeword.utils import download_models; download_models(['hey_jarvis_v0.1'])"
if errorlevel 1 ( echo [ERROR] Wake word model download failed. & pause & exit /b 1 )
echo [OK] Wake word model ready.

REM ── 7. Generate icon ──
echo.
echo [5/7] Generating desktop icon...
python generate_icon.py
echo [OK] Icon generated.

REM ── 8. Create desktop + startup shortcuts ──
echo.
echo [6/7] Creating desktop shortcut and startup entry...
call create_shortcut.bat
echo [OK] Shortcuts created.

REM ── 9. Register startup listener ──
echo.
echo [7/7] Registering always-on wake word listener...
set ARJUN_DIR=%~dp0
set ARJUN_DIR=%ARJUN_DIR:~0,-1%
for /f "tokens=*" %%i in ('where pythonw.exe 2^>nul') do set PYTHONW=%%i
if "%PYTHONW%"=="" (
    for /f "tokens=*" %%i in ('where python.exe') do set PYTHONW=%%i
    set PYTHONW=%PYTHONW:python.exe=pythonw.exe%
)

REM Add startup listener to Windows registry (runs silently at login)
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" ^
    /v "ArjunListener" ^
    /t REG_SZ ^
    /d "\"%PYTHONW%\" \"%ARJUN_DIR%\startup_listener.py\"" ^
    /f >nul
echo [OK] Startup listener registered in Windows.

REM ── Create Projects folder ──
if not exist "%USERPROFILE%\Documents\ArjunProjects" (
    mkdir "%USERPROFILE%\Documents\ArjunProjects"
)

echo.
echo  =============================================
echo   Setup complete!
echo.
echo   1. Edit .env with your Telegram + Gmail creds
echo   2. Restart Windows (startup listener activates)
echo   3. Or double-click the Arjun icon on your desktop
echo   4. Say "Hey Jarvis" anytime to wake him up
echo  =============================================
echo.
pause
