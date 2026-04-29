@echo off
REM Refresh Favorites, Recently Played, and Most Played in one shot.
spindoctor-fav rebuild --apply
spindoctor-recent rebuild --apply
spindoctor-stats build-wheel --apply
if errorlevel 1 pause
