@echo off
setlocal
set "PROJECT_ROOT=%~dp0.."
pushd "%PROJECT_ROOT%" || exit /b 1

set "VENV_PY=%PROJECT_ROOT%\.venv\Scripts\python.exe"

if exist "%VENV_PY%" (
    "%VENV_PY%" -c "import sys" >nul 2>nul
    if errorlevel 1 (
        echo Existing .venv is not runnable. Recreating it.
        rmdir /s /q ".venv"
        if errorlevel 1 exit /b 1
        call :create_venv
        if errorlevel 1 exit /b 1
    ) else (
        echo .venv already exists
    )
) else (
    call :create_venv
    if errorlevel 1 exit /b 1
)

if not exist "%VENV_PY%" (
    echo Failed to create .venv.
    exit /b 1
)

if not exist ".env" (
    if exist ".env.example" (
        copy ".env.example" ".env" >nul
        if errorlevel 1 exit /b 1
        echo Created .env from .env.example
    )
)

if /I "%~1"=="--skip-install" goto initdb
"%VENV_PY%" -m pip install -r "requirements.txt"
if errorlevel 1 exit /b 1
"%VENV_PY%" -m playwright install chromium
if errorlevel 1 exit /b 1

:initdb
"%VENV_PY%" -c "from app.db.session import init_db; init_db(); print('database initialized')"
if errorlevel 1 exit /b 1

echo Setup complete
popd
exit /b 0

:create_venv
call :resolve_python
if errorlevel 1 exit /b 1
echo Creating .venv with "%PYTHON_EXE%"
"%PYTHON_EXE%" -m venv ".venv"
if errorlevel 1 exit /b 1
exit /b 0

:resolve_python
if not "%PYTHON_PATH%"=="" if exist "%PYTHON_PATH%" (
    set "PYTHON_EXE=%PYTHON_PATH%"
    exit /b 0
)

where python >nul 2>nul
if not errorlevel 1 (
    for /f "delims=" %%P in ('where python') do (
        set "PYTHON_EXE=%%P"
        exit /b 0
    )
)

where py >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_EXE=py"
    exit /b 0
)

set "CODEX_PY=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%CODEX_PY%" (
    set "PYTHON_EXE=%CODEX_PY%"
    exit /b 0
)

echo Python executable not found. Set PYTHON_PATH to a Python executable.
exit /b 1
