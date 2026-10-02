# 윈도우 샌드박스 안에서 설치 파일을 시험한다 (tools/sandbox_test.py 가 C:\test 로 넣고 로그온 때 돌린다).
# 결과: C:\test\out\results.txt (통과/실패 줄, 끝에 '실패: N'), 설치 기록, 에이전트 기록, 설정 창 사진. 끝나면 샌드박스를 끈다.
# 이 파일은 BOM 있는 UTF-8 로 저장한다 (PowerShell 5.1 이 BOM 없는 파일을 ANSI 로 읽어 한글이 깨진다).
$ErrorActionPreference = "Continue"
$T = "C:\test"; $O = "$T\out"
New-Item -ItemType Directory -Force $O | Out-Null
$results = New-Object System.Collections.Generic.List[string]
$script:fails = 0
function Check($name, $ok, $detail = "") {
    if ($ok) { $results.Add("통과  $name") } else { $script:fails++; $results.Add("실패  $name  $detail") }
    $results | Set-Content "$O\results.txt" -Encoding UTF8
}
$App = "C:\Program Files\AFTER MARKET\RPA"
$PD = "C:\ProgramData\AFTER MARKET\RPA"
$Py = "$App\python\python.exe"
$SM = "C:\ProgramData\Microsoft\Windows\Start Menu\Programs\AFTER MARKET RPA"
$Task = "AFTER MARKET\RPA Agent"

# 0. 관리자 권한으로 도는가 - 아니면 조용한 설치가 UAC 창 앞에서 기다리며 멈추니 바로 끝낸다
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
Check "샌드박스 스크립트가 관리자 권한으로 돈다" $admin
if (-not $admin) {
    $results.Add("실패: $script:fails")
    $results | Set-Content "$O\results.txt" -Encoding UTF8
    "done" | Set-Content "$T\done.txt"
    shutdown /s /t 5
    exit
}

