@echo off
setlocal
cd /d "%~dp0"

echo ==========================================
echo          LOTO LAB 5/35
echo ==========================================
echo.

where py >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_CMD=py -3"
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        echo Python 3 n'est pas installe ou introuvable.
        echo Installe Python 3.11 ou plus recent depuis https://www.python.org/downloads/windows/
        echo Pendant l'installation, cochez "Add Python to PATH".
        pause
        exit /b 1
    )
    set "PYTHON_CMD=python"
)

if not exist ".venv\Scripts\python.exe" (
    echo Creation de l'environnement Python...
    %PYTHON_CMD% -m venv .venv
    if errorlevel 1 goto error
)

call ".venv\Scripts\activate.bat"
if errorlevel 1 goto error

echo Installation ou verification des dependances...
python -m pip install -r requirements.txt
if errorlevel 1 goto error

set "APP_PASSWORD="
set "SECRET_KEY=local-only-change-before-public-deployment"
set "DATABASE_URL=sqlite:///./loto.db"
set "COOKIE_SECURE=false"

echo.
echo LOTO LAB demarre sur http://127.0.0.1:8000
echo Gardez cette fenetre ouverte pendant l'utilisation.
echo Pour arreter le logiciel, appuyez sur Ctrl+C.
echo.
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
pause
exit /b 0

:error
echo.
echo Une erreur est survenue. Verifiez que Python 3.11+ est installe et que votre connexion Internet fonctionne.
pause
exit /b 1
