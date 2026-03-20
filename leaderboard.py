#!/usr/bin/env python3
"""
Gauntlet Leaderboard Server.

Coordinates multiplayer gauntlet runs. Players connect via WebSocket,
the operator starts the gauntlet from stdin, and a live web dashboard
shows standings.

Usage:
    python server.py [--port 8080]

Routes:
    GET /     — HTML dashboard (polls /api/state every 2s)
    GET /api/state — JSON snapshot of all players
    GET /ws   — WebSocket upgrade for player connections

Operator controls (stdin):
    Enter — Send "go" to all waiting players
    Ctrl+C — Shut down
"""

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field

from aiohttp import web, WSMsgType

GAUNTLET_DIFFICULTIES = [
    "VeryEasy", "Easy", "Medium", "MediumHard", "Hard", "Harder", "VeryHard",
]


@dataclass
class PlayerState:
    name: str
    race: str = ""
    map_name: str = ""
    current_round: int = 0          # 0-indexed round they're on
    highest_completed: int = -1     # highest 0-indexed round completed (-1 = none)
    state: str = "waiting"          # waiting / playing / between_rounds / completed / disconnected
    elapsed: float = 0.0            # total elapsed seconds reported by client
    round_results: list = field(default_factory=list)  # list of {round, difficulty, result, game_time}
    minimap_config: dict | None = None
    minimap_units: list | None = None
    minimap_visibility: str | None = None
    stats: dict | None = None
    ws: web.WebSocketResponse | None = field(default=None, repr=False)
    connected_at: float = field(default_factory=time.time)


