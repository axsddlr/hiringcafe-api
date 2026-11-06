# Dev run helper for Windows.
# Usage: .\run.ps1            (127.0.0.1:8070)
#        .\run.ps1 -Port 9000
param(
    [int]$Port = 8070,
    [string]$HostAddress = "127.0.0.1"
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "virtualenv missing. Run: uv venv; uv pip install -r requirements.txt"
}

if (-not (Test-Path (Join-Path $PSScriptRoot "data\us_zips.db"))) {
    Write-Host "building zip database..." -ForegroundColor Yellow
    & $python scripts\build_zipdb.py
}

Write-Host "starting on http://${HostAddress}:${Port}  (docs at /docs)" -ForegroundColor Green
& $python -m uvicorn app.main:app --host $HostAddress --port $Port --log-level info
