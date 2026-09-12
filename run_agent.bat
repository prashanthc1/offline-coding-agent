@echo off
setlocal enabledelayedexpansion

REM ==============================================================================
REM Offline Coding Agent Runner for kirmya_project (Windows)
REM ==============================================================================

set "OLLAMA_HOST=%OLLAMA_HOST%"
if "%OLLAMA_HOST%"=="" set "OLLAMA_HOST=http://localhost:11434"

set "MODEL=%OLLAMA_MODEL%"
if "%MODEL%"=="" set "MODEL=qwen2.5-coder:7b"

set "WORKSPACE=%~1"
if "%WORKSPACE%"=="" (
    if defined KIRMYA_PROJECT_PATH (
        set "WORKSPACE=%KIRMYA_PROJECT_PATH%"
    ) else if exist ".\kirmya_project" (
        set "WORKSPACE=.\kirmya_project"
    ) else if exist ".\kirmya_project_demo" (
        set "WORKSPACE=.\kirmya_project_demo"
    ) else (
        set "WORKSPACE=.\kirmya_project"
    )
)

REM If specified workspace directory doesn't exist, automatically create it
if not exist "%WORKSPACE%" (
    echo [Notice] Directory "%WORKSPACE%" does not exist. Creating workspace folder...
    mkdir "%WORKSPACE%"
)

echo ==========================================================
echo   Starting Offline Coding Agent for kirmya_project
echo ==========================================================
echo Workspace: %WORKSPACE%
echo Model:     %MODEL%
echo Ollama:    %OLLAMA_HOST%
echo ----------------------------------------------------------

REM 1. Verify Ollama is reachable (using -NoProfile to avoid PSReadLine errors)
echo [1/4] Checking Ollama connectivity at %OLLAMA_HOST%...
powershell -NoProfile -NonInteractive -Command "try { $r = Invoke-WebRequest -Uri '%OLLAMA_HOST%/api/tags' -TimeoutSec 3 -UseBasicParsing; if ($r.StatusCode -ne 200) { exit 1 } } catch { exit 1 }"
if %errorlevel% neq 0 (
    echo.
    echo ERROR: Ollama is not running or unreachable at %OLLAMA_HOST%.
    echo Please start Ollama in another window with: ollama serve
    echo.
    pause
    exit /b 1
)
echo       Ollama service is up and running.

REM 2. Verify model availability
echo [2/4] Verifying model availability (%MODEL%)...
powershell -NoProfile -NonInteractive -Command "$r = (Invoke-RestMethod -Uri '%OLLAMA_HOST%/api/tags').models; if ($r.name -like '*%MODEL%*') { exit 0 } else { exit 1 }"
if %errorlevel% neq 0 (
    echo WARNING: Model '%MODEL%' not detected in Ollama.
    echo Attempting to pull model with: ollama pull %MODEL%...
    where ollama >nul 2>nul
    if %errorlevel% equ 0 (
        ollama pull %MODEL%
    ) else (
        echo ERROR: 'ollama' command not found in PATH to auto-pull.
        echo Please run: ollama pull %MODEL%
        pause
        exit /b 1
    )
) else (
    echo       Model '%MODEL%' is ready.
)

REM 3. Setup Python virtual environment
echo [3/4] Preparing Python environment...
set "SCRIPT_DIR=%~dp0"
set "VENV_DIR=%SCRIPT_DIR%.venv"

if not exist "%VENV_DIR%\Scripts\activate.bat" (
    echo       Creating virtual environment in %VENV_DIR%...
    python -m venv "%VENV_DIR%"
)

call "%VENV_DIR%\Scripts\activate.bat"

if exist "%SCRIPT_DIR%requirements.txt" (
    echo       Checking/installing Python dependencies...
    pip install -q -r "%SCRIPT_DIR%requirements.txt"
)

REM 4. Launch agent
echo [4/4] Launching Offline Coding Agent...
python "%SCRIPT_DIR%agent.py" "%WORKSPACE%" --model "%MODEL%"

if %errorlevel% neq 0 (
    echo.
    echo Agent exited with error code %errorlevel%.
    pause
)

endlocal
