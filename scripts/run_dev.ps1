# Free port 7860, activate .venv, and start AI Citizen Assistant cleanly
$ErrorActionPreference = "SilentlyContinue"
$conns = Get-NetTCPConnection -LocalPort 7860
if ($conns) {
    $conns | ForEach-Object {
        Stop-Process -Id $_.OwningProcess -Force
    }
    Start-Sleep -Milliseconds 500
}
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
& "$Root\.venv\Scripts\Activate.ps1"
python run.py
