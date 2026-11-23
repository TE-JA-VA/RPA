# 윈도우 샌드박스 안에서 스탠드얼론 설치 파일을 시험한다 (계획 ③ Task 6 - tools/sandbox_test.py --standalone 이 C:\test 로 넣는다).
# 결과: C:\test\out\results.txt (통과/실패 줄, 끝에 '실패: N'), 설치·에이전트·로컬 서버 기록, trap.txt. 끝나면 샌드박스를 끈다.
# 일반 버전의 sandbox_inner.ps1 은 고치지 않는다. 이 파일은 BOM 있는 UTF-8 (PowerShell 5.1 이 BOM 없는 파일을 ANSI 로 읽는다).
# 파이썬이 찍는 한글은 콘솔 코드 페이지라 깨질 수 있다 - 한글을 견줄 때는 파일(UTF-8)로 받거나 두 가지로 읽는다.
$ErrorActionPreference = "Continue"
$T = "C:\test"; $O = "$T\out"
New-Item -ItemType Directory -Force $O | Out-Null
$results = New-Object System.Collections.Generic.List[string]
$script:fails = 0
function Save { $results | Set-Content "$O\results.txt" -Encoding UTF8 }
function Check($name, $ok, $detail = "") {
    if ($ok) { $results.Add("통과  $name") } else { $script:fails++; $results.Add("실패  $name  $detail") }
    Save
}
function Note($text) { $results.Add("참고  $text"); Save }
function Finish {
    Copy-Item "$PD\data\에이전트_기록.txt" "$O\agent_log.txt" -ErrorAction SilentlyContinue
    Copy-Item "$PD\data\에이전트_오류.txt" "$O\agent_err.txt" -ErrorAction SilentlyContinue
    Copy-Item "$KD\로컬서버_기록.txt" "$O\server_log.txt" -ErrorAction SilentlyContinue
    $results.Add("실패: $script:fails")
    Save
    "done" | Set-Content "$T\done.txt"
    shutdown /s /t 5
    exit
}
$App = "C:\Program Files\AFTER MARKET\RPA"
$PD = "C:\ProgramData\AFTER MARKET\RPA"
$KD = "$PD\standalone"
$Py = "$App\python\python.exe"
$SM = "C:\ProgramData\Microsoft\Windows\Start Menu\Programs\오토파일럿"
$Task = "AFTER MARKET\RPA Agent"
$Uninst = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
$SaKey = "$Uninst\{7D2E9A61-3B4F-4C8D-A5E2-91F0C6B3D7A4}_is1"
$CloudKey = "$Uninst\{C3F7A2B4-5E81-4D2A-9B6C-7A1E0F3D8B52}_is1"
$Over = Test-Path "$T\over_cloud.exe"
$Admin = "sbxadmin"; $Pw1 = "Sbx-First-2026"; $Pw2 = "Sbx-Second-2026"     # 샌드박스 안에서만 쓰는 시험 계정
$X = "$O\exe"
New-Item -ItemType Directory -Force $X | Out-Null

