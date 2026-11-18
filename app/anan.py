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


Hl2Error = AnanError                      # the shared reading code (rf_logger) catches this name


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


DDC_N = 2                                   # Thetis receives on DDC2 (data comes back from port base+11+2)
PORT_LIST = (PORT + 1, PORT + 2, PORT + 3, PORT + 1, PORT + 4, PORT + 5, PORT + 11, PORT + 2, PORT + 3)


def general_packet(seq, base=PORT, phase=True):
    """General: copied from what Thetis sends (recorded on the real ANAN-7000DLE MkIII). Nothing here switches on transmit."""
    b = bytearray(60)
    struct.pack_into(">I", b, 0, seq)
    for off, port in zip((5, 7, 9, 11, 13, 15, 17, 19, 21), (base + 1, base + 2, base + 3, base + 1, base + 4, base + 5,
                                                              base + 11, base + 2, base + 3)):
        struct.pack_into(">H", b, off, port)
    for i, v in ((24, 0x02), (26, 0x10), (27, 0x46), (28, 0x20), (33, 0x03), (34, 0x20), (36, 0x64), (37, 0x08 if phase else 0x00),
                 (38, 0x01), (58, 0x01), (59, 0x03)):
        b[i] = v
    return bytes(b)


def ddc_packet(seq, rate_khz, ddcs=None):
    """DDC-Specific: copied from Thetis, with the receivers in `ddcs` switched on (all on ADC0) at rate_khz,
    24 bits per sample. Default: only DDC2, like Thetis."""
    ddcs = tuple(ddcs) if ddcs else (DDC_N,)
    b = bytearray(PKT)
    struct.pack_into(">I", b, 0, seq)
    for i, v in ((4, 2), (5, 7), (6, 7), (22, 24), (23, 1), (28, 24), (34, 24), (35, 1), (40, 24), (43, 0x30),
                 (46, 24), (49, 0x30), (52, 24), (55, 0x30), (58, 24)):
        b[i] = v
    mask = 0
    for d in ddcs:
        mask |= 1 << d
        row = 17 + 6 * d
        b[row] = 0                          # this DDC takes ADC0
        struct.pack_into(">H", b, row + 1, int(rate_khz))
        b[row + 3] = b[row + 4] = 0
        b[row + 5] = 24
    b[7] = mask
    return bytes(b)


def high_priority_packet(seq, run, freq_hz, phase=True, alex=True):
    """High Priority (1444 bytes like Thetis): run bit and the receive frequencies. freq_hz is one number
    (DDC1 to DDC4 all get it, as Thetis does) or a dict {ddc number: Hz}. PTT never set, drive level 0."""
    b = bytearray(PKT)
    struct.pack_into(">I", b, 0, seq)
    b[4] = 0x01 if run else 0x00            # bit 0 run; bit 1 (PTT) is never set
    items = freq_hz.items() if isinstance(freq_hz, dict) else [(d, freq_hz) for d in (1, 2, 3, 4)]
    for d, hz in items:
        w = phase_word(hz) if phase else int(hz) & 0xFFFFFFFF
        struct.pack_into(">I", b, 5 + 4 * int(d), w)
    b[345] = 0                              # TX drive level (Thetis sends 0x22 or more; we send none)
    if alex:
        b[1400] = 0x02
        for i, v in ((1428, 0x01), (1429, 0x10), (1431, 0x20), (1432, 0x01), (1433, 0x10), (1434, 0x10)):
            b[i] = v                        # filter / relay bytes as Thetis sends them at 10 MHz (at 3.7 MHz only byte 1429/1433 differ: a transmit filter)
    return bytes(b)


def duc_packet(seq):
    """DUC-Specific (60 bytes) as Thetis sends it. Only used by the 'streams' way of starting."""
    b = bytearray(60)
    struct.pack_into(">I", b, 0, seq)
    for i, v in ((4, 1), (5, 0xAA), (7, 2), (8, 0x58), (9, 0x19), (10, 0x32), (11, 1), (12, 0x36), (13, 7), (15, 0xC0), (17, 9),
                 (50, 6), (51, 0x17), (57, 0x1F), (58, 0x1F), (59, 0x1F)):
        b[i] = v
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
    return seq, v[:, 1] + 1j * v[:, 0]          # the ANAN sends the pair the other way round: swapping keeps the spectrum the right way up (checked with WWV)