# 1. 조용한 설치
$p = Start-Process "$T\setup.exe" -ArgumentList "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG=`"$O\setup1.log`"" -Wait -PassThru
Check "조용한 설치 (코드 0)" ($p.ExitCode -eq 0) "코드 $($p.ExitCode)"
Check "프로그램 파일" ((Test-Path "$App\rpa_settings.py") -and (Test-Path "$App\firebase\agent\background.py") -and (Test-Path "$App\python\pythonw.exe") -and (Test-Path "$App\ERPia_RPA.exe") -and (Test-Path "$App\ms-playwright") -and (Test-Path "$App\manifest.json"))
Check "빈 틀은 template 이름으로, 진짜 설정 이름·안내 문서는 없다" ((Test-Path "$App\RPA_UserConfig.template.json") -and -not (Test-Path "$App\RPA_UserConfig.json") -and -not (Test-Path "$App\배포안내.txt"))
$ver = & $Py -c "import sys; sys.path.insert(0, r'$App'); import rpa_status as st; r = st.check_install(r'$App'); print(r['state'], r['version'])"
Check "판 점검 ok" ("$ver" -like "ok *") "$ver"
Check "새 자리 config·data" ((Test-Path "$PD\config") -and (Test-Path "$PD\data"))
$acl = (icacls "$PD\config") -join "`n"
$acl | Set-Content "$O\acl.txt" -Encoding UTF8
Check "config 는 관리자·SYSTEM 만" (($acl -match "Administrators") -and ($acl -match "SYSTEM") -and -not ($acl -match "Users") -and -not ($acl -match "CREATOR OWNER")) $acl
Check "시작 메뉴 바로 가기 둘" ((Test-Path "$SM\RPA 설정.lnk") -and (Test-Path "$SM\RPA 대시보드.url"))
$un = Get-ChildItem "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall" | Where-Object { $_.GetValue("DisplayName") -eq "AFTER MARKET RPA" }
Check "앱 및 기능 목록" ($null -ne $un)
# 아이콘 (2026-09-30): 바로 가기 둘·제거 목록이 설치 폴더의 AFTER_MARKET.ico 를 쓴다
$Ico = "$App\AFTER_MARKET.ico"
$lnkIcon = (New-Object -ComObject WScript.Shell).CreateShortcut("$SM\RPA 설정.lnk").IconLocation
$urlIcon = Select-String -Path "$SM\RPA 대시보드.url" -Pattern "^IconFile=(.*)$" -ErrorAction SilentlyContinue | ForEach-Object { $_.Matches[0].Groups[1].Value }
$unIcon = if ($un) { $un.GetValue("DisplayIcon") }
Check "아이콘: 설정·대시보드 바로 가기, 앱 및 기능 목록" ((Test-Path $Ico) -and ($lnkIcon -like "$Ico*") -and ($urlIcon -eq $Ico) -and ($unIcon -eq $Ico)) "lnk=$lnkIcon url=$urlIcon un=$unIcon"
$recLnk = (New-Object -ComObject WScript.Shell).CreateShortcut("$SM\RPA 옵저버.lnk")
Check "시작 메뉴 'RPA 옵저버' (옵저버 exe, 주황 아이콘)" (($recLnk.TargetPath -eq "$App\Prepare_Observer.exe") -and ($recLnk.IconLocation -like "$App\AFTER_MARKET_PREPARE.ico*")) "target=$($recLnk.TargetPath) icon=$($recLnk.IconLocation)"
$tk = & $Py -c "import tkinter; r = tkinter.Tk(); r.destroy(); print('tk ok')"
Check "내장 파이썬 tkinter" ("$tk" -eq "tk ok") "$tk"
# exe 가 새 윈도우에서 켜지는가 (2026-09-29 노트북: System32 에만 있던 mfc140u.dll 이 exe 에 안 들어가 win32ui 에서 죽었다).
# 빌드 PC 점검(smoke_check)과 같게 임시 설정으로 --check. 파일로 받으면 CP949 로 찍혀 나와서(샌드박스 실측) 둘 다 본다
# 노트북 흉내: 윈도우 판이 다르면 UIAutomationCore.dll 시각이 빌드 PC 와 달라, exe 에 묶인 comtypes 모듈이 거부된다
# (2026-09-29 노트북 'Typelib different than module'). 샌드박스는 이 PC 의 윈도우 파일을 빌려 써서 그대로 두면 못 잡는다
$uia = "C:\Windows\System32\UIAutomationCore.dll"
takeown /f $uia | Out-Null
icacls $uia /grant "*S-1-5-32-544:F" | Out-Null
(Get-Item $uia).LastWriteTime = Get-Date "2020-01-01"
Check "UIAutomationCore.dll 시각을 바꿨다 (빌드 PC 와 다른 윈도우 흉내)" ((Get-Item $uia).LastWriteTime.Year -eq 2020)
$X = "$O\exe"
New-Item -ItemType Directory -Force "$X\cfg" | Out-Null
Copy-Item "$App\RPA_UserConfig.template.json" "$X\cfg\RPA_UserConfig.json"
$env:RPA_USER_CONFIG = "$X\cfg\RPA_UserConfig.json"; $env:RPA_PROGRAMDATA = "$X\pd"; $env:RPA_STATUS_DIR = "$X\st"; $env:RPA_UNATTENDED = "1"
foreach ($e in @(@("ERPia_RPA.exe", "=== 점검 끝"), @("Prepare_RPA.exe", "쓸 수 있는 Action"), @("Prepare_Observer.exe", "옵저버 점검 끝"))) {
    $p = Start-Process "$App\$($e[0])" -ArgumentList "--check" -WorkingDirectory $App -PassThru -WindowStyle Hidden -RedirectStandardOutput "$X\$($e[0]).out.txt" -RedirectStandardError "$X\$($e[0]).err.txt"
    $done = $p.WaitForExit(180000)
    $bytes = [IO.File]::ReadAllBytes("$X\$($e[0]).out.txt") + [IO.File]::ReadAllBytes("$X\$($e[0]).err.txt")
    $u8 = [Text.Encoding]::UTF8.GetString($bytes); $ks = [Text.Encoding]::GetEncoding(949).GetString($bytes)
    Check "$($e[0]) --check 가 켜져 끝까지 간다" ($done -and ($u8.Contains($e[1]) -or $ks.Contains($e[1]))) ($u8.Substring([Math]::Max(0, $u8.Length - 300)))
}
Remove-Item Env:RPA_USER_CONFIG, Env:RPA_PROGRAMDATA, Env:RPA_STATUS_DIR, Env:RPA_UNATTENDED

