@echo off
chcp 949 >nul
title ERPia RPA 클라우드 에이전트
cd /d "%~dp0"

fltmc >nul 2>&1
if errorlevel 1 (
    echo 관리자 권한이 필요합니다. 권한을 올려 다시 시작합니다.
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList 'elevated' -Verb RunAs"
    exit /b
)

echo ================================================
echo   ERPia RPA 클라우드 에이전트
echo   이 창을 닫으면 에이전트만 꺼집니다.
echo ================================================
echo.

python agent.py
echo.
echo 에이전트가 끝났습니다. 위 내용을 확인하세요.
pause
