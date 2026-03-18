# SC2 Bot Development Workspace

This workspace is for developing a StarCraft II bot using the SC2 API. The bot is to be developed in real-time as the game is played.

## Project layout

- `bot_src/` — The bot logic (hot-reloaded at runtime).
- `harness/` — Hot-reloading harness internals.
- `leaderboard.py` — Gauntlet leaderboard server (web dashboard + WebSocket coordinator).
- `cheatsheets/` — API reference files.
- `python-sc2/` — Fork of [BurnySc2/python-sc2](https://github.com/BurnySc2/python-sc2), the Python client library for the SC2 API. Installed as an editable package. Gitignored — cloned by the setup script.
- `s2client-proto/` — The official SC2 API protobuf definitions repo, for reference. Gitignored — cloned by the setup script.

## How the system works

StarCraft II exposes a protobuf-over-WebSocket API. The game client itself acts as the server — you launch it with `-listen` and `-port` flags and connect to `ws://host:port/sc2api`. python-sc2 handles all of this: launching SC2, connecting, deserializing game state, and sending actions.

The harness (`run.py`) builds on python-sc2 by subclassing `BotAI`. On every game tick it scans all `.py` files in `bot_src/` for changes and hot-reloads the entire package if anything changed. The user defines a standard `BotAI` subclass in `bot_src/bot.py` with `on_step`, callbacks like `on_unit_destroyed`, etc. The harness calls these as unbound methods on the live bot instance, so `self` is the real BotAI with all game state. Instance variables on `self` persist across reloads. An optional `on_reload` hook fires on every hot-reload. Errors in bot code are caught and logged without crashing the game.

## Running

```bash
.venv/bin/python3 run.py [--map Simple64] [--race terran] [--difficulty medium]
```

The game runs in realtime mode. Edit files in `bot_src/` in another window and save — changes take effect on the next tick.

## API cheatsheets

`cheatsheets/` contains pre-written API reference files. **Read these instead of the python-sc2 source** to orient yourself quickly — especially important when the game is already running.

- `api.md` — Shared API: BotAI state, Unit/Units classes, economy, building placement, tech progress, map queries, events, debug commands, common patterns. Read this every session.
- `terran.md` — Terran-specific: add-ons, flying structures, Orbital Command, unit transforms, unit type IDs, upgrades.
- `protoss.md` — Protoss-specific: power fields, warpgate, chrono boost, archon merge, unit type IDs, upgrades.
- `zerg.md` — Zerg-specific: larva, drone sacrifice, creep, burrow, hatch progression, morphs, unit type IDs, upgrades.

At session start, read `api.md` + the race file matching the current game. This should be sufficient for writing bot code without consulting the python-sc2 source.

## Live game state files

When a game is running, the harness writes live state to `log/`. Read these to understand the current game without alt-tabbing or asking the user.

- `log/game.txt` — Static metadata (race, map, opponent, start positions). Written once at game start.
- `log/snapshot.txt` — Current game state: resources, supply, army, structures, production queue, upgrades, enemy units/structures. Rewritten every ~2 seconds.
- `log/events.log` — Append-only timestamped event stream (units lost/killed, buildings completed, upgrades, reloads, errors). Covers the entire game. Use `Read` with `offset`/`limit` to grab the tail.
- `log/errors.log` — Append-only full tracebacks with tick/time headers. Read this first when debugging bot crashes.
- `log/bot.log` — Append-only bot log messages from `self.log("message")` calls in bot code, timestamped with in-game time.

The `log/` directory is recreated fresh each game and is gitignored.

## Sending commands to a running game

`cmd.py` executes one-off Python snippets inside the running game loop on the next tick. `self` (or `bot`) is the BotAI instance. Common imports (`UnitTypeId`, `AbilityId`, `UpgradeId`, `Race`, `Point2`) are pre-loaded.

```bash
.venv/bin/python3 cmd.py 'self.minerals'                  # expression auto-printed
.venv/bin/python3 cmd.py 'print(self.workers.idle.amount)' # explicit print
.venv/bin/python3 cmd.py 'await self.build(UnitTypeId.SUPPLYDEPOT, near=self.townhalls.first.position)'
```

stdout/stderr/errors are captured and returned. Exit code 0 on success, 1 on error or timeout. Use this to inspect game state or issue one-off orders without modifying bot_src/.

## Key files

- `run.py` — CLI entry point. Parses args, dispatches to harness modules.
- `harness/bot.py` — HarnessBot class: hot-reload logic, event delegation, command execution.
- `bot_src/bot.py` — The bot entry point. Defines a `BotAI` subclass with `on_step`, callbacks, etc. Bot code can be split across multiple files in `bot_src/`.
- `python-sc2/sc2/bot_ai.py` — The `BotAI` class that `bot` is an instance of. Reference for available state and methods.
- `python-sc2/sc2/main.py` — Game loop internals (`_play_game_ai`, `run_game`).
- `python-sc2/sc2/unit.py` — Unit methods (attack, move, gather, build, train, etc.).
- `python-sc2/sc2/ids/unit_typeid.py` — `UnitTypeId` enum (e.g. `UnitTypeId.SCV`, `UnitTypeId.BARRACKS`).
- `python-sc2/sc2/ids/ability_id.py` — `AbilityId` enum for raw ability commands.

## SC2 installation

- SC2 is installed at `/Applications/StarCraft II/`
- Maps are in `/Applications/StarCraft II/Maps/Melee/` (Melee pack)
- Game version: Base95841

## Dependencies

See `requirements.txt`. The setup script creates a venv and installs everything, including python-sc2 in editable mode.
