#Requires -Version 5.1
<#
.SYNOPSIS
  Install the logicapp-std-operator skill into ~/.agents/skills/ so Copilot
  CLI auto-loads it from any directory.

.PARAMETER Target
  Override the install target (default: ~/.agents/skills/logicapp-std-operator).

.PARAMETER Force
  Overwrite an existing install without prompting.

.EXAMPLE
  .\install.ps1
  .\install.ps1 -Force
  .\install.ps1 -Target C:\custom\path\logicapp-std-operator
#>
param(
    [string]$Target = (Join-Path $env:USERPROFILE ".agents\skills\logicapp-std-operator"),
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$source = $PSScriptRoot

if (-not (Test-Path (Join-Path $source "SKILL.md"))) {
    Write-Error "install.ps1 must be run from inside the skill folder (no SKILL.md found in $source)."
    exit 1
}

if (Test-Path $Target) {
    if (-not $Force) {
        Write-Host "Target already exists: $Target" -ForegroundColor Yellow
        $reply = Read-Host "Overwrite? (y/N)"
        if ($reply -ne "y" -and $reply -ne "Y") {
            Write-Host "Aborted." -ForegroundColor Red
            exit 1
        }
    }
    Remove-Item -Recurse -Force $Target
}

# Ensure parent dir exists. New-Item -Force creates intermediate dirs and
# is a no-op when the dir already exists, so we don't need Split-Path.
$parent = [System.IO.Path]::GetDirectoryName($Target)
if ($parent -and -not (Test-Path $parent)) {
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
}

Copy-Item -Recurse $source $Target

# Strip scaffolding from the destination (they're not part of the runtime skill).
foreach ($scaffold in @("install.ps1", "install.sh", "INSTALL.md")) {
    $path = Join-Path $Target $scaffold
    if (Test-Path $path) { Remove-Item -Force $path }
}

Write-Host ""
Write-Host "Installed to $Target" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. In your Copilot CLI session, run: /skills reload"
Write-Host "     (or /restart if /skills reload doesn't pick it up)"
Write-Host "  2. Verify with: /env"
Write-Host "     -- look for 'logicapp-std-operator' under Skills."
Write-Host "  3. Make sure 'lat' is installed and on PATH:"
Write-Host "     cd <repo>\python-port; uv pip install -e ."
Write-Host ""
