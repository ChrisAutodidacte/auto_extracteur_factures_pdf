@echo off
chcp 65001 > nul
title Traitement Automatique des Factures PDF - Chris l'Autodidacte
echo ============================================================
echo   TRAITEMENT AUTOMATIQUE DES FACTURES PDF (GEMINI IA)
echo ============================================================
echo.

:: Verifier si le fichier .env existe
if not exist "%~dp0.env" (
    echo [ATTENTION] Le fichier .env est introuvable.
    echo Veuillez copier le fichier .env.example en .env et y renseigner votre cle API Gemini.
    echo.
    echo Rendez-vous sur https://aistudio.google.com/ pour obtenir une cle gratuite.
    echo.
    pause
    exit /b 1
)

:: Activation de l'environnement virtuel si present
if exist "%~dp0venv\Scripts\activate.bat" (
    call "%~dp0venv\Scripts\activate.bat"
) else if exist "%~dp0.venv\Scripts\activate.bat" (
    call "%~dp0.venv\Scripts\activate.bat"
)

:: Lancement du script python
python "%~dp0traitement_factures.py"

echo.
echo ============================================================
echo Traitement terminé.
echo.
pause
