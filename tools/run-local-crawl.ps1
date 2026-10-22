# Run an isolated ProcureFlow diagnostic locally after setup-local-crawler.ps1.
param(
    [ValidateSet("wishket","freemoa","wanted")]
    [string]$Site = "wishket",
    [ValidateSet("projects","partners","portfolios")]
    [string]$Section = "projects",
    [ValidateRange(1,10)]
    [int]$Limit = 4
)
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Run tools\setup-local-crawler.ps1 first." }
Push-Location $root
try {
    & $python tools\crawl_probe.py --site $Site --section $Section --limit $Limit --output ("artifacts\local-" + $Site + "-" + $Section)
    if ($LASTEXITCODE -ne 0) { throw "Crawl probe failed" }
    Write-Host ("Evidence: " + (Join-Path $root ("artifacts\local-" + $Site + "-" + $Section + "\result.json")))
} finally {
    Pop-Location
}
