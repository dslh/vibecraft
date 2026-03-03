# SC2 Bot Harness

A hot-reloading harness for developing StarCraft II bots interactively. Edit your bot logic while a game is running — changes take effect on the next game tick.

## Setup

Requires StarCraft II installed at `/Applications/StarCraft II/` with maps in the `Maps/` subdirectory.

```bash
# Create venv and install dependencies (one-time)
python3 -m venv .venv
.venv/bin/pip install -e ../python-sc2

# Run a game
.venv/bin/python3 run.py
```

### Options

```
--map NAME         Map to play on (default: Simple64)
--race RACE        Bot race: terran, zerg, protoss, random (default: terran)
--enemy-race RACE  Enemy race (default: random)
--difficulty DIFF   AI difficulty: veryeasy, easy, medium, mediumhard,
                   hard, harder, veryhard, cheatvision, cheatmoney,
                   cheatinsane (default: medium)
```

### Available maps

Melee pack (installed in `Maps/Melee/`):

- **Simple64, Simple96, Simple128** — proper 1v1 maps with ramps, expansions, etc.
- **Flat32, Flat48, Flat64, Flat96, Flat128** — flat open maps, good for testing
- **Empty128** — completely empty

## How it works

`run.py` launches SC2 in realtime mode and runs a `HarnessBot` that, on every game tick:

1. Checks if `bot.py` has been modified on disk
2. If so, hot-reloads it via `importlib.reload()`
3. Calls your `play(bot, memory)` function
4. Catches exceptions gracefully — a syntax error or crash skips that tick, the game keeps going

## Writing your bot

All your logic goes in `bot.py`. Implement one function:

```python
def play(bot, memory):
    ...
```

**`bot`** is a [python-sc2 `BotAI`](https://github.com/BurnySc2/python-sc2) instance. Key attributes:

| Category | Attributes |
|----------|-----------|
| Your units | `bot.workers`, `bot.units`, `bot.structures`, `bot.townhalls`, `bot.gas_buildings` |
| Enemy | `bot.enemy_units`, `bot.enemy_structures` |
| Resources | `bot.minerals`, `bot.vespene`, `bot.supply_used`, `bot.supply_left` |
| Map | `bot.start_location`, `bot.enemy_start_locations`, `bot.game_info.map_center`, `bot.mineral_field`, `bot.vespene_geyser`, `bot.expansion_locations_list` |
| Time | `bot.time` (seconds), `bot.time_formatted`, `bot.state.game_loop` |
| Queries | `bot.already_pending(UnitTypeId.X)`, `bot.can_afford(UnitTypeId.X)` |

Commands are issued directly on units:

```python
worker.gather(bot.mineral_field.closest_to(worker))
worker.attack(target)
unit.move(position)
townhall.train(UnitTypeId.SCV)
bot.do(worker.build(UnitTypeId.BARRACKS, position))
```

**`memory`** is a `dict` that persists across hot-reloads. Use it to keep state between ticks even as you edit your code:

```python
def play(bot, memory):
    memory.setdefault("rush_sent", False)
    if bot.supply_army > 10 and not memory["rush_sent"]:
        for unit in bot.units:
            unit.attack(bot.enemy_start_locations[0])
        memory["rush_sent"] = True
```

`play()` can also be `async` if you need python-sc2's async methods (e.g. `find_placement`).

## Multiplayer

### LAN mode

Two players on the same network, each running SC2 locally:

```bash
# Player 1 (host):
.venv/bin/python3 run.py --host --race terran

# Player 2 (join — use the IP printed by the host):
.venv/bin/python3 run.py --join 192.168.1.100 --race zerg
```

### Remote mode

Bot code runs on each player's machine; SC2 instances run on a shared server (or any machine). This decouples bot development from SC2 hosting — useful for live coding competitions.

**On the server machine**, launch SC2 instances:

```bash
.venv/bin/python3 server.py
```

This starts two SC2 instances and prints their WebSocket URLs and the commands each player should run.

**On each player's machine**, connect to a remote SC2 instance:

```bash
# Player 1 (creates the game):
.venv/bin/python3 run.py --remote-host ws://SERVER:PORT/sc2api --race terran

# Player 2 (joins the game — use the host-ip printed by server.py):
.venv/bin/python3 run.py --remote-join ws://SERVER:PORT/sc2api --host-ip SERVER --race zerg
```

The `--host-ip` tells SC2 where the game-hosting instance lives so the two SC2 instances can sync with each other. For `--remote-host` it's auto-derived from the WebSocket URL; for `--remote-join` it must be specified explicitly.

Both players edit `bot.py` locally with full hot-reload, same as single-player mode.

#### server.py options

```
--instances N   Number of SC2 instances to launch (default: 2)
--verbose, -v   Enable debug logging
```

### Gauntlet mode

Play 7 escalating rounds (VeryEasy → VeryHard). Losses retry the same difficulty until you win or Ctrl+C:

```bash
.venv/bin/python3 run.py --gauntlet --race terran
```

Add a countdown between rounds:

```bash
.venv/bin/python3 run.py --gauntlet --race terran --prep-time 10
```

### Multiplayer gauntlet (leaderboard)

Run a [leaderboard server](../leaderboard/) and connect multiple players for a synchronized race through the gauntlet. Each player runs their own gauntlet against the AI — the leaderboard tracks who gets furthest, fastest.

```bash
# On the server:
python ../leaderboard/server.py --prep-time 10

# Each player:
.venv/bin/python3 run.py --gauntlet --leaderboard HOST:8080 --name alice --race terran
```

Players connect and appear in the lobby. The operator presses Enter to start everyone simultaneously. A live web dashboard at `http://HOST:8080` shows standings.

If a player disconnects and reconnects with the same `--name`, they resume from where they left off. If the leaderboard server goes down, games continue uninterrupted.
