@echo off
rem Double-click: test, commit whatever Claude and Codex changed, sync with
rem GitHub, deploy main to the VPS and show the commit it is running.
rem Stops at the first step that fails; nothing is deployed after a failure.
setlocal
cd /d "%~dp0..\.."
if "%JOBDISCO_VPS%"=="" (set HOST=ubuntu@40.160.142.175) else (set HOST=%JOBDISCO_VPS%)
if "%JOBDISCO_VPS_KEY%"=="" (set KEY=%USERPROFILE%\.ssh\op1m_vps) else (set KEY=%JOBDISCO_VPS_KEY%)
rem Where new files may be added from. Anything new elsewhere stays untracked.
set NEW_PATHS=src tests docs data/config deploy AGENTS.md CLAUDE.md README.md CONTEXT.md pyproject.toml requirements.txt .gitattributes .gitignore

echo == 1. Status ==
git status --short || goto failed

echo == 2. Tests ==
set PYTHONPATH=src
.venv\Scripts\python.exe -m unittest discover -s tests || goto failed

echo == 3-4. Stage ==
git add -u || goto failed
git add -- %NEW_PATHS% || goto failed

echo == 5. Commit ==
git diff --cached --quiet
if not errorlevel 1 (
  echo Nothing to commit.
  goto pull
)
rem Outside any parentheses, so STAMP is read after it is set.
for /f "delims=" %%T in ('powershell -NoProfile -Command "Get-Date -Format 'yyyy-MM-dd HH:mm'"') do set STAMP=%%T
git commit -m "auto deploy %STAMP%" || goto failed

:pull

echo == 6. Pull ==
git pull --rebase origin main
if errorlevel 1 (
  git rebase --abort 2>nul
  echo Pull conflicted with GitHub; nothing was pushed. Resolve it, or ask Claude or Codex.
  goto failed
)

echo == 7. Push ==
git push origin HEAD:main || goto failed

echo == 8. Deploy ==
ssh -t -i "%KEY%" %HOST% "sudo bash /opt/jobdisco/code/deploy/vps/install.sh" || goto failed

echo == 9. Deployed commit ==
for /f "delims=" %%C in ('git rev-parse --short HEAD') do set LOCAL=%%C
for /f "delims=" %%C in ('ssh -i "%KEY%" %HOST% "sudo -u jobdisco git -C /opt/jobdisco/code rev-parse --short HEAD"') do set REMOTE=%%C
echo Pushed:   %LOCAL%
echo On VPS:   %REMOTE%
if /i "%LOCAL%"=="%REMOTE%" (echo OK: the VPS runs what was pushed.) else (echo WARNING: the VPS is not on the pushed commit.)
pause
exit /b 0

:failed
echo.
echo Stopped with exit code %ERRORLEVEL%. 75 at the deploy step means a collection pass is running; try again after it ends.
pause
exit /b 1
