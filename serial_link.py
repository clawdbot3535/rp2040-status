#!/usr/bin/env python3
"""USB-Serial-Link mit VID-Discovery. Schnittstelle bewusst transport-neutral,
damit spaeter ein ble_link.py mit gleicher API (open/read_lines/write_line/close)
andocken kann."""

import serial
from serial.tools import list_ports

_READ_CHUNK = 256


def _list_ports():
    return list(list_ports.comports())


def find_device(vid: int, pid: int = None):
    """Erstes Geraet mit passender USB-Vendor-ID (und optional Product-ID), oder None.

    Der PID-Filter ist noetig, sobald mehrere Boards desselben Herstellers
    stecken: ein ESP32-S3 im JTAG-Modus (PID 0x1001) hat dieselbe VID wie
    einer im OTG/CDC-Modus (PID 0x4001)."""
    matches = sorted(
        p.device
        for p in _list_ports()
        if getattr(p, "vid", None) == vid
        and (pid is None or getattr(p, "pid", None) == pid)
    )
    return matches[0] if matches else None


class SerialLink:
    """Duenne, zeilenbasierte Serial-Verbindung. Reconnect macht der Aufrufer."""

    def __init__(self, baud: int = 115200):
        self.baud = baud
        self._conn = None
        self._buf = b""

    def open(self, device: str) -> None:
        self.close()
        self._conn = serial.Serial(device, self.baud, timeout=0, dsrdtr=False)
        self._buf = b""

    def is_open(self) -> bool:
        return self._conn is not None and self._conn.is_open

    def write_line(self, text: str) -> None:
        if self._conn is None:
            raise RuntimeError("write_line called on closed SerialLink")
        self._conn.write((text + "\n").encode())

    def read_lines(self):
        """Nicht-blockierend: liefert komplette Zeilen seit dem letzten Aufruf."""
        if self._conn is None:
            return
        self._buf += self._conn.read(_READ_CHUNK)
        while b"\n" in self._buf:
            line, self._buf = self._buf.split(b"\n", 1)
            yield line.decode(errors="replace").strip()

    def close(self) -> None:
        try:
            if self._conn:
                self._conn.close()
        except Exception:
            pass
        self._conn = None
