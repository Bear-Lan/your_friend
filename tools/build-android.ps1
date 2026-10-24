param([string]$Flutter = '', [string]$AndroidSdk = '', [string]$Jdk = '')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $Flutter) { $Flutter = Join-Path $projectRoot '.local\toolchains\flutter\bin\flutter.bat' }
if (-not $AndroidSdk) { $AndroidSdk = Join-Path $projectRoot '.local\toolchains\android' }
if ($Jdk) { $env:JAVA_HOME = $Jdk }
$env:ANDROID_HOME = $AndroidSdk
$env:ANDROID_SDK_ROOT = $AndroidSdk
Push-Location (Join-Path $projectRoot 'apps\client')
try {
    & $Flutter pub get
    if ($LASTEXITCODE -ne 0) { throw 'flutter pub get failed' }
    # Debug signing is intentionally used for this development preview. Release
    # signing keys must be supplied separately before public distribution.
    & $Flutter build apk --debug
    if ($LASTEXITCODE -ne 0) { throw 'Android build failed' }
    $output = Join-Path $projectRoot '.local\releases\android'
    New-Item -ItemType Directory -Force -Path $output | Out-Null
    Copy-Item -LiteralPath 'build\app\outputs\flutter-apk\app-debug.apk' -Destination (Join-Path $output 'your-friend-preview.apk') -Force
    Write-Output "Development APK: $output\your-friend-preview.apk"
} finally { Pop-Location }
