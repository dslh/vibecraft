"""
SC2 Bot Harness — hot-reloads bot_src/ on every game tick.

Usage:
    python run.py [--map MAP_NAME] [--race RACE] [--difficulty DIFFICULTY]
    python run.py --gauntlet [--prep-time 10]     # escalate VeryEasy → VeryHard
    python run.py --gauntlet --leaderboard HOST:PORT --name alice  # multiplayer gauntlet
    python run.py --human protoss --race zerg     # play against your own bot
    python run.py --host --race terran            # host a LAN game
    python run.py --join 192.168.1.100 --race zerg  # join a LAN game
    python run.py --proton --race terran             # launch SC2 via Proton (Linux)

While the game is running, edit bot_src/ and save. Your changes take effect
on the next tick. If bot code has a syntax error or crashes, the harness
logs the error and skips that tick — the game keeps running.
"""

import argparse
import asyncio
import sys

from loguru import logger

from sc2.data import Difficulty, Race

from harness.ports import DEFAULT_BASE_PORT

RACE_MAP = {r.name.lower(): r for r in Race}
DIFFICULTY_MAP = {d.name.lower(): d for d in Difficulty}


def main():
    from dotenv import load_dotenv
    load_dotenv()

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
        "--gauntlet",
        action="store_true",
        help="Gauntlet mode: escalate difficulty from VeryEasy to VeryHard, stopping on first loss",
    )
    parser.add_argument(
        "--prep-time",
        type=int,
        default=None,
        metavar="SECONDS",
        help="Countdown before each game starts (computer games only). "
             "Omit for interactive 'press enter' prompt between matches.",
    )
    parser.add_argument(
        "--leaderboard",
        default=None,
        metavar="HOST:PORT",
        help="Connect to a leaderboard server for multiplayer gauntlet (e.g. localhost:8080)",
    )
    parser.add_argument(
        "--name",
        default=None,
        help="Player name for the leaderboard (default: hostname)",
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
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging from python-sc2 and SC2 process",
    )
    parser.add_argument(
        "--proton",
        action="store_true",
        help="Launch SC2 through Proton (for Linux/Steam Deck)",
    )
    parser.add_argument(
        "--steam-path",
        default=None,
        metavar="PATH",
        help="Steam installation root (default: auto-detect ~/.steam/steam or ~/.local/share/Steam)",
    )
    parser.add_argument(
        "--proton-version",
        default=None,
        metavar="VERSION",
        help='Proton version directory name (default: auto-detect latest, e.g. "Proton 10.0")',
    )
    parser.add_argument(
        "--sc2-path",
        default=None,
        metavar="PATH",
        help="SC2 installation path (default: auto-detect within Steam library)",
    )
    args = parser.parse_args()

    if args.proton:
        from harness.proton import setup_proton
        setup_proton(args)

    # Deferred imports — these trigger sc2 path resolution, so Proton env
    # vars must be configured first.
    from sc2 import maps
    from sc2.main import run_game
    from sc2.player import Bot, Computer, Human

    from harness.bot import BOT_PACKAGE, HarnessBot
    from harness.gauntlet import prep_countdown, run_gauntlet
    from harness.lan import host_lan_game, join_lan_game

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

    if args.gauntlet and args.human:
        parser.error("--gauntlet cannot be used with --human")
    if args.leaderboard and not args.gauntlet:
        parser.error("--leaderboard requires --gauntlet")

    if args.host:
        asyncio.run(host_lan_game(args.map, bot_race, args.base_port, args.players, lan_ip=args.lan_ip))
        return

    if args.join:
        asyncio.run(join_lan_game(args.join, bot_race, args.base_port, args.players))
        return

    if args.gauntlet:
        # Stash resolved enemy race on args so gauntlet.py can access it
        args._enemy_race = RACE_MAP[args.enemy_race]
        run_gauntlet(args, bot_race)
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

    print(f"[harness] Edit files in {BOT_PACKAGE}/ while the game runs. Changes apply next tick.")
    print()

    if not args.human:
        label = f"{args.map}: {difficulty.name} {enemy_race.name}"
        if args.prep_time is not None and args.prep_time > 0:
            prep_countdown(args.prep_time, label)
        elif args.prep_time is None:
            input(f"  {label} — Press enter to start.")

    run_game(
        maps.get(args.map),
        players,
        realtime=True,
    )


if __name__ == "__main__":
    main()