class LeaderboardServer:
    def __init__(self, prep_time: int = 0):
        self.players: dict[str, PlayerState] = {}
        self.started = False  # has the operator pressed Enter?
        self.prep_time = prep_time
        self.app = web.Application()
        self.app.router.add_get("/", self.handle_dashboard)
        self.app.router.add_get("/api/state", self.handle_api_state)
        self.app.router.add_get("/ws", self.handle_ws)

    # ── Ranking ──────────────────────────────────────────────────────

    def ranked_players(self) -> list[PlayerState]:
        """Players sorted by highest round (desc), then elapsed time (asc)."""
        players = list(self.players.values())
        players.sort(key=lambda p: (-p.highest_completed, p.elapsed))
        return players

    # ── HTTP handlers ────────────────────────────────────────────────

    async def handle_dashboard(self, request: web.Request) -> web.Response:
        return web.Response(text=DASHBOARD_HTML, content_type="text/html")

    async def handle_api_state(self, request: web.Request) -> web.Response:
        ranked = self.ranked_players()
        players_data = []
        for rank, p in enumerate(ranked, 1):
            entry = {
                "rank": rank,
                "name": p.name,
                "race": p.race,
                "current_round": p.current_round,
                "highest_completed": p.highest_completed,
                "state": p.state,
                "elapsed": p.elapsed,
                "round_results": p.round_results,
            }
            if p.minimap_config:
                entry["minimap_config"] = p.minimap_config
            if p.minimap_units is not None:
                entry["minimap_units"] = p.minimap_units
            if p.minimap_visibility is not None:
                entry["minimap_visibility"] = p.minimap_visibility
            if p.stats:
                entry["stats"] = p.stats
            players_data.append(entry)
        return web.json_response({
            "started": self.started,
            "players": players_data,
            "total_rounds": len(GAUNTLET_DIFFICULTIES),
            "difficulties": GAUNTLET_DIFFICULTIES,
        })

    # ── WebSocket handler ────────────────────────────────────────────

    async def handle_ws(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)

        player_name = None

        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                    except json.JSONDecodeError:
                        continue

                    msg_type = data.get("type")

                    if msg_type == "hello":
                        player_name = data.get("name", "unknown")
                        race = data.get("race", "")
                        map_name = data.get("map", "")

                        if player_name in self.players:
                            # Reconnection — preserve progress
                            old = self.players[player_name]
                            if old.ws is not None:
                                try:
                                    await old.ws.close()
                                except Exception:
                                    pass
                            old.ws = ws
                            old.race = race or old.race
                            old.map_name = map_name or old.map_name
                            old.state = "between_rounds"
                            resume_round = old.highest_completed + 1
                            print(f"[server] {player_name} reconnected — resuming at round {resume_round + 1}")
                            await ws.send_json({
                                "type": "welcome_back",
                                "resume_round": resume_round,
                                "elapsed_before": old.elapsed,
                            })
                        else:
                            # New player
                            self.players[player_name] = PlayerState(
                                name=player_name,
                                race=race,
                                map_name=map_name,
                                ws=ws,
                            )
                            print(f"[server] {player_name} joined ({race})")

                            if self.started:
                                # Late joiner — send go immediately
                                await ws.send_json({"type": "go", "prep_time": self.prep_time})
                            else:
                                await ws.send_json({"type": "wait"})

                    elif msg_type == "status" and player_name:
                        p = self.players.get(player_name)
                        if p:
                            p.current_round = data.get("round", p.current_round)
                            p.state = data.get("state", p.state)
                            p.elapsed = data.get("elapsed", p.elapsed)

                    elif msg_type == "round_complete" and player_name:
                        p = self.players.get(player_name)
                        if p:
                            rnd = data.get("round", 0)
                            result = data.get("result", "")
                            game_time = data.get("game_time", 0)
                            p.elapsed = data.get("elapsed", p.elapsed)
                            p.round_results.append({
                                "round": rnd,
                                "difficulty": data.get("difficulty", ""),
                                "result": result,
                                "game_time": game_time,
                            })
                            if result == "Victory":
                                if rnd > p.highest_completed:
                                    p.highest_completed = rnd
                                if rnd >= len(GAUNTLET_DIFFICULTIES) - 1:
                                    p.state = "completed"
                                    print(f"[server] {player_name} COMPLETED the gauntlet! ({p.elapsed:.0f}s)")
                                else:
                                    p.state = "between_rounds"
                            else:
                                p.state = "between_rounds"
                            print(f"[server] {player_name} round {rnd + 1}: {result} ({game_time:.0f}s)")

                    elif msg_type == "minimap_init" and player_name:
                        p = self.players.get(player_name)
                        if p:
                            p.minimap_config = {
                                "map_size": data.get("map_size"),
                                "playable": data.get("playable"),
                                "terrain": data.get("terrain"),
                            }

                    elif msg_type == "minimap" and player_name:
                        p = self.players.get(player_name)
                        if p:
                            p.minimap_units = data.get("units")
                            p.minimap_visibility = data.get("visibility")
                            _stat_keys = ("minerals", "vespene", "supply_used", "supply_cap",
                                          "supply_army", "workers", "income_minerals",
                                          "income_vespene", "killed_value")
                            stats = {k: data[k] for k in _stat_keys if k in data}
                            if stats:
                                p.stats = stats

                elif msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                    break
        finally:
            if player_name and player_name in self.players:
                p = self.players[player_name]
                if p.ws is ws:
                    p.state = "disconnected"
                    p.minimap_units = None
                    p.minimap_visibility = None
                    p.stats = None
                    p.ws = None
                    print(f"[server] {player_name} disconnected")

        return ws

    # ── Operator console ─────────────────────────────────────────────

    async def on_stdin_ready(self):
        """Called when stdin has data (operator pressed a key)."""
        # Non-blocking read — consume whatever is available without risking
        # a blocking readline() that would freeze the event loop.
        try:
            data = os.read(sys.stdin.fileno(), 4096)
        except (OSError, BlockingIOError):
            return
        if not data or b"\n" not in data:
            return

        if not self.started:
            self.started = True
            n = 0
            for p in self.players.values():
                if p.ws is not None and not p.ws.closed:
                    try:
                        await p.ws.send_json({"type": "go", "prep_time": self.prep_time})
                        n += 1
                    except Exception:
                        pass
            print(f"[server] GO! Sent start signal to {n} player(s)")
        else:
            # Show current standings
            ranked = self.ranked_players()
            print(f"\n[server] Current standings ({len(ranked)} players):")
            for i, p in enumerate(ranked, 1):
                diff = GAUNTLET_DIFFICULTIES[min(p.current_round, len(GAUNTLET_DIFFICULTIES) - 1)]
                print(f"  {i}. {p.name} — round {p.highest_completed + 2}/{len(GAUNTLET_DIFFICULTIES)} "
                      f"({diff}) [{p.state}] {p.elapsed:.0f}s")
            print()

    async def start(self, port: int):
        loop = asyncio.get_event_loop()

        # Set stdin to non-blocking so os.read() in on_stdin_ready never blocks
        import fcntl
        fd = sys.stdin.fileno()
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

        loop.add_reader(fd, lambda: asyncio.ensure_future(self.on_stdin_ready()))

        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()

        n_players = len(self.players)
        print(f"[server] Leaderboard server running on http://0.0.0.0:{port}")
        print(f"[server] Dashboard: http://localhost:{port}")
        print(f"[server] Waiting for players to connect...")
        print(f"[server] Press Enter to start the gauntlet")
        print()

        # Run forever
        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            pass
        finally:
            loop.remove_reader(sys.stdin.fileno())
            await runner.cleanup()


