# Run once on Windows in PowerShell. Does not modify existing ProcureFlow directories.
param(
    [string]$InstallPath = "$env:USERPROFILE\ProcureFlowCrawler"
)
$ErrorActionPreference = "Stop"
$repo = "https://github.com/lyonbegin/procureflow.git"

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git is required. Install with: winget install --id Git.Git -e"
}
if ((Get-Command py -ErrorAction SilentlyContinue)) {
    $pyCommand = "py"
    $pyFlags = @("-3")
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $pyCommand = "python"
    $pyFlags = @()
} else {
    throw "Python 3.11+ is required. Install with: winget install --id Python.Python.3.12 -e"
}

if (-not (Test-Path $InstallPath)) {
    git clone --depth 1 --branch main $repo $InstallPath
    if ($LASTEXITCODE -ne 0) { throw "Git clone failed" }
} elseif (-not (Test-Path (Join-Path $InstallPath "tools\crawl_probe.py"))) {
    throw "The chosen folder exists but is not ProcureFlowCrawler. Use a new InstallPath."
}
$venv = Join-Path $InstallPath ".venv"
if (-not (Test-Path (Join-Path $venv "Scripts\python.exe"))) {
    & $pyCommand @pyFlags -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw "Python virtual environment failed" }
}
$python = Join-Path $venv "Scripts\python.exe"
& $python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed" }
& $python -m pip install playwright==1.56.0
if ($LASTEXITCODE -ne 0) { throw "Playwright installation failed" }
& $python -m playwright install chromium
if ($LASTEXITCODE -ne 0) { throw "Chromium installation failed" }
Push-Location $InstallPath
try {
    & $python -m unittest discover -s tests -p "test_crawl_probe.py" -v
    if ($LASTEXITCODE -ne 0) { throw "Crawler unit tests failed" }
} finally {
    Pop-Location
}
Write-Host "Crawler environment ready: $InstallPath"
Write-Host ('Run: powershell -ExecutionPolicy Bypass -File "' + $InstallPath + '\tools\run-local-crawl.ps1" -Site wishket -Section projects')
