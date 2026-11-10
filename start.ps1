param([int]$Port = 8000)
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
Write-Host "R34 Observatory: http://127.0.0.1:$Port"
& $r34Python -m uvicorn backend.app:app --host 127.0.0.1 --port $Port
