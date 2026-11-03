@echo off
chcp 949 >nul
rem 이 PC 의 번호(윈도우 MachineGuid)를 보이고 클립보드에 복사한다 - 옵저버 단독 설치 파일은 PC 한 대 용 (사용자 2026-11-03).
rem 관리자 권한 없이 돈다 (reg query 는 누구나 읽는다). 이 파일은 CP949+CRLF (한글 bat 는 UTF-8 금지).
set G=
for /f "tokens=2,*" %%a in ('reg query "HKLM\SOFTWARE\Microsoft\Cryptography" /v MachineGuid /reg:64 ^| find /i "MachineGuid"') do set G=%%b
if "%G%"=="" echo PC 번호를 읽지 못했습니다. 담당자에게 문의하여 주십시오.
if "%G%"=="" pause
if "%G%"=="" exit /b 1
echo.
echo 이 PC 의 번호: %G%
echo %G%| clip
echo 번호를 클립보드에 복사하였습니다. 이 번호를 담당자에게 보내 주십시오.
echo.
pause
