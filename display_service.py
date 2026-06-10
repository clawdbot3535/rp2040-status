#!/usr/bin/env python3
"""Display-Service — sendet die Session-Liste ans ESP32-S3-Touch-LCD und
verarbeitet Tap-Events (focus). Treibt KEINE LED (das macht broker.py)."""

import glob
import hashlib
import json
import os
import time
from typing import List, Optional, Tuple

from focus import focus_session
from confirm import confirm_action
from serial_link import SerialLink, find_device

STATUS_DIR = "/tmp/rp2040-status"
CONFIG_FILE = os.path.join(STATUS_DIR, ".config")
POLL_MS = 200
DEFAULT_STALE_SECONDS = 600
ESP32S3_VID = 0x303A  # Espressif — Touch-LCD


def derive_key(path: str) -> str:
    """Kurzer, stabiler Schluessel aus dem Dateinamen (Transport-Detail)."""
    base = os.path.basename(path)
    return hashlib.sha1(base.encode()).hexdigest()[:6]


def _sanitize(value) -> str:
    """| und Zeilenumbrueche raus — sie sind Protokoll-Trenner."""
    return str(value or "").replace("|", "/").replace("\n", " ").replace("\r", " ")


def read_sessions(status_dir: str, stale_seconds: Optional[float], now: float) -> List[Tuple[str, dict]]:
    """Liste von (path, record). Filtert stale, loescht NICHTS."""
    if not os.path.isdir(status_dir):
        return []
    out = []
    for path in glob.glob(os.path.join(status_dir, "*")):
        if os.path.basename(path).startswith("."):
            continue
        try:
            with open(path) as f:
                rec = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        ts = rec.get("ts", 0)
        if stale_seconds is not None and now - ts > stale_seconds:
            continue
        out.append((path, rec))
    return out


def build_frame(sessions: List[Tuple[str, dict]]) -> Tuple[str, dict]:
    """Baut den LIST-Frame-String + key->path-Map. Neueste Session zuerst."""
    sessions = sorted(sessions, key=lambda pr: pr[1].get("ts", 0), reverse=True)
    lines = [f"LIST {len(sessions)}"]
    key_map = {}
    for path, rec in sessions:
        key = derive_key(path)
        if key in key_map and key_map[key] != path:
            # 6-Hex-Kollision: auf vollen Hash erweitern (deterministisch, eindeutig).
            key = hashlib.sha1(os.path.basename(path).encode()).hexdigest()
        key_map[key] = path
        row = "|".join([
            key,
            _sanitize(rec.get("status", "")),
            _sanitize(rec.get("source", "")),
            _sanitize(rec.get("project", "")),
            _sanitize(rec.get("branch", "")),
            _sanitize(rec.get("title", "")),
            _sanitize(rec.get("path", "")),
        ])
        lines.append(f"S {row}")
    lines.append("END")
    return "\n".join(lines), key_map


# Bewusst dupliziert aus broker.py: broker.py bleibt per Design unveraendert.
def read_config() -> dict:
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def get_stale_seconds():
    cfg = read_config()
    if not cfg.get("timeout_enabled", True):
        return None
    return cfg.get("stale_seconds", DEFAULT_STALE_SECONDS)


def _read_focus(path: str):
    try:
        with open(path) as f:
            return json.load(f).get("focus")
    except (json.JSONDecodeError, OSError):
        return None


def _read_record(path: str):
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _bump_working(path: str, rec: dict) -> None:
    """Setzt die Session nach einer Bestaetigung sofort auf WORKING (Felder bleiben).
    Sonst klebt PERMISSION, bis der Agent zufaellig wieder einen Hook feuert."""
    rec = dict(rec)
    rec["status"] = "WORKING"
    rec["ts"] = time.time()
    tmp = path + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(rec, f)
        os.replace(tmp, path)
    except OSError:
        pass


def handle_incoming(line: str, key_map: dict) -> bool:
    """Verarbeitet eine Zeile vom Display. Gibt True zurueck, wenn ein Resend
    erzwungen werden soll (z.B. nach 'ready')."""
    line = line.strip()
    if line == "ready":
        return True
    if line.startswith("focus "):
        key = line[len("focus "):].strip()
        path = key_map.get(key)
        if path:
            focus_session(_read_focus(path))
    if line.startswith("act "):
        parts = line.split()
        if len(parts) == 3:
            key, action = parts[1], parts[2]
            path = key_map.get(key)
            if path:
                rec = _read_record(path)
                if confirm_action(rec, action) and rec:
                    # Sofortiges Feedback: PERMISSION -> WORKING + Resend erzwingen.
                    _bump_working(path, rec)
                    return True
    return False


def main() -> None:
    print(f"Display-Service gestartet (poll: {POLL_MS}ms)")
    os.makedirs(STATUS_DIR, exist_ok=True)
    link = SerialLink()
    last_frame = None
    key_map = {}
    last_device_check = 0

    try:
        while True:
            now = time.time()

            if not link.is_open() and now - last_device_check > 5:
                device = find_device(ESP32S3_VID)
                if device:
                    try:
                        link.open(device)
                        last_frame = None  # Resend nach (Re)connect
                        print(f"Display verbunden: {device}")
                    except Exception as e:
                        print(f"Verbindungsfehler: {e}")
                last_device_check = now

            # key_map stammt aus dem zuletzt gesendeten Frame (eine Iteration alt) —
            # genau der Frame, den das Display gerade zeigt, also passt der Tap-Key.
            if link.is_open():
                try:
                    for line in link.read_lines():
                        if handle_incoming(line, key_map):
                            last_frame = None
                except Exception as e:
                    print(f"Lesefehler — Reconnect erzwungen: {e}")
                    link.close()
                    last_device_check = 0

            frame, key_map = build_frame(read_sessions(STATUS_DIR, get_stale_seconds(), now))
            if frame != last_frame and link.is_open():
                try:
                    link.write_line(frame)
                    last_frame = frame
                except Exception:
                    link.close()
                    last_device_check = 0
                    print("Schreibfehler — Reconnect erzwungen")

            time.sleep(POLL_MS / 1000)
    finally:
        link.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nDisplay-Service beendet.")
