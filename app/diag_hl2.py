"""
Hermes Lite 2 test: is the radio found, does it stream cleanly, and do all four receivers agree?

  1. Finds the radio (the address saved on the control panel, or a search of the network).
  2. Starts four receivers at once and checks that samples arrive without gaps.
  3. Shows the level on each of your frequencies, all measured at the same instant.
  4. Checks the spectrum is not mirrored (two receivers set 20 kHz apart must see the same signals shifted
     the right way). If it is mirrored, tells you.
  5. Checks the gain control works (changing it should change the level by the same amount).
  6. Watches for overload.

Run it with HL2_Test.bat (Windows) or:  python3 diag_hl2.py [--ip 192.168.1.50] [--report file]
Nothing is changed on your computer. Send the report (hl2_test_report.txt) to Claude.
"""
import argparse
import copy
import json
import math
import os
import sys
import time

import numpy as np

import rfmap_common as C
import rf_logger as RL
import hl2


def band_db(x, rate, bw=5000.0):
    n = 4096
    w = np.hanning(n).astype(np.float32)
    nseg = len(x) // n
    sp = np.abs(np.fft.fftshift(np.fft.fft(x[: nseg * n].reshape(nseg, n) * w, axis=1), axes=1)) ** 2
    sp = sp.mean(axis=0) / (n * float(np.sum(w ** 2)))
    half = max(int(round(bw / (rate / n) / 2)), 1)
    return 10 * math.log10(float(sp[n // 2 - half: n // 2 + half + 1].sum()) + 1e-20), sp


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="")
    ap.add_argument("--port", type=int, default=hl2.PORT, help=argparse.SUPPRESS)
    ap.add_argument("--rate", type=int, default=0)
    ap.add_argument("--report", default="")
    args = ap.parse_args(argv)
    out = []

    def say(t=""):
        print(t)
        out.append(t)

    say("RF Noise Map - Hermes Lite 2 test")
    say("=" * 60)
    import rfmap_log as L
    L.setup("hl2test")
    cfg = {}
    try:
        with open(os.path.join(C.data_dir(), "Settings", "config.json")) as f:
            cfg = json.load(f)
    except Exception:
        pass
    ip = args.ip or cfg.get("hl2_ip", "")
    rate = args.rate or int(cfg.get("hl2_rate", 96000))
    gain = int(cfg.get("hl2_gain_db", 15))
    chans = [c for c in cfg.get("channels", []) if str(c.get("mhz", "")).strip() != "" and float(c["mhz"]) <= 38][:4]
    if not chans:
        chans = [{"mhz": 3.7}, {"mhz": 7.3}, {"mhz": 14.2}, {"mhz": 10.1}]
    ok = True
    try:
        say("Step 1: looking for the radio%s (about 3 seconds)..." % ((" at " + ip) if ip else " on the network"))
        found = hl2.discover(ip or None, timeout=3.0, port=args.port)
        if not found:
            say("  NOT FOUND. Check: the network cable is plugged in, the radio is on (wait 20 seconds after power),")
            say("  Thetis / SDR Console / other programs are closed, and the address is right.")
            say("  Tip: on the control panel press 'Find my radio', or type the address you see in your router.")
            return 1
        d = found[0]
        say("  found %s at %s, gateware %s, %d receivers%s" % ("a Hermes Lite 2" if d["is_hl2"] else "an HPSDR radio (board %d)" % d["board"],
                                                         d["ip"], d["gateware"], d["nrx"], " - BUSY (another program is using it)" if d["busy"] else ""))
        if not d["is_hl2"]:
            say("  (This is not reported as a Hermes Lite 2. It may still work.)")
        nrx = max(1, min(4, d["nrx"]))
        cl = hl2.Hl2Client(d["ip"], d["port"], rate=rate, nrx=nrx)
        cl.lna_db = gain
        for i in range(nrx):
            cl.freq[i] = int(float(chans[i % len(chans)]["mhz"]) * 1e6)
        say("Step 2: starting %d receivers at %d kHz each..." % (nrx, rate // 1000))
        try:
            cl.start()
        except hl2.Hl2Error as e:
            say("  FAILED: " + str(e))
            return 1
        time.sleep(1.0)
        p0, l0 = cl.packets, cl.lost
        time.sleep(3.0)
        pk, lost = cl.packets - p0, cl.lost - l0
        say("  %d packets in 3 s (%.0f per second), %d lost" % (pk, pk / 3.0, lost))
        if pk == 0:
            say("  PROBLEM: no data is arriving."); ok = False
        elif lost > 0.01 * pk:
            say("  PROBLEM: the network is dropping packets. Use a direct cable (no Wi-Fi, no busy switch), or a lower detail setting."); ok = False
        else:
            say("  data flow is clean")

        say("Step 3: the level on each frequency, all measured at the same instant:")
        say("  %-10s %-12s %-14s" % ("slice", "MHz", "level (dBFS)"))
        nseg = max(1, int(round(0.064 * rate / 4096)))
        for i in range(nrx):
            x, _t = cl.take(i, nseg * 4096)
            lv, _sp = band_db(x, rate)
            say("  %-10s %-12g %-14.1f" % ("slice %d" % (i + 1), cl.freq[i] / 1e6, lv))
        say("  (readings are in dB relative to the radio's full scale, including the radio gain of %d dB)" % gain)

        say("Step 4: is the picture mirrored? (two receivers 20 kHz apart should see the same signals shifted)")
        if nrx >= 2:
            f0 = 7_100_000
            cl.set_freq(0, f0)
            cl.set_freq(1, f0 + 20000)
            time.sleep(0.4)
            xa, _ = cl.take(0, 8 * 4096)
            xb, _ = cl.take(1, 8 * 4096)
            _, sa = band_db(xa, rate)
            _, sb = band_db(xb, rate)
            la, lb = 10 * np.log10(sa + 1e-20), 10 * np.log10(sb + 1e-20)
            shift = int(round(20000 / (rate / 4096)))
            # compare A shifted by -shift (normal) and +shift (mirrored) against B
            def corr(k):
                if k >= 0:
                    u, v = la[k:], lb[:4096 - k]
                else:
                    u, v = la[:4096 + k], lb[-k:]
                u = u - u.mean(); v = v - v.mean()
                return float((u * v).sum() / (math.sqrt((u * u).sum() * (v * v).sum()) + 1e-12))
            normal, mirror = corr(shift), corr(-shift)
            say("  agreement if normal: %.2f   if mirrored: %.2f" % (normal, mirror))
            if max(normal, mirror) < 0.15:
                say("  Not enough signal here to tell (try with the antenna connected to a real antenna).")
            elif normal >= mirror:
                say("  OK: the picture is the right way round.")
            else:
                say("  MIRRORED: the picture is left-right reversed. Tell Claude: hl2.py Q_SIGN needs to be flipped.")
                ok = False
        else:
            say("  skipped (the radio has only one receiver)")

        say("Step 5: does the gain control work?")
        cl.set_freq(0, int(float(chans[0]["mhz"]) * 1e6)); time.sleep(0.3)
        x, _ = cl.take(0, nseg * 4096); a, _ = band_db(x, rate, bw=rate * 0.8)
        cl.set_gain(gain - 10); time.sleep(0.6)
        x, _ = cl.take(0, nseg * 4096); b, _ = band_db(x, rate, bw=rate * 0.8)
        cl.set_gain(gain)
        say("  lowering the gain by 10 dB changed the level by %.1f dB (expected about -10)" % (b - a))
        if not (-13 < (b - a) < -7):
            say("  PROBLEM: the gain control did not change the level as expected."); ok = False

        say("Step 6: overload check (10 seconds)...")
        cl.overload = False
        t_end = time.time() + 10
        while time.time() < t_end:
            time.sleep(0.2)
        if cl.overload:
            say("  OVERLOAD seen: a strong signal is overloading the radio. Lower the radio gain, or add an attenuator.")
        else:
            say("  no overload")
        cl.stop()
    except Exception as e:
        say("The test stopped: %s: %s" % (type(e).__name__, e))
        L.exception("hl2 test")
        ok = False
    say("")
    say("Result: " + ("everything looks good." if ok else "there are problems, see above."))
    say("Please send this report (hl2_test_report.txt) to Claude.")
    if args.report:
        try:
            with open(args.report, "w", encoding="utf-8") as f:
                f.write("\n".join(out) + "\n")
        except OSError:
            pass
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
