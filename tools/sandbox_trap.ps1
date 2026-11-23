# 스탠드얼론 샌드박스의 덫 (계획 ③ Task 6) - hosts 로 127.0.0.2 에 돌린 바깥 주소(Firebase·Google·Anthropic·업데이트 사이트)에
# 누가 붙으면 한 줄씩 적는다. 설치 전부터 떠 있어야 해서 (내장 파이썬이 아직 없다) PowerShell 로 듣는다.
# 줄: 시각  포트  붙은 프로세스  받은 글 앞부분(HTTP Host 줄·TLS SNI 이름이 보인다). 이 파일은 BOM 있는 UTF-8.
param([string]$Log = "C:\test\out\trap.txt", [string]$Ip = "127.0.0.2")
$ErrorActionPreference = "Continue"
$listeners = @()
foreach ($port in 80, 443) {
    $l = New-Object System.Net.Sockets.TcpListener ([Net.IPAddress]::Parse($Ip)), $port
    $l.Start()
    $listeners += $l
}
Set-Content "$(Split-Path $Log)\trap_ready.txt" "ready" -Encoding ASCII
while ($true) {
    foreach ($l in $listeners) {
        while ($l.Pending()) {
            $c = $l.AcceptTcpClient()
            $port = $l.LocalEndpoint.Port
            $who = ""
            try {
                $rp = $c.Client.RemoteEndPoint.Port
                $conn = Get-NetTCPConnection -LocalPort $rp -RemotePort $port -ErrorAction SilentlyContinue | Select-Object -First 1
                if ($conn) { $pr = Get-CimInstance Win32_Process -Filter "ProcessId=$($conn.OwningProcess)"; $who = "$($pr.Name) $($pr.CommandLine)" }
            } catch {}
            $text = ""
            try {
                $c.ReceiveTimeout = 1500
                $buf = New-Object byte[] 2048
                $n = $c.GetStream().Read($buf, 0, $buf.Length)
                $text = (([Text.Encoding]::ASCII.GetString($buf, 0, $n)) -replace "[^\x20-\x7E]+", " ").Trim()
                if ($text.Length -gt 300) { $text = $text.Substring(0, 300) }
            } catch {}
            Add-Content $Log "$(Get-Date -Format 'HH:mm:ss.fff')  $port  [$who]  $text" -Encoding UTF8
            $c.Close()
        }
    }
    Start-Sleep -Milliseconds 100
}
