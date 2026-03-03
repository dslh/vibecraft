"""
TUI Dashboard for SC2 Bot Harness.

Renders a real-time terminal dashboard using Rich's Live display,
updated each game tick from on_step().
"""

from __future__ import annotations

import atexit
import platform
import subprocess
import sys
import traceback

_IS_WINDOWS = platform.system() == "Windows"

if _IS_WINDOWS:
    import msvcrt
else:
    import select
    import termios
    import tty
from collections import Counter, deque
from dataclasses import dataclass, field

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sc2.ids.unit_typeid import UnitTypeId

# Unit types to exclude from army composition display
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
    """Human-readable unit name from type ID."""
    return type_id.name.replace("_", " ").title()


def _upgrade_name(upgrade_id) -> str:
    return upgrade_id.name.replace("_", " ").title()


@dataclass
class StickyEvent:
    game_time: str
    category: str  # "lost", "killed", "attacked", "building", "upgrade", "enemy_spotted", "harness"
    message: str
    expire_at: float


# Category -> Rich style
_EVENT_STYLES = {
    "lost": "bold red",
    "killed": "green",
    "attacked": "red",
    "building": "bold cyan",
    "upgrade": "bold magenta",
    "enemy_spotted": "bold yellow",
    "harness": "dim white",
    "error": "bold red",
}


class EventLog:
    def __init__(self, ttl: float = 10.0, maxlen: int = 50):
        self.events: deque[StickyEvent] = deque(maxlen=maxlen)
        self.ttl = ttl

    def add(self, game_time: str, category: str, message: str, current_time: float):
        self.events.append(StickyEvent(
            game_time=game_time,
            category=category,
            message=message,
            expire_at=current_time + self.ttl,
        ))

    def prune(self, current_time: float):
        while self.events and self.events[0].expire_at < current_time:
            self.events.popleft()

    def recent(self, n: int = 6) -> list[StickyEvent]:
        return list(self.events)[-n:]