# exe 를 창 없이 돌려 (출력 글, 종료 코드) - 콘솔 출력은 UTF-8·CP949 둘 다로 읽는다. 시간을 넘기면 끈다 (코드 -1)
function RunExe($exe, $arg, $tag, $sec = 180) {
    $o = "$X\$tag.out.txt"; $e = "$X\$tag.err.txt"
    if ($arg) { $p = Start-Process "$App\$exe" -ArgumentList $arg -WorkingDirectory $App -PassThru -WindowStyle Hidden -RedirectStandardOutput $o -RedirectStandardError $e }
    else { $p = Start-Process "$App\$exe" -WorkingDirectory $App -PassThru -WindowStyle Hidden -RedirectStandardOutput $o -RedirectStandardError $e }
    $null = $p.Handle                                # 손잡이를 쥐어 둬야 끝난 뒤 ExitCode 가 비지 않는다 (PowerShell 5.1 - 첫 샌드박스에서 코드가 비었다)
    $ended = $p.WaitForExit($sec * 1000)
    if (-not $ended) { taskkill /F /T /PID $p.Id 2>&1 | Out-Null }
    $b = [IO.File]::ReadAllBytes($o) + [IO.File]::ReadAllBytes($e)
    $text = [Text.Encoding]::UTF8.GetString($b) + "`n" + [Text.Encoding]::GetEncoding(949).GetString($b)
    return @{ Text = $text; Code = $(if ($ended) { $p.ExitCode } else { -1 }) }
}
function Tail($s, $n = 300) { "$s".Substring([Math]::Max(0, "$s".Length - $n)) -replace "\s+", " " }
# 내장 파이썬으로 짧은 코드 - 결과를 UTF-8 파일로 받아 읽는다 (한글이 깨지지 않게)
function PyOut($code, $tag) {
    $f = "$X\py_$tag.txt"
    Remove-Item $f -ErrorAction SilentlyContinue
    $full = "import sys, os`nsys.path[:0] = [r'$App', os.path.join(r'$App', 'firebase', 'agent')]`n_out = open(r'$f', 'w', encoding='utf-8')`ntry:`n" +
            (($code -split "`n" | ForEach-Object { "    $_" }) -join "`n") + "`nexcept Exception as _e:`n    _out.write('오류 ' + type(_e).__name__ + ': ' + str(_e))`n_out.close()`n"
    [IO.File]::WriteAllText("$X\py_$tag.py", $full, (New-Object Text.UTF8Encoding($false)))
    & $Py "$X\py_$tag.py" 2>&1 | Out-File "$X\py_$tag.err.txt"
    if (Test-Path $f) { (Get-Content $f -Raw -Encoding UTF8) } else { "(출력 없음) " + (Get-Content "$X\py_$tag.err.txt" -Raw) }
}
function StatusOf($prog) { PyOut "import rpa_status as st`n_out.write(open(st.status_path('$prog'), encoding='utf-8').read())" "status_$prog" }
function AclSids($path) { @((Get-Acl $path).Access | ForEach-Object { $_.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value } | Sort-Object -Unique) }
function Listening($port) { $null -ne (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) }
function WaitListen($port, $sec) { for ($i = 0; $i -lt $sec; $i++) { if (Listening $port) { return $true }; Start-Sleep 1 }; return $false }
function ServerProcs { @(Get-CimInstance Win32_Process -Filter "Name='python.exe' or Name='pythonw.exe' or Name='AFTER_MARKET_RPA_Supervisor.exe' or Name='AFTER_MARKET_RPA_Agent.exe'" | Where-Object { $_.CommandLine -match "local_server\.py" }) }
function TrapCount { if (Test-Path "$O\trap.txt") { @(Get-Content "$O\trap.txt").Count } else { 0 } }

# 0. 관리자 권한 - 아니면 조용한 설치가 UAC 창 앞에서 멈추니 바로 끝낸다
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
Check "샌드박스 스크립트가 관리자 권한으로 돈다" $isAdmin
if (-not $isAdmin) { Finish }

# 0-1. PC 번호(MachineGuid)를 라이선스의 샌드박스 번호로 (가정 확인 - 안 되면 여기서 끝낸다)
$want = (Get-Content "$T\guid.txt" -Raw).Trim()
$cr = "HKLM:\SOFTWARE\Microsoft\Cryptography"
$before = (Get-ItemProperty $cr).MachineGuid
$err = ""
try { Set-ItemProperty -Path $cr -Name MachineGuid -Value $want -ErrorAction Stop } catch { $err = "$_" }
$got = (Get-ItemProperty $cr).MachineGuid
$reg64 = (reg query "HKLM\SOFTWARE\Microsoft\Cryptography" /v MachineGuid /reg:64) -join " "
Check "MachineGuid 를 샌드박스 번호로 바꿨다 (64비트 보기의 reg query 도 같은 값 - PC번호_확인.bat 이 읽는 자리)" (($got -eq $want) -and ($reg64 -match [regex]::Escape($want))) "전 $before / 지금 $got / $err"
if ($got -ne $want) { Finish }

