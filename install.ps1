param([string]$Destination = (Join-Path (Get-Location) 'thinknova-toolkit'))
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
function Refresh-ToolPath {
    $env:Path = $env:Path + ';' + [Environment]::GetEnvironmentVariable('Path','User') + ';' + [Environment]::GetEnvironmentVariable('Path','Machine')
}
function Install-ToolDependency([string]$Package) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { throw "DEPENDENCY_REPAIR_UNAVAILABLE: winget missing; cannot install $Package automatically." }
    & winget install --exact --id $Package --silent --accept-package-agreements --accept-source-agreements --disable-interactivity
    if ($LASTEXITCODE -ne 0) { throw "DEPENDENCY_REPAIR_FAILED: $Package, exit $LASTEXITCODE. Check network and installation permissions." }
    Refresh-ToolPath
}
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Install-ToolDependency 'Git.Git' }
$python = $null
$candidates = @()
if (Get-Command py -ErrorAction SilentlyContinue) {
    $candidates += (& py -3 -c 'import sys; print(sys.executable)' 2>$null)
}
if (Get-Command python -ErrorAction SilentlyContinue) { $candidates += (Get-Command python).Source }
foreach ($candidate in $candidates) {
    & $candidate -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)'
    if ($LASTEXITCODE -eq 0) { $python = $candidate; break }
}
if (-not $python) {
    Install-ToolDependency 'Python.Python.3.12'
    $python = Join-Path $env:LOCALAPPDATA 'Programs/Python/Python312/python.exe'
    if (-not (Test-Path -LiteralPath $python)) { throw 'PYTHON_REPAIR_NOT_EFFECTIVE: Python installer completed but interpreter was not found.' }
}
$repository = 'https://github.com/yaoyingyunlian-create/thinknova-mcp.git'
if (-not (Test-Path -LiteralPath $Destination)) {
    & git -c core.autocrlf=false clone $repository $Destination
    if ($LASTEXITCODE -ne 0) { throw 'TOOLKIT_CLONE_FAILED: verify GitHub network access.' }
} else {
    $remote = & git -C $Destination remote get-url origin
    if ($LASTEXITCODE -ne 0 -or $remote -ne $repository) { throw 'DESTINATION_CONFLICT: existing directory is not the expected toolkit; preserved without changes.' }
}
& $python (Join-Path $Destination 'bootstrap.py') setup
if ($LASTEXITCODE -ne 0) { throw "TOOLKIT_SETUP_FAILED: exit $LASTEXITCODE. See the specific dependency error above." }
