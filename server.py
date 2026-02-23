"""
SC2 LAN Game Server — creates a multiplayer game and observes.

Usage:
    python server.py [--map Simple64] [--players 2] [--base-port 5100]

Run this on the big-screen machine. Players join with:
    python run.py --join <this machine's IP> --race <race>
"""

import argparse
import asyncio
import os
import socket

from sc2 import maps
from sc2.client import Client
from sc2.data import Race
from sc2.player import Human
from sc2.sc2process import SC2Process

from ports import DEFAULT_BASE_PORT, make_portconfig


def get_lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


async def run_server(map_name: str, num_players: int, base_port: int):
    os.environ["SC2SERVERHOST"] = "0.0.0.0"

    portconfig = make_portconfig(base_port, num_players)
    lan_ip = get_lan_ip()

    print("[server] Launching SC2...")

    async with SC2Process() as controller:
        players = [Human(Race.Random) for _ in range(num_players)]
        result = await controller.create_game(maps.get(map_name), players, realtime=True)

        if result.create_game.HasField("error"):
            print(f"[server] Failed to create game: {result.create_game.error}")
            if result.create_game.HasField("error_details"):
                print(f"[server] Details: {result.create_game.error_details}")
            return

        print(f"[server] Game created: {map_name} ({num_players} player slots)")
        print(f"[server] Players should run:")
        print(f"[server]   python run.py --join {lan_ip} --race <race>")
        if base_port != DEFAULT_BASE_PORT:
            print(f"[server]   (add --base-port {base_port})")
        print(f"[server] Waiting for {num_players} players to join...")

        # Join as observer — this blocks until all participant slots are filled
        client = Client(controller._ws)
        await client.join_game(
            observed_player_id=0,
            portconfig=portconfig,
            host_ip=lan_ip,
        )

        print("[server] Game started!")
        print()

        # Observer loop — poll until game ends
        while not client._game_result:
            await client.observation()

        print()
        print("[server] Game over!")
        for player_id, player_result in client._game_result.items():
            print(f"[server]   Player {player_id}: {player_result}")


def main():
    parser = argparse.ArgumentParser(description="SC2 LAN Game Server")
    parser.add_argument("--map", default="Simple64", help="Map name (default: Simple64)")
    parser.add_argument("--players", type=int, default=2, help="Number of players (default: 2)")
    parser.add_argument(
        "--base-port", type=int, default=DEFAULT_BASE_PORT,
        help=f"Base port (default: {DEFAULT_BASE_PORT})",
    )
    args = parser.parse_args()

    asyncio.run(run_server(args.map, args.players, args.base_port))


if __name__ == "__main__":
    main()
