# Repo Tutor - start backend + web_v3 frontend
# Usage: .\scripts\dev_v3.ps1

$ErrorActionPreference = 'Stop'

function Assert-PortFree {
    param (
        [int]$Port,
        [string]$Label
    )

    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $listener) {
        return
    }

    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)" -ErrorAction SilentlyContinue
    $command = if ($process -and $process.CommandLine) { $process.CommandLine } else { "PID $($listener.OwningProcess)" }

    Write-Host "[ERROR] Port $Port is already in use by $Label" -ForegroundColor Red
    Write-Host "Process: $command" -ForegroundColor DarkGray
    Write-Host 'Stop the existing server before retrying.' -ForegroundColor DarkGray
    Read-Host 'Press Enter to exit'
    exit 1
}

$Root = Split-Path -Parent $PSScriptRoot
if (-not $PSScriptRoot) {
    $Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
}

$WebDir    = Join-Path $Root 'web_v3'
$IndexFile = Join-Path $WebDir 'index.html'

if (-not (Test-Path $IndexFile)) {
    Write-Host '[ERROR] web_v3\index.html not found' -ForegroundColor Red
    Write-Host "Checked: $IndexFile"
    Read-Host 'Press Enter to exit'
    exit 1
}

$BackendPort  = 8000
$FrontendPort = 5181

Write-Host ''
Write-Host '  =============================================' -ForegroundColor DarkYellow
Write-Host '    Repo Tutor - Pixel Frontend v3' -ForegroundColor Yellow
Write-Host "    Backend:  http://localhost:$BackendPort" -ForegroundColor Cyan
Write-Host "    Frontend: http://localhost:$FrontendPort" -ForegroundColor Cyan
Write-Host "    Serving:  $WebDir" -ForegroundColor DarkGray
Write-Host '  =============================================' -ForegroundColor DarkYellow
Write-Host ''

Assert-PortFree -Port $BackendPort  -Label 'the backend endpoint'
Assert-PortFree -Port $FrontendPort -Label 'the frontend endpoint'

$backendCmd = "cd /d `"$Root`" && python -m uvicorn backend.main:app --host 127.0.0.1 --port $BackendPort"
Start-Process cmd -ArgumentList '/k', $backendCmd -WindowStyle Normal

Start-Sleep -Seconds 2

$frontendCmd = "cd /d `"$WebDir`" && python -m http.server $FrontendPort --bind 127.0.0.1"
Start-Process cmd -ArgumentList '/k', $frontendCmd -WindowStyle Normal

Start-Sleep -Seconds 1

Start-Process "http://localhost:$FrontendPort"

Write-Host '  Both servers started in separate windows.' -ForegroundColor Green
Write-Host '  Close those windows to stop.' -ForegroundColor DarkGray
Write-Host ''
Read-Host 'Press Enter to exit'
