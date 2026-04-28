@echo off
REM Regenerates the Most Played wheel from RocketLauncher playtime stats.
spindoctor-stats build-wheel --apply
if errorlevel 1 pause
