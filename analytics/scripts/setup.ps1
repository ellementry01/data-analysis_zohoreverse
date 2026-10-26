# One-time setup for Ellementry Analytics on Windows (PowerShell 5.1+).
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 [-DbUser postgres] [-DbHost localhost] [-DbPort 5432]
# Requires: Python 3.11+, Node.js 18+, PostgreSQL 14+ (psql on PATH or in C:\Program Files\PostgreSQL\<v>\bin).
param(
  [string]$DbUser = "postgres",
  [string]$DbHost = "localhost",
  [int]$DbPort = 5432,
  [string]$DbName = "ellementry_analytics"
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Write-Host "== Ellementry Analytics setup ==" -ForegroundColor Cyan

# --- locate psql --------------------------------------------------------------------------------
$psql = (Get-Command psql -ErrorAction SilentlyContinue).Source
if (-not $psql) {
  $cand = Get-ChildItem "C:\Program Files\PostgreSQL\*\bin\psql.exe" -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | Select-Object -First 1
  if ($cand) { $psql = $cand.FullName }
}
if (-not $psql) { throw "psql not found. Install PostgreSQL or add its bin folder to PATH." }

# --- databases (password comes from PGPASSWORD / pgpass.conf, or psql prompts) ------------------
foreach ($db in @($DbName, "${DbName}_test")) {
  $exists = & $psql -h $DbHost -p $DbPort -U $DbUser -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$db'"
  if ($exists -ne "1") {
    Write-Host "Creating database $db"
    & $psql -h $DbHost -p $DbPort -U $DbUser -d postgres -c "CREATE DATABASE $db" | Out-Null
  } else { Write-Host "Database $db exists" }
}

# --- backend --------------------------------------------------------------------------------------
Push-Location "$root\backend"
if (-not (Test-Path ".venv")) { python -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install --upgrade pip | Out-Null
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path ".env")) {
  (Get-Content .env.example) -replace "postgresql\+psycopg://postgres@localhost:5432/ellementry_analytics", "postgresql+psycopg://$DbUser@${DbHost}:$DbPort/$DbName" | Set-Content -Encoding utf8 .env
  Write-Host "Created backend\.env (edit it to add a password or LLM settings)"
}
New-Item -ItemType Directory -Force "data\uploads" | Out-Null
& .\.venv\Scripts\python.exe -c "from app.db import init_db; init_db(); print('database migrated')"
Pop-Location

# --- sample data ----------------------------------------------------------------------------------
if (-not (Test-Path "$root\sample_data\sales_register.xlsx")) {
  Push-Location "$root\sample_data"; & "$root\backend\.venv\Scripts\python.exe" generate.py; Pop-Location
}

# --- frontend -------------------------------------------------------------------------------------
Push-Location "$root\frontend"
npm install --no-audit --no-fund
npm run build
Pop-Location

Write-Host "`nSetup complete. Start the app with:  scripts\start.ps1" -ForegroundColor Green
