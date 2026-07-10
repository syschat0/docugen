@echo off
setlocal
set "PROJECT_ROOT=%~dp0.."
set "VENV_PY=%PROJECT_ROOT%\.venv\Scripts\python.exe"

if not exist "%VENV_PY%" (
    echo .venv not found. Run scripts\setup.bat first.
    exit /b 1
)

pushd "%PROJECT_ROOT%" || exit /b 1
"%VENV_PY%" "scripts\benchmark_quality.py" %*
set "STATUS=%ERRORLEVEL%"
popd
exit /b %STATUS%
