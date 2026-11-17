# Скачивает ffmpeg.exe (сборка BtbN 8.1, GPL) в bin\ — нужен для записи видео и для сборки установщика.
# Downloads ffmpeg.exe (BtbN 8.1 build, GPL) into bin\ — required for video recording and for building the installer.
#
# Почему не самая новая сборка: ffmpeg «master» требует драйвер NVIDIA 610+, а 8.1 работает с NVENC на драйверах 570+.
# Why not the newest build: ffmpeg "master" needs NVIDIA driver 610+, while 8.1 works with NVENC on drivers 570+.
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$bin = Join-Path $root 'bin'
$url = 'https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-n8.1-latest-win64-gpl-8.1.zip'
$tmp = Join-Path ([IO.Path]::GetTempPath()) ('skrin-ffmpeg-' + [guid]::NewGuid())
New-Item -ItemType Directory -Force $tmp, $bin | Out-Null
try {
    Write-Host "Downloading $url"
    $ProgressPreference = 'SilentlyContinue'
    Invoke-WebRequest -Uri $url -OutFile "$tmp\ffmpeg.zip" -UseBasicParsing
    Expand-Archive "$tmp\ffmpeg.zip" -DestinationPath $tmp -Force
    $exe = Get-ChildItem $tmp -Recurse -Filter ffmpeg.exe | Select-Object -First 1
    Copy-Item $exe.FullName (Join-Path $bin 'ffmpeg.exe') -Force
    Write-Host "OK: $bin\ffmpeg.exe"
} finally {
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
}
