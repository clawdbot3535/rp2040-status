# tests/test_serial_link.py
import serial_link

class _Port:
    def __init__(self, vid, device): self.vid = vid; self.device = device

def test_find_device_matches_vid(monkeypatch):
    ports = [_Port(0x2E8A, "/dev/cu.led"), _Port(0x303A, "/dev/cu.display")]
    monkeypatch.setattr(serial_link, "_list_ports", lambda: ports)
    assert serial_link.find_device(0x303A) == "/dev/cu.display"
    assert serial_link.find_device(0x2E8A) == "/dev/cu.led"

def test_find_device_none_when_absent(monkeypatch):
    monkeypatch.setattr(serial_link, "_list_ports", lambda: [_Port(0x2E8A, "/dev/cu.led")])
    assert serial_link.find_device(0x303A) is None
