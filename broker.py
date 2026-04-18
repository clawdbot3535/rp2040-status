#!/usr/bin/env python3
"""
RP2040 Status LED Broker — liest Session-Statusdateien
und sendet den hoechstprioren Status an den RP2040.

Usage:
    python3 broker.py          # Vordergrund
    python3 broker.py &        # Hintergrund

Prioritaet (hoch → niedrig):
    PERMISSION > INPUT > WORKING > DONE

Stale Sessions (>120s ohne Update) werden ignoriert.
"""

import glob
import json
import os
import sys
import time
from typing import List, Optional, Tuple

STATUS_DIR = "/tmp/rp2040-status"
CONFIG_FILE = os.path.join(STATUS_DIR, ".config")
BAUD = 115200
POLL_MS = 200
DEFAULT_STALE_SECONDS = 600

PRIORITY = {
    "PERMISSION": 4,
    "INPUT": 3,
    "WORKING": 2,
    "DONE": 1,
}


def find_device() -> Optional[str]:
    """Findet den RP2040 USB-Serial Port."""
    for pattern in ["/dev/cu.usbmodem*", "/dev/ttyACM*"]:
        devices = sorted(glob.glob(pattern))
        if devices:
            return devices[0]
    return None


def open_serial(device: str):
    """Oeffnet Serial-Verbindung (pyserial oder Fallback)."""
    try:
        import serial
        return serial.Serial(device, BAUD, timeout=1, dsrdtr=False)
    except ImportError:
        import subprocess
        subprocess.run(
            ["stty", "-f", device, str(BAUD)],
            capture_output=True, timeout=2,
        )
        return open(device, "w")


def send_to_device(conn, status: str) -> bool:
    """Sendet Status-String. Gibt False bei Schreibfehler zurueck."""
    try:
        if hasattr(conn, "write") and hasattr(conn, "in_waiting"):
            conn.write(f"{status}\n".encode())
        else:
            conn.write(f"{status}\n")
            conn.flush()
        return True
    except Exception:
        return False


def read_config() -> dict:
    """Liest Broker-Config (timeout on/off, stale seconds)."""
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def get_stale_seconds() -> Optional[int]:
    """Gibt Stale-Timeout zurueck, oder None wenn deaktiviert."""
    cfg = read_config()
    if not cfg.get("timeout_enabled", True):
        return None
    return cfg.get("stale_seconds", DEFAULT_STALE_SECONDS)


def read_all_sessions() -> List[Tuple[str, float]]:
    """Liest alle aktiven Session-Status."""
    if not os.path.isdir(STATUS_DIR):
        return []

    now = time.time()
    stale = get_stale_seconds()
    sessions = []

    for path in glob.glob(os.path.join(STATUS_DIR, "*")):
        if os.path.basename(path).startswith("."):
            continue
        try:
            with open(path) as f:
                data = json.load(f)
            status = data.get("status", "")
            ts = data.get("ts", 0)

            if stale is not None and now - ts > stale:
                os.remove(path)
                continue

            if status in PRIORITY:
                sessions.append((status, ts))
        except (json.JSONDecodeError, OSError):
            try:
                os.remove(path)
            except OSError:
                pass

    return sessions


def highest_priority(sessions: List[Tuple[str, float]]) -> str:
    """Waehlt den Status mit hoechster Prioritaet."""
    if not sessions:
        return "OFF"
    return max(sessions, key=lambda s: PRIORITY.get(s[0], 0))[0]


def main() -> None:
    print(f"RP2040 Status Broker gestartet (poll: {POLL_MS}ms, stale: {DEFAULT_STALE_SECONDS}s)")
    os.makedirs(STATUS_DIR, exist_ok=True)

    conn = None
    last_status = None
    last_device_check = 0

    while True:
        now = time.time()

        # Device-Check alle 5s (nicht bei jedem Poll)
        if conn is None and now - last_device_check > 5:
            device = find_device()
            if device:
                try:
                    conn = open_serial(device)
                    last_status = None  # erzwinge Resend nach Reconnect
                    print(f"Verbunden: {device}")
                except Exception as e:
                    print(f"Verbindungsfehler: {e}")
                    conn = None
            last_device_check = now

        # Status evaluieren
        sessions = read_all_sessions()
        status = highest_priority(sessions)

        # Nur senden wenn sich Status geaendert hat
        if status != last_status:
            send_ok = True
            if conn:
                send_ok = send_to_device(conn, status)
                if not send_ok:
                    try:
                        conn.close()
                    except Exception:
                        pass
                    conn = None
                    last_device_check = 0  # sofortiger Reconnect-Versuch
                    print(f"✗ Schreibfehler bei '{status}' — Reconnect erzwungen")
            if send_ok:
                last_status = status
                active = len(sessions)
                print(f"→ {status} ({active} aktive Session{'s' if active != 1 else ''})")

        time.sleep(POLL_MS / 1000)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nBroker beendet.")
        sys.exit(0)
