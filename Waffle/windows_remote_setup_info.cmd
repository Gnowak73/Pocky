@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "PS_SCRIPT=%SCRIPT_DIR%windows_remote_setup_info.ps1"
set "WAFFLE_V2=%SCRIPT_DIR%waffle_v2"

echo WAFFLE remote setup info
echo.

if not exist "%PS_SCRIPT%" (
    echo Could not find PowerShell helper:
    echo   %PS_SCRIPT%
    echo.
    pause
    exit /b 1
)

if exist "%WAFFLE_V2%\near_realtime_aia_pipeline.py" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%PS_SCRIPT%" -WafflePath "%WAFFLE_V2%"
) else (
    echo Could not auto-detect waffle_v2 at:
    echo   %WAFFLE_V2%
    echo.
    echo Running helper without WafflePath. If it prints REMOTE_WAFFLE_V2_PATH,
    echo run the .ps1 manually with -WafflePath set to the real path.
    echo.
    powershell -NoProfile -ExecutionPolicy Bypass -File "%PS_SCRIPT%"
)

echo.
echo Done. Copy the printed commands to the local/control computer.
echo This window will stay open so the output can be read.
echo.
pause
