@echo off
rem Double-click this to reach the review queue (docs/vps-deployment.md).
rem It opens the ssh tunnel in its own window and then opens the browser.
rem Closing that window ends the tunnel.
setlocal
if "%JOBDISCO_VPS%"=="" (set HOST=ubuntu@40.160.142.175) else (set HOST=%JOBDISCO_VPS%)
if "%JOBDISCO_VPS_KEY%"=="" (set KEY=%USERPROFILE%\.ssh\op1m_vps) else (set KEY=%JOBDISCO_VPS_KEY%)

start "op1m review tunnel" cmd /k ssh -N -L 8765:127.0.0.1:8765 -i "%KEY%" %HOST%
timeout /t 2 /nobreak >nul
start "" http://localhost:8765
