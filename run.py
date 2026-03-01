"""
SC2 Bot Harness — hot-reloads bot.py on every game tick.

Usage:
    python run.py [--map MAP_NAME] [--race RACE] [--difficulty DIFFICULTY]
    python run.py --human protoss --race zerg     # play against your own bot
    python run.py --host --race terran            # host a LAN game
    python run.py --join 192.168.1.100 --race zerg  # join a LAN game

Remote mode (bot code here, SC2 on a separate machine — see server.py):
    python run.py --remote-host ws://SERVER:5000/sc2api --race terran
    python run.py --remote-join ws://SERVER:5001/sc2api --host-ip SERVER --race zerg

While the game is running, edit bot.py and save. Your changes take effect
on the next tick. If bot.py has a syntax error or crashes, the harness
logs the error and skips that tick — the game keeps running.
"""

import argparse
import asyncio
import importlib
import inspect
import os
import socket
import sys
import traceback
from urllib.parse import urlparse

import aiohttp
from loguru import logger
from s2clientprotocol import sc2api_pb2 as sc_pb

from sc2 import maps
from sc2.bot_ai import BotAI
from sc2.client import Client
from sc2.data import Difficulty, Race, Result
from sc2.main import _play_game_ai, run_game
from sc2.player import Bot, Computer, Human
from sc2.sc2process import SC2Process

from dashboard import Dashboard
from ports import DEFAULT_BASE_PORT, make_portconfig

# The bot module to hot-reload. Lives next to this file.
BOT_MODULE_NAME = "bot"
BOT_MODULE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.py")

RACE_MAP = {r.name.lower(): r for r in Race}
DIFFICULTY_MAP = {d.name.lower(): d for d in Difficulty}


class HarnessBot(BotAI):

    # Set by main() before the game starts so the dashboard can display them.
    _map_name: str = ""
    _opponent_info: str = ""

    def __init__(self):
        super().__init__()
        self.memory = {}
        self._bot_module = None
        self._bot_mtime = 0.0
        self._last_error = None
        self.dashboard: Dashboard | None = None

    async def on_start(self):
        self.dashboard = Dashboard(
            self,
            map_name=self._map_name,
            opponent_info=self._opponent_info,
        )
        self.dashboard.start()

    async def on_step(self, iteration: int):
        dash = self.dashboard

        # Hot-reload bot.py if it changed on disk (or on first load)
        try:
            mtime = os.path.getmtime(BOT_MODULE_PATH)
        except OSError:
            if self._last_error != "missing":
                msg = f"bot.py not found at {BOT_MODULE_PATH}"
                if dash:
                    dash.log("harness", msg)
                else:
                    print(f"[harness] {msg}")
                self._last_error = "missing"
            return

        if mtime != self._bot_mtime:
            self._bot_mtime = mtime
            try:
                if BOT_MODULE_NAME in sys.modules:
                    self._bot_module = importlib.reload(sys.modules[BOT_MODULE_NAME])
                else:
                    self._bot_module = importlib.import_module(BOT_MODULE_NAME)
                self._last_error = None
                msg = f"Reloaded bot.py (tick {iteration}, {self.time_formatted})"
                if dash:
                    dash.set_error(None)
                    dash.last_reload_time = self.time_formatted
                    dash.log("harness", msg)
                else:
                    print(f"[harness] {msg}")
            except Exception:
                self._last_error = "load"
                tb = traceback.format_exc()
                if dash:
                    dash.set_error(tb, tick=iteration, game_time=self.time_formatted)
                    dash.log("error", "Failed to load bot.py")
                else:
                    print(f"[harness] Failed to load bot.py:")
                    traceback.print_exc()
                return

        if self._bot_module is None:
            return

        play_fn = getattr(self._bot_module, "play", None)
        if play_fn is None:
            if self._last_error != "no_play":
                msg = "No play() function found in bot.py"
                if dash:
                    dash.log("harness", msg)
                else:
                    print(f"[harness] {msg}")
                self._last_error = "no_play"
            return

        try:
            result = play_fn(self, self.memory)
            # Support async play() functions
            if inspect.isawaitable(result):
                await result
        except Exception:
            tb = traceback.format_exc()
            if dash:
                dash.set_error(tb, tick=iteration, game_time=self.time_formatted)
            else:
                print(f"[harness] Bot error at tick {iteration} ({self.time_formatted}):")
                traceback.print_exc()

        # Update dashboard at end of tick
        if dash:
            dash.update(iteration)

    async def on_end(self, game_result: Result):
        if self.dashboard:
            self.dashboard.log("harness", f"Game ended: {game_result}")
            # Final render so the user sees the end state briefly
            self.dashboard.update(0)
            import time
            time.sleep(1.5)
            self.dashboard.stop()
        print(f"[harness] Game ended: {game_result}")

    async def on_unit_destroyed(self, unit_tag: int):
        if self.dashboard:
            self.dashboard.on_unit_destroyed(unit_tag)

    async def on_unit_took_damage(self, unit, amount_damage_taken: float):
        if self.dashboard:
            self.dashboard.on_unit_took_damage(unit, amount_damage_taken)

    async def on_building_construction_complete(self, unit):
        if self.dashboard:
            self.dashboard.on_building_construction_complete(unit)

    async def on_upgrade_complete(self, upgrade):
        if self.dashboard:
            self.dashboard.on_upgrade_complete(upgrade)

    async def on_enemy_unit_entered_vision(self, unit):
        if self.dashboard:
            self.dashboard.on_enemy_unit_entered_vision(unit)


