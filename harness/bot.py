import ast
import asyncio
import base64
import ctypes
import importlib
import inspect
import io
import json
import os
import sys
import textwrap
import threading
import time
import traceback
from types import SimpleNamespace

import numpy as np

from sc2.bot_ai import BotAI
from sc2.data import Race, Result

from .dashboard import Dashboard
from .state_writer import STATE_DIR as LOG_DIR
from .state_writer import StateWriter

# Bot code package — hot-reloaded from the bot_src/ directory.
BOT_PACKAGE = "bot_src"
BOT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), BOT_PACKAGE)
BOT_ENTRY = f"{BOT_PACKAGE}.bot"  # Must define a BotAI subclass

# Commands directory — cmd.py drops .py files here for one-shot execution.
COMMANDS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "commands")


STEP_TIMEOUT = 5.0  # seconds — kill bot on_step if it takes longer than this


def _raise_in_thread(thread_id, exc_type):
    """Raise an exception in another thread (CPython only)."""
    res = ctypes.pythonapi.PyThreadState_SetAsyncExc(
        ctypes.c_ulong(thread_id), ctypes.py_object(exc_type),
    )
    if res == 0:
        raise ValueError("Invalid thread ID")
    if res > 1:
        # Something went wrong, reset it
        ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(thread_id), None)


async def _run_with_timeout(coro, timeout):
    """Run a coroutine with a hard timeout that can interrupt synchronous loops.

    Uses a worker thread so that even blocking/synchronous code can be
    interrupted via PyThreadState_SetAsyncExc.
    """
    loop = asyncio.get_event_loop()
    result_exc = [None, None]  # [result, exception]
    thread_id = [None]

    def _worker():
        thread_id[0] = threading.current_thread().ident
        inner_loop = asyncio.new_event_loop()
        try:
            result_exc[0] = inner_loop.run_until_complete(coro)
        except BaseException as e:
            result_exc[1] = e
        finally:
            inner_loop.close()

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout)

    if t.is_alive():
        # Capture stack trace from the stuck thread before killing it
        stuck_tb = ""
        if thread_id[0] is not None:
            frame = sys._current_frames().get(thread_id[0])
            if frame:
                stuck_tb = "".join(traceback.format_stack(frame))
            try:
                _raise_in_thread(thread_id[0], SystemExit)
            except (ValueError, SystemError):
                pass
        t.join(1.0)
        msg = f"on_step exceeded {timeout}s timeout (possible infinite loop)\n\nBot was stuck at:\n{stuck_tb}"
        raise TimeoutError(msg)

    if result_exc[1] is not None:
        raise result_exc[1]
    return result_exc[0]


_HARNESS_METHODS = {
    'on_step', 'on_start', 'on_end', 'on_reload',
    'on_unit_destroyed', 'on_unit_took_damage',
    'on_building_construction_complete', 'on_upgrade_complete',
    'on_enemy_unit_entered_vision',
}


def _find_bot_class(module):
    """Find the first BotAI subclass defined in the module."""
    for name, obj in inspect.getmembers(module, inspect.isclass):
        if issubclass(obj, BotAI) and obj is not BotAI and obj.__module__ == module.__name__:
            return obj
    return None


