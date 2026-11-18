"""
anan.py - finds ANAN / openHPSDR "Protocol 2" radios on the network (for example the ANAN-7000DLE MkIII).

ROUND 1 (1.4.0j): FINDING. Asks a radio to identify itself and reports what it says.
ROUND 2 (1.4.0k): A SHORT READ TEST (read_test, run by Tools\\ANAN_Read_Test.bat). It starts ONE receiver for a
couple of seconds, collects the radio signal (I/Q) it sends back, reports the level and where the strongest
signal sits, then stops the radio. It is RECEIVE ONLY: every packet is sent with PTT off, drive at zero and the
power amplifier switched off, and the radio is told to stop in a "finally" step even if something fails.
Using it in a drive comes in the next rounds.

How a radio is found: one 60-byte "discovery" packet (command 0x02) is sent to UDP port 1024 (to one IP
address if you give it, otherwise as a broadcast from each network card). The radio answers with its status,
MAC address, board type, protocol version and firmware version. The reply layout below was confirmed on a
real ANAN-7000DLE MkIII (board type 5, protocol 4.3, firmware 22).

Design and testing: KW4EX. Shared as is, no warranty, use at your own risk.
"""
import socket
import struct
import sys
import threading
import time

PORT = 1024                 # discovery and the General packet (the radio listens here)
P_DDC_SPEC, P_HIGH_PRI, P_DDC0 = 1025, 1027, 1035      # ports as they are in the Protocol 2 description used by Thetis, piHPSDR
PKT = 1444                  # command packets and DDC data packets are 1444 bytes
ADC_CLOCK = 122880000.0     # the radio's converter clock, used for the "phase word" form of a frequency
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
# The packets (receive only)
# ----------------------------------------------------------------------------
def phase_word(hz):
    return int(round(float(hz) / ADC_CLOCK * 4294967296.0)) & 0xFFFFFFFF


def general_packet(seq, base=PORT, phase=True):
    """Tells the radio which ports the PC listens on. Everything that could switch on transmit stays zero."""
    b = bytearray(60)
    struct.pack_into(">I", b, 0, seq)
    b[4] = 0x00
    for off, port in ((5, base + 1), (7, base + 2), (9, base + 3), (11, base + 1), (13, base + 4), (15, base + 11),
                      (17, base + 5), (19, base + 2), (21, base + 3)):
        struct.pack_into(">H", b, off, port)
    b[37] = 0x08 if phase else 0x00         # bit 3: the frequency is sent as a phase word (1) or in Hz (0)
    return bytes(b)


def ddc_packet(seq, rate_khz):
    """DDC-Specific: switch on DDC0 only, taking ADC0, at rate_khz, 24 bits per sample."""
    b = bytearray(PKT)
    struct.pack_into(">I", b, 0, seq)
    b[4] = 2                                # number of ADCs on the board
    b[7] = 0x01                             # DDC0 enabled
    b[17] = 0                               # DDC0 uses ADC0
    struct.pack_into(">H", b, 18, int(rate_khz))
    b[22] = 24
    return bytes(b)


def high_priority_packet(seq, run, freq_hz, phase=True):
    """High Priority: run bit, DDC0 frequency. PTT stays 0 and the drive level stays 0 (all other bytes zero)."""
    b = bytearray(PKT)
    struct.pack_into(">I", b, 0, seq)
    b[4] = 0x01 if run else 0x00            # bit 0 run; bit 1 (PTT) is never set
    struct.pack_into(">I", b, 5, phase_word(freq_hz) if phase else int(freq_hz) & 0xFFFFFFFF)
    return bytes(b)


def parse_ddc(data):
    """A DDC data packet -> (sequence, complex samples scaled to +-1) or None."""
    import numpy as np
    if len(data) < 16 + 6:
        return None
    seq = struct.unpack(">I", data[0:4])[0]
    bits, n = struct.unpack(">HH", data[12:16])
    if bits != 24 or n <= 0 or len(data) < 16 + 6 * n:
        return None
    raw = np.frombuffer(data, dtype=np.uint8, count=6 * n, offset=16).reshape(n, 2, 3).astype(np.int32)
    v = (raw[:, :, 0] << 16) | (raw[:, :, 1] << 8) | raw[:, :, 2]
    v = np.where(v >= 1 << 23, v - (1 << 24), v) / float(1 << 23)
    return seq, v[:, 0] + 1j * v[:, 1]


