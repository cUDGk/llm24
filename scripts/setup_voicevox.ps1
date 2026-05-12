# VOICEVOX Engine セットアップ (Windows CPU 解凍版)
# 使い方:  .\scripts\setup_voicevox.ps1

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# venv チェック
$venvPy = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Write-Host "[error] .venv が無い。先に `python -m venv .venv` してから `pip install -r requirements.txt` してください。" -ForegroundColor Red
    exit 1
}

& $venvPy "scripts\setup_voicevox.py"
