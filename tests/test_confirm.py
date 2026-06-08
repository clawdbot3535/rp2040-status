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


def _rec(focus, source="codex"):
    return {"source": source, "focus": focus}

def test_confirm_action_tmux_sends_keys(monkeypatch):
    monkeypatch.setattr(confirm, "_load_keymap", lambda: {})
    calls = {}
    def fake_run(cmd, **kw):
        calls["cmd"] = cmd
        class R: returncode = 0; stdout = "ok"
        return R()
    monkeypatch.setattr(confirm.subprocess, "run", fake_run)
    ok = confirm.confirm_action(_rec({"backend": "tmux", "pane": "%5"}), "approve")
    assert ok is True
    assert calls["cmd"] == ["tmux", "send-keys", "-t", "%5", "y", "Enter"]

def test_confirm_action_iterm2_write_text(monkeypatch):
    monkeypatch.setattr(confirm, "_load_keymap", lambda: {})
    calls = {}
    def fake_run(cmd, **kw):
        calls["cmd"] = cmd
        class R: returncode = 0; stdout = "ok"
        return R()
    monkeypatch.setattr(confirm.subprocess, "run", fake_run)
    ok = confirm.confirm_action(
        _rec({"backend": "iterm2", "session_id": "w0t1p0:GUID-7"}), "reject")
    assert ok is True
    assert calls["cmd"][0] == "osascript"
    assert calls["cmd"][-2] == "GUID-7"
    assert calls["cmd"][-1] == "n"

def test_confirm_action_continue_iterm2_empty_payload(monkeypatch):
    monkeypatch.setattr(confirm, "_load_keymap", lambda: {})
    captured = {}
    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        class R: returncode = 0; stdout = "ok"
        return R()
    monkeypatch.setattr(confirm.subprocess, "run", fake_run)
    ok = confirm.confirm_action(
        _rec({"backend": "iterm2", "session_id": "x:y"}), "continue")
    assert ok is True
    assert captured["cmd"][-1] == ""

def test_confirm_action_invalid_action_noop():
    assert confirm.confirm_action(_rec({"backend": "tmux", "pane": "%1"}), "delete") is False

def test_confirm_action_kill_switch(monkeypatch):
    monkeypatch.setattr(confirm, "_load_keymap", lambda: {"enabled": False})
    assert confirm.confirm_action(_rec({"backend": "tmux", "pane": "%1"}), "approve") is False

def test_confirm_action_no_focus_noop(monkeypatch):
    monkeypatch.setattr(confirm, "_load_keymap", lambda: {})
    assert confirm.confirm_action({"source": "codex", "focus": None}, "approve") is False

def test_iterm_payload_unsupported_special_keys(monkeypatch):
    monkeypatch.setattr(confirm, "_load_keymap",
                        lambda: {"*": {"approve": ["Up", "Enter"]}})
    flag = {"ran": False}
    def fake_run(cmd, **kw):
        flag["ran"] = True
        class R: returncode = 0; stdout = "ok"
        return R()
    monkeypatch.setattr(confirm.subprocess, "run", fake_run)
    ok = confirm.confirm_action(
        {"source": "codex", "focus": {"backend": "iterm2", "session_id": "x:y"}}, "approve")
    assert ok is False and flag["ran"] is False
