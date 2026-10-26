# Start Ellementry Analytics.
#   scripts\start.ps1          -> production mode: API + built UI on http://localhost:8000
#   scripts\start.ps1 -Dev     -> dev mode: API on :8000 (auto-reload) + Vite UI on http://localhost:5173
param([switch]$Dev)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$py = "$root\backend\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

if ($Dev) {
  Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\backend'; & '$py' -m uvicorn app.main:app --reload --port 8000"
  Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\frontend'; npm run dev"
  Start-Sleep -Seconds 4
  Start-Process "http://localhost:5173"
} else {
  if (-not (Test-Path "$root\frontend\dist\index.html")) {
    Push-Location "$root\frontend"; npm run build; Pop-Location
  }
  Start-Process "http://localhost:8000"
  Set-Location "$root\backend"
  & $py -m uvicorn app.main:app --host 127.0.0.1 --port 8000
}
