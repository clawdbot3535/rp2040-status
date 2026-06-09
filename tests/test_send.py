# tests/test_send.py
import json, os

def test_working_writes_enriched_fields(tmp_path, monkeypatch):
    import send; monkeypatch.setattr(send, "STATUS_DIR", str(tmp_path))
    monkeypatch.setenv("ITERM_SESSION_ID", "w0t1p0:UUID-1")
    monkeypatch.setattr(send, "resolve_branch", lambda cwd: "main")
    send.write_status("abc", "WORKING", "claude-code",
                      project="rp2040-status", branch="main",
                      title="", focus={"backend": "iterm2", "session_id": "w0t1p0:UUID-1"})
    with open(os.path.join(str(tmp_path), "claude-code-abc")) as f:
        rec = json.load(f)
    assert rec["id"] == "abc"
    assert rec["project"] == "rp2040-status"
    assert rec["branch"] == "main"
    assert rec["focus"] == {"backend": "iterm2", "session_id": "w0t1p0:UUID-1"}

def test_done_preserves_sticky_fields(tmp_path, monkeypatch):
    import send; monkeypatch.setattr(send, "STATUS_DIR", str(tmp_path))
    send.write_status("abc", "WORKING", "claude-code",
                      project="rp2040-status", branch="main", title="x",
                      focus={"backend": "iterm2", "session_id": "S1"})
    send.write_status("abc", "DONE", "claude-code",
                      project="", branch=None, title="", focus=None)
    with open(os.path.join(str(tmp_path), "claude-code-abc")) as f:
        rec = json.load(f)
    assert rec["status"] == "DONE"
    assert rec["project"] == "rp2040-status"
    assert rec["branch"] == "main"
    assert rec["focus"] == {"backend": "iterm2", "session_id": "S1"}

def test_write_status_leaves_no_temp_files(tmp_path, monkeypatch):
    import send, os
    monkeypatch.setattr(send, "STATUS_DIR", str(tmp_path))
    send.write_status("abc", "WORKING", "claude-code",
                      project="p", branch="main", title="", focus=None)
    names = os.listdir(str(tmp_path))
    assert names == ["claude-code-abc"]  # genau die Zieldatei, kein .tmp-*

def test_update_all_preserves_enriched_fields(tmp_path, monkeypatch):
    import send; monkeypatch.setattr(send, "STATUS_DIR", str(tmp_path))
    send.write_status("abc", "WORKING", "claude-code",
                      project="rp2040-status", branch="main", title="t",
                      focus={"backend": "iterm2", "session_id": "S1"})
    send.update_all_sessions("DONE")
    import json, os
    with open(os.path.join(str(tmp_path), "claude-code-abc")) as f:
        rec = json.load(f)
    assert rec["status"] == "DONE"
    assert rec["project"] == "rp2040-status"
    assert rec["branch"] == "main"
    assert rec["focus"] == {"backend": "iterm2", "session_id": "S1"}

def test_resolve_focus_tmux_when_in_pane(monkeypatch):
    import send
    monkeypatch.setattr(send, "_tmux_pane_for_self", lambda: "%7")
    monkeypatch.setenv("ITERM_SESSION_ID", "w0t1p0:GUID")
    assert send.resolve_focus() == {
        "backend": "tmux", "pane": "%7", "iterm_session": "w0t1p0:GUID"}

def test_resolve_focus_iterm2_when_not_in_tmux(monkeypatch):
    import send
    monkeypatch.setattr(send, "_tmux_pane_for_self", lambda: None)
    monkeypatch.setenv("ITERM_SESSION_ID", "w0t1p0:GUID")
    assert send.resolve_focus() == {"backend": "iterm2", "session_id": "w0t1p0:GUID"}

def test_resolve_focus_none_when_nothing(monkeypatch):
    import send
    monkeypatch.setattr(send, "_tmux_pane_for_self", lambda: None)
    monkeypatch.delenv("ITERM_SESSION_ID", raising=False)
    assert send.resolve_focus() is None

def test_resolve_path_abbreviates_home(monkeypatch):
    import send
    monkeypatch.setenv("HOME", "/Users/me")
    assert send.resolve_path("/Users/me/Projects/foo") == "~/Projects/foo"
    assert send.resolve_path("/Users/me") == "~"
    assert send.resolve_path("/etc/bar") == "/etc/bar"
    assert send.resolve_path("") == ""

def test_write_status_stores_and_preserves_path(tmp_path, monkeypatch):
    import send; monkeypatch.setattr(send, "STATUS_DIR", str(tmp_path))
    send.write_status("abc", "WORKING", "claude-code", project="foo",
                      work_path="~/Projects/foo")
    send.write_status("abc", "DONE", "claude-code")  # kein Pfad geliefert -> sticky
    with open(os.path.join(str(tmp_path), "claude-code-abc")) as f:
        rec = json.load(f)
    assert rec["path"] == "~/Projects/foo"
