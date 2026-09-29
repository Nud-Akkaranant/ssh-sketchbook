param(
    [ValidatePattern('^\d+\.\d+\.\d+(?:\.\d+)?$')]
    [string]$Version = '0.1.0'
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
Set-Location (Split-Path -Parent $PSScriptRoot)

python -m PyInstaller --noconfirm --clean --onedir --windowed `
    --name ssh-sketchbook --icon static/icon.ico --add-data 'static;static' app.py

$bundle = 'dist/ssh-sketchbook/_internal'
foreach ($asset in @('static/vendor/xterm.js', 'static/vendor/xterm.css', 'static/vendor/addon-fit.js', 'winpty/winpty.dll')) {
    if (-not (Test-Path (Join-Path $bundle $asset))) {
        throw "The bundled app is missing $asset."
    }
}
if (-not (Get-ChildItem (Join-Path $bundle 'winpty') -Filter '*winpty*.pyd')) {
    throw 'The bundled app is missing the pywinpty native extension.'
}

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
