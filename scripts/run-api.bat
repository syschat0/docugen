@echo off
setlocal
set "PROJECT_ROOT=%~dp0.."
set "VENV_PY=%PROJECT_ROOT%\.venv\Scripts\python.exe"
set "HOST_NAME=127.0.0.1"
set "PORT=8000"
set "RELOAD=--reload"

if not "%~1"=="" set "HOST_NAME=%~1"
if not "%~2"=="" set "PORT=%~2"
if /I "%~3"=="--no-reload" set "RELOAD="

if not exist "%VENV_PY%" (
    echo .venv not found. Run scripts\setup.bat first.
    exit /b 1
)

pushd "%PROJECT_ROOT%" || exit /b 1
echo Starting API at http://%HOST_NAME%:%PORT%
"%VENV_PY%" -m uvicorn app.main:app --host "%HOST_NAME%" --port "%PORT%" %RELOAD%
set "STATUS=%ERRORLEVEL%"
popd
exit /b %STATUS%
