#!/usr/bin/env python3
"""Confirm-from-device: sendet kuratierte Tastenfolgen an einen wartenden Agenten.
Getrennt von focus.py, weil dies Eingaben injiziert (zustandsaendernd, riskant)."""

import json
import os

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
    """Token-Sequenz fuer (source, action): source-spezifisch > '*' > Code-Default."""
    km = _load_keymap()
    for scope in (source, "*"):
        if scope and scope in km and isinstance(km[scope], dict) and action in km[scope]:
            return km[scope][action]
    return _DEFAULTS.get(action)
