param(
    [string]$Python = "",
    [string]$BundleModel = ""
)
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location -LiteralPath $root
if (-not $Python) {
    $Python = Join-Path $root ".venv\Scripts\python.exe"
}
if (-not (Test-Path -LiteralPath $Python)) {
    throw "Create the Python 3.11+ virtual environment described in README.md first."
}
& $Python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Tests failed. Build cancelled." }
& $Python -m ruff check app.py src tests scripts
if ($LASTEXITCODE -ne 0) { throw "Code checks failed. Build cancelled." }
$buildArgs = @((Join-Path $root "scripts\build.py"))
if ($BundleModel) { $buildArgs += @("--bundle-model", $BundleModel) }
& $Python @buildArgs
if ($LASTEXITCODE -ne 0) { throw "Executable build failed." }
Write-Host "Ready: $root\dist\AI Audio Sentence Splitter\AI Audio Sentence Splitter.exe"
Write-Host "Distribute the entire application folder, not just the .exe."
