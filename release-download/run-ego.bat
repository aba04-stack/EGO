@echo off
REM EGO launcher
cd /d "%~dp0"
ego
if %errorlevel% neq 0 py -m alterego_training_hub
