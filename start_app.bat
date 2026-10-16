@echo off
rem WeChatDataAnalysis desktop launcher
rem Sets a longer backend startup timeout, then runs the full dev stack
rem (frontend :3000 + backend :10392 + Electron window).

cd /d e:\Source\WeChatDataAnalysis\desktop
if errorlevel 1 (
  echo [ERROR] Cannot find e:\Source\WeChatDataAnalysis\desktop
  pause
  exit /b 1
)

set WECHAT_TOOL_BACKEND_STARTUP_TIMEOUT_MS=180000
echo Starting WeChatDataAnalysis (frontend + backend + Electron)...
echo Press Ctrl+C in this window to stop the app.
echo.

call npm run dev

echo.
echo App stopped.
pause
