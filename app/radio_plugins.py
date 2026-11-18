"""
radio_plugins.py - the list of radio TYPES the program knows about ("plug-ins").

Each radio type is one small class below. It says what the radio is called, how it is found, how it is
read, and what to expect from it (how exact the level is, whether it listens to several frequencies at
once). The Hardware window and the slot chooser are built from this list, so adding a radio later means
adding one class here (and its reader in rf_logger.py) and nothing else on the screens.

Two kinds of radio:
  "iq"    a radio that hands over the raw radio signal, so the program measures the power inside the
          chosen width itself (Hermes Lite 2, ANAN, SDRplay, RTL-SDR). Fine detail, fast.
  "meter" a radio that is tuned by a control link (CAT or TCI) and reports its own signal-meter level.
          Coarser and slower, and each radio's meter has its own scale, so every slot is coloured on
          its own scale. Planned, not built yet.

`planned = True` entries are only listed (greyed out) so you can see what is coming.
"""

import rfmap_common as C


class RadioDriver:
    id = ""                 # what the slot chooser stores ("hl2", "sdrplay", "rtl1".. )
    name = ""
    kind = "iq"
    accuracy = ""           # one line for the Hardware window
    multi = False           # True = several frequencies are read at the same instant
    max_mhz = None          # highest frequency it can hear (None = no limit worth mentioning)
    planned = False
    scan_only = False       # True = can be found but not yet used for readings
    note = ""
    cfg_flag = ""           # the "tick box" in config.json that switches it on

    def slot_values(self, found):
        """The choices this radio adds to a slot's Radio chooser: [(value, label)]."""
        return [(self.id, self.name)]

    def detect(self, cfg, practice=False):
        """Look for the radio. Returns {"found": [{"label","detail"}], "note": ""}."""
        return {"found": [], "note": ""}

    def describe(self):
        return {"id": self.id, "name": self.name, "kind": self.kind, "accuracy": self.accuracy,
                "multi": self.multi, "max_mhz": self.max_mhz, "planned": self.planned, "scan_only": self.scan_only, "note": self.note}


class Hl2Driver(RadioDriver):
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


class SdrplayDriver(RadioDriver):
    id, name, kind = "sdrplay", "SDRplay RSP1", "iq"
    accuracy = "Raw radio signal. One receiver, so its frequencies take turns. Covers HF through VHF and airband."
    cfg_flag = "use_sdrplay"

    def detect(self, cfg, practice=False):
        if practice:
            return {"found": [{"label": "Pretend SDRplay", "detail": "practice mode"}], "note": "Practice mode."}
        soapy, note = C.find_soapy()
        if soapy is None:
            return {"found": [], "note": "The SDRplay radio library (SoapySDR) is not available. " + str(note)}
        try:
            devs = [dict(d) for d in soapy.Device.enumerate("driver=sdrplay")]
        except Exception as e:
            return {"found": [], "note": "Could not ask for the radio: %s" % e}
        out = [{"label": d.get("label") or d.get("serial") or "SDRplay", "detail": "USB"} for d in devs]
        return {"found": out, "note": "" if out else "No SDRplay found. Check the USB cable and the SDRplay API."}


class RtlDriver(RadioDriver):
    id, name, kind = "rtl", "RTL-SDR dongles", "iq"
    accuracy = "Raw radio signal. Each dongle is one receiver; several dongles read together. Not yet tried on real dongles."
    cfg_flag = "use_rtl"

    def slot_values(self, found):
        n = max(1, min(4, len(found))) if found else 4
        return [("rtl%d" % k, "RTL-SDR %d" % k) for k in range(1, n + 1)]

    def detect(self, cfg, practice=False):
        if practice:
            return {"found": [{"label": "Pretend RTL-SDR %d" % k, "detail": "practice mode"} for k in (1, 2, 3, 4)], "note": "Practice mode."}
        import rf_logger as RL
        lst, note = RL.rtl_list()
        out = [{"label": "RTL-SDR %d: %s" % (k + 1, d["label"]), "detail": "serial %s" % (d["serial"] or "none")}
               for k, d in enumerate(lst[:4])]
        return {"found": out, "note": note if not out else ""}


# ---- planned radio types (listed so you can see what is coming; they cannot be picked yet) ----------

class AnanDriver(RadioDriver):
    id, name, kind = "anan", "ANAN (Apache / OpenHPSDR, e.g. ANAN-7000)", "iq"
    accuracy = "Raw radio signal, four receivers read at the same instant (like the Hermes Lite 2). Levels in dBFS, not yet calibrated to dBm."
    multi, max_mhz, cfg_flag = True, 55.0, "use_anan"
    note = "Testing (1.4.0u): readings work in slots; no sound or calibration yet. Close Thetis first."

    def slot_values(self, found):
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


class FlexDriver(RadioDriver):
    id, name, kind = "flex", "FlexRadio (SmartSDR slices)", "iq"
    accuracy = "Several slices at once through the radio's own network interface."
    multi, planned = True, True
    note = "Planned: after the ANAN."


class TciDriver(RadioDriver):
    id, name, kind = "tci", "TCI radios (Thetis, ExpertSDR, SunSDR)", "meter"
    accuracy = "Signal level in dBm from the radio's own meter."
    planned = True
    note = "Planned."


class CatDriver(RadioDriver):
    id, name, kind = "cat", "Icom / Kenwood / Yaesu over the CAT port", "meter"
    accuracy = "S-meter reading of one tuned frequency: coarser and slower, and each slot is coloured on its own scale."
    planned = True
    note = "Planned."


DRIVERS = [Hl2Driver(), SdrplayDriver(), RtlDriver(), AnanDriver(), FlexDriver(), TciDriver(), CatDriver()]


def get(driver_id):
    for d in DRIVERS:
        if d.id == driver_id:
            return d
    return None


def driver_for_slot_value(v):
    """'rtl3' -> the RTL driver, 'hl2' -> Hermes, and so on."""
    v = str(v or "")
    if v.startswith("rtl"):
        return get("rtl")
    return get(v)
