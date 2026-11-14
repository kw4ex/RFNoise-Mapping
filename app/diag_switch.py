"""
Switching test: does the radio give the right level straight after it changes frequency?

It needs the real SDRplay. It picks a STRONG and a QUIET frequency, measures each one carefully
(after waiting a full second, the "true" reading), then jumps between them the way the logger does
and shows how far the quick readings are from the true ones.

Run it with Switch_Test.bat (Windows) or:  python3 diag_switch.py
Nothing is changed on your computer; a report is saved as switch_test_report.txt.
"""
import argparse
import copy
import json
import math
import os
import sys
import time

import rfmap_common as C
import rf_logger as RL

CANDIDATES_MHZ = [3.7, 7.3, 14.2, 50.2, 88.5, 97.1, 100.1, 107.9, 118.0, 127.0, 146.52, 148.0]


def true_level(sdr, mhz, settings, wait_s=1.0):
    """Reading taken after the radio has had a full second on that frequency (keeps draining the queue)."""
    hz = mhz * 1e6
    sdr.DRAIN, sdr.SETTLE = True, 8192
    sdr.measure(hz, 5000.0, 0, 0, settings)
    t_end = time.time() + wait_s
    while time.time() < t_end:
        sdr._read(sdr.NSAMP)
    vals = [sdr.measure(hz, 5000.0, 0, 0, settings) for _ in range(3)]
    return sum(vals) / len(vals)


def profile(sdr, strong, quiet, settings, pause_s, drain, trials=6, nseg=16):
    """After jumping strong -> quiet, read 2 ms slices and show the level of each slice (dB). Returns list of rows."""
    import numpy as np
    n = sdr.FFT_N
    binw = sdr.SAMPLE_RATE / n
    offset = sdr.OFFSET_HZ
    centre = n // 2 + int(round(offset / binw))
    half = max(int(round(5000.0 / binw / 2)), 1)
    rows = []
    for _ in range(trials):
        sdr.DRAIN, sdr.SETTLE = False, 4096
        sdr.measure(strong * 1e6, 5000.0, 0, 0, settings)
        if pause_s:
            time.sleep(pause_s)
        sdr.dev.setFrequency(sdr.RX, 0, quiet * 1e6 - offset)
        if drain:
            sdr._drain()
        row = []
        buf = np.zeros(n, np.complex64)
        for _k in range(nseg):
            got = 0
            while got < n:
                sr = sdr.dev.readStream(sdr.stream, [buf[got:]], n - got, timeoutUs=500_000)
                if sr.ret > 0:
                    got += sr.ret
                elif sr.ret < 0:
                    break
            spec = np.abs(np.fft.fftshift(np.fft.fft(buf * sdr.window))) ** 2 / (n * sdr.win_pow)
            row.append(10.0 * math.log10(float(spec[centre - half: centre + half + 1].sum()) + 1e-20))
        rows.append(row)
    return rows


