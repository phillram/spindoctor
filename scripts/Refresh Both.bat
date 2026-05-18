@echo off
REM Refresh Favorites, Recently Played, and Most Played in one shot.
REM Pause on ANY step's failure so a silent fail-and-close doesn't
REM leave the user wondering which wheel didn't rebuild.
spindoctor-fav rebuild --apply
if errorlevel 1 (echo. & echo Favorites step failed. & pause & exit /b 1)
spindoctor-recent rebuild --apply
if errorlevel 1 (echo. & echo Recently Played step failed. & pause & exit /b 1)
spindoctor-stats build-wheel --apply
if errorlevel 1 (echo. & echo Most Played step failed. & pause & exit /b 1)
