@echo off
rem Removes the development link made by scripts\install_dev.bat. Only a junction or symbolic
rem link is removed (the repo is never touched); a real folder is left alone.
setlocal

set "PLUGINS=%APPDATA%\QGIS\QGIS4\profiles\default\python\plugins"
set "DEST=%PLUGINS%\xsections"

if not exist "%PLUGINS%" goto :nothing
dir /AL /B "%PLUGINS%" 2>nul | findstr /I /X "xsections" >nul
if errorlevel 1 goto :not_link

rem rmdir without /S on a junction removes the link only, never the files it points to
rmdir "%DEST%"
if errorlevel 1 goto :failed
echo Removed the link "%DEST%". Restart QGIS to unload the plugin.
exit /b 0

:not_link
if exist "%DEST%" goto :real_folder
:nothing
echo Nothing to remove: "%DEST%" does not exist.
exit /b 0

:real_folder
echo Not removed: "%DEST%" is a real folder, not a link made by install_dev.bat.
echo Remove it with the QGIS Plugin Manager (Uninstall) or by hand.
exit /b 1

:failed
echo Could not remove "%DEST%" (is QGIS running?).
exit /b 1
