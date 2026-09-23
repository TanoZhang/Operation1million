@echo off
rem Double-click: sync this checkout with GitHub (pull, then push anything
rem committed here), then deploy main to the VPS (docs/vps-deployment.md,
rem "Update"). It never commits for you; uncommitted edits stay local.
setlocal
cd /d "%~dp0..\.."
if "%JOBDISCO_VPS%"=="" (set HOST=ubuntu@40.160.142.175) else (set HOST=%JOBDISCO_VPS%)
if "%JOBDISCO_VPS_KEY%"=="" (set KEY=%USERPROFILE%\.ssh\op1m_vps) else (set KEY=%JOBDISCO_VPS_KEY%)

echo == Pull ==
git pull --ff-only origin main || goto failed
echo == Push ==
git push origin HEAD:main || goto failed
echo == Deploy ==
ssh -t -i "%KEY%" %HOST% "sudo bash /opt/jobdisco/code/deploy/vps/install.sh"
if errorlevel 1 goto failed
echo.
echo Done. The installer printed the commit it installed above.
pause
exit /b 0

:failed
echo.
echo Stopped with exit code %ERRORLEVEL%. 75 means a collection pass is running; try again after it ends.
pause
exit /b 1