# 0-2. 막을 주소 → 127.0.0.2 (hosts), 덫을 띄우고 견줌으로 하나를 일부러 불러 세는지 본다
$block = @(Get-Content "$T\hosts_block.txt" | Where-Object { $_.Trim() })
$hostsPath = "$env:SystemRoot\System32\drivers\etc\hosts"
Add-Content $hostsPath ("`r`n" + ($block -join "`r`n") + "`r`n") -Encoding ASCII
ipconfig /flushdns | Out-Null
Start-Process powershell.exe -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$T\trap.ps1`"" -WindowStyle Hidden | Out-Null
for ($i = 0; ($i -lt 40) -and -not (Test-Path "$O\trap_ready.txt"); $i++) { Start-Sleep -Milliseconds 500 }
Check "덫이 127.0.0.2 의 80·443 을 듣는다" (Test-Path "$O\trap_ready.txt")
$h0 = ($block[0] -split "\s+")[1]
$ips = @([Net.Dns]::GetHostAddresses($h0) | ForEach-Object { $_.IPAddressToString })
try { Invoke-WebRequest "http://$h0/" -UseBasicParsing -TimeoutSec 8 | Out-Null } catch {}
Start-Sleep 2
$base = TrapCount
Check "견줌: 막은 주소 $h0 가 127.0.0.2 로 풀리고, 일부러 부르면 덫이 센다 (막은 주소 $($block.Count)개)" (($ips -contains "127.0.0.2") -and ($base -ge 1)) "풀린 주소 $($ips -join ',') / 덫 $base"
Note "덫 기준 줄 수 $base (이 뒤로 늘면 막은 주소로 연결을 시도한 것)"

if ($Over) {
    # --over-cloud: 일반 버전이 깔린 PC 에 스탠드얼론 설치 파일 → 시작 전에 멈추고 일반 설치는 그대로
    $p = Start-Process "$T\over_cloud.exe" -ArgumentList "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG=`"$O\setup_cloud.log`"" -Wait -PassThru
    Check "일반 버전 조용한 설치 (코드 0)" ($p.ExitCode -eq 0) "코드 $($p.ExitCode)"
    $v0 = (Get-Content "$App\manifest.json" -Raw | ConvertFrom-Json).version
    $p = Start-Process "$T\setup.exe" -ArgumentList "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG=`"$O\setup_sa_over.log`"" -Wait -PassThru
    Check "일반 버전이 깔린 PC 에서 스탠드얼론 설치 파일은 시작 전에 멈춘다 (코드 1)" ($p.ExitCode -eq 1) "코드 $($p.ExitCode)"
    $lg = if (Test-Path "$O\setup_sa_over.log") { Get-Content "$O\setup_sa_over.log" -Raw } else { "" }
    Note "스탠드얼론 설치 기록에 '일반 버전이 설치되어' 알림: $(if ($lg -match '일반 버전이 설치되어') { '있음' } else { '없음 (조용한 설치의 알림은 기록에 안 남을 수 있다)' })"
    $v1 = (Get-Content "$App\manifest.json" -Raw | ConvertFrom-Json).version
    Check "일반 설치가 그대로 (edition.json 없음, 같은 버전 $v0, 일반 제거 등록 있음·스탠드얼론 등록 없음)" ((-not (Test-Path "$App\edition.json")) -and ($v0 -eq $v1) -and (Test-Path $CloudKey) -and -not (Test-Path $SaKey)) "버전 $v0 → $v1"
    $n = (TrapCount) - $base
    Check "덫에 걸린 연결 0 (막은 주소로 연결 시도 없음)" ($n -eq 0) ((Get-Content "$O\trap.txt" -ErrorAction SilentlyContinue | Select-Object -Skip $base) -join " | ")
    Finish
}

# 1. 조용한 설치
$p = Start-Process "$T\setup.exe" -ArgumentList "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG=`"$O\setup1.log`"" -Wait -PassThru
Check "조용한 설치 (코드 0)" ($p.ExitCode -eq 0) "코드 $($p.ExitCode)"
$need = @("edition.json", "manifest.sig", "manifest.json", "firebase\web\index.html", "firebase\web\fonts", "firebase\agent\local_web.py",
          "firebase\agent\local_server.py", "rpa_settings.py", "ERPia_RPA.exe", "Prepare_RPA.exe", "Prepare_Observer.exe", "python\pythonw.exe", "lib\.unpacked")
