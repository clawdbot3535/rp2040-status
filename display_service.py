#!/usr/bin/env python3
"""Display-Service — sendet die Session-Liste ans ESP32-S3-Touch-LCD und
verarbeitet Tap-Events (focus). Treibt KEINE LED (das macht broker.py)."""

import glob
import hashlib
import json
import os
from typing import List, Optional, Tuple

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
