# Сборка установщика «Скрина»: dist\SkrinSetup-<версия>.exe
# Нужно: Python с PySide6, pyaudiowpatch, pyinstaller, Pillow; Inno Setup 6; bin\ffmpeg.exe (сборка 8.1).
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$ver = (python -c "import config; print(config.VERSION)").Trim()
Write-Host "Скрин $ver"

python build\make_icon.py

python -m PyInstaller --noconfirm --clean --windowed --name Skrin `
    --icon "$PSScriptRoot\build\skrin.ico" `
    --distpath "$PSScriptRoot\build\dist" --workpath "$PSScriptRoot\build\work" --specpath "$PSScriptRoot\build" `
    --exclude-module PIL --exclude-module numpy --exclude-module tkinter `
    skrin.pyw
if ($LASTEXITCODE -ne 0) { throw "PyInstaller завершился с ошибкой" }

$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Не найден Inno Setup 6 (winget install JRSoftware.InnoSetup)" }
& $iscc /Qp "/DAppVer=$ver" build\skrin.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup завершился с ошибкой" }

Get-Item "dist\SkrinSetup-$ver.exe" | Select-Object FullName, @{n='МБ'; e={[math]::Round($_.Length / 1MB, 1)}}
