@echo off
rem Runs the XSections test suite headless with QGIS 4 (OSGeo4W) in several processes at once.
rem Usage: scripts\run_tests_parallel.bat [--workers N] [--serial] [--plan] [unittest names, e.g. tests.test_scales]
rem No name = the whole suite in min(6, CPUs - 1) workers; the summary ends like unittest's ("Ran N tests" / "OK").
set QT_QPA_PLATFORM=offscreen
set QT_QPA_FONTDIR=C:\Windows\Fonts
set PYTHONDONTWRITEBYTECODE=1
set OSGEO4W=%LOCALAPPDATA%\Programs\OSGeo4W
pushd "%~dp0.."
call "%OSGEO4W%\bin\python-qgis.bat" "%~dp0run_tests_parallel.py" %*
set RC=%ERRORLEVEL%
popd
exit /b %RC%
