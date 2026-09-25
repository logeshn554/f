param(
    [ValidateSet('paper','replay','status')][string]$Mode = 'paper',
    [ValidateSet('india','global')][string]$Region = 'india',
    [ValidateRange(1,100000)][int]$Cycles = 1,
    [ValidateRange(5,60)][int]$Interval = 15
)
$ErrorActionPreference = 'Stop'
$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
$bundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if ($pythonCommand) {
    $pythonPath = $pythonCommand.Source
} elseif (Test-Path -LiteralPath $bundledPython) {
    $pythonPath = $bundledPython
} else {
    throw 'Python 3.10 or newer is required. Install Python and run this script again.'
}
$scriptPath = Join-Path $PSScriptRoot 'delta_paper.py'
$dataPath = Join-Path $PSScriptRoot ('delta_run_' + $Region)
& $pythonPath $scriptPath $Mode --region $Region --directory $dataPath --cycles $Cycles --interval $Interval
exit $LASTEXITCODE
