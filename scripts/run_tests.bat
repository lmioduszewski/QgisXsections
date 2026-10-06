@echo off
rem Runs the XSections test suite headless with QGIS 4 (OSGeo4W).
rem Usage: scripts\run_tests.bat [unittest args, e.g. tests.test_scales]
set QT_QPA_PLATFORM=offscreen
set QT_QPA_FONTDIR=C:\Windows\Fonts
set OSGEO4W=%LOCALAPPDATA%\Programs\OSGeo4W
pushd "%~dp0.."
if "%~1"=="" (
  call "%OSGEO4W%\bin\python-qgis.bat" -m unittest discover -s tests -t . -v
) else (
  call "%OSGEO4W%\bin\python-qgis.bat" -m unittest -v %*
)
set RC=%ERRORLEVEL%
popd
exit /b %RC%
