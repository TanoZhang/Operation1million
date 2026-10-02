@echo off
rem Double-click this to reach the review queue (docs/vps-deployment.md).
rem It opens the ssh tunnel in its own window and then opens the browser.
rem Closing that window ends the tunnel.
setlocal
call "%~dp0vps-env.bat"

start "op1m review tunnel" cmd /k ssh -N -L 8765:127.0.0.1:8765 -i "%KEY%" %HOST%
timeout /t 2 /nobreak >nul
start "" http://localhost:8765
