# 윈도우 샌드박스 안에서 스탠드얼론 설치 파일을 사내 서버(NT)에 등록해 본다 (사내 서버 ⑤ Task 8 - tools/sandbox_test.py --standalone --lan-enroll 이 C:\test 로 넣는다).
# 1) 조용한 설치 2) C:\test\enroll.txt 의 등록 글로 rpa_settings.install_link → rs.save 3) 에이전트가 사내 서버에 붙는지 (로컬 서버는 띄우지 않는다)
# 4) out\ready.txt 를 쓰고, C:\test\end.txt 가 생길 때까지 5초마다 out\status.json (멈춤 까닭·연결 파일·기록 끝 줄) - 업체 웹에서 실행·사용 중지·지우기를 해 본다
# 5) end.txt 가 생기면 마지막 결과를 쓰고 끈다. 등록 글·열쇠는 결과에 싣지 않는다. 이 파일은 BOM 있는 UTF-8 (PowerShell 5.1).
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
$App = "C:\Program Files\AFTER MARKET\RPA Standalone"
$PD = "C:\ProgramData\AFTER MARKET\RPA Standalone"
$KD = "$PD\standalone"
$Py = "$App\python\python.exe"
$Link = "$KD\server_link.json"
$Stop = "$PD\data\에이전트_멈춤.json"
$Log = "$PD\data\에이전트_기록.txt"
$SM = "C:\ProgramData\Microsoft\Windows\Start Menu\Programs\오토파일럿 스탠드얼론\오토파일럿 대시보드.url"
$X = "$O\py"
New-Item -ItemType Directory -Force $X | Out-Null
# 내장 파이썬으로 짧은 코드 - 결과를 UTF-8 파일로 받아 읽는다 (sandbox_inner_standalone.ps1 의 PyOut 과 같다)
function PyOut($code, $tag) {
    $f = "$X\py_$tag.txt"
    Remove-Item $f -ErrorAction SilentlyContinue
    $full = "import sys, os, json`nsys.path[:0] = [r'$App', os.path.join(r'$App', 'firebase', 'agent')]`n_out = open(r'$f', 'w', encoding='utf-8')`ntry:`n" +
            (($code -split "`n" | ForEach-Object { "    $_" }) -join "`n") + "`nexcept Exception as _e:`n    _out.write('오류 ' + type(_e).__name__ + ': ' + str(_e))`n_out.close()`n"
    [IO.File]::WriteAllText("$X\py_$tag.py", $full, (New-Object Text.UTF8Encoding($false)))
    & $Py "$X\py_$tag.py" 2>&1 | Out-File "$X\py_$tag.err.txt"
    if (Test-Path $f) { (Get-Content $f -Raw -Encoding UTF8) } else { "(출력 없음) " + (Get-Content "$X\py_$tag.err.txt" -Raw) }
}
function Listening($port) { $null -ne (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) }
function LogTail($n = 12) { if (Test-Path $Log) { @(Get-Content $Log -Encoding UTF8 -Tail $n) } else { @() } }

# 1) 설치
$p = Start-Process "$T\setup.exe" -ArgumentList "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG=`"$O\setup.log`"" -Wait -PassThru
Check "조용한 설치 종료 0" ($p.ExitCode -eq 0) "코드 $($p.ExitCode)"
Check "내장 파이썬이 있다" (Test-Path $Py)

# 2) 사내 서버 등록 → 저장 (설정 창의 창 없는 함수 - 등록 글은 파일로만)
$got = PyOut ("import rpa_settings as rs`np = rs.default_paths()`ntext = open(r'$T\enroll.txt', encoding='utf-8-sig').read()`n" +
              "got = rs.install_link(text, p)`n" +
              "form = {k: '' for k in rs.FORM_KEYS}`nform.update(admin_code='AM001', erp_id='rpa', erp_pw='Sbx-Erp-1234!', print_mode=rs.PRINT_MANUAL)`n" +
              "done = rs.save(form, p, standalone=True)`n" +
              "_out.write(json.dumps({'pc_id': got['pc_id'], 'server': got['server'], 'done': got['done'] + done}, ensure_ascii=False))") "enroll"
Remove-Item "$T\enroll.txt" -Force -ErrorAction SilentlyContinue      # 한 번짜리 글 - 쓰고 나면 지운다
$info = $null
try { $info = $got | ConvertFrom-Json } catch { }
Check "install_link·save 성공 (사내 서버에 등록)" ($null -ne $info -and "$($info.pc_id)" -match '^pc_\d+$') (("$got" -replace "\s+", " "))
if ($info) { Note "PC 번호 $($info.pc_id), 서버 $($info.server)"; foreach ($d in $info.done) { Note "$d" } }
Check "연결 파일이 생겼다 (standalone\server_link.json)" (Test-Path $Link)
$mode = PyOut "import license_check`n_out.write(license_check.mode())" "mode"
Check "연결 방식 = lan" ("$mode".Trim() -eq "lan") "$mode"
if (Test-Path $SM) { Note ("대시보드 바로 가기: " + ((Get-Content $SM | Where-Object { $_ -like "URL=*" }) -join " ")) }

# 3) 에이전트가 사내 서버에 붙는다 (90초), 로컬 서버(8781)는 듣지 않는다
$ok = $false
for ($i = 0; $i -lt 45; $i++) {
    if ((LogTail 40) -match "에이전트 시작.*PC=pc_") { $ok = $true; break }
    Start-Sleep -Seconds 2
}
Check "에이전트 시작 (PC=pc_..)" $ok ((LogTail 6) -join " | ")
Check "멈춤 파일이 없다" (-not (Test-Path $Stop)) "$(Get-Content $Stop -Raw -ErrorAction SilentlyContinue)"
Check "로컬 서버(8781)가 듣지 않는다 (감독이 띄우지 않음)" (-not (Listening 8781))
$results.Add("첫 확인 끝 - 실패 $script:fails")
Save
"ready" | Set-Content "$O\ready.txt"

# 4) 사람이 업체 웹에서 실행·사용 중지·지우기를 해 보는 동안 상태를 적는다
while (-not (Test-Path "$T\end.txt")) {
    $st = [ordered]@{
        at = (Get-Date).ToString("HH:mm:ss")
        link = (Test-Path $Link)
        stop = $(if (Test-Path $Stop) { Get-Content $Stop -Raw -Encoding UTF8 } else { $null })
        log = (LogTail 10)
    }
    ($st | ConvertTo-Json -Depth 3) | Set-Content "$O\status.json" -Encoding UTF8
    Start-Sleep -Seconds 5
}

# 5) 끝
Copy-Item $Log "$O\agent_log.txt" -ErrorAction SilentlyContinue
Copy-Item "$PD\data\에이전트_오류.txt" "$O\agent_err.txt" -ErrorAction SilentlyContinue
$results.Add("실패: $script:fails")
Save
"done" | Set-Content "$T\done.txt"
shutdown /s /t 5
