import os
import socket

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
