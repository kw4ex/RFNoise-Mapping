"""
hl2.py - talk to a Hermes Lite 2 (HL2) radio over the network, using only Python's standard library
(plus numpy, which the program already needs).

The HL2 speaks "openHPSDR Protocol 1": small UDP packets to port 1024 on the radio.
  * Find it:   send a 63-byte "discovery" packet; the radio answers with its address and model.
  * Start it:  send a 64-byte "start" packet.
  * Command it: every packet we send carries two 5-byte commands (set frequency, sample rate, gain...).
  * Listen:    the radio sends 1032-byte packets, each holding two blocks of I/Q samples.
               With N receivers on, every sample group holds N pairs of 24-bit numbers.

Why this radio is good for noise mapping: it has several receivers that run AT THE SAME TIME, each tuned
to its own frequency, so nothing has to be retuned between readings.

This file also contains Hl2Sim, a pretend HL2 used for testing without hardware.
"""

import socket
import struct
import threading
import time

import numpy as np

PORT = 1024
RATES = {48000: 0, 96000: 1, 192000: 2, 384000: 3}
RING = 1 << 18                      # samples remembered per receiver (about 0.7 s at 384 kHz)
MAX_RX = 12                         # the protocol allows up to 12; most radios have fewer (4 is common)
LNA_MIN_DB, LNA_MAX_DB = -12, 48    # HL2 low-noise-amplifier range in direct mode
# The HL2 gateware reports Q with the opposite sign, which would mirror the spectrum. Undo it here.
# (Checked by the HL2 test, which compares two receivers; change this if a real radio proves otherwise.)
Q_SIGN = -1.0


class Hl2Error(Exception):
    pass


# ----------------------------------------------------------------------------
# Finding the radio
# ----------------------------------------------------------------------------
def _local_broadcasts():
    """Broadcast addresses to try. Some computers refuse the all-networks one, so guess a few more."""
    out = ["255.255.255.255", "169.254.255.255"]
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if ip.startswith("127."):
                continue
            a = ip.split(".")
            out.append(".".join(a[:3] + ["255"]))
    except OSError:
        pass
    return list(dict.fromkeys(out))


def parse_discovery(data, addr):
    if len(data) < 11 or data[0] != 0xEF or data[1] != 0xFE or data[2] not in (2, 3):
        return None
    mac = ":".join("%02X" % b for b in data[3:9])
    board = data[10]
    nrx = data[19] if len(data) > 19 and 0 < data[19] <= MAX_RX else 4
    return {"ip": addr[0], "port": addr[1], "mac": mac, "gateware": "%d.%d" % (data[9], data[21] if len(data) > 21 else 0),
            "board": board, "is_hl2": board == 0x06, "nrx": nrx, "busy": data[2] == 3}


def discover(ip=None, timeout=2.0, port=PORT):
    """Look for HPSDR radios. With ip given, ask just that address (works even where broadcasts are blocked).
    Returns a list of dicts: ip, mac, gateware, board, is_hl2, nrx, busy."""
    pkt = bytes([0xEF, 0xFE, 0x02]) + bytes(60)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    found = {}
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.settimeout(0.2)
        targets = [ip] if ip else _local_broadcasts()
        t_end = time.time() + timeout
        last_send = 0.0
        while time.time() < t_end:
            if time.time() - last_send > 0.5:          # ask again a few times, in case a packet was lost
                for t in targets:
                    try:
                        s.sendto(pkt, (t, port))
                    except OSError:
                        pass
                last_send = time.time()
            try:
                data, addr = s.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            d = parse_discovery(data, addr)
            if d:
                found[d["ip"]] = d
                if ip:
                    break
    finally:
        s.close()
    return list(found.values())


