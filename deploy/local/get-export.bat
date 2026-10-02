@echo off
rem Double-click after pressing E on the review page: copies the review
rem workbook from the VPS to one file on this computer, replacing the last copy.
rem Close it in Excel first; Windows will not replace a workbook Excel has open.
setlocal
if "%JOBDISCO_VPS%"=="" (set HOST=ubuntu@40.160.142.175) else (set HOST=%JOBDISCO_VPS%)
rem The VPS key: JOBDISCO_VPS_KEY, else op1m_vps, else op1m_laptop.
set KEY=%JOBDISCO_VPS_KEY%
if "%KEY%"=="" set KEY=%USERPROFILE%\.ssh\op1m_vps
if not exist "%KEY%" if exist "%USERPROFILE%\.ssh\op1m_laptop" set KEY=%USERPROFILE%\.ssh\op1m_laptop
if "%JOBDISCO_EXPORT%"=="" (set TARGET=%USERPROFILE%\Documents\review-queue.xlsx) else (set TARGET=%JOBDISCO_EXPORT%)

rem Read with sudo: the workbook belongs to the service user and is private.
rem Downloaded beside the target and moved over it only when complete.
ssh -i "%KEY%" %HOST% "sudo cat /opt/jobdisco/exports/review-queue.xlsx" > "%TARGET%.part"
if errorlevel 1 goto failed
move /y "%TARGET%.part" "%TARGET%" >nul
if errorlevel 1 goto failed
echo Saved to %TARGET%
pause
exit /b 0

:failed
del "%TARGET%.part" 2>nul
echo.
echo Not copied. Press E on the review page first, and close the workbook in Excel.
pause
exit /b 1
