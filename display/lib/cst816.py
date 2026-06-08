# display/lib/cst816.py — minimaler CST816T-Treiber (Register aus der C++-Referenz).
from machine import Pin, I2C
import time

ADDR = 0x15

class CST816:
    def __init__(self, sda=11, scl=10, rst=13, freq=400_000):
        self._rst = Pin(rst, Pin.OUT)
        self._rst.value(0); time.sleep_ms(10)
        self._rst.value(1); time.sleep_ms(50)
        self.i2c = I2C(0, sda=Pin(sda), scl=Pin(scl), freq=freq)

    def read(self):
        """Gibt (touched, x, y, gesture) zurueck. touched=False wenn kein Finger."""
        try:
            d = self.i2c.readfrom_mem(ADDR, 0x01, 6)
        except OSError:
            return (False, 0, 0, 0)
        gesture = d[0]
        fingers = d[1] & 0x0F
        if fingers == 0:
            return (False, 0, 0, gesture)
        x = ((d[2] & 0x0F) << 8) | d[3]
        y = ((d[4] & 0x0F) << 8) | d[5]
        return (True, x, y, gesture)
