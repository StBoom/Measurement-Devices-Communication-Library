param(
    [string]$ReleaseDate = (Get-Date -Format "yyyy-MM-dd"),
    [switch]$SkipInstall,
    [switch]$SkipExeBuild
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$releaseRoot = Join-Path $projectRoot "release"
$exeSource = Join-Path $projectRoot "dist\MeasurementDevicesCommunicationLibrary"
$dependenciesDir = Join-Path $projectRoot "dependencies"
$buildScript = Join-Path $PSScriptRoot "build_exe.ps1"
$exeReleaseBase = Join-Path $releaseRoot "MeasurementDevicesCommunicationLibrary_EXE_Windows_$ReleaseDate"
$pythonReleaseBase = Join-Path $releaseRoot "MeasurementDevicesCommunicationLibrary_Python_Source_$ReleaseDate"
$dependenciesReleaseBase = Join-Path $releaseRoot "MeasurementDevicesCommunicationLibrary_Dependencies_$ReleaseDate"

$running = Get-Process -Name "MeasurementDevicesCommunicationLibrary" -ErrorAction SilentlyContinue
if ($running) {
    $running | Stop-Process -Force
}

if (-not $SkipExeBuild) {
    if (-not (Test-Path -LiteralPath $buildScript)) {
        throw "Missing build script: $buildScript"
    }

    if ($SkipInstall) {
        & $buildScript -SkipInstall
    }
    else {
        & $buildScript
    }
}

if (-not (Test-Path -LiteralPath $exeSource)) {
    throw "Missing EXE build folder: $exeSource. Run scripts\build_exe.ps1 first or run this script without -SkipExeBuild."
}

if (-not (Test-Path -LiteralPath $releaseRoot)) {
    New-Item -ItemType Directory -Path $releaseRoot | Out-Null
}

function New-UniqueDirectory {
    param([string]$BasePath)

    if (-not (Test-Path -LiteralPath $BasePath) -and -not (Test-Path -LiteralPath "$BasePath.zip")) {
        New-Item -ItemType Directory -Path $BasePath | Out-Null
        return $BasePath
    }

    $timestamp = Get-Date -Format "HHmmss"
    $candidate = "${BasePath}_$timestamp"
    $counter = 2
    while ((Test-Path -LiteralPath $candidate) -or (Test-Path -LiteralPath "$candidate.zip")) {
        $candidate = "${BasePath}_$timestamp-$counter"
        $counter++
    }
    New-Item -ItemType Directory -Path $candidate | Out-Null
    return $candidate
}

function New-ReleaseZip {
    param([string]$DirectoryPath)

    $zipPath = "$DirectoryPath.zip"
    if (Test-Path -LiteralPath $zipPath) {
        throw "Release ZIP already exists: $zipPath"
    }
    Compress-Archive -LiteralPath $DirectoryPath -DestinationPath $zipPath -Force
    return $zipPath
}

$exeRelease = New-UniqueDirectory -BasePath $exeReleaseBase
$pythonRelease = New-UniqueDirectory -BasePath $pythonReleaseBase
$dependenciesRelease = $null

Copy-Item -LiteralPath (Join-Path $exeSource "MeasurementDevicesCommunicationLibrary.exe") -Destination $exeRelease -Force
Copy-Item -LiteralPath (Join-Path $exeSource "_internal") -Destination $exeRelease -Recurse -Force

foreach ($file in @("README.md", "config.example.ini")) {
    $source = Join-Path $projectRoot $file
    if (Test-Path -LiteralPath $source) {
        Copy-Item -LiteralPath $source -Destination $exeRelease -Force
    }
}

foreach ($folder in @("src", "tests", "scripts")) {
    $source = Join-Path $projectRoot $folder
    if (Test-Path -LiteralPath $source) {
        Copy-Item -LiteralPath $source -Destination $pythonRelease -Recurse -Force
    }
}

foreach ($file in @("README.md", "pyproject.toml", "config.example.ini")) {
    $source = Join-Path $projectRoot $file
    if (Test-Path -LiteralPath $source) {
        Copy-Item -LiteralPath $source -Destination $pythonRelease -Force
    }
}

Get-ChildItem -LiteralPath $pythonRelease -Recurse -Directory -Filter "__pycache__" | ForEach-Object {
    Remove-Item -LiteralPath $_.FullName -Recurse -Force
}

Get-ChildItem -LiteralPath $pythonRelease -Recurse -File | Where-Object { $_.Extension -in @(".pyc", ".pyo") } | ForEach-Object {
    Remove-Item -LiteralPath $_.FullName -Force
}

if (Test-Path -LiteralPath $dependenciesDir) {
    $dependenciesRelease = New-UniqueDirectory -BasePath $dependenciesReleaseBase
    Get-ChildItem -LiteralPath $dependenciesDir | Copy-Item -Destination $dependenciesRelease -Recurse -Force
}

$exeReleaseZip = New-ReleaseZip -DirectoryPath $exeRelease
$pythonReleaseZip = New-ReleaseZip -DirectoryPath $pythonRelease
$dependenciesReleaseZip = $null
if ($dependenciesRelease) {
    $dependenciesReleaseZip = New-ReleaseZip -DirectoryPath $dependenciesRelease
}

"EXE release: $exeRelease"
"EXE release ZIP: $exeReleaseZip"
"Python release: $pythonRelease"
"Python release ZIP: $pythonReleaseZip"
if ($dependenciesRelease) {
    "Dependencies release: $dependenciesRelease"
    "Dependencies release ZIP: $dependenciesReleaseZip"
}
