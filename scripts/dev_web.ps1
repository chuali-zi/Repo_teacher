# Repo Tutor - start frontend only
# Usage: .\scripts\dev_web.ps1

$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSScriptRoot
if (-not $PSScriptRoot) {
    $Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
}

$WebDir = Join-Path $Root 'web'
$IndexFile = Join-Path $WebDir 'index.html'

if (-not (Test-Path $IndexFile)) {
    Write-Host '[ERROR] web\index.html not found' -ForegroundColor Red
    Write-Host "Checked: $IndexFile"
    Read-Host 'Press Enter to exit'
    exit 1
}

Write-Host ''
Write-Host '  =============================================' -ForegroundColor DarkYellow
Write-Host '    Repo Tutor - Frontend' -ForegroundColor Yellow
Write-Host "    http://localhost:5180" -ForegroundColor Cyan
Write-Host "    Serving: $WebDir" -ForegroundColor DarkGray
Write-Host '  =============================================' -ForegroundColor DarkYellow
Write-Host ''
Write-Host '  Note: backend must be started separately (scripts\dev_backend.cmd)' -ForegroundColor DarkGray
Write-Host '  Press Ctrl+C to stop' -ForegroundColor DarkGray
Write-Host ''

Start-Process 'http://localhost:5180'

Push-Location $WebDir
try {
    python -m http.server 5180 --bind 127.0.0.1
} finally {
    Pop-Location
}
