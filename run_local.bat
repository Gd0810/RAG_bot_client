@echo off
cd /d "%~dp0"

if exist "env\Scripts\activate.bat" (
    call "env\Scripts\activate.bat"
)

rem Open the local site over HTTP after Django has had time to start.
start "" powershell -NoProfile -Command "Start-Sleep -Seconds 2; Start-Process 'http://127.0.0.1:8000/'"

if exist "env\Scripts\python.exe" (
    "env\Scripts\python.exe" manage.py runserver 127.0.0.1:8000
) else (
    python manage.py runserver 127.0.0.1:8000
)
