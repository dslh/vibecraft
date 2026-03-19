#!/bin/sh
# Vibecraft SC2 Bot — one-line setup for macOS and Linux
# Usage: curl -fsSL https://raw.githubusercontent.com/dslh/vibecraft/main/setup.sh | sh
set -e

REPO_URL="https://github.com/dslh/vibecraft.git"
SC2_FORK_URL="https://github.com/dslh/python-sc2.git"
PROTO_URL="https://github.com/Blizzard/s2client-proto.git"
MAP_PACK_URL="https://blzdistsc2-a.akamaihd.net/MapPacks/Melee.zip"
MAP_PACK_PASSWORD="iagreetotheeula"

# --- Helpers ---

info()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33mWarning:\033[0m %s\n' "$*"; }
error() { printf '\033[1;31mError:\033[0m %s\n' "$*"; exit 1; }

check_cmd() {
    command -v "$1" >/dev/null 2>&1
}

# --- Check prerequisites ---

check_cmd git || error "git is not installed. Please install git and try again."

PYTHON=""
for cmd in python3 python; do
    if check_cmd "$cmd"; then
        # Verify it's Python 3.9+
        if "$cmd" -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" 2>/dev/null; then
            PYTHON="$cmd"
            break
        fi
    fi
done
[ -n "$PYTHON" ] || error "Python 3.9+ is required. Please install Python and try again."
info "Using $($PYTHON --version)"

# --- Clone repositories ---

if [ -d "vibecraft" ]; then
    info "vibecraft/ already exists, skipping clone"
else
    info "Cloning vibecraft..."
    git clone "$REPO_URL"
fi
cd vibecraft

if [ -d "python-sc2" ]; then
    info "python-sc2/ already exists, skipping clone"
else
    info "Cloning python-sc2 fork..."
    git clone "$SC2_FORK_URL"
fi

if [ -d "s2client-proto" ]; then
    info "s2client-proto/ already exists, skipping clone"
else
    info "Cloning s2client-proto..."
    git clone "$PROTO_URL"
fi

# --- Set up Python environment ---

if [ -d ".venv" ]; then
    info "Virtual environment already exists"
else
    info "Creating virtual environment..."
    "$PYTHON" -m venv .venv
fi

info "Installing dependencies..."
.venv/bin/pip install -q -r requirements.txt

# --- Locate SC2 installation ---

OS="$(uname -s)"
SC2_PATH=""

if [ -n "$SC2PATH" ]; then
    SC2_PATH="$SC2PATH"
elif [ "$OS" = "Darwin" ]; then
    if [ -d "/Applications/StarCraft II" ]; then
        SC2_PATH="/Applications/StarCraft II"
    fi
else
    # Linux — check common locations
    for candidate in \
        "$HOME/StarCraftII" \
        "$HOME/.steam/steam/steamapps/common/StarCraft II" \
        "$HOME/.local/share/Steam/steamapps/common/StarCraft II"; do
        if [ -d "$candidate" ]; then
            SC2_PATH="$candidate"
            break
        fi
    done
fi

# --- Download and extract map pack ---

if [ -z "$SC2_PATH" ]; then
    warn "Could not find a StarCraft II installation."
    warn "Skipping map pack download."
    warn ""
    warn "Once SC2 is installed, download the Melee map pack manually:"
    warn "  curl -o Melee.zip '$MAP_PACK_URL'"
    warn "  unzip -P $MAP_PACK_PASSWORD Melee.zip -d '<SC2_PATH>/Maps'"
else
    info "Found StarCraft II at: $SC2_PATH"

    # Find or create the Maps directory (case may vary)
    MAPS_DIR=""
    for name in Maps maps; do
        if [ -d "$SC2_PATH/$name" ]; then
            MAPS_DIR="$SC2_PATH/$name"
            break
        fi
    done
    if [ -z "$MAPS_DIR" ]; then
        MAPS_DIR="$SC2_PATH/Maps"
        mkdir -p "$MAPS_DIR"
    fi

    # Check if maps already exist
    if [ -d "$MAPS_DIR/Melee" ] || ls "$MAPS_DIR"/*.SC2Map >/dev/null 2>&1; then
        info "Maps already present in $MAPS_DIR, skipping download"
    else
        info "Downloading Melee map pack..."
        TMPZIP="$(mktemp)"
        trap 'rm -f "$TMPZIP"' EXIT

        if check_cmd curl; then
            curl -fSL -o "$TMPZIP" "$MAP_PACK_URL"
        elif check_cmd wget; then
            wget -q -O "$TMPZIP" "$MAP_PACK_URL"
        else
            warn "Neither curl nor wget found. Skipping map download."
            warn "Download manually: $MAP_PACK_URL"
            TMPZIP=""
        fi

        if [ -n "$TMPZIP" ] && [ -s "$TMPZIP" ]; then
            if check_cmd unzip; then
                info "Extracting maps to $MAPS_DIR..."
                unzip -o -P "$MAP_PACK_PASSWORD" "$TMPZIP" -d "$MAPS_DIR"
            else
                warn "unzip not found. Extract manually:"
                warn "  unzip -P $MAP_PACK_PASSWORD Melee.zip -d '$MAPS_DIR'"
            fi
        fi
    fi
fi

# --- Done ---

printf '\n'
info "Setup complete!"
printf '\n'
printf '  Verify your setup:\n'
printf '    cd vibecraft && .venv/bin/python3 run.py --test\n'
printf '\n'
printf '  Start a game:\n'
printf '    cd vibecraft && .venv/bin/python3 run.py\n'
printf '\n'
