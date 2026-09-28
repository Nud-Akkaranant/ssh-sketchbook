param(
    [ValidatePattern('^\d+\.\d+\.\d+(?:\.\d+)?$')]
    [string]$Version = '0.1.0'
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
Set-Location (Split-Path -Parent $PSScriptRoot)

python -m PyInstaller --noconfirm --clean --onedir --windowed `
    --name ssh-sketchbook --icon static/icon.ico --add-data 'static;static' app.py

$iscc = (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source
if (-not $iscc) {
    $iscc = Join-Path ([Environment]::GetFolderPath('ProgramFilesX86')) 'Inno Setup 6\ISCC.exe'
}
if (-not (Test-Path $iscc)) {
    throw 'Inno Setup 6 is required. Install it before building the setup executable.'
}

& $iscc "/DAppVersion=$Version" 'installer/ssh-sketchbook.iss'
if (-not (Test-Path 'dist/installer/ssh-sketchbook-setup.exe')) {
    throw 'The installer was not created.'
}
