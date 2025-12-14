@echo off
git add .
if "%~1"=="" (
    git commit -m "Auto update"
) else (
    git commit -m "%~1"
)
git push
echo Done!
