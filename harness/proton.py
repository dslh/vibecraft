"""Proton auto-detection and SC2 launch configuration for Linux/Steam Deck."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

SC2_STEAM_APP_ID = "418530"

# Common Steam install locations on Linux
STEAM_SEARCH_PATHS = [
    Path.home() / ".steam" / "steam",
    Path.home() / ".local" / "share" / "Steam",
]


def find_steam_root() -> Path | None:
    """Auto-detect the Steam installation root."""
    for p in STEAM_SEARCH_PATHS:
        if (p / "steamapps").is_dir():
            return p
    return None


def find_sc2_in_steam(steam_root: Path) -> Path | None:
    """Find SC2 install within Steam's library folders."""
    # Check the default steamapps first
    sc2 = steam_root / "steamapps" / "common" / "StarCraft II"
    if sc2.is_dir():
        return sc2
    # Check additional library folders defined in libraryfolders.vdf
    vdf = steam_root / "steamapps" / "libraryfolders.vdf"
    if vdf.is_file():
        for match in re.finditer(r'"path"\s+"([^"]+)"', vdf.read_text()):
            sc2 = Path(match.group(1)) / "steamapps" / "common" / "StarCraft II"
            if sc2.is_dir():
                return sc2
    return None


def find_latest_proton(steam_root: Path) -> Path | None:
    """Find the latest Proton installation in Steam's common apps."""
    common = steam_root / "steamapps" / "common"
    if not common.is_dir():
        return None
    proton_dirs = sorted(
        (p for p in common.iterdir() if p.is_dir() and p.name.startswith("Proton ")),
        key=lambda p: p.name,
        reverse=True,
    )
    for d in proton_dirs:
        if (d / "proton").is_file():
            return d
    return None


def setup_proton(args):
    """Configure SC2 launch through Proton. Must be called before sc2.paths
    is imported (i.e. before importing sc2.main or sc2.maps)."""
    # 1. Find Steam
    steam_root = Path(args.steam_path) if args.steam_path else find_steam_root()
    if not steam_root or not steam_root.is_dir():
        print("[proton] ERROR: Could not find Steam installation.")
        print("[proton] Try: --steam-path /path/to/steam")
        sys.exit(1)

    # 2. Find SC2
    sc2_path = Path(args.sc2_path) if args.sc2_path else find_sc2_in_steam(steam_root)
    if not sc2_path or not sc2_path.is_dir():
        print("[proton] ERROR: Could not find StarCraft II installation in Steam library.")
        print("[proton] Try: --sc2-path /path/to/StarCraft\\ II")
        sys.exit(1)

    # 3. Find Proton
    if args.proton_version:
        proton_dir = steam_root / "steamapps" / "common" / args.proton_version
    else:
        proton_dir = find_latest_proton(steam_root)
    if not proton_dir or not (proton_dir / "proton").is_file():
        print("[proton] ERROR: Could not find Proton installation.")
        print('[proton] Try: --proton-version "Proton 10.0"')
        sys.exit(1)

    # 4. Compatdata prefix (created by Steam on first SC2 launch)
    compat_data = steam_root / "steamapps" / "compatdata" / SC2_STEAM_APP_ID
    if not compat_data.is_dir():
        print(f"[proton] ERROR: Compatdata prefix not found at {compat_data}")
        print("[proton] Has SC2 been launched through Steam at least once?")
        sys.exit(1)

    # 5. Configure sc2.paths for Proton platform
    os.environ["SC2PF"] = "Proton"
    os.environ["SC2PATH"] = str(sc2_path)

    # Populate proton_config — sc2.paths reads this when building launch args
    from sc2.paths import proton_config
    proton_config["proton_path"] = str(proton_dir / "proton")
    proton_config["compat_data"] = str(compat_data)
    proton_config["steam_path"] = str(steam_root)

    print(f"[proton] Steam:  {steam_root}")
    print(f"[proton] SC2:    {sc2_path}")
    print(f"[proton] Proton: {proton_dir.name}")
    print()
