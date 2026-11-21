"""
base.py - what every radio plug-in looks like.

A radio plug-in is ONE small file in this folder. It defines a class based on RadioDriver and ends with
    DRIVER = MyDriver()
The program loads every such file when it starts (see __init__.py), so adding a radio means adding a file.
The Hardware window and each slot's Radio chooser are built from the loaded list.

What a plug-in provides
  id, name, kind        what it is called; "iq" (the radio hands over the raw signal) or "meter" (it reports its own meter)
  cfg_flag              the tick box in the settings that switches it on ("" = always listed)
  multi                 True = all its slots are read at the same instant
  owns(value)           does a slot's Radio value (e.g. "rtl2", "cat1") belong to this plug-in?
  slot_values(...)      the choices it adds to a slot's Radio chooser
  detect(...)           look for the radio (used by "Scan for radios")
  open(...)             make the reader the live view and the recorder use
"""


class RadioDriver:
    id = ""                 # what the slot chooser stores ("hl2", "sdrplay", "rtl1".. )
    name = ""
    kind = "iq"
    accuracy = ""           # one line for the Hardware window
    multi = False           # True = several frequencies are read at the same instant
    max_mhz = None          # highest frequency it can hear (None = no limit worth mentioning)
    planned = False         # listed (greyed out) but not usable yet
    scan_only = False       # True = can be found but not yet used for readings
    note = ""
    cfg_flag = ""           # the "tick box" in config.json that switches it on
    order = 100             # position in the lists (small numbers first)

    def owns(self, value):
        """Does this slot Radio value belong to this plug-in?"""
        return str(value or "") == self.id

    def slot_values(self, found, cfg=None):
        """The choices this radio adds to a slot's Radio chooser: [(value, label)]."""
        return [(self.id, self.name)]

    def detect(self, cfg, practice=False):
        """Look for the radio. Returns {"found": [{"label","detail"}], "note": ""}."""
        return {"found": [], "note": ""}

    def open(self, rid, settings, chans, ctx):
        """Return the reader for slot value rid. chans = this radio's own slots. ctx = hl2_ip, hl2_rate, hl2_port."""
        raise NotImplementedError("%s cannot be opened yet." % self.name)

    def describe(self):
        return {"id": self.id, "name": self.name, "kind": self.kind, "accuracy": self.accuracy,
                "multi": self.multi, "max_mhz": self.max_mhz, "planned": self.planned, "scan_only": self.scan_only, "note": self.note}
