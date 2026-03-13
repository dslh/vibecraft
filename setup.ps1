# Script d'installation du bot SC2 pour Windows
# Utilisation (une seule commande) :
#   powershell -ExecutionPolicy Bypass -Command "iwr https://raw.githubusercontent.com/dslh/vibecraft/main/setup.ps1 -OutFile setup.ps1; .\setup.ps1; Remove-Item setup.ps1"
#
# Ou si vous avez deja le depot clone :
#   powershell -ExecutionPolicy Bypass -File setup.ps1

$ErrorActionPreference = "Stop"

$installDir = Join-Path $env:USERPROFILE "vibecraft"

function Write-Step { param($msg) Write-Host "`n>> $msg" -ForegroundColor Cyan }
function Write-Ok   { param($msg) Write-Host "   $msg" -ForegroundColor Green }
function Write-Warn { param($msg) Write-Host "   $msg" -ForegroundColor Yellow }
function Write-Err  { param($msg) Write-Host "   $msg" -ForegroundColor Red }

# Telecharge et extrait un fichier zip dans un dossier cible.
# Parametres :
#   $url     - URL du fichier zip
#   $dest    - Dossier de destination pour l'extraction
#   $label   - Nom affiche dans les messages de progression
function Install-MapPack {
    param($url, $dest, $label)
    $zipPath = Join-Path $env:TEMP "SC2_Maps_$label.zip"
    try {
        Write-Host "   $label : telechargement..." -ForegroundColor White
        $ProgressPreference = 'SilentlyContinue'
        Invoke-WebRequest -Uri $url -OutFile $zipPath
        $ProgressPreference = 'Continue'

        Write-Host "   $label : extraction..." -ForegroundColor White
        Expand-Archive -Path $zipPath -DestinationPath $dest -Force
        Remove-Item $zipPath -ErrorAction SilentlyContinue
        Write-Ok "$label : installe."
    } catch {
        Write-Warn "Echec du telechargement de $label : $_"
        Write-Warn "Telechargement manuel : $url"
    }
}

Write-Host ""
Write-Host "=== Installation du bot SC2 ===" -ForegroundColor Magenta
Write-Host ""
Write-Host "   Dossier d'installation : $installDir" -ForegroundColor White

# ---------------------------------------------------------------------------
# 1. Verification des prerequis
# ---------------------------------------------------------------------------

Write-Step "Verification des prerequis..."

# -- Python --
$python = $null
foreach ($cmd in @("python", "python3")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($ver -match "Python (\d+)\.(\d+)") {
            $major = [int]$Matches[1]; $minor = [int]$Matches[2]
            if ($major -ge 3 -and $minor -ge 10) {
                $python = $cmd
                Write-Ok "Python : $ver"
                break
            }
        }
    } catch {}
}
if (-not $python) {
    Write-Err "Python 3.10+ introuvable. Installez-le depuis https://www.python.org/downloads/"
    Write-Err "Pensez a cocher « Add Python to PATH » pendant l'installation."
    exit 1
}

# -- Git --
try {
    $gitVer = & git --version 2>&1
    Write-Ok "Git : $gitVer"
} catch {
    Write-Err "Git introuvable. Installez-le depuis https://git-scm.com/downloads/win"
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
    Write-Ok "StarCraft II : $sc2Path"
} else {
    Write-Warn "StarCraft II introuvable. Installez-le depuis https://battle.net (l'edition Starter gratuite suffit)."
    Write-Warn "Si installe ailleurs, definissez la variable d'environnement SC2PATH."
    Write-Warn "On continue quand meme — vous pourrez installer SC2 plus tard."
    $sc2Path = $null
}

# ---------------------------------------------------------------------------
# 2. Cloner les depots
# ---------------------------------------------------------------------------

# Si le script est lance depuis l'interieur du depot, on utilise ce dossier.
# Sinon, on installe dans $installDir.
$scriptInRepo = Test-Path (Join-Path $PSScriptRoot "run.py")

if ($scriptInRepo) {
    $baseDir = Split-Path $PSScriptRoot -Parent
    $botDir = $PSScriptRoot
    Write-Step "Execution depuis le depot existant : $botDir"
} else {
    $baseDir = $installDir
    $botDir = Join-Path $baseDir "bot"

    Write-Step "Installation du projet dans $baseDir..."

    if (-not (Test-Path $baseDir)) {
        New-Item -ItemType Directory -Path $baseDir | Out-Null
    }

    # -- Depot bot --
    if (Test-Path $botDir) {
        Write-Ok "bot/ existe deja, mise a jour..."
        Push-Location $botDir
        & git pull --ff-only 2>&1 | Out-Null
        Pop-Location
    } else {
        Write-Host "   Clonage du depot bot..." -ForegroundColor White
        & git clone https://github.com/dslh/vibecraft.git $botDir
        if ($LASTEXITCODE -ne 0) { Write-Err "Echec du clonage du depot bot."; exit 1 }
        Write-Ok "Depot bot clone."
    }
}

# -- Depot python-sc2 --
$pySc2Dir = Join-Path $baseDir "python-sc2"
if (Test-Path $pySc2Dir) {
    Write-Ok "python-sc2/ existe deja, mise a jour..."
    Push-Location $pySc2Dir
    & git pull --ff-only 2>&1 | Out-Null
    Pop-Location
} else {
    Write-Host "   Clonage de python-sc2..." -ForegroundColor White
    & git clone https://github.com/dslh/python-sc2.git $pySc2Dir
    if ($LASTEXITCODE -ne 0) { Write-Err "Echec du clonage de python-sc2."; exit 1 }
    Write-Ok "python-sc2 clone."
}

