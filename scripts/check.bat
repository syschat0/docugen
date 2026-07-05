@echo off
setlocal
set "PROJECT_ROOT=%~dp0.."
set "VENV_PY=%PROJECT_ROOT%\.venv\Scripts\python.exe"

if not exist "%VENV_PY%" (
    echo .venv not found. Run scripts\setup.bat first.
    exit /b 1
)

pushd "%PROJECT_ROOT%" || exit /b 1
"%VENV_PY%" -m compileall app
if errorlevel 1 exit /b 1
"%VENV_PY%" -m pytest tests -q
if errorlevel 1 exit /b 1
"%VENV_PY%" -c "from app.db.session import init_db; init_db(); from app.main import app; print('check ok')"
set "STATUS=%ERRORLEVEL%"
popd
exit /b %STATUS%
