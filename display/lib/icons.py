"""Lädt die AA-Icon-Frames aus icons.bin (roh, kein grosses Byte-Literal)."""
REFRESH_W = 48
BURST_W = 64
CHECK_W = 48
_rf = 48 * 48
_bf = 64 * 64
_cf = 48 * 48
try:
    _d = open("/lib/icons.bin", "rb").read()
except OSError:
    _d = open("lib/icons.bin", "rb").read()
_o = 0
REFRESH_FRAMES = tuple(_d[_o + i * _rf:_o + (i + 1) * _rf] for i in range(12)); _o += 12 * _rf
BURST_FRAMES = tuple(_d[_o + i * _bf:_o + (i + 1) * _bf] for i in range(12)); _o += 12 * _bf
CHECK = _d[_o:_o + _cf]