# ---------------------------------------------------------------------------
# 3. Creer le venv et installer les dependances
# ---------------------------------------------------------------------------

Write-Step "Configuration de l'environnement virtuel Python..."

$venvDir = Join-Path $botDir ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"
$venvPip = Join-Path $venvDir "Scripts\pip.exe"

if (-not (Test-Path $venvPython)) {
    & $python -m venv $venvDir
    if ($LASTEXITCODE -ne 0) { Write-Err "Echec de la creation du venv."; exit 1 }
    Write-Ok "Venv cree."
} else {
    Write-Ok "Le venv existe deja."
}

Write-Host "   Installation de python-sc2 (mode editable)..." -ForegroundColor White
& $venvPip install -e $pySc2Dir 2>&1 | Select-Object -Last 3
if ($LASTEXITCODE -ne 0) { Write-Err "Echec de l'installation de python-sc2."; exit 1 }

Write-Host "   Installation des dependances du chat..." -ForegroundColor White
& $venvPip install claude-agent-sdk mcp rich prompt_toolkit 2>&1 | Select-Object -Last 3
if ($LASTEXITCODE -ne 0) {
    Write-Warn "Echec de l'installation des dependances du chat (optionnel — le bot fonctionne quand meme)."
}

Write-Ok "Dependances installees."

# ---------------------------------------------------------------------------
# 4. Installer les cartes
# ---------------------------------------------------------------------------

Write-Step "Installation des cartes..."

if ($sc2Path) {
    $mapsDir = Join-Path $sc2Path "Maps"
    if (-not (Test-Path $mapsDir)) {
        New-Item -ItemType Directory -Path $mapsDir | Out-Null
    }

    # Pack Melee de Blizzard (Simple64, Flat48, etc.)
    $simple64 = Get-ChildItem -Path $mapsDir -Filter "Simple64.SC2Map" -Recurse -ErrorAction SilentlyContinue
    if ($simple64) {
        Write-Ok "Pack Melee deja present."
    } else {
        Install-MapPack "https://blzdistsc2-a.akamaihd.net/MapPacks/Melee.zip" $mapsDir "Pack Melee (Blizzard)"
    }

    # Packs AI Arena — cartes competitives recentes
    Install-MapPack "https://aiarena.net/wiki/184/plugin/attachments/download/45/" $mapsDir "AI Arena 2025 PreSeason 2"
    Install-MapPack "https://aiarena.net/wiki/184/plugin/attachments/download/41/" $mapsDir "AI Arena 2024 Season 4"

    $mapCount = (Get-ChildItem -Path $mapsDir -Filter "*.SC2Map" -Recurse).Count
    Write-Ok "$mapCount cartes installees au total."
} else {
    Write-Warn "Installation des cartes ignoree (SC2 introuvable)."
    Write-Warn "Apres avoir installe SC2, relancez ce script ou telechargez les cartes manuellement :"
    Write-Warn "  Melee : https://blzdistsc2-a.akamaihd.net/MapPacks/Melee.zip"
    Write-Warn "  AI Arena : https://aiarena.net/wiki/maps/"
    Write-Warn "Extrayez les fichiers .SC2Map dans : <dossier SC2>\Maps\"
}

# ---------------------------------------------------------------------------
# 5. Verification
# ---------------------------------------------------------------------------

Write-Step "Verification de l'installation..."

$testScript = @"
import sys
try:
    import sc2
    from sc2.bot_ai import BotAI
    from sc2.ids.unit_typeid import UnitTypeId
    from sc2.ids.ability_id import AbilityId
    print('python-sc2 : OK')
except Exception as e:
    print(f'python-sc2 : ECHEC - {e}')
    sys.exit(1)

try:
    from bot_src.bot import BotAI as UserBot
    print('bot_src : OK')
except Exception as e:
    print(f'bot_src : ECHEC - {e}')
    sys.exit(1)

print('Tous les imports OK')
"@

Push-Location $botDir
$result = & $venvPython -c $testScript 2>&1
$exitCode = $LASTEXITCODE
Pop-Location

foreach ($line in $result) {
    if ($exitCode -eq 0) { Write-Ok $line } else { Write-Err $line }
}

if ($exitCode -ne 0) {
    Write-Err "La verification a echoue. Consultez les erreurs ci-dessus."
    exit 1
}

# ---------------------------------------------------------------------------
# Termine !
# ---------------------------------------------------------------------------

Write-Host ""
Write-Host "=== Installation terminee ! ===" -ForegroundColor Magenta
Write-Host ""
Write-Host "Pour lancer une partie :" -ForegroundColor White
Write-Host "   cd $botDir" -ForegroundColor Yellow
Write-Host "   .venv\Scripts\python run.py --map Simple64 --race terran --difficulty medium" -ForegroundColor Yellow
Write-Host ""
Write-Host "Pour lancer l'interface chat (necessite une cle API Anthropic) :" -ForegroundColor White
Write-Host "   .venv\Scripts\python chat.py" -ForegroundColor Yellow
Write-Host ""
Write-Host "Modifiez les fichiers dans bot_src\ pendant la partie — les changements" -ForegroundColor White
Write-Host "sont recharges automatiquement au prochain tick." -ForegroundColor White
Write-Host ""
