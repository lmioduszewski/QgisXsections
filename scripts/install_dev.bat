@echo off
rem Development install: links the plugin folder into the default QGIS 4 profile with a
rem directory junction (no copy, no admin rights). Edits in the repo show up in QGIS after a
rem restart, or at once with the Plugin Reloader plugin.
rem Refuses if anything named "xsections" is already in the plugins folder.
rem Undo with scripts\uninstall_dev.bat.
setlocal

for %%I in ("%~dp0..\xsections") do set "SRC=%%~fI"
set "PLUGINS=%APPDATA%\QGIS\QGIS4\profiles\default\python\plugins"
set "DEST=%PLUGINS%\xsections"

if not exist "%SRC%\metadata.txt" goto :no_source
if not exist "%PLUGINS%" goto :make_plugins
if exist "%DEST%" goto :taken
rem a junction whose target is gone fails "if exist", so also look for a link of that name
dir /AL /B "%PLUGINS%" 2>nul | findstr /I /X "xsections" >nul
if not errorlevel 1 goto :taken
goto :link

:make_plugins
echo Creating %PLUGINS%
mkdir "%PLUGINS%"
if errorlevel 1 goto :failed

:link
mklink /J "%DEST%" "%SRC%"
if errorlevel 1 goto :failed
echo.
echo XSections is linked into your QGIS 4 profile:
echo   %DEST%
echo   points to %SRC%
echo Start QGIS, then turn on XSections under Plugins ^> Manage and Install Plugins ^> Installed.
exit /b 0

:no_source
echo Cannot find the plugin folder (no metadata.txt in "%SRC%").
exit /b 1

:taken
echo Not installed: "%DEST%" already exists.
echo If it is an older copy of XSections, remove it first. A link made by this script is
echo removed by scripts\uninstall_dev.bat.
exit /b 1

:failed
echo Not installed: could not create "%DEST%".
exit /b 1
