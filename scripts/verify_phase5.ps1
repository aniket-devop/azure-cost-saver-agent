#requires -Version 5.1
<#
.SYNOPSIS
  Verifies the Phase 5 CLI from PowerShell without touching Azure.
.DESCRIPTION
  Runs from anywhere. Creates .venv if missing, installs the project, runs the quality checks,
  then exercises the offline `azure-finops demo` scenarios and checks exit codes, output files,
  ASCII-only console output and byte-for-byte reproducibility. Works in Windows PowerShell 5.1
  and PowerShell 7+. It never calls Azure: the demo uses synthetic in-memory data.
#>
[CmdletBinding()]
param([switch]$SkipQualityChecks)

$ErrorActionPreference = 'Stop'
$ExpectedDemoReportSha256 = 'A67A62D640A66832FC8E7DE8846D9833A49EA13144AA3D97E017E54D096B5FEB'

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot
$OnWindows = ($PSVersionTable.PSVersion.Major -lt 6) -or $IsWindows
$Failures = New-Object System.Collections.Generic.List[string]

function Write-Check([bool]$Ok, [string]$Message) {
    if ($Ok) { Write-Host "[PASS] $Message" } else { Write-Host "[FAIL] $Message"; $Failures.Add($Message) }
}

# Runs a native command, never throws on stderr output (Windows PowerShell 5.1 would),
# and returns the exit code plus all output as one ASCII-checked string.
function Invoke-Native([string]$Exe, [string[]]$Arguments) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $lines = & $Exe @Arguments 2>&1 | ForEach-Object { "$_" }
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
    return [pscustomobject]@{ ExitCode = $code; Output = ($lines -join "`n") }
}

Write-Host "PowerShell $($PSVersionTable.PSVersion) on $(if ($OnWindows) { 'Windows' } else { 'non-Windows (not a Windows verification)' })"

# 1. Python and virtual environment
$pythonCmd = if ($OnWindows) { 'python' } else { 'python3' }
$sysPython = Get-Command $pythonCmd -ErrorAction SilentlyContinue
if (-not $sysPython) { throw "Python 3.11+ was not found on PATH." }
# NOTE: Windows PowerShell 5.1 strips double quotes from arguments passed to native programs,
# so python -c snippets below must not contain any double quote.
$ver = Invoke-Native $sysPython.Source @('-c', 'import sys; print(sys.version_info.major, sys.version_info.minor)')
$verText = (($ver.Output -split '\s+') | Where-Object { $_ -ne '' }) -join '.'
$verOk = ($ver.ExitCode -eq 0) -and ($verText -match '^\d+\.\d+$') -and ([version]$verText -ge [version]'3.11')
Write-Check $verOk "Python $verText is 3.11 or newer"

$venvPython = if ($OnWindows) { Join-Path $RepoRoot '.venv\Scripts\python.exe' } else { Join-Path $RepoRoot '.venv/bin/python' }
$venvCli = if ($OnWindows) { Join-Path $RepoRoot '.venv\Scripts\azure-finops.exe' } else { Join-Path $RepoRoot '.venv/bin/azure-finops' }
if (-not (Test-Path $venvPython)) {
    Write-Host "Creating .venv ..."
    $r = Invoke-Native $sysPython.Source @('-m', 'venv', '.venv'); Write-Check ($r.ExitCode -eq 0) 'venv created'
}
$r = Invoke-Native $venvPython @('-m', 'pip', 'install', '--quiet', '-e', '.[dev]')
Write-Check ($r.ExitCode -eq 0) 'pip install -e ".[dev]"'

# 2. Quality checks
if (-not $SkipQualityChecks) {
    foreach ($step in @(
        @{ Name = 'pytest';       Args = @('-m', 'pytest', '-q') },
        @{ Name = 'ruff check';   Args = @('-m', 'ruff', 'check', '.') },
        @{ Name = 'ruff format';  Args = @('-m', 'ruff', 'format', '--check', '.') },
        @{ Name = 'mypy (strict)'; Args = @('-m', 'mypy') })) {
        $r = Invoke-Native $venvPython $step.Args
        Write-Check ($r.ExitCode -eq 0) $step.Name
        if ($r.ExitCode -ne 0) { Write-Host $r.Output }
    }
}

# 3. Offline CLI scenarios: expected exit codes and output files
$work = Join-Path ([System.IO.Path]::GetTempPath()) ("azure-finops-verify-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $work | Out-Null
$scenarios = @(
    @{ Name = 'healthy';        Code = 0 },
    @{ Name = 'partial';        Code = 3 },
    @{ Name = 'notify-failure'; Code = 4 },
    @{ Name = 'llm-rejected';   Code = 0 })
foreach ($s in $scenarios) {
    $out = Join-Path $work $s.Name
    $r = Invoke-Native $venvCli @('demo', '--scenario', $s.Name, '--out-dir', $out)
    Write-Check ($r.ExitCode -eq $s.Code) "demo --scenario $($s.Name) exits $($s.Code) (got $($r.ExitCode))"
    Write-Check (($r.Output -notmatch '[^\x00-\x7F]')) "demo --scenario $($s.Name) console output is ASCII"
    $files = 'report.md', 'report.json', 'run_summary.json' | ForEach-Object { Test-Path (Join-Path $out $_) }
    Write-Check (($files -notcontains $false)) "demo --scenario $($s.Name) wrote report.md, report.json, run_summary.json"
}

# 4. `python -m` entry point and --explain
$out = Join-Path $work 'module'
$r = Invoke-Native $venvPython @('-m', 'azure_finops_agent', 'demo', '--explain', '--out-dir', $out)
Write-Check ($r.ExitCode -eq 0 -and (Test-Path (Join-Path $out 'explanation.txt'))) 'python -m azure_finops_agent demo --explain writes explanation.txt'

# 5. Reproducibility: same bytes twice, and the known hash
$a = Join-Path $work 'repro-a'; $b = Join-Path $work 'repro-b'
[void](Invoke-Native $venvCli @('demo', '--out-dir', $a)); [void](Invoke-Native $venvCli @('demo', '--out-dir', $b))
$ha = (Get-FileHash (Join-Path $a 'report.json') -Algorithm SHA256).Hash
$hb = (Get-FileHash (Join-Path $b 'report.json') -Algorithm SHA256).Hash
Write-Check ($ha -ieq $hb) 'two demo runs produce byte-identical report.json'
Write-Check ($ha -ieq $ExpectedDemoReportSha256) "demo report.json SHA-256 matches the documented value ($ha)"

# 6. Real mode fails fast and clearly without configuration (no Azure call is attempted)
$savedSub = $env:AZURE_SUBSCRIPTION_ID
Remove-Item Env:AZURE_SUBSCRIPTION_ID -ErrorAction SilentlyContinue
$r = Invoke-Native $venvCli @('run', '--out-dir', (Join-Path $work 'real'))
Write-Check ($r.ExitCode -eq 1 -and $r.Output -match 'AZURE_SUBSCRIPTION_ID') "run without AZURE_SUBSCRIPTION_ID exits 1 with a clear message"
if ($savedSub) { $env:AZURE_SUBSCRIPTION_ID = $savedSub }

$r = Invoke-Native $venvCli @('--version'); Write-Check ($r.ExitCode -eq 0) "azure-finops --version ($($r.Output))"
Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue

if ($Failures.Count -gt 0) {
    Write-Host "`n$($Failures.Count) check(s) FAILED:"; $Failures | ForEach-Object { Write-Host " - $_" }
    exit 1
}
Write-Host "`nAll checks passed."
exit 0
