@echo off
chcp 65001 >nul
setlocal
rem Ярлык сервиса макетов форм. Двойной щелчок - последняя папка макетов; папка или
rem модель, перетащенная на ярлык, - сервис на эту папку. Окно закрывается, когда сервис запущен; ошибка
rem остается на экране. Python ищется как py -3, python, python3 (заглушка Microsoft Store не годится).
set "FM_PY="
py -3 -c "import sys; sys.exit(sys.version_info < (3, 9))" >nul 2>&1 && set "FM_PY=py -3"
if not defined FM_PY python -c "import sys; sys.exit(sys.version_info < (3, 9))" >nul 2>&1 && set "FM_PY=python"
if not defined FM_PY python3 -c "import sys; sys.exit(sys.version_info < (3, 9))" >nul 2>&1 && set "FM_PY=python3"
if not defined FM_PY (
    echo Не найден Python 3.9 или новее - он нужен, чтобы открыть макеты.
    echo Скачайте установщик: https://www.python.org/downloads/
    echo При установке отметьте "Add python.exe to PATH", затем снова откройте ярлык.
    goto :fail
)
%FM_PY% "%~dp0formmockup.py" serve --shortcut %*
if errorlevel 1 goto :fail
exit /b 0

:fail
echo.
if not defined FORMMOCKUP_NO_PAUSE pause
exit /b 1
