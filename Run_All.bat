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
    start "ERPia RPA 대시보드" /min "%~dp0RPA_Dashboard.exe" --port %DASHBOARD_PORT%
    echo.
    echo  대시보드: http://localhost:%DASHBOARD_PORT%  ^(다른 PC/휴대폰 주소는 대시보드 창에 나옵니다^)
) else (
    echo  [안내] RPA_Dashboard.exe 가 없어 대시보드는 띄우지 않습니다.
)

echo.
echo ============================================================
echo  1/2  프리페어 RPA - 메일 첨부파일 내려받기
echo ============================================================
rem --no-keep-open : 브라우저를 닫아야 다음 단계로 넘어간다
"%~dp0Prepare_RPA.exe" --all --no-keep-open
set PREPARE_RC=%ERRORLEVEL%

if not "%PREPARE_RC%"=="0" (
    echo.
    echo [경고] 프리페어 RPA 가 정상 종료하지 않았습니다. 코드=%PREPARE_RC%
    echo        내려받은 엑셀이 없을 수 있지만 루틴 RPA 는 그대로 진행합니다.
    echo        엑셀업로드 단계는 파일이 없으면 알아서 건너뜁니다.
    echo.
)

echo.
echo ============================================================
echo  2/2  루틴 RPA - ERPia 처리
echo ============================================================
"%~dp0ERPia_RPA.exe"
set ROUTINE_RC=%ERRORLEVEL%

echo.
echo ============================================================
echo  끝났습니다.  프리페어=%PREPARE_RC%  루틴=%ROUTINE_RC%
echo ============================================================
endlocal