# 2. 가짜 설정 (로그인 없이 파일만) → --after-install --no-window → 작업 등록·에이전트 켜기
$cfg = @'
import os, sys
app = r"C:\Program Files\AFTER MARKET\RPA"
sys.path.insert(0, app); sys.path.insert(0, os.path.join(app, "firebase", "agent"))
import rpa_status as st, secret, agent
data = st.read_user_config(os.path.join(app, "RPA_UserConfig.template.json"))
data["LogIn"].update(AdminCode="sbx", ID="sbx", PW="sbx-pw")
st.write_user_config(data, st.user_config_path())
secret.write_config(secret.CONFIG_PATH, dict(secret.PUBLIC, email=agent.email_for("sbx", "sbx"), cid="sbx", pc_id="sbx"), "not-the-password")
print("cfg ok")
'@
[IO.File]::WriteAllText("$O\cfg.py", $cfg, (New-Object Text.UTF8Encoding($false)))
$c = & $Py "$O\cfg.py"
Check "가짜 설정을 썼다" ("$c" -eq "cfg ok") "$c"
$p = Start-Process $Py -ArgumentList "`"$App\rpa_settings.py`" --after-install --no-window" -Wait -PassThru -WindowStyle Hidden
Check "--after-install --no-window (코드 0)" ($p.ExitCode -eq 0) "코드 $($p.ExitCode)"
$q = (schtasks /Query /TN $Task /XML) -join "`n"
$q | Set-Content "$O\task.xml" -Encoding UTF8
Check "작업 등록 (가장 높은 권한·배터리·제한 없음·우선순위 5)" (($q -match "<RunLevel>HighestAvailable</RunLevel>") -and ($q -match "<DisallowStartIfOnBatteries>false") -and ($q -match "<StopIfGoingOnBatteries>false") -and ($q -match "<ExecutionTimeLimit>PT0S") -and ($q -match "<Priority>5</Priority>"))
# 작업 관리자에 'Python' 대신 AFTER MARKET 으로 (2026-09-29 요청): 작업은 감독 사본으로, 감독은 에이전트 사본으로 띄운다
$Brand = @{ "AFTER_MARKET_RPA_Supervisor.exe" = "AFTER MARKET RPA 에이전트 감독"; "AFTER_MARKET_RPA_Agent.exe" = "AFTER MARKET RPA 에이전트" }
Check "작업이 AFTER MARKET 감독 사본으로 띄운다" ($q -match "AFTER_MARKET_RPA_Supervisor\.exe")
$desc = @($Brand.Keys | Where-Object { (Get-Item "$App\python\$_").VersionInfo.FileDescription -eq $Brand[$_] })
Check "AFTER MARKET 사본 설명 둘 (작업 관리자 '프로세스' 탭 글자)" ($desc.Count -eq 2) ($Brand.Keys | ForEach-Object { "$_=" + (Get-Item "$App\python\$_" -ErrorAction SilentlyContinue).VersionInfo.FileDescription })
# 탐색기·작업 관리자가 보여 주는 아이콘을 ico 파일의 것과 견준다. 루틴·프리페어 exe 는 Nuitka 로 새로 빌드한 판이어야 맞다 (--exes-from 옛 exe 면 실패)
# 프리페어·옵저버는 주황 A (2026-09-30 '나. 주황 A' - 작업 표시줄에서 루틴과 가른다)
Add-Type -AssemblyName System.Drawing
function IconPng($path) { $ms = New-Object IO.MemoryStream; [Drawing.Icon]::ExtractAssociatedIcon($path).ToBitmap().Save($ms, [Drawing.Imaging.ImageFormat]::Png); [Convert]::ToBase64String($ms.ToArray()) }
$IcoPrep = "$App\AFTER_MARKET_PREPARE.ico"
$want = @{ "ERPia_RPA.exe" = $Ico; "Prepare_RPA.exe" = $IcoPrep; "Prepare_Observer.exe" = $IcoPrep }
$Brand.Keys | ForEach-Object { $want["python\$_"] = $Ico }
$plain = @($want.Keys | Where-Object { (-not (Test-Path "$App\$_")) -or (-not (Test-Path $want[$_])) -or ((IconPng "$App\$_") -ne (IconPng $want[$_])) })
Check "exe 다섯의 아이콘: 루틴·감독·에이전트는 크림 A, 프리페어·옵저버는 주황 A" (($plain.Count -eq 0) -and ((IconPng $Ico) -ne (IconPng $IcoPrep))) ($plain -join ", ")

