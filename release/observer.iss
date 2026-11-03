; 오토파일럿 옵저버 단독 설치 파일 (설계 docs/superpowers/specs/2026-11-03-observer-standalone-design.md 4.2·4.8)
; tools/build_observer.py 가 배포_옵저버_<버전> 폴더에 대고 한 PC 용으로 컴파일한다:
;   ISCC.exe /DAppVersion=... /DNumVersion=... /DSourceDir=D:\AX\배포_옵저버_<버전> /DBoundPC=<MachineGuid> /DFlagFile=<PC번호를 채운 OBSERVER_STANDALONE> /OD:\AX /F... observer.iss
; 오토파일럿 설치 파일(installer.iss)과 AppId·폴더·작업 이름이 다르다 - 한 PC 에 둘 다 깔려도 서로 안 본다.
; 그 PC 에서만: InitializeSetup 이 이 PC 의 MachineGuid 와 BoundPC 를 견준다 (다르면 설치하지 않음). 설치 파일을 풀어 고치면 우회된다 - 사내용이라 받아들임 (사용자 2026-11-03).
; 이 파일은 BOM 있는 UTF-8 로 저장한다 (Inno Setup 이 한글을 그렇게 읽는다. tests/test_encoding.py 가 본다).

#ifndef AppVersion
  #error AppVersion 이 없습니다 - tools/build_observer.py 로 컴파일하세요
#endif
#ifndef NumVersion
  #error NumVersion 이 없습니다 - tools/build_observer.py 로 컴파일하세요
#endif
#ifndef SourceDir
  #error SourceDir 이 없습니다 - tools/build_observer.py 로 컴파일하세요
#endif
#ifndef BoundPC
  #error BoundPC 가 없습니다 - tools/build_observer.py <PC번호> 로 컴파일하세요
#endif
#ifndef FlagFile
  #error FlagFile 이 없습니다 - tools/build_observer.py 로 컴파일하세요
#endif

