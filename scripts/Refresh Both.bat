@echo off
REM Refresh Favorites, Recently Played, and Most Played in one shot.
spindoctor-fav rebuild
spindoctor-recent rebuild
spindoctor-stats build-wheel --apply
if errorlevel 1 pause