$lack = @($need | Where-Object { -not (Test-Path "$App\$_") })
$guardApp = @(Get-ChildItem "$App\app" -Filter "license_check*.pyd" -File -ErrorAction SilentlyContinue)
$guardRoot = @(Get-ChildItem $App -Filter "license_check*.pyd" -File -ErrorAction SilentlyContinue)
Check "있어야 할 파일 (edition.json·manifest.sig·웹 파일·글꼴·local_web, app\·뿌리의 license_check 조각)" (($lack.Count -eq 0) -and ($guardApp.Count -eq 1) -and ($guardRoot.Count -eq 1)) "없음: $($lack -join ', ') / 조각 app $($guardApp.Count) 뿌리 $($guardRoot.Count)"
$banned = @("update_helper.py", "firebase-config.js", "data-firebase.js", "license_check.py", "클라우드_안내.txt", "배포안내.txt", "배포안내_스탠드얼론.txt", "PC번호_확인.bat")
$bad = @(Get-ChildItem $App -Recurse -File -Force -ErrorAction SilentlyContinue | Where-Object { ($_.FullName -notlike "$App\python\*") -and (($_.Name -like "ai_rescue*") -or ($banned -contains $_.Name) -or ($_.Name -like "*signing_key*") -or ($_.Name -like "*.testkey.txt")) } | ForEach-Object { $_.FullName.Substring($App.Length) })
if (Test-Path "$App\lib\anthropic") { $bad += "\lib\anthropic" }
Check "없어야 할 파일 (ai_rescue·lib\anthropic·update_helper.py·firebase-config.js·data-firebase.js·license_check.py·안내 문서·열쇠)" ($bad.Count -eq 0) ($bad -join ", ")
$ed = Get-Content "$App\edition.json" -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json
Check "edition.json = standalone · 시험용 빌드" (($ed.edition -eq "standalone") -and ($ed.test_build -eq $true)) "$ed"
$ci = PyOut "import rpa_status as st`nr = st.check_install(r'$App')`n_out.write(str(r['state']) + ' ' + str(r.get('version')))" "ci1"
Check "설치 점검 ok" ("$ci" -like "ok *") "$ci"
$un = Get-ItemProperty $SaKey -ErrorAction SilentlyContinue
$wow = @(Get-ChildItem "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall" -ErrorAction SilentlyContinue | Where-Object { $_.PSChildName -like "{7D2E9A61*" })
Check "앱 및 기능: '오토파일럿 스탠드얼론 (시험용)' (스탠드얼론 AppId, 64비트 보기의 제거 키 - WOW6432Node 아님)" (($null -ne $un) -and ($un.DisplayName -eq "오토파일럿 스탠드얼론 (시험용)") -and ($wow.Count -eq 0)) "이름 $($un.DisplayName) / WOW64 $($wow.Count)"
Check "일반 버전 제거 키는 없다" (-not (Test-Path $CloudKey))
$url = Select-String -Path "$SM\오토파일럿 대시보드.url" -Pattern "^URL=(.*)$" -ErrorAction SilentlyContinue | ForEach-Object { $_.Matches[0].Groups[1].Value }
Check "대시보드 바로 가기 주소 http://127.0.0.1:8781/ · 설정 바로 가기" (($url -eq "http://127.0.0.1:8781/") -and (Test-Path "$SM\오토파일럿 설정.lnk")) "url=$url"
Check "설정 폴더 config·data·standalone" ((Test-Path "$PD\config") -and (Test-Path "$PD\data") -and (Test-Path $KD))
schtasks /Query /TN $Task *> $null
Check "라이선스·설정 전에는 작업이 없고 로컬 서버도 안 뜬다" (($LASTEXITCODE -ne 0) -and -not (Listening 8781))

# 2. 라이선스 없음 → 있음 (다른 PC 것 → 맞는 것). 사용자 설정은 먼저 (exe 점검이 설정을 읽는다)
$c = PyOut "import rpa_status as st`ndata = st.read_user_config(os.path.join(r'$App', 'RPA_UserConfig.template.json'))`nst.write_user_config(data, st.user_config_path())`n_out.write('cfg ok')" "cfg"
Check "사용자 설정을 썼다 (빈 틀)" ("$c" -eq "cfg ok") "$c"
foreach ($e in @(@("ERPia_RPA.exe", "=== 점검 끝"), @("Prepare_RPA.exe", "쓸 수 있는 Action"), @("Prepare_Observer.exe", "옵저버 점검 끝"))) {
    $r = RunExe $e[0] "--check" "nolic_$($e[0])"
    Check "라이선스 없음: $($e[0]) --check 가 끝까지 가고 '라이선스: 라이선스 파일이 없습니다'" ($r.Text.Contains($e[1]) -and $r.Text.Contains("라이선스: 라이선스 파일이 없습니다")) (Tail $r.Text)
}
foreach ($exe in "ERPia_RPA.exe", "Prepare_RPA.exe") {
    $r = RunExe $exe "" "nolic_run_$exe" 120
    $prog = if ($exe -eq "ERPia_RPA.exe") { "routine" } else { "prepare" }
    $stt = StatusOf $prog
    Check "라이선스 없음: $exe 는 켜지지 않는다 (종료 코드 2, 현황 stopped·사유 '라이선스 파일이 없습니다')" (($r.Code -eq 2) -and ($stt -match '"stopped"') -and ($stt -match "라이선스 파일이 없습니다")) "코드 $($r.Code) / $(Tail $stt 200)"
}
Copy-Item "$T\license_other.json" "$PD\license.json" -Force
$r = RunExe "Prepare_RPA.exe" "" "otherlic_run" 120
$stt = StatusOf "prepare"
Check "다른 PC 의 라이선스: Prepare_RPA.exe 2 · '이 PC 의 라이선스가 아닙니다'" (($r.Code -eq 2) -and ($stt -match "이 PC 의 라이선스가 아닙니다")) "코드 $($r.Code) / $(Tail $stt 200)"
$r = RunExe "ERPia_RPA.exe" "--check" "otherlic_check"
Check "다른 PC 의 라이선스: ERPia_RPA.exe --check 에 '이 PC 의 라이선스가 아닙니다'" ($r.Text.Contains("이 PC 의 라이선스가 아닙니다")) (Tail $r.Text)
Copy-Item "$T\license.json" "$PD\license.json" -Force
$r = RunExe "ERPia_RPA.exe" "--check" "lic_check"
Check "맞는 라이선스: --check 에 '라이선스: 확인됨 (샌드박스상사, PC 번호 $want)'" ($r.Text.Contains("라이선스: 확인됨 (샌드박스상사, PC 번호 $want)")) (Tail $r.Text)
# 가정 확인: 조각(.pyd)에서 불린 가드 모듈을 '컴파일됨' 으로 본다 (__compiled__ 또는 확장 모듈 자리) - 틀리면 설치본이 모두 막힌다
$g = PyOut "import site`nsys.path.insert(0, os.path.join(r'$App', 'app'))`nsite.addsitedir(os.path.join(r'$App', 'lib'))`nimport ap_guard, license_check, rpa_status, update_sign, edition`n_out.write(repr([ap_guard.startup_problem(), ap_guard.loose_sources(r'$App'), [ap_guard._compiled(sys.modules[n]) for n in ap_guard.GUARD_PIECES], '__compiled__' in vars(ap_guard), rpa_status.shipped(), os.path.basename(ap_guard.__file__)]))" "guard"
Check "가드 조각이 스스로를 컴파일된 것으로 본다 (loose 없음, 다섯 모두 compiled)" ("$g" -match "^\[[^\[]*, \[\], \[True, True, True, True, True\]") "$g"
Note "가드 판정 (내장 python.exe 로 부름 - startup_problem·shipped 는 exe 와 다를 수 있다): $g"
$r = RunExe "Prepare_RPA.exe" "" "lic_run" 120
Check "맞는 라이선스·고치지 않은 설치: Prepare_RPA.exe 가 가드를 지나 도움말로 끝난다 (종료 코드 0)" ($r.Code -eq 0) "코드 $($r.Code) / $(Tail $r.Text)"

