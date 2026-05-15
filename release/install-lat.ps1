#Requires -Version 5.1
<#
.SYNOPSIS
  One-click installer for the `lat` Python CLI.

.DESCRIPTION
  Sets up a Python venv under python-port/ and installs `lat` editably,
  so `lat` becomes available on PATH (within the venv). Auto-detects
  `uv` and uses it if present (much faster than pip); falls back to
  python -m venv + pip.

.PARAMETER Python
  Override the Python interpreter (default: 'python' or 'python3').

.PARAMETER ForceVenv
  Recreate the venv even if it already exists.

.EXAMPLE
  .\release\install-lat.ps1
  .\release\install-lat.ps1 -Python python3.12
#>
param(
    [string]$Python,
    [switch]$ForceVenv
)

$ErrorActionPreference = "Stop"

$repoRoot   = Resolve-Path (Join-Path $PSScriptRoot "..")
$pyPortDir  = Join-Path $repoRoot "python-port"
$venvDir    = Join-Path $pyPortDir ".venv"

if (-not (Test-Path (Join-Path $pyPortDir "pyproject.toml"))) {
    Write-Error "Could not find python-port/pyproject.toml under $repoRoot."
    exit 1
}

# Decide installer strategy.
$haveUv = $null -ne (Get-Command uv -ErrorAction SilentlyContinue)

if (-not $Python) {
    foreach ($candidate in 'python', 'python3') {
        if (Get-Command $candidate -ErrorAction SilentlyContinue) { $Python = $candidate; break }
    }
}
if (-not $Python) {
    Write-Error "No Python interpreter found on PATH. Install Python >= 3.11 (https://www.python.org/) and retry."
    exit 1
}

# Check Python version >= 3.11.
$verLine = & $Python -c "import sys; print('{0}.{1}'.format(sys.version_info.major, sys.version_info.minor))"
$verParts = $verLine.Trim().Split('.')
if ([int]$verParts[0] -lt 3 -or ([int]$verParts[0] -eq 3 -and [int]$verParts[1] -lt 11)) {
    Write-Error "Python $verLine found, but lat needs Python >= 3.11."
    exit 1
}

Write-Host "Installing `lat` Python CLI..." -ForegroundColor Cyan
Write-Host "  Repo root:      $repoRoot"
Write-Host "  python-port:    $pyPortDir"
Write-Host "  Python:         $Python ($verLine)"
Write-Host "  Backend:        $(if ($haveUv) {'uv (preferred)'} else {'pip via venv'})"
Write-Host "  Venv:           $venvDir"
Write-Host ""

# Step 1: create venv.
if ($ForceVenv -and (Test-Path $venvDir)) {
    Write-Host "Removing existing venv..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force $venvDir
}
if (-not (Test-Path $venvDir)) {
    Write-Host "Creating venv..." -ForegroundColor Cyan
    Push-Location $pyPortDir
    try {
        if ($haveUv) {
            & uv venv --python $Python
        } else {
            & $Python -m venv .venv
        }
    } finally { Pop-Location }
} else {
    Write-Host "Venv already exists — reusing (use -ForceVenv to recreate)." -ForegroundColor Yellow
}

# Step 2: install `lat` editably.
Write-Host "Installing lat (editable)..." -ForegroundColor Cyan
Push-Location $pyPortDir
try {
    if ($haveUv) {
        & uv pip install -e .
    } else {
        $pipExe = Join-Path $venvDir "Scripts\pip.exe"
        if (-not (Test-Path $pipExe)) { $pipExe = Join-Path $venvDir "bin/pip" }
        & $pipExe install -e .
    }
} finally { Pop-Location }

# Step 3: verify.
$latExe = Join-Path $venvDir "Scripts\lat.exe"
if (-not (Test-Path $latExe)) { $latExe = Join-Path $venvDir "bin/lat" }

Write-Host ""
Write-Host "=========================================================" -ForegroundColor Green
Write-Host "lat installed successfully" -ForegroundColor Green
Write-Host "=========================================================" -ForegroundColor Green
Write-Host ""
Write-Host "To use lat in your current shell, activate the venv:"
Write-Host "  $venvDir\Scripts\Activate.ps1" -ForegroundColor Cyan
Write-Host ""
Write-Host "Then verify:"
Write-Host "  lat --help" -ForegroundColor Cyan
Write-Host ""
Write-Host "Or run lat directly without activating:"
Write-Host "  $latExe --help" -ForegroundColor Cyan
Write-Host ""
