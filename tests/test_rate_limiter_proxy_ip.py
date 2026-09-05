from bot.services.rate_limiter import _client_ip


class _Transport:
    def __init__(self, peer_ip: str) -> None:
        self.peer_ip = peer_ip

    def get_extra_info(self, name: str):
        if name == "peername":
            return (self.peer_ip, 443)
        return None


class _Request:
    def __init__(self, headers: dict[str, str], peer_ip: str = "172.18.0.1") -> None:
        self.headers = headers
        self.transport = _Transport(peer_ip)
        self.remote = peer_ip


def test_real_ip_wins_over_client_controlled_forwarded_for() -> None:
    request = _Request(
        {
            "X-Real-IP": "203.0.113.20",
            "X-Forwarded-For": "198.51.100.77, 203.0.113.20",
        }
    )

    assert _client_ip(request) == "203.0.113.20"


def test_forwarded_for_is_only_fallback_when_real_ip_is_missing() -> None:
    request = _Request({"X-Forwarded-For": "198.51.100.77, 203.0.113.20"})

    assert _client_ip(request) == "198.51.100.77"


def test_socket_peer_is_final_fallback() -> None:
    request = _Request({}, peer_ip="172.18.0.1")

    assert _client_ip(request) == "172.18.0.1"
