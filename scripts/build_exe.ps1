param(
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$appName = "MeasurementDevicesCommunicationLibrary"
$entryPoint = Join-Path $projectRoot "src\instrument_visa\gui_launcher.py"
$distDir = Join-Path $projectRoot "dist"
$buildDir = Join-Path $projectRoot "build"
$specFile = Join-Path $projectRoot "$appName.spec"
$appDistDir = Join-Path $distDir $appName
$projectWithSaleae = "$projectRoot[saleae]"

if (-not (Test-Path -LiteralPath $entryPoint)) {
    throw "Entry point not found: $entryPoint"
}

if (-not $SkipInstall) {
    py -m pip install -e $projectWithSaleae
    py -m pip install --upgrade pyinstaller
}

if (Test-Path -LiteralPath $buildDir) {
    Remove-Item -LiteralPath $buildDir -Recurse -Force
}
if (Test-Path -LiteralPath $appDistDir) {
    Remove-Item -LiteralPath $appDistDir -Recurse -Force
}
if (Test-Path -LiteralPath $specFile) {
    Remove-Item -LiteralPath $specFile -Force
}

Push-Location $projectRoot
try {
    py -m PyInstaller `
        --noconfirm `
        --clean `
        --onedir `
        --windowed `
        --name $appName `
        --paths "src" `
        --collect-all pyvisa `
        --collect-all pyvisa_py `
        --collect-all openpyxl `
        --collect-all PIL `
        --collect-all serial `
        --collect-all paramiko `
        --collect-all saleae `
        $entryPoint
}
finally {
    Pop-Location
}

$filesToCopy = @(
    "README.md",
    "config.example.ini"
)

foreach ($file in $filesToCopy) {
    $source = Join-Path $projectRoot $file
    if (Test-Path -LiteralPath $source) {
        Copy-Item -LiteralPath $source -Destination $appDistDir -Force
    }
}

New-Item -ItemType Directory -Path (Join-Path $appDistDir "logs") -Force | Out-Null

"Build complete: $(Join-Path $appDistDir "$appName.exe")"
"Optional runtime installers are packaged separately by scripts\package_release.ps1."
