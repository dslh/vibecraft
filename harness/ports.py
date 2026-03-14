from sc2.portconfig import Portconfig

DEFAULT_BASE_PORT = 5100


def make_portconfig(base_port: int, num_players: int) -> Portconfig:
    server_ports = [base_port, base_port + 1]
    guests = num_players - 1
    player_ports = [
        [base_port + 2 + 2 * i, base_port + 3 + 2 * i]
        for i in range(guests)
    ]
    return Portconfig(server_ports=server_ports, player_ports=player_ports)
