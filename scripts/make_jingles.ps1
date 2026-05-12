# 簡易ジングル素材を ffmpeg で生成して assets/ に置く。
# あとでフリー素材に差し替え可能。
#
# 使い方: .\scripts\make_jingles.ps1

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$assets = Join-Path $root "assets"
New-Item -ItemType Directory -Force -Path $assets | Out-Null

$ffmpeg = $env:FFMPEG_BIN
if (-not $ffmpeg) { $ffmpeg = "ffmpeg" }

function Tone([string]$expr, [double]$dur, [string]$out) {
    # sine音生成 (モノラル→ステレオ化、軽くフェードあり)
    & $ffmpeg -y -loglevel error -f lavfi `
        -i "sine=$expr`:duration=$dur" `
        -af "afade=t=in:st=0:d=0.02,afade=t=out:st=$([math]::Round($dur - 0.05, 3)):d=0.05,volume=0.6" `
        -ac 2 -ar 44100 $out
    if ($LASTEXITCODE -ne 0) { throw "tone gen failed: $out" }
}

function Silence([double]$dur, [string]$out) {
    & $ffmpeg -y -loglevel error -f lavfi `
        -i "anullsrc=channel_layout=stereo:sample_rate=44100" `
        -t $dur $out
    if ($LASTEXITCODE -ne 0) { throw "silence gen failed: $out" }
}

function Concat([string[]]$inputs, [string]$out) {
    $listFile = [System.IO.Path]::GetTempFileName()
    $lines = $inputs | ForEach-Object { "file '$_'" }
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllLines($listFile, $lines, $utf8NoBom)
    & $ffmpeg -y -loglevel error -f concat -safe 0 -i $listFile -c copy $out
    Remove-Item $listFile -Force
    if ($LASTEXITCODE -ne 0) { throw "concat failed: $out" }
}

$tmp = Join-Path $env:TEMP "llm24_jingle"
New-Item -ItemType Directory -Force -Path $tmp | Out-Null

Write-Host "[time] ピンポンパンポン的な時報ジングル生成..." -ForegroundColor Cyan
# E5 (659.25) -> D5 (587.33) -> E5 -> A4 (440) のような4音 (NHK風寄せ)
Tone "frequency=1318.5" 0.45 (Join-Path $tmp "t1.wav")
Silence 0.05 (Join-Path $tmp "s1.wav")
Tone "frequency=987.77" 0.45 (Join-Path $tmp "t2.wav")
Silence 0.05 (Join-Path $tmp "s2.wav")
Tone "frequency=1318.5" 0.45 (Join-Path $tmp "t3.wav")
Silence 0.05 (Join-Path $tmp "s3.wav")
Tone "frequency=659.26" 0.9 (Join-Path $tmp "t4.wav")
Concat @(
    (Join-Path $tmp "t1.wav"),
    (Join-Path $tmp "s1.wav"),
    (Join-Path $tmp "t2.wav"),
    (Join-Path $tmp "s2.wav"),
    (Join-Path $tmp "t3.wav"),
    (Join-Path $tmp "s3.wav"),
    (Join-Path $tmp "t4.wav")
) (Join-Path $assets "jingle_time.wav")

Write-Host "[mail] お便りコーナージングル生成..." -ForegroundColor Cyan
# 明るい和音 C5 + E5 + G5 を 1.5秒、フェードあり (aevalsrc 単一ソースで和音合成)
$mailOut = Join-Path $assets "jingle_mail.wav"
$chord = "aevalsrc=0.25*sin(523.25*2*PI*t)+0.25*sin(659.26*2*PI*t)+0.25*sin(783.99*2*PI*t):duration=1.5:s=44100"
& $ffmpeg -y -loglevel error -f lavfi -i $chord -af "afade=t=in:st=0:d=0.05,afade=t=out:st=1.3:d=0.2" -ac 2 -ar 44100 $mailOut
if ($LASTEXITCODE -ne 0) { throw "mail jingle failed" }

Write-Host "[station] 番組IDジングル生成 (短いベル風)..." -ForegroundColor Cyan
Tone "frequency=880" 0.3 (Join-Path $tmp "b1.wav")
Silence 0.1 (Join-Path $tmp "bs.wav")
Tone "frequency=1318.5" 0.6 (Join-Path $tmp "b2.wav")
Concat @(
    (Join-Path $tmp "b1.wav"),
    (Join-Path $tmp "bs.wav"),
    (Join-Path $tmp "b2.wav")
) (Join-Path $assets "jingle_station.wav")

Remove-Item -Recurse -Force $tmp

Write-Host "[done] assets/ にジングル3点を生成しました:" -ForegroundColor Green
Get-ChildItem $assets -Filter "*.wav" | Format-Table Name, Length
