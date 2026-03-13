# SC2 Bot Setup Script for Windows
# Usage (one-liner):
#   powershell -ExecutionPolicy Bypass -Command "iwr https://raw.githubusercontent.com/dslh/vibecraft/main/setup.ps1 -OutFile setup.ps1; .\setup.ps1; Remove-Item setup.ps1"
#
# Or if you already have the repo cloned:
#   powershell -ExecutionPolicy Bypass -File setup.ps1

$ErrorActionPreference = "Stop"

function Write-Step { param($msg) Write-Host "`n>> $msg" -ForegroundColor Cyan }
function Write-Ok   { param($msg) Write-Host "   $msg" -ForegroundColor Green }
function Write-Warn { param($msg) Write-Host "   $msg" -ForegroundColor Yellow }
function Write-Err  { param($msg) Write-Host "   $msg" -ForegroundColor Red }

Write-Host ""
Write-Host "=== SC2 Bot Setup ===" -ForegroundColor Magenta
Write-Host ""

# ---------------------------------------------------------------------------
# 1. Check prerequisites
# ---------------------------------------------------------------------------

Write-Step "Checking prerequisites..."

# -- Python --
$python = $null
foreach ($cmd in @("python", "python3")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($ver -match "Python (\d+)\.(\d+)") {
            $major = [int]$Matches[1]; $minor = [int]$Matches[2]
            if ($major -ge 3 -and $minor -ge 10) {
                $python = $cmd
                Write-Ok "Python: $ver"
                break
            }
        }
    } catch {}
}
if (-not $python) {
    Write-Err "Python 3.10+ not found. Install from https://www.python.org/downloads/"
    Write-Err "Make sure to check 'Add Python to PATH' during installation."
    exit 1
}

# -- Git --
try {
    $gitVer = & git --version 2>&1
    Write-Ok "Git: $gitVer"
} catch {
    Write-Err "Git not found. Install from https://git-scm.com/downloads/win"
    exit 1
}

# -- StarCraft II --
$sc2Path = $env:SC2PATH
if (-not $sc2Path) {
    $defaultPaths = @(
        "${env:ProgramFiles(x86)}\StarCraft II",
        "$env:ProgramFiles\StarCraft II",
        "C:\Program Files (x86)\StarCraft II",
        "C:\Program Files\StarCraft II"
    )
    foreach ($p in $defaultPaths) {
        if (Test-Path $p) { $sc2Path = $p; break }
    }
}

if ($sc2Path -and (Test-Path $sc2Path)) {
    Write-Ok "StarCraft II: $sc2Path"
} else {
    Write-Warn "StarCraft II not found. Install from https://battle.net (free Starter Edition works)."
    Write-Warn "If installed in a non-default location, set SC2PATH environment variable."
    Write-Warn "Continuing setup anyway — you can install SC2 later."
    $sc2Path = $null
}

# ---------------------------------------------------------------------------
# 2. Determine working directory
# ---------------------------------------------------------------------------

# If we're already inside the bot repo (e.g. user cloned and ran setup.ps1),
# work from the parent directory. Otherwise, create an sc2/ directory here.
$scriptInRepo = Test-Path (Join-Path $PSScriptRoot "run.py")

if ($scriptInRepo) {
    $baseDir = Split-Path $PSScriptRoot -Parent
    $botDir = $PSScriptRoot
    Write-Step "Running from inside the repo: $botDir"
} else {
    $baseDir = Join-Path (Get-Location) "sc2"
    $botDir = Join-Path $baseDir "bot"

    Write-Step "Setting up project in $baseDir..."

    if (-not (Test-Path $baseDir)) {
        New-Item -ItemType Directory -Path $baseDir | Out-Null
    }

    # -- Clone bot repo --
    if (Test-Path $botDir) {
        Write-Ok "bot/ already exists, pulling latest..."
        Push-Location $botDir
        & git pull --ff-only 2>&1 | Out-Null
        Pop-Location
    } else {
        Write-Host "   Cloning bot repo..." -ForegroundColor White
        & git clone https://github.com/dslh/vibecraft.git $botDir
        if ($LASTEXITCODE -ne 0) { Write-Err "Failed to clone bot repo."; exit 1 }
        Write-Ok "Cloned bot repo."
    }
}

# -- Clone python-sc2 --
$pySc2Dir = Join-Path $baseDir "python-sc2"
if (Test-Path $pySc2Dir) {
    Write-Ok "python-sc2/ already exists, pulling latest..."
    Push-Location $pySc2Dir
    & git pull --ff-only 2>&1 | Out-Null
    Pop-Location
} else {
    Write-Host "   Cloning python-sc2..." -ForegroundColor White
    & git clone https://github.com/dslh/python-sc2.git $pySc2Dir
    if ($LASTEXITCODE -ne 0) { Write-Err "Failed to clone python-sc2 repo."; exit 1 }
    Write-Ok "Cloned python-sc2."
}

# ---------------------------------------------------------------------------
# 3. Create venv and install dependencies
# ---------------------------------------------------------------------------

