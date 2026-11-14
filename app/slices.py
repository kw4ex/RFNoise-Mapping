"""
slices.py - the "slices" preview: a live picture of EVERY measured frequency at once, without logging.

While logging, the logger itself supplies these pictures. This preview is for checking the antenna, the gain
and the frequencies BEFORE a drive. With the Hermes Lite 2 all channels are live together; with the SDRplay
(one receiver) the channels are looked at one after another.
"""

import threading
import time

import rfmap_log as L

IDLE_STOP_S = 25          # free the radio when the browser stops asking for pictures


class SlicePreview:
    def __init__(self):
        self.lock = threading.Lock()
        self.thread = None
        self.running = False
        self.error = ""
        self.name = ""
        self.last_poll = time.time()
        self.health = {}
        self.cfg = {}

    def start(self, radio, practice, channels, hl2_ip="", hl2_rate=96000, gain=None):
        import rf_logger as RL
        self.stop()
        gain = gain or {}
        settings = {"channels": channels, "if_gain_db": gain.get("if_gain_db", 40),
                    "rf_gain_state": gain.get("rf_gain_state", 0), "hl2_gain_db": gain.get("hl2_gain_db", 15)}
        try:
            if practice:
                sdr = RL.SimSdr()
            elif radio == "hl2":
                sdr = RL.HermesLite2(settings, hl2_ip, int(hl2_rate))
            else:
                sdr = RL.SoapySdr(settings)
        except SystemExit as e:                        # the radio classes print-and-exit on trouble
            raise ValueError(str(e).strip() or "The radio could not be opened.")
        except RuntimeError as e:
            raise ValueError(str(e))
        with RL.PAN_FRAME["lock"]:
            RL.PAN_FRAME["all"] = {}
        with self.lock:
            self.cfg = settings
            self.running = True
            self.error = ""
            self.name = getattr(sdr, "name", "")
            self.last_poll = time.time()
        self.thread = threading.Thread(target=self._loop, args=(sdr,), name="slices", daemon=True)
        self.thread.start()

    def set(self, channels=None, gain=None):
        with self.lock:
            if channels is not None:
                self.cfg["channels"] = channels
            if gain:
                self.cfg.update(gain)

    def stop(self):
        self.running = False
        t = self.thread
        if t is not None and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=4)
        self.thread = None

    def get(self):
        import rf_logger as RL
        self.last_poll = time.time()
        with RL.PAN_FRAME["lock"]:
            fr = [RL.PAN_FRAME["all"][k] for k in sorted(RL.PAN_FRAME["all"])]
        return {"ok": True, "running": self.running, "logging": False, "error": self.error,
                "radio": self.name, "frames": fr, "health": self.health}

    def _loop(self, sdr):
        import rf_logger as RL
        try:
            while self.running:
                if time.time() - self.last_poll > IDLE_STOP_S:
                    break
                with self.lock:
                    cfg = dict(self.cfg)
                chans = [c for c in cfg["channels"][:RL.MAX_CHANNELS]]
                if getattr(sdr, "multi", False):
                    for k, (_lv, _t, fr) in enumerate(sdr.measure_all(chans, cfg)):
                        if fr:
                            RL.publish_spectrum(fr[0], fr[1], fr[2], chans[k]["mhz"] * 1e6,
                                                chans[k]["bw_khz"] * 1e3, fr[3], k)
                    time.sleep(0.08)
                else:
                    for k, ch in enumerate(chans):
                        lv = sdr.measure(ch["mhz"] * 1e6, ch["bw_khz"] * 1e3, 0.0, 0.0, cfg)
                        fr = sdr.last_frame()
                        if fr:
                            RL.publish_spectrum(fr[0], fr[1], fr[2], ch["mhz"] * 1e6, ch["bw_khz"] * 1e3, lv, k)
                        if not self.running:
                            break
                if hasattr(sdr, "health"):
                    self.health = sdr.health()
        except Exception as e:
            self.error = "%s: %s" % (type(e).__name__, e)
            L.error("the slices preview stopped", e)
        finally:
            self.running = False
            try:
                sdr.close()
            except Exception:
                pass


SLICES = SlicePreview()
