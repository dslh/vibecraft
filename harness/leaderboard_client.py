"""
Leaderboard WebSocket client for arena mode.

Runs an aiohttp WebSocket connection on a background daemon thread
with its own event loop. The main thread (which is blocked inside
run_game() → asyncio.run()) calls thread-safe methods to send
status updates and wait for matchmaking.

Usage:
    lb = LeaderboardClient("localhost:8080", name="alice", race="Terran")
    lb.start()
    lb.wait_for_connect()
    lb.send_status(state="playing_cpu", opponent="Medium Random", game_time=0)
    lb.send_game_complete(result="Victory", game_time=120.5, opponent="Medium Random", game_type="cpu")
    lb.queue_pvp()
    match = lb.wait_for_match()  # blocks until paired
    lb.close()
"""

from __future__ import annotations

import asyncio
import json
import threading

import aiohttp


class LeaderboardClient:
    def __init__(self, address: str, *, name: str, race: str):
        self.address = address
        self.name = name
        self.race = race

        # Threading primitives
        self._connect_event = threading.Event()
        self._match_event = threading.Event()
        self._match_info: dict | None = None
        self._match_cancelled_reason: str | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._session: aiohttp.ClientSession | None = None
        self._connected = False

    def start(self):
        """Start the background thread and connect to the server."""
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def _run_loop(self):
        """Entry point for the background thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._connect_and_listen())
        except Exception as e:
            print(f"[leaderboard] Connection error: {e}")
        finally:
            try:
                self._loop.run_until_complete(self._cleanup())
            except Exception:
                pass
            self._loop.close()
            self._loop = None
            # Unblock main thread if still waiting
            self._connect_event.set()
            self._match_event.set()

    async def _connect_and_listen(self):
        """Connect to the leaderboard server and listen for messages."""
        url = f"ws://{self.address}/ws"
        try:
            self._session = aiohttp.ClientSession()
            self._ws = await self._session.ws_connect(url, heartbeat=30, timeout=10)
            self._connected = True
        except Exception as e:
            print(f"[leaderboard] Could not connect to {url}: {e}")
            self._connect_event.set()
            return

        print(f"[leaderboard] Connected to {url}")

        # Send hello
        await self._ws.send_json({
            "type": "hello",
            "name": self.name,
            "race": self.race,
        })

        # Listen for messages
        try:
            async for msg in self._ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                    except json.JSONDecodeError:
                        continue

                    msg_type = data.get("type")

                    if msg_type == "connected":
                        print(f"[leaderboard] Registered as '{self.name}'")
                        self._connect_event.set()

                    elif msg_type == "match_assigned":
                        self._match_info = data
                        role = data.get("role", "?")
                        opponent = data.get("opponent_name", "?")
                        print(f"[leaderboard] Match found! {role} vs {opponent}")
                        self._match_event.set()

                    elif msg_type == "match_cancelled":
                        reason = data.get("reason", "unknown")
                        print(f"[leaderboard] Match cancelled: {reason}")
                        self._match_cancelled_reason = reason
                        self._match_event.set()

                elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSE):
                    break
        except Exception as e:
            print(f"[leaderboard] WebSocket error: {e}")
        finally:
            self._connected = False

    async def _cleanup(self):
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._session and not self._session.closed:
            await self._session.close()

    def wait_for_connect(self, timeout: float = 30) -> bool:
        """Block until the server acknowledges our hello."""
        return self._connect_event.wait(timeout=timeout)

    def send_status(self, *, state: str, opponent: str = "", game_time: float = 0.0):
        """Send a status update to the server."""
        self._send({
            "type": "status",
            "state": state,
            "opponent": opponent,
            "game_time": game_time,
        })

    def send_game_complete(self, *, result: str, game_time: float,
                           opponent: str, game_type: str):
        """Report a completed game to the server."""
        self._send({
            "type": "game_complete",
            "result": result,
            "game_time": game_time,
            "opponent": opponent,
            "game_type": game_type,
        })

    def queue_pvp(self):
        """Enter the PvP matchmaking queue."""
        self._match_event.clear()
        self._match_info = None
        self._match_cancelled_reason = None
        self._send({"type": "queue_pvp"})

    def cancel_pvp(self):
        """Leave the PvP matchmaking queue."""
        self._send({"type": "cancel_pvp"})

    def wait_for_match(self, timeout: float = 3600) -> dict | None:
        """Block until the server assigns a PvP match. Returns match info or None if cancelled."""
        self._match_event.wait(timeout=timeout)
        if self._match_cancelled_reason:
            return None
        return self._match_info

    def send_minimap_init(self, *, map_size: list, playable: list, terrain: str):
        """Send map geometry and terrain data for dashboard minimap."""
        self._send({
            "type": "minimap_init",
            "map_size": map_size,
            "playable": playable,
            "terrain": terrain,
        })

    def send_minimap(self, *, units: list, visibility: str, stats: dict | None = None):
        """Send unit positions and fog-of-war for the live minimap overlay."""
        msg = {
            "type": "minimap",
            "units": units,
            "visibility": visibility,
        }
        if stats:
            msg.update(stats)
        self._send(msg)

    def _send(self, data: dict):
        """Thread-safe send via the background event loop."""
        if not self._connected or self._loop is None or self._ws is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(self._do_send(data), self._loop)
        except Exception:
            pass

    async def _do_send(self, data: dict):
        if self._ws and not self._ws.closed:
            try:
                await self._ws.send_json(data)
            except Exception:
                self._connected = False

    def close(self):
        """Shut down the background thread."""
        if self._loop and not self._loop.is_closed():
            try:
                asyncio.run_coroutine_threadsafe(self._cleanup(), self._loop)
            except Exception:
                pass
