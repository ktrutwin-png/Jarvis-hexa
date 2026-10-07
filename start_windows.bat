@echo off
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 goto usepython
py -3 -m heksa
goto finish
:usepython
where python >nul 2>nul
if errorlevel 1 goto missing
python -m heksa
goto finish
:missing
echo Zainstaluj Python 3 z python.org, a potem uruchom ten plik ponownie.
:finish
pause
