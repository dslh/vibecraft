# Windows Setup Guide

## Prerequisites

### 1. StarCraft II

Install SC2 from [Battle.net](https://battle.net). The free Starter Edition works — you don't need to buy the game. It should install to the default location:

```
C:\Program Files (x86)\StarCraft II
```

If you install it elsewhere, set the `SC2PATH` environment variable to the install directory.

### 2. Maps

The bot defaults to `Simple64` but can use any melee map. Download the **Melee** map pack from Blizzard's [map repository](https://github.com/Blizzard/s2client-proto#map-packs) and extract the `.SC2Map` files into:

```
C:\Program Files (x86)\StarCraft II\Maps\
```

Maps can be in subdirectories (e.g. `Maps\Melee\Simple64.SC2Map`) — the bot searches one level deep.

### 3. Python 3.10+

Install Python **3.10 or newer** from [python.org](https://www.python.org/downloads/). During installation, check **"Add Python to PATH"**.

Verify it works:

```
python --version
```

### 4. Git

Install Git from [git-scm.com](https://git-scm.com/downloads/win). The defaults are fine.

### 5. Terminal

You need a terminal that supports ANSI colors and isn't painful to use. Pick one:

- **Windows Terminal** — comes preinstalled on Windows 11, or grab it from the Microsoft Store. Recommended.
- **VS Code integrated terminal** — works well if you're already using VS Code.

Avoid plain `cmd.exe` — it works but the experience is poor.

## Project Setup

### Clone the repos

```bash
mkdir sc2
cd sc2
git clone https://github.com/dslh/vibecraft.git bot
git clone https://github.com/dslh/python-sc2.git
```

### Create the venv and install dependencies

```bash
cd bot
python -m venv .venv
.venv\Scripts\pip install -e ..\python-sc2
.venv\Scripts\pip install claude-agent-sdk mcp rich prompt_toolkit
```

This installs `python-sc2` in editable mode along with all its dependencies (aiohttp, protobuf, numpy, scipy, etc.), plus the chat interface dependencies.

### Verify it works

```bash
.venv\Scripts\python run.py --map Simple64 --race terran --difficulty medium
```

SC2 should launch, connect, and start a game. The bot hot-reloads code from `bot_src/` on every tick — edit and save files to update behavior mid-game.

## AI-Assisted Development

If you already have an agentic coding tool installed (Claude Code, Cursor, Windsurf, etc.), you're all set — just open the project in it. The `CLAUDE.md` in the project root has full documentation on the harness, cheatsheets, live log files, and the `cmd.py` tool for sending one-off commands into a running game.

If you don't, the project includes a built-in chat interface. Open a second terminal in the `bot/` directory and run:

```bash
.venv\Scripts\python chat.py
```

On first run it will prompt for an [Anthropic API key](https://console.anthropic.com/) and save it to `.env`. The chat agent can read game state, edit bot code, and execute commands in a running game — all through a conversational interface.

## Troubleshooting

- **"Map not found"** — Make sure `.SC2Map` files are in `StarCraft II\Maps\` (or a subdirectory). The map name passed to `--map` must match the filename without extension.
- **SC2 doesn't launch** — Check that `SC2_x64.exe` exists in `StarCraft II\Versions\BaseXXXXX\`. If you have multiple `Base*` folders, the bot uses the latest one.
- **"SC2 installation not found"** — Set `SC2PATH=C:\Program Files (x86)\StarCraft II` as an environment variable.
- **Python import errors** — Make sure you installed python-sc2 into the bot's venv, not your system Python. Use `.venv\Scripts\python`, not just `python`.
