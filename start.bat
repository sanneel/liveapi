@echo off
:: Usage: start.bat [prod]
:: If "prod" is passed, run in production mode (secure settings, external host)

if "%1"=="prod" (
    echo Starting in PRODUCTION mode...
    set "APP_ENV=production"
    set "COOKIE_SECURE=True"
    set "LOG_LEVEL=INFO"
    set "HOST=0.0.0.0"
) else (
    echo Starting in DEVELOPMENT mode...
    set "APP_ENV=development"
    set "COOKIE_SECURE=False"
    set "LOG_LEVEL=DEBUG"
    set "HOST=127.0.0.1"
)

echo Starting Jugabet servers...

start "Server 8000 - Events + Admin" cmd /k "cd /d %~dp0 && venv_win\Scripts\activate && python -m uvicorn server:app --host %HOST% --port 8000"
timeout /t 2 /nobreak >nul

start "Server 8001 - Football" cmd /k "cd /d %~dp0 && venv_win\Scripts\activate && python -m uvicorn render_server:app --host %HOST% --port 8001"
start "Server 8002 - Basketball" cmd /k "cd /d %~dp0 && venv_win\Scripts\activate && python -m uvicorn basketball_render_server:app --host %HOST% --port 8002"
start "Server 8003 - Tennis" cmd /k "cd /d %~dp0 && venv_win\Scripts\activate && python -m uvicorn tennis_render_server:app --host %HOST% --port 8003"
start "Server 8004 - Cybersport" cmd /k "cd /d %~dp0 && venv_win\Scripts\activate && python -m uvicorn cybersport_render_server:app --host %HOST% --port 8004"
start "Server 8005 - Fights" cmd /k "cd /d %~dp0 && venv_win\Scripts\activate && python -m uvicorn fights_render_server:app --host %HOST% --port 8005"

echo All servers starting...
echo.
echo Admin panel: http://%HOST%:8000/admin
echo Health check: http://%HOST%:8000/health
echo.
pause
