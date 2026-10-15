@echo off
chcp 6501 >nul
REM EGO 1.16.0 — установка на Windows
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel% neq 0 (
  echo Python не найден. Установите Python 3.11 или 3.12 с https://www.python.org
  echo и отметьте галочку "Add python.exe to PATH", затем запустите этот файл снова.
  pause
  exit /b 1
)
echo Устанавливаю EGO 1.16.0 ...
py -m pip install --upgrade pip
py -m pip install "ego-1.16.0-py3-none-any.whl" cryptography
if %errorlevel% neq 0 (
  echo.
  echo Установка не удалась — пришлите текст ошибки выше разработчику.
  pause
  exit /b 1
)
echo.
echo Готово! Запуск: ego
echo (или запустите файл run-alterego.bat рядом)
pause
