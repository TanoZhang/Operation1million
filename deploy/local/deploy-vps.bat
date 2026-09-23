@echo off
rem Double-click this to deploy whatever is on main to the VPS
rem (docs/vps-deployment.md, "Update"). The installer prints the commit it
rem installed; the window stays open so you can read it.
setlocal
if "%JOBDISCO_VPS%"=="" (set HOST=ubuntu@40.160.142.175) else (set HOST=%JOBDISCO_VPS%)
if "%JOBDISCO_VPS_KEY%"=="" (set KEY=%USERPROFILE%\.ssh\op1m_vps) else (set KEY=%JOBDISCO_VPS_KEY%)

ssh -t -i "%KEY%" %HOST% "sudo bash /opt/jobdisco/code/deploy/vps/install.sh"
echo.
echo Deployment finished with exit code %ERRORLEVEL%. Exit code 75 means a collection pass is running; try again after it ends.
pause
