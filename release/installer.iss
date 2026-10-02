; AFTER MARKET RPA 설치 파일 (배포판 구조 2부 3절 - docs/superpowers/specs/2026-09-29-installer-design.md)
; tools/build_release.py 가 판 폴더에 대고 컴파일한다:
;   ISCC.exe /DAppVersion=2026.09.29-5 /DNumVersion=2026.9.29.5 /DSourceDir=D:\AX\배포_2026.09.29-5 /OD:\AX /F... installer.iss
; 설치·제거·바로 가기·폴더 권한만 여기서 한다. 입력·로그인 확인·작업 등록·에이전트 켜고 끄기는 rpa_settings.py.
; 이 파일은 BOM 있는 UTF-8 로 저장한다 (Inno Setup 이 한글을 그렇게 읽는다. tests/test_encoding.py 가 본다).

#ifndef AppVersion
  #error AppVersion 이 없습니다 - tools/build_release.py 로 컴파일하세요
#endif
#ifndef NumVersion
  #error NumVersion 이 없습니다 - tools/build_release.py 로 컴파일하세요
#endif
#ifndef SourceDir
  #error SourceDir 이 없습니다 - tools/build_release.py 로 컴파일하세요
#endif

[Setup]
AppId={{C3F7A2B4-5E81-4D2A-9B6C-7A1E0F3D8B52}
AppName=AFTER MARKET RPA
AppVersion={#AppVersion}
AppVerName=AFTER MARKET RPA {#AppVersion}
AppPublisher=AFTER MARKET
VersionInfoVersion={#NumVersion}
DefaultDirName={commonpf64}\AFTER MARKET\RPA
DisableDirPage=yes
DefaultGroupName=AFTER MARKET RPA
DisableProgramGroupPage=yes
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
UninstallDisplayName=AFTER MARKET RPA
; 아이콘: tools/make_icon.py 가 만든다. 설치 파일 아이콘은 이 스크립트 옆 것, 나머지는 판 폴더에 들어간 사본
SetupIconFile=AFTER_MARKET.ico
UninstallDisplayIcon={app}\AFTER_MARKET.ico
OutputDir=.
OutputBaseFilename=AFTER_MARKET_RPA_Setup_{#AppVersion}

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Dirs]
; 이 config 폴더가 생기면 그 PC 는 새 구조다 (1부 3절). 제거할 때 자동으로 지우지 않는다 (끝에 묻는다)
Name: "{commonappdata}\AFTER MARKET\RPA\config"; Flags: uninsneveruninstall
Name: "{commonappdata}\AFTER MARKET\RPA\data"; Flags: uninsneveruninstall
Name: "{group}"

[Files]
; 판 폴더 전부. 빈 틀은 template 이름으로 (프로그램 폴더에 진짜 설정처럼 보이는 파일을 두지 않는다), 안내 문서는 넣지 않는다
Source: "{#SourceDir}\*"; DestDir: "{app}"; Excludes: "\RPA_UserConfig.json,\배포안내.txt,\클라우드_안내.txt"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#SourceDir}\RPA_UserConfig.json"; DestDir: "{app}"; DestName: "RPA_UserConfig.template.json"; Flags: ignoreversion

[Icons]
Name: "{group}\RPA 설정"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\rpa_settings.py"""; WorkingDir: "{app}"; Comment: "RPA 설정 창 (관리자 권한 요청이 뜹니다)"; IconFilename: "{app}\AFTER_MARKET.ico"; AppUserModelID: "AFTERMARKET.RPA.Settings"
Name: "{group}\RPA 옵저버"; Filename: "{app}\Prepare_Observer.exe"; WorkingDir: "{app}"; Comment: "쇼핑몰 조작을 기록해 프리페어가 따라 하게 (관리자 권한 요청이 뜹니다)"; IconFilename: "{app}\AFTER_MARKET_PREPARE.ico"; AppUserModelID: "AFTERMARKET.RPA.Observer"

[INI]
Filename: "{group}\RPA 대시보드.url"; Section: "InternetShortcut"; Key: "URL"; String: "https://rpa-test-f02e0.web.app"
Filename: "{group}\RPA 대시보드.url"; Section: "InternetShortcut"; Key: "IconFile"; String: "{app}\AFTER_MARKET.ico"
Filename: "{group}\RPA 대시보드.url"; Section: "InternetShortcut"; Key: "IconIndex"; String: "0"

[Run]
; 상속을 끊고 Administrators(S-1-5-32-544)·SYSTEM(S-1-5-18) 만 남긴다. 한글 윈도우의 그룹 이름 차이에 흔들리지 않게 SID 로.
; 설치 전에 누가 이 폴더를 미리 만들어 두었어도 막히게 (2026-09-29 검토): 주인을 Administrators 로 바꾸고, 아래 폴더·파일은
; 따로 붙은 권한을 지우고 위의 것을 물려받게 한다 (주인은 권한을 다시 바꿀 수 있고, 따로 붙은 권한은 상속으로 안 지워진다)
Filename: "{sys}\icacls.exe"; Parameters: """{commonappdata}\AFTER MARKET\RPA"" /setowner *S-1-5-32-544 /T /C /Q"; Flags: runhidden waituntilterminated; StatusMsg: "설정 폴더를 관리자만 열 수 있게 막는 중..."
Filename: "{sys}\icacls.exe"; Parameters: """{commonappdata}\AFTER MARKET\RPA"" /inheritance:r /grant:r *S-1-5-32-544:(OI)(CI)F *S-1-5-18:(OI)(CI)F"; Flags: runhidden waituntilterminated; StatusMsg: "설정 폴더를 관리자만 열 수 있게 막는 중..."
Filename: "{sys}\icacls.exe"; Parameters: """{commonappdata}\AFTER MARKET\RPA\*"" /reset /T /C /Q"; Flags: runhidden waituntilterminated; StatusMsg: "설정 폴더를 관리자만 열 수 있게 막는 중..."
; 처음 설치면 설정 창, 판 올림이면 창 없이 작업 등록·에이전트 켜기. 조용한 설치에서는 창을 절대 띄우지 않는다 (기다리며 멈춘다)
Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\rpa_settings.py"" --after-install"; WorkingDir: "{app}"; Flags: waituntilterminated; StatusMsg: "설정 창에서 설정을 마치고 [저장] 을 누르세요..."; Check: not WizardSilent
Filename: "{app}\python\python.exe"; Parameters: """{app}\rpa_settings.py"" --after-install --no-window"; WorkingDir: "{app}"; Flags: runhidden waituntilterminated; Check: WizardSilent

[UninstallDelete]
Type: files; Name: "{group}\RPA 대시보드.url"
; 파이썬이 만든 __pycache__ 까지 남지 않게 프로그램 폴더를 통째로 (자리가 고정이라 안전하다)
Type: filesandordirs; Name: "{app}"
Type: dirifempty; Name: "{commonpf64}\AFTER MARKET"

[Code]
const
  EXIT_RPA_RUNNING = 5;
  EXIT_STOP_FAILED = 6;
  // 옵저버가 켜 있는 동안 쥐는 잠금 (rpa_status.OBSERVER_LOCK 과 같아야 한다). 켜진 exe 는 덮지도 지우지도 못한다
  OBSERVER_LOCK = 'Local\AFTER_MARKET_RPA_OBSERVER';
  OBSERVER_OPEN = '옵저버가 켜져 있습니다. 옵저버를 닫은 뒤 다시 ';

// 설치돼 있는 rpa_settings.py 를 창 없이 돌린다. 처음 설치라 파일이 없으면 -1, 못 띄우면 -2
function RunSettings(const Args: String): Integer;
var
  Py, Script: String;
  Code: Integer;
begin
  Result := -1;
  Py := ExpandConstant('{app}\python\python.exe');
  Script := ExpandConstant('{app}\rpa_settings.py');
  if FileExists(Py) and FileExists(Script) then
  begin
    if Exec(Py, AddQuotes(Script) + ' ' + Args, ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, Code) then
      Result := Code
    else
      Result := -2;
  end;
  Log(Format('rpa_settings %s -> %d', [Args, Result]));
end;

// 판을 올릴 때: 파일을 덮기 전에 에이전트를 멈춘다. RPA 가 돌면 설치를 멈춘다 (도는 exe 는 덮어쓸 수 없다)
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Code: Integer;
begin
  Result := '';
  // 에이전트를 멈추기 전에 본다 - 여기서 그만두면 에이전트는 그대로 돈다 (2026-10-02: 켜진 옵저버 exe 를 덮다 막혔다)
  if CheckForMutexes(OBSERVER_LOCK) then
  begin
    Result := OBSERVER_OPEN + '설치하세요.';
    exit;
  end;
  Code := RunSettings('--stop');
  if Code = EXIT_RPA_RUNNING then
    Result := 'RPA 가 돌고 있습니다. RPA 가 끝난 뒤 다시 설치하세요.'
  else if (Code <> 0) and (Code <> -1) then
  begin
    // 6(에이전트가 안 멈춤)뿐 아니라 뜻밖의 코드(설정 창이 오류로 죽음 등)도 멈췄다고 믿지 않는다 - 도는 파일을 덮으면 잠김 오류
    if SuppressibleMsgBox('에이전트를 멈추지 못했습니다. 에이전트 창(에이전트_시작.bat)이 열려 있으면 닫고 [예] 를 누르세요.' + #13#10 +
                          '[아니요] 를 누르면 설치를 그만둡니다.', mbConfirmation, MB_YESNO, IDYES) = IDNO then
      Result := '에이전트를 멈추지 못해 설치를 그만뒀습니다.';
  end;
end;

// 지우기 전: RPA 가 돌면 그만둔다. 확인만 한다 - 사람이 제거를 그만두면 에이전트가 꺼진 채 남지 않게,
// 멈추기는 파일을 지우기 직전(usUninstall 의 --remove-task)에 한다 (2026-09-29 검토)
function InitializeUninstall(): Boolean;
begin
  Result := True;
  if CheckForMutexes(OBSERVER_LOCK) then
  begin
    SuppressibleMsgBox(OBSERVER_OPEN + '지우세요.', mbError, MB_OK, IDOK);
    Result := False;
    exit;
  end;
  if RunSettings('--check-rpa') = EXIT_RPA_RUNNING then
  begin
    SuppressibleMsgBox('RPA 가 돌고 있습니다. RPA 가 끝난 뒤 다시 지우세요.', mbError, MB_OK, IDOK);
    Result := False;
  end;
end;

// 파일을 지우기 직전 작업을 지우고, 끝에 설정·기록을 지울지 묻는다 (기본 아니요 - 조용한 제거면 남긴다)
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Data: String;
begin
  if CurUninstallStep = usUninstall then
    RunSettings('--remove-task');
  if CurUninstallStep = usPostUninstall then
  begin
    Data := ExpandConstant('{commonappdata}\AFTER MARKET\RPA');
    if DirExists(Data) and (SuppressibleMsgBox('설정과 기록(' + Data + ')도 지울까요?' + #13#10 +
         '다시 설치해서 쓰려면 [아니요] 를 누르세요. 설정에는 잠근 비밀번호가 들어 있습니다.',
         mbConfirmation, MB_YESNO or MB_DEFBUTTON2, IDNO) = IDYES) then
    begin
      DelTree(Data, True, True, True);
      RemoveDir(ExpandConstant('{commonappdata}\AFTER MARKET'));
    end;
  end;
end;