# 2-1. edition.json 을 지워도 일반 버전으로 넘어가지 않는다 (검토 2026-11-23 I-1 - 남은 표시: 빈 server_info 조각·manifest.sig·목록)
$edPath = "$App\edition.json"; $edBytes = [IO.File]::ReadAllBytes($edPath)
Remove-Item $edPath -Force
Remove-Item "$PD\license.json" -Force
foreach ($exe in "ERPia_RPA.exe", "Prepare_RPA.exe") {
    $r = RunExe $exe "" "noed_nolic_$exe" 120
    $stt = StatusOf $(if ($exe -eq "ERPia_RPA.exe") { "routine" } else { "prepare" })
    Check "edition.json 지움 + 라이선스 없음: $exe 2 · '라이선스 파일이 없습니다' (일반 버전으로 넘어가지 않는다)" (($r.Code -eq 2) -and ($stt -match "라이선스 파일이 없습니다")) "코드 $($r.Code) / $(Tail $stt 200)"
}
$r = RunExe "Prepare_Observer.exe" "--check" "noed_nolic_obs"
Check "edition.json 지움 + 라이선스 없음: Prepare_Observer.exe --check 에 '라이선스: 라이선스 파일이 없습니다'" ($r.Text.Contains("라이선스: 라이선스 파일이 없습니다")) (Tail $r.Text)
Copy-Item "$T\license.json" "$PD\license.json" -Force
foreach ($exe in "ERPia_RPA.exe", "Prepare_RPA.exe") {
    $r = RunExe $exe "" "noed_$exe" 120
    $stt = StatusOf $(if ($exe -eq "ERPia_RPA.exe") { "routine" } else { "prepare" })
    Check "edition.json 지움 (라이선스 맞음): $exe 2 · 현황에 'edition.json'" (($r.Code -eq 2) -and ($stt -match "edition\.json")) "코드 $($r.Code) / $(Tail $stt 200)"
}
$r = RunExe "Prepare_Observer.exe" "--check" "noed_obs"
Check "edition.json 지움: Prepare_Observer.exe --check 에 '라이선스: 확인됨' (여전히 스탠드얼론으로 본다)" ($r.Text.Contains("라이선스: 확인됨")) (Tail $r.Text)
foreach ($m in "run_routine", "web_runner", "rpa_observer") {
    $pf = "$X\imp_$m.py"
    $src = "import sys, os, site`nsys.path.insert(0, os.path.join(r'$App', 'app'))`nsite.addsitedir(os.path.join(r'$App', 'lib'))`nimport $m`nprint('imported')`n"
    [IO.File]::WriteAllText($pf, $src, (New-Object Text.UTF8Encoding($false)))
    $p = Start-Process $Py -ArgumentList "-E -s `"$pf`"" -WorkingDirectory $X -PassThru -WindowStyle Hidden -RedirectStandardOutput "$X\imp_$m.out.txt" -RedirectStandardError "$X\imp_$m.err.txt"
    $null = $p.Handle
    $ended = $p.WaitForExit(120000)
    if (-not $ended) { taskkill /F /T /PID $p.Id 2>&1 | Out-Null }
    $ie = (Get-Content "$X\imp_$m.err.txt" -Raw -ErrorAction SilentlyContinue) + (Get-Content "$X\imp_$m.out.txt" -Raw -ErrorAction SilentlyContinue)
    Check "edition.json 지움: python.exe 로 $m 를 직접 불러오면 2 · stderr 에 'edition.json' (import_guard)" ($ended -and ($p.ExitCode -eq 2) -and ("$ie" -match "edition\.json")) "코드 $(if ($ended) { $p.ExitCode } else { '시간 넘김' }) / $(Tail $ie 200)"
}
[IO.File]::WriteAllBytes($edPath, $edBytes)
$r = RunExe "Prepare_RPA.exe" "" "ed_back" 120
Check "edition.json 을 되돌리면 Prepare_RPA.exe 가 다시 0" ($r.Code -eq 0) "코드 $($r.Code) / $(Tail $r.Text)"

# 3. 설정 (창 없이): 관리자 계정 → --after-install --no-window → 작업 등록, 감독이 로컬 서버·에이전트를 띄운다
$a = PyOut "import rpa_settings as rs`np = rs.default_paths()`nuid = rs.create_admin(p, '$Admin', '$Pw1', '$Pw1')`n_out.write(' '.join(str(x) for x in (uid, rs.admin_exists(p), rs.license_state(p)['ok'], rs.configured(p))))" "admin"
Check "관리자 계정을 만들었다 · 라이선스 맞음 · 설정 끝 (configured)" ("$a" -eq "$Admin True True True") "$a"
$p = Start-Process $Py -ArgumentList "-E -s `"$App\rpa_settings.py`" --after-install --no-window" -Wait -PassThru -WindowStyle Hidden
Check "--after-install --no-window (코드 0)" ($p.ExitCode -eq 0) "코드 $($p.ExitCode)"
schtasks /Query /TN $Task *> $null
Check "작업 등록" ($LASTEXITCODE -eq 0)
$up = WaitListen 8781 120
Check "로컬 서버가 127.0.0.1:8781 을 연다 (감독 아래)" $up
$srv = @(ServerProcs)
if ($srv.Count -eq 0) { Get-CimInstance Win32_Process | ForEach-Object { "$($_.ProcessId) $($_.Name) $($_.CommandLine)" } | Out-File "$O\procs_no_server.txt" -Encoding UTF8 }
Check "로컬 서버 프로세스가 떠 있다 (local_server.py)" ($srv.Count -ge 1) "$($srv.Count)개 - procs_no_server.txt"
for ($i = 0; ($i -lt 60) -and -not (Test-Path "$KD\agent.key"); $i++) { Start-Sleep 1 }
Start-Sleep 10                                     # 에이전트가 붙어 첫 현황을 올릴 때까지
$alog = if (Test-Path "$PD\data\에이전트_기록.txt") { Get-Content "$PD\data\에이전트_기록.txt" -Raw -Encoding UTF8 } else { "" }
Check "에이전트 기록에 Firebase 로그인 시도가 없다 (googleapis·identitytoolkit·securetoken·firebaseio 글자 없음)" (($alog.Length -gt 0) -and ($alog -notmatch "googleapis|identitytoolkit|securetoken|firebaseio|firebasedatabase")) "기록 $($alog.Length)자"
# 휴대폰 창구 (계획 ④): 짝지은 휴대폰이 0대면 사내망 포트(8782)·방화벽 규칙이 없다
netsh advfirewall firewall show rule name="AUTOPILOT Phone OTP" *> $null
$rule = $LASTEXITCODE -eq 0
Check "휴대폰 0대: 8782 포트가 열려 있지 않고 방화벽 규칙도 없다" ((-not (Listening 8782)) -and (-not $rule)) "듣기 $(Listening 8782) / 규칙 $rule"

# 4. 열쇠·계정·라이선스 파일 권한 - 관리자·SYSTEM 뿐
$acls = @()
foreach ($f in "$KD\agent.key", "$KD\relay.key", "$KD\accounts.json", "$PD\license.json") {
    if (-not (Test-Path $f)) { $acls += "$(Split-Path $f -Leaf)=없음"; continue }
    $sids = AclSids $f
    if (@($sids | Where-Object { $_ -notin "S-1-5-32-544", "S-1-5-18" }).Count -gt 0) { $acls += "$(Split-Path $f -Leaf)=$($sids -join ',')" }
}
Check "agent.key·relay.key·accounts.json·license.json 의 권한은 관리자·SYSTEM 뿐" ($acls.Count -eq 0) ($acls -join " / ")

# 5. 업체 웹 창구 끝에서 끝까지 (127.0.0.1 만)
& $Py -I "$T\check_standalone.py" full $Admin $Pw1 $Pw2 "$O\check_full.txt" 2>&1 | Out-File "$X\check_full.err.txt"
foreach ($line in @(Get-Content "$O\check_full.txt" -Encoding UTF8 -ErrorAction SilentlyContinue)) {
    if ($line.StartsWith("통과  ")) { Check $line.Substring(4) $true }
    elseif ($line.StartsWith("실패  ")) { $script:fails++; $results.Add($line); Save }
    elseif ($line.StartsWith("참고  ")) { $results.Add($line); Save }
}
if (-not (Test-Path "$O\check_full.txt")) { Check "check_standalone full 결과가 있다" $false (Get-Content "$X\check_full.err.txt" -Raw) }
$sch = PyOut "import rpa_status as st`ns = st.read_settings()['schedule']`n_out.write(str(s.get('enabled')) + ' ' + ','.join(x.get('at', '') for x in s.get('slots') or []))" "sch1"
Check "자동 실행 설정이 PC 에 저장됐다 (03:17)" ("$sch" -eq "True 03:17") "$sch"
Note "PROCESS 현황: $(Tail (StatusOf 'routine') 300)"
$left = @(Get-CimInstance Win32_Process -Filter "Name='ERPia_RPA.exe'")
if ($left.Count) { Note "launch 뒤 남은 ERPia_RPA.exe $($left.Count)개 - 끈다"; $left | ForEach-Object { taskkill /F /T /PID $_.ProcessId 2>&1 | Out-Null } }

# 6. 변조: 깔린 .py 한 바이트 → exe 가 2. app\ 에 .py 를 끼워도 2
$dashPy = "$App\rpa_dashboard.py"; $orig = [IO.File]::ReadAllBytes($dashPy)
[IO.File]::AppendAllText($dashPy, "#")
foreach ($exe in "Prepare_RPA.exe", "ERPia_RPA.exe") {
    $r = RunExe $exe "" "tamper_$exe" 120
    $stt = StatusOf $(if ($exe -eq "ERPia_RPA.exe") { "routine" } else { "prepare" })
    Check "변조(rpa_dashboard.py 한 바이트): $exe 가 2 · '프로그램 파일이 설치된 버전과 달라' · '같은 버전 설치 파일로 다시 설치'" (($r.Code -eq 2) -and ($stt -match "프로그램 파일이 설치된 버전과 달라") -and ($stt -match "같은 버전 설치 파일로 다시 설치")) "코드 $($r.Code) / $(Tail $stt 250)"
}
[IO.File]::WriteAllBytes($dashPy, $orig)
Set-Content "$App\app\license_check.py" "LICENSE_PUBLIC_KEY_HEX = ''" -Encoding ASCII
$r = RunExe "Prepare_RPA.exe" "" "loose_run" 120
$stt = StatusOf "prepare"
Check "app\license_check.py 를 끼우면 Prepare_RPA.exe 가 2 · 'app\license_check.py'" (($r.Code -eq 2) -and ($stt -match [regex]::Escape("app\\license_check.py"))) "코드 $($r.Code) / $(Tail $stt 250)"
[IO.File]::AppendAllText($dashPy, "#")              # 둘 다 남긴 채 덮어 설치 - 같은 버전 설치 파일이 풀어야 한다

# 7. 덮어 설치 (같은 설치 파일)
$p = Start-Process "$T\setup.exe" -ArgumentList "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG=`"$O\setup2.log`"" -Wait -PassThru
Check "덮어 설치 (코드 0)" ($p.ExitCode -eq 0) "코드 $($p.ExitCode)"
$l2 = Get-Content "$O\setup2.log" -Raw -ErrorAction SilentlyContinue
Check "파일을 덮기 전에 --stop (0) - 로컬 서버까지 멈춤 (남으면 6)" ($l2 -match "rpa_settings --stop -> 0")
$ci = PyOut "import rpa_status as st`nr = st.check_install(r'$App')`n_out.write(str(r['state']) + ' ' + str(r.get('version')))" "ci2"
Check "덮어 설치 뒤 변조가 풀렸다 (점검 ok, app\license_check.py 없음, app\_start.py 있음)" (("$ci" -like "ok *") -and -not (Test-Path "$App\app\license_check.py") -and (Test-Path "$App\app\_start.py")) "$ci"
$r = RunExe "ERPia_RPA.exe" "--check" "after_check"
Check "덮어 설치 뒤 ERPia_RPA.exe --check: 라이선스 확인됨" ($r.Text.Contains("라이선스: 확인됨")) (Tail $r.Text)
$up = WaitListen 8781 120
Check "덮어 설치 뒤 로컬 서버가 다시 뜬다" $up
Start-Sleep 10
& $Py -I "$T\check_standalone.py" after $Admin $Pw1 $Pw2 "$O\check_after.txt" 2>&1 | Out-File "$X\check_after.err.txt"
foreach ($line in @(Get-Content "$O\check_after.txt" -Encoding UTF8 -ErrorAction SilentlyContinue)) {
    if ($line.StartsWith("통과  ")) { Check $line.Substring(4) $true }
    elseif ($line.StartsWith("실패  ")) { $script:fails++; $results.Add($line); Save }
    elseif ($line.StartsWith("참고  ")) { $results.Add($line); Save }
}
if (-not (Test-Path "$O\check_after.txt")) { Check "check_standalone after 결과가 있다" $false (Get-Content "$X\check_after.err.txt" -Raw) }
$sch = PyOut "import rpa_status as st`ns = st.read_settings()['schedule']`n_out.write(str(s.get('enabled')) + ' ' + ','.join(x.get('at', '') for x in s.get('slots') or []))" "sch2"
$lic = PyOut "import rpa_settings as rs`n_out.write(str(rs.license_state(rs.default_paths())['ok']))" "lic2"
Check "덮어 설치 뒤 라이선스·자동 실행 설정이 남아 있다" (("$lic" -eq "True") -and ("$sch" -eq "True 03:17")) "라이선스 $lic / 자동 실행 $sch"
$acls = @()
foreach ($f in "$KD\agent.key", "$KD\relay.key", "$KD\accounts.json", "$PD\license.json") {
    if (-not (Test-Path $f)) { $acls += "$(Split-Path $f -Leaf)=없음"; continue }
    $sids = AclSids $f
    if (@($sids | Where-Object { $_ -notin "S-1-5-32-544", "S-1-5-18" }).Count -gt 0) { $acls += "$(Split-Path $f -Leaf)=$($sids -join ',')" }
}
Check "덮어 설치 뒤에도 열쇠·계정·라이선스 권한은 관리자·SYSTEM 뿐 (권한 다시 잠근 뒤에도 서버가 열쇠를 읽어 떴다)" (($acls.Count -eq 0) -and $up) ($acls -join " / ")

# 8. --cloud-setup: 스탠드얼론이 깔린 PC 에서 일반 설치 파일은 시작 전에 멈춘다
if (Test-Path "$T\cloud_setup.exe") {
    $p = Start-Process "$T\cloud_setup.exe" -ArgumentList "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG=`"$O\setup_cloud.log`"" -Wait -PassThru
    Check "스탠드얼론이 깔린 PC 에서 일반 설치 파일은 멈춘다 (코드 1)" ($p.ExitCode -eq 1) "코드 $($p.ExitCode)"
    Check "스탠드얼론 설치는 그대로 (edition.json, 로컬 서버, 스탠드얼론 등록, 일반 등록 없음)" ((Test-Path "$App\edition.json") -and (Listening 8781) -and (Test-Path $SaKey) -and -not (Test-Path $CloudKey))
}

# 9. 조용한 제거: 프로그램·작업·시작 메뉴는 없어지고 설정·라이선스·계정은 남는다
Start-Process "$App\unins000.exe" -ArgumentList "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART" -Wait
for ($i = 0; ($i -lt 60) -and (Test-Path $App); $i++) { Start-Sleep 1 }
$leftFiles = if (Test-Path $App) { $f = @(Get-ChildItem $App -Recurse -Force -File -ErrorAction SilentlyContinue); "남은 파일 $($f.Count)개: " + (($f | Select-Object -First 12 | ForEach-Object { $_.FullName.Substring($App.Length) }) -join "; ") } else { "" }
Check "제거: 프로그램 폴더가 없다" (-not (Test-Path $App)) $leftFiles
schtasks /Query /TN $Task *> $null
Check "제거: 작업이 없다" ($LASTEXITCODE -ne 0)
Check "제거: 시작 메뉴가 없다" (-not (Test-Path $SM))
Check "제거: 로컬 서버가 멈췄다 (8781 닫힘)" (-not (Listening 8781))
Check "제거: 설정·라이선스·웹 계정은 남는다" ((Test-Path "$PD\license.json") -and (Test-Path "$KD\accounts.json") -and (Test-Path "$PD\config"))
Check "제거: 스탠드얼론 제거 키가 없다" (-not (Test-Path $SaKey))

# 10. 덫
$n = (TrapCount) - $base
Check "덫에 걸린 연결 0 (막은 주소로 연결 시도 없음 - 설치부터 제거까지)" ($n -eq 0) ((Get-Content "$O\trap.txt" -ErrorAction SilentlyContinue | Select-Object -Skip $base) -join " | ")
Finish
