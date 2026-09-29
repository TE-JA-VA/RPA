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
$tk = & $Py -c "import tkinter; r = tkinter.Tk(); r.destroy(); print('tk ok')"
Check "내장 파이썬 tkinter" ("$tk" -eq "tk ok") "$tk"

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

# 3. 감독 → 에이전트. 인터넷이 있으면: 가짜 비밀번호라 로그인이 거부되고(3) 감독도 같이 끝난다 (틀린 비밀번호로
#    되풀이하지 않는다). 없으면 (2026-09-29 첫 시험의 샌드박스가 그랬다): 에이전트는 죽지 않고 다시 붙으려 한다
$log = "$PD\data\에이전트_기록.txt"
$online = $false
try { Invoke-WebRequest -Uri "https://identitytoolkit.googleapis.com/" -UseBasicParsing -TimeoutSec 10 | Out-Null; $online = $true }
catch { if ($_.Exception.Response) { $online = $true } }      # 404 여도 닿은 것이다
$results.Add("참고  샌드박스 인터넷: $(if ($online) { '있음' } else { '없음' })")
function AgentProcs { @(Get-CimInstance Win32_Process -Filter "Name='python.exe' or Name='pythonw.exe'" | Where-Object { $_.CommandLine -match "background\.py|agent\.py" }) }
if ($online) {
    $ok3 = $false
    for ($i = 0; $i -lt 120; $i++) {
        Start-Sleep 1
        if ((Test-Path $log) -and ((Get-Content $log -Encoding UTF8 -Raw) -match "코드 3")) { $ok3 = $true; break }
    }
    Check "감독이 에이전트를 띄웠고, 로그인 거부(3)에 같이 끝났다" $ok3
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
}
Copy-Item $log "$O\agent_log1.txt" -ErrorAction SilentlyContinue
Copy-Item "$PD\data\에이전트_오류.txt" "$O\agent_err1.txt" -ErrorAction SilentlyContinue

# 4. 한 번 더 설치 (판 올림 흉내): 먼저 --stop, 끝나면 창 없이 작업 등록·켜기
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
