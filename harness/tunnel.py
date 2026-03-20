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


class _UdpRelay(asyncio.DatagramProtocol):
    """Bound on a remote port to intercept local SC2 traffic.
    Also delivers incoming tunnel data to the local SC2 port."""

    def __init__(self, tunnel, send_id, deliver_addr):
        self.tunnel = tunnel
        self.send_id = send_id
        self.deliver_addr = deliver_addr
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        asyncio.create_task(self.tunnel._send(self.send_id, data))

    def deliver(self, data):
        if self.transport:
            self.transport.sendto(data, self.deliver_addr)


class Tunnel:
    def __init__(self, base_port, is_host):
        self.base_port = base_port
        self.is_host = is_host
        self.peer_ip = None
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
            peername = writer.get_extra_info("peername")
            t.peer_ip = peername[0] if peername else None
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
                    print("[tunnel] Waiting for host...")
                await asyncio.sleep(1)
        raise ConnectionError(f"Could not connect to {host_ip}:{base_port}")

    async def start_relays(self):
        """Start all port relays and the tunnel reader.

        For ports owned by the LOCAL SC2 (host owns server ports, joiner owns
        client ports), a TCP deliverer connects to the local SC2 port and
        bridges it to the tunnel.

        For REMOTE ports, an interceptor listens/binds locally so the local
        SC2 can connect to it, and bridges traffic through the tunnel.
        """
        bp = self.base_port
        if self.is_host:
            await self._udp_relay(bind=bp + 3, deliver=bp + 1, send_id=2, recv_id=0)
            await self._tcp_interceptor(port_id=3, port_num=bp + 4)
            self._tasks.append(
                asyncio.create_task(self._tcp_deliverer(port_id=1, port_num=bp + 2))
            )
        else:
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
            pass

    async def _udp_relay(self, bind, deliver, send_id, recv_id):
        loop = asyncio.get_running_loop()
        transport, protocol = await loop.create_datagram_endpoint(
            lambda: _UdpRelay(self, send_id, ("127.0.0.1", deliver)),
            local_addr=("127.0.0.1", bind),
        )
        self._transports.append(transport)
        self._handlers[recv_id] = protocol.deliver

    async def _tcp_interceptor(self, port_id, port_num):
        queue = asyncio.Queue()
        self._handlers[port_id] = queue.put_nowait

        async def on_connect(reader, writer):
            async def local_to_tunnel():
                try:
                    while data := await reader.read(65535):
                        await self._send(port_id, data)
                except (ConnectionError, OSError):
                    pass

            async def tunnel_to_local():
                try:
                    while True:
                        writer.write(await queue.get())
                        await writer.drain()
                except (ConnectionError, OSError):
                    pass

            self._tasks.append(asyncio.create_task(local_to_tunnel()))
            self._tasks.append(asyncio.create_task(tunnel_to_local()))

        server = await asyncio.start_server(on_connect, "127.0.0.1", port_num)
        self._servers.append(server)

    async def _tcp_deliverer(self, port_id, port_num):
        queue = asyncio.Queue()
        self._handlers[port_id] = queue.put_nowait

        # Retry until SC2 binds the port (happens during join_game)
        reader = writer = None
        for _ in range(120):
            try:
                reader, writer = await asyncio.open_connection(
                    "127.0.0.1", port_num
                )
                break
            except OSError:
                await asyncio.sleep(0.5)
        if reader is None:
            print(f"[tunnel] Timed out connecting to local port {port_num}")
            return

        async def tunnel_to_local():
            try:
                while True:
                    writer.write(await queue.get())
                    await writer.drain()
            except (ConnectionError, OSError):
                pass

        self._tasks.append(asyncio.create_task(tunnel_to_local()))

        try:
            while data := await reader.read(65535):
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