class HarnessBot(BotAI):

    # Set by main() before the game starts so the dashboard can display them.
    _map_name: str = ""
    _opponent_info: str = ""

    def __init__(self):
        super().__init__()
        self._harness_state = SimpleNamespace(
            bot_module=None,
            bot_mtimes={},
            last_error=None,
            user_class=None,
            dashboard=None,
            lb=None,
        )

    async def _drain_commands(self):
        """Execute any pending command files dropped by cmd.py."""
        if not os.path.isdir(COMMANDS_DIR):
            return
        try:
            entries = sorted(f for f in os.listdir(COMMANDS_DIR) if f.endswith(".py"))
        except OSError:
            return
        if not entries:
            return

        from sc2.ids.unit_typeid import UnitTypeId
        from sc2.ids.ability_id import AbilityId
        from sc2.ids.upgrade_id import UpgradeId
        from sc2.position import Point2

        exec_globals = {
            "__builtins__": __builtins__,
            "self": self,
            "bot": self,
            "UnitTypeId": UnitTypeId,
            "AbilityId": AbilityId,
            "UpgradeId": UpgradeId,
            "Race": Race,
            "Point2": Point2,
        }

        for entry in entries:
            cmd_path = os.path.join(COMMANDS_DIR, entry)
            result_path = os.path.join(COMMANDS_DIR, entry.removesuffix(".py") + ".result")
            try:
                with open(cmd_path) as f:
                    code = f.read()
            except OSError:
                continue

            # If the last statement is an expression, capture its value
            try:
                tree = ast.parse(code)
                if tree.body and isinstance(tree.body[-1], ast.Expr):
                    last = tree.body[-1]
                    lines = code.split("\n")
                    last_start = last.lineno - 1
                    lines[last_start] = "__result__ = " + lines[last_start]
                    code = "\n".join(lines)
            except SyntaxError:
                pass  # Let the exec report it

            # Wrap in async function so `await` works in commands
            indented = textwrap.indent(code, "    ")
            wrapper = f"async def __cmd__(self):\n    __result__ = None\n{indented}\n    return __result__"

            stdout_capture = io.StringIO()
            stderr_capture = io.StringIO()
            result = {"ok": True, "stdout": "", "stderr": "", "error": None}

            try:
                exec(compile(wrapper, cmd_path, "exec"), exec_globals)
                old_stdout, old_stderr = sys.stdout, sys.stderr
                sys.stdout, sys.stderr = stdout_capture, stderr_capture
                try:
                    retval = await _run_with_timeout(
                        exec_globals["__cmd__"](self), STEP_TIMEOUT,
                    )
                finally:
                    sys.stdout, sys.stderr = old_stdout, old_stderr

                result["stdout"] = stdout_capture.getvalue()
                result["stderr"] = stderr_capture.getvalue()
                if retval is not None:
                    result["stdout"] += repr(retval) + "\n"
            except Exception:
                sys.stdout, sys.stderr = sys.__stdout__, sys.__stderr__
                result["ok"] = False
                result["stdout"] = stdout_capture.getvalue()
                result["stderr"] = stderr_capture.getvalue()
                result["error"] = traceback.format_exc()

            try:
                with open(result_path, "w") as f:
                    json.dump(result, f)
            except OSError:
                pass

            # Log to dashboard
            dash = self._harness_state.dashboard
            if dash:
                preview = code.strip().split("\n")[0][:60]
                if result["ok"]:
                    dash.log("cmd", preview)
                else:
                    dash.log("cmd", f"FAILED: {preview}")

            # Clean up command file
            try:
                os.unlink(cmd_path)
            except FileNotFoundError:
                pass

    def log(self, message: str):
        """Log a message from bot code. Shows in dashboard and writes to log/bot.log."""
        try:
            game_time = self.time_formatted
        except Exception:
            game_time = "--:--"
        hs = self._harness_state
        if hs.dashboard:
            hs.dashboard.log("bot", message)
        else:
            print(f"[bot] [{game_time}] {message}")
        try:
            with open(os.path.join(LOG_DIR, "bot.log"), "a") as f:
                f.write(f"[{game_time}] {message}\n")
        except Exception:
            pass

    async def on_start(self):
        hs = self._harness_state
        state_writer = StateWriter(
            self,
            map_name=self._map_name,
            opponent_info=self._opponent_info,
        )
        state_writer.start()
        hs.dashboard = Dashboard(
            self,
            map_name=self._map_name,
            opponent_info=self._opponent_info,
            state_writer=state_writer,
        )
        hs.dashboard.start()

        if hs.lb:
            gi = self.game_info
            pa = gi.playable_area
            terrain_b64 = base64.b64encode(
                np.packbits(gi.pathing_grid.data_numpy).tobytes()
            ).decode("ascii")
            hs.lb.send_minimap_init(
                map_size=[gi.map_size.x, gi.map_size.y],
                playable=[pa.x, pa.y, pa.width, pa.height],
                terrain=terrain_b64,
            )

        # Delegate to user class on_start (fires once per game)
        uc = hs.user_class
        if uc and hasattr(uc, 'on_start'):
            try:
                result = uc.on_start(self)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                tb = traceback.format_exc()
                if hs.dashboard:
                    hs.dashboard.set_error(tb, tick=0, game_time=self.time_formatted)

    async def on_step(self, iteration: int):
        hs = self._harness_state
        dash = hs.dashboard

        # Hot-reload bot code if any .py file in bot_src/ changed (or on first load)
        if not os.path.isdir(BOT_DIR):
            if hs.last_error != "missing":
                msg = f"Bot source directory not found: {BOT_PACKAGE}/"
                if dash:
                    dash.log("harness", msg)
                else:
                    print(f"[harness] {msg}")
                hs.last_error = "missing"
            return

        current_mtimes = {}
        for root, dirs, files in os.walk(BOT_DIR):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for f in files:
                if f.endswith(".py"):
                    path = os.path.join(root, f)
                    current_mtimes[path] = os.path.getmtime(path)

        code_changed = current_mtimes != hs.bot_mtimes
        if code_changed:
            if hs.bot_mtimes:
                changed = sorted(
                    os.path.relpath(p, BOT_DIR)
                    for p in current_mtimes
                    if current_mtimes.get(p) != hs.bot_mtimes.get(p)
                )
                changed += sorted(
                    os.path.relpath(p, BOT_DIR)
                    for p in hs.bot_mtimes
                    if p not in current_mtimes
                )
            else:
                changed = []
            hs.bot_mtimes = current_mtimes
            try:
                # Purge all bot package modules so imports are re-evaluated
                to_remove = [
                    k for k in sys.modules
                    if k == BOT_PACKAGE or k.startswith(BOT_PACKAGE + ".")
                ]
                for k in to_remove:
                    del sys.modules[k]
                hs.bot_module = importlib.import_module(BOT_ENTRY)

                # Find the user's BotAI subclass
                user_class = _find_bot_class(hs.bot_module)
                if user_class is None:
                    if hs.last_error != "no_class":
                        msg = f"No BotAI subclass found in {BOT_ENTRY}"
                        if dash:
                            dash.log("harness", msg)
                        else:
                            print(f"[harness] {msg}")
                        hs.last_error = "no_class"
                    return

                # Synthesize a new class combining HarnessBot + user attributes
                # Exclude harness-controlled methods — they're called via unbound delegation
                attrs = {
                    name: value
                    for name, value in vars(user_class).items()
                    if not (name.startswith('__') and name.endswith('__'))
                    and name not in _HARNESS_METHODS
                }
                new_class = type('UserBot', (HarnessBot,), attrs)
                self.__class__ = new_class
                hs.user_class = user_class

                hs.last_error = None
                if changed:
                    changed_str = ", ".join(changed)
                    msg = f"Reloaded bot [{changed_str}] (tick {iteration}, {self.time_formatted})"
                else:
                    msg = f"Loaded bot code (tick {iteration}, {self.time_formatted})"
                if dash:
                    dash.set_error(None)
                    dash.last_reload_time = self.time_formatted
                    dash.log("harness", msg)
                else:
                    print(f"[harness] {msg}")

                # Call on_reload if defined (fires every hot-reload)
                if hasattr(user_class, 'on_reload'):
                    try:
                        result = user_class.on_reload(self)
                        if inspect.isawaitable(result):
                            await result
                    except Exception:
                        tb = traceback.format_exc()
                        if dash:
                            dash.set_error(tb, tick=iteration, game_time=self.time_formatted)

            except Exception:
                hs.last_error = "load"
                tb = traceback.format_exc()
                if dash:
                    dash.set_error(tb, tick=iteration, game_time=self.time_formatted)
                    dash.log("error", "Failed to load bot code")
                else:
                    print(f"[harness] Failed to load bot code:")
                    traceback.print_exc()
                return

        if hs.user_class is None:
            return

        # Delegate on_step to user class (with timeout to catch infinite loops)
        uc = hs.user_class
        if hasattr(uc, 'on_step'):
            try:
                result = uc.on_step(self, iteration)
                if inspect.isawaitable(result):
                    await _run_with_timeout(result, STEP_TIMEOUT)
            except TimeoutError as e:
                tb = f"TimeoutError: {e}"
                if dash:
                    dash.set_error(tb, tick=iteration, game_time=self.time_formatted)
                    dash.log("error", f"on_step timed out ({STEP_TIMEOUT}s) — possible infinite loop")
                else:
                    print(f"[harness] {tb}")
            except Exception:
                tb = traceback.format_exc()
                if dash:
                    dash.set_error(tb, tick=iteration, game_time=self.time_formatted)
                else:
                    print(f"[harness] Bot error at tick {iteration} ({self.time_formatted}):")
                    traceback.print_exc()

        # Execute any pending commands from cmd.py
        await self._drain_commands()

        # Update dashboard at end of tick
        if dash:
            dash.update(iteration)

        # Send minimap data to leaderboard (~every 22 ticks / ~1s)
        if hs.lb:
            units = []
            for u in self.units:
                units.append([round(u.position.x, 1), round(u.position.y, 1), 0])
            for s in self.structures:
                units.append([round(s.position.x, 1), round(s.position.y, 1), 1])
            for u in self.enemy_units:
                units.append([round(u.position.x, 1), round(u.position.y, 1), 2])
            for s in self.enemy_structures:
                units.append([round(s.position.x, 1), round(s.position.y, 1), 3])
            for m in self.mineral_field:
                units.append([round(m.position.x, 1), round(m.position.y, 1), 4])
            for g in self.vespene_geyser:
                units.append([round(g.position.x, 1), round(g.position.y, 1), 5])
            # Pack visibility grid: 2 bits per cell (0=hidden, 1=fogged, 2=visible)
            vis = self.state.visibility.data_numpy.flatten()
            pad = (-len(vis)) % 4
            if pad:
                vis = np.concatenate([vis, np.zeros(pad, dtype=np.uint8)])
            packed = (vis[0::4] << 6) | (vis[1::4] << 4) | (vis[2::4] << 2) | vis[3::4]
            vis_b64 = base64.b64encode(packed.astype(np.uint8).tobytes()).decode("ascii")
            hs.lb.send_minimap(units=units, visibility=vis_b64)

    async def on_end(self, game_result: Result):
        hs = self._harness_state
        # Delegate to user class on_end before cleanup
        uc = hs.user_class
        if uc and hasattr(uc, 'on_end'):
            try:
                result = uc.on_end(self, game_result)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                pass
        if hs.dashboard:
            hs.dashboard.log("harness", f"Game ended: {game_result}")
            # Final render so the user sees the end state briefly
            hs.dashboard.update(0)
            time.sleep(1.5)
            hs.dashboard.stop()
        print(f"[harness] Game ended: {game_result}")

    async def on_unit_destroyed(self, unit_tag: int):
        hs = self._harness_state
        if hs.dashboard:
            hs.dashboard.on_unit_destroyed(unit_tag)
        uc = hs.user_class
        if uc and hasattr(uc, 'on_unit_destroyed'):
            try:
                result = uc.on_unit_destroyed(self, unit_tag)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                tb = traceback.format_exc()
                if hs.dashboard:
                    hs.dashboard.set_error(tb, tick=self.state.game_loop, game_time=self.time_formatted)

    async def on_unit_took_damage(self, unit, amount_damage_taken: float):
        hs = self._harness_state
        if hs.dashboard:
            hs.dashboard.on_unit_took_damage(unit, amount_damage_taken)
        uc = hs.user_class
        if uc and hasattr(uc, 'on_unit_took_damage'):
            try:
                result = uc.on_unit_took_damage(self, unit, amount_damage_taken)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                tb = traceback.format_exc()
                if hs.dashboard:
                    hs.dashboard.set_error(tb, tick=self.state.game_loop, game_time=self.time_formatted)

    async def on_building_construction_complete(self, unit):
        hs = self._harness_state
        if hs.dashboard:
            hs.dashboard.on_building_construction_complete(unit)
        uc = hs.user_class
        if uc and hasattr(uc, 'on_building_construction_complete'):
            try:
                result = uc.on_building_construction_complete(self, unit)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                tb = traceback.format_exc()
                if hs.dashboard:
                    hs.dashboard.set_error(tb, tick=self.state.game_loop, game_time=self.time_formatted)

    async def on_upgrade_complete(self, upgrade):
        hs = self._harness_state
        if hs.dashboard:
            hs.dashboard.on_upgrade_complete(upgrade)
        uc = hs.user_class
        if uc and hasattr(uc, 'on_upgrade_complete'):
            try:
                result = uc.on_upgrade_complete(self, upgrade)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                tb = traceback.format_exc()
                if hs.dashboard:
                    hs.dashboard.set_error(tb, tick=self.state.game_loop, game_time=self.time_formatted)

    async def on_enemy_unit_entered_vision(self, unit):
        hs = self._harness_state
        if hs.dashboard:
            hs.dashboard.on_enemy_unit_entered_vision(unit)
        uc = hs.user_class
        if uc and hasattr(uc, 'on_enemy_unit_entered_vision'):
            try:
                result = uc.on_enemy_unit_entered_vision(self, unit)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                tb = traceback.format_exc()
                if hs.dashboard:
                    hs.dashboard.set_error(tb, tick=self.state.game_loop, game_time=self.time_formatted)
