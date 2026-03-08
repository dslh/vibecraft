import asyncio
import os
import socket

import aiohttp
from s2clientprotocol import sc2api_pb2 as sc_pb

from sc2 import maps
from sc2.client import Client
from sc2.data import Race
from sc2.main import _play_game_ai
from sc2.player import Human
from sc2.sc2process import SC2Process

from .bot import BOT_PACKAGE, HarnessBot
from .ports import DEFAULT_BASE_PORT, make_portconfig


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
    print(f"[harness] Edit files in {BOT_PACKAGE}/ while the game runs. Changes apply next tick.")
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
