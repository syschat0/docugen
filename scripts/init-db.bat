@echo off
setlocal
set "PROJECT_ROOT=%~dp0.."
set "VENV_PY=%PROJECT_ROOT%\.venv\Scripts\python.exe"

if not exist "%VENV_PY%" (
    echo .venv not found. Run scripts\setup.bat first.
    exit /b 1
)

pushd "%PROJECT_ROOT%" || exit /b 1
"%VENV_PY%" -c "from app.db.session import init_db; init_db(); print('database initialized')"
set "STATUS=%ERRORLEVEL%"
popd
exit /b %STATUS%
