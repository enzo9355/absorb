# ABSORB Institutional Report Runtime Dependency Installation Script
# Usage: .\scripts\install_report_runtime.ps1

$ErrorActionPreference = "Stop"

Write-Host "Upgrading pip..." -ForegroundColor Green
python -m pip install --upgrade pip

Write-Host "Installing base production requirements..." -ForegroundColor Green
python -m pip install -r requirements.txt

Write-Host "Installing report runtime requirements (ReportLab, Matplotlib, PyPDF, Statsmodels)..." -ForegroundColor Green
python -m pip install -r requirements-report.txt

Write-Host "Report runtime installation complete." -ForegroundColor Green
