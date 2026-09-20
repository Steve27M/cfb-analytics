@echo off
rem Refresh the in-progress season and publish it:   scripts\live.cmd   [--skip-ingest]
rem A .cmd launcher because Windows blocks unsigned .ps1 files by default (execution policy).
rem It runs live.ps1 with the policy bypassed for this one process only; nothing on the
rem machine is reconfigured.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0live.ps1" %*
exit /b %ERRORLEVEL%