def run_pattern(sdr, fa, fb, settings, pause_s, drain, settle, rounds=8):
    """Jump A, B, A, B ... like the logger. Returns (mean error of A, mean error of B, seconds per reading)."""
    sdr.DRAIN, sdr.SETTLE = drain, settle
    ea, eb, t_tot, n = [], [], 0.0, 0
    for _ in range(rounds):
        for mhz, ref, store in ((fa[0], fa[1], ea), (fb[0], fb[1], eb)):
            t0 = time.time()
            v = sdr.measure(mhz * 1e6, 5000.0, 0, 0, settings)
            t_tot += time.time() - t0
            n += 1
            if not math.isnan(v):
                store.append(v - ref)
        if pause_s:
            time.sleep(pause_s)
    avg = lambda l: sum(l) / len(l) if l else float("nan")
    return avg(ea), avg(eb), t_tot / max(n, 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", help="save the report to this file")
    args = ap.parse_args()
    out = []

    def say(t=""):
        print(t)
        out.append(t)

    say("RF Noise Map - switching test")
    say("=" * 60)
    import rfmap_log as L
    L.setup("switchtest")
    settings = copy.deepcopy(RL.DEFAULT_SETTINGS)
    for cand in (os.path.join(C.data_dir(), "Settings", "settings.json"),
                 os.path.join(C.data_dir(), "Settings", "logger_settings.json")):
        try:
            with open(cand) as f:
                settings.update(json.load(f))
            break
        except Exception:
            pass
    try:
        sdr = RL.SoapySdr(settings)
    except SystemExit as e:
        say("Could not open the radio: " + str(e).strip())
        say("Close SDRuno / SDRconnect / SDR Console / HDSDR and RF Noise Map, plug the radio in, and try again.")
        return 1
    try:
        say("Step 1: finding a strong and a quiet frequency (about 20 seconds)...")
        freqs = list(CANDIDATES_MHZ)
        for ch in settings.get("channels", []):
            if ch["mhz"] not in freqs:
                freqs.append(ch["mhz"])
        levels = []
        for mhz in freqs:
            v = sdr.measure(mhz * 1e6, 5000.0, 0, 0, settings)
            v = sdr.measure(mhz * 1e6, 5000.0, 0, 0, settings)
            if not math.isnan(v):
                levels.append((v, mhz))
        if len(levels) < 2:
            say("The radio gave no readings. Check the antenna and the cable.")
            return 1
        levels.sort()
        quiet, strong = levels[0], levels[-1]
        gap = strong[0] - quiet[0]
        say(f"  strongest: {strong[1]} MHz at about {strong[0]:.0f} dBFS;  quietest: {quiet[1]} MHz at about {quiet[0]:.0f} dBFS")
        if gap < 15:
            say("  The two are less than 15 dB apart, so this test cannot show a problem clearly.")
            say("  Connect the antenna (an FM broadcast band signal near 88-108 MHz works well) and run it again.")
        say("Step 2: measuring each one carefully, with a full second to settle ('true' readings)...")
        ta = true_level(sdr, strong[1], settings)
        tb = true_level(sdr, quiet[1], settings)
        say(f"  true level  {strong[1]} MHz: {ta:.1f} dBFS      {quiet[1]} MHz: {tb:.1f} dBFS")
        fa, fb = (strong[1], ta), (quiet[1], tb)

        say("Step 3: jumping between them the way the program does (error = quick reading minus true reading):")
        say(f"  {'case':44s} {'strong err':>10s} {'quiet err':>10s}  {'ms/reading':>10s}")
        cases = [
            ("OLD method, jumping back to back", 0.0, False, 4096),
            ("OLD method, 0.15 s between jumps (like 45 mph)", 0.15, False, 4096),
            ("OLD method, 1 s between jumps (slow driving)", 1.0, False, 4096),
            ("NEW method, jumping back to back", 0.0, True, 8192),
            ("NEW method, 0.15 s between jumps", 0.15, True, 8192),
            ("NEW method, 1 s between jumps", 1.0, True, 8192),
            ("NEW + longer settle (16384), 0.15 s between", 0.15, True, 16384),
        ]
        worst_old = worst_new = 0.0
        for name, pause, drain, settle in cases:
            ea, eb, t = run_pattern(sdr, fa, fb, settings, pause, drain, settle)
            say(f"  {name:44s} {ea:+10.1f} {eb:+10.1f}  {t*1000:10.0f}")
            w = max(abs(ea), abs(eb))
            if name.startswith("OLD"):
                worst_old = max(worst_old, w)
            elif name.startswith("NEW method"):
                worst_new = max(worst_new, w)
        say()
        say("Step 4: time profile. After jumping from the strong to the quiet frequency, the level of each")
        say(f"  2 ms slice (true quiet level is {tb:.0f} dBFS). Each line is the average of 6 jumps; slices run left to right.")
        for pause, drain in ((0.0, False), (0.15, False), (0.15, True), (1.0, True)):
            rows = profile(sdr, strong[1], quiet[1], settings, pause, drain)
            avg = [sum(r[i] for r in rows) / len(rows) for i in range(len(rows[0]))]
            say(f"  pause {pause:4.2f}s drain {'on ' if drain else 'off'}: " + " ".join(f"{v:4.0f}" for v in avg))
            firsts = []
            for r in rows:
                k = next((i for i, v in enumerate(r) if v < tb + 3.0), None)
                firsts.append("never" if k is None else str(k * 2))
            say("      ms until within 3 dB of true, per jump: " + ", ".join(firsts))
        say()
        say("How to read this: 0.0 means the quick reading matches the true one. If readings are mixed up with the")
        say("frequency just before, the strong one reads too LOW (minus number) and the quiet one too HIGH (plus number).")
        say()
        if gap < 15:
            say("Result: not conclusive (see above).")
        elif worst_old < 1.0:
            say(f"Result: even the old method was within {worst_old:.1f} dB. Switching looks clean.")
        elif worst_new < 1.0:
            say(f"Result: the OLD method was off by up to {worst_old:.1f} dB; the NEW method is within {worst_new:.1f} dB. The program now uses the new method.")
        else:
            say(f"Result: the old method was off by up to {worst_old:.1f} dB and the new method by up to {worst_new:.1f} dB.")
            say("Please send this report (switch_test_report.txt) to Claude.")
        return 0
    finally:
        sdr.close()
        if args.report:
            try:
                with open(args.report, "w", encoding="utf-8") as f:
                    f.write("\n".join(out) + "\n")
            except OSError:
                pass


if __name__ == "__main__":
    sys.exit(main())
