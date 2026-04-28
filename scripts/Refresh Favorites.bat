@echo off
REM Regenerates the cross-system HyperSpin Favorites wheel.
REM Drop into HyperSpin's Tools folder, or schedule via Task Scheduler.
spindoctor-fav rebuild
if errorlevel 1 pause
