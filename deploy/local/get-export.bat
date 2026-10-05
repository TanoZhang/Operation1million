@echo off
rem Double-click after pressing E on the review page: copies the review
rem workbook from the VPS to one file on this computer, replacing the last copy.
rem Close it in Excel first; Windows will not replace a workbook Excel has open.
setlocal
call "%~dp0vps-env.bat"
if "%OPERATION1MILLION_EXPORT%"=="" (set TARGET=%USERPROFILE%\Documents\review-queue.xlsx) else (set TARGET=%OPERATION1MILLION_EXPORT%)

rem Read with sudo: the workbook belongs to the service user and is private.
rem Downloaded beside the target and moved over it only when complete.
ssh -i "%KEY%" %HOST% "sudo cat /opt/operation1million/exports/review-queue.xlsx" > "%TARGET%.part"
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