# ----------------------------------------------------------------------------
# The radio connection
# ----------------------------------------------------------------------------
class Hl2Client:
    """Runs the radio: sends commands, collects samples into one ring buffer per receiver."""

    def __init__(self, ip, port=PORT, rate=96000, nrx=4):
        if rate not in RATES:
            raise Hl2Error("Sample rate must be one of 48000, 96000, 192000 or 384000.")
        self.ip, self.port = ip, int(port)
        self.rate = rate
        self.nrx = max(1, min(MAX_RX, int(nrx)))
        self.freq = [7_000_000] * self.nrx
        self.lna_db = 15
        self.sock = None
        self.lock = threading.Lock()
        self.ring = [np.zeros(RING, np.complex64) for _ in range(self.nrx)]
        self.count = [0] * self.nrx                  # total samples written per receiver
        self.t_last = [0.0] * self.nrx               # when the newest samples arrived
        self.packets = 0
        self.lost = 0                                # packets missed (network drops)
        self.overload = False                        # the radio's ADC clipped recently
        self._seq_in = None
        self._seq_out = 0
        self._stop = threading.Event()
        self._rx_thread = self._tx_thread = None
        self._urgent = []                            # command frames to send right away
        self._rr = 0                                 # round-robin position for refreshing commands
        self.retune_t = [0.0] * self.nrx

    # ---- commands -------------------------------------------------------
    def _frames(self):
        """All the commands the radio needs to keep hearing, as (C0, C1, C2, C3, C4)."""
        fr = [(0x00, RATES[self.rate], 0, 0, ((self.nrx - 1) << 3) | 0x04)]          # rate, receivers, duplex
        for i in range(self.nrx):
            c0 = 0x04 + 2 * i if i < 7 else 0x24 + 2 * (i - 7)
            fr.append((c0,) + tuple(struct.pack(">I", int(self.freq[i]))))
        fr.append((0x02,) + tuple(struct.pack(">I", int(self.freq[0]))))              # transmit frequency (unused)
        g = int(round(max(LNA_MIN_DB, min(LNA_MAX_DB, self.lna_db)))) + 12
        fr.append((0x14, 0, 0, 0, 0x40 | g))                                        # low-noise-amplifier gain
        return fr

    def _packet(self, frames):
        self._seq_out = (self._seq_out + 1) & 0xFFFFFFFF
        out = bytearray(b"\xEF\xFE\x01\x02" + struct.pack(">I", self._seq_out))
        for f in frames:
            out += b"\x7F\x7F\x7F" + bytes(f) + bytes(504)
        return bytes(out)

    def _tx_loop(self):
        t_next = time.time()
        while not self._stop.is_set():
            with self.lock:
                allf = self._frames()
                if self._urgent:
                    pair = [self._urgent.pop(0), self._urgent.pop(0) if self._urgent else allf[self._rr % len(allf)]]
                else:
                    pair = [allf[self._rr % len(allf)], allf[(self._rr + 1) % len(allf)]]
                    self._rr = (self._rr + 2) % len(allf)
            try:
                self.sock.sendto(self._packet(pair), (self.ip, self.port))
            except OSError:
                pass
            t_next += 0.008                                  # about 125 packets a second keeps the radio awake
            time.sleep(max(0.0, t_next - time.time()))

    # ---- receiving ------------------------------------------------------
    def _rx_loop(self):
        s = self.sock
        n = self.nrx
        grp = 6 * n + 2
        per = 504 // grp
        while not self._stop.is_set():
            try:
                data, _a = s.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            if len(data) != 1032 or data[0] != 0xEF or data[1] != 0xFE or data[2] != 1 or data[3] != 6:
                continue
            seq = struct.unpack(">I", data[4:8])[0]
            if self._seq_in is not None and seq != ((self._seq_in + 1) & 0xFFFFFFFF):
                self.lost += (seq - self._seq_in - 1) & 0xFFFFFFFF
            self._seq_in = seq
            now = time.time()
            self.packets += 1
            for off in (8, 520):
                if data[off:off + 3] != b"\x7F\x7F\x7F":
                    continue
                c0 = data[off + 3]
                if (c0 & 0xF8) == 0 and (data[off + 4] & 1):
                    self.overload = True
                payload = np.frombuffer(data, np.uint8, count=per * grp, offset=off + 8).reshape(per, grp)
                for r in range(n):
                    iq = payload[:, 6 * r: 6 * r + 6].astype(np.int32)
                    iv = (iq[:, 0] << 16) | (iq[:, 1] << 8) | iq[:, 2]
                    qv = (iq[:, 3] << 16) | (iq[:, 4] << 8) | iq[:, 5]
                    iv = iv - ((iv & 0x800000) << 1)
                    qv = qv - ((qv & 0x800000) << 1)
                    z = (iv + 1j * Q_SIGN * qv).astype(np.complex64) * np.float32(1.0 / 8388608.0)
                    c = self.count[r]
                    pos = c % RING
                    k = len(z)
                    if pos + k <= RING:
                        self.ring[r][pos:pos + k] = z
                    else:
                        h = RING - pos
                        self.ring[r][pos:] = z[:h]
                        self.ring[r][:k - h] = z[h:]
                    self.count[r] = c + k
                    self.t_last[r] = now

    # ---- life cycle -----------------------------------------------------
    def start(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
        self.sock.bind(("", 0))
        self.sock.settimeout(0.25)
        self._stop.clear()
        self.sock.sendto(self._packet(self._frames()[:2]), (self.ip, self.port))     # tell it what we want first
        self.sock.sendto(bytes([0xEF, 0xFE, 0x04, 0x01]) + bytes(60), (self.ip, self.port))
        self._tx_thread = threading.Thread(target=self._tx_loop, daemon=True)
        self._rx_thread = threading.Thread(target=self._rx_loop, daemon=True)
        self._tx_thread.start()
        self._rx_thread.start()
        t0 = time.time()
        while time.time() - t0 < 3.0:                                               # wait for samples to flow
            if all(c > 0 for c in self.count):
                return
            time.sleep(0.02)
        self.stop()
        raise Hl2Error("The radio did not send any samples. Check the network cable, the power, and that "
                       "no other program (Thetis, SDR Console...) is using the radio.")

    def stop(self):
        self._stop.set()
        try:
            if self.sock:
                self.sock.sendto(bytes([0xEF, 0xFE, 0x04, 0x00]) + bytes(60), (self.ip, self.port))
        except OSError:
            pass
        for t in (self._rx_thread, self._tx_thread):
            if t:
                t.join(timeout=1.0)
        try:
            if self.sock:
                self.sock.close()
        except OSError:
            pass
        self.sock = None

    # ---- settings -------------------------------------------------------
    def set_freq(self, rx, hz):
        hz = int(round(hz))
        with self.lock:
            if self.freq[rx] == hz:
                return False
            self.freq[rx] = hz
            c0 = 0x04 + 2 * rx if rx < 7 else 0x24 + 2 * (rx - 7)
            fr = (c0,) + tuple(struct.pack(">I", hz))
            self._urgent += [fr, fr]
            self.retune_t[rx] = time.time()
        return True

    def set_gain(self, lna_db):
        with self.lock:
            self.lna_db = lna_db
            g = int(round(max(LNA_MIN_DB, min(LNA_MAX_DB, lna_db)))) + 12
            self._urgent += [(0x14, 0, 0, 0, 0x40 | g)] * 2

    # ---- reading samples ------------------------------------------------
    SETTLE_S = 0.05                  # after a retune, ignore this long (old-frequency samples still in the pipeline)

    def take(self, rx, n, timeout=1.0):
        """The newest n samples of receiver rx, and the time (seconds since 1970) of their middle.
        Straight after a retune, only samples that arrived after the settling time are used."""
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
            raise Hl2Error("Not enough samples arrived from the radio.")
        c = self.count[rx]
        tl = self.t_last[rx]
        idx = (np.arange(c - n, c)) % RING
        x = self.ring[rx][idx].copy()
        if self.count[rx] - c > RING - n:                  # overwritten while copying (very unlikely)
            raise Hl2Error("Samples were lost while reading.")
        return x, tl - 0.5 * n / self.rate


# ----------------------------------------------------------------------------
# A pretend HL2, for testing without hardware
# ----------------------------------------------------------------------------
class Hl2Sim:
    """Behaves like an HL2 on 127.0.0.1. `carriers` is {absolute_hz: level_dbfs}, `noise_db` the noise floor."""

    def __init__(self, carriers=None, noise_db=-105.0, nrx=4, port=0, q_bug=True):
        self.carriers = dict(carriers or {})
        self.noise_db = noise_db
        self.nrx = nrx
        self.q_bug = q_bug
        self.rate = 48000
        self.n_active = 1
        self.freq = [0] * MAX_RX
        self.lna = 0
        self.running = False
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", port))
        self.sock.settimeout(0.05)
        self.port = self.sock.getsockname()[1]
        self.client = None
        self._stop = threading.Event()
        self.last_host_pkt = 0.0
        self.cmd_count = 0
        self.th = threading.Thread(target=self._loop, daemon=True)
        self.th.start()

    def close(self):
        self._stop.set()
        self.th.join(timeout=1.0)
        self.sock.close()

    def _discovery_reply(self):
        r = bytearray(60)
        r[0:2] = b"\xEF\xFE"
        r[2] = 3 if self.running else 2
        r[3:9] = bytes([0x00, 0x1C, 0xC0, 0xA2, 0x13, 0x37])
        r[9] = 72
        r[10] = 0x06
        r[19] = self.nrx
        r[21] = 4
        return bytes(r)

    def _handle(self, data, addr):
        if len(data) >= 3 and data[0] == 0xEF and data[1] == 0xFE:
            if data[2] == 2:
                self.sock.sendto(self._discovery_reply(), addr)
            elif data[2] == 4:
                self.running = bool(data[3] & 1)
                self.client = addr if self.running else None
                self.t0 = time.time()
                self.sent = 0
            elif data[2] == 1 and len(data) == 1032:
                self.last_host_pkt = time.time()
                for off in (8, 520):
                    if data[off:off + 3] != b"\x7F\x7F\x7F":
                        continue
                    c0, c1, c2, c3, c4 = data[off + 3: off + 8]
                    a = c0 >> 1
                    self.cmd_count += 1
                    if a == 0:
                        self.rate = {0: 48000, 1: 96000, 2: 192000, 3: 384000}[c1 & 3]
                        self.n_active = min(self.nrx, ((c4 >> 3) & 0xF) + 1)
                    elif 2 <= a <= 8:
                        self.freq[a - 2] = struct.unpack(">I", bytes([c1, c2, c3, c4]))[0]
                    elif 0x12 <= a <= 0x16:
                        self.freq[7 + a - 0x12] = struct.unpack(">I", bytes([c1, c2, c3, c4]))[0]
                    elif a == 0x0A:
                        self.lna = (c4 & 0x3F) - 12

    def _make(self, n_samples, rx, start_index):
        """Pretend antenna signal seen by receiver rx: carriers plus noise, as complex numbers."""
        k = np.arange(start_index, start_index + n_samples)
        t = k / float(self.rate)
        x = np.zeros(n_samples, np.complex128)
        amp_gain = 10 ** (self.lna / 20.0)
        for f_abs, spec in self.carriers.items():
            # spec = level_db, or (level_db, am_tone_hz, am_depth) for an AM-modulated test carrier
            if isinstance(spec, (tuple, list)):
                db, am_hz, depth = spec
            else:
                db, am_hz, depth = spec, 0.0, 0.0
            df = f_abs - self.freq[rx]
            if abs(df) < self.rate * 0.45:
                env = 1.0 + depth * np.sin(2 * np.pi * am_hz * t) if am_hz else 1.0
                x += (10 ** (db / 20.0)) * env * np.exp(2j * np.pi * df * t)
        x *= amp_gain
        sig = 10 ** (self.noise_db / 20.0) * amp_gain / np.sqrt(2.0)
        x += sig * (np.random.randn(n_samples) + 1j * np.random.randn(n_samples))
        return x

    def _loop(self):
        idx = 0
        while not self._stop.is_set():
            try:
                data, addr = self.sock.recvfrom(2048)
                self._handle(data, addr)
            except socket.timeout:
                pass
            except OSError:
                return
            if not (self.running and self.client):
                idx = 0
                continue
            if self.last_host_pkt and time.time() - self.last_host_pkt > 3.0:
                self.running = False                           # watchdog: host went quiet
                continue
            n = self.n_active
            grp = 6 * n + 2
            per = 504 // grp
            due = int((time.time() - self.t0) * self.rate / (2 * per))
            m = min(due - self.sent, 200)
            if m <= 0:
                time.sleep(0.002)
                continue
            total = m * 2 * per
            planes = []
            for r in range(n):
                z = self._make(total, r, idx)
                iv = np.clip(np.round(z.real * 8388607), -8388608, 8388607).astype(np.int64) & 0xFFFFFF
                qraw = -z.imag if self.q_bug else z.imag
                qv = np.clip(np.round(qraw * 8388607), -8388608, 8388607).astype(np.int64) & 0xFFFFFF
                planes.append((iv, qv))
            idx += total
            for p in range(m):
                pkt = bytearray(b"\xEF\xFE\x01\x06" + struct.pack(">I", self.sent & 0xFFFFFFFF))
                for blk in range(2):
                    lo = (p * 2 + blk) * per
                    body = np.zeros((per, grp), np.uint8)
                    for r in range(n):
                        iv, qv = planes[r]
                        for j, v in ((0, iv[lo:lo + per]), (3, qv[lo:lo + per])):
                            body[:, 6 * r + j] = (v >> 16) & 255
                            body[:, 6 * r + j + 1] = (v >> 8) & 255
                            body[:, 6 * r + j + 2] = v & 255
                    pkt += b"\x7F\x7F\x7F" + bytes([0, 0, 0, 0, 0]) + body.tobytes() + bytes(504 - per * grp)
                self.sent += 1
                try:
                    self.sock.sendto(bytes(pkt), self.client)
                except OSError:
                    pass
