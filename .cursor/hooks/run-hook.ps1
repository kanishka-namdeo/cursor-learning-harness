param(
    [Parameter(Mandatory = $true)]
    [string]$ScriptName
)

$ScriptPath = Split-Path -Parent $MyInvocation.MyCommand.Definition
$ProjectRoot = Split-Path (Split-Path $ScriptPath -Parent) -Parent
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$TargetScript = Join-Path $ScriptPath $ScriptName

if (-not (Test-Path $TargetScript)) {
    Write-Error "Hook script not found: $TargetScript"
    exit 1
}

if (Test-Path $VenvPython) {
    & $VenvPython $TargetScript @args
} else {
    python $TargetScript @args
}