class Dashboard:
    def __init__(self, bot, *, map_name: str = "", opponent_info: str = ""):
        self.bot = bot
        self.map_name = map_name
        self.opponent_info = opponent_info

        self.event_log = EventLog()
        self.last_error: str | None = None
        self.last_error_tick: int | None = None
        self.last_error_time: str | None = None
        self.last_reload_time: str = ""

        self._console = Console()
        self._live: Live | None = None
        self._render_count = 0
        self._seen_enemy_types: set[UnitTypeId] = set()
        self._damage_cooldowns: dict[int, float] = {}  # unit_tag -> next report time
        self._error_expanded = False

        # Creep calculation cache
        self._creep_pct: float = 0.0
        self._creep_tick: int = -100

        # Terminal raw mode state
        self._old_term_settings = None

    def start(self):
        layout = self._make_layout()
        self._live = Live(
            layout,
            console=self._console,
            auto_refresh=False,
            screen=True,
        )
        self._live.start()
        atexit.register(self._atexit_cleanup)
        # Put stdin in raw mode so we can read single keypresses without blocking
        if not _IS_WINDOWS:
            try:
                self._old_term_settings = termios.tcgetattr(sys.stdin)
                tty.setcbreak(sys.stdin.fileno())
            except Exception:
                self._old_term_settings = None

    def stop(self):
        # Restore terminal settings before stopping Live
        if not _IS_WINDOWS and self._old_term_settings is not None:
            try:
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self._old_term_settings)
            except Exception:
                pass
            self._old_term_settings = None
        if self._live is not None:
            try:
                self._live.stop()
            except Exception:
                pass
            self._live = None

    def _atexit_cleanup(self):
        self.stop()

    def log(self, category: str, message: str):
        """Add a sticky event to the log."""
        try:
            game_time = self.bot.time_formatted
            current_time = self.bot.time
        except Exception:
            game_time = "--:--"
            current_time = 0.0
        self.event_log.add(game_time, category, message, current_time)

    def set_error(self, error_text: str | None, *, tick: int | None = None, game_time: str | None = None):
        self.last_error = error_text
        if error_text is not None:
            self.last_error_tick = tick
            self.last_error_time = game_time
        else:
            self.last_error_tick = None
            self.last_error_time = None
            self._error_expanded = False

    def _poll_keys(self):
        """Non-blocking check for keypresses. Call each render tick."""
        try:
            if _IS_WINDOWS:
                while msvcrt.kbhit():
                    ch = msvcrt.getwch()
                    if ch == "e":
                        if self.last_error:
                            self._error_expanded = not self._error_expanded
                    elif ch == "c":
                        if self.last_error:
                            self._copy_error_to_clipboard()
            else:
                while select.select([sys.stdin], [], [], 0)[0]:
                    ch = sys.stdin.read(1)
                    if ch == "e":
                        if self.last_error:
                            self._error_expanded = not self._error_expanded
                    elif ch == "c":
                        if self.last_error:
                            self._copy_error_to_clipboard()
        except Exception:
            pass

    def _copy_error_to_clipboard(self):
        pf = platform.system()
        if pf == "Darwin":
            cmd = ["pbcopy"]
        elif pf == "Windows":
            cmd = ["clip.exe"]
        else:
            cmd = ["xclip", "-selection", "clipboard"]
        try:
            subprocess.run(
                cmd,
                input=self.last_error.encode(),
                check=True,
                timeout=2,
            )
            self.log("harness", "Error copied to clipboard")
        except Exception:
            self.log("harness", "Failed to copy to clipboard")

    def update(self, iteration: int):
        """Rebuild and render the dashboard. Call every tick (throttled internally)."""
        if self._live is None:
            return

        # Always poll keys so input doesn't buffer up
        self._poll_keys()

        # Throttle rendering: every 5th tick
        self._render_count += 1
        if self._render_count % 5 != 1 and self._render_count > 1:
            return

        try:
            self.event_log.prune(self.bot.time)
            layout = self._make_layout()
            self._fill_layout(layout, iteration)
            self._live.update(layout)
            self._live.refresh()
        except Exception:
            pass  # Never crash the game for a rendering error

    # ── Event callbacks ──────────────────────────────────────────────

    def on_unit_destroyed(self, unit_tag: int):
        """Called when any unit dies."""
        bot = self.bot
        # Check if it was ours
        prev = bot._units_previous_map.get(unit_tag) or bot._structures_previous_map.get(unit_tag)
        if prev is not None:
            self.log("lost", f"Lost: {_name(prev.type_id)}")
            return

        # Check if it was an enemy
        prev = bot._enemy_units_previous_map.get(unit_tag) or bot._enemy_structures_previous_map.get(unit_tag)
        if prev is not None:
            self.log("killed", f"Killed: {_name(prev.type_id)}")

    def on_unit_took_damage(self, unit, amount_damage_taken: float):
        """Called when one of our units takes damage."""
        now = self.bot.time
        tag = unit.tag
        if tag in self._damage_cooldowns and now < self._damage_cooldowns[tag]:
            return
        self._damage_cooldowns[tag] = now + 3.0
        self.log("attacked", f"{_name(unit.type_id)} attacked (-{int(amount_damage_taken)} HP)")

    def on_building_construction_complete(self, unit):
        self.log("building", f"Building completed: {_name(unit.type_id)}")

    def on_upgrade_complete(self, upgrade):
        self.log("upgrade", f"Upgrade complete: {_upgrade_name(upgrade)}")

    def on_enemy_unit_entered_vision(self, unit):
        if unit.type_id not in self._seen_enemy_types:
            self._seen_enemy_types.add(unit.type_id)
            self.log("enemy_spotted", f"New enemy type: {_name(unit.type_id)}")

    # ── Layout construction ──────────────────────────────────────────

    def _make_layout(self) -> Layout:
        layout = Layout(name="root")

        if self._error_expanded and self.last_error:
            # Expanded: header + full error panel
            layout.split_column(
                Layout(name="header", size=3),
                Layout(name="error", ratio=1),
            )
        else:
            # Normal: full dashboard with compact error
            layout.split_column(
                Layout(name="header", size=3),
                Layout(name="body", ratio=1),
                Layout(name="events", size=8),
                Layout(name="error", size=4),
            )
            layout["body"].split_row(
                Layout(name="left", ratio=1),
                Layout(name="center", ratio=1),
                Layout(name="right", ratio=1),
            )
            layout["left"].split_column(
                Layout(name="economy", ratio=2),
                Layout(name="production", ratio=2),
                Layout(name="upgrades", ratio=1),
            )
            layout["center"].split_column(
                Layout(name="army", ratio=3),
                Layout(name="mapinfo", ratio=1),
            )
            layout["right"].split_column(
                Layout(name="enemy_units", ratio=1),
                Layout(name="enemy_structures", ratio=1),
            )
        return layout

    def _fill_layout(self, layout: Layout, iteration: int):
        bot = self.bot

        # Header
        layout["header"].update(self._build_header(bot, iteration))

        if self._error_expanded and self.last_error:
            # Expanded error takes over the body
            layout["error"].update(self._build_error())
            return

        # Left column
        layout["economy"].update(self._build_economy(bot))
        layout["production"].update(self._build_production(bot))
        layout["upgrades"].update(self._build_upgrades(bot))

        # Center column
        layout["army"].update(self._build_army(bot))
        layout["mapinfo"].update(self._build_map_info(bot))

        # Right column
        layout["enemy_units"].update(self._build_enemy_units(bot))
        layout["enemy_structures"].update(self._build_enemy_structures(bot))

        # Bottom
        layout["events"].update(self._build_events())
        layout["error"].update(self._build_error())

    def _build_header(self, bot, iteration: int) -> Panel:
        parts = []
        try:
            parts.append(bot.time_formatted)
        except Exception:
            parts.append("--:--")
        parts.append(f"Tick {iteration}")
        if self.last_reload_time:
            parts.append(f"Reloaded {self.last_reload_time}")
        try:
            parts.append(bot.race.name)
        except Exception:
            pass
        if self.map_name:
            parts.append(self.map_name)
        if self.opponent_info:
            parts.append(f"vs {self.opponent_info}")
        return Panel(
            Text(" │ ".join(parts), justify="center"),
            title="SC2 Dashboard",
            style="bold",
        )

    def _build_economy(self, bot) -> Panel:
        lines = Text()
        try:
            lines.append(f"Minerals  {bot.minerals:>6,}\n")
            lines.append(f"Vespene   {bot.vespene:>6,}\n")
            lines.append(f"Supply    {bot.supply_used:>3}/{bot.supply_cap}\n")

            n_workers = bot.workers.amount
            idle = bot.workers.idle.amount
            idle_str = f" ({idle} idle)" if idle else ""
            lines.append(f"Workers   {n_workers:>3}{idle_str}\n")

            bases = bot.townhalls.amount
            gas = bot.gas_buildings.amount
            lines.append(f"Bases     {bases:>3}   Gas {gas}")
        except Exception:
            lines.append("(loading...)")
        return Panel(lines, title="Economy")

    def _build_production(self, bot) -> Panel:
        lines = Text()
        try:
            items = []
            for structure in bot.structures:
                for order in structure.orders:
                    name = order.ability.button_name or order.ability.friendly_name
                    progress = order.progress
                    items.append((name, progress))

            if not items:
                lines.append("(idle)", style="dim")
            else:
                for name, progress in items[:6]:
                    pct = int(progress * 100)
                    filled = int(progress * 4)
                    bar = "█" * filled + "─" * (4 - filled)
                    lines.append(f"{name:<16} {bar} {pct:>3}%\n")
        except Exception:
            lines.append("(loading...)")
        return Panel(lines, title="Production")

    def _build_upgrades(self, bot) -> Panel:
        lines = Text()
        try:
            done = sorted(bot.state.upgrades, key=lambda u: u.name)
            for u in done[-4:]:
                lines.append("✓ ", style="green")
                lines.append(f"{_upgrade_name(u)}\n")

            # In-progress upgrades from structure orders
            for structure in bot.structures:
                for order in structure.orders:
                    fname = order.ability.friendly_name
                    if "Research" in fname or "Upgrade" in fname:
                        pct = int(order.progress * 100)
                        lines.append("◑ ", style="yellow")
                        lines.append(f"{order.ability.button_name} {pct}%\n")

            if not lines.plain:
                lines.append("(none)", style="dim")
        except Exception:
            lines.append("(loading...)")
        return Panel(lines, title="Upgrades")

    def _build_army(self, bot) -> Panel:
        lines = Text()
        try:
            counts: Counter = Counter()
            total_supply = 0
            for u in bot.units:
                if u.type_id in _EXCLUDED_FROM_ARMY:
                    continue
                counts[u.type_id] += 1

            if not counts:
                lines.append("(no army)", style="dim")
            else:
                for type_id, count in counts.most_common(10):
                    lines.append(f"{_name(type_id):<18} {count:>3}\n")

            lines.append(f"\nSupply: {bot.supply_army}", style="bold")
        except Exception:
            lines.append("(loading...)")
        return Panel(lines, title="Army")

    def _build_map_info(self, bot) -> Panel:
        lines = Text()
        try:
            bases = bot.townhalls.amount
            total_exps = len(bot.expansion_locations_list)
            lines.append(f"Expansions  {bases}/{total_exps}\n")

            # Creep percentage (cached, recalculate every ~50 ticks)
            if hasattr(bot, "state") and hasattr(bot.state, "creep"):
                tick = self._render_count
                if tick - self._creep_tick >= 50:
                    self._creep_tick = tick
                    try:
                        import numpy as np
                        creep_grid = bot.state.creep.data_numpy
                        pathable_grid = bot.game_info.pathing_grid.data_numpy
                        pathable_count = pathable_grid.sum()
                        if pathable_count > 0:
                            self._creep_pct = creep_grid.sum() / pathable_count * 100
                    except Exception:
                        pass
                if self._creep_pct > 0:
                    lines.append(f"Creep       {self._creep_pct:.0f}%")
        except Exception:
            lines.append("(loading...)")
        return Panel(lines, title="Map")

    def _build_enemy_units(self, bot) -> Panel:
        lines = Text()
        try:
            counts: Counter = Counter()
            for u in bot.enemy_units:
                counts[u.type_id] += 1

            if not counts:
                lines.append("(none visible)", style="dim")
            else:
                for type_id, count in counts.most_common(10):
                    lines.append(f"{_name(type_id):<18} {count:>3}\n")
        except Exception:
            lines.append("(loading...)")
        return Panel(lines, title="Enemy Units")

    def _build_enemy_structures(self, bot) -> Panel:
        lines = Text()
        try:
            counts: Counter = Counter()
            for s in bot.enemy_structures:
                counts[s.type_id] += 1

            if not counts:
                lines.append("(none visible)", style="dim")
            else:
                for type_id, count in counts.most_common(8):
                    lines.append(f"{_name(type_id):<18} {count:>3}\n")
        except Exception:
            lines.append("(loading...)")
        return Panel(lines, title="Enemy Structures")

    def _build_events(self) -> Panel:
        lines = Text()
        events = self.event_log.recent(6)
        if not events:
            lines.append("(no events)", style="dim")
        else:
            for ev in events:
                style = _EVENT_STYLES.get(ev.category, "")
                lines.append(f"{ev.game_time}  ", style="dim")
                lines.append(f"{ev.message}\n", style=style)
        return Panel(lines, title="Events")

    def _build_error(self) -> Panel:
        if self.last_error:
            # Build title with tick/time context
            title_parts = ["Error"]
            if self.last_error_time:
                title_parts.append(self.last_error_time)
            if self.last_error_tick is not None:
                title_parts.append(f"tick {self.last_error_tick}")
            title = " @ ".join(title_parts)

            if self._error_expanded:
                # Full traceback
                content = Text(self.last_error, style="red")
                subtitle = "[dim]\\[e] collapse  \\[c] copy[/dim]"
            else:
                # Compact: show last few lines (the exception is always at the tail)
                lines = self.last_error.rstrip().split("\n")
                tail = "\n".join(lines[-3:])
                content = Text(tail, style="red")
                subtitle = "[dim]\\[e] expand  \\[c] copy[/dim]"

            return Panel(
                content,
                title=title,
                subtitle=subtitle,
                border_style="red",
            )
        return Panel(Text("(no errors)", style="dim green"), title="Error")
