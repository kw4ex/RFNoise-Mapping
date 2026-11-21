"""
radio_plugins.py - the list of radio TYPES the program knows about, loaded from the radios/ folder.

Each radio type is one small file in radios/ (see radios/base.py). The Hardware window and every slot's
Radio chooser are built from this list, so adding a radio means adding a file and nothing else on the screens.
"""
from radios import DRIVERS, LOAD_PROBLEMS          # noqa: F401
from radios.base import RadioDriver                # noqa: F401


def get(driver_id):
    for d in DRIVERS:
        if d.id == driver_id:
            return d
    return None


def driver_for_slot_value(v):
    """'rtl3' -> the RTL driver, 'cat1' -> the CAT driver, 'hl2' -> Hermes, and so on."""
    for d in DRIVERS:
        if d.owns(v):
            return d
    return None
