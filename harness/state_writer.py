"""
State file writer for SC2 Bot Harness.

Writes game state to bot/log/ so that external tools (like Claude Code)
can read it to understand the live game. Files:

  log/game.txt      — static game metadata, written once at start
  log/snapshot.txt  — current game state, rewritten every ~2s
  log/events.log    — append-only event stream for the whole game
  log/errors.log    — append-only full tracebacks
"""

from __future__ import annotations

import os
import shutil
from collections import Counter

from sc2.ids.unit_typeid import UnitTypeId

STATE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "log")

# Same exclusion sets as dashboard
_WORKER_TYPES = {
    UnitTypeId.SCV, UnitTypeId.PROBE, UnitTypeId.DRONE, UnitTypeId.DRONEBURROWED,
    UnitTypeId.MULE,
}
_SUPPLY_TYPES = {
    UnitTypeId.OVERLORD, UnitTypeId.OVERLORDTRANSPORT, UnitTypeId.OVERSEER,
    UnitTypeId.OVERSEERSIEGEMODE,
}
_EXCLUDED_FROM_ARMY = _WORKER_TYPES | _SUPPLY_TYPES | {
    UnitTypeId.LARVA, UnitTypeId.EGG, UnitTypeId.BROODLING,
}


def _name(type_id: UnitTypeId) -> str:
    return type_id.name.replace("_", " ").title()


def _upgrade_name(upgrade_id) -> str:
    return upgrade_id.name.replace("_", " ").title()


class StateWriter:
    def __init__(self, bot, *, map_name: str = "", opponent_info: str = ""):
        self.bot = bot
        self.map_name = map_name
        self.opponent_info = opponent_info
        self._write_count = 0

    def start(self):
        """Create log/ directory (clean slate) and write game.txt."""
        if os.path.exists(STATE_DIR):
            shutil.rmtree(STATE_DIR)
        os.makedirs(STATE_DIR)

        self._write_game_txt()

    def _write_game_txt(self):
        bot = self.bot
        lines = []
        try:
            lines.append(f"Race: {bot.race.name}")
        except Exception:
            lines.append("Race: unknown")
        lines.append(f"Map: {self.map_name}")
        lines.append(f"Opponent: {self.opponent_info}")
        try:
            lines.append(f"Start position: {bot.start_location}")
            lines.append(f"Enemy start: {bot.enemy_start_locations}")
            lines.append(f"Expansion locations: {len(bot.expansion_locations_list)}")
        except Exception:
            pass
        _write(os.path.join(STATE_DIR, "game.txt"), "\n".join(lines) + "\n")

    def update(self, iteration: int):
        """Write snapshot."""
        try:
            self._write_snapshot(iteration)
        except Exception:
            pass

    def log_event(self, game_time: str, category: str, message: str):
        """Append one line to events.log."""
        line = f"{game_time} [{category:<10}] {message}\n"
        _append(os.path.join(STATE_DIR, "events.log"), line)

    def log_error(self, traceback_text: str, *, tick: int | None = None, game_time: str | None = None):
        """Append a full traceback to errors.log."""
        header = f"--- tick {tick} @ {game_time} ---\n" if tick is not None else "---\n"
        _append(os.path.join(STATE_DIR, "errors.log"), header + traceback_text + "\n")

    def _write_snapshot(self, iteration: int):
        bot = self.bot
        lines = []

        # Header
        try:
            lines.append(f"Game Time: {bot.time_formatted}  Tick: {iteration}")
        except Exception:
            lines.append(f"Tick: {iteration}")
        lines.append("")

        # Economy
        try:
            lines.append("Resources:")
            lines.append(f"  Minerals: {bot.minerals}  Vespene: {bot.vespene}  Supply: {bot.supply_used}/{bot.supply_cap}")
            lines.append("")

            n_workers = bot.workers.amount
            idle = bot.workers.idle.amount
            idle_str = f" ({idle} idle)" if idle else ""
            lines.append(f"Workers: {n_workers}{idle_str}")
            lines.append(f"Bases: {bot.townhalls.amount}  Gas Buildings: {bot.gas_buildings.amount}")
        except Exception:
            lines.append("Resources: (unavailable)")
        lines.append("")

        # Army
        try:
            counts: Counter = Counter()
            for u in bot.units:
                if u.type_id not in _EXCLUDED_FROM_ARMY:
                    counts[u.type_id] += 1
            if counts:
                lines.append("Army:")
                for type_id, count in counts.most_common():
                    lines.append(f"  {_name(type_id):<20} {count:>3}")
                lines.append(f"  Army supply: {bot.supply_army}")
            else:
                lines.append("Army: (none)")
        except Exception:
            lines.append("Army: (unavailable)")
        lines.append("")

        # Our structures
        try:
            struct_counts: Counter = Counter()
            for s in bot.structures:
                struct_counts[s.type_id] += 1
            if struct_counts:
                lines.append("Structures:")
                for type_id, count in struct_counts.most_common():
                    lines.append(f"  {_name(type_id):<20} {count:>3}")
            else:
                lines.append("Structures: (none)")
        except Exception:
            lines.append("Structures: (unavailable)")
        lines.append("")

        # Production queue
        try:
            items = []
            for structure in bot.structures:
                for order in structure.orders:
                    name = order.ability.button_name or order.ability.friendly_name
                    pct = int(order.progress * 100)
                    items.append(f"  {name:<20} {pct:>3}%")
            if items:
                lines.append("Production Queue:")
                lines.extend(items)
            else:
                lines.append("Production Queue: (idle)")
        except Exception:
            lines.append("Production Queue: (unavailable)")
        lines.append("")

        # Upgrades
        try:
            done = sorted(bot.state.upgrades, key=lambda u: u.name)
            if done:
                lines.append(f"Upgrades (done): {', '.join(_upgrade_name(u) for u in done)}")
            else:
                lines.append("Upgrades (done): (none)")

            in_progress = []
            for structure in bot.structures:
                for order in structure.orders:
                    fname = order.ability.friendly_name
                    if "Research" in fname or "Upgrade" in fname:
                        pct = int(order.progress * 100)
                        in_progress.append(f"{order.ability.button_name} ({pct}%)")
            if in_progress:
                lines.append(f"Upgrades (in progress): {', '.join(in_progress)}")
        except Exception:
            lines.append("Upgrades: (unavailable)")
        lines.append("")

        # Enemy units
        try:
            enemy_counts: Counter = Counter()
            for u in bot.enemy_units:
                enemy_counts[u.type_id] += 1
            if enemy_counts:
                lines.append("Enemy Units:")
                for type_id, count in enemy_counts.most_common():
                    lines.append(f"  {_name(type_id):<20} {count:>3}")
            else:
                lines.append("Enemy Units: (none visible)")
        except Exception:
            lines.append("Enemy Units: (unavailable)")
        lines.append("")

        # Enemy structures
        try:
            enemy_struct: Counter = Counter()
            for s in bot.enemy_structures:
                enemy_struct[s.type_id] += 1
            if enemy_struct:
                lines.append("Enemy Structures:")
                for type_id, count in enemy_struct.most_common():
                    lines.append(f"  {_name(type_id):<20} {count:>3}")
            else:
                lines.append("Enemy Structures: (none visible)")
        except Exception:
            lines.append("Enemy Structures: (unavailable)")

        _write(os.path.join(STATE_DIR, "snapshot.txt"), "\n".join(lines) + "\n")


def _write(path: str, content: str):
    """Atomic-ish write: write to .tmp then rename."""
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(content)
    os.replace(tmp, path)


def _append(path: str, content: str):
    with open(path, "a") as f:
        f.write(content)
