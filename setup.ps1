# Vibecraft SC2 Bot — one-line setup for Windows
# Usage: irm https://raw.githubusercontent.com/dslh/vibecraft/main/setup.ps1 | iex
$ErrorActionPreference = "Stop"

$RepoUrl      = "https://github.com/dslh/vibecraft.git"
$SC2ForkUrl   = "https://github.com/dslh/python-sc2.git"
$ProtoUrl     = "https://github.com/Blizzard/s2client-proto.git"
$MapPackUrl   = "https://blzdistsc2-a.akamaihd.net/MapPacks/Melee.zip"
$MapPackPassword = "iagreetotheeula"

# --- Helpers ---

function Info($msg)  { Write-Host "==> $msg" -ForegroundColor Cyan }
function Warn($msg)  { Write-Host "Warning: $msg" -ForegroundColor Yellow }

function FindPython {
    foreach ($cmd in @("python3", "python", "py")) {
        try {
            $version = & $cmd --version 2>&1
            if ($version -match "Python (\d+)\.(\d+)") {
                $major = [int]$Matches[1]
                $minor = [int]$Matches[2]
                if ($major -ge 3 -and $minor -ge 9) {
                    return $cmd
                }
            }
        } catch {}
    }
    return $null
}

# --- Check prerequisites ---

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "Error: git is not installed. Please install git and try again." -ForegroundColor Red
    exit 1
}

$Python = FindPython
if (-not $Python) {
    Write-Host "Error: Python 3.9+ is required. Please install Python and try again." -ForegroundColor Red
    exit 1
}
Info "Using $(& $Python --version 2>&1)"

# --- Clone repositories ---

if (Test-Path "vibecraft") {
    Info "vibecraft/ already exists, skipping clone"
} else {
    Info "Cloning vibecraft..."
    git clone $RepoUrl
}
Set-Location vibecraft

if (Test-Path "python-sc2") {
    Info "python-sc2/ already exists, skipping clone"
} else {
    Info "Cloning python-sc2 fork..."
    git clone $SC2ForkUrl
}

if (Test-Path "s2client-proto") {
    Info "s2client-proto/ already exists, skipping clone"
} else {
    Info "Cloning s2client-proto..."
    git clone $ProtoUrl
}

# --- Set up Python environment ---

if (Test-Path ".venv") {
    Info "Virtual environment already exists"
} else {
    Info "Creating virtual environment..."
    & $Python -m venv .venv
}

Info "Installing dependencies..."
& .venv\Scripts\pip install -q -r requirements.txt

# --- Locate SC2 installation ---

$SC2Path = $null

if ($env:SC2PATH) {
    $SC2Path = $env:SC2PATH
} else {
    $candidates = @(
        "C:\Program Files (x86)\StarCraft II",
        "C:\Program Files\StarCraft II",
        "D:\Program Files (x86)\StarCraft II",
        "D:\StarCraft II"
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            $SC2Path = $candidate
            break
        }
    }
}

# --- Download and extract map pack ---

if (-not $SC2Path) {
    Warn "Could not find a StarCraft II installation."
    Warn "Skipping map pack download."
    Warn ""
    Warn "Once SC2 is installed, you can download the Melee map pack manually."
    Warn "See the README for details."
} else {
    Info "Found StarCraft II at: $SC2Path"

    $MapsDir = $null
    foreach ($name in @("Maps", "maps")) {
        $candidate = Join-Path $SC2Path $name
        if (Test-Path $candidate) {
            $MapsDir = $candidate
            break
        }
    }
    if (-not $MapsDir) {
        $MapsDir = Join-Path $SC2Path "Maps"
        New-Item -ItemType Directory -Path $MapsDir -Force | Out-Null
    }

    # Check if maps already exist
    $hasMapFiles = (Get-ChildItem -Path $MapsDir -Filter "*.SC2Map" -ErrorAction SilentlyContinue).Count -gt 0
    $hasMeleeDir = Test-Path (Join-Path $MapsDir "Melee")

    if ($hasMapFiles -or $hasMeleeDir) {
        Info "Maps already present in $MapsDir, skipping download"
    } else {
        Info "Downloading Melee map pack..."
        $TmpZip = Join-Path $env:TEMP "Melee_$(Get-Random).zip"

        try {
            Invoke-WebRequest -Uri $MapPackUrl -OutFile $TmpZip -UseBasicParsing

            Info "Extracting maps to $MapsDir..."
            # PowerShell can't extract password-protected zips natively, so use Python
            & .venv\Scripts\python -c @"
import zipfile, sys
with zipfile.ZipFile(sys.argv[1]) as zf:
    zf.extractall(sys.argv[2], pwd=sys.argv[3].encode())
"@ $TmpZip $MapsDir $MapPackPassword

        } catch {
            Warn "Failed to download or extract map pack: $_"
            Warn "You can download it manually from:"
            Warn "  $MapPackUrl"
        } finally {
            if (Test-Path $TmpZip) { Remove-Item $TmpZip -Force }
        }
    }
}

# --- Done ---

Write-Host ""
Info "Setup complete!"
Write-Host ""
Write-Host "  Verify your setup:"
Write-Host "    cd vibecraft; .venv\Scripts\python run.py --test"
Write-Host ""
Write-Host "  Start a game:"
Write-Host "    cd vibecraft; .venv\Scripts\python run.py"
Write-Host ""
