"""
Ordinary radios read over their USB / serial CAT cable (Icom, Yaesu, Kenwood, Elecraft ...).
The commands and meter tables for each model are in cat_models.json; the shared reader is cat_engine.py.
The radios you have added are in the settings under "cat_radios": a list of
  {"id": "cat1", "model": "ic7300", "port": "/dev/cu.usbserial-1420", "baud": 19200, "civ_addr": "", "mode": "follow"}
"""
import radios.base as B
from radios import cat_engine as E

MAX_CAT = 4


class CatDriver(B.RadioDriver):
    order = 50
    id, name, kind = "cat", "Radios on a USB / CAT cable (Icom, Yaesu, Kenwood, Elecraft)", "meter"
    accuracy = ("The radio's own S-meter, one frequency at a time (coarser and slower than a raw-signal receiver). "
                "Each radio gets its own colour scale on the map. Follow mode never changes the radio.")
    cfg_flag = "use_cat"
    note = ("Add each radio in Hardware setup, under 'Radios on a CAT cable'. Not yet checked against real radios.")

    def owns(self, value):
        v = str(value or "")
        return v.startswith("cat") and v[3:].isdigit()

    @staticmethod
    def entries(cfg):
        out = []
        for i, e in enumerate((cfg or {}).get("cat_radios") or [], 1):
            if isinstance(e, dict) and e.get("model"):
                e = dict(e)
                e["id"] = "cat%d" % i
                out.append(e)
        return out[:MAX_CAT]

    def label_for(self, e):
        m = E.model_by_id(e.get("model")) or {}
        return "%s %s%s" % (m.get("maker", ""), m.get("name", e.get("model")), " (follow)" if e.get("mode") != "control" else "")

    def slot_values(self, found, cfg=None):
        return [(e["id"], self.label_for(e)) for e in self.entries(cfg)]

    @staticmethod
    def _is_flex(e):
        return E.is_flex(E.model_by_id(e.get("model")) or {})

    def detect(self, cfg, practice=False):
        ents = [e for e in self.entries(cfg) if not self._is_flex(e)]
        if practice:
            return {"found": [{"label": self.label_for(e), "detail": "practice mode"} for e in ents],
                    "note": "Practice mode." if ents else "Practice mode. Add a radio below to see it in the slot menus."}
        out = []
        for e in ents:
            if not str(e.get("port") or "").strip():
                out.append({"label": self.label_for(e), "ok": False, "detail": "added, but no USB port chosen yet (nothing tested)"})
                continue
            r = E.test_radio(e)
            out.append({"label": self.label_for(e), "ok": bool(r.get("ok")), "detail": ("%s: %s" % (e.get("port"), r["message"]))})
        return {"found": out, "note": "" if out else "None added. Use 'Add a CAT radio' below."}

    def open(self, rid, settings, chans, ctx):
        for e in self.entries(settings):
            if e["id"] == rid:
                return E.CatRadio(e)
        raise E.CatError("The radio %s is not set up (Hardware setup > Radios on a CAT cable)." % rid)


class FlexScanDriver(B.RadioDriver):
    """The FlexRadio line in the scan list (0.7.0i). It only LOOKS: the radios themselves are the same 'cat1'..'cat4' entries
    and are opened by CatDriver, so nothing about slots or settings changes."""
    order = 25
    id, name, kind = "flexscan", "FlexRadio 6000 / 8000 series (network)", "meter"
    accuracy = ("Found on the network, like the ANAN. In Control mode each slot gets its own receiver and picture. "
                "Add it in Hardware setup, under 'Your radios'.")
    note = "Listed here so a Flex is found and tested next to the other network radios."

    def owns(self, value):
        return False

    def slot_values(self, found, cfg=None):
        return []

    def detect(self, cfg, practice=False):
        ents = [e for e in CatDriver.entries(cfg) if CatDriver._is_flex(e)]
        lab = lambda e: CatDriver().label_for(e)
        if practice:
            return {"found": [{"label": lab(e), "detail": "practice mode"} for e in ents], "note": "Practice mode."}
        out = []
        for e in ents:
            if not str(e.get("port") or "").strip():
                out.append({"label": lab(e), "ok": False, "detail": "added, but no address chosen yet (nothing tested)"})
                continue
            r = E.test_radio(e)
            out.append({"label": lab(e), "ok": bool(r.get("ok")), "detail": ("%s: %s" % (e.get("port"), r["message"]))})
        note = ""
        try:                                           # Flex radios announce themselves on the network
            import radios.flex_api as FX
            st = {}
            have = {str(e.get("port") or "").split(":")[0] for e in ents}
            heard = 0
            for f in FX.find_radios(3.0, stats=st):
                heard += 1
                if f["ip"] not in have:
                    mid = next((m["id"] for m in E.load_models()["models"] if m["dialect"] == "flex_api" and m["name"].upper() == str(f["model"]).upper()), "")
                    if not mid:
                        mid = next((m["id"] for m in E.load_models()["models"] if m["dialect"] == "flex_api" and str(f["model"]).upper().replace("FLEX-", "") in m["name"].upper()), "flex6600")
                    out.append({"label": "FlexRadio %s%s" % (f["model"], (" '%s'" % f["nickname"]) if f["nickname"] else ""), "ok": True,
                                "detail": "found on the network at %s." % f["ip"], "add": {"model": mid, "port": f["ip"], "baud": 0, "civ_addr": "", "mode": "control"}})
            if not heard:
                note = "No Flex radio heard on the network. " + FX.why_none(st.get("heard", 0))
        except Exception as ex:
            note = "Flex search did not run: %s" % ex
        return {"found": out, "note": note}


DRIVER = CatDriver()
DRIVERS = [DRIVER, FlexScanDriver()]
