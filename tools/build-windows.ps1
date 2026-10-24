param([string]$Flutter = '', [switch]$SkipBackend)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $Flutter) { $Flutter = Join-Path $projectRoot '.local\toolchains\flutter\bin\flutter.bat' }
if (-not (Test-Path -LiteralPath $Flutter)) { throw 'Flutter SDK not found. Pass -Flutter with a flutter.bat path.' }
Push-Location (Join-Path $projectRoot 'apps\client')
try {
    & $Flutter pub get
    if ($LASTEXITCODE -ne 0) { throw 'flutter pub get failed' }
    & $Flutter build windows --release
    if ($LASTEXITCODE -ne 0) { throw 'Windows build failed' }
} finally { Pop-Location }
$output = Join-Path $projectRoot '.local\releases\windows'
New-Item -ItemType Directory -Force -Path $output | Out-Null
Copy-Item -Path (Join-Path $projectRoot 'apps\client\build\windows\x64\runner\Release\*') -Destination $output -Recurse -Force
if (-not $SkipBackend) {
    Push-Location $projectRoot
    try {
        & uv run --with pyinstaller pyinstaller --noconfirm --clean --onefile --noconsole --name yf-service --distpath .local/releases/windows/backend --workpath .local/pyinstaller/work --specpath .local/pyinstaller --paths services/memory_api --collect-all yf --collect-all uvicorn tools/service_entry.py
        if ($LASTEXITCODE -ne 0) { throw 'Service build failed' }
    } finally { Pop-Location }
}
Write-Output "Windows application: $output\your_friend.exe"
Write-Output 'Copy the entire windows folder when moving this portable app; it contains required libraries and assets.'
