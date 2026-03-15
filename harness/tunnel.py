"""
Game port tunnel for SC2 LAN multiplayer.

SC2 restricts game port communication to localhost. This tunnel
multiplexes all game port traffic over a single TCP connection
between two machines, presenting the ports as localhost on each end.

Port layout (base_port=5100):
  5100        — tunnel TCP connection between machines
  5101 (UDP)  — server game_port  (host SC2 binds)
  5102 (TCP)  — server base_port  (host SC2 binds)
  5103 (UDP)  — client game_port  (joiner SC2 binds)
  5104 (TCP)  — client base_port  (joiner SC2 binds)

Frame format: [port_id:1] [length:2 big-endian] [payload]
"""

import asyncio

_TAG = "[tunnel]"


class _UdpRelay(asyncio.DatagramProtocol):
    """Bound on a remote port to intercept local SC2 traffic.
    Also delivers incoming tunnel data to the local SC2 port."""

    def __init__(self, tunnel, send_id, deliver_addr, bind_port):
        self.tunnel = tunnel
        self.send_id = send_id
        self.deliver_addr = deliver_addr
        self.bind_port = bind_port
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        print(f"{_TAG} UDP recv {len(data)}b on :{self.bind_port} → tunnel (id={self.send_id})")
        asyncio.create_task(self.tunnel._send(self.send_id, data))

    def deliver(self, data):
        if self.transport:
            print(f"{_TAG} UDP deliver {len(data)}b → :{self.deliver_addr[1]}")
            self.transport.sendto(data, self.deliver_addr)


