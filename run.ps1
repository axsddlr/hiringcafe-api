# Dev run helper for Windows.
# Usage: .\run.ps1            (127.0.0.1:8070)
#        .\run.ps1 -Port 9000
param(
    [int]$Port = 8070,
    [string]$HostAddress = "127.0.0.1"
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv not found. Install: https://docs.astral.sh/uv/getting-started/installation/"
}

if (-not (Test-Path (Join-Path $PSScriptRoot "data\us_zips.db"))) {
    Write-Host "building zip database..." -ForegroundColor Yellow
    & uv run python scripts\build_zipdb.py
}

Write-Host "starting on http://${HostAddress}:${Port}  (docs at /docs)" -ForegroundColor Green
& uv run uvicorn app.main:app --host $HostAddress --port $Port --log-level info
