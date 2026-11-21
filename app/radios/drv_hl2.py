"""Hermes Lite 2 (OpenHPSDR protocol 1, network cable)."""
import radios.base as B
import nt_common as C


class Hl2Driver(B.RadioDriver):
    order = 10
    id, name, kind = "hl2", "Hermes Lite 2", "iq"
    accuracy = "Raw radio signal, read at the same instant on every slot. HF only (to about 38 MHz)."
    multi, max_mhz, cfg_flag = True, 38.0, "use_hl2"

    def detect(self, cfg, practice=False):
        if practice:
            return {"found": [{"label": "Pretend Hermes Lite 2", "detail": "practice mode"}], "note": "Practice mode."}
        import hl2
        ip = str(cfg.get("hl2_ip", "")).strip()
        try:
            devs = hl2.discover(ip or None, timeout=3.0)
        except Exception as e:
            return {"found": [], "note": "Could not search the network: %s" % e}
        out = []
        for d in devs:
            det = "%s, %d receivers" % (d.get("ip", "?"), d.get("nrx", 0))
            if d.get("busy"):
                det += " (another program is using it)"
            out.append({"label": "Hermes Lite 2", "detail": det})
        return {"found": out, "note": "" if out else
                "No radio answered" + (" at " + ip if ip else " on the network") + ". Check the network cable and power; close Thetis / SDR Console."}

    def open(self, rid, settings, chans, ctx):
        import nt_logger as RL
        hset = dict(settings)
        hset["channels"] = chans
        return RL.HermesLite2(hset, ctx.get("hl2_ip", ""), ctx.get("hl2_rate", 96000), ctx.get("hl2_port", 1024))


DRIVER = Hl2Driver()
