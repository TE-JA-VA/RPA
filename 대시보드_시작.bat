@echo off
rem =====================================================================
rem  ERPia RPA 현황 대시보드 시작 (이 PC 개발 환경용: .venv 파이썬으로 띄운다)
rem
rem  더블클릭 -> 관리자 권한 확인창(UAC) '예' -> 이 창에 주소가 찍힌다
rem  -> 브라우저에서 http://localhost:8765 -> admin 으로 로그인 -> 실행 버튼
rem
rem  이 창을 닫으면 대시보드와 자동 실행이 꺼진다 (돌고 있는 RPA 는 영향 없음).
rem  관리자 권한이 필요한 이유: ERPia 가 관리자 권한으로 돌아서, 여기서 띄운 RPA 도
rem  관리자 권한이어야 ERPia 화면을 조작할 수 있다.
rem =====================================================================

net session >nul 2>&1
if errorlevel 1 (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"
title ERPia RPA 대시보드
if not exist ".venv\Scripts\python.exe" (
    echo [오류] .venv 가 없습니다. 이 파일은 D:\AX\RPA 안에서 실행해야 합니다.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" rpa_dashboard.py --port 8765
echo.
echo 대시보드가 끝났습니다. 아무 키나 누르면 창이 닫힙니다.
pause >nul
