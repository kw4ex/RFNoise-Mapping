"""ANAN and other OpenHPSDR protocol 2 radios (network cable)."""
import radios.base as B


class AnanDriver(B.RadioDriver):
    order = 20
    id, name, kind = "anan", "ANAN (Apache / OpenHPSDR, e.g. ANAN-7000)", "iq"
    accuracy = "Raw radio signal, four receivers read at the same instant (like the Hermes Lite 2). Levels in dBFS, not yet calibrated to dBm."
    multi, max_mhz, cfg_flag = True, 55.0, "use_anan"
    note = "Four slots at the same instant on the main antenna input. Levels in dBFS (not yet dBm). Listen and record work (AM, SAM, USB, LSB, NFM). Close Thetis first."

    def slot_values(self, found, cfg=None):
        return [(self.id, "ANAN")]

    def detect(self, cfg, practice=False):
        if practice:
            return {"found": [{"label": "Pretend ANAN", "detail": "practice mode"}], "note": "Practice mode."}
        import anan
        ip = str(cfg.get("anan_ip", "")).strip()
        try:
            devs = anan.discover(ip or None, timeout=3.0)
        except Exception as e:
            return {"found": [], "note": "Could not search the network: %s" % e}
        out = []
        for d in devs:
            det = "%s, protocol %s, firmware %d, board type %d" % (d["ip"], d["protocol_text"], d["firmware"], d["board"])
            if d["board_note"]:
                det += " (" + d["board_note"] + ")"
            det += " - free" if not d["busy"] else " (another program, such as Thetis, is using it)"
            out.append({"label": "ANAN / openHPSDR radio", "detail": det})
        return {"found": out, "note": "" if out else
                "No radio answered" + (" at " + ip if ip else " on the network") + ". Check the network cable and power. The radio needs its Protocol 2 firmware."}

    def open(self, rid, settings, chans, ctx):
        import nt_logger as RL
        aset = dict(settings)
        aset["channels"] = chans
        return RL.AnanRadio(aset, "", ctx.get("hl2_rate", 96000))


DRIVER = AnanDriver()
