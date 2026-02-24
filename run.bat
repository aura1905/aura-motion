@echo off
title GE SD Motion Portal
echo ==========================================
echo   GE SD Motion Portal v1.2.7 Starting...
echo ==========================================

echo [*] Checking dependencies...
pip install -r requirements.txt --quiet

echo [*] Starting server and launching browser...
python app.py

pause
