"""
radios - the radio plug-ins. Every file here (except base.py and the cat_* helper files) that ends with
DRIVER = SomeDriver()   (or DRIVERS = [ ... ])   is loaded when the program starts.

A plug-in that fails to load is skipped and the reason is kept in LOAD_PROBLEMS, so one bad file can
never stop the other radios.
"""
import importlib
import os
import pkgutil

from .base import RadioDriver

_SKIP = {"base", "cat_engine", "cat_sim", "flex_api"}
LOAD_PROBLEMS = {}


def _load():
    found = []
    here = os.path.dirname(os.path.abspath(__file__))
    for m in sorted(pkgutil.iter_modules([here]), key=lambda x: x.name):
        if m.name in _SKIP or m.name.startswith("_"):
            continue
        try:
            mod = importlib.import_module("radios." + m.name)
            ds = list(getattr(mod, "DRIVERS", [])) or ([mod.DRIVER] if hasattr(mod, "DRIVER") else [])
            if not ds:
                LOAD_PROBLEMS[m.name] = "the file has no DRIVER line"
            found += [d for d in ds if isinstance(d, RadioDriver)]
        except Exception as e:                      # a broken plug-in is skipped, never fatal
            LOAD_PROBLEMS[m.name] = "%s: %s" % (type(e).__name__, e)
    found.sort(key=lambda d: (d.order, d.id))
    return found


DRIVERS = _load()
