@echo off
rem Drag an image onto this file: prints the console report for every code.
setlocal
for %%I in ("%~dp0..") do set "ROOT=%%~fI"
set "PY=%ROOT%\.venv\Scripts\python.exe"

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

"%PY%" -X utf8 "%ROOT%\main.py" --file "%~1"
echo.
pause
