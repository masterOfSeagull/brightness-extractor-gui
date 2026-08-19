@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
    py frame_sampler_gui.py
) else (
    python frame_sampler_gui.py
)

if errorlevel 1 pause
