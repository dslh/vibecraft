"""
Leaderboard WebSocket client for gauntlet mode.

Runs an aiohttp WebSocket connection on a background daemon thread
with its own event loop. The main thread (which is blocked inside
run_game() → asyncio.run()) calls thread-safe methods to send
status updates and wait for the start signal.

Usage:
    lb = LeaderboardClient("localhost:8080", name="alice", race="Terran", map_name="Simple64")
    lb.start()
    lb.wait_for_go()          # blocks until operator presses Enter on server
    # ... run games ...
    lb.send_round_complete(round_idx=0, difficulty="VeryEasy", result="Victory", game_time=120.5, elapsed=120.5)
    lb.close()
"""

from __future__ import annotations

import asyncio
import json
import threading
import time

import aiohttp


class LeaderboardClient:
    def __init__(self, address: str, *, name: str, race: str, map_name: str):
        self.address = address
        self.name = name
        self.race = race
        self.map_name = map_name

        # Threading primitives
        self._go_event = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._session: aiohttp.ClientSession | None = None
        self._connected = False

        # Set by server on go/reconnect
        self.prep_time: int = 0
        self.resume_round: int | None = None
        self.elapsed_before: float = 0.0

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
            self._go_event.set()

    async def _connect_and_listen(self):
        """Connect to the leaderboard server and listen for messages."""
        url = f"ws://{self.address}/ws"
        try:
            self._session = aiohttp.ClientSession()
            self._ws = await self._session.ws_connect(url, heartbeat=30, timeout=10)
            self._connected = True
        except Exception as e:
            print(f"[leaderboard] Could not connect to {url}: {e}")
            self._go_event.set()  # Don't block the main thread
            return

        print(f"[leaderboard] Connected to {url}")

        # Send hello
        await self._ws.send_json({
            "type": "hello",
            "name": self.name,
            "race": self.race,
            "map": self.map_name,
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

                    if msg_type == "wait":
                        print(f"[leaderboard] Waiting for operator to start...")

                    elif msg_type == "go":
                        self.prep_time = data.get("prep_time", 0)
                        print(f"[leaderboard] GO!")
                        self._go_event.set()

                    elif msg_type == "welcome_back":
                        self.resume_round = data.get("resume_round", 0)
                        self.elapsed_before = data.get("elapsed_before", 0.0)
                        print(f"[leaderboard] Reconnected — resuming at round {self.resume_round + 1}")
                        self._go_event.set()

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

    def wait_for_go(self, timeout: float = 3600):
        """Block the main thread until the server sends 'go'. Returns True if go received."""
        return self._go_event.wait(timeout=timeout)

    def send_status(self, *, round_idx: int, difficulty: str, state: str, elapsed: float):
        """Send a status update to the server (non-blocking, fire-and-forget)."""
        self._send({
            "type": "status",
            "round": round_idx,
            "difficulty": difficulty,
            "state": state,
            "elapsed": elapsed,
        })

    def send_round_complete(self, *, round_idx: int, difficulty: str, result: str,
                            game_time: float, elapsed: float):
        """Send round completion to the server (non-blocking, fire-and-forget)."""
        self._send({
            "type": "round_complete",
            "round": round_idx,
            "difficulty": difficulty,
            "result": result,
            "game_time": game_time,
            "elapsed": elapsed,
        })

    def _send(self, data: dict):
        """Thread-safe send via the background event loop."""
        if not self._connected or self._loop is None or self._ws is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(self._do_send(data), self._loop)
        except Exception:
            pass  # Server down, loop closed, etc. — don't crash the game

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
        # Don't join the daemon thread — it'll die with the process
