@echo off
setlocal

set "ROOT_DIR=%~dp0.."
set "VENV_PYTHON=%ROOT_DIR%\.venv\Scripts\python.exe"

if not exist "%VENV_PYTHON%" (
  echo Missing virtual environment Python at "%VENV_PYTHON%"
  echo Create it with:
  echo   py -3 -m venv .venv
  echo   .venv\Scripts\pip install -r requirements.txt
  exit /b 1
)

pushd "%ROOT_DIR%"
"%VENV_PYTHON%" -m uvicorn app:app --host 127.0.0.1 --port 8000
set EXIT_CODE=%ERRORLEVEL%
popd

exit /b %EXIT_CODE%

