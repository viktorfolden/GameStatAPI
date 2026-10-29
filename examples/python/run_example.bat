@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "PROJECT_DIR=%%~fI"
set "PYTHON=%PROJECT_DIR%\.venv\Scripts\python.exe"

if "%~1"=="" set "ACTION=login"
if not "%~1"=="" set "ACTION=%~1"

if /i "%ACTION%"=="-h" goto help
if /i "%ACTION%"=="--help" goto help
if /i "%ACTION%"=="login" goto valid_action
if /i "%ACTION%"=="signup" goto valid_action
if /i "%ACTION%"=="submit" goto valid_action
if /i "%ACTION%"=="game" goto valid_action
if /i "%ACTION%"=="reset-password" goto valid_action

echo Usage: %~nx0 [login^|signup^|submit^|game^|reset-password] [options] 1>&2
exit /b 2

:help
echo Usage: %~nx0 [login^|signup^|submit^|game^|reset-password] [options] (default: login)
echo Reset password: requests an email code; --use-existing-code skips sending another.
echo Game: opens Orbit Defenders after interactive login/signup.
echo Submit options: --run-id UUID --score N --hits N --misses N --enemies-killed N --play-time-seconds N
echo Creates .venv if needed and installs the example's dependencies.
echo Override SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY, or GAME_API_URL via environment variables.
exit /b 0

:valid_action
if not defined SUPABASE_URL set "SUPABASE_URL=https://sghwafwnxfqcbdpiabnq.supabase.co"
if not defined SUPABASE_PUBLISHABLE_KEY set "SUPABASE_PUBLISHABLE_KEY=sb_publishable_4mmrRASle-Xv8l1-qJqQJA_srF6z1i4"
if not defined GAME_API_URL set "GAME_API_URL=https://viktor-game-api.onrender.com"

if exist "%PYTHON%" goto venv_ready
where py >nul 2>nul
if errorlevel 1 goto use_python
py -3 -m venv "%PROJECT_DIR%\.venv"
if errorlevel 1 goto failed
goto venv_ready

:use_python
python -m venv "%PROJECT_DIR%\.venv"
if errorlevel 1 goto failed

:venv_ready
if /i "%ACTION%"=="game" goto game

"%PYTHON%" -m pip install --quiet -r "%SCRIPT_DIR%requirements.txt"
if errorlevel 1 exit /b %errorlevel%
if "%~1"=="" goto default_login
"%PYTHON%" "%SCRIPT_DIR%game_client.py" %*
exit /b %errorlevel%

:default_login
"%PYTHON%" "%SCRIPT_DIR%game_client.py" login
exit /b %errorlevel%

:game
"%PYTHON%" -m pip install --quiet -r "%SCRIPT_DIR%requirements-game.txt"
if errorlevel 1 exit /b %errorlevel%
call :run_game %2 %3 %4 %5 %6 %7 %8 %9
exit /b %errorlevel%

:run_game
"%PYTHON%" "%SCRIPT_DIR%space_demo.py" %*
exit /b %errorlevel%

:failed
exit /b %errorlevel%
