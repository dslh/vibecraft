import asyncio
import os
import socket
import time

from sc2 import maps
from sc2.client import Client
from sc2.data import Race, Result
from sc2.main import _play_game_ai
from sc2.player import Human
from sc2.sc2process import SC2Process

from .bot import BOT_PACKAGE, HarnessBot
from .ports import DEFAULT_BASE_PORT, make_portconfig
from .tunnel import Tunnel


def get_lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


async def _run_lan_game(client, player_id, lb=None, map_name="", opponent_info=""):
    """Shared game loop for both host and join LAN paths."""
    harness_bot = HarnessBot()
    harness_bot._map_name = map_name
    harness_bot._opponent_info = opponent_info
    if lb:
        harness_bot._harness_state.lb = lb

    print(f"[harness] Joined as player {player_id}. Game starting!")
    print(f"[harness] Edit files in {BOT_PACKAGE}/ while the game runs. Changes apply next tick.")
    print()

    game_start = time.time()
    try:
        result = await _play_game_ai(client, player_id, harness_bot, realtime=True, game_time_limit=None)
    except (KeyboardInterrupt, SystemExit, asyncio.CancelledError):
        if not harness_bot._harness_state.game_ended:
            from .state_writer import write_game_ended_marker
            write_game_ended_marker("ABANDONED")
        raise
    game_time = time.time() - game_start

    print(f"[harness] Game ended: {result}")

    try:
        await client.leave()
    except Exception:
        pass

    return result, game_time


async def _join_game_checked(client, race, portconfig):
    """Call join_game and check the response for errors.

    python-sc2's Client.join_game doesn't inspect the error field, so a
    failed join (wrong map, checksum mismatch, etc.) silently returns
    player_id 0.  We call _execute directly and raise on failure.
    """
    from sc2.protocol import sc_pb

    req = sc_pb.RequestJoinGame(
        race=race.value,
        options=sc_pb.InterfaceOptions(
            raw=True, score=True, show_cloaked=True,
            show_burrowed_shadows=True, raw_crop_to_playable_area=False,
            show_placeholders=True,
        ),
    )
    req.server_ports.game_port = portconfig.server[0]
    req.server_ports.base_port = portconfig.server[1]
    for ppc in portconfig.players:
        p = req.client_ports.add()
        p.game_port = ppc[0]
        p.base_port = ppc[1]
    req.host_ip = "127.0.0.1"

    result = await client._execute(join_game=req)
    jr = result.join_game

    if jr.HasField("error"):
        _JOIN_ERRORS = {
            1: "MissingParticipation — no race or observer id specified",
            2: "InvalidObservedPlayerId",
            3: "MissingOptions — interface options not set",
            4: "MissingPorts — server_ports/client_ports not set",
            5: "GameFull — all player slots are taken",
            6: "LaunchError — SC2 failed to launch the game",
            7: "FeatureUnsupported — multiplayer not supported in this SC2 build",
            8: "NoSpaceForUser",
            9: "MapDoesNotExist — map file not found on this machine",
            10: "CannotOpenMap — map file exists but could not be loaded",
            11: "ChecksumError — SC2 version or map mismatch between players",
            12: "NetworkError — game port communication failed",
            13: "OtherError",
        }
        msg = _JOIN_ERRORS.get(jr.error, f"unknown error {jr.error}")
        details = jr.error_details if jr.HasField("error_details") else ""
        if details:
            msg = f"{msg} ({details})"
        raise RuntimeError(f"join_game failed: {msg}")

    client._game_result = None
    client._player_id = jr.player_id
    return jr.player_id


