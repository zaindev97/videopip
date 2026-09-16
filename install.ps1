# VideoPip installer for Windows (PowerShell)
#   irm https://raw.githubusercontent.com/zaindev97/videopip/main/install.ps1 | iex
# Installs Python (if missing, via winget), pipx, videopip with all extras, then runs `videopip setup`.

$ErrorActionPreference = "Stop"

function Has($cmd) { return [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }

Write-Host "==> VideoPip installer" -ForegroundColor Cyan

$py = $null
if (Has "py") { $py = "py" } elseif (Has "python") { $py = "python" }
if (-not $py) {
    if (-not (Has "winget")) { throw "Python 3.10+ is required. Install it from https://www.python.org/downloads/ and re-run." }
    Write-Host "==> Installing Python 3.12 with winget"
    winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
    $py = "py"
}

& $py -c "import sys; assert sys.version_info >= (3, 10), sys.version" 2>$null
if ($LASTEXITCODE -ne 0) { throw "Python 3.10 or newer is required." }

Write-Host "==> Installing pipx"
& $py -m pip install --user --upgrade pipx | Out-Null
& $py -m pipx ensurepath | Out-Null
$env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + $env:Path

Write-Host "==> Installing videopip"
& $py -m pipx install --force "videopip[all]"

if (-not (Has "ffmpeg")) {
    if (Has "winget") {
        Write-Host "==> Installing ffmpeg with winget (full build)"
        winget install -e --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements
        $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
    }
}

Write-Host "==> Running videopip setup"
& $py -m pipx run --spec "videopip[all]" videopip setup --full

Write-Host ""
Write-Host "Done. Open a NEW terminal and try:" -ForegroundColor Green
Write-Host "   videopip demo"
