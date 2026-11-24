@echo off
REM Redirect to silent VBS launcher (avoids console from uv pythonw shim)
wscript //nologo "%~dp0start.vbs"
