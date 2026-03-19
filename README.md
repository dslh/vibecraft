# SC2 Bot Harness

A hot-reloading harness for developing StarCraft II bots interactively. Edit your bot logic while a game is running — changes take effect on the next game tick.

## Setup

Requires StarCraft II installed with maps in the `Maps/` subdirectory.

### Quick start

The setup script clones the repo, installs dependencies, and downloads the Melee map pack:

```bash
# macOS / Linux:
curl -fsSL https://raw.githubusercontent.com/dslh/vibecraft/main/setup.sh | sh

# Windows (PowerShell):
irm https://raw.githubusercontent.com/dslh/vibecraft/main/setup.ps1 | iex
```

Then verify and run:

```bash
cd vibecraft
.venv/bin/python3 run.py --test   # smoke test
.venv/bin/python3 run.py          # start a game
```

### Manual setup

If you prefer to set things up yourself:

**macOS / Linux:**

```bash
git clone https://github.com/dslh/vibecraft.git && cd vibecraft
git clone https://github.com/dslh/python-sc2.git
git clone https://github.com/Blizzard/s2client-proto.git
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

**Windows (PowerShell):**

```powershell
git clone https://github.com/dslh/vibecraft.git; cd vibecraft
git clone https://github.com/dslh/python-sc2.git
git clone https://github.com/Blizzard/s2client-proto.git
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

### Verifying your setup

`--test` runs a quick smoke test that launches SC2, connects over WebSocket, creates and joins a game, reads one observation, steps the simulation, and shuts down cleanly. It exits 0 on success, 1 on failure.

```bash
.venv/bin/python3 run.py --test              # uses default map (Simple64)
.venv/bin/python3 run.py --test --map Acropolis  # test with a specific map
.venv/bin/python3 run.py --test --proton     # test a Proton/Linux setup
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

## How it works

`run.py` launches SC2 in realtime mode and runs a `HarnessBot` that, on every game tick:

1. Scans all `.py` files in `bot_src/` for changes (by mtime)
2. If any file changed, purges all `bot_src` modules from `sys.modules` and re-imports fresh
3. Finds your `BotAI` subclass, synthesizes a new class combining it with the harness, and swaps `self.__class__`
4. Calls your `on_step(self, iteration)` method (and any callbacks you define)
5. Catches exceptions gracefully — a syntax error or crash skips that tick, the game keeps going

This means you can split your bot across as many files as you want inside `bot_src/`. Edit any file and save — all changes take effect together on the next tick.

## Writing your bot

Your bot code lives in `bot_src/`. The entry point is `bot_src/bot.py`, which must define a `BotAI` subclass:

```python
from sc2.bot_ai import BotAI
from sc2.ids.unit_typeid import UnitTypeId

class MyBot(BotAI):
    async def on_step(self, iteration):
        for worker in self.workers.idle:
            worker.gather(self.mineral_field.closest_to(worker))
```

`self` is the live [python-sc2 `BotAI`](https://github.com/BurnySc2/python-sc2) instance. Key attributes:

| Category | Attributes |
|----------|-----------|
| Your units | `self.workers`, `self.units`, `self.structures`, `self.townhalls`, `self.gas_buildings` |
| Enemy | `self.enemy_units`, `self.enemy_structures` |
| Resources | `self.minerals`, `self.vespene`, `self.supply_used`, `self.supply_left` |
| Map | `self.start_location`, `self.enemy_start_locations`, `self.game_info.map_center`, `self.mineral_field`, `self.vespene_geyser`, `self.expansion_locations_list` |
| Time | `self.time` (seconds), `self.time_formatted`, `self.state.game_loop` |
| Queries | `self.already_pending(UnitTypeId.X)`, `self.can_afford(UnitTypeId.X)` |

Commands are issued directly on units:

```python
worker.gather(self.mineral_field.closest_to(worker))
worker.attack(target)
unit.move(position)
townhall.train(UnitTypeId.SCV)
self.do(worker.build(UnitTypeId.BARRACKS, position))
```

**Instance variables** on `self` persist across hot-reloads. Use them to keep state between ticks:

```python
class MyBot(BotAI):
    async def on_step(self, iteration):
        if not hasattr(self, 'rush_sent'):
            self.rush_sent = False
        if self.supply_army > 10 and not self.rush_sent:
            for unit in self.units:
                unit.attack(self.enemy_start_locations[0])
            self.rush_sent = True
```

### Logging

Use `self.log()` to print messages from your bot. They show up in the dashboard Events panel and are written to `log/bot.log` with the in-game timestamp:

```python
self.log("Expanding to natural")
self.log(f"Enemy army spotted: {self.enemy_units.amount} units")
```

### Callbacks

All standard python-sc2 callbacks are supported:

```python
class MyBot(BotAI):
    async def on_start(self):
        ...  # once at game start

    async def on_step(self, iteration):
        ...  # every tick

    async def on_end(self, game_result):
        ...  # when game ends

    async def on_unit_destroyed(self, unit_tag):
        ...

    async def on_unit_took_damage(self, unit, amount_damage_taken):
        ...

    async def on_building_construction_complete(self, unit):
        ...

    async def on_upgrade_complete(self, upgrade):
        ...

    async def on_enemy_unit_entered_vision(self, unit):
        ...

    def on_reload(self):
        ...  # fires on every hot-reload (optional, harness-specific)
```

### Splitting your bot across files

As your bot grows, split logic into separate modules inside `bot_src/`:

```
bot_src/
  __init__.py
  bot.py          # entry point — defines BotAI subclass
  economy.py      # economy management
  army.py         # army control
  strategy.py     # high-level decisions
```

Import them in `bot.py` using relative imports:

```python
from .economy import manage_economy
from .army import manage_army

class MyBot(BotAI):
    async def on_step(self, iteration):
        manage_economy(self)
        manage_army(self)
```

Saving any file in `bot_src/` triggers a full reload — all modules are re-imported together.

## Sending commands to a running game

Use `cmd.py` to execute one-off Python snippets inside the running game loop. Code runs on the next game tick with `self` (or `bot`) bound to the BotAI instance. Common imports (`UnitTypeId`, `AbilityId`, `UpgradeId`, `Race`, `Point2`) are pre-loaded.

```bash
# Inspect game state (last expression is auto-printed)
./cmd.py 'self.minerals'
./cmd.py 'len(self.workers.idle)'

# Print statements work too
./cmd.py 'print(f"Supply: {self.supply_used}/{self.supply_cap}")'

# Issue orders
./cmd.py 'await self.build(UnitTypeId.SUPPLYDEPOT, near=self.townhalls.first.position)'
./cmd.py 'self.workers.idle.first.attack(self.enemy_start_locations[0])'

# Multi-line via stdin
echo 'for w in self.workers.idle:
    w.gather(self.mineral_field.closest_to(w))' | ./cmd.py
```

stdout, stderr, and errors are captured and returned to the caller. Exit code is 0 on success, 1 on error or timeout (30s). `await` is supported for async methods.

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

Both players edit `bot_src/` locally with full hot-reload, same as single-player mode.

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
