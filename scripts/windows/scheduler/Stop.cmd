@echo off
"%~dp0..\..\..\.venv\Scripts\python.exe" -m internship_agent.scheduler_windows stop --root "%~dp0..\..\.."
pause
