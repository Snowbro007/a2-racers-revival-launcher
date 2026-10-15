@echo off
setlocal DisableDelayedExpansion
set "root=%~dp0"
set "script=%root%tools\Show-A2Launcher.ps1"
set "powershell=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"

if not exist "%root%release-manifest.json" goto :incomplete
if not exist "%script%" goto :incomplete
if not exist "%root%tools\launcher_common.ps1" goto :incomplete
if not exist "%root%tools\launcher_window.xaml" goto :incomplete

if not exist "%powershell%" (
    echo.
    echo A2 Racers Revival kan niet starten: Windows PowerShell ontbreekt.
    echo Deze launcher is gemaakt voor Windows 11.
    goto :failed
)

echo A2 Racers Revival wordt gestart...
echo De eerste voorbereiding kan even duren.
"%powershell%" -NoLogo -NoProfile -STA -ExecutionPolicy Bypass -File "%script%"
if "%errorlevel%"=="0" exit /b 0

echo.
echo De launcher is gestopt. De fout staat hierboven of in het foutvenster.
echo Maak een foto van de foutmelding als je hulp wilt.
goto :failed

:incomplete
echo.
echo A2 Racers Revival is niet volledig uitgepakt.
echo Rechtsklik op de gedownloade ZIP en kies "Alles uitpakken...".
echo Open daarna Launcher.cmd in de nieuwe map, niet vanuit de ZIP.

:failed
echo.
pause
exit /b 1
