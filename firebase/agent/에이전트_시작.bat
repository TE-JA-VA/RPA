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

rem 배포 폴더의 내장 python 을 먼저 쓴다 (두 단계 위 python\). 없으면 PATH 의 python.
set "PY=%~dp0..\..\python\python.exe"
if not exist "%PY%" set "PY=python"

echo ================================================
echo   ERPia RPA 클라우드 에이전트
echo   이 창을 닫으면 에이전트가 멈춥니다.
echo   처음 실행이면 회사 코드, PC 이름, 기계 계정 비밀번호를 묻습니다.
echo ================================================
echo.

"%PY%" agent.py
echo.
echo 에이전트가 멈췄습니다. 위 내용을 확인하세요.
pause
