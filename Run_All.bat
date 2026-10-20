@echo off
setlocal

rem ===================================================================
rem  프리페어 RPA -> 루틴 RPA 를 이어서 실행한다.
rem
rem  프리페어 RPA : 메일에서 '>>>' 로 시작하는 건의 첨부파일을
rem                 바탕화면\ERPIA_AI\ERPIA_AI_EXCEL 로 내려받는다.
rem  루틴 RPA     : ERPia 를 돌린다. 위에서 받은 엑셀을 주문매핑
rem                 매출처리 단계에서 업로드한다.
rem
rem  반드시 관리자 권한으로 실행할 것 (ERPia 가 관리자 권한으로 돌기 때문).
rem  실행 중에는 PC 화면을 잠그면 안 된다 (화면을 읽어서 조작하기 때문).
rem
rem  이 파일은 CP949 로 저장해야 한다. UTF-8 로 저장하면 한글 줄이 깨진다.
rem  맨 위에 chcp 65001 을 넣어 UTF-8 로 바꿔도 안 된다 - cmd 가 한글 줄 뒤의 줄 위치를 잘못 세어
rem  다음 줄 앞부분을 건너뛰고 나머지 조각을 명령으로 실행한다 (2026-09-29 확인, tests\test_encoding.py).
rem ===================================================================

cd /d "%~dp0"

rem --- 현황 대시보드 --------------------------------------------------
rem  진행 상황을 웹으로 보여준다. 이미 떠 있으면 새로 띄워도 알아서 바로 끝난다.
rem  사내 다른 PC 나 휴대폰에서 보려면 방화벽에서 포트를 열어야 한다.
rem  '개인/도메인' 네트워크에 한해, 규칙이 없을 때만 한 번 추가한다.
set DASHBOARD_PORT=8765
if exist "%~dp0RPA_Dashboard.exe" (
    netsh advfirewall firewall show rule name="ERPIA_RPA_Dashboard" >nul 2>&1
    if errorlevel 1 netsh advfirewall firewall add rule name="ERPIA_RPA_Dashboard" dir=in action=allow protocol=TCP localport=%DASHBOARD_PORT% profile=private,domain >nul
    start "오토파일럿 대시보드" /min "%~dp0RPA_Dashboard.exe" --port %DASHBOARD_PORT%
    echo.
    echo  대시보드: http://localhost:%DASHBOARD_PORT%  ^(다른 PC/휴대폰 주소는 대시보드 창에 나옵니다^)
) else (
    echo  [안내] RPA_Dashboard.exe 가 없어 대시보드는 띄우지 않습니다.
)

echo.
echo ============================================================
echo  1/2  ACTOR 오토파일럿 - 메일 첨부파일 내려받기
echo ============================================================
rem --no-keep-open : 브라우저를 닫아야 다음 단계로 넘어간다
rem 웰라이프 업체는 ACTOR 가 수집하는 동안 PROCESS 를 함께 띄워 받은 엑셀을 바로 올린다 (2026-10-19).
rem 그때 ACTOR 는 PROCESS 가 끝날 때까지 기다렸다가 100~103 (100 + ACTOR 실패 2 + PROCESS 실패 1) 으로 끝난다 - PROCESS 를 다시 띄우지 않는다.
set RPA_ALL_RUN=1
"%~dp0Prepare_RPA.exe" --all --no-keep-open
set PREPARE_RC=%ERRORLEVEL%
set RPA_ALL_RUN=
if %PREPARE_RC% GEQ 100 if %PREPARE_RC% LSS 200 goto together

if not "%PREPARE_RC%"=="0" (
    echo.
    echo [경고] ACTOR 오토파일럿이 정상 종료하지 않았습니다. 코드=%PREPARE_RC%
    echo        내려받은 엑셀이 없을 수 있지만 PROCESS 오토파일럿은 그대로 진행합니다.
    echo        엑셀업로드 단계는 파일이 없으면 알아서 건너뜁니다.
    echo.
)

echo.
echo ============================================================
echo  2/2  PROCESS 오토파일럿 - ERPia 처리
echo ============================================================
"%~dp0ERPia_RPA.exe"
set ROUTINE_RC=%ERRORLEVEL%
goto summary

:together
rem 100 + (ACTOR 실패 2) + (PROCESS 실패 1)
set /a TOGETHER_CODE=PREPARE_RC-100
set /a ROUTINE_RC=TOGETHER_CODE %% 2
set /a PREPARE_RC=TOGETHER_CODE / 2
echo.
echo  2/2  PROCESS 오토파일럿은 수집과 함께 돌았습니다.

:summary

echo.
echo ============================================================
echo  끝났습니다.  ACTOR 오토파일럿=%PREPARE_RC%  PROCESS=%ROUTINE_RC%
echo ============================================================
endlocal
