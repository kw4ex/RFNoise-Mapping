"""
anan.py - finds ANAN / openHPSDR "Protocol 2" radios on the network (for example the ANAN-7000DLE MkIII).

ROUND 1 (version 1.4.0j): FINDING ONLY. This file asks a radio to identify itself and reports what it says.
It does not start the radio, tune it, read signal or touch transmit in any way. Reading the radio's signal
comes in the next rounds.

How a radio is found: one 60-byte "discovery" packet (command 0x02) is sent to UDP port 1024 (to one IP
address if you give it, otherwise as a broadcast from each network card). The radio answers with its status,
MAC address, board type, protocol version and firmware version. The reply layout below was confirmed on a
real ANAN-7000DLE MkIII (board type 5, protocol 4.3, firmware 22).

Design and testing: KW4EX. Shared as is, no warranty, use at your own risk.
"""
import socket
import threading
import time

PORT = 1024
BOARD_NOTES = {5: "Orion MkII family (ANAN-7000DLE / 8000DLE class)"}      # only what has been confirmed so far


class AnanError(Exception):
    pass


def packet():
    """The discovery request: 4 bytes of sequence number (0), the command 0x02, padding to 60 bytes."""
    return bytes(4) + b"\x02" + bytes(55)


def parse_discovery(data, addr):
    """Turn a reply into a dict, or None if it is not a Protocol 2 discovery reply."""
    if len(data) < 14 or data[4] not in (2, 3) or data[:4] != bytes(4):
        return None
    return {"ip": addr[0], "port": addr[1],
            "mac": ":".join("%02X" % b for b in data[5:11]),
            "busy": data[4] == 3,                      # 3 = another program (Thetis, ...) is using the radio
            "board": data[11], "board_note": BOARD_NOTES.get(data[11], ""),
            "protocol": data[12], "protocol_text": "%.1f" % (data[12] / 10.0),
            "firmware": data[13]}


def _local_ips():
    ips = set()
    try:
        for ai in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(ai[4][0])
    except Exception:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.0.2.1", 9))
        ips.add(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    return sorted(i for i in ips if not i.startswith("127.") and not i.startswith("169.254."))


def discover(ip=None, timeout=3.0, port=PORT):
    """Look for Protocol 2 radios. With ip given, ask just that address. Returns a list of dicts."""
    import select
    pkt = packet()
    found = {}
    socks = []                                          # (socket, destination)
    try:
        if ip:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            socks.append((s, ip))
        else:
            for lip in _local_ips() or [""]:             # once out of EACH network card
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                try:
                    s.bind((lip, 0))
                except OSError:
                    s.close()
                    continue
                socks.append((s, "255.255.255.255"))
        t_end = time.time() + timeout
        last = 0.0
        while time.time() < t_end:
            if time.time() - last > 0.7:                 # ask again a few times, in case a packet was lost
                for s, dest in socks:
                    try:
                        s.sendto(pkt, (dest, port))
                    except OSError:
                        pass
                last = time.time()
            try:
                ready, _, _ = select.select([x[0] for x in socks], [], [], 0.2)
            except (OSError, ValueError):
                break
            for s in ready:
                try:
                    data, addr = s.recvfrom(2048)
                except OSError:
                    continue
                d = parse_discovery(data, addr)
                if d:
                    found[d["ip"]] = d
            if ip and found:
                break
    finally:
        for s, _d in socks:
            try:
                s.close()
            except OSError:
                pass
    return list(found.values())


# ----------------------------------------------------------------------------
# A pretend ANAN for testing, answering discovery like the real one
# ----------------------------------------------------------------------------
class AnanSim:
    def __init__(self, busy=False, port=0, board=5, protocol=43, firmware=22):
        self.busy, self.board, self.protocol, self.firmware = busy, board, protocol, firmware
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", port))
        self.sock.settimeout(0.05)
        self.port = self.sock.getsockname()[1]
        self.requests = 0
        self._stop = threading.Event()
        self.th = threading.Thread(target=self._loop, daemon=True)
        self.th.start()

    def _loop(self):
        while not self._stop.is_set():
            try:
                data, addr = self.sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            if len(data) >= 5 and data[4] == 2:
                self.requests += 1
                r = bytearray(60)
                r[4] = 3 if self.busy else 2
                r[5:11] = bytes([0x68, 0x27, 0x19, 0x96, 0x8E, 0x44])
                r[11], r[12], r[13] = self.board, self.protocol, self.firmware
                self.sock.sendto(bytes(r), addr)

    def close(self):
        self._stop.set()
        self.th.join(timeout=1.0)
        self.sock.close()
