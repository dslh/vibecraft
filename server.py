"""
SC2 Server — launches SC2 instances for remote bot connections.

Usage:
    python server.py [--instances 2]

Launches N SC2 instances listening on the network, prints their WebSocket
URLs, then waits. Remote bots connect via:
    python run.py --remote-host ws://THIS_IP:<port>/sc2api --race terran
    python run.py --remote-join ws://THIS_IP:<port>/sc2api --host-ip THIS_IP --race zerg
"""

import argparse
import asyncio
import os
import socket
import sys

from loguru import logger

from sc2.sc2process import SC2Process


def get_lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


async def run_server(num_instances: int):
    os.environ["SC2SERVERHOST"] = "0.0.0.0"

    lan_ip = get_lan_ip()
    processes = []

    print(f"[server] Launching {num_instances} SC2 instance(s)...")

    try:
        for i in range(num_instances):
            # Let portpicker find a free port (same as run.py does).
            proc = SC2Process()
            controller = await proc.__aenter__()
            processes.append(proc)
            print(f"[server] SC2 instance {i + 1} ready: ws://{lan_ip}:{proc._port}/sc2api")

            # SC2 only accepts one WebSocket connection at a time. Release ours
            # so the remote bot can connect. The SC2 process stays running.
            await proc._close_connection()

        print()
        print(f"[server] All instances ready. Players should run:")
        print(f"[server]   Player 1: python run.py --remote-host ws://{lan_ip}:{processes[0]._port}/sc2api --race <race>")
        if num_instances > 1:
            print(f"[server]   Player 2: python run.py --remote-join ws://{lan_ip}:{processes[1]._port}/sc2api --host-ip {lan_ip} --race <race>")
        print()
        print(f"[server] Press Ctrl+C to shut down.")

        # Wait until interrupted
        await asyncio.Event().wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        print(f"\n[server] Shutting down SC2 instances...")
        for proc in reversed(processes):
            try:
                await proc.__aexit__(None, None, None)
            except Exception:
                pass


def main():
    parser = argparse.ArgumentParser(description="SC2 Server — launches SC2 instances for remote bots")
    parser.add_argument("--instances", type=int, default=2, help="Number of SC2 instances (default: 2)")
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging from python-sc2 and SC2 process",
    )
    args = parser.parse_args()

    if args.verbose:
        logger.enable("sc2")
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")

    asyncio.run(run_server(args.instances))


if __name__ == "__main__":
    main()
