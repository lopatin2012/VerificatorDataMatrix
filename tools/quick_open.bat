@echo off
rem Drag an image onto this file: the GUI opens with it already analyzed.
setlocal
for %%I in ("%~dp0..") do set "ROOT=%%~fI"
set "PY=%ROOT%\.venv\Scripts\python.exe"
set "PYW=%ROOT%\.venv\Scripts\pythonw.exe"

if "%~1"=="" (
  echo Drag a DataMatrix image onto this file.
  pause
  exit /b 2
)
if not exist "%PY%" (
  echo Python venv not found: "%PY%"
  echo Install it with: .venv\Scripts\python.exe -m pip install -r requirements.txt
  pause
  exit /b 1
)
if not exist "%~1" (
  echo File not found: "%~1"
  pause
  exit /b 1
)

if exist "%PYW%" (
  start "" "%PYW%" "%ROOT%\main.py" --gui --file "%~1"
) else (
  start "" "%PY%" "%ROOT%\main.py" --gui --file "%~1"
)
exit /b 0
