@echo off
echo Starting Jugabet servers...

start "Server 8000 - Events + Admin" cmd /k "cd /d %~dp0 && venv_win\Scripts\python -m uvicorn server:app --host 127.0.0.1 --port 8000 --reload"
timeout /t 2 /nobreak >nul

start "Server 8001 - Football" cmd /k "cd /d %~dp0 && venv_win\Scripts\python -m uvicorn render_server:app --host 127.0.0.1 --port 8001 --reload"
start "Server 8002 - Basketball" cmd /k "cd /d %~dp0 && venv_win\Scripts\python -m uvicorn basketball_render_server:app --host 127.0.0.1 --port 8002 --reload"
start "Server 8003 - Tennis" cmd /k "cd /d %~dp0 && venv_win\Scripts\python -m uvicorn tennis_render_server:app --host 127.0.0.1 --port 8003 --reload"
start "Server 8004 - Cybersport" cmd /k "cd /d %~dp0 && venv_win\Scripts\python -m uvicorn cybersport_render_server:app --host 127.0.0.1 --port 8004 --reload"
start "Server 8005 - Fights" cmd /k "cd /d %~dp0 && venv_win\Scripts\python -m uvicorn fights_render_server:app --host 127.0.0.1 --port 8005 --reload"

echo All servers starting...
echo.
echo Admin panel: http://127.0.0.1:8000/admin
echo Health check: http://127.0.0.1:8000/health
echo.
pause
