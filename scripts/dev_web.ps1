# Repo Tutor - start default web_v3 frontend only
# Usage: .\scripts\dev_web.ps1

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
    Write-Host 'Stop the existing server or use the matching legacy/default script.' -ForegroundColor DarkGray
    Read-Host 'Press Enter to exit'
    exit 1
}

$Root = Split-Path -Parent $PSScriptRoot
if (-not $PSScriptRoot) {
    $Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
}

$WebDir = Join-Path $Root 'web_v3'
$IndexFile = Join-Path $WebDir 'index.html'
$FrontendPort = 5181

if (-not (Test-Path $IndexFile)) {
    Write-Host '[ERROR] web_v3\index.html not found' -ForegroundColor Red
    Write-Host "Checked: $IndexFile"
    Read-Host 'Press Enter to exit'
    exit 1
}

Write-Host ''
Write-Host '  =============================================' -ForegroundColor DarkYellow
Write-Host '    Repo Tutor - Pixel Frontend v3' -ForegroundColor Yellow
Write-Host "    http://localhost:$FrontendPort" -ForegroundColor Cyan
Write-Host "    Serving: $WebDir" -ForegroundColor DarkGray
Write-Host '  =============================================' -ForegroundColor DarkYellow
Write-Host ''
Write-Host '  Note: backend must be started separately (scripts\dev_backend.cmd)' -ForegroundColor DarkGray
Write-Host '  Press Ctrl+C to stop' -ForegroundColor DarkGray
Write-Host ''

Assert-PortFree -Port $FrontendPort -Label 'the frontend endpoint'

Start-Process "http://localhost:$FrontendPort"

Push-Location $WebDir
try {
    python -m http.server $FrontendPort --bind 127.0.0.1
} finally {
    Pop-Location
}
