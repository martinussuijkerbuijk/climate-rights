@echo off
REM ============================================================================
REM == Startup Script for NPM Dev Server and Kiosk Browser
REM ==
REM == This script performs the following actions:
REM == 1. Navigates to your project directory.
REM == 2. Starts the 'npm run dev' server in a new command window.
REM == 3. Waits for a few seconds to allow the server to initialize.
REM == 4. Launches a web browser in kiosk mode to the specified URL.
REM ============================================================================

ECHO Starting the application environment...

REM --- STEP 1: Set your project path and URL ---
REM IMPORTANT: Change these variables to match your setup.
SET PROJECT_PATH="C:\Users\LattePanda\Documents\climate-rights\_MAP\projection-map"
SET DEV_URL="http://localhost:5137"

REM --- STEP 2: Navigate to the project directory ---
ECHO Navigating to project directory...
cd /d %PROJECT_PATH%

IF %ERRORLEVEL% NEQ 0 (
    ECHO ERROR: The project path was not found: %PROJECT_PATH%
    ECHO Please update the PROJECT_PATH variable in this script.
    pause
    exit /b
)

REM --- STEP 3: Start the NPM development server ---
ECHO Starting NPM dev server in a new window...
start "NPM Dev Server" npm run dev

REM --- STEP 4: Wait for the server to start ---
REM Adjust the time (in seconds) if your server takes longer to start.
ECHO Waiting for server to initialize (10 seconds)...
timeout /t 10 /nobreak >nul

REM --- STEP 5: Launch the browser in kiosk mode ---
ECHO Launching browser in kiosk mode...

REM --- Option A: For Google Chrome ---
REM Remove "REM" from the line below if you use Google Chrome.
start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --kiosk %DEV_URL%

REM --- Option B: For Microsoft Edge ---
REM Remove "REM" from the line below if you use Microsoft Edge.
REM start "" "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --kiosk %DEV_URL%

ECHO Startup script finished.
