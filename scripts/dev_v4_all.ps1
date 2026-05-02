# Repo Tutor v4 - start new_kernel backend + web_v4 static frontend
# Usage: .\scripts\dev_v4_all.ps1

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
    Read-Host 'Press Enter to exit'
    exit 1
}

$Root = Split-Path -Parent $PSScriptRoot
if (-not $PSScriptRoot) {
    $Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
}

$WebDir       = Join-Path $Root 'web_v4'
$IndexFile    = Join-Path $WebDir 'RepoTutor.html'
$KernelInit   = Join-Path $Root 'new_kernel\__init__.py'
$LlmConfig    = Join-Path $Root 'llm_config.json'
$BackendPort  = 8000
$FrontendPort = 5184

if (-not (Test-Path $IndexFile)) {
    Write-Host '[ERROR] web_v4\RepoTutor.html not found.' -ForegroundColor Red
    Write-Host "Checked: $IndexFile"
    Read-Host 'Press Enter to exit'
    exit 1
}

if (-not (Test-Path $KernelInit)) {
    Write-Host '[ERROR] new_kernel package not found.' -ForegroundColor Red
    Write-Host "Checked: $KernelInit"
    Read-Host 'Press Enter to exit'
    exit 1
}

if (-not (Test-Path $LlmConfig)) {
    Write-Host '[WARN] llm_config.json not found at project root.' -ForegroundColor Yellow
    Write-Host "Expected: $LlmConfig" -ForegroundColor DarkGray
    Write-Host 'Backend will boot but LLM-driven turns will be disabled.' -ForegroundColor DarkGray
    Write-Host ''
}

Write-Host ''
Write-Host '  =============================================' -ForegroundColor DarkYellow
Write-Host '    Repo Tutor v4 - new_kernel + web_v4' -ForegroundColor Yellow
Write-Host "    Backend:  http://127.0.0.1:$BackendPort" -ForegroundColor Cyan
Write-Host "    Frontend: http://127.0.0.1:$FrontendPort/RepoTutor.html" -ForegroundColor Cyan
Write-Host "    Serving:  $WebDir" -ForegroundColor DarkGray
Write-Host "    Config:   $LlmConfig" -ForegroundColor DarkGray
Write-Host '  =============================================' -ForegroundColor DarkYellow
Write-Host ''

Assert-PortFree -Port $BackendPort  -Label 'the backend endpoint'
Assert-PortFree -Port $FrontendPort -Label 'the frontend endpoint'

$backendCmd = "set PYTHONPATH=$Root&& cd /d `"$Root`" && python -m uvicorn new_kernel.api.app:app --host 127.0.0.1 --port $BackendPort"
Start-Process cmd -ArgumentList '/k', $backendCmd -WindowStyle Normal

Start-Sleep -Seconds 2

$frontendCmd = "cd /d `"$WebDir`" && python -m http.server $FrontendPort --bind 127.0.0.1"
Start-Process cmd -ArgumentList '/k', $frontendCmd -WindowStyle Normal

Start-Sleep -Seconds 1

Start-Process "http://127.0.0.1:$FrontendPort/RepoTutor.html"

Write-Host ''
Write-Host '  Both servers started in separate windows.' -ForegroundColor Green
Write-Host '  Close those windows to stop.' -ForegroundColor DarkGray
Write-Host ''
Read-Host 'Press Enter to exit'