# 3. 감독 → 에이전트. 인터넷이 있으면: 가짜 비밀번호라 로그인이 거부되고(3) 감독도 같이 끝난다 (틀린 비밀번호로
#    되풀이하지 않는다). 없으면 (2026-09-29 첫 시험의 샌드박스가 그랬다): 에이전트는 죽지 않고 다시 붙으려 한다
$log = "$PD\data\에이전트_기록.txt"
$online = $false
try { Invoke-WebRequest -Uri "https://identitytoolkit.googleapis.com/" -UseBasicParsing -TimeoutSec 10 | Out-Null; $online = $true }
catch { if ($_.Exception.Response) { $online = $true } }      # 404 여도 닿은 것이다
$results.Add("참고  샌드박스 인터넷: $(if ($online) { '있음' } else { '없음' })")
function AgentProcs { @(Get-CimInstance Win32_Process -Filter "Name='python.exe' or Name='pythonw.exe' or Name='AFTER_MARKET_RPA_Supervisor.exe' or Name='AFTER_MARKET_RPA_Agent.exe'" | Where-Object { $_.CommandLine -match "background\.py|agent\.py" }) }
if ($online) {
    $ok3 = $false; $seen = @{}
    for ($i = 0; $i -lt 600; $i++) {        # 0.2초마다 - 가짜 비밀번호라 에이전트는 몇 초만 산다
        Start-Sleep -Milliseconds 200
        AgentProcs | ForEach-Object { $seen[$_.Name] = 1 }
        if (($i % 5 -eq 0) -and (Test-Path $log) -and ((Get-Content $log -Encoding UTF8 -Raw) -match "코드 3")) { $ok3 = $true; break }
    }
    Check "감독이 에이전트를 띄웠고, 로그인 거부(3)에 같이 끝났다" $ok3
    Check "감독·에이전트가 AFTER MARKET 이름으로 떴다" ($seen.ContainsKey("AFTER_MARKET_RPA_Supervisor.exe") -and $seen.ContainsKey("AFTER_MARKET_RPA_Agent.exe")) (($seen.Keys) -join ", ")
    $stopJson = if (Test-Path "$PD\data\에이전트_멈춤.json") { Get-Content "$PD\data\에이전트_멈춤.json" -Encoding UTF8 -Raw } else { "" }
    Check "멈춘 까닭을 설정 창이 볼 파일에 남겼다 (코드 3)" ($stopJson -match '"code": 3') $stopJson
    Start-Sleep 2
    $left = AgentProcs
    Check "감독·에이전트가 남아 있지 않다" ($left.Count -eq 0) (($left | ForEach-Object { $_.CommandLine }) -join " | ")
} else {
    Start-Sleep 20
    $text = if (Test-Path $log) { Get-Content $log -Encoding UTF8 -Raw } else { "" }
    $retries = ([regex]::Matches($text, "구독이 끊겼습니다")).Count
    $procs = AgentProcs
    Check "인터넷이 없어도 에이전트는 죽지 않고 다시 붙으려 한다 (감독·에이전트 둘 다 창 없이 돈다)" (($text -match "감독: 시작합니다") -and ($retries -ge 2) -and ($procs.Count -eq 2)) "다시 붙기 $retries 번, 프로세스 $($procs.Count)"
    $names = @($procs | ForEach-Object { $_.Name })
    Check "감독·에이전트가 AFTER MARKET 이름으로 떴다" (($names -contains "AFTER_MARKET_RPA_Supervisor.exe") -and ($names -contains "AFTER_MARKET_RPA_Agent.exe")) ($names -join ", ")
}
Copy-Item $log "$O\agent_log1.txt" -ErrorAction SilentlyContinue
Copy-Item "$PD\data\에이전트_오류.txt" "$O\agent_err1.txt" -ErrorAction SilentlyContinue

