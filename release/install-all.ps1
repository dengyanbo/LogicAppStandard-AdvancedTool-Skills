#Requires -Version 5.1
<#
.SYNOPSIS
  One-click installer for everything: `lat` CLI + agent skill.

.DESCRIPTION
  Composite installer that runs install-lat.ps1 then install-skill.ps1.
  Aborts on first error.

.PARAMETER Force
  Pass -Force to the skill installer (skips overwrite prompts).

.PARAMETER ForceVenv
  Pass -ForceVenv to the lat installer (recreates the venv from scratch).

.PARAMETER Python
  Override the Python interpreter used by the lat installer.

.EXAMPLE
  .\release\install-all.ps1
  .\release\install-all.ps1 -Force
#>
param(
    [switch]$Force,
    [switch]$ForceVenv,
    [string]$Python
)

$ErrorActionPreference = "Stop"

$scriptDir = $PSScriptRoot

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Installing lat + logicapp-std-operator skill"               -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# Step 1: lat.
$latArgs = @{}
if ($ForceVenv) { $latArgs.ForceVenv = $true }
if ($Python)    { $latArgs.Python    = $Python }
& (Join-Path $scriptDir "install-lat.ps1") @latArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""

# Step 2: skill.
$skillArgs = @{}
if ($Force) { $skillArgs.Force = $true }
& (Join-Path $scriptDir "install-skill.ps1") @skillArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  All done!"                                                  -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Quick checklist:"
Write-Host "  1. Activate the lat venv:"
Write-Host "     <repo>\python-port\.venv\Scripts\Activate.ps1" -ForegroundColor Cyan
Write-Host "  2. Verify lat:        lat --help"                  -ForegroundColor Cyan
Write-Host "  3. Open Copilot CLI:  copilot"                     -ForegroundColor Cyan
Write-Host "  4. Verify the skill:  /skills reload  then  /env"  -ForegroundColor Cyan
Write-Host ""
