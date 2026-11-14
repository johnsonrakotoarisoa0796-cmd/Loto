$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Host "=== LOTO LAB : ajout du laboratoire scientifique ===" -ForegroundColor Cyan
python .\apply_scientific_upgrade.py
if ($LASTEXITCODE -ne 0) { throw "L'application de la mise à jour a échoué." }

Write-Host "`nVérification de la syntaxe Python..." -ForegroundColor Cyan
python -m py_compile .\scientific_engine.py .\app\main.py
if ($LASTEXITCODE -ne 0) { throw "Erreur de syntaxe Python. Les sauvegardes .bak sont conservées." }

Write-Host "`nMise à jour appliquée. Pour exécuter tous les tests :" -ForegroundColor Green
Write-Host "python -m pytest tests -q" -ForegroundColor Yellow
Write-Host "Puis publier la mise à jour sur GitHub :" -ForegroundColor Green
Write-Host 'git add .; git commit -m "Add conservative scientific anomaly audit"; git -c http.version=HTTP/1.1 push' -ForegroundColor Yellow
