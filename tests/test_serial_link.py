# tests/test_serial_link.py
import serial_link

class _Port:
    def __init__(self, vid, device, pid=None):
        self.vid = vid; self.device = device; self.pid = pid

def test_find_device_matches_vid(monkeypatch):
    ports = [_Port(0x2E8A, "/dev/cu.led"), _Port(0x303A, "/dev/cu.display")]
    monkeypatch.setattr(serial_link, "_list_ports", lambda: ports)
    assert serial_link.find_device(0x303A) == "/dev/cu.display"
    assert serial_link.find_device(0x2E8A) == "/dev/cu.led"

def test_find_device_none_when_absent(monkeypatch):
    monkeypatch.setattr(serial_link, "_list_ports", lambda: [_Port(0x2E8A, "/dev/cu.led")])
    assert serial_link.find_device(0x303A) is None

def test_find_device_pid_filter_skips_other_device_with_same_vid(monkeypatch):
    # Reboot-Szenario: zwei Espressif-Geraete, JTAG-Debug-Unit sortiert vor dem
    # Touch-LCD. Ohne PID-Filter griffe find_device das falsche Geraet.
    ports = [
        _Port(0x303A, "/dev/cu.usbmodem1133301", pid=0x1001),   # fremdes Board (JTAG)
        _Port(0x303A, "/dev/cu.usbmodem11334201", pid=0x4001),  # Touch-LCD (CDC)
    ]
    monkeypatch.setattr(serial_link, "_list_ports", lambda: ports)
    assert serial_link.find_device(0x303A, pid=0x4001) == "/dev/cu.usbmodem11334201"

def test_find_device_pid_filter_none_when_pid_absent(monkeypatch):
    ports = [_Port(0x303A, "/dev/cu.usbmodem1133301", pid=0x1001)]
    monkeypatch.setattr(serial_link, "_list_ports", lambda: ports)
    assert serial_link.find_device(0x303A, pid=0x4001) is None

def test_find_device_without_pid_keeps_old_behavior(monkeypatch):
    ports = [_Port(0x303A, "/dev/cu.b", pid=0x4001), _Port(0x303A, "/dev/cu.a", pid=0x1001)]
    monkeypatch.setattr(serial_link, "_list_ports", lambda: ports)
    assert serial_link.find_device(0x303A) == "/dev/cu.a"


class _FakeConn:
    def __init__(self):
        self.is_open = True
        self.written = []
    def write(self, b):
        self.written.append(b)
    def close(self):
        self.is_open = False

def test_is_open_reflects_conn_state():
    link = serial_link.SerialLink()
    assert link.is_open() is False
    fake = _FakeConn()
    link._conn = fake
    assert link.is_open() is True
    fake.is_open = False
    assert link.is_open() is False

def test_write_line_encodes_and_appends_newline():
    link = serial_link.SerialLink()
    fake = _FakeConn()
    link._conn = fake
    link.write_line("hello")
    assert fake.written == [b"hello\n"]

def test_write_line_raises_when_closed():
    import pytest
    link = serial_link.SerialLink()
    with pytest.raises(RuntimeError):
        link.write_line("hi")
