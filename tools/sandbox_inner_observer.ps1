# 윈도우 샌드박스 안에서 옵저버 단독 설치 파일을 시험한다 (tools/sandbox_test.py --observer 가 C:\test 로 넣고 로그온 때 돌린다).
# 1단계: 이 PC(샌드박스)의 MachineGuid 를 C:\test\guid.txt 에 적고, 호스트가 그 번호로 설치 파일을 만들어 C:\test\ready.txt 를 둘 때까지 기다린다.
# 2단계: 다른 PC 용 설치 파일은 거절되는지, 이 PC 용은 깔리는지 → 관제 서버·예약·실행·제거를 본다. 결과: C:\test\out\results.txt (끝에 '실패: N').
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
function Finish() {
    $results.Add("실패: $script:fails")
    $results | Set-Content "$O\results.txt" -Encoding UTF8
    "done" | Set-Content "$T\done.txt"
    shutdown /s /t 5
    exit
}
$App = "C:\Program Files\AFTER MARKET\Observer"
$PD = "C:\ProgramData\AFTER MARKET\Observer"
$Py = "$App\python\python.exe"
$SM = "C:\ProgramData\Microsoft\Windows\Start Menu\Programs\옵저버(Stand Alone)"
$Task = "오토파일럿 옵저버 관제"

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
Check "샌드박스 스크립트가 관리자 권한으로 돈다" $admin
if (-not $admin) { Finish }

