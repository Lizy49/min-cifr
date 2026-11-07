$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create Python virtual environment.' }
}
& '.venv/Scripts/python.exe' -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& '.venv/Scripts/python.exe' run.py --open-browser
if ($LASTEXITCODE -ne 0) { throw 'Application failed. Check console output and write access to data.' }
