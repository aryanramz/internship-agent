@echo off
"%~dp0..\..\..\.venv\Scripts\python.exe" -m internship_agent.scheduler_windows remove --root "%~dp0..\..\.."
pause
