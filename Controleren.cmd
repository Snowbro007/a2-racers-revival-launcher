@echo off
setlocal DisableDelayedExpansion
set "root=%~dp0"
set "powershell=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"

if not exist "%root%release-manifest.json" goto :incomplete
if not exist "%root%tools\Show-A2Launcher.ps1" goto :incomplete
if not exist "%powershell%" goto :missingpowershell

echo A2 Racers Revival controleert de launcher en spelbestanden...
"%powershell%" -NoLogo -NoProfile -STA -ExecutionPolicy Bypass -File "%root%tools\Show-A2Launcher.ps1" -CheckOnly
if "%errorlevel%"=="0" (
    echo.
    echo Controle geslaagd. Druk op een toets om dit venster te sluiten.
    pause >nul
    exit /b 0
)
echo.
echo Controle mislukt. Maak een foto van de foutmelding hierboven.
goto :failed

:incomplete
echo Pak eerst de hele ZIP uit met "Alles uitpakken...".
goto :failed

:missingpowershell
echo Windows PowerShell ontbreekt. Deze launcher is gemaakt voor Windows 11.

:failed
echo.
pause
exit /b 1
