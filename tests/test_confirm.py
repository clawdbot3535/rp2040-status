# tests/test_confirm.py
import confirm

def test_resolve_keys_default(monkeypatch):
    monkeypatch.setattr(confirm, "_load_keymap", lambda: {})
    assert confirm.resolve_keys("codex", "approve") == ["y", "Enter"]
    assert confirm.resolve_keys("codex", "reject") == ["n", "Enter"]
    assert confirm.resolve_keys("codex", "continue") == ["Enter"]

def test_resolve_keys_star_override(monkeypatch):
    monkeypatch.setattr(confirm, "_load_keymap",
                        lambda: {"*": {"approve": ["1", "Enter"]}})
    assert confirm.resolve_keys("codex", "approve") == ["1", "Enter"]
    assert confirm.resolve_keys("codex", "reject") == ["n", "Enter"]

def test_resolve_keys_source_beats_star(monkeypatch):
    monkeypatch.setattr(confirm, "_load_keymap", lambda: {
        "claude-code": {"approve": ["2", "Enter"]},
        "*": {"approve": ["y", "Enter"]}})
    assert confirm.resolve_keys("claude-code", "approve") == ["2", "Enter"]
    assert confirm.resolve_keys("codex", "approve") == ["y", "Enter"]

def test_is_enabled_default_true(monkeypatch):
    monkeypatch.setattr(confirm, "_load_keymap", lambda: {})
    assert confirm.is_enabled() is True

def test_is_enabled_kill_switch(monkeypatch):
    monkeypatch.setattr(confirm, "_load_keymap", lambda: {"enabled": False})
    assert confirm.is_enabled() is False

def test_resolve_keys_unknown_action_returns_empty(monkeypatch):
    monkeypatch.setattr(confirm, "_load_keymap", lambda: {})
    assert confirm.resolve_keys("codex", "bogus") == []

def test_resolve_keys_invalid_value_falls_back(monkeypatch):
    # nicht-Listen-Wert aus hand-editierter keymap.json -> Default greift
    monkeypatch.setattr(confirm, "_load_keymap", lambda: {"*": {"approve": "y"}})
    assert confirm.resolve_keys("codex", "approve") == ["y", "Enter"]
