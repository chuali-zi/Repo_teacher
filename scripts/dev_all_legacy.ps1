# Repo Tutor - start backend + legacy frontend
# Usage: .\scripts\dev_all_legacy.ps1

$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSScriptRoot
if (-not $PSScriptRoot) {
    $Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
}

$WebDir  = Join-Path $Root 'web'
$IndexFile = Join-Path $WebDir 'index.html'

if (-not (Test-Path $IndexFile)) {
    Write-Host '[ERROR] web\index.html not found' -ForegroundColor Red
    Write-Host "Checked: $IndexFile"
    Read-Host 'Press Enter to exit'
    exit 1
}

Write-Host ''
Write-Host '  =============================================' -ForegroundColor DarkYellow
Write-Host '    Repo Tutor - Legacy Frontend' -ForegroundColor Yellow
Write-Host "    Backend:  http://localhost:8000" -ForegroundColor Cyan
Write-Host "    Frontend: http://localhost:5180" -ForegroundColor Cyan
Write-Host '  =============================================' -ForegroundColor DarkYellow
Write-Host ''

$backendCmd = "cd /d `"$Root`" && python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000"
Start-Process cmd -ArgumentList '/k', $backendCmd -WindowStyle Normal

Start-Sleep -Seconds 2

$frontendCmd = "cd /d `"$WebDir`" && python -m http.server 5180 --bind 127.0.0.1"
Start-Process cmd -ArgumentList '/k', $frontendCmd -WindowStyle Normal

Start-Sleep -Seconds 1

Start-Process 'http://localhost:5180'

Write-Host ''
Write-Host '  Both servers started in separate windows.' -ForegroundColor Green
Write-Host '  Close those windows to stop.' -ForegroundColor DarkGray
Write-Host ''
Read-Host 'Press Enter to exit'
