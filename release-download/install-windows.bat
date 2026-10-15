@echo off
chcp 6501 >nul
REM AlterEgo LLM Studio 1.15.0 — установка на Windows
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel% neq 0 (
  echo Python не найден. Установите Python 3.11 или 3.12 с https://www.python.org
  echo и отметьте галочку "Add python.exe to PATH", затем запустите этот файл снова.
  pause
  exit /b 1
)
echo Устанавливаю AlterEgo LLM Studio 1.15.0 ...
py -m pip install --upgrade pip
py -m pip install "alterego_training_hub_desktop-1.15.0-py3-none-any.whl" cryptography
if %errorlevel% neq 0 (
  echo.
  echo Установка не удалась — пришлите текст ошибки выше разработчику.
  pause
  exit /b 1
)
echo.
echo Готово! Запуск: alterego-llm-studio
echo (или запустите файл run-alterego.bat рядом)
pause
