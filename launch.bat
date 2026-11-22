@echo off
cd /d "%~dp0"
if exist "dist\AI Audio Sentence Splitter\AI Audio Sentence Splitter.exe" (
    start "" "dist\AI Audio Sentence Splitter\AI Audio Sentence Splitter.exe"
    exit /b
)
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "app.py"
    exit /b
)
echo Use the bundled Windows release, or follow README.md to set up the source.
pause