def get_lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


async def _run_lan_game(client, player_id):
    """Shared game loop for both host and join LAN paths."""
    harness_bot = HarnessBot()

    print(f"[harness] Joined as player {player_id}. Game starting!")
    print(f"[harness] Edit {BOT_MODULE_PATH} while the game runs. Changes apply next tick.")
    print()

    result = await _play_game_ai(client, player_id, harness_bot, realtime=True, game_time_limit=None)

    print(f"[harness] Game ended: {result}")

    try:
        await client.leave()
    except Exception:
        pass


async def host_lan_game(map_name: str, race: Race, base_port: int, num_players: int, lan_ip: str | None = None):
    os.environ["SC2SERVERHOST"] = "0.0.0.0"

    portconfig = make_portconfig(base_port, num_players)
    if lan_ip is None:
        lan_ip = get_lan_ip()

    print(f"[harness] Hosting LAN game on {map_name}...")

    async with SC2Process() as controller:
        players = [Human(Race.Random) for _ in range(num_players)]
        result = await controller.create_game(maps.get(map_name), players, realtime=True)

        if result.create_game.HasField("error"):
            err = result.create_game.error
            details = result.create_game.error_details if result.create_game.HasField("error_details") else ""
            print(f"[harness] Failed to create game: {err} {details}")
            return

        print(f"[harness] Game created ({num_players} player slots)")
        print(f"[harness] Other player should run:")
        print(f"[harness]   python run.py --join {lan_ip} --race <race>")
        if base_port != DEFAULT_BASE_PORT:
            print(f"[harness]   (add --base-port {base_port})")
        print(f"[harness] Waiting for opponent to join...")

        client = Client(controller._ws)
        player_id = await client.join_game(
            race=race,
            portconfig=portconfig,
            host_ip=lan_ip,
        )

        await _run_lan_game(client, player_id)


async def join_lan_game(host_ip: str, race: Race, base_port: int, num_players: int):
    os.environ["SC2SERVERHOST"] = "0.0.0.0"

    portconfig = make_portconfig(base_port, num_players)

    print(f"[harness] Joining LAN game at {host_ip}...")

    async with SC2Process() as controller:
        client = Client(controller._ws)
        player_id = await client.join_game(
            race=race,
            portconfig=portconfig,
            host_ip=host_ip,
        )

        await _run_lan_game(client, player_id)


