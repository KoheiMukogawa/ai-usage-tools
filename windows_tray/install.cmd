@echo off
rem Windows setup without WSL. Double-click to run. Uninstall: install.cmd -Uninstall
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
pause
