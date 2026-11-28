"""Reticulum gateway with an announce-only distance limit."""

import time

import RNS

MAX_ANNOUNCE_HOPS = 25


def install_announce_filter():
    """Reject distant announces before Reticulum caches or processes them."""
    original = RNS.Transport.packet_filter

    def packet_filter(packet):
        # Inbound filtering precedes Reticulum's increment for the receiving hop.
        if (
            packet.packet_type == RNS.Packet.ANNOUNCE
            and packet.hops + 1 > MAX_ANNOUNCE_HOPS
        ):
            return False
        return original(packet)

    RNS.Transport.packet_filter = staticmethod(packet_filter)


def main():
    install_announce_filter()
    core = RNS.Reticulum(configdir="/var/lib/cixnet/reticulum")
    removed = 0
    for route in core.get_path_table():
        if route["hops"] > MAX_ANNOUNCE_HOPS:
            core.drop_path(route["hash"])
            removed += 1
    print(
        f"Announce limit: {MAX_ANNOUNCE_HOPS} hops; expired {removed} older routes",
        flush=True,
    )
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