async def create_game_on_remote(client: Client, map_name: str, num_players: int, realtime: bool = True):
    """Issue a CreateGame request through an existing WebSocket client.

    This replicates Controller.create_game() without needing an SC2Process.
    The remote SC2 instance resolves the map path against its own Maps/ directory.
    """
    try:
        game_map = maps.get(map_name)
        map_path = str(game_map.relative_path)
    except (KeyError, SystemExit, FileNotFoundError):
        # SC2 not installed locally — construct the relative path directly.
        map_path = f"Melee/{map_name}.SC2Map"

    req = sc_pb.RequestCreateGame(
        local_map=sc_pb.LocalMap(map_path=map_path),
        realtime=realtime,
    )
    for _ in range(num_players):
        p = req.player_setup.add()
        p.type = sc_pb.Participant

    result = await client._execute(create_game=req)
    if result.create_game.HasField("error"):
        err = result.create_game.error
        details = result.create_game.error_details if result.create_game.HasField("error_details") else ""
        raise RuntimeError(f"Failed to create game: {err} {details}")
    return result


async def remote_host_game(
    ws_url: str, map_name: str, race: Race, base_port: int, num_players: int, host_ip: str,
):
    """Connect to a remote SC2 instance, create a game, join it, and run bot code."""
    portconfig = make_portconfig(base_port, num_players)

    print(f"[harness] Connecting to remote SC2 at {ws_url}...")
    session = aiohttp.ClientSession()
    ws = None
    try:
        ws = await session.ws_connect(ws_url, timeout=120)
        client = Client(ws)

        print(f"[harness] Connected. Creating game on {map_name}...")
        await create_game_on_remote(client, map_name, num_players, realtime=True)

        print(f"[harness] Game created ({num_players} player slots)")
        print(f"[harness] Waiting for opponent to join...")

        player_id = await client.join_game(
            race=race,
            portconfig=portconfig,
            host_ip=host_ip,
        )

        await _run_lan_game(client, player_id)
    finally:
        if ws is not None:
            await ws.close()
        await session.close()


async def remote_join_game(
    ws_url: str, race: Race, base_port: int, num_players: int, host_ip: str,
):
    """Connect to a remote SC2 instance, join an existing game, and run bot code."""
    portconfig = make_portconfig(base_port, num_players)

    print(f"[harness] Connecting to remote SC2 at {ws_url}...")
    session = aiohttp.ClientSession()
    ws = None
    try:
        ws = await session.ws_connect(ws_url, timeout=120)
        client = Client(ws)

        print(f"[harness] Connected. Joining game (host: {host_ip})...")
        player_id = await client.join_game(
            race=race,
            portconfig=portconfig,
            host_ip=host_ip,
        )

        await _run_lan_game(client, player_id)
    finally:
        if ws is not None:
            await ws.close()
        await session.close()


