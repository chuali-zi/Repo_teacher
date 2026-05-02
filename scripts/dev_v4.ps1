# Repo Tutor v4 - start new_kernel backend only (uvicorn + FastAPI on port 8000)
# Usage: .\scripts\dev_v4.ps1

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

$KernelInit = Join-Path $Root 'new_kernel\__init__.py'
$LlmConfig  = Join-Path $Root 'llm_config.json'
$BackendPort = 8000

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
Write-Host '    Repo Tutor v4 - new_kernel backend' -ForegroundColor Yellow
Write-Host "    http://127.0.0.1:$BackendPort" -ForegroundColor Cyan
Write-Host "    Module:  new_kernel.api.app:app" -ForegroundColor DarkGray
Write-Host "    Config:  $LlmConfig" -ForegroundColor DarkGray
Write-Host '  =============================================' -ForegroundColor DarkYellow
Write-Host ''
Write-Host '  Press Ctrl+C to stop' -ForegroundColor DarkGray
Write-Host ''

Assert-PortFree -Port $BackendPort -Label 'the backend endpoint'

Push-Location $Root
try {
    $env:PYTHONPATH = $Root
    python -m uvicorn new_kernel.api.app:app --host 127.0.0.1 --port $BackendPort
} finally {
    Pop-Location
}
