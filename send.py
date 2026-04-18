#!/usr/bin/env python3
"""
Schreibt Session-Status in /tmp/rp2040-status/.

Usage:
    # Aus Hooks (liest session_id aus stdin-JSON):
    echo '{"session_id":"abc"}' | python3 send.py WORKING

    # Manuell testen:
    python3 send.py WORKING
    python3 send.py INPUT
    python3 send.py PERMISSION
    python3 send.py DONE
    python3 send.py OFF

Der broker.py Daemon liest die Statusdateien und sendet
den hoechstprioren Status an den RP2040.
"""

import glob
import json
import os
import sys
import time

VALID = {"WORKING", "INPUT", "PERMISSION", "DONE", "OFF"}
STATUS_DIR = "/tmp/rp2040-status"
CONFIG_FILE = os.path.join(STATUS_DIR, ".config")


def read_session_id() -> str:
    """Liest session_id aus stdin-JSON (Hook-Input)."""
    try:
        if not sys.stdin.isatty():
            data = json.loads(sys.stdin.read())
            return data.get("session_id", "manual")
    except Exception:
        pass
    return "manual"


def update_all_sessions(status: str) -> None:
    """Aktualisiert alle existierenden Session-Dateien auf neuen Status."""
    if not os.path.isdir(STATUS_DIR):
        return
    now = time.time()
    for path in glob.glob(os.path.join(STATUS_DIR, "*")):
        if os.path.basename(path).startswith("."):
            continue
        try:
            with open(path, "w") as f:
                json.dump({"status": status, "ts": now}, f)
        except OSError:
            pass


def write_status(session_id: str, status: str) -> None:
    """Schreibt Status-Datei fuer diese Session."""
    os.makedirs(STATUS_DIR, exist_ok=True)
    path = os.path.join(STATUS_DIR, session_id)

    if status == "OFF":
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        return

    with open(path, "w") as f:
        json.dump({"status": status, "ts": time.time()}, f)


def set_timeout(enabled: bool) -> None:
    """Schaltet Stale-Timeout ein/aus."""
    os.makedirs(STATUS_DIR, exist_ok=True)
    cfg = {}
    try:
        with open(CONFIG_FILE) as f:
            cfg = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    cfg["timeout_enabled"] = enabled
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f)
    print(f"Timeout {'ON (600s)' if enabled else 'OFF'}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <{'|'.join(sorted(VALID))}|TIMEOUT-ON|TIMEOUT-OFF>")
        sys.exit(1)

    cmd = sys.argv[1].upper()

    if cmd == "TIMEOUT-ON":
        set_timeout(True)
        sys.exit(0)
    elif cmd == "TIMEOUT-OFF":
        set_timeout(False)
        sys.exit(0)

    if cmd not in VALID:
        print(f"Unknown: {cmd}. Valid: {', '.join(sorted(VALID))}, TIMEOUT-ON, TIMEOUT-OFF")
        sys.exit(1)

    if "--all" in sys.argv:
        update_all_sessions(cmd)
    else:
        sid = sys.argv[2] if len(sys.argv) > 2 else read_session_id()
        write_status(sid, cmd)
