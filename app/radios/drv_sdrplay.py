"""SDRplay RSP1 (USB, through SoapySDR)."""
import radios.base as B
import nt_common as C


class SdrplayDriver(B.RadioDriver):
    order = 30
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

    def open(self, rid, settings, chans, ctx):
        import nt_logger as RL
        return RL.SoapySdr(settings)


DRIVER = SdrplayDriver()
