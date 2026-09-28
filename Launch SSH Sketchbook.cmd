@echo off
cd /d "%~dp0"
py -3 app.py
if errorlevel 1 (
  echo.
  echo SSH Sketchbook could not start. See the error above.
  pause
)
