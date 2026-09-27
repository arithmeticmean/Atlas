"""Where this instance can be reached from.

Deliberately separate from anything to do with invites. An invite is a
credential and says nothing about network topology; how you reach Atlas is a
property of the deployment. Locally that means a LAN address nobody wants to
look up by hand; deployed behind a name, it is already known and this is just
confirmation. Keeping them apart means an invite token stays valid however the
instance is reached.

Address discovery is standard library only. ``netifaces`` needs a C compiler on
some platforms and ``psutil`` is a lot of weight for one string -- and this
project already learned what a native dependency costs an installable wheel
(see the libmagic note in ingest/loaders.py).
"""

import socket
from dataclasses import dataclass

# Any routable address works: opening a UDP socket performs no handshake and
# sends no packets, it only asks the kernel which local interface would carry
# traffic to that destination. The address is never contacted.
_ROUTE_PROBE = ("192.0.2.1", 9)  # TEST-NET-1, reserved and unroutable

_LOOPBACK_HOSTS = frozenset(
    {"127.0.0.1", "localhost", "::1", "[::1]"}
)


@dataclass(frozen=True, slots=True)
class Reachability:
    """How this process can be reached, as the process itself sees it."""

    bound_host: str
    port: int
    loopback_only: bool
    addresses: list[str]


def primary_address() -> str | None:
    """The IPv4 address of the interface that carries outbound traffic.

    ``None`` when the host has no usable route (offline, or a locked-down
    container), which callers should treat as "cannot determine", not an error.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(_ROUTE_PROBE)
        address: str = sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()
    return None if address.startswith("127.") else address


def local_addresses() -> list[str]:
    """Candidate addresses for reaching this machine, best first.

    The routing-table answer leads; anything the hostname resolves to follows,
    for the case where a local DNS name is the address people actually use.
    """
    found: list[str] = []

    primary = primary_address()
    if primary:
        found.append(primary)

    try:
        _, _, resolved = socket.gethostbyname_ex(socket.gethostname())
    except OSError:
        resolved = []
    for address in resolved:
        if not address.startswith("127.") and address not in found:
            found.append(address)

    return found


def describe(bound_host: str, port: int) -> Reachability:
    """Summarise reachability for the UI.

    ``loopback_only`` is the field that matters: when the server is bound to
    loopback, no address reaches it from another machine, so the interface must
    say that plainly instead of offering a URL that will refuse the connection.
    """
    loopback_only = bound_host in _LOOPBACK_HOSTS
    return Reachability(
        bound_host=bound_host,
        port=port,
        loopback_only=loopback_only,
        addresses=[] if loopback_only else local_addresses(),
    )
