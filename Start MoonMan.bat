@echo off
rem MoonMan one-click start: dashboard + all services, then browser.
cd /d C:\MoonworksDev\moonman-ai\src
set MOONMAN_CONTROL_AUTOSTART=1
start "MoonMan Mission Control" py moonman_control.py
timeout /t 3 /nobreak >nul
start http://localhost:8100/
