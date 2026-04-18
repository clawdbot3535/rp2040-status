"""
RP2040 Zero Status LED - MicroPython
=====================================
Empfaengt Befehle ueber USB-Serial und steuert die WS2812B LED.

Protokoll (eine Zeile pro Befehl):
  WORKING    -> Blau (Claude arbeitet)
  INPUT      -> Gelb pulsierend (wartet auf Eingabe)
  PERMISSION -> Rot pulsierend (braucht Genehmigung)
  DONE       -> Gruen (fertig)
  OFF        -> LED aus

Waveshare RP2040-Zero: WS2812B auf GPIO16
"""

import sys
import time
import select
import neopixel
import machine

# --- Hardware ---
np = neopixel.NeoPixel(machine.Pin(16), 1)

# --- Farben (G, R, B) - WS2812B nutzt GRB-Reihenfolge ---
COLORS = {
    "WORKING":    (0, 0, 50),
    "INPUT":      (38, 50, 0),
    "PERMISSION": (0, 50, 0),
    "DONE":       (50, 0, 0),
    "OFF":        (0, 0, 0),
}

PULSE_MODES = {"INPUT", "PERMISSION"}

# --- State ---
mode = "OFF"

# --- Non-blocking stdin ---
poll = select.poll()
poll.register(sys.stdin, select.POLLIN)


def set_led(r, g, b):
    np[0] = (r, g, b)
    np.write()


def pulse_factor(t, period_ms=1500):
    """Dreiecks-Puls: 0.15 .. 1.0"""
    phase = (t % period_ms) / period_ms
    triangle = phase * 2 if phase < 0.5 else 2 - phase * 2
    return 0.15 + 0.85 * triangle


def startup_animation():
    """Kurzer Farbdurchlauf beim Boot."""
    for color in [(50, 0, 0), (0, 50, 0), (0, 0, 50), (50, 38, 0), (0, 0, 0)]:
        set_led(*color)
        time.sleep_ms(150)


def read_command():
    """Liest einen Befehl von USB-Serial (non-blocking)."""
    if poll.poll(0):
        try:
            line = sys.stdin.readline().strip().upper()
            if line in COLORS:
                return line
        except Exception:
            pass
    return None


# --- Main Loop ---
startup_animation()

while True:
    cmd = read_command()
    if cmd is not None:
        mode = cmd

    if mode in PULSE_MODES:
        base = COLORS[mode]
        f = pulse_factor(time.ticks_ms())
        set_led(int(base[0] * f), int(base[1] * f), int(base[2] * f))
    else:
        set_led(*COLORS.get(mode, (0, 0, 0)))

    time.sleep_ms(20)
