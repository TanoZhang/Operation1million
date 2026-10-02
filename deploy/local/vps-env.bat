@echo off
rem Sets HOST and KEY for the scripts beside this one, which `call` it after
rem their own setlocal. One copy of the choice instead of three.
rem The VPS: JOBDISCO_VPS, else the production host.
rem The key: JOBDISCO_VPS_KEY, else op1m_vps, else op1m_laptop -- the name
rem the key has on the laptop, which has no op1m_vps (2026-10-01).
if "%JOBDISCO_VPS%"=="" (set HOST=ubuntu@40.160.142.175) else (set HOST=%JOBDISCO_VPS%)
set KEY=%JOBDISCO_VPS_KEY%
if "%KEY%"=="" set KEY=%USERPROFILE%\.ssh\op1m_vps
if not exist "%KEY%" if exist "%USERPROFILE%\.ssh\op1m_laptop" set KEY=%USERPROFILE%\.ssh\op1m_laptop
