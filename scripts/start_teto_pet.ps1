param()

$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = Split-Path -Parent $ScriptDir
$PythonScript = Join-Path $ScriptDir 'start_teto_pet.py'
$ImageDir = Join-Path $RootDir 'web_v4\images'

if (-not (Test-Path -LiteralPath $PythonScript)) {
  Write-Host "[ERROR] Start script not found: $PythonScript" -ForegroundColor Red
  Read-Host 'Press Enter to exit'
  exit 1
}

if (-not (Test-Path -LiteralPath $ImageDir)) {
  Write-Host "[ERROR] Image folder not found: $ImageDir" -ForegroundColor Red
  Read-Host 'Press Enter to exit'
  exit 1
}

$PythonExe = Get-Command python -ErrorAction SilentlyContinue
if (-not $PythonExe) {
  Write-Host '[ERROR] Python not found in PATH.' -ForegroundColor Red
  Read-Host 'Press Enter to exit'
  exit 1
}

Write-Host ''
Write-Host '  =============================================' -ForegroundColor DarkYellow
Write-Host '    Repo Tutor - Teto Desktop Pet' -ForegroundColor Yellow
Write-Host '    double click / right click to exit' -ForegroundColor DarkGray
Write-Host '    starting...' -ForegroundColor Cyan
Write-Host '  =============================================' -ForegroundColor DarkYellow
Write-Host ''

& $PythonExe.Path $PythonScript
