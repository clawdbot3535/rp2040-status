# display/boot.py — laeuft VOR main.py. Haelt die Board-Stromversorgung (SYS_EN).
from machine import Pin

# Waveshare ESP32-S3-Touch-LCD-1.69: SYS_EN = GPIO41, HIGH = Power gehalten.
_sys_en = Pin(41, Pin.OUT)
_sys_en.value(1)
