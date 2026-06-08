#!/usr/bin/env python3
"""
Schreibt Session-Status in /tmp/rp2040-status/.

Usage:
    # Claude Code (Hook liefert JSON via stdin):
    echo '{"session_id":"abc"}' | python3 send.py WORKING

    # Codex CLI (Hook in ~/.codex/hooks.json liefert JSON via stdin):
    echo '{"session_id":"abc","turn_id":"t1"}' | python3 send.py WORKING --source codex

    # Antigravity oder beliebige Tools via Env-Vars:
    RP2040_SOURCE=antigravity RP2040_SESSION_ID=$AG_SESSION python3 send.py INPUT

    # Explizit ueber Flags:
    python3 send.py WORKING --session abc --source codex

    # Manuell:
    python3 send.py WORKING
    python3 send.py OFF

    # Konfiguration:
    python3 send.py TIMEOUT-ON
    python3 send.py TIMEOUT-OFF

Der broker.py Daemon liest die Status-Dateien und sendet
den hoechstprioren Status an den RP2040.

Aufloesungs-Reihenfolge fuer session_id:
    --session > positional > $RP2040_SESSION_ID > stdin JSON > "manual"

Aufloesungs-Reihenfolge fuer source:
    --source > $RP2040_SOURCE > stdin-Heuristik (Codex turn_id, Claude Code) > "unknown"
"""

import argparse
import glob
import json
import os
import subprocess
import sys
import time
from typing import Optional

VALID = {"WORKING", "INPUT", "PERMISSION", "DONE", "OFF"}
STATUS_DIR = "/tmp/rp2040-status"
CONFIG_FILE = os.path.join(STATUS_DIR, ".config")
CODEX_HOOK_KEYS = {"turn_id"}
CLAUDE_CODE_HOOK_KEYS = {"transcript_path", "hook_event_name"}


def read_stdin_json() -> dict:
    """Liest stdin als JSON. Gibt {} bei TTY oder Fehler zurueck."""
    if sys.stdin.isatty():
        return {}
    try:
        return json.loads(sys.stdin.read())
    except (json.JSONDecodeError, OSError):
        return {}


def resolve_session_id(explicit: Optional[str], stdin_data: dict) -> str:
    if explicit:
        return explicit
    env_sid = os.environ.get("RP2040_SESSION_ID")
    if env_sid:
        return env_sid
    for key in ("session_id", "sessionId", "id"):
        if key in stdin_data:
            return str(stdin_data[key])
    return "manual"


def resolve_source(explicit: Optional[str], stdin_data: dict) -> str:
    if explicit:
        return explicit
    env_src = os.environ.get("RP2040_SOURCE")
    if env_src:
        return env_src
    # Codex hooks send turn_id (Codex extension over the Claude Code schema).
    if any(k in stdin_data for k in CODEX_HOOK_KEYS):
        return "codex"
    if any(k in stdin_data for k in CLAUDE_CODE_HOOK_KEYS):
        return "claude-code"
    if "session_id" in stdin_data:
        return "claude-code"
    return "unknown"


def session_path(session_id: str, source: str) -> str:
    """Datei-Pfad mit Source-Prefix fuer Isolation zwischen Tools."""
    if source and source != "unknown":
        fname = f"{source}-{session_id}"
    else:
        fname = session_id
    return os.path.join(STATUS_DIR, fname)


def resolve_project(cwd: str) -> str:
    return os.path.basename(os.path.normpath(cwd)) if cwd else ""


def resolve_branch(cwd: str) -> str:
    if not cwd:
        return ""
    try:
        out = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=2,
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def resolve_focus() -> Optional[dict]:
    sid = os.environ.get("ITERM_SESSION_ID")
    if sid:
        return {"backend": "iterm2", "session_id": sid}
    return None


def _read_existing(path: str) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def write_status(session_id: str, status: str, source: str,
                 project: str = "", branch: Optional[str] = None, title: str = "",
                 focus: Optional[dict] = None) -> None:
    """Schreibt/merged Status-Datei. status/ts immer neu; project/branch/title/focus
    werden beibehalten, wenn das neue Event sie nicht liefert."""
    os.makedirs(STATUS_DIR, exist_ok=True)
    path = session_path(session_id, source)

    if status == "OFF":
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        return

    old = _read_existing(path)

    def pick(new, key):
        return new if new else old.get(key, "")

    record = {
        "status": status,
        "ts": time.time(),
        "source": source or old.get("source", "") or "unknown",
        "id": session_id,
        "project": pick(project, "project"),
        "branch": pick(branch, "branch"),
        "title": pick(title, "title"),
        "focus": focus if focus else old.get("focus"),
    }
    with open(path, "w") as f:
        json.dump(record, f)


def update_all_sessions(status: str) -> None:
    """Aktualisiert alle existierenden Session-Dateien auf neuen Status."""
    if not os.path.isdir(STATUS_DIR):
        return
    now = time.time()
    for path in glob.glob(os.path.join(STATUS_DIR, "*")):
        if os.path.basename(path).startswith("."):
            continue
        try:
            old = _read_existing(path)
            record = {**old, "status": status, "ts": now, "source": old.get("source", "unknown")}
            with open(path, "w") as f:
                json.dump(record, f)
        except OSError:
            pass


def set_timeout(enabled: bool) -> None:
    """Schaltet Stale-Timeout ein/aus."""
    os.makedirs(STATUS_DIR, exist_ok=True)
    cfg: dict = {}
    try:
        with open(CONFIG_FILE) as f:
            cfg = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    cfg["timeout_enabled"] = enabled
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f)
    print(f"Timeout {'ON (600s)' if enabled else 'OFF'}")


def parse_args(argv) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="send.py",
        description="Status an den RP2040 Status LED Broker senden.",
    )
    p.add_argument(
        "status",
        help=f"{', '.join(sorted(VALID))}, TIMEOUT-ON, TIMEOUT-OFF",
    )
    p.add_argument(
        "session_pos",
        nargs="?",
        default=None,
        help="Session ID (positional, Backwards-Compat).",
    )
    p.add_argument("--session", default=None, help="Session ID (explicit).")
    p.add_argument(
        "--source",
        default=None,
        help="Quelle: claude-code | codex | antigravity | <name>.",
    )
    p.add_argument(
        "--all",
        action="store_true",
        help="Alle aktiven Sessions auf neuen Status setzen.",
    )
    p.add_argument("--title", default="", help="Optionaler Kurztitel fuer die Session.")
    return p.parse_args(argv)


def main() -> int:
    args = parse_args(sys.argv[1:])
    cmd = args.status.upper()

    if cmd == "TIMEOUT-ON":
        set_timeout(True)
        return 0
    if cmd == "TIMEOUT-OFF":
        set_timeout(False)
        return 0

    if cmd not in VALID:
        print(
            f"Unknown: {cmd}. Valid: {', '.join(sorted(VALID))}, TIMEOUT-ON, TIMEOUT-OFF",
            file=sys.stderr,
        )
        return 1

    if args.all:
        update_all_sessions(cmd)
        return 0

    stdin_data = read_stdin_json()
    explicit_sid = args.session or args.session_pos
    sid = resolve_session_id(explicit_sid, stdin_data)
    source = resolve_source(args.source, stdin_data)
    cwd = stdin_data.get("cwd") or os.environ.get("PWD", "")
    project = resolve_project(cwd)
    branch = resolve_branch(cwd) if cmd == "WORKING" else None
    title = args.title or ""
    focus = resolve_focus()

    write_status(sid, cmd, source, project=project, branch=branch,
                 title=title, focus=focus)
    return 0


if __name__ == "__main__":
    sys.exit(main())
