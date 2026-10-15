@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
  echo Python Launcher ^(py^) не найден. Установите Python 3.11 или 3.12 с https://www.python.org
  echo и отметьте галочку "Add python.exe to PATH", затем запустите этот файл снова.
  pause
  exit /b 1
)

set "WHEEL="
for %%F in (ego_desktop-*-py3-none-any.whl) do if exist "%%~fF" (
  if defined WHEEL (
    echo Найдено несколько wheel-файлов. Оставьте рядом только wheel этой версии релиза.
    pause
    exit /b 1
  )
  set "WHEEL=%%~nxF"
)
if not defined WHEEL (
  echo Рядом не найден ego_desktop-*-py3-none-any.whl.
  echo Скачайте wheel из того же GitHub Release и положите его рядом с этим установщиком.
  pause
  exit /b 1
)

echo Устанавливаю %WHEEL% ...
py -m pip install --upgrade pip
if errorlevel 1 (
  echo Не удалось обновить pip; установка остановлена.
  pause
  exit /b 1
)
py -m pip show alterego-training-hub-desktop >nul 2>nul
if not errorlevel 1 (
  echo Найдена старая установка. Переношу ее на EGO...
  py -m pip uninstall -y alterego-training-hub-desktop
  if errorlevel 1 (
    echo Не удалось удалить старый пакет. Установка остановлена.
    pause
    exit /b 1
  )
)
py -m pip install "%WHEEL%" cryptography
if errorlevel 1 (
  echo Установка не удалась — пришлите текст ошибки выше разработчику.
  pause
  exit /b 1
)
echo.
echo Готово! Запуск: ego
echo Если команда не найдена, запустите run-ego.bat рядом.
pause