# 1. 이 PC 의 번호를 호스트에 알리고 설치 파일을 기다린다
$guid = (Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Cryptography").MachineGuid.Trim().ToLower()
$guid | Set-Content "$T\guid.txt" -Encoding ASCII
Check "MachineGuid 를 읽었다" ($guid -match "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$") $guid
for ($i = 0; ($i -lt 600) -and -not (Test-Path "$T\ready.txt"); $i++) { Start-Sleep 1 }
Check "호스트가 이 PC 용 설치 파일을 만들었다" ((Test-Path "$T\ready.txt") -and (Test-Path "$T\setup.exe") -and (Test-Path "$T\setup_other.exe"))
if (-not (Test-Path "$T\setup.exe")) { Finish }

# 2. 다른 PC 용 설치 파일은 조용한 설치에서 메시지 없이 실패 코드로 끝나고 아무것도 깔지 않는다
$p = Start-Process "$T\setup_other.exe" -ArgumentList "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG=`"$O\setup_other.log`"" -Wait -PassThru
Check "다른 PC 용 설치 파일은 거절 (코드 0 아님, 프로그램 폴더 없음)" (($p.ExitCode -ne 0) -and -not (Test-Path "$App\observer_hub.py")) "코드 $($p.ExitCode)"

# 3. 이 PC 용 조용한 설치
$p = Start-Process "$T\setup.exe" -ArgumentList "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG=`"$O\setup.log`"" -Wait -PassThru
Check "조용한 설치 (코드 0)" ($p.ExitCode -eq 0) "코드 $($p.ExitCode)"
Check "프로그램 파일: 옵저버·ACTOR exe, observer_hub.py, 화면, 내장 파이썬, Observer_Hub.exe" ((Test-Path "$App\Prepare_Observer.exe") -and (Test-Path "$App\Prepare_RPA.exe") -and (Test-Path "$App\observer_hub.py") -and (Test-Path "$App\hub\index.html") -and (Test-Path "$App\python\Observer_Hub.exe") -and (Test-Path "$App\playwright\node.exe"))
Check "ERPia exe·에이전트·설정 창·업데이트 도우미·판 목록은 없다" (-not (Test-Path "$App\ERPia_RPA.exe") -and -not (Test-Path "$App\firebase") -and -not (Test-Path "$App\rpa_settings.py") -and -not (Test-Path "$App\update_helper.py") -and -not (Test-Path "$App\manifest.json"))
$flag = if (Test-Path "$App\OBSERVER_STANDALONE") { (Get-Content "$App\OBSERVER_STANDALONE" -Raw).Trim().ToLower() } else { "" }
Check "표시 파일 OBSERVER_STANDALONE 에 이 PC 의 번호" ($flag -eq $guid) "파일 '$flag' / PC '$guid'"
Check "새 자리 config·data (Observer)" ((Test-Path "$PD\config") -and (Test-Path "$PD\data"))
$acl = (icacls "$PD\config") -join "`n"
Check "config 는 관리자·SYSTEM 만" (($acl -match "Administrators") -and ($acl -match "SYSTEM") -and -not ($acl -match "Users")) $acl
Check "시작 메뉴 '옵저버(Stand Alone)'·'옵저버(Stand Alone) 관제', 바탕화면 '옵저버(Stand Alone) 관제'" ((Test-Path "$SM\옵저버(Stand Alone).lnk") -and (Test-Path "$SM\옵저버(Stand Alone) 관제.lnk") -and (Test-Path "C:\Users\Public\Desktop\옵저버(Stand Alone) 관제.lnk"))
Check "등대 아이콘과 favicon 이 설치됐다" ((Test-Path "$App\OBSERVER_SA.ico") -and (Test-Path "$App\hub\favicon.png"))
$q = (schtasks /Query /TN $Task /XML) -join "`n"
$q | Set-Content "$O\task.xml" -Encoding UTF8
Check "작업 스케줄러 '$Task' (가장 높은 권한·대화형·Observer_Hub.exe)" (($q -match "<RunLevel>HighestAvailable</RunLevel>") -and ($q -match "InteractiveToken") -and ($q -match "Observer_Hub\.exe"))
$sa = & $Py -c "import sys; sys.path.insert(0, r'$App'); import rpa_status as st; print(st.standalone(), st.standalone_pc_problem(), st.install_root())" 2>&1
Check "내장 파이썬에서 단독 표시 켜짐·이 PC 통과·ProgramData Observer" ("$sa" -like "True None *Observer*") "$sa"

# 4. 관제 서버 - 작업이 켠 Observer_Hub 를 포트 8775~8784 의 /healthz 서명으로 찾는다 (observer_hub.find_port 와 같다)
$port = ""
for ($i = 0; ($i -lt 60) -and ($port -eq ""); $i++) {
    foreach ($p in 8775..8784) {
        try { if ((Invoke-WebRequest "http://127.0.0.1:$p/healthz" -UseBasicParsing -TimeoutSec 2).Content.Trim() -eq "AUTOPILOT_OBSERVER_HUB") { $port = "$p"; break } } catch { }
    }
    if ($port -eq "") { Start-Sleep 1 }
}
Check "관제가 떠 있다 (/healthz 서명)" ($port -match "^\d+$") "port '$port'"
$hubOk = $false; $state = $null
try { $state = Invoke-RestMethod "http://127.0.0.1:$port/api/state" -TimeoutSec 10; $hubOk = $true } catch { $err = "$_" }
Check "GET /api/state 200 (127.0.0.1)" ($hubOk -and ($state.PSObject.Properties.Name -contains "presets") -and ($null -ne $state.schedule)) "$err"
Check "단독 한도: 프리셋 40·동시 실행 16" (($state.limits.presets -eq 40) -and ($state.limits.parallel_max -eq 16)) "$($state.limits | ConvertTo-Json -Compress)"
$ip = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } | Select-Object -First 1).IPAddress
$lan = $false
if ($ip) { try { Invoke-RestMethod "http://${ip}:$port/api/state" -TimeoutSec 5 | Out-Null; $lan = $true } catch { } }
Check "다른 IP($ip)로는 연결되지 않는다 (127.0.0.1 에만)" (-not $lan)
$html = ""
try { $html = (Invoke-WebRequest "http://127.0.0.1:$port/" -UseBasicParsing -TimeoutSec 10).Content } catch { }
Check "관제 화면 html 이 나온다" ($html.Contains("옵저버(Stand Alone) 관제"))
$body = '{"enabled":true,"days":[0,1,2,3,4],"slots":[{"at":"09:00","presets":[1]}],"skip_holidays":true,"off_dates":[]}'
$sch = $null
try { $sch = Invoke-RestMethod "http://127.0.0.1:$port/api/schedule" -Method Post -ContentType "application/json" -Body $body -TimeoutSec 10 } catch { $err = "$_" }
Check "POST /api/schedule 저장 (presets [1])" (($null -ne $sch) -and $sch.ok -and ($sch.schedule.slots[0].presets -contains 1)) "$err"
$evil = 0
try { Invoke-RestMethod "http://127.0.0.1:$port/api/run" -Method Post -ContentType "application/json" -Body '{"presets":null}' -Headers @{ Origin = "http://evil.example" } -TimeoutSec 10 | Out-Null } catch { $evil = $_.Exception.Response.StatusCode.value__ }
Check "다른 Origin 의 POST 는 403" ($evil -eq 403) "$evil"
$run = $null
try { $run = Invoke-RestMethod "http://127.0.0.1:$port/api/run" -Method Post -ContentType "application/json" -Body '{"presets":null}' -TimeoutSec 10 } catch { $err = "$_" }
Check "POST /api/run {presets:null} → ACTOR 띄움" (($null -ne $run) -and $run.ok) "$err"
$hist = $null
for ($i = 0; $i -lt 90; $i++) {
    Start-Sleep 2
    try { $hist = Invoke-RestMethod "http://127.0.0.1:$port/api/history?period=7" -TimeoutSec 10 } catch { }
    if ($hist -and $hist.summary.total -ge 1) { break }
}
Check "ACTOR 가 '프리셋 없음' 으로 끝나 기록 1줄" (($null -ne $hist) -and ($hist.summary.total -eq 1) -and ($hist.runs[0].program -eq "prepare")) "$($hist | ConvertTo-Json -Compress -Depth 4)"
Check "기록 폴더는 ProgramData Observer (바탕화면 ERPIA_AI 없음)" ((Test-Path "$PD\data\status\history.jsonl") -and -not (Test-Path "$env:USERPROFILE\Desktop\ERPIA_AI"))

