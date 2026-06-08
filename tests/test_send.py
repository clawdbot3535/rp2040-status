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
