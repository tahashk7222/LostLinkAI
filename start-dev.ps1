# Starts the LostLink AI backend (http://localhost:8000) and frontend (http://localhost:3000)
# in two new PowerShell windows. Easiest: double-click start-dev.cmd (works under any execution policy).
# npm.cmd is used instead of npm because npm.ps1 is blocked when script execution is restricted.
$root = $PSScriptRoot

# Reload PATH from the registry so tools installed after this terminal (or VS Code) started are found.
$env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
    Write-Host "Node.js/npm not found. Install Node.js 20+ from https://nodejs.org and try again."
    exit 1
}

if (-not (Test-Path "$root\backend\.venv")) {
    Write-Host "Backend venv missing. Run:  cd backend; python -m venv .venv; .\.venv\Scripts\pip install -r requirements.txt"
    exit 1
}
if (-not (Test-Path "$root\backend\.env")) {
    # Never run with the placeholder secret: generate a random one for this machine.
    $secret = & "$root\backend\.venv\Scripts\python.exe" -c "import secrets;print(secrets.token_urlsafe(48))"
    (Get-Content "$root\backend\.env.example") -replace '^JWT_SECRET=.*', "JWT_SECRET=$secret" |
        Set-Content "$root\backend\.env" -Encoding ascii
}
if (-not (Test-Path "$root\frontend\.env.local")) { Copy-Item "$root\frontend\.env.example" "$root\frontend\.env.local" }
if (-not (Test-Path "$root\frontend\node_modules")) {
    Write-Host "Installing frontend dependencies..."
    Push-Location "$root\frontend"; npm.cmd install; Pop-Location
}

Start-Process powershell -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-Command", "cd '$root\backend'; .\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000"
Start-Process powershell -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-Command", "cd '$root\frontend'; npm.cmd run dev"
Write-Host "API:  http://localhost:8000/docs"
Write-Host "Web:  http://localhost:3000"
