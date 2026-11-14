[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$DossierProjet = (Get-Location).Path
)

$ErrorActionPreference = "Stop"
$Source = [System.IO.Path]::GetFullPath($PSScriptRoot)
$Target = [System.IO.Path]::GetFullPath($DossierProjet)

# Refuse to run when the archive was extracted directly over the live project.
if ([string]::Equals($Source.TrimEnd('\'), $Target.TrimEnd('\'), [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "The update archive must be extracted to a separate temporary folder. Do not run the installer from inside the live project. See MISE-A-JOUR-PRO-1.1.0.txt."
}

$Required = @(
    "analysis_engine.py", "scientific_engine.py",
    "app\main.py", "app\templates\index.html", "app\templates\login.html", "app\templates\science.html",
    "app\static\style.css", "app\static\app.js", "app\static\science.css",
    "app\static\science.js", "app\static\theme.js",
    "tests\test_analysis.py", "tests\test_scientific_engine.py",
    "README.md", "MISE-A-JOUR-PRO-1.1.0.txt",
    "INSTALLER-LOTO-LAB-PRO.ps1", "RESTAURER-LOTO-LAB.ps1"
)

foreach ($Relative in $Required) {
    $Candidate = Join-Path $Source $Relative
    if (-not (Test-Path -LiteralPath $Candidate -PathType Leaf)) {
        throw "Required update file is missing: $Candidate"
    }
}

if (-not (Test-Path -LiteralPath (Join-Path $Target "app\main.py") -PathType Leaf)) {
    throw "Invalid target folder: app\main.py was not found in $Target"
}

$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupRoot = Join-Path $Target ("_backups\loto-lab-1.1.0-" + $Stamp)
New-Item -ItemType Directory -Force -Path $BackupRoot | Out-Null

Write-Host "=== LOTO LAB 1.1.0 - SAFE UPDATE ===" -ForegroundColor Cyan
Write-Host "Source: $Source"
Write-Host "Target: $Target"
Write-Host "Backup: $BackupRoot"

foreach ($Relative in $Required) {
    $From = Join-Path $Source $Relative
    $To = Join-Path $Target $Relative
    $ToDir = Split-Path -Parent $To
    New-Item -ItemType Directory -Force -Path $ToDir | Out-Null

    if (Test-Path -LiteralPath $To -PathType Leaf) {
        $Backup = Join-Path $BackupRoot $Relative
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Backup) | Out-Null
        Copy-Item -LiteralPath $To -Destination $Backup -Force
    }

    Copy-Item -LiteralPath $From -Destination $To -Force
    Write-Host "Updated: $Relative"
}

Write-Host ""
Write-Host "Update completed." -ForegroundColor Green
Write-Host "The loto.db database, .env file, passwords, and secret keys were not modified." -ForegroundColor Green
Write-Host "Restart LOTO LAB, check the Appearance selector, and open /science."
