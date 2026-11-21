"""
cat_sim.py - a pretend CAT radio on a pseudo serial port, for testing cat_engine without a real radio.
(Linux / Mac only: it uses a pseudo-terminal.)  It answers the same commands a real radio would.
"""
import os
import pty
import threading
import time

import cat_engine as E


class FakeRig(threading.Thread):
    def __init__(self, model_id, freq_hz=7100000, raw=60, echo=False, hear=None):
        super().__init__(daemon=True)
        self.model = E.model_by_id(model_id)
        self.freq = int(freq_hz)
        self.raw = raw
        self.echo = echo                                   # Icom radios echo the command on a CI-V bus
        self.hear = hear                                   # optional function(freq_hz) -> meter number
        self.master, slave = pty.openpty()
        self.port = os.ttyname(slave)
        self._slave = slave
        self.log = []
        self.alive = True
        self.noise_first = False                           # send an unrelated message before answering (like AI on)

    def meter(self):
        return int(self.hear(self.freq)) if self.hear else int(self.raw)

    def run(self):
        buf = b""
        while self.alive:
            try:
                d = os.read(self.master, 256)
            except OSError:
                break
            if not d:
                time.sleep(0.01)
                continue
            buf += d
            if self.model["dialect"] == "icom_civ":
                while b"\xfd" in buf:
                    fr, buf = buf.split(b"\xfd", 1)
                    self._icom(fr + b"\xfd")
            else:
                while b";" in buf:
                    cmd, buf = buf.split(b";", 1)
                    self._text(cmd.decode("ascii", "ignore") + ";")

    def _send(self, b):
        os.write(self.master, b)

    def _icom(self, frame):
        self.log.append(frame)
        if not frame.startswith(b"\xfe\xfe"):
            return
        to, frm, body = frame[2], frame[3], frame[4:-1]
        addr = int(self.model["civ_addr"], 16)
        if to != addr:
            return
        if self.echo:
            self._send(frame)
        head = b"\xfe\xfe" + bytes([frm, addr])
        cmd = body[0]
        if cmd == 0x03:
            self._send(head + b"\x03" + E.hz_to_bcd(self.freq) + b"\xfd")
        elif cmd == 0x05:
            self.freq = E.bcd_to_hz(body[1:6])
            self._send(head + b"\xfb\xfd")
        elif cmd == 0x15 and body[1:2] == b"\x02":
            v = self.meter()
            self._send(head + b"\x15\x02" + bytes([(v // 1000) << 4 | (v // 100 % 10), (v // 10 % 10) << 4 | (v % 10)]) + b"\xfd")
        else:
            self._send(head + b"\xfa\xfd")

    def _text(self, cmd):
        self.log.append(cmd)
        if self.noise_first:
            self._send(b"IF00007100000;")
        d = self.model.get("freq_digits", 11)
        if cmd == "FA;":
            self._send(("FA%0*d;" % (d, self.freq)).encode())
        elif cmd.startswith("FA") and len(cmd) > 3:
            self.freq = int(cmd[2:-1])
        elif cmd == self.model.get("meter_cmd"):
            pre = self.model.get("meter_prefix", "SM0")
            width = 3 if self.model["maker"] == "Yaesu" else 4
            if pre == "SMH":
                width = 3
            self._send(("%s%0*d;" % (pre, width, self.meter())).encode())
        else:
            self._send(b"?;")

    def stop(self):
        self.alive = False
        try:
            os.close(self.master)
        except OSError:
            pass


class FakeFlex(threading.Thread):
    """A pretend Flex: TCP command port plus UDP meter packets. Used only by the tests."""

    def __init__(self, freq_mhz=7.1, dbm=-95.0, slices=1, refuse_create=False, need_pan=False, auto_pan=False, no_pan_slice=False, gui_pan=False, max_slices=None, owners=None, other_clients=()):
        import socket
        threading.Thread.__init__(self, daemon=True)
        self.srv = socket.socket(); self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("127.0.0.1", 0)); self.srv.listen(2); self.srv.settimeout(0.3)
        self.port = self.srv.getsockname()[1]
        self.slices = {i: freq_mhz for i in range(slices)}
        self.dbm = dbm
        self.udp_port = None
        self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.running = True
        self.log = []
        self.refuse_create = refuse_create
        self.need_pan = need_pan
        self.auto_pan = auto_pan       # like a real radio: 'slice create' makes its own panadapter and names it in the slice news
        self.slice_pan = {}
        self.gui_pan = gui_pan           # real Flex (probe 2026-11-19): 'display panafall create' is refused (50001000) until 'client gui'; reply is 'pan,waterfall'
        self.is_gui = False
        self.no_pan_slice = no_pan_slice   # a real Flex (2026-11-19): 'slice create' with no pan= gives pan=0x00000000, and 'display pan set' on it is refused
        self.pan_sub = False
        self.streams = []                   # DAX audio streams the program asked for: stream ids
        self.refuse_stream = False
        self.tone_hz = 1000.0
        self._ph = 0
        self.max_slices = max_slices        # a real 6700 has 8; 'slice create' beyond that is refused 50000003
        self.owners = dict(owners or {})    # slice index -> client handle that owns it (default: whoever created it = us, 12345678)
        self.other_clients = list(other_clients)   # handles of OTHER programs that are connected (SmartSDR on another computer, say)
        self.pans = []
        self.pan_par = {}
        self.fft_frame = 0
        self.conn = None

    def _send(self, s):
        try:
            self.conn.sendall((s + "\n").encode())
        except Exception:
            pass

    def _slice_status(self, i):
        self._send("S12345678|slice %d RF_frequency=%.6f mode=AM active=1 in_use=1 client_handle=0x%s%s" % (i, self.slices[i], self.owners.get(i, "12345678"), (" pan=" + self.slice_pan[i]) if i in self.slice_pan else ""))

    def _udp_loop(self):
        import struct, time
        while self.running:
            time.sleep(0.05)
            if self.udp_port and self.slices:
                body = b"".join(struct.pack(">Hh", 100 + i, int(round(self.dbm * 128))) for i in self.slices)
                pkt = struct.pack(">IIIIIII", 0x38000000, 0x700, 0x534C, 0x8002, 0, 0, 0) + body
                try:
                    self.udp.sendto(pkt, ("127.0.0.1", self.udp_port))
                    for pid, par in list(self.pan_par.items()):
                        if "min_dbm" in par and "ypixels" in par:
                            n = int(par.get("xpixels", 1024)); self.fft_frame += 1
                            dbm = [-125.0] * n
                            for k in range(n // 2 - 3, n // 2 + 4):
                                dbm[k] = -70.0
                            y = float(par["ypixels"]); mn = float(par["min_dbm"]); mx = float(par["max_dbm"])
                            vals = [int(round((mx - v) / (mx - mn) * y)) for v in dbm]
                            for st in range(0, n, n // 2):
                                part = vals[st:st + n // 2]
                                hdr = struct.pack(">IIIIIII", 0x38000000, int(pid, 16), 0x534C, 0x8003, 0, 0, 0)
                                self.udp.sendto(hdr + struct.pack(">HHHHI", st, len(part), 2, n, self.fft_frame) + struct.pack(">%dH" % len(part), *part), ("127.0.0.1", self.udp_port))
                except Exception:
                    pass
                try:
                    import math
                    for sid in list(self.streams):          # DAX audio: float32 stereo, 24 kHz, a steady tone
                        for _pk in range(9):                  # 9 x 128 samples every 50 ms = 24,000 samples a second
                            n = 128
                            vals = [math.sin(2 * math.pi * self.tone_hz * (self._ph + k) / 24000.0) * 0.5 for k in range(n)]
                            self._ph += n
                            hdr = struct.pack(">IIIIIII", 0x38000000, sid, 0x534C, 0x03E3, 0, 0, 0)
                            self.udp.sendto(hdr + b"".join(struct.pack(">ff", v, v) for v in vals), ("127.0.0.1", self.udp_port))
                except Exception:
                    pass

    def run(self):
        import socket
        threading.Thread(target=self._udp_loop, daemon=True).start()
        while self.running:
            try:
                self.conn, _ = self.srv.accept()
            except socket.timeout:
                continue
            self.conn.settimeout(0.3)
            self._send("V1.4.0.0"); self._send("H12345678")
            buf = b""
            while self.running:
                try:
                    d = self.conn.recv(4096)
                    if not d:
                        break
                except socket.timeout:
                    continue
                except OSError:
                    break
                buf += d
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    self._cmd(line.decode().strip())

    def _cmd(self, line):
        self.log.append(line)
        seq, _, c = line[1:].partition("|")
        ok = lambda msg="": self._send("R%s|0|%s" % (seq, msg))
        if c.startswith("client udpport"):
            self.udp_port = int(c.split()[-1]); ok()
        elif c == "sub slice all":
            ok()
            for i in self.slices:
                self._slice_status(i)
        elif c.startswith("stream create"):
            if self.refuse_stream:
                self._send("R%s|50000016|" % seq); return
            sid = 0x20000000 + len(self.streams) + 1; self.streams.append(sid); ok("0x%08X" % sid)
        elif c.startswith("stream remove"):
            try: self.streams.remove(int(c.split()[-1], 16))
            except Exception: pass
            ok()
        elif c == "sub client all":
            ok()
            for h in ["12345678"] + self.other_clients:
                self._send("S%s|client 0x%s connected client_id=X program=Test station=Test local_ptt=0" % (h, h))
        elif c == "sub pan all":
            self.pan_sub = True; ok()
        elif c == "sub meter all":
            ok()
            self._send("S12345678|meter " + "#".join("%d.src=SLC#%d.num=%d#%d.nam=LEVEL#%d.unit=dBm" % (100 + i, 100 + i, i, 100 + i, 100 + i) for i in self.slices)
                       + "#999.src=TX-#999.num=1#999.nam=FWDPWR#999.unit=dBm")
        elif c.startswith("slice tune"):
            _, _, i, f = c.split()
            if int(i) in self.slices:
                self.slices[int(i)] = float(f); ok(); self._slice_status(int(i))
            else:
                self._send("R%s|50000001|bad slice" % seq)
        elif c == "client gui":
            self.is_gui = True; ok("125803C8-3372-4571-A84D-CAEA265FF117")
        elif c.startswith("display panafall create"):
            if self.gui_pan and not self.is_gui:
                self._send("R%s|50001000|" % seq); return
            pid = "0x4000000%d" % len(self.pans); self.pans.append(pid)
            if self.gui_pan:
                ok("%s,0x4200000%d" % (pid, len(self.pans)))
            else:
                ok("pan=%s waterfall=0x4200000%d" % (pid, len(self.pans)))
            self._send("S12345678|display pan %s x_pixels=800" % pid)
        elif c.startswith("display pan set"):
            parts = c.split()
            if int(parts[3], 16) == 0:
                self._send("R%s|50000029|invalid panadapter" % seq); return
            par = self.pan_par.setdefault(parts[3], {})
            for tok in parts[4:]:
                if "=" in tok:
                    k, v = tok.split("=", 1); par[k] = v
            ok()
        elif c.startswith("display panafall remove"):
            pid = c.split()[-1]
            if pid in self.pans: self.pans.remove(pid)
            self.pan_par.pop(pid, None)
            ok()
        elif c.startswith("slice create"):
            if self.max_slices is not None and len(self.slices) >= self.max_slices:
                self._send("R%s|50000003|" % seq)
            elif self.refuse_create or (self.need_pan and "pan=" not in c):
                self._send("R%s|50000016|no panadapter" % seq)
            else:
                i = max(self.slices, default=-1) + 1
                self.slices[i] = 7.1
                if self.no_pan_slice and "pan=" not in c:
                    self.slice_pan[i] = "0x00000000"
                elif "pan=" in c:
                    self.slice_pan[i] = c.split("pan=")[1].split()[0]
                if self.auto_pan and "pan=" not in c:
                    pid = "0x4000000%d" % len(self.pans); self.pans.append(pid); self.slice_pan[i] = pid
                    if self.pan_sub:                               # a real radio only sends panadapter news to a client that asked for it
                        self._send("S12345678|display pan %s x_pixels=800" % pid)
                ok(str(i)); self._slice_status(i)
                self._send("S12345678|meter %d.src=SLC#%d.num=%d#%d.nam=LEVEL#%d.unit=dBm" % (100 + i, 100 + i, i, 100 + i, 100 + i))
        elif c.startswith("slice remove"):
            i = int(c.split()[-1]); self.slices.pop(i, None); self.owners.pop(i, None)
            ok(); self._send("S12345678|slice %d in_use=0" % i)
        else:
            ok()

    def stop(self):
        self.running = False
        try:
            self.srv.close(); self.udp.close()
        except Exception:
            pass
