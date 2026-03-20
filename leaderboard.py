#!/usr/bin/env python3
"""
SC2 Bot Arena — Leaderboard Server.

Players connect via WebSocket, appear on a live dashboard, and can
be matched against each other for PvP games.

Usage:
    python leaderboard.py [--port 8080]

Routes:
    GET /        — HTML dashboard (polls /api/state every 2s)
    GET /api/state — JSON snapshot of all players
    GET /ws      — WebSocket upgrade for player connections
"""

import argparse
import asyncio
import json
import time
from dataclasses import dataclass, field

from aiohttp import web, WSMsgType


@dataclass
class PlayerState:
    name: str
    race: str = ""
    state: str = "idle"             # idle / queued_pvp / playing_cpu / playing_pvp / disconnected
    opponent: str = ""              # "Medium Random" or "bob"
    game_time: float = 0.0          # current game in-game time
    game_history: list = field(default_factory=list)  # [{result, opponent, game_type, game_time}]
    minimap_config: dict | None = None
    minimap_units: list | None = None
    minimap_visibility: str | None = None
    stats: dict | None = None
    ws: web.WebSocketResponse | None = field(default=None, repr=False)
    peer_ip: str = ""
    connected_at: float = field(default_factory=time.time)


class LeaderboardServer:
    def __init__(self):
        self.players: dict[str, PlayerState] = {}
        self._next_match_port = 5200
        self.app = web.Application()
        self.app.router.add_get("/", self.handle_dashboard)
        self.app.router.add_get("/api/state", self.handle_api_state)
        self.app.router.add_get("/ws", self.handle_ws)

    # ── HTTP handlers ────────────────────────────────────────────────

    async def handle_dashboard(self, request: web.Request) -> web.Response:
        return web.Response(text=DASHBOARD_HTML, content_type="text/html")

    async def handle_api_state(self, request: web.Request) -> web.Response:
        players_data = []
        for p in self.players.values():
            entry = {
                "name": p.name,
                "race": p.race,
                "state": p.state,
                "opponent": p.opponent,
                "game_time": p.game_time,
                "game_history": p.game_history[-5:],  # last 5 results
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
        return web.json_response({"players": players_data})

    # ── Matchmaking ──────────────────────────────────────────────────

    async def _try_match(self):
        """Pair up queued PvP players."""
        queued = [p for p in self.players.values()
                  if p.state == "queued_pvp" and p.ws and not p.ws.closed]
        while len(queued) >= 2:
            p1, p2 = queued.pop(0), queued.pop(0)
            base_port = self._next_match_port
            self._next_match_port += 10

            p1.state = "playing_pvp"
            p2.state = "playing_pvp"
            p1.opponent = p2.name
            p2.opponent = p1.name

            # Clear stale minimap data from previous game
            for p in (p1, p2):
                p.minimap_config = None
                p.minimap_units = None
                p.minimap_visibility = None
                p.stats = None
                p.game_time = 0.0

            try:
                await p1.ws.send_json({
                    "type": "match_assigned",
                    "role": "host",
                    "opponent_name": p2.name,
                    "opponent_ip": p2.peer_ip,
                    "base_port": base_port,
                })
                await p2.ws.send_json({
                    "type": "match_assigned",
                    "role": "joiner",
                    "opponent_name": p1.name,
                    "opponent_ip": p1.peer_ip,
                    "base_port": base_port,
                })
                print(f"[server] Matched {p1.name} (host) vs {p2.name} (joiner) on port {base_port}")
            except Exception as e:
                print(f"[server] Failed to send match assignment: {e}")

    # ── WebSocket handler ────────────────────────────────────────────

    async def handle_ws(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)

        peer_ip = request.remote or ""
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

                        if player_name in self.players:
                            old = self.players[player_name]
                            if old.ws is not None:
                                try:
                                    await old.ws.close()
                                except Exception:
                                    pass
                            old.ws = ws
                            old.race = race or old.race
                            old.state = "idle"
                            old.peer_ip = peer_ip
                            print(f"[server] {player_name} reconnected ({peer_ip})")
                        else:
                            self.players[player_name] = PlayerState(
                                name=player_name,
                                race=race,
                                ws=ws,
                                peer_ip=peer_ip,
                            )
                            print(f"[server] {player_name} joined ({race}, {peer_ip})")

                        await ws.send_json({"type": "connected"})

                    elif msg_type == "status" and player_name:
                        p = self.players.get(player_name)
                        if p:
                            p.state = data.get("state", p.state)
                            p.opponent = data.get("opponent", p.opponent)
                            p.game_time = data.get("game_time", p.game_time)

                    elif msg_type == "game_complete" and player_name:
                        p = self.players.get(player_name)
                        if p:
                            result = data.get("result", "")
                            game_time = data.get("game_time", 0)
                            opponent = data.get("opponent", "")
                            game_type = data.get("game_type", "")
                            p.game_history.append({
                                "result": result,
                                "opponent": opponent,
                                "game_type": game_type,
                                "game_time": game_time,
                            })
                            p.state = "idle"
                            p.game_time = 0.0
                            # Clear minimap
                            p.minimap_config = None
                            p.minimap_units = None
                            p.minimap_visibility = None
                            p.stats = None
                            print(f"[server] {player_name}: {result} vs {opponent} ({game_time:.0f}s)")

                    elif msg_type == "queue_pvp" and player_name:
                        p = self.players.get(player_name)
                        if p:
                            p.state = "queued_pvp"
                            p.opponent = ""
                            print(f"[server] {player_name} queued for PvP")
                            await self._try_match()

                    elif msg_type == "cancel_pvp" and player_name:
                        p = self.players.get(player_name)
                        if p and p.state == "queued_pvp":
                            p.state = "idle"
                            print(f"[server] {player_name} left PvP queue")

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
                    was_queued = p.state == "queued_pvp"
                    p.state = "disconnected"
                    p.minimap_units = None
                    p.minimap_visibility = None
                    p.stats = None
                    p.ws = None
                    print(f"[server] {player_name} disconnected")

                    # If they were queued, no action needed — they're just gone.
                    # If they were in a PvP game, SC2 handles the disconnect.

        return ws

    async def start(self, port: int):
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()

        print(f"[server] SC2 Bot Arena running on http://0.0.0.0:{port}")
        print(f"[server] Dashboard: http://localhost:{port}")
        print()

        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            pass
        finally:
            await runner.cleanup()


# ── Dashboard HTML ───────────────────────────────────────────────────

DASHBOARD_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SC2 Bot Arena</title>
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
  .history {
    display: flex;
    gap: 4px;
    flex: 1;
    flex-wrap: wrap;
  }
  .history-chip {
    font-size: 0.7rem;
    font-weight: 600;
    padding: 0.1rem 0.4rem;
    border-radius: 4px;
    white-space: nowrap;
  }
  .history-chip.win { background: rgba(63,185,80,0.2); color: var(--green); }
  .history-chip.loss { background: rgba(248,81,73,0.15); color: var(--red); }
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
  .status-idle { background: rgba(139,148,158,0.15); color: var(--text-dim); }
  .status-queued_pvp {
    background: rgba(210,153,34,0.15); color: var(--yellow);
    animation: pulse 1.5s ease-in-out infinite;
  }
  .status-playing_cpu { background: rgba(88,166,255,0.15); color: var(--blue); }
  .status-playing_pvp { background: rgba(63,185,80,0.15); color: var(--green); }
  .status-disconnected { background: rgba(139,148,158,0.15); color: var(--text-dim); }
  .footer-time {
    font-variant-numeric: tabular-nums;
    color: var(--text-dim);
    font-size: 0.85rem;
    white-space: nowrap;
  }
  .no-players {
    text-align: center;
    padding: 3rem;
    color: var(--text-dim);
    font-size: 1.1rem;
  }
</style>
</head>
<body>
<h1>SC2 Bot Arena</h1>
<p class="subtitle">Live Dashboard</p>
<div id="app"></div>

<script>
const MINIMAP_COLORS = [
  [63,185,80],   // 0 own unit
  [88,166,255],  // 1 own structure
  [248,81,73],   // 2 enemy unit
  [210,153,34],  // 3 enemy structure
  [45,212,191],  // 4 mineral
  [188,140,255], // 5 gas
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

const STATUS_LABELS = {
  idle: "In Menu",
  queued_pvp: "Queued PvP",
  playing_cpu: "vs CPU",
  playing_pvp: "vs Player",
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

function supplyClass(used, cap) {
  if (used >= cap && cap > 0) return "stat-supply-blocked";
  if (cap > 0 && used >= cap - 2) return "stat-supply-warn";
  return "stat-supply";
}

function render(data) {
  const app = document.getElementById("app");

  if (data.players.length === 0) {
    app.innerHTML = '<div class="no-players">No players connected</div>';
    return;
  }

  let html = '<div class="card-grid">';

  for (const p of data.players) {
    const raceClass = RACE_CLASSES[p.race] || "race-random";
    const raceColor = p.race === "Terran" ? "var(--terran)" : p.race === "Protoss" ? "var(--protoss)" : p.race === "Zerg" ? "var(--zerg)" : "var(--border)";
    const isPlaying = p.state === "playing_cpu" || p.state === "playing_pvp";
    const hasMinimap = p.minimap_config && p.minimap_units && isPlaying;
    const s = p.stats || {};

    html += '<div class="card" style="border-left: 3px solid ' + raceColor + '">';

    // Header: name, race
    html += '<div class="card-header">';
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
      html += isPlaying ? "" : "—";
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
      if (p.state === "queued_pvp") html += "Waiting for opponent...";
      else if (p.state === "disconnected") html += "Disconnected";
      else if (isPlaying) html += "Starting...";
      else html += "In menu";
      html += '</div>';
    }
    html += '</div>';  // card-stats

    html += '</div>';  // card-body

    // Footer: opponent/status + game history + time
    html += '<div class="card-footer">';

    // Recent game history chips
    html += '<div class="history">';
    for (const g of (p.game_history || [])) {
      const isWin = g.result === "Victory";
      const cls = isWin ? "win" : "loss";
      const label = (isWin ? "W" : "L") + " vs " + esc(g.opponent);
      html += '<span class="history-chip ' + cls + '">' + label + '</span>';
    }
    html += '</div>';

    const statusCls = "status status-" + p.state;
    let statusLabel = STATUS_LABELS[p.state] || p.state;
    if (isPlaying && p.opponent) {
      statusLabel += ": " + esc(p.opponent);
    }
    html += '<span class="' + statusCls + '">' + statusLabel + '</span>';

    if (isPlaying && p.game_time > 0) {
      html += '<span class="footer-time">' + formatTime(p.game_time) + '</span>';
    }
    html += '</div>';  // card-footer

    html += '</div>';  // card
  }

  html += '</div>';  // card-grid

  app.innerHTML = html;

  // Render minimap canvases after DOM update
  const playing = data.players.filter(p =>
    (p.state === "playing_cpu" || p.state === "playing_pvp") && p.minimap_config && p.minimap_units
  );
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
    parser = argparse.ArgumentParser(description="SC2 Bot Arena — Leaderboard Server")
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on (default: 8080)")
    args = parser.parse_args()

    server = LeaderboardServer()
    try:
        asyncio.run(server.start(args.port))
    except KeyboardInterrupt:
        print("\n[server] Shutting down")


if __name__ == "__main__":
    main()