class AnanReader:
    """Starts DDC0 for a while and collects its samples. Always stops the radio (see stop())."""

    def __init__(self, ip, base=PORT, rate_khz=192, phase=True):
        self.ip, self.base, self.rate_khz, self.phase = ip, base, rate_khz, phase
        self.tx = None
        self.rx = None
        self.seq = {"gen": 0, "ddc": 0, "hp": 0}
        self.freq = 0.0
        self.started = False

    def _send(self, kind, pkt, port):
        self.tx.sendto(pkt, (self.ip, port))
        self.seq[kind] += 1

    def start(self, freq_hz):
        self.freq = float(freq_hz)
        try:
            self.rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.rx.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
            self.rx.bind(("", self.base + 11))
        except OSError as e:
            self.close()
            raise AnanError("Could not listen on port %d (%s). Another program, such as Thetis, is probably using the radio. Close it and try again." % (self.base + 11, e))
        self.rx.settimeout(0.2)
        self.tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._send("gen", general_packet(self.seq["gen"], self.base, self.phase), self.base)
        time.sleep(0.05)
        self._send("ddc", ddc_packet(self.seq["ddc"], self.rate_khz), self.base + 1)
        time.sleep(0.05)
        self._send("hp", high_priority_packet(self.seq["hp"], True, self.freq, self.phase), self.base + 3)
        self.started = True

    def collect(self, seconds):
        """Returns (list of (seq, samples), number of datagrams that were not DDC data)."""
        out, other = [], 0
        end = time.time() + seconds
        last_hp = time.time()
        while time.time() < end:
            if time.time() - last_hp > 0.2:                    # keep the radio's watchdog happy
                self._send("hp", high_priority_packet(self.seq["hp"], True, self.freq, self.phase), self.base + 3)
                last_hp = time.time()
            try:
                data, addr = self.rx.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            p = parse_ddc(data)
            if p:
                out.append(p)
            else:
                other += 1
        return out, other

    def stop(self):
        if self.tx is not None:
            for _ in range(3):
                try:
                    self._send("hp", high_priority_packet(self.seq["hp"], False, self.freq, self.phase), self.base + 3)
                except OSError:
                    pass
                time.sleep(0.05)
        self.started = False
        self.close()

    def close(self):
        for s in (self.rx, self.tx):
            try:
                if s:
                    s.close()
            except OSError:
                pass
        self.rx = self.tx = None


