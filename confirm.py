#!/usr/bin/env python3
"""Confirm-from-device: sendet kuratierte Tastenfolgen an einen wartenden Agenten.
Getrennt von focus.py, weil dies Eingaben injiziert (zustandsaendernd, riskant)."""

import json
import os
import subprocess

_DEFAULTS = {"approve": ["y", "Enter"], "reject": ["n", "Enter"], "continue": ["Enter"]}
_KEYMAP_PATHS = (
    "keymap.json",
    os.path.expanduser("~/.config/rp2040-status/keymap.json"),
)


def _load_keymap() -> dict:
    for path in _KEYMAP_PATHS:
        try:
            with open(path) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            continue
    return {}


def is_enabled() -> bool:
    """Kill-Switch: default an."""
    return _load_keymap().get("enabled", True)


def resolve_keys(source, action):
    """Token-Sequenz fuer (source, action): source-spezifisch > '*' > Code-Default.
    Gibt immer eine Liste von Strings zurueck (ungueltige Keymap-Werte fallen durch)."""
    km = _load_keymap()
    for scope in (source, "*"):
        if scope and scope in km and isinstance(km[scope], dict) and action in km[scope]:
            val = km[scope][action]
            if isinstance(val, list) and all(isinstance(t, str) for t in val):
                return val
    return _DEFAULTS.get(action, [])


_VALID = ("approve", "reject", "continue")

# iTerm2-AppleScript: an die Session-GUID schreiben (write text haengt Newline an).
_ITERM2_WRITE = '''
on run argv
  set targetId to item 1 of argv
  set theText to item 2 of argv
  tell application "iTerm2"
    repeat with w in windows
      repeat with t in tabs of w
        repeat with s in sessions of t
          if (unique id of s) is targetId then
            tell s to write text theText
            return "ok"
          end if
        end repeat
      end repeat
    end repeat
  end tell
  return "notfound"
end run
'''

# Tokens, die KEINE literalen Zeichen sind (tmux-Tastennamen).
_SPECIAL = {"Enter", "Up", "Down", "Left", "Right", "Escape", "Space",
            "Tab", "BSpace", "C-c", "C-d", "Home", "End"}


def _iterm_payload(tokens):
    """Bildet eine Token-Sequenz auf einen iTerm2 'write text'-Payload ab.
    v1 unterstuetzt [literal..., 'Enter'] oder ['Enter']. Sonst None (uebersprungen)."""
    if tokens == ["Enter"]:
        return ""  # write text "" laesst iTerm2 ein blankes Newline (~Enter) senden
    if tokens and tokens[-1] == "Enter" and all(t not in _SPECIAL for t in tokens[:-1]):
        return "".join(tokens[:-1])
    return None


def _send_tmux(pane, tokens) -> bool:
    if not pane:
        return False
    try:
        r = subprocess.run(["tmux", "send-keys", "-t", pane, *tokens],
                           capture_output=True, text=True, timeout=5)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _send_iterm2(session_id, tokens) -> bool:
    if not session_id:
        return False
    payload = _iterm_payload(tokens)
    if payload is None:
        print("confirm: iTerm2 unterstuetzt diese Tokens in v1 nicht:", tokens)
        return False
    try:
        # "wNtMpK:GUID" -> "GUID" (iTerm2 unique id); ohne Doppelpunkt unveraendert.
        guid = session_id.split(":", 1)[1] if ":" in session_id else session_id
        r = subprocess.run(
            ["osascript", "-e", _ITERM2_WRITE, guid, payload],
            capture_output=True, text=True, timeout=5)
        return r.returncode == 0 and r.stdout.strip() == "ok"
    except (OSError, subprocess.SubprocessError):
        return False


def confirm_action(record, action) -> bool:
    """Sendet die fuer (source, action) konfigurierte Tastenfolge an das Agenten-Ziel.
    True bei erfolgreichem Senden, sonst False (no-op)."""
    if action not in _VALID:
        return False
    if not is_enabled():
        return False
    focus_obj = (record or {}).get("focus")
    if not focus_obj or not isinstance(focus_obj, dict):
        return False
    tokens = resolve_keys((record or {}).get("source"), action)
    if not tokens:
        return False
    backend = focus_obj.get("backend")
    if backend == "tmux":
        return _send_tmux(focus_obj.get("pane", ""), tokens)
    if backend == "iterm2":
        return _send_iterm2(focus_obj.get("session_id", ""), tokens)
    return False