Write-Step "Setting up Python virtual environment..."

$venvDir = Join-Path $botDir ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"
$venvPip = Join-Path $venvDir "Scripts\pip.exe"

if (-not (Test-Path $venvPython)) {
    & $python -m venv $venvDir
    if ($LASTEXITCODE -ne 0) { Write-Err "Failed to create venv."; exit 1 }
    Write-Ok "Created venv."
} else {
    Write-Ok "Venv already exists."
}

Write-Host "   Installing python-sc2 (editable)..." -ForegroundColor White
& $venvPip install -e $pySc2Dir 2>&1 | Select-Object -Last 3
if ($LASTEXITCODE -ne 0) { Write-Err "Failed to install python-sc2."; exit 1 }

Write-Host "   Installing chat dependencies..." -ForegroundColor White
& $venvPip install claude-agent-sdk mcp rich prompt_toolkit 2>&1 | Select-Object -Last 3
if ($LASTEXITCODE -ne 0) {
    Write-Warn "Chat dependencies failed to install (optional — bot still works)."
}

Write-Ok "Dependencies installed."

# ---------------------------------------------------------------------------
# 4. Install maps
# ---------------------------------------------------------------------------

Write-Step "Checking maps..."

$mapsDir = $null
if ($sc2Path) {
    $mapsDir = Join-Path $sc2Path "Maps"
    if (-not (Test-Path $mapsDir)) {
        New-Item -ItemType Directory -Path $mapsDir | Out-Null
    }

    # Check if Simple64 exists anywhere under Maps/
    $simple64 = Get-ChildItem -Path $mapsDir -Filter "Simple64.SC2Map" -Recurse -ErrorAction SilentlyContinue
    if ($simple64) {
        Write-Ok "Maps already installed ($($simple64.Count) Simple64.SC2Map found)."
    } else {
        Write-Host "   Downloading Melee map pack..." -ForegroundColor White
        $zipPath = Join-Path $env:TEMP "SC2_Melee_Maps.zip"

        try {
            $ProgressPreference = 'SilentlyContinue'
            Invoke-WebRequest -Uri "https://blzdistsc2-a.akamaihd.net/MapPacks/Melee.zip" -OutFile $zipPath
            $ProgressPreference = 'Continue'

            Write-Host "   Extracting maps to $mapsDir..." -ForegroundColor White
            Expand-Archive -Path $zipPath -DestinationPath $mapsDir -Force
            Remove-Item $zipPath -ErrorAction SilentlyContinue

            $mapCount = (Get-ChildItem -Path $mapsDir -Filter "*.SC2Map" -Recurse).Count
            Write-Ok "Installed $mapCount maps."
        } catch {
            Write-Warn "Failed to download maps: $_"
            Write-Warn "You can manually download from: https://blzdistsc2-a.akamaihd.net/MapPacks/Melee.zip"
            Write-Warn "Extract .SC2Map files into: $mapsDir"
        }
    }
} else {
    Write-Warn "Skipping map installation (SC2 not found)."
    Write-Warn "After installing SC2, download maps from:"
    Write-Warn "  https://blzdistsc2-a.akamaihd.net/MapPacks/Melee.zip"
    Write-Warn "Extract into: <SC2 install dir>\Maps\"
}

# ---------------------------------------------------------------------------
# 5. Verify
# ---------------------------------------------------------------------------

Write-Step "Verifying installation..."

$testScript = @"
import sys
try:
    import sc2
    from sc2.bot_ai import BotAI
    from sc2.ids.unit_typeid import UnitTypeId
    from sc2.ids.ability_id import AbilityId
    print('python-sc2: OK')
except Exception as e:
    print(f'python-sc2: FAILED - {e}')
    sys.exit(1)

try:
    from bot_src.bot import BotAI as UserBot
    print('bot_src: OK')
except Exception as e:
    print(f'bot_src: FAILED - {e}')
    sys.exit(1)

print('All imports OK')
"@

Push-Location $botDir
$result = & $venvPython -c $testScript 2>&1
$exitCode = $LASTEXITCODE
Pop-Location

foreach ($line in $result) {
    if ($exitCode -eq 0) { Write-Ok $line } else { Write-Err $line }
}

if ($exitCode -ne 0) {
    Write-Err "Verification failed. Check the errors above."
    exit 1
}

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------

Write-Host ""
Write-Host "=== Setup complete! ===" -ForegroundColor Magenta
Write-Host ""
Write-Host "To start a game:" -ForegroundColor White
if (-not $scriptInRepo) {
    Write-Host "   cd sc2\bot" -ForegroundColor Yellow
}
Write-Host "   .venv\Scripts\python run.py --map Simple64 --race terran --difficulty medium" -ForegroundColor Yellow
Write-Host ""
Write-Host "To start the chat interface (needs Anthropic API key):" -ForegroundColor White
Write-Host "   .venv\Scripts\python chat.py" -ForegroundColor Yellow
Write-Host ""
Write-Host "Edit files in bot_src\ while the game runs — changes hot-reload on the next tick." -ForegroundColor White
Write-Host ""
