[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$DossierProjet = (Get-Location).Path,
    [string]$Sauvegarde = ''
)

$ErrorActionPreference = 'Stop'
$Target = [System.IO.Path]::GetFullPath($DossierProjet)
$BackupRoot = Join-Path $Target '_backups'
if ([string]::IsNullOrWhiteSpace($Sauvegarde)) {
    $Candidate = Get-ChildItem -LiteralPath $BackupRoot -Directory -Filter 'loto-lab-1.1.0-*' -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $Candidate) { throw "Aucune sauvegarde LOTO LAB 1.1.0 trouvée dans $BackupRoot" }
    $Sauvegarde = $Candidate.FullName
}
$BackupRoot = [System.IO.Path]::GetFullPath($Sauvegarde)
if (-not (Test-Path -LiteralPath $BackupRoot -PathType Container)) {
    throw "Dossier de sauvegarde introuvable : $BackupRoot"
}
$Files = @(Get-ChildItem -LiteralPath $BackupRoot -Recurse -File)
if ($Files.Count -eq 0) { throw "La sauvegarde est vide : $BackupRoot" }

Write-Host '=== RESTAURATION LOTO LAB ===' -ForegroundColor Yellow
Write-Host "Projet     : $Target"
Write-Host "Sauvegarde : $BackupRoot"
foreach ($File in $Files) {
    $Relative = $File.FullName.Substring($BackupRoot.TrimEnd('\').Length).TrimStart('\')
    $Destination = Join-Path $Target $Relative
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Destination) | Out-Null
    Copy-Item -LiteralPath $File.FullName -Destination $Destination -Force
    Write-Host "Restauré : $Relative"
}
Write-Host 'Restauration terminée. Redémarre l’application.' -ForegroundColor Green
Write-Host 'Les fichiers non présents dans la sauvegarde ainsi que loto.db et .env sont laissés intacts.'
