# VOICEVOX Engine を起動 (vendor/voicevox/ から)
# 使い方:  .\scripts\run_voicevox.ps1

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot

$exe = Get-ChildItem -Path (Join-Path $root "vendor\voicevox") -Recurse -Filter "run.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $exe) {
    Write-Host "[error] vendor/voicevox/ に run.exe が見つかりません。.\scripts\setup_voicevox.ps1 を先に実行してください。" -ForegroundColor Red
    exit 1
}

Write-Host "[info] starting VOICEVOX engine: $($exe.FullName)" -ForegroundColor Cyan
& $exe.FullName
