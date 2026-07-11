@echo off
setlocal
set "PROJECT_ROOT=%~dp0.."
set "VENV_PY=%PROJECT_ROOT%\.venv\Scripts\python.exe"
pushd "%PROJECT_ROOT%" || exit /b 1
"%VENV_PY%" "scripts\export_slm_candidate.py" %*
set "STATUS=%ERRORLEVEL%"
popd
exit /b %STATUS%