[Setup]
AppId={{7D4E9C21-3B6F-4A58-8E1D-2F9C5B7A6E43}
AppName=오토파일럿 옵저버
AppVersion={#AppVersion}
AppVerName=오토파일럿 옵저버 {#AppVersion}
AppPublisher=오토파일럿
VersionInfoVersion={#NumVersion}
DefaultDirName={commonpf64}\AFTER MARKET\Observer
DisableDirPage=yes
DefaultGroupName=오토파일럿 옵저버
DisableProgramGroupPage=yes
UsePreviousGroup=no
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupLogging=yes
CloseApplications=no
RestartApplications=no
UninstallDisplayName=오토파일럿 옵저버
SetupIconFile=AFTER_MARKET_PREPARE.ico
UninstallDisplayIcon={app}\AFTER_MARKET_PREPARE.ico
OutputDir=.
OutputBaseFilename=AUTOPILOT_Observer_Setup_{#AppVersion}

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Dirs]
; 설정(프리셋·계정)·기록은 제거해도 남긴다 (끝에 묻는다)
Name: "{commonappdata}\AFTER MARKET\Observer\config"; Flags: uninsneveruninstall
Name: "{commonappdata}\AFTER MARKET\Observer\data"; Flags: uninsneveruninstall
Name: "{group}"

[Files]
; 판 폴더 전부. 표시 파일은 PC번호를 채운 사본(FlagFile)으로 넣는다 - 판 폴더의 빈 것은 뺀다. 안내 문서는 넣지 않는다
Source: "{#SourceDir}\*"; DestDir: "{app}"; Excludes: "\OBSERVER_STANDALONE,\옵저버_안내.txt"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#FlagFile}"; DestDir: "{app}"; DestName: "OBSERVER_STANDALONE"; Flags: ignoreversion

[Icons]
Name: "{group}\옵저버"; Filename: "{app}\Prepare_Observer.exe"; WorkingDir: "{app}"; Comment: "쇼핑몰 조작을 기록해 ACTOR 가 따라 하게 (관리자 권한 요청이 뜹니다)"; IconFilename: "{app}\AFTER_MARKET_PREPARE.ico"; AppUserModelID: "AFTERMARKET.Observer.Record"
Name: "{group}\옵저버 관제"; Filename: "{app}\python\Observer_Hub.exe"; Parameters: """{app}\observer_hub.py"" --open"; WorkingDir: "{app}"; Comment: "이 PC 의 옵저버 관제 화면을 브라우저로 엽니다"; IconFilename: "{app}\AFTER_MARKET_PREPARE.ico"
Name: "{commondesktop}\옵저버 관제"; Filename: "{app}\python\Observer_Hub.exe"; Parameters: """{app}\observer_hub.py"" --open"; WorkingDir: "{app}"; Comment: "이 PC 의 옵저버 관제 화면을 브라우저로 엽니다"; IconFilename: "{app}\AFTER_MARKET_PREPARE.ico"

[Run]
; 설정 폴더 권한: 오토파일럿 설치 파일(installer.iss)과 같게 - 상속을 끊고 Administrators·SYSTEM 만 (SID 로)
Filename: "{sys}\icacls.exe"; Parameters: """{commonappdata}\AFTER MARKET\Observer"" /setowner *S-1-5-32-544 /T /C /Q"; Flags: runhidden waituntilterminated; StatusMsg: "설정 폴더를 관리자만 열 수 있게 막는 중..."
Filename: "{sys}\icacls.exe"; Parameters: """{commonappdata}\AFTER MARKET\Observer"" /inheritance:r /grant:r *S-1-5-32-544:(OI)(CI)F *S-1-5-18:(OI)(CI)F"; Flags: runhidden waituntilterminated; StatusMsg: "설정 폴더를 관리자만 열 수 있게 막는 중..."
Filename: "{sys}\icacls.exe"; Parameters: """{commonappdata}\AFTER MARKET\Observer\*"" /reset /T /C /Q"; Flags: runhidden waituntilterminated; StatusMsg: "설정 폴더를 관리자만 열 수 있게 막는 중..."
; 작업 스케줄러 '오토파일럿 옵저버 관제' 등록 (로그온 시·이 사용자·대화형·가장 높은 권한) 뒤 바로 켠다
Filename: "{app}\python\python.exe"; Parameters: """{app}\observer_hub.py"" --install-task"; WorkingDir: "{app}"; Flags: runhidden waituntilterminated; StatusMsg: "옵저버 관제를 등록하는 중..."
Filename: "{app}\python\Observer_Hub.exe"; Parameters: """{app}\observer_hub.py"" --open"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent; Description: "옵저버 관제 화면 열기"

[UninstallRun]
Filename: "{app}\python\python.exe"; Parameters: """{app}\observer_hub.py"" --remove-task"; WorkingDir: "{app}"; Flags: runhidden waituntilterminated; RunOnceId: "RemoveHubTask"

[UninstallDelete]
Type: files; Name: "{commondesktop}\옵저버 관제.lnk"
Type: filesandordirs; Name: "{app}"
Type: dirifempty; Name: "{commonpf64}\AFTER MARKET"

[Code]
const
  // 단독 옵저버가 켜 있는 동안 쥐는 잠금 (rpa_status.STANDALONE_LOCK 과 같아야 한다). 켜진 exe 는 덮지도 지우지도 못한다
  OBSERVER_LOCK = 'Local\AFTER_MARKET_OBSERVER_SA';
  OBSERVER_OPEN = '옵저버가 켜져 있습니다. 옵저버를 닫은 뒤 다시 ';
  TASK_NAME = '오토파일럿 옵저버 관제';

// 이 PC 의 윈도우 MachineGuid (소문자). 설치 파일은 한 PC 용 - 다른 PC 면 설치하지 않는다 (사용자 2026-11-03)
function MachineGuid(): String;
var
  V: String;
begin
  Result := '';
  if RegQueryStringValue(HKLM64, 'SOFTWARE\Microsoft\Cryptography', 'MachineGuid', V) then
    Result := Lowercase(Trim(V));
end;

function InitializeSetup(): Boolean;
begin
  Result := CompareText(MachineGuid(), '{#BoundPC}') = 0;
  if not Result then
  begin
    Log('BoundPC ' + '{#BoundPC}' + ' <> MachineGuid ' + MachineGuid());
    if not WizardSilent then
      MsgBox('이 설치 파일은 다른 PC 용입니다. 담당자에게 이 PC 의 번호(PC번호_확인.bat)를 보내 새 설치 파일을 받아 주십시오.', mbError, MB_OK);
  end;
end;

// 설치 폴더에서 도는 프로그램(Observer_Hub.exe·Prepare_RPA.exe·Prepare_Observer.exe)을 끝낸다 - 경로로 걸러서 (taskkill /IM 은
// 오토파일럿 쪽 같은 이름 exe 도 죽인다). 작업 스케줄러 작업도 끝낸다. 도는 파일은 덮지도 지우지도 못한다 (검토 2026-11-03)
procedure StopAppProcesses();
var
  Code: Integer;
  Cmd: String;
begin
  Exec(ExpandConstant('{sys}\schtasks.exe'), '/End /TN "' + TASK_NAME + '"', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Cmd := '-NoProfile -ExecutionPolicy Bypass -Command "Get-Process | Where-Object { $_.Path -like ''' + ExpandConstant('{app}') + '\*'' } | Stop-Process -Force"';
  Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'), Cmd, '', SW_HIDE, ewWaitUntilTerminated, Code);
  Sleep(1500);
end;

// 덮어 설치: 옵저버가 켜 있으면 멈춘다. 관제·ACTOR 는 끝내고 파일을 덮는다
function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if CheckForMutexes(OBSERVER_LOCK) then
  begin
    Result := OBSERVER_OPEN + '설치하세요.';
    exit;
  end;
  StopAppProcesses();
end;

function InitializeUninstall(): Boolean;
begin
  Result := True;
  if CheckForMutexes(OBSERVER_LOCK) then
  begin
    SuppressibleMsgBox(OBSERVER_OPEN + '지우세요.', mbError, MB_OK, IDOK);
    Result := False;
    exit;
  end;
  StopAppProcesses();
end;

// 끝에 설정·기록을 지울지 묻는다 (기본 아니요 - 조용한 제거면 남긴다)
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Data: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    Data := ExpandConstant('{commonappdata}\AFTER MARKET\Observer');
    if DirExists(Data) and (SuppressibleMsgBox('설정과 기록(' + Data + ')도 지울까요?' + #13#10 +
         '다시 설치해서 쓰려면 [아니요] 를 누르세요. 설정에는 잠근 비밀번호가 들어 있습니다.',
         mbConfirmation, MB_YESNO or MB_DEFBUTTON2, IDNO) = IDYES) then
    begin
      DelTree(Data, True, True, True);
      RemoveDir(ExpandConstant('{commonappdata}\AFTER MARKET'));
    end;
  end;
end;
