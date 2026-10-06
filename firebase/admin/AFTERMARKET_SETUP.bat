@echo off
rem AFTER MARKET admin screen: starts the local server (node admin.js) and opens the browser.
rem ASCII only on purpose - a bat with Korean text must be CP949 (UTF-8 breaks cmd line parsing).
cd /d "%~dp0"
node admin.js
if errorlevel 1 pause
