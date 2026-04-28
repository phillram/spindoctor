@echo off
REM Refresh Favorites and Recently Played in one shot.
spindoctor-fav rebuild
spindoctor-recent rebuild
if errorlevel 1 pause
