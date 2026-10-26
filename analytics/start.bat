@echo off
rem Double-click to start Ellementry Analytics (run scripts\setup.ps1 once first).
powershell -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1" %*
