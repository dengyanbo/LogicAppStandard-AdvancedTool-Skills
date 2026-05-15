#Requires -Version 5.1
<#
.SYNOPSIS
  One-click installer for the logicapp-std-operator skill.

.DESCRIPTION
  Installs the agent skill to ~/.agents/skills/ so Copilot CLI auto-loads it
  from any directory. Wraps the skill-bundled installer at
  .github/skills/logicapp-std-operator/install.ps1.

.PARAMETER Target
  Override the install target. Defaults to
  $env:USERPROFILE\.agents\skills\logicapp-std-operator.

.PARAMETER Force
  Overwrite an existing install without prompting.

.EXAMPLE
  .\release\install-skill.ps1
  .\release\install-skill.ps1 -Force
#>
param(
    [string]$Target,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

# Resolve repo root from this script's location.
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$skillBundled = Join-Path $repoRoot ".github\skills\logicapp-std-operator\install.ps1"

if (-not (Test-Path $skillBundled)) {
    Write-Error "Could not find skill installer at $skillBundled. Is this script running from inside the repo?"
    exit 1
}

Write-Host "Installing logicapp-std-operator skill..." -ForegroundColor Cyan
Write-Host "  Repo root:  $repoRoot"
Write-Host "  Delegating to: $skillBundled"
Write-Host ""

$args = @()
if ($Target) { $args += @("-Target", $Target) }
if ($Force)  { $args += "-Force" }

& $skillBundled @args
exit $LASTEXITCODE