async def host_lan_game(map_name: str, race: Race, base_port: int, num_players: int, lan_ip: str | None = None):
    # SC2 must listen on all interfaces, not just loopback — otherwise it
    # may skip game port networking entirely.
    os.environ["SC2SERVERHOST"] = "0.0.0.0"

    if lan_ip is None:
        lan_ip = get_lan_ip()

    # Game ports start after the tunnel port (base_port)
    portconfig = make_portconfig(base_port + 1, num_players)

    print(f"[harness] Hosting LAN game on {map_name}...")
    tunnel = await Tunnel.listen(base_port)

    print(f"[harness] Other player should run:")
    print(f"[harness]   python run.py --join {lan_ip} --race <race>")
    if base_port != DEFAULT_BASE_PORT:
        print(f"[harness]   (add --base-port {base_port})")
    print(f"[harness] Waiting for opponent to connect...")

    await tunnel.wait_for_peer()
    print(f"[harness] Opponent connected!")

    try:
        async with SC2Process() as sc2:
            players = [Human(Race.Random) for _ in range(num_players)]
            result = await sc2.create_game(maps.get(map_name), players, realtime=True)

            if result.create_game.HasField("error"):
                err = result.create_game.error
                details = result.create_game.error_details if result.create_game.HasField("error_details") else ""
                print(f"[harness] Failed to create game: {err} {details}")
                return

            print(f"[harness] Game created. Starting...")

            await tunnel.start_relays()

            client = Client(sc2._ws)
            player_id = await client.join_game(
                race=race, portconfig=portconfig, host_ip="127.0.0.1"
            )

            await _run_lan_game(client, player_id)
    finally:
        await tunnel.stop()


async def join_lan_game(host_ip: str, race: Race, base_port: int, num_players: int):
    os.environ["SC2SERVERHOST"] = "0.0.0.0"

    # Game ports must match what the host uses
    portconfig = make_portconfig(base_port + 1, num_players)

    print(f"[harness] Connecting to {host_ip}:{base_port}...")
    tunnel = await Tunnel.connect(host_ip, base_port)
    print(f"[harness] Connected!")

    try:
        async with SC2Process() as sc2:
            await tunnel.start_relays()

            client = Client(sc2._ws)
            player_id = await _join_game_checked(client, race, portconfig)

            await _run_lan_game(client, player_id)
    finally:
        await tunnel.stop()


async def host_pvp_game(map_name: str, race: Race, base_port: int,
                        opponent_name: str = "", lb=None) -> tuple[Result | None, float]:
    """Host a PvP game coordinated by the leaderboard server."""
    os.environ["SC2SERVERHOST"] = "0.0.0.0"

    portconfig = make_portconfig(base_port + 1, 2)

    print(f"[arena] Hosting PvP game on {map_name}...")
    tunnel = await Tunnel.listen(base_port)
    print(f"[arena] Waiting for opponent to connect...")

    await tunnel.wait_for_peer()
    print(f"[arena] Opponent connected!")

    try:
        async with SC2Process() as sc2:
            players = [Human(Race.Random) for _ in range(2)]
            create_result = await sc2.create_game(maps.get(map_name), players, realtime=True)

            if create_result.create_game.HasField("error"):
                err = create_result.create_game.error
                details = create_result.create_game.error_details if create_result.create_game.HasField("error_details") else ""
                print(f"[arena] Failed to create game: {err} {details}")
                return None, 0.0

            print(f"[arena] Game created. Starting...")

            await tunnel.start_relays()

            client = Client(sc2._ws)
            player_id = await client.join_game(
                race=race, portconfig=portconfig, host_ip="127.0.0.1"
            )

            return await _run_lan_game(client, player_id, lb=lb,
                                       map_name=map_name,
                                       opponent_info=f"PvP vs {opponent_name}")
    finally:
        await tunnel.stop()


async def join_pvp_game(host_ip: str, map_name: str, race: Race, base_port: int,
                        opponent_name: str = "", lb=None) -> tuple[Result | None, float]:
    """Join a PvP game coordinated by the leaderboard server."""
    os.environ["SC2SERVERHOST"] = "0.0.0.0"

    portconfig = make_portconfig(base_port + 1, 2)

    print(f"[arena] Connecting to {host_ip}:{base_port}...")
    tunnel = await Tunnel.connect(host_ip, base_port)
    print(f"[arena] Connected!")

    try:
        async with SC2Process() as sc2:
            await tunnel.start_relays()

            client = Client(sc2._ws)
            player_id = await _join_game_checked(client, race, portconfig)

            return await _run_lan_game(client, player_id, lb=lb,
                                       map_name=map_name,
                                       opponent_info=f"PvP vs {opponent_name}")
    finally:
        await tunnel.stop()