def analyse(pkts, rate_khz):
    """Level and strongest signal of what was received."""
    import numpy as np
    if not pkts:
        return {"packets": 0}
    seqs = [p[0] for p in pkts]
    lost = sum(max(0, (b - a - 1)) for a, b in zip(seqs, seqs[1:]))
    x = np.concatenate([p[1] for p in pkts])
    pw = float(np.mean(np.abs(x) ** 2)) or 1e-30
    n = 8192
    res = {"packets": len(pkts), "lost": lost, "samples": len(x), "level_dbfs": 10 * np.log10(pw)}
    if len(x) >= n:
        w = np.hanning(n)
        acc = np.zeros(n)
        k = 0
        for i in range(0, len(x) - n + 1, n):
            acc += np.abs(np.fft.fftshift(np.fft.fft(x[i:i + n] * w))) ** 2
            k += 1
        sp = 10 * np.log10(acc / k + 1e-30)
        f = (np.arange(n) - n // 2) * (rate_khz * 1000.0 / n)
        j = int(np.argmax(sp))
        res.update(peak_offset_khz=float(f[j] / 1000.0), peak_over_median_db=float(sp[j] - np.median(sp)))
    return res


def read_test(ip, freq_mhz=10.0, seconds=2.0, rate_khz=192, modes=("phase", "hz"), base=PORT, say=print):
    """Tunes DDC0 to freq_mhz and reads for `seconds`, once per way of sending the frequency. Receive only."""
    results = {}
    for m in modes:
        say("What I am doing: starting receiver 0 at %.4f MHz (frequency sent as %s) for %.0f seconds..." %
            (freq_mhz, "a phase word" if m == "phase" else "Hz", seconds))
        r = AnanReader(ip, base, rate_khz, m == "phase")
        try:
            r.start(freq_mhz * 1e6)
            pkts, other = r.collect(seconds)
        except AnanError as e:
            say("  " + str(e))
            return results
        finally:
            r.stop()                                            # always tell the radio to stop
        a = analyse(pkts, rate_khz)
        a["other_datagrams"] = other
        results[m] = a
        if a["packets"] == 0:
            say("  No signal data came back (%d other packets)." % other)
            say("  Most likely cause: the Windows Firewall is blocking UDP port %d for Python. Fix: run Tools\\Allow_ANAN_Firewall.bat once (it asks Windows for permission), then run this test again." % (base + 11))
            say("  Other possible causes: another program is using the radio, or the radio's Protocol 2 firmware.")
        else:
            say("  Received %d packets (%d samples), %d lost. Level %.1f dBFS." % (a["packets"], a["samples"], a["lost"], a["level_dbfs"]))
            if "peak_offset_khz" in a:
                say("  Strongest signal: %+.2f kHz from the tuned frequency, %.1f dB above the typical noise." % (a["peak_offset_khz"], a["peak_over_median_db"]))
        time.sleep(1.0)
    say("The radio was told to stop.")
    return results


def main(argv):
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    rep = os.path.join(os.path.dirname(here), "Reports")
    rep = os.path.join(rep if os.path.isdir(rep) else here, "anan_read_test.txt")
    lines = []

    def say(t=""):
        print(t)
        lines.append(t)
    args = [a for a in argv if not a.startswith("-")]
    ip = ""
    mhz = None
    for a in args:
        if a.count(".") == 3:
            ip = a
        else:
            try:
                mhz = float(a)
            except ValueError:
                pass
    say("ANAN read test (receive only). Design and testing: KW4EX. Shared as is, no warranty, use at your own risk.")
    say("Time: " + time.strftime("%Y-%m-%d %H:%M:%S"))
    if not ip:
        say("What I am doing: looking for the ANAN on the network (3 seconds)...")
        d = discover(None, 3.0)
        if not d:
            say("No ANAN answered. Check the cable and power, or give its address, e.g. ANAN_Read_Test.bat 192.168.0.51")
            open(rep, "w", encoding="utf-8").write("\n".join(lines) + "\n")
            return 1
        ip = d[0]["ip"]
        say("Found it at %s (%s)." % (ip, "free" if not d[0]["busy"] else "IN USE by another program: close Thetis first"))
        if d[0]["busy"]:
            open(rep, "w", encoding="utf-8").write("\n".join(lines) + "\n")
            return 1
    if mhz is None:
        mhz = 10.0
    say("Tuned frequency: %.4f MHz. Tip: put a known steady signal here (for example 10.000 MHz WWV or an AM broadcast carrier) if an antenna is connected." % mhz)
    try:
        read_test(ip, mhz, say=say)
    finally:
        try:
            open(rep, "w", encoding="utf-8").write("\n".join(lines) + "\n")
            print("This report is saved in: " + rep)
        except OSError as e:
            print("Could not save the report: %s" % e)
    return 0



# ----------------------------------------------------------------------------
# A pretend ANAN for testing, answering discovery like the real one
# ----------------------------------------------------------------------------
class AnanSim:
    """A pretend ANAN on 127.0.0.1. port = the "discovery/General" port (0 = any, discovery only). With a fixed
    port it also does the Protocol 2 handshake and streams DDC0 I/Q like the real radio would: noise plus one
    carrier at carrier_hz. It follows the same reading of the frequency fields as the program does, so it
    proves the program is consistent with itself, not with the real radio."""

    def __init__(self, busy=False, port=0, board=5, protocol=43, firmware=22, carrier_hz=10010200.0,
                 carrier_dbfs=-50.0, noise_dbfs=-95.0):
        self.busy, self.board, self.protocol, self.firmware = busy, board, protocol, firmware
        self.carrier_hz, self.carrier_dbfs, self.noise_dbfs = carrier_hz, carrier_dbfs, noise_dbfs
        self.requests = 0
        self.run = False
        self.freq = 0.0
        self.rate_khz = 192
        self.ddc_on = False
        self.client = None
        self.pc_ddc_port = 0
        self.ptt_seen = False
        self.max_hp_byte_nonzero = False
        self.phase = True
        self.base = port
        self.socks = {}
        for k, off in (("gen", 0), ("ddc", 1), ("hp", 3)):
            if off and not port:
                continue
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.bind(("127.0.0.1", port + off))
            s.settimeout(0.02)
            self.socks[k] = s
        self.port = self.socks["gen"].getsockname()[1]
        self.out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._stop = threading.Event()
        self.th = threading.Thread(target=self._loop, daemon=True)
        self.th.start()

    def _handle(self, kind, data, addr):
        if kind == "gen":
            if len(data) >= 5 and data[4] == 2:
                self.requests += 1
                r = bytearray(60)
                r[4] = 3 if self.busy else 2
                r[5:11] = bytes([0x68, 0x27, 0x19, 0x96, 0x8E, 0x44])
                r[11], r[12], r[13] = self.board, self.protocol, self.firmware
                self.socks["gen"].sendto(bytes(r), addr)
            elif len(data) >= 38 and data[4] == 0:
                self.client = addr[0]
                self.pc_ddc_port = struct.unpack(">H", data[15:17])[0]
                self.phase = bool(data[37] & 0x08)
        elif kind == "ddc" and len(data) >= 23:
            self.ddc_on = bool(data[7] & 1)
            self.rate_khz = struct.unpack(">H", data[18:20])[0] or 192
        elif kind == "hp" and len(data) >= 9:
            self.run = bool(data[4] & 1)
            if data[4] & 2:
                self.ptt_seen = True
            if any(data[9:]):
                self.max_hp_byte_nonzero = True            # anything else (drive, TX frequency...) must stay zero
            w = struct.unpack(">I", data[5:9])[0]
            self.freq = w / 4294967296.0 * ADC_CLOCK if self.phase else float(w)

    def _loop(self):
        import numpy as np
        rng = np.random.default_rng(1)
        n = 238
        t = 0
        nxt = time.time()
        seq = 0
        while not self._stop.is_set():
            for k, s in self.socks.items():
                try:
                    d, a = s.recvfrom(4096)
                except socket.timeout:
                    continue
                except OSError:
                    return
                self._handle(k, d, a)
            if self.run and self.ddc_on and self.client and self.pc_ddc_port:
                now = time.time()
                step = n / (self.rate_khz * 1000.0)
                while nxt <= now:
                    idx = np.arange(t, t + n)
                    fs = self.rate_khz * 1000.0
                    amp_n = 10 ** (self.noise_dbfs / 20.0) / np.sqrt(2)
                    x = amp_n * (rng.standard_normal(n) + 1j * rng.standard_normal(n))
                    off = self.carrier_hz - self.freq
                    if abs(off) < fs / 2:
                        x = x + 10 ** (self.carrier_dbfs / 20.0) * np.exp(2j * np.pi * off * idx / fs)
                    qi = np.clip(np.round(np.real(x) * (1 << 23)), -(1 << 23), (1 << 23) - 1).astype(np.int64) & 0xFFFFFF
                    qq = np.clip(np.round(np.imag(x) * (1 << 23)), -(1 << 23), (1 << 23) - 1).astype(np.int64) & 0xFFFFFF
                    arr = np.empty((n, 6), dtype=np.uint8)
                    for j, v in enumerate((qi, qq)):
                        arr[:, 3 * j] = (v >> 16) & 255
                        arr[:, 3 * j + 1] = (v >> 8) & 255
                        arr[:, 3 * j + 2] = v & 255
                    pkt = struct.pack(">IQHH", seq, 0, 24, n) + arr.tobytes()
                    try:
                        self.out.sendto(pkt, (self.client, self.pc_ddc_port))
                    except OSError:
                        pass
                    seq += 1
                    t += n
                    nxt += step
            else:
                nxt = time.time()
                time.sleep(0.005)

    def close(self):
        self._stop.set()
        self.th.join(timeout=1.0)
        for s in list(self.socks.values()) + [self.out]:
            s.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