def main():
    parser = argparse.ArgumentParser(description="SC2 Bot Harness with hot-reload")
    parser.add_argument("--map", default="Simple64", help="Map name (default: Simple64)")
    parser.add_argument("--race", default="terran", choices=list(RACE_MAP.keys()), help="Bot race")
    parser.add_argument(
        "--human",
        default=None,
        choices=list(RACE_MAP.keys()),
        metavar="RACE",
        help="Play as a human against your bot (specify your race)",
    )
    parser.add_argument(
        "--difficulty",
        default="medium",
        choices=list(DIFFICULTY_MAP.keys()),
        help="Computer difficulty (ignored in --human mode)",
    )
    parser.add_argument(
        "--enemy-race",
        default="random",
        choices=list(RACE_MAP.keys()),
        help="Enemy race (ignored in --human mode)",
    )
    parser.add_argument(
        "--host",
        action="store_true",
        help="Host a LAN game (other player joins with --join)",
    )
    parser.add_argument(
        "--join",
        default=None,
        metavar="HOST_IP",
        help="Join a LAN game at the given server IP",
    )
    parser.add_argument(
        "--base-port", type=int, default=DEFAULT_BASE_PORT,
        help=f"Base port for LAN games (default: {DEFAULT_BASE_PORT})",
    )
    parser.add_argument(
        "--players", type=int, default=2,
        help="Number of players in the LAN game (default: 2)",
    )
    parser.add_argument(
        "--lan-ip", default=None,
        help="Override auto-detected LAN IP (use 127.0.0.1 for local testing)",
    )
    parser.add_argument(
        "--remote-host",
        default=None,
        metavar="WS_URL",
        help="Connect to a remote SC2 instance and host a game (e.g. ws://192.168.1.50:5000/sc2api)",
    )
    parser.add_argument(
        "--remote-join",
        default=None,
        metavar="WS_URL",
        help="Connect to a remote SC2 instance and join an existing game (e.g. ws://192.168.1.50:5001/sc2api)",
    )
    parser.add_argument(
        "--host-ip",
        default=None,
        help="IP of the SC2 instance that created the game (for P2P between SC2 instances). "
             "Auto-derived from WS URL for --remote-host; required for --remote-join.",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging from python-sc2 and SC2 process",
    )
    args = parser.parse_args()

    if args.verbose:
        logger.enable("sc2")
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")

        # python-sc2 launches SC2 with stderr=DEVNULL — undo that so we can
        # see SC2's own log output.
        import subprocess as _sp
        import sc2.sc2process as _sc2proc
        _real_popen = _sp.Popen

        def _popen_no_suppress(*args, **kwargs):
            kwargs.pop("stderr", None)
            return _real_popen(*args, **kwargs)

        _sc2proc.subprocess.Popen = _popen_no_suppress

    bot_race = RACE_MAP[args.race]

    if args.remote_host:
        host_ip = args.host_ip
        if not host_ip:
            host_ip = urlparse(args.remote_host).hostname
            print(f"[harness] --host-ip not specified, using {host_ip} from WebSocket URL")
        asyncio.run(remote_host_game(
            args.remote_host, args.map, bot_race, args.base_port, args.players, host_ip,
        ))
        return

    if args.remote_join:
        if not args.host_ip:
            parser.error("--host-ip is required with --remote-join (IP of the SC2 that created the game)")
        asyncio.run(remote_join_game(
            args.remote_join, bot_race, args.base_port, args.players, args.host_ip,
        ))
        return

    if args.host:
        asyncio.run(host_lan_game(args.map, bot_race, args.base_port, args.players, lan_ip=args.lan_ip))
        return

    if args.join:
        asyncio.run(join_lan_game(args.join, bot_race, args.base_port, args.players))
        return

    harness_bot = HarnessBot()
    harness_bot._map_name = args.map

    if args.human:
        human_race = RACE_MAP[args.human]
        harness_bot._opponent_info = f"Human {human_race.name}"
        players = [Human(human_race), Bot(bot_race, harness_bot)]
        print(f"[harness] Starting: You ({human_race.name}) vs Bot ({bot_race.name}) on {args.map}")
    else:
        enemy_race = RACE_MAP[args.enemy_race]
        difficulty = DIFFICULTY_MAP[args.difficulty]
        harness_bot._opponent_info = f"{difficulty.name} {enemy_race.name}"
        players = [Bot(bot_race, harness_bot), Computer(enemy_race, difficulty)]
        print(f"[harness] Starting: Bot ({bot_race.name}) vs {difficulty.name} {enemy_race.name} on {args.map}")

    print(f"[harness] Edit {BOT_MODULE_PATH} while the game runs. Changes apply next tick.")
    print()

    run_game(
        maps.get(args.map),
        players,
        realtime=True,
    )


if __name__ == "__main__":
    main()
