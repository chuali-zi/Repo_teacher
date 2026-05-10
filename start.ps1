$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$ScriptsDir = Join-Path $Root 'scripts'

$DevScript = Join-Path $ScriptsDir 'dev_v4_all.ps1'
$PetScript = Join-Path $ScriptsDir 'start_teto_pet.ps1'

function Assert-ScriptExists {
    param (
        [string]$Path,
        [string]$Name
    )

    if (Test-Path -LiteralPath $Path) {
        return
    }

    Write-Host "[ERROR] $Name not found." -ForegroundColor Red
    Write-Host "Checked: $Path" -ForegroundColor DarkGray
    Read-Host 'Press Enter to exit'
    exit 1
}

function Start-RepoScript {
    param (
        [string]$Path,
        [string]$Title
    )

    $command = "& { `$Host.UI.RawUI.WindowTitle = '$Title'; & '$Path' }"

    Start-Process powershell.exe -ArgumentList @(
        '-NoProfile',
        '-ExecutionPolicy',
        'Bypass',
        '-NoExit',
        '-Command',
        $command
    ) -WorkingDirectory $Root -WindowStyle Normal
}

Assert-ScriptExists -Path $DevScript -Name 'dev_v4_all.ps1'
Assert-ScriptExists -Path $PetScript -Name 'start_teto_pet.ps1'

Write-Host ''
Write-Host '  =============================================' -ForegroundColor DarkYellow
Write-Host '    Repo Tutor - unified launcher' -ForegroundColor Yellow
Write-Host '    starting web/backend and Teto desktop pet' -ForegroundColor Cyan
Write-Host '  =============================================' -ForegroundColor DarkYellow
Write-Host ''

Start-RepoScript -Path $DevScript -Title 'Repo Tutor v4'
Start-RepoScript -Path $PetScript -Title 'Repo Tutor Teto Pet'

Write-Host '  Started both scripts in separate PowerShell windows.' -ForegroundColor Green
Write-Host '  Close those windows to stop their processes.' -ForegroundColor DarkGray
Write-Host ''
Read-Host 'Press Enter to exit'
