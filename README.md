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
