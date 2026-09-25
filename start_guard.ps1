param([ValidateRange(1024,65535)][int]$Port = 8765, [switch]$Foreground)
$ErrorActionPreference = 'Stop'
$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
$bundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if ($pythonCommand) { $pythonPath = $pythonCommand.Source }
elseif (Test-Path -LiteralPath $bundledPython) { $pythonPath = $bundledPython }
else { throw 'Python 3.10 or newer is required.' }
$scriptPath = Join-Path $PSScriptRoot 'guard_server.py'
$logPath = Join-Path $PSScriptRoot 'guard_live'
New-Item -ItemType Directory -Force -Path $logPath | Out-Null
if ($Foreground) {
    & $pythonPath $scriptPath --port $Port
} else {
    $serverArgs = '"' + $scriptPath + '" --port ' + $Port
    $process = Start-Process -FilePath $pythonPath -ArgumentList $serverArgs -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logPath 'stdout.log') -RedirectStandardError (Join-Path $logPath 'stderr.log')
    if ($process.WaitForExit(1500)) {
        $startupError = Get-Content -LiteralPath (Join-Path $logPath 'stderr.log') -Tail 10
        throw "ETH Guard exited during startup: $startupError"
    }
    Write-Output "ETH Guard starting on http://127.0.0.1:$Port (process $($process.Id)). Use the dashboard to pause entries or close a paper position."
}