class AnanReader:
    """Starts one receiver for a while and collects its samples. Always stops the radio (see stop()).
    One socket does everything: the radio sends its answers back to the port the requests came from."""

    def __init__(self, ip, base=PORT, rate_khz=192, phase=True, streams=False, alex=True):
        self.ip, self.base, self.rate_khz, self.phase, self.streams, self.alex = ip, base, rate_khz, phase, streams, alex
        self.sock = None
        self.seq = {"gen": 0, "ddc": 0, "hp": 0, "duc": 0, "iq": 0, "aud": 0}
        self.freq = 0.0
        self.started = False
        self._tx_t = 0.0

    @property
    def tx(self):
        return self.sock

    def _send(self, kind, pkt, port):
        self.sock.sendto(pkt, (self.ip, port))
        self.seq[kind] += 1

    def _hp(self, run):
        self._send("hp", high_priority_packet(self.seq["hp"], run, self.freq, self.phase, self.alex), self.base + 3)

    def start(self, freq_hz):
        self.freq = float(freq_hz)
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
            self.sock.bind(("", 0))
        except OSError as e:
            self.close()
            raise AnanError("Could not open a network port (%s)." % e)
        self.sock.settimeout(0.05)
        self._send("gen", general_packet(self.seq["gen"], self.base, self.phase), self.base)
        time.sleep(0.05)
        self._send("ddc", ddc_packet(self.seq["ddc"], self.rate_khz), self.base + 1)
        if self.streams:
            self._send("duc", duc_packet(self.seq["duc"]), self.base + 2)
        time.sleep(0.05)
        self._hp(True)
        self._tx_t = time.time()
        self.started = True

    def _keepalive(self):
        """Every 0.2 s: High Priority (and General). In 'streams' mode also silent TX I/Q and audio like Thetis."""
        self._hp(True)
        self._send("gen", general_packet(self.seq["gen"], self.base, self.phase), self.base)

    def _pump_streams(self, now):
        if not self.streams:
            return
        due = int((now - self._tx_t) * 200)
        for _ in range(min(due, 50)):
            self._send("iq", struct.pack(">I", self.seq["iq"]) + bytes(PKT - 4), self.base + 5)
            self._send("aud", struct.pack(">I", self.seq["aud"]) + bytes(256), self.base + 4)
        if due:
            self._tx_t = now

    def collect(self, seconds):
        """Returns (list of (seq, samples), number of datagrams that were not DDC data)."""
        out, other = [], 0
        end = time.time() + seconds
        last = time.time()
        while time.time() < end:
            now = time.time()
            if now - last > 0.2:                                # keep the radio's watchdog happy
                self._keepalive()
                last = now
            self._pump_streams(now)
            try:
                data, addr = self.sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            p = parse_ddc(data) if len(data) == PKT else None
            if p:
                out.append(p)
            else:
                other += 1
        return out, other

    def stop(self):
        if self.sock is not None:
            for _ in range(3):
                try:
                    self._hp(False)
                except OSError:
                    pass
                time.sleep(0.05)
        self.started = False
        self.close()

    def close(self):
        try:
            if self.sock:
                self.sock.close()
        except OSError:
            pass
        self.sock = None


