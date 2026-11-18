@echo off
setlocal
cd /d "%~dp0\..\backend"

where py >nul 2>nul
if %errorlevel%==0 (
  set PYTHON_CMD=py
) else (
  set PYTHON_CMD=python
)

if not exist .venv (
  %PYTHON_CMD% -m venv .venv || goto :error
)
call .venv\Scripts\activate.bat || goto :error
python -m pip install --upgrade pip || goto :error
pip install -r requirements.txt || goto :error

if not defined APP_ENV set APP_ENV=development
if not defined DATABASE_URL set DATABASE_URL=sqlite:///./epic.db
if not defined SECRET_KEY set SECRET_KEY=local-development-secret-change-before-production
set AUTO_CREATE_SCHEMA=false
if not defined ENFORCE_AUTHORIZATION set ENFORCE_AUTHORIZATION=false
if not defined ALLOWED_ORIGINS set ALLOWED_ORIGINS=["http://127.0.0.1:8000","http://localhost:8000"]
if not defined TRUSTED_HOSTS set TRUSTED_HOSTS=["127.0.0.1","localhost","testserver"]

alembic upgrade head || goto :error
echo.
echo EPIC is starting at http://127.0.0.1:8000
echo Press Ctrl+C to stop it.
echo.
start "" http://127.0.0.1:8000
uvicorn app.main:app --host 127.0.0.1 --port 8000
goto :eof

:error
echo.
echo EPIC could not start. Review the error above.
pause
exit /b 1