# 5. 같은 PC 에 다시 설치 (덮어쓰기) 된다 - 관제(작업)를 끝내고 덮는다
$p = Start-Process "$T\setup.exe" -ArgumentList "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG=`"$O\setup2.log`"" -Wait -PassThru
Check "같은 PC 에 다시 설치 (코드 0)" ($p.ExitCode -eq 0) "코드 $($p.ExitCode)"
Check "다시 설치해도 설정(예약)은 그대로" ((Get-Content "$PD\data\status\settings.json" -Raw) -match '"presets"')

# 6. 조용한 제거: 작업·프로그램·시작 메뉴는 없어지고 설정·기록은 남는다
Get-CimInstance Win32_Process -Filter "Name='Observer_Hub.exe'" | ForEach-Object { taskkill /F /T /PID $_.ProcessId 2>&1 | Out-Null }
Start-Process "$App\unins000.exe" -ArgumentList "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART" -Wait
for ($i = 0; ($i -lt 60) -and (Test-Path $App); $i++) { Start-Sleep 1 }
Check "제거: 프로그램 폴더가 없다" (-not (Test-Path $App))
schtasks /Query /TN $Task *> $null
Check "제거: 작업이 없다" ($LASTEXITCODE -ne 0)
Check "제거: 시작 메뉴·바탕화면 바로 가기가 없다" (-not (Test-Path $SM) -and -not (Test-Path "C:\Users\Public\Desktop\옵저버(Stand Alone) 관제.lnk"))
Check "제거: 설정·기록은 남는다" ((Test-Path "$PD\config") -and (Test-Path "$PD\data\status\settings.json"))
Finish
