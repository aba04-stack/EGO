@echo off
alterego-llm-studio
if %errorlevel% neq 0 py -m alterego_training_hub
pause