class Tunnel:
    def __init__(self, base_port, is_host):
        self.base_port = base_port
        self.is_host = is_host
        self._reader = None
        self._writer = None
        self._write_lock = asyncio.Lock()
        self._handlers = {}
        self._tasks = []
        self._servers = []
        self._transports = []
        self._ready = asyncio.Event()

    @classmethod
    async def listen(cls, base_port):
        """Host: start listening for the joiner's tunnel connection."""
        t = cls(base_port, is_host=True)

        async def accept(reader, writer):
            t._reader = reader
            t._writer = writer
            t._ready.set()

        server = await asyncio.start_server(accept, "0.0.0.0", base_port)
        t._servers.append(server)
        return t

    async def wait_for_peer(self):
        await self._ready.wait()

    @classmethod
    async def connect(cls, host_ip, base_port):
        """Joiner: connect to the host's tunnel."""
        t = cls(base_port, is_host=False)
        for i in range(120):
            try:
                t._reader, t._writer = await asyncio.open_connection(
                    host_ip, base_port
                )
                t._ready.set()
                return t
            except OSError:
                if i == 0:
                    print(f"{_TAG} Waiting for host...")
                await asyncio.sleep(1)
        raise ConnectionError(f"Could not connect to {host_ip}:{base_port}")

    async def start_relays(self):
        """Start all port relays and the tunnel reader."""
        bp = self.base_port
        side = "host" if self.is_host else "joiner"
        if self.is_host:
            print(f"{_TAG} Host relays: intercept :{bp+3}(udp) :{bp+4}(tcp), deliver :{bp+1}(udp) :{bp+2}(tcp)")
            await self._udp_relay(bind=bp + 3, deliver=bp + 1, send_id=2, recv_id=0)
            await self._tcp_interceptor(port_id=3, port_num=bp + 4)
            self._tasks.append(
                asyncio.create_task(self._tcp_deliverer(port_id=1, port_num=bp + 2))
            )
        else:
            print(f"{_TAG} Joiner relays: intercept :{bp+1}(udp) :{bp+2}(tcp), deliver :{bp+3}(udp) :{bp+4}(tcp)")
            await self._udp_relay(bind=bp + 1, deliver=bp + 3, send_id=0, recv_id=2)
            await self._tcp_interceptor(port_id=1, port_num=bp + 2)
            self._tasks.append(
                asyncio.create_task(self._tcp_deliverer(port_id=3, port_num=bp + 4))
            )
        self._tasks.append(asyncio.create_task(self._read_loop()))

    async def _send(self, port_id, data):
        async with self._write_lock:
            self._writer.write(
                bytes([port_id]) + len(data).to_bytes(2, "big") + data
            )
            await self._writer.drain()

    async def _read_loop(self):
        try:
            while True:
                hdr = await self._reader.readexactly(3)
                port_id = hdr[0]
                length = int.from_bytes(hdr[1:3], "big")
                data = await self._reader.readexactly(length)
                handler = self._handlers.get(port_id)
                if handler:
                    handler(data)
        except (asyncio.IncompleteReadError, ConnectionError, OSError):
            print(f"{_TAG} Tunnel connection closed")

    async def _udp_relay(self, bind, deliver, send_id, recv_id):
        loop = asyncio.get_running_loop()
        transport, protocol = await loop.create_datagram_endpoint(
            lambda: _UdpRelay(self, send_id, ("127.0.0.1", deliver), bind),
            local_addr=("127.0.0.1", bind),
        )
        self._transports.append(transport)
        self._handlers[recv_id] = protocol.deliver
        print(f"{_TAG} UDP relay bound :{bind}")

    async def _tcp_interceptor(self, port_id, port_num):
        queue = asyncio.Queue()
        self._handlers[port_id] = queue.put_nowait

        async def on_connect(reader, writer):
            print(f"{_TAG} TCP interceptor :{port_num} — SC2 connected (id={port_id})")

            async def local_to_tunnel():
                try:
                    while data := await reader.read(65535):
                        print(f"{_TAG} TCP :{port_num} → tunnel {len(data)}b (id={port_id})")
                        await self._send(port_id, data)
                except (ConnectionError, OSError):
                    pass

            async def tunnel_to_local():
                try:
                    while True:
                        data = await queue.get()
                        print(f"{_TAG} TCP tunnel → :{port_num} {len(data)}b (id={port_id})")
                        writer.write(data)
                        await writer.drain()
                except (ConnectionError, OSError):
                    pass

            self._tasks.append(asyncio.create_task(local_to_tunnel()))
            self._tasks.append(asyncio.create_task(tunnel_to_local()))

        server = await asyncio.start_server(on_connect, "127.0.0.1", port_num)
        self._servers.append(server)
        print(f"{_TAG} TCP interceptor listening :{port_num}")

    async def _tcp_deliverer(self, port_id, port_num):
        queue = asyncio.Queue()
        self._handlers[port_id] = queue.put_nowait

        # Retry until SC2 binds the port (happens during join_game)
        reader = writer = None
        for attempt in range(120):
            try:
                reader, writer = await asyncio.open_connection(
                    "127.0.0.1", port_num
                )
                break
            except OSError:
                if attempt % 10 == 0:
                    print(f"{_TAG} TCP deliverer waiting for SC2 to bind :{port_num}...")
                await asyncio.sleep(0.5)
        if reader is None:
            print(f"{_TAG} TCP deliverer TIMED OUT — SC2 never bound :{port_num}")
            print(f"{_TAG} SC2 may not use game ports with host_ip=127.0.0.1")
            return

        print(f"{_TAG} TCP deliverer connected to :{port_num} (id={port_id})")

        async def tunnel_to_local():
            try:
                while True:
                    data = await queue.get()
                    print(f"{_TAG} TCP tunnel → :{port_num} {len(data)}b (id={port_id})")
                    writer.write(data)
                    await writer.drain()
            except (ConnectionError, OSError):
                pass

        self._tasks.append(asyncio.create_task(tunnel_to_local()))

        try:
            while data := await reader.read(65535):
                print(f"{_TAG} TCP :{port_num} → tunnel {len(data)}b (id={port_id})")
                await self._send(port_id, data)
        except (ConnectionError, OSError):
            pass

    async def stop(self):
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        for server in self._servers:
            server.close()
        for transport in self._transports:
            transport.close()
        if self._writer:
            self._writer.close()
