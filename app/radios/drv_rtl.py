"""RTL-SDR dongles (USB, through SoapySDR). Up to four."""
import radios.base as B
import nt_common as C


class RtlDriver(B.RadioDriver):
    order = 40
    id, name, kind = "rtl", "RTL-SDR dongles", "iq"
    accuracy = "Raw radio signal. Each dongle is one receiver; several dongles read together. Not yet tried on real dongles."
    cfg_flag = "use_rtl"

    def owns(self, value):
        return str(value or "") in C.RTL_IDS

    def slot_values(self, found, cfg=None):
        n = max(1, min(4, len(found))) if found else 4
        return [("rtl%d" % k, "RTL-SDR %d" % k) for k in range(1, n + 1)]

    def driver_state(self):
        return C.soapy_driver_state("rtlsdr", "the RTL-SDR dongles")

    def detect(self, cfg, practice=False):
        if practice:
            return {"found": [{"label": "Pretend RTL-SDR %d" % k, "detail": "practice mode"} for k in (1, 2, 3, 4)], "note": "Practice mode."}
        import nt_logger as RL
        lst, note = RL.rtl_list()
        out = [{"label": "RTL-SDR %d: %s" % (k + 1, d["label"]), "detail": "serial %s" % (d["serial"] or "none")}
               for k, d in enumerate(lst[:4])]
        return {"found": out, "note": note if not out else ""}

    def open(self, rid, settings, chans, ctx):
        import nt_logger as RL
        return RL.RtlSdr(settings, rid)


DRIVER = RtlDriver()
