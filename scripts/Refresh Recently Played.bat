@echo off
REM Regenerates the Recently Played wheel from RocketLauncher's launch stats.
REM Drop into HyperSpin's Tools folder, or schedule via Task Scheduler.
spindoctor-recent rebuild
if errorlevel 1 pause
