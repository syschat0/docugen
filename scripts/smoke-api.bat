@echo off
setlocal
set "PROJECT_ROOT=%~dp0.."
set "VENV_PY=%PROJECT_ROOT%\.venv\Scripts\python.exe"
set "HOST_NAME=127.0.0.1"
set "PORT=8765"

if not "%~1"=="" set "HOST_NAME=%~1"
if not "%~2"=="" set "PORT=%~2"

if not exist "%VENV_PY%" (
    echo .venv not found. Run scripts\setup.bat first.
    exit /b 1
)

pushd "%PROJECT_ROOT%" || exit /b 1
"%VENV_PY%" "scripts\smoke_api.py" "%HOST_NAME%" "%PORT%"
set "STATUS=%ERRORLEVEL%"
popd
exit /b %STATUS%

