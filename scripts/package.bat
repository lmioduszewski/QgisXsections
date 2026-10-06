@echo off
rem Builds dist\xsections-<version>.zip for Plugins > Manage and Install Plugins > Install from ZIP.
rem Uses QGIS's Python from OSGeo4W when it is installed, else the Python launcher (py -3), else
rem python on PATH. Any Python 3.9+ works: scripts\package.py needs only the standard library.
rem Usage: scripts\package.bat [--out FOLDER]
setlocal
set "SCRIPT=%~dp0package.py"
set "QGISPY=%LOCALAPPDATA%\Programs\OSGeo4W\bin\python-qgis.bat"
if not exist "%QGISPY%" set "QGISPY=C:\OSGeo4W\bin\python-qgis.bat"
if exist "%QGISPY%" goto :qgis
where py >nul 2>nul
if not errorlevel 1 goto :launcher
python "%SCRIPT%" %*
exit /b %ERRORLEVEL%

:qgis
call "%QGISPY%" "%SCRIPT%" %*
exit /b %ERRORLEVEL%

:launcher
py -3 "%SCRIPT%" %*
exit /b %ERRORLEVEL%
