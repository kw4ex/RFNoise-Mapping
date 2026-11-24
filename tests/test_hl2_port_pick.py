"""The HL2 stream must go out of the network port the radio answers on (Mac with Wi-Fi AND a USB network adapter)."""
import os, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, os.path.join(ROOT, "app"))
import hl2
sim = hl2.Hl2Sim(port=0)
calls = []
real_bound = hl2._bound_socket
hl2._interfaces = lambda: [("wifi0", "192.168.1.5", None), ("usbeth0", "169.254.7.7", None)]     # two network ports
def bound(name):
    calls.append(name); return real_bound("lo" if name else name)
hl2._bound_socket = bound
try:
    cl = hl2.Hl2Client("127.0.0.1", port=sim.port, rate=48000, nrx=2)
    cl.start()
    time.sleep(0.5)
    assert calls, "the radio was never asked out of a chosen network port"
    assert all(c > 0 for c in cl.count), cl.count
    cl.stop()
    # one network port only: ordinary behaviour, no probing
    calls.clear(); hl2._interfaces = lambda: [("en0", "192.168.1.5", None)]
    cl = hl2.Hl2Client("127.0.0.1", port=sim.port, rate=48000, nrx=2); cl.start(); time.sleep(0.3)
    assert not calls and all(c > 0 for c in cl.count)
    cl.stop()
finally:
    sim.close()
print("PASS the HL2 stream uses the network port the radio answers on")
