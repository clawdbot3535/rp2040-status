# tests/test_focus.py
import focus

def test_dispatch_iterm2_calls_osascript(monkeypatch):
    calls = {}
    def fake_run(cmd, **kw):
        calls["cmd"] = cmd
        class R:
            returncode = 0
            stdout = "ok"
        return R()
    monkeypatch.setattr(focus.subprocess, "run", fake_run)
    ok = focus.focus_session({"backend": "iterm2", "session_id": "w0t1p0:GUID-9"})
    assert ok is True
    assert calls["cmd"][0] == "osascript"
    assert calls["cmd"][-1] == "GUID-9"   # GUID is the bare last argv element

def test_missing_focus_is_noop():
    assert focus.focus_session(None) is False
    assert focus.focus_session({}) is False

def test_unknown_backend_is_noop():
    assert focus.focus_session({"backend": "nope"}) is False

def test_osascript_failure_returns_false(monkeypatch):
    def fake_run(cmd, **kw):
        class R: returncode = 1
        return R()
    monkeypatch.setattr(focus.subprocess, "run", fake_run)
    assert focus.focus_session({"backend": "iterm2", "session_id": "x:y"}) is False

def test_dispatch_tmux_selects_pane(monkeypatch):
    calls = []
    def fake_run(cmd, **kw):
        calls.append(cmd)
        class R:
            returncode = 0
            stdout = "ok"
        return R()
    monkeypatch.setattr(focus.subprocess, "run", fake_run)
    ok = focus.focus_session({"backend": "tmux", "pane": "%3", "iterm_session": "w0t1p0:G"})
    assert ok is True
    assert any(c[:2] == ["tmux", "select-pane"] and "%3" in c for c in calls)

def test_tmux_missing_pane_is_noop():
    assert focus.focus_session({"backend": "tmux"}) is False
    assert focus.focus_session({"backend": "tmux", "pane": ""}) is False

def test_iterm2_notfound_returns_false(monkeypatch):
    def fake_run(cmd, **kw):
        class R:
            returncode = 0
            stdout = "notfound"
        return R()
    monkeypatch.setattr(focus.subprocess, "run", fake_run)
    assert focus.focus_session({"backend": "iterm2", "session_id": "x:y"}) is False
