"""Smoke-test: launch SC2, connect, play through one game tick, then quit."""

import asyncio
import sys
import time

from loguru import logger

# Suppress python-sc2's own logging — we print our own status lines.
logger.remove()
logger.add(sys.stderr, level="WARNING")

from s2clientprotocol import sc2api_pb2 as sc_pb
from sc2 import maps
from sc2.client import Client
from sc2.data import Difficulty, Race
from sc2.player import Computer
from sc2.sc2process import SC2Process


async def _run_test(map_name: str) -> None:
    step = 0

    def ok(msg: str) -> None:
        nonlocal step
        step += 1
        print(f"  [{step}] OK  {msg}")

    print(f"[test] Starting SC2 smoke test (map: {map_name})")
    t0 = time.monotonic()

    # --- Launch & connect ---
    async with SC2Process() as controller:
        elapsed = time.monotonic() - t0
        ok(f"SC2 launched and WebSocket connected ({elapsed:.1f}s)")

        # --- Ping ---
        resp = await controller.ping()
        ping = resp.ping
        ok(f"Ping OK — game version {ping.game_version}, "
           f"base build {ping.base_build}, "
           f"data build {ping.data_version}")

        # --- Available maps ---
        map_resp = await controller.request_available_maps()
        local_maps = list(map_resp.available_maps.local_map_paths)
        ok(f"Available maps: {len(local_maps)} found")

        # --- Create game (1 participant + 1 computer) ---
        game_map = maps.get(map_name)
        computer = Computer(Race.Zerg, Difficulty.VeryEasy)

        req = sc_pb.RequestCreateGame(
            local_map=sc_pb.LocalMap(map_path=str(game_map.relative_path)),
            realtime=False,
        )
        # Participant slot (us)
        participant = req.player_setup.add()
        participant.type = sc_pb.Participant
        # Computer opponent
        comp = req.player_setup.add()
        comp.type = computer.type.value
        comp.race = computer.race.value
        comp.difficulty = computer.difficulty.value
        comp.ai_build = computer.ai_build.value

        result = await controller._execute(create_game=req)
        if result.create_game.HasField("error"):
            raise RuntimeError(
                f"CreateGame failed: {result.create_game.error} "
                f"{result.create_game.error_details}"
            )
        ok(f"Game created on map '{map_name}'")

        # --- Join game ---
        client = Client(controller._ws)
        player_id = await client.join_game(name="test", race=Race.Terran)
        ok(f"Joined game as player {player_id}")

        # --- Game info ---
        game_info = await client.get_game_info()
        ok(f"Game info: {game_info.map_size.x}x{game_info.map_size.y} map, "
           f"{len(game_info.start_locations)} start locations")

        # --- Observation ---
        obs_resp = await client.observation()
        game_loop = obs_resp.observation.observation.game_loop
        ok(f"Observation received at game_loop={game_loop}")

        # --- Data request ---
        game_data = await client.get_game_data()
        n_units = len(game_data.units)
        n_abilities = len(game_data.abilities)
        ok(f"Game data: {n_units} unit types, {n_abilities} abilities")

        # --- Step the simulation forward ---
        await client.step()
        obs_resp2 = await client.observation()
        game_loop2 = obs_resp2.observation.observation.game_loop
        ok(f"Simulation step OK — game_loop advanced {game_loop} -> {game_loop2}")

        # --- Quit ---
        await client.leave()
        await client.quit()
        ok("Left game and sent quit")

    elapsed = time.monotonic() - t0
    print(f"\n[test] All checks passed in {elapsed:.1f}s")


def run_test(map_name: str) -> int:
    """Run the smoke test. Returns 0 on success, 1 on failure."""
    try:
        asyncio.run(_run_test(map_name))
        return 0
    except Exception as e:
        logger.exception(f"Smoke test failed: {e}")
        return 1