# ── Dashboard HTML ───────────────────────────────────────────────────

DASHBOARD_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SC2 Gauntlet Leaderboard</title>
<style>
  :root {
    --bg: #0d1117;
    --surface: #161b22;
    --border: #30363d;
    --text: #c9d1d9;
    --text-dim: #8b949e;
    --accent: #58a6ff;
    --green: #3fb950;
    --yellow: #d29922;
    --red: #f85149;
    --blue: #58a6ff;
    --purple: #bc8cff;
    --terran: #4a90d9;
    --protoss: #d4af37;
    --zerg: #9b59b6;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 2rem;
  }
  h1 {
    font-size: 1.8rem;
    margin-bottom: 0.5rem;
    color: var(--accent);
  }
  .subtitle {
    color: var(--text-dim);
    margin-bottom: 2rem;
    font-size: 0.95rem;
  }
  .lobby {
    text-align: center;
    padding: 3rem;
    border: 1px dashed var(--border);
    border-radius: 8px;
    max-width: 500px;
    width: 100%;
  }
  .lobby h2 {
    color: var(--yellow);
    margin-bottom: 1rem;
    font-size: 1.2rem;
  }
  .lobby .players {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    justify-content: center;
    margin-top: 1rem;
  }
  .lobby .player-chip {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 999px;
    padding: 0.4rem 1rem;
    font-size: 0.9rem;
  }
  .card-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
    gap: 1rem;
    width: 100%;
    max-width: 1400px;
  }
  .card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    overflow: hidden;
    display: flex;
    flex-direction: column;
  }
  .card-header {
    display: flex;
    align-items: center;
    padding: 0.6rem 0.8rem;
    gap: 0.5rem;
    border-bottom: 1px solid var(--border);
  }
  .card-rank {
    font-weight: 700;
    font-size: 1.1rem;
    color: var(--text-dim);
    min-width: 2rem;
    text-align: center;
  }
  .card-rank.r1 { color: #ffd700; font-size: 1.3rem; }
  .card-rank.r2 { color: #c0c0c0; font-size: 1.2rem; }
  .card-rank.r3 { color: #cd7f32; font-size: 1.15rem; }
  .card-name {
    font-weight: 600;
    font-size: 1.05rem;
    flex: 1;
  }
  .card-race {
    font-size: 0.85rem;
    font-weight: 600;
    padding: 0.15rem 0.5rem;
    border-radius: 999px;
    background: rgba(255,255,255,0.06);
  }
  .race-terran { color: var(--terran); }
  .race-protoss { color: var(--protoss); }
  .race-zerg { color: var(--zerg); }
  .race-random { color: var(--text-dim); }
  .card-body {
    display: flex;
    padding: 0.8rem;
    gap: 0.8rem;
    flex: 1;
  }
  .card-minimap {
    flex-shrink: 0;
  }
  .card-minimap canvas {
    display: block;
    border-radius: 4px;
    background: #000;
  }
  .card-minimap-placeholder {
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 4px;
    background: rgba(0,0,0,0.3);
    color: var(--text-dim);
    font-size: 0.75rem;
  }
  .card-stats {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
    font-variant-numeric: tabular-nums;
    min-width: 0;
  }
  .stat-row {
    display: flex;
    gap: 0.6rem;
    flex-wrap: wrap;
  }
  .stat {
    display: flex;
    align-items: center;
    gap: 0.25rem;
    font-size: 0.85rem;
  }
  .stat-label {
    color: var(--text-dim);
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.03em;
  }
  .stat-value {
    font-weight: 600;
  }
  .stat-minerals { color: #4dd0e1; }
  .stat-gas { color: #81c784; }
  .stat-supply { color: var(--text); }
  .stat-supply-warn { color: var(--yellow); }
  .stat-supply-blocked { color: var(--red); }
  .stat-army { color: var(--red); }
  .stat-workers { color: var(--blue); }
  .stat-income { color: var(--text-dim); }
  .stat-killed { color: var(--yellow); }
  .stats-idle {
    color: var(--text-dim);
    font-size: 0.85rem;
    font-style: italic;
    display: flex;
    align-items: center;
    flex: 1;
  }
  .card-footer {
    display: flex;
    align-items: center;
    padding: 0.5rem 0.8rem;
    gap: 0.5rem;
    border-top: 1px solid var(--border);
  }
  .progress {
    display: flex;
    gap: 3px;
    align-items: center;
    flex: 1;
  }
  .seg {
    width: 28px;
    height: 16px;
    border-radius: 3px;
    background: var(--border);
    position: relative;
    overflow: hidden;
  }
  .seg.done { background: var(--green); }
  .seg.current {
    background: var(--blue);
    animation: pulse 1.5s ease-in-out infinite;
  }
  .seg.retry {
    background: var(--yellow);
    animation: pulse 1.5s ease-in-out infinite;
  }
  .seg-label {
    position: absolute;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 0.5rem;
    font-weight: 700;
    color: rgba(0,0,0,0.5);
  }
  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.5; }
  }
  .status {
    font-size: 0.75rem;
    font-weight: 600;
    padding: 0.15rem 0.5rem;
    border-radius: 999px;
    white-space: nowrap;
  }
  .status-playing { background: rgba(63,185,80,0.15); color: var(--green); }
  .status-between_rounds { background: rgba(63,185,80,0.15); color: var(--green); }
  .status-waiting { background: rgba(210,153,34,0.15); color: var(--yellow); }
  .status-completed { background: rgba(88,166,255,0.15); color: var(--blue); }
  .status-disconnected { background: rgba(139,148,158,0.15); color: var(--text-dim); }
  .footer-time {
    font-variant-numeric: tabular-nums;
    color: var(--text-dim);
    font-size: 0.85rem;
    white-space: nowrap;
  }
</style>
</head>
<body>
<h1>SC2 Gauntlet</h1>
<p class="subtitle">Leaderboard</p>
<div id="app"></div>

<script>
const MINIMAP_COLORS = [
  [63,185,80],   // 0 own unit — green
  [88,166,255],  // 1 own structure — blue
  [248,81,73],   // 2 enemy unit — red
  [210,153,34],  // 3 enemy structure — yellow
  [45,212,191],  // 4 mineral — teal
  [188,140,255], // 5 gas — purple
];
const MINIMAP_SIZE = 160;

function decodeTerrain(b64, w, h) {
  const raw = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
  const n = w * h;
  const grid = new Uint8Array(n);
  for (let i = 0; i < n; i++) {
    grid[i] = (raw[i >> 3] >> (7 - (i & 7))) & 1;
  }
  return grid;
}

function decodeVisibility(b64, w, h) {
  const raw = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
  const n = w * h;
  const grid = new Uint8Array(n);
  for (let i = 0; i < n; i++) {
    grid[i] = (raw[i >> 2] >> (6 - (i & 3) * 2)) & 3;
  }
  return grid;
}

function renderMinimap(canvas, config, units, visB64) {
  const ctx = canvas.getContext("2d");
  const S = MINIMAP_SIZE;
  if (!config || !config.playable) { ctx.clearRect(0,0,S,S); return; }

  const [px, py, pw, ph] = config.playable;
  const [mw, mh] = config.map_size;
  const scale = S / Math.max(pw, ph);
  const offX = (S - pw * scale) / 2;
  const offY = (S - ph * scale) / 2;

  if (config.terrain && !canvas._terrain) {
    canvas._terrain = decodeTerrain(config.terrain, mw, mh);
  }
  const terrain = canvas._terrain;
  const vis = visB64 ? decodeVisibility(visB64, mw, mh) : null;

  const img = ctx.createImageData(S, S);
  const d = img.data;
  for (let cy = 0; cy < S; cy++) {
    for (let cx = 0; cx < S; cx++) {
      const mx = Math.floor((cx - offX) / scale + px);
      const my = Math.floor((S - cy - offY) / scale + py);
      const idx = (cy * S + cx) * 4;
      if (mx < 0 || mx >= mw || my < 0 || my >= mh) {
        d[idx]=13; d[idx+1]=17; d[idx+2]=23; d[idx+3]=255;
        continue;
      }
      const gi = my * mw + mx;
      const pathable = terrain ? terrain[gi] : 1;
      const v = vis ? vis[gi] : 2;
      if (!pathable) {
        d[idx]=18; d[idx+1]=20; d[idx+2]=26; d[idx+3]=255;
      } else if (v === 0) {
        d[idx]=13; d[idx+1]=17; d[idx+2]=23; d[idx+3]=255;
      } else if (v === 1) {
        d[idx]=24; d[idx+1]=34; d[idx+2]=28; d[idx+3]=255;
      } else {
        d[idx]=34; d[idx+1]=56; d[idx+2]=38; d[idx+3]=255;
      }
    }
  }
  ctx.putImageData(img, 0, 0);

  for (const u of (units || [])) {
    const sx = (u[0] - px) * scale + offX;
    const sy = S - ((u[1] - py) * scale + offY);
    const cat = u[2];
    const c = MINIMAP_COLORS[cat] || [255,255,255];
    const r = (cat === 1 || cat === 3) ? 4 : 3;
    ctx.fillStyle = "rgb(" + c[0] + "," + c[1] + "," + c[2] + ")";
    ctx.fillRect(sx - r/2, sy - r/2, r, r);
  }
}

const DIFF_SHORT = ["VE", "E", "M", "MH", "H", "Hr", "VH"];
const STATUS_LABELS = {
  waiting: "Waiting",
  playing: "Playing",
  between_rounds: "Ready",
  completed: "Complete",
  disconnected: "Offline",
};
const RACE_CLASSES = {
  Terran: "race-terran",
  Protoss: "race-protoss",
  Zerg: "race-zerg",
  Random: "race-random",
};

function formatTime(secs) {
  const m = Math.floor(secs / 60);
  const s = Math.floor(secs % 60);
  return m + ":" + String(s).padStart(2, "0");
}

function fmtNum(n) {
  if (n == null) return "—";
  return n.toLocaleString();
}

function hasRetried(p, roundIdx) {
  let attempts = 0;
  for (const r of p.round_results) {
    if (r.round === roundIdx) attempts++;
  }
  return attempts > 1;
}

function supplyClass(used, cap) {
  if (used >= cap && cap > 0) return "stat-supply-blocked";
  if (cap > 0 && used >= cap - 2) return "stat-supply-warn";
  return "stat-supply";
}

function render(data) {
  const app = document.getElementById("app");

  if (!data.started) {
    let html = '<div class="lobby"><h2>Waiting for players...</h2>';
    html += '<p style="color:var(--text-dim)">Operator presses Enter to start</p>';
    html += '<div class="players">';
    for (const p of data.players) {
      html += '<span class="player-chip">' + esc(p.name);
      if (p.race) html += ' <span style="color:var(--text-dim)">(' + esc(p.race) + ')</span>';
      html += '</span>';
    }
    if (data.players.length === 0) {
      html += '<span style="color:var(--text-dim)">No players connected yet</span>';
    }
    html += '</div></div>';
    app.innerHTML = html;
    return;
  }

  let html = '<div class="card-grid">';

  for (const p of data.players) {
    const raceClass = RACE_CLASSES[p.race] || "race-random";
    const raceColor = p.race === "Terran" ? "var(--terran)" : p.race === "Protoss" ? "var(--protoss)" : p.race === "Zerg" ? "var(--zerg)" : "var(--border)";
    const rankCls = p.rank <= 3 ? " r" + p.rank : "";
    const isPlaying = p.state === "playing";
    const hasMinimap = p.minimap_config && p.minimap_units && isPlaying;
    const s = p.stats || {};

    html += '<div class="card" style="border-left: 3px solid ' + raceColor + '">';

    // Header: rank, name, race
    html += '<div class="card-header">';
    html += '<span class="card-rank' + rankCls + '">#' + p.rank + '</span>';
    html += '<span class="card-name">' + esc(p.name) + '</span>';
    if (p.race) html += '<span class="card-race ' + raceClass + '">' + esc(p.race) + '</span>';
    html += '</div>';

    // Body: minimap + stats
    html += '<div class="card-body">';

    // Minimap
    html += '<div class="card-minimap">';
    if (hasMinimap) {
      html += '<canvas id="mm-' + esc(p.name) + '" width="' + MINIMAP_SIZE + '" height="' + MINIMAP_SIZE + '"></canvas>';
    } else {
      html += '<div class="card-minimap-placeholder" style="width:' + MINIMAP_SIZE + 'px;height:' + MINIMAP_SIZE + 'px">';
      html += isPlaying ? "" : (p.state === "completed" ? "GG" : "—");
      html += '</div>';
    }
    html += '</div>';

    // Stats panel
    html += '<div class="card-stats">';
    if (isPlaying && p.stats) {
      // Resources
      html += '<div class="stat-row">';
      html += '<div class="stat"><span class="stat-label">Min</span> <span class="stat-value stat-minerals">' + fmtNum(s.minerals) + '</span></div>';
      html += '<div class="stat"><span class="stat-label">Gas</span> <span class="stat-value stat-gas">' + fmtNum(s.vespene) + '</span></div>';
      const sc = supplyClass(s.supply_used, s.supply_cap);
      html += '<div class="stat"><span class="stat-label">Supply</span> <span class="stat-value ' + sc + '">' + (s.supply_used != null ? s.supply_used + "/" + s.supply_cap : "—") + '</span></div>';
      html += '</div>';

      // Army + Workers
      html += '<div class="stat-row">';
      html += '<div class="stat"><span class="stat-label">Army</span> <span class="stat-value stat-army">' + fmtNum(s.supply_army) + '</span></div>';
      html += '<div class="stat"><span class="stat-label">Workers</span> <span class="stat-value stat-workers">' + fmtNum(s.workers) + '</span></div>';
      html += '</div>';

      // Income + Killed
      html += '<div class="stat-row">';
      html += '<div class="stat"><span class="stat-label">Income</span> <span class="stat-value stat-income">' + fmtNum(s.income_minerals) + '/' + fmtNum(s.income_vespene) + '</span></div>';
      html += '<div class="stat"><span class="stat-label">Killed</span> <span class="stat-value stat-killed">' + fmtNum(s.killed_value) + '</span></div>';
      html += '</div>';
    } else {
      html += '<div class="stats-idle">';
      if (p.state === "completed") html += "Gauntlet complete!";
      else if (p.state === "disconnected") html += "Disconnected";
      else if (p.state === "between_rounds") html += "Between rounds";
      else html += "Waiting...";
      html += '</div>';
    }
    html += '</div>';  // card-stats

    html += '</div>';  // card-body

    // Footer: progress + status + time
    html += '<div class="card-footer">';
    html += '<div class="progress">';
    for (let i = 0; i < data.total_rounds; i++) {
      let cls = "seg";
      if (i <= p.highest_completed) {
        cls += " done";
      } else if (i === p.current_round && (p.state === "playing" || p.state === "between_rounds")) {
        cls += hasRetried(p, i) ? " retry" : " current";
      }
      html += '<div class="' + cls + '"><span class="seg-label">' + DIFF_SHORT[i] + '</span></div>';
    }
    html += '</div>';
    const statusCls = "status status-" + p.state;
    const statusLabel = STATUS_LABELS[p.state] || p.state;
    html += '<span class="' + statusCls + '">' + statusLabel + '</span>';
    html += '<span class="footer-time">' + formatTime(p.elapsed) + '</span>';
    html += '</div>';  // card-footer

    html += '</div>';  // card
  }

  html += '</div>';  // card-grid

  app.innerHTML = html;

  // Render minimap canvases after DOM update
  const playing = data.players.filter(p => p.state === "playing" && p.minimap_config && p.minimap_units);
  for (const p of playing) {
    const canvas = document.getElementById("mm-" + p.name);
    if (canvas) renderMinimap(canvas, p.minimap_config, p.minimap_units, p.minimap_visibility);
  }
}

function esc(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

async function poll() {
  try {
    const res = await fetch("/api/state");
    const data = await res.json();
    render(data);
  } catch (e) {
    // Server might be restarting
  }
}

poll();
setInterval(poll, 2000);
</script>
</body>
</html>
"""


def main():
    parser = argparse.ArgumentParser(description="SC2 Gauntlet Leaderboard Server")
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on (default: 8080)")
    parser.add_argument("--prep-time", type=int, default=None, metavar="SECONDS",
                        help="Countdown before each round (sent to all clients). "
                             "Omit for interactive 'press enter' prompt between matches.")
    args = parser.parse_args()

    server = LeaderboardServer(prep_time=args.prep_time)
    try:
        asyncio.run(server.start(args.port))
    except KeyboardInterrupt:
        print("\n[server] Shutting down")


if __name__ == "__main__":
    main()
