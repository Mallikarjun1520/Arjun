@echo off
title Creating ARJUN Desktop Shortcut
echo.
echo Creating ARJUN desktop icon...

REM Get the current directory (where arjun files are)
set ARJUN_DIR=%~dp0
set ARJUN_DIR=%ARJUN_DIR:~0,-1%

REM Get pythonw.exe path
for /f "tokens=*" %%i in ('where pythonw.exe 2^>nul') do set PYTHONW=%%i
if "%PYTHONW%"=="" (
    REM Fall back to python.exe location and swap
    for /f "tokens=*" %%i in ('where python.exe') do set PYTHONW=%%i
    set PYTHONW=%PYTHONW:python.exe=pythonw.exe%
)

REM Create the VBScript that makes the shortcut
set VBSCRIPT=%TEMP%\make_arjun_shortcut.vbs
(
echo Set oWS = WScript.CreateObject^("WScript.Shell"^)
echo sLinkFile = oWS.SpecialFolders^("Desktop"^) ^& "\Arjun.lnk"
echo Set oLink = oWS.CreateShortcut^(sLinkFile^)
echo oLink.TargetPath = "%PYTHONW%"
echo oLink.Arguments = """%ARJUN_DIR%\launcher.pyw"""
echo oLink.WorkingDirectory = "%ARJUN_DIR%"
echo oLink.WindowStyle = 7
echo oLink.Description = "ARJUN AI Assistant"
echo oLink.IconLocation = "%ARJUN_DIR%\arjun_icon.ico,0"
echo oLink.Save
) > "%VBSCRIPT%"

cscript //nologo "%VBSCRIPT%"
del "%VBSCRIPT%"

echo.
echo [OK] Desktop shortcut "Arjun" created.
echo      Double-click it to launch Arjun silently.
echo.

REM Also create startup shortcut so Arjun starts with Windows
set STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
(
echo Set oWS = WScript.CreateObject^("WScript.Shell"^)
echo sLinkFile = "%STARTUP_DIR%\Arjun.lnk"
echo Set oLink = oWS.CreateShortcut^(sLinkFile^)
echo oLink.TargetPath = "%PYTHONW%"
echo oLink.Arguments = """%ARJUN_DIR%\launcher.pyw"""
echo oLink.WorkingDirectory = "%ARJUN_DIR%"
echo oLink.WindowStyle = 7
echo oLink.Description = "ARJUN AI Assistant"
echo oLink.IconLocation = "%ARJUN_DIR%\arjun_icon.ico,0"
echo oLink.Save
) > "%VBSCRIPT%"

cscript //nologo "%VBSCRIPT%"
del "%VBSCRIPT%"

echo [OK] Startup shortcut created.
echo      Arjun will now start automatically when Windows boots.
echo.
pause
