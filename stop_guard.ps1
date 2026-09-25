$ErrorActionPreference = 'Stop'
$infoPath = Join-Path $PSScriptRoot 'guard_live\process.json'
if (-not (Test-Path -LiteralPath $infoPath)) { throw 'No ETH Guard process record exists.' }
$info = Get-Content -LiteralPath $infoPath -Raw | ConvertFrom-Json
$guardProcessId = [int]$info.pid
$guardProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $guardProcessId"
if (-not $guardProcess) { Write-Output 'ETH Guard is already stopped.'; exit 0 }
$expectedScript = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'guard_server.py'))
if (-not $guardProcess.CommandLine.Contains($expectedScript)) {
    throw 'Recorded PID belongs to a different command. Nothing was stopped.'
}
Stop-Process -Id $guardProcessId
Write-Output 'ETH Guard stopped. SQLite state is retained. Paper exits do not run while stopped.'