# 4. 한 번 더 설치 (판 올림 흉내). 옵저버가 켜져 있으면 (잠금 이름은 rpa_status.OBSERVER_LOCK) 파일을 덮기 전에 멈춘다 -
#    켜진 exe 는 덮을 수 없어 설치가 가운데서 막혔다 (2026-10-02). 그때는 에이전트도 멈추지 않는다 (--stop 을 안 부른다)
$obs = New-Object System.Threading.Mutex($false, "Local\AFTER_MARKET_RPA_OBSERVER")
$p = Start-Process "$T\setup.exe" -ArgumentList "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG=`"$O\setup_observer.log`"" -Wait -PassThru
$lo = Get-Content "$O\setup_observer.log" -Raw
Check "옵저버가 켜져 있으면 설치를 시작 전에 멈춘다 (코드 7, 에이전트는 안 멈춤)" (($p.ExitCode -eq 7) -and -not ($lo -match "rpa_settings --stop")) "코드 $($p.ExitCode)"
$obs.Dispose()
# 이제 정말로: 먼저 --stop, 끝나면 창 없이 작업 등록·켜기
$p = Start-Process "$T\setup.exe" -ArgumentList "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG=`"$O\setup2.log`"" -Wait -PassThru
Check "다시 설치 (코드 0)" ($p.ExitCode -eq 0) "코드 $($p.ExitCode)"
$l2 = Get-Content "$O\setup2.log" -Raw
Check "파일을 덮기 전에 --stop (0)" ($l2 -match "rpa_settings --stop -> 0")

# 5. 설정 창 사진 (이 샌드박스 계정은 관리자라 바로 뜬다)
$w = Start-Process "$App\python\pythonw.exe" -ArgumentList "`"$App\rpa_settings.py`"" -PassThru
Start-Sleep 10
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
$b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size)
$bmp.Save("$O\settings.png")
$g.Dispose(); $bmp.Dispose()
Check "설정 창이 떴다 (사진 settings.png)" (-not $w.HasExited)
Stop-Process -Id $w.Id -Force -ErrorAction SilentlyContinue

# 6. 조용한 제거: 작업·프로그램·시작 메뉴는 없어지고 설정·기록은 남는다 (조용한 제거의 기본)
Start-Process "$App\unins000.exe" -ArgumentList "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART" -Wait
for ($i = 0; ($i -lt 60) -and (Test-Path $App); $i++) { Start-Sleep 1 }
Check "제거: 프로그램 폴더가 없다" (-not (Test-Path $App))
schtasks /Query /TN $Task *> $null
Check "제거: 작업이 없다" ($LASTEXITCODE -ne 0)
Check "제거: 시작 메뉴가 없다" (-not (Test-Path $SM))
Check "제거: 설정·기록은 남는다" (Test-Path "$PD\config\agent_config.json")

$results.Add("실패: $script:fails")
$results | Set-Content "$O\results.txt" -Encoding UTF8
"done" | Set-Content "$T\done.txt"
shutdown /s /t 5