class AnanClient:
    """Runs several receivers at once and keeps one ring of samples per receiver (same idea as Hl2Client).
    The radio sends receiver n from its port base+11+n back to the port we sent from, so one socket does it all."""

    RING = 1 << 18
    SETTLE_S = 0.08                       # after a retune, ignore this long (old-frequency samples still in the pipeline)

    def __init__(self, ip, base=PORT, rate=192000, nrx=4, ddcs=(2, 3, 4, 5)):
        if rate not in (48000, 96000, 192000, 384000):
            raise AnanError("Sample rate must be one of 48000, 96000, 192000 or 384000.")
        self.ip, self.base, self.rate = ip, int(base), int(rate)
        self.ddcs = tuple(ddcs)[:max(1, min(len(ddcs), int(nrx)))]
        self.nrx = len(self.ddcs)
        self.freq = [7_000_000] * self.nrx
        self.sock = None
        self.lock = threading.Lock()
        self.ring = [np_zeros(self.RING) for _ in range(self.nrx)]
        self.count = [0] * self.nrx
        self.t_last = [0.0] * self.nrx
        self.retune_t = [0.0] * self.nrx
        self.packets = 0
        self.lost = 0
        self.overload = False
        self._seq_in = {}
        self.seq = {"gen": 0, "ddc": 0, "hp": 0}
        self._stop = threading.Event()
        self._rx_thread = self._tx_thread = None

    # ---- commands ----
    def _send(self, kind, pkt, port):
        try:
            self.sock.sendto(pkt, (self.ip, port))
        except OSError:
            return
        self.seq[kind] += 1

    def _hp(self, run):
        with self.lock:
            fr = {d: self.freq[i] for i, d in enumerate(self.ddcs)}
        self._send("hp", high_priority_packet(self.seq["hp"], run, fr), self.base + 3)

    def _tx_loop(self):
        t_next = time.time()
        while not self._stop.is_set():
            self._hp(True)
            self._send("gen", general_packet(self.seq["gen"], self.base, True), self.base)
            t_next += 0.2
            time.sleep(max(0.0, t_next - time.time()))

    # ---- receiving ----
    def _rx_loop(self):
        import numpy as np
        s = self.sock
        lo = self.base + 11
        while not self._stop.is_set():
            try:
                data, a = s.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            if len(data) == 60 and a[1] == self.base + 1:           # the radio's status packet
                if data[5] & 1:                                     # ADC0 overload bit (as the protocol describes it)
                    self.overload = True
                continue
            if len(data) != PKT or not (lo <= a[1] < lo + 16):
                continue
            ddc = a[1] - lo
            if ddc not in self.ddcs:
                continue
            r = self.ddcs.index(ddc)
            p = parse_ddc(data)
            if not p:
                continue
            seq, z = p
            prev = self._seq_in.get(ddc)
            if prev is not None and seq != ((prev + 1) & 0xFFFFFFFF):
                self.lost += (seq - prev - 1) & 0xFFFFFFFF
            self._seq_in[ddc] = seq
            self.packets += 1
            z = z.astype(np.complex64)
            c = self.count[r]
            pos = c % self.RING
            k = len(z)
            if pos + k <= self.RING:
                self.ring[r][pos:pos + k] = z
            else:
                h = self.RING - pos
                self.ring[r][pos:] = z[:h]
                self.ring[r][:k - h] = z[h:]
            self.count[r] = c + k
            self.t_last[r] = time.time()

    # ---- life cycle ----
    def start(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
        self.sock.bind(("", 0))
        self.sock.settimeout(0.25)
        self._stop.clear()
        self._send("gen", general_packet(self.seq["gen"], self.base, True), self.base)
        time.sleep(0.05)
        self._send("ddc", ddc_packet(self.seq["ddc"], self.rate // 1000, self.ddcs), self.base + 1)
        time.sleep(0.05)
        self._hp(True)
        self._tx_thread = threading.Thread(target=self._tx_loop, daemon=True)
        self._rx_thread = threading.Thread(target=self._rx_loop, daemon=True)
        self._tx_thread.start()
        self._rx_thread.start()
        t0 = time.time()
        while time.time() - t0 < 3.0:
            if all(c > 0 for c in self.count):
                return
            time.sleep(0.02)
        got = [d for d, c in zip(self.ddcs, self.count) if c > 0]
        self.stop()
        if got:
            raise AnanError("Only some of the ANAN receivers sent samples (receivers %s of %s)." % (got, list(self.ddcs)))
        raise AnanError("The ANAN did not send any samples. Check the network cable and power, that no other program "
                        "(Thetis, SDR Console) is using the radio, and the Windows Firewall rule (Tools\\Allow_ANAN_Firewall.bat).")

    def stop(self):
        """Always tells the radio to stop (run bit off, three times)."""
        self._stop.set()
        for t in (self._rx_thread, self._tx_thread):
            if t:
                t.join(timeout=1.0)
        if self.sock is not None:
            for _ in range(3):
                self._hp(False)
                time.sleep(0.05)
            try:
                self.sock.close()
            except OSError:
                pass
        self.sock = None

    # ---- settings and samples ----
    def set_freq(self, rx, hz):
        hz = int(round(hz))
        with self.lock:
            if self.freq[rx] == hz:
                return False
            self.freq[rx] = hz
            self.retune_t[rx] = time.time()
        self._hp(True)                                              # tell the radio at once
        return True

    def take(self, rx, n, timeout=1.0):
        """The newest n samples of receiver rx and the time of their middle (like Hl2Client.take)."""
        import numpy as np
        if self.retune_t[rx]:
            t_ok = self.retune_t[rx] + self.SETTLE_S
            while time.time() < t_ok:
                time.sleep(0.002)
            c0 = self.count[rx]
            t_end = time.time() + timeout + n / float(self.rate)
            while self.count[rx] < c0 + n and time.time() < t_end:
                time.sleep(0.002)
            self.retune_t[rx] = 0.0
        t_end = time.time() + timeout
        while self.count[rx] < n and time.time() < t_end:
            time.sleep(0.002)
        if self.count[rx] < n:
            raise AnanError("Not enough samples arrived from the radio.")
        c = self.count[rx]
        tl = self.t_last[rx]
        x = self.ring[rx][np.arange(c - n, c) % self.RING].copy()
        if self.count[rx] - c > self.RING - n:
            raise AnanError("Samples were lost while reading.")
        return x, tl - 0.5 * n / self.rate


def np_zeros(n):
    import numpy as np
    return np.zeros(n, np.complex64)


def analyse(pkts, rate_khz, targets=()):
    """Level and strongest signals of what was received. The DC offset is removed, the band edges (filter skirts)
    and the middle 1.5 kHz are ignored, and peaks are measured against the typical noise of the usable part."""
    import numpy as np
    if not pkts:
        return {"packets": 0}
    seqs = [p[0] for p in pkts]
    lost = sum(max(0, (b - a - 1)) for a, b in zip(seqs, seqs[1:]))
    x = np.concatenate([p[1] for p in pkts])
    dc = complex(np.mean(x))
    x = x - dc
    pw = float(np.mean(np.abs(x) ** 2)) or 1e-30
    n = 8192
    res = {"packets": len(pkts), "lost": lost, "samples": len(x), "level_dbfs": 10 * np.log10(pw),
           "dc_dbfs": 20 * np.log10(abs(dc) + 1e-30)}
    if len(x) >= n:
        w = np.hanning(n)
        acc = np.zeros(n)
        k = 0
        for i in range(0, len(x) - n + 1, n):
            acc += np.abs(np.fft.fftshift(np.fft.fft(x[i:i + n] * w))) ** 2
            k += 1
        sp = 10 * np.log10(acc / k + 1e-30)
        f = (np.arange(n) - n // 2) * (rate_khz * 1000.0 / n)
        use = (np.abs(f) < rate_khz * 1000.0 * 0.4) & (np.abs(f) > 750.0)
        floor = float(np.median(sp[use]))
        idx = np.where(use)[0]
        order = idx[np.argsort(sp[idx])[::-1]]
        peaks = []
        for j in order:
            if all(abs(f[j] - p[0]) > 1500.0 for p in peaks):
                peaks.append((float(f[j]), float(sp[j] - floor)))
            if len(peaks) == 5:
                break
        res["floor_dbfs_per_bin"] = floor
        res["targets"] = {}
        for t in targets:                                   # level at a wanted offset (kHz), +-0.3 kHz
            m = np.abs(f - t * 1000.0) < 300.0
            res["targets"][t] = float(np.max(sp[m]) - floor) if m.any() else None
        res["peaks"] = [(round(o / 1000.0, 3), round(d, 1)) for o, d in peaks]
        res.update(peak_offset_khz=peaks[0][0] / 1000.0, peak_over_median_db=peaks[0][1])
    return res


def read_test(ip, freq_mhz=10.0, seconds=2.0, rate_khz=192, modes=("basic", "streams"), base=PORT, say=print, alex=True, targets=()):
    """Tunes the receiver to freq_mhz and reads for `seconds`, once per way of starting. Receive only.
    basic = General + DDC-Specific + High Priority. streams = the same plus silent transmit streams like Thetis sends."""
    results = {}
    for m in modes:
        say("What I am doing: starting a receiver at %.4f MHz (%s start) for %.0f seconds..." %
            (freq_mhz, "Thetis-like, with silent transmit streams" if m == "streams" else "basic", seconds))
        r = AnanReader(ip, base, rate_khz, True, streams=(m == "streams"), alex=alex)
        try:
            r.start(freq_mhz * 1e6)
            pkts, other = r.collect(seconds)
        except AnanError as e:
            say("  " + str(e))
            return results
        finally:
            r.stop()                                            # always tell the radio to stop
        a = analyse(pkts, rate_khz, targets)
        a["other_datagrams"] = other
        results[m] = a
        if a["packets"] == 0:
            say("  No signal data came back (%d other packets)." % other)
        else:
            say("  Received %d packets (%d samples), %d lost. Level %.1f dBFS." % (a["packets"], a["samples"], a["lost"], a["level_dbfs"]))
            say("  DC offset (the radio's own constant) %.1f dBFS - removed before measuring." % a["dc_dbfs"])
            for off, db in a.get("peaks", []):
                say("  Peak %+8.3f kHz from the tuned frequency (%.4f MHz): %.1f dB above the typical noise." % (off, freq_mhz + off / 1000.0, db))
            for t, db in (a.get("targets") or {}).items():
                say("  At the wanted offset %+.1f kHz: %s." % (t, "%.1f dB above the typical noise" % db if db is not None else "outside the band"))
            time.sleep(0.5)
            break                                               # the first way that works is enough
        time.sleep(1.0)
    say("The radio was told to stop.")
    if results and all(v.get("packets", 0) == 0 for v in results.values()):
        diagnose(ip, freq_mhz, base, say)
    return results


RULE_NAME = "RF Noise Map - ANAN radio data (Python)"


def multi_test(ip, say=print, base=PORT, ddcs=(2, 3, 4, 5), seconds=2.0):
    """Four receivers at once on WWV's 5, 10 and 15 MHz and on 2.5 MHz, each tuned 5 kHz below the carrier, so the
    carrier should show up at +5 kHz in each. Receive only. Returns how many receivers found their carrier."""
    import numpy as np
    plan = [(4.995e6, "WWV 5 MHz"), (9.995e6, "WWV 10 MHz"), (14.995e6, "WWV 15 MHz"), (2.495e6, "WWV 2.5 MHz")]
    say("What I am doing: starting four receivers at once (receivers %s) for %.0f seconds..." % (list(ddcs), seconds))
    c = AnanClient(ip, base, 192000, 4, ddcs)
    for i, (hz, _n) in enumerate(plan):
        c.freq[i] = hz
    found = 0
    try:
        c.start()
        time.sleep(seconds)
        for i, (hz, name) in enumerate(plan):
            x, _t = c.take(i, 32768)
            x = x - np.mean(x)
            n = 8192
            w = np.hanning(n)
            acc = np.zeros(n)
            k = 0
            for j in range(0, len(x) - n + 1, n):
                acc += np.abs(np.fft.fftshift(np.fft.fft(x[j:j + n] * w))) ** 2
                k += 1
            sp = 10 * np.log10(acc / k + 1e-30)
            f = (np.arange(n) - n // 2) * (192000.0 / n)
            use = (np.abs(f) < 76800.0) & (np.abs(f) > 750.0)
            floor = float(np.median(sp[use]))
            m = np.abs(f - 5000.0) < 300.0
            db = float(np.max(sp[m]) - floor)
            j = int(np.argmax(np.where(use, sp, -1e9)))
            ok = db >= 15.0
            found += 1 if ok else 0
            say("  Receiver %d, tuned %.4f MHz (%s): carrier at +5 kHz is %.1f dB above the typical noise - %s. Level %.1f dBFS. Strongest anywhere: %+.1f kHz." %
                (ddcs[i], hz / 1e6, name, db, "FOUND" if ok else "not seen (it may simply be weak right now)",
                 10 * np.log10(float(np.mean(np.abs(x) ** 2)) + 1e-30), f[j] / 1000.0))
        say("  %d packets, %d lost." % (c.packets, c.lost))
    except AnanError as e:
        say("  " + str(e))
    finally:
        c.stop()
        say("The radio was told to stop.")
    return found


def _run(cmd):
    import subprocess
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=15).stdout
    except Exception as e:
        return "(could not run: %s)" % e


def diagnose(ip, freq_mhz, base=PORT, say=print):
    """Used when nothing came back: checks this PC's side and listens on EVERY port the radio might use."""
    say("")
    say("--- Extra checks (nothing came back, so let us look closer) ---")
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect((ip, base))
        local = s.getsockname()[0]
        s.close()
        say("This PC reaches the radio from its address %s." % local)
    except OSError as e:
        local = ""
        say("Could not work out this PC's address towards the radio: %s" % e)
    if sys.platform == "win32":
        out = _run(["netsh", "advfirewall", "firewall", "show", "rule", "name=" + RULE_NAME])
        if "Rule Name" in out:
            enabled = [l.strip() for l in out.splitlines() if l.strip().startswith(("Enabled", "Program", "Profiles", "RemoteIP"))]
            say("Firewall rule FOUND: " + " | ".join(enabled))
        else:
            say("Firewall rule NOT found (%s). Run Tools\\Allow_ANAN_Firewall.bat and press Y." % RULE_NAME)
        st = [l.strip() for l in _run(["netsh", "advfirewall", "show", "allprofiles", "state"]).splitlines() if l.strip().startswith(("Domain", "Private", "Public", "State"))]
        say("Windows Firewall state: " + " | ".join(st))
        say("Python program used: " + sys.executable)
    say("Listening for anything the radio sends back, on the same port the requests leave from...")
    r = AnanReader(ip, base, 192, True, streams=True)
    seen = {}
    try:
        r.start(freq_mhz * 1e6)
        end = time.time() + 2.5
        last = time.time()
        while time.time() < end:
            now = time.time()
            if now - last > 0.2:
                r._keepalive()
                last = now
            r._pump_streams(now)
            try:
                d, a = r.sock.recvfrom(4096)
            except (socket.timeout, OSError):
                continue
            e = seen.setdefault((a[0], a[1]), [0, len(d), d[:16].hex(" ")])
            e[0] += 1
    finally:
        r.stop()
    if not seen:
        say("Nothing at all came back from the radio. It did not answer the start request, or Windows is blocking it.")
    for (ip_, p), (n, ln, h) in sorted(seen.items()):
        say("From %s port %d: %d packets of %d bytes, starting %s" % (ip_, p, n, ln, h))
    say("The radio was told to stop.")


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
    say("Known-signal check: WWV is on 10.000 MHz. The radio is tuned 10 kHz below and 10 kHz above it, so WWV should show up")
    say("at +10 kHz and at -10 kHz (at 10.000 MHz in both cases).")
    try:
        ok = 0
        for f, want in ((9.990, 10.0), (10.010, -10.0)):
            say("")
            res = read_test(ip, f, say=say, modes=("basic",), targets=(want,))
            for v in res.values():
                db = (v.get("targets") or {}).get(want)
                if db is not None and db >= 15.0:
                    ok += 1
        say("")
        say("--- Four receivers at once ---")
        nf = multi_test(ip, say=say)
        say("")
        if ok == 2:
            say("RESULT: WWV was found at the right place both times, so frequencies and the spectrum direction are correct.")
        elif ok == 1:
            say("RESULT: WWV was found once. WWV may be weak right now, or one reading is wrong - send this report to Claude.")
        else:
            say("RESULT: WWV was not found. It may be too weak at this time of day, or something is still wrong - send this report to Claude.")
        say("RESULT (four receivers): %d of 4 receivers found their WWV carrier." % nf)
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
    port it also does the Protocol 2 handshake and streams every switched-on receiver like the real radio:
    from its own port (port+11+n) back to the port the requests came from, noise plus carriers at the given
    absolute frequencies. It proves the program is consistent with itself, not with the real radio."""

    def __init__(self, busy=False, port=0, board=5, protocol=43, firmware=22, carrier_hz=10010200.0,
                 carrier_dbfs=-50.0, noise_dbfs=-95.0, carriers=None):
        self.busy, self.board, self.protocol, self.firmware = busy, board, protocol, firmware
        self.carriers = list(carriers) if carriers else [(carrier_hz, carrier_dbfs)]
        self.noise_dbfs = noise_dbfs
        self.requests = 0
        self.run = False
        self.freq = {}                                  # ddc number -> Hz
        self.rate = {}                                  # ddc number -> kHz
        self.mask = 0
        self.client = None
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
            s.settimeout(0.01)
            self.socks[k] = s
        self.port = self.socks["gen"].getsockname()[1]
        self.outs = {}
        if port:
            for n in range(8):
                o = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                o.bind(("127.0.0.1", port + 11 + n))
                self.outs[n] = o
        self._stop = threading.Event()
        self.th = threading.Thread(target=self._loop, daemon=True)
        self.th.start()

    @property
    def ddc_on(self):
        return bool(self.mask)

    def _handle(self, kind, data, addr):
        if kind == "gen":
            if len(data) >= 5 and data[4] == 2:
                self.requests += 1
                r = bytearray(60)
                r[4] = 3 if self.busy else 2
                r[5:11] = bytes([0x68, 0x27, 0x19, 0x96, 0x8E, 0x44])
                r[11], r[12], r[13] = self.board, self.protocol, self.firmware
                self.socks["gen"].sendto(bytes(r), addr)
            elif len(data) == 60 and data[4] == 0:
                self.phase = bool(data[37] & 0x08)
        elif kind == "ddc" and len(data) == PKT:
            self.mask = data[7]
            for n in range(8):
                self.rate[n] = struct.unpack(">H", data[18 + 6 * n:20 + 6 * n])[0] or 192
        elif kind == "hp" and len(data) == PKT:
            self.run = bool(data[4] & 1)
            self.client = addr                          # like the real radio: answers go back to the sender's port
            if data[4] & 2:
                self.ptt_seen = True
            if data[345] or any(data[329:345]):
                self.max_hp_byte_nonzero = True         # drive level / TX frequency must stay zero
            for n in range(8):
                w = struct.unpack(">I", data[5 + 4 * n:9 + 4 * n])[0]
                self.freq[n] = w / 4294967296.0 * ADC_CLOCK if self.phase else float(w)

    def _loop(self):
        import numpy as np
        rng = np.random.default_rng(1)
        n = 238
        t = [0] * 8
        seq = [0] * 8
        nxt = time.time()
        while not self._stop.is_set():
            for k, s in self.socks.items():
                try:
                    d, a = s.recvfrom(4096)
                except socket.timeout:
                    continue
                except OSError:
                    return
                self._handle(k, d, a)
            if self.run and self.mask and self.client and self.outs:
                now = time.time()
                rate = (self.rate.get(2) or 192)
                step = n / (rate * 1000.0)
                while nxt <= now:
                    for ddc in range(8):
                        if not self.mask & (1 << ddc):
                            continue
                        fs = (self.rate.get(ddc) or 192) * 1000.0
                        idx = np.arange(t[ddc], t[ddc] + n)
                        amp_n = 10 ** (self.noise_dbfs / 20.0) / np.sqrt(2)
                        x = amp_n * (rng.standard_normal(n) + 1j * rng.standard_normal(n))
                        for chz, cdb in self.carriers:
                            off = chz - self.freq.get(ddc, 0.0)
                            if abs(off) < fs / 2:
                                x = x + 10 ** (cdb / 20.0) * np.exp(2j * np.pi * off * idx / fs)
                        qi = np.clip(np.round(np.real(x) * (1 << 23)), -(1 << 23), (1 << 23) - 1).astype(np.int64) & 0xFFFFFF
                        qq = np.clip(np.round(np.imag(x) * (1 << 23)), -(1 << 23), (1 << 23) - 1).astype(np.int64) & 0xFFFFFF
                        arr = np.empty((n, 6), dtype=np.uint8)
                        for j, v in enumerate((qq, qi)):          # the real radio sends the pair this way round
                            arr[:, 3 * j] = (v >> 16) & 255
                            arr[:, 3 * j + 1] = (v >> 8) & 255
                            arr[:, 3 * j + 2] = v & 255
                        pkt = struct.pack(">IQHH", seq[ddc], 0, 24, n) + arr.tobytes()
                        try:
                            self.outs[ddc].sendto(pkt, self.client)
                        except OSError:
                            pass
                        seq[ddc] += 1
                        t[ddc] += n
                    nxt += step
            else:
                nxt = time.time()
                time.sleep(0.003)

    def close(self):
        self._stop.set()
        self.th.join(timeout=1.0)
        for s in list(self.socks.values()) + list(self.outs.values()):
            s.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
