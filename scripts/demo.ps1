# Starts Stock Report on a throwaway database with fresh fake data, so you can click through everything.
# It never touches stock.db. The demo accounts use the placeholder password P@ss123 (demo data only).
# Add -Lan to open it from a phone or another computer on your network (it then listens on every address).
# Add -Password 'something' to use a different demo password.
param([switch]$Lan, [string]$Password)
$root = Split-Path $PSScriptRoot -Parent
$dir = Join-Path ([IO.Path]::GetTempPath()) ("stockreport-demo-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
New-Item -ItemType Directory -Path $dir | Out-Null
$env:DATABASE_URL = "sqlite:///" + ($dir -replace "\\", "/") + "/demo.db"
$env:DEMO_PASSWORD = if ($Password) { $Password } else { 'P@ss123' }
Write-Host "Demo database: $dir"
$bind = "127.0.0.1"
# Use the first free port from 8000, so an older server that is still running never blocks a new one.
$port = 8000
while (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) { $port++ }
if ($port -ne 8000) { Write-Host "Port 8000 is already in use by another server, so this one uses port $port." }
Write-Host "Open http://localhost:$port  ·  sam@example.com (staff), acme@acme.example.com, nova@nova.example.com"
if ($Lan) {
    $bind = "0.0.0.0"
    $ip = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } | Select-Object -First 1).IPAddress
    Write-Host "On your network: http://${ip}:$port  (allow Python through the Windows firewall if asked)"
}
Write-Host "Password for all three: $env:DEMO_PASSWORD"
Set-Location $root
& .\.venv\Scripts\python.exe -u -m uvicorn app.main:app --host $bind --port $port
