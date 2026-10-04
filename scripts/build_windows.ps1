$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

python scripts/make_icons.py
pip install -r requirements.txt -r requirements-dev.txt

# WITH_CUDA=1 — включить CUDA-библиотеки в exe (нужны pip-пакеты nvidia-cublas-cu12, nvidia-cudnn-cu12)
if (-not $env:WITH_CUDA) { $env:WITH_CUDA = "0" }
$env:ONEFILE = "1"

pyinstaller packaging/transcriber.spec --noconfirm --clean

Compress-Archive -Path dist\MeetingTranscriber.exe `
    -DestinationPath dist\MeetingTranscriber-win64.zip -Force
Write-Host "`nГотово: dist\MeetingTranscriber.exe"
