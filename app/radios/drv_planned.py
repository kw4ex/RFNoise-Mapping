"""Radio types that are listed (greyed out) so you can see what is coming. They cannot be picked yet."""
import radios.base as B



class TciDriver(B.RadioDriver):
    order = 91
    id, name, kind = "tci", "TCI radios (Thetis, ExpertSDR, SunSDR)", "meter"
    accuracy = "Signal level in dBm from the radio's own meter, over the network."
    planned = True
    note = "Planned."


DRIVERS = [TciDriver()]
