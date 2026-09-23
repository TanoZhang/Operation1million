@echo off
rem Double-click: copy the VPS's data to this machine with
rem backup-from-vps.sh, into the same folder as every earlier backup
rem (%USERPROFILE%\op1m-backup unless JOBDISCO_BACKUP_DIR says otherwise).
rem The newest copy lands in current\, the one before it in previous\.
setlocal
cd /d "%~dp0..\.."
rem Git Bash only: the bash.exe in System32 is WSL, which cannot see this key.
set BASH=%ProgramFiles%\Git\bin\bash.exe
if not exist "%BASH%" set BASH=%LOCALAPPDATA%\Programs\Git\bin\bash.exe
if not exist "%BASH%" (
  echo Git Bash was not found. Install Git for Windows, or run deploy\local\backup-from-vps.sh from Git Bash.
  pause
  exit /b 1
)
set JOBDISCO_PYTHON=.venv/Scripts/python.exe
"%BASH%" ./deploy/local/backup-from-vps.sh
set CODE=%ERRORLEVEL%
echo.
if not "%CODE%"=="0" (echo Backup failed with exit code %CODE%.) else (echo Backup done.)
pause
