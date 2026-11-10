param([int]$Port = 8000, [switch]$SkipUpdate)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONUTF8 = '1'
if (Test-Path -LiteralPath "$PSScriptRoot/.venv/Scripts/python.exe") {
    $r34Python = "$PSScriptRoot/.venv/Scripts/python.exe"
} elseif (Test-Path -LiteralPath "$PSScriptRoot/.runtime/fastapi") {
    $env:PYTHONPATH = "$PSScriptRoot/.runtime"
    $r34Python = 'python'
} else {
    Write-Host 'First run: python -m venv .venv'
    Write-Host 'Then: ./.venv/Scripts/python -m pip install -r requirements.txt'
    exit 1
}
if (-not $SkipUpdate) {
    & $r34Python -m backend.batch --output dist
    if ($LASTEXITCODE -ne 0) {
        if (-not (Test-Path -LiteralPath "$PSScriptRoot/dist/index.html")) { exit 1 }
        Write-Warning 'Update failed; serving the previous batch. Check its timestamp.'
    }
}
if (-not (Test-Path -LiteralPath "$PSScriptRoot/dist/index.html")) {
    throw 'No batch output exists. Run without -SkipUpdate first.'
}
Write-Host "R34 Observatory: http://127.0.0.1:$Port"
& $r34Python -m http.server $Port --bind 127.0.0.1 --directory "$PSScriptRoot/dist"
