@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
set "PYTHONUTF8=1"
set "ATOMMOVR_BOOT_SELECTOR="

if defined ATOMMOVR_PYTHON (
  "%ATOMMOVR_PYTHON%" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
  if errorlevel 1 goto invalid_override
  set "ATOMMOVR_BOOT_PYTHON=%ATOMMOVR_PYTHON%"
  goto launch
)

for %%P in (
  "%~dp0.venv\Scripts\python.exe"
  "%ATOMMOVR_SOURCE%\.venv\Scripts\python.exe"
  "%USERPROFILE%\Downloads\atommovr-main\.venv\Scripts\python.exe"
  "%~dp0.deps\atommovr\.venv\Scripts\python.exe"
) do (
  if exist "%%~P" (
    "%%~P" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
    if not errorlevel 1 (
      set "ATOMMOVR_BOOT_PYTHON=%%~P"
      goto launch
    )
  )
)

for %%V in (3.12 3.11 3.13 3.14 3) do (
  py -%%V -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
  if not errorlevel 1 (
    set "ATOMMOVR_BOOT_PYTHON=py"
    set "ATOMMOVR_BOOT_SELECTOR=-%%V"
    goto launch
  )
)

for %%P in (python3 python) do (
  %%P -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
  if not errorlevel 1 (
    set "ATOMMOVR_BOOT_PYTHON=%%P"
    goto launch
  )
)
echo Python 3.11 or newer is required. Install Python or set ATOMMOVR_PYTHON.
goto failed

:invalid_override
echo ATOMMOVR_PYTHON must point to a working Python 3.11+ executable.
goto failed

:launch
pushd "%~dp0"
"%ATOMMOVR_BOOT_PYTHON%" %ATOMMOVR_BOOT_SELECTOR% "%~dp0launch.py" %*
set "ATOMMOVR_LAUNCH_RESULT=%ERRORLEVEL%"
popd
if not "%ATOMMOVR_LAUNCH_RESULT%"=="0" if not defined ATOMMOVR_NO_PAUSE pause
exit /b %ATOMMOVR_LAUNCH_RESULT%

:failed
if not defined ATOMMOVR_NO_PAUSE pause
exit /b 1
