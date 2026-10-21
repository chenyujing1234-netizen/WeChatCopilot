@echo off
rem WeChat chat sorter GUI launcher (tools\chat_sorter)
rem Prefers the repo virtualenv, falls back to system python.
setlocal
set "TOOL_DIR=%~dp0"
set "PY=%TOOL_DIR%..\..\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" "%TOOL_DIR%chat_sorter_gui.py" %*
if errorlevel 1 pause
endlocal



