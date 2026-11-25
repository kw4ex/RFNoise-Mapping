"""
slices.py - the "slices" preview: a live picture of EVERY measured frequency at once, without logging.

While logging, the logger itself supplies these pictures. This preview is for checking the antenna, the gain
and the frequencies BEFORE a drive. With the Hermes Lite 2 all channels are live together; with the SDRplay
(one receiver) the channels are looked at one after another.
"""

import threading
import time

import nt_log as L

IDLE_STOP_S = 600         # free the radio when the browser stops asking for pictures (never during a recording)


class SlicePreview:
    @property
    def warn(self):
        return getattr(self, "_warn", {})

    @warn.setter
    def warn(self, value):
        """Whenever a slot's message changes it is also written to the program log (so it can be read without the screen)."""
        value = value or {}
        seen = getattr(self, "_warn_logged", {})
        for slot, msg in value.items():
            if seen.get(slot) != msg:
                try:
                    L.warn("Slot %s: %s" % (slot, msg))
                except Exception:
                    pass
        self._warn_logged = dict(value)
        self._warn = value

    def __init__(self):
        self.lock = threading.Lock()
        self.thread = None
        self.running = False
        self.error = ""
        self.name = ""
        self.last_poll = time.time()
        self.health = {}
        self.cfg = {}
        self.warn = {}
        self.warn_base = {}

    def start(self, practice, channels, hl2_ip="", hl2_rate=96000, gain=None):
        import nt_logger as RL
        self.stop()
        gain = gain or {}
        settings = {"channels": channels, "if_gain_db": gain.get("if_gain_db", 40),
                    "rf_gain_state": gain.get("rf_gain_state", 0), "hl2_gain_db": gain.get("hl2_gain_db", 15), "view_speed": gain.get("view_speed", "normal"),
                    "rtl_gain_db": gain.get("rtl_gain_db") or {}, "cat_radios": gain.get("cat_radios") or []}
        try:
            if practice:
                sdr = RL.SimSdr()
            else:
                sdr = RL.MultiRadio(settings, hl2_ip, int(hl2_rate), tolerant=True)
        except SystemExit as e:                        # the radio classes print-and-exit on trouble
            raise ValueError(str(e).strip() or "The radio could not be opened.")
        except RuntimeError as e:
            raise ValueError(str(e))
        with RL.PAN_FRAME["lock"]:
            RL.PAN_FRAME["all"] = {}
        import hl2_audio
        import nt_common as C
        with self.lock:
            self.cfg = settings
            self.running = True
            self.error = ""
            self.name = getattr(sdr, "name", "")
            self.last_poll = time.time()
            self.sdr = sdr
            bad = getattr(sdr, "failed", {}) or {}          # a radio that would not open only takes down its own slots
            self.warn = {c.get("slot"): bad[c.get("radio")] for c in channels if c.get("slot") and c.get("radio") in bad}
            self.warn_base = dict(self.warn)
        hl2_audio.SND.attach(lambda ch: RL.hl2_lookup(sdr, self.cfg.get("channels", []), ch),
                             C.sub_dir("Recordings"))
        self.thread = threading.Thread(target=self._loop, args=(sdr,), name="slices", daemon=True)
        self.thread.start()

    def set(self, channels=None, gain=None):
        with self.lock:
            if channels is not None:
                self.cfg["channels"] = channels
            if gain:
                self.cfg.update(gain)

    def stop(self):
        try:
            import hl2_audio
            hl2_audio.SND.stop_all()
        except Exception:
            pass
        self.running = False
        t = self.thread
        if t is not None and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=4)
        self.thread = None

    def get(self):
        import nt_logger as RL
        self.last_poll = time.time()
        with RL.PAN_FRAME["lock"]:
            fr = [RL.PAN_FRAME["all"][k] for k in sorted(RL.PAN_FRAME["all"])]
        import hl2_audio
        return {"ok": True, "running": self.running, "logging": False, "error": self.error,
                "radio": self.name, "frames": fr, "health": self.health, "sound": hl2_audio.SND.status(), "warn": dict(self.warn)}

    def _recording(self):
        try:
            import hl2_audio
            return any(v.get("rec_file") for v in hl2_audio.SND.status().values())
        except Exception:
            return False

    def _loop(self, sdr):
        import nt_logger as RL
        try:
            while self.running:
                if time.time() - self.last_poll > IDLE_STOP_S and not self._recording():
                    break
                with self.lock:
                    cfg = dict(self.cfg)
                chans = [c for c in cfg["channels"][:RL.MAX_CHANNELS]]
                act = [(k, c) for k, c in enumerate(chans) if not c.get("skip")]      # skipped = on the SDRplay, which the live-view engine uses
                if not act:
                    time.sleep(0.2)
                elif getattr(sdr, "multi", False):
                    res = sdr.measure_all([c for _, c in act], cfg)
                    for (k, c), (_lv, _t, fr) in zip(act, res):
                        if fr:
                            RL.publish_spectrum(fr[0], fr[1], fr[2], c["mhz"] * 1e6, c["bw_khz"] * 1e3, fr[3], RL.slot_idx(c, k), c.get("radio", ""))
                        elif _lv == _lv and str(c.get("radio", "")).startswith("cat"):        # a CAT radio: a flat line at its meter level
                            RL.publish_meter(_lv, c["mhz"] * 1e6, c["bw_khz"] * 1e3, RL.slot_idx(c, k), c.get("radio", ""))
                    if hasattr(sdr, "slot_notes"):                                           # a CAT radio says why it gave no reading
                        self.warn = {**getattr(self, "warn_base", {}), **sdr.slot_notes([c for _, c in act])}
                    time.sleep({"smooth": 0.004, "light": 0.15}.get(cfg.get("view_speed"), 0.03))      # picture speed (a runtime choice)
                else:
                    for k, ch in act:
                        lv = sdr.measure(ch["mhz"] * 1e6, ch["bw_khz"] * 1e3, 0.0, 0.0, cfg)
                        fr = sdr.last_frame()
                        if fr:
                            RL.publish_spectrum(fr[0], fr[1], fr[2], ch["mhz"] * 1e6, ch["bw_khz"] * 1e3, lv, RL.slot_idx(ch, k))
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
                import hl2_audio
                hl2_audio.SND.stop_all()           # finish any slice recordings cleanly
            except Exception:
                pass
            try:
                sdr.close()
            except Exception:
                pass


    def pos(self, slot):
        """Where panel slot `slot` (0 to 3) sits in the radio's channel list (the sound engine counts positions). Falls back to
        the slot number when it is not in the list."""
        import nt_logger as RL
        p = RL.pos_of_slot((self.cfg or {}).get("channels", []), slot)
        return p if p >= 0 else int(slot)


SLICES = SlicePreview()
