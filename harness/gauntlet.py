import socket
import time

from sc2 import maps
from sc2.data import Difficulty, Result
from sc2.main import run_game
from sc2.player import Bot, Computer

from .bot import BOT_PACKAGE, HarnessBot

GAUNTLET_DIFFICULTIES = [
    Difficulty.VeryEasy, Difficulty.Easy, Difficulty.Medium,
    Difficulty.MediumHard, Difficulty.Hard, Difficulty.Harder, Difficulty.VeryHard,
]


def prep_countdown(seconds, label):
    from rich.console import Console
    from rich.text import Text
    from rich.live import Live

    console = Console()
    with Live(console=console, refresh_per_second=2) as live:
        for remaining in range(seconds, 0, -1):
            live.update(Text(f"  {label} — starting in {remaining}s ", style="bold yellow"))
            time.sleep(1)
        live.update(Text(f"  {label} — GO! ", style="bold green"))
        time.sleep(0.5)


def run_gauntlet(args, bot_race):
    enemy_race = args._enemy_race
    total = len(GAUNTLET_DIFFICULTIES)

    # Leaderboard integration
    lb = None
    if args.leaderboard:
        from .leaderboard_client import LeaderboardClient
        name = args.name or socket.gethostname().split(".")[0]
        lb = LeaderboardClient(
            args.leaderboard,
            name=name,
            race=bot_race.name,
            map_name=args.map,
        )
        lb.start()
        print(f"[gauntlet] Connecting to leaderboard at {args.leaderboard} as '{name}'...")
        lb.wait_for_go()

    start_round = 0
    # winning_time: cumulative game time of victories only (used for ranking)
    winning_time = 0.0

    # Handle reconnection resume
    if lb and lb.resume_round is not None:
        start_round = lb.resume_round
        winning_time = lb.elapsed_before

    # Prep time: server's value overrides local --prep-time when connected
    prep_time = lb.prep_time if lb else args.prep_time

    print(f"[gauntlet] Starting gauntlet: {total} rounds, VeryEasy → VeryHard")
    print(f"[gauntlet] Edit files in {BOT_PACKAGE}/ while the game runs. Changes apply next tick.")
    if start_round > 0:
        print(f"[gauntlet] Resuming from round {start_round + 1}")
    print()

    round_idx = start_round
    try:
        while round_idx < total:
            difficulty = GAUNTLET_DIFFICULTIES[round_idx]
            round_num = round_idx + 1

            harness_bot = HarnessBot()
            harness_bot._map_name = args.map
            harness_bot._opponent_info = f"Gauntlet R{round_num}: {difficulty.name} {enemy_race.name}"

            if lb:
                harness_bot._harness_state.lb = lb
                lb.send_status(
                    round_idx=round_idx,
                    difficulty=difficulty.name,
                    state="playing",
                    elapsed=winning_time,
                )

            if prep_time > 0:
                label = f"Round {round_num}/{total}: {difficulty.name} {enemy_race.name}"
                prep_countdown(prep_time, label)

            print(f"[gauntlet] Round {round_num}/{total}: "
                  f"Bot ({bot_race.name}) vs {difficulty.name} {enemy_race.name} on {args.map}")

            game_start = time.time()
            players = [Bot(bot_race, harness_bot), Computer(enemy_race, difficulty)]
            result = run_game(maps.get(args.map), players, realtime=True)
            game_time = time.time() - game_start

            if result == Result.Victory:
                winning_time += game_time
                print(f"[gauntlet] Round {round_num} WON!")
                round_idx += 1
            else:
                print(f"[gauntlet] Round {round_num} lost. Retrying {difficulty.name}...")
                # don't increment — retry same level

            if lb:
                lb.send_round_complete(
                    round_idx=round_idx if result == Result.Victory else round_idx,
                    difficulty=difficulty.name,
                    result=result.name if result else "Unknown",
                    game_time=game_time,
                    elapsed=winning_time,
                )

        print(f"[gauntlet] GAUNTLET COMPLETE! All {total} rounds won!")
    finally:
        if lb:
            lb.send_status(
                round_idx=min(round_idx, total - 1),
                difficulty=GAUNTLET_DIFFICULTIES[min(round_idx, total - 1)].name,
                state="completed" if round_idx >= total else "disconnected",
                elapsed=winning_time,
            )
            # Give the send a moment to flush
            time.sleep(0.5)
            lb.close()
