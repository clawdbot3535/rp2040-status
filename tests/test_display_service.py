# tests/test_display_service.py
import json, os
import display_service as ds

def _write(tmp, name, **rec):
    with open(os.path.join(tmp, name), "w") as f:
        json.dump(rec, f)

def test_derive_key_stable_and_short():
    k1 = ds.derive_key("/tmp/rp2040-status/claude-code-abc")
    k2 = ds.derive_key("/tmp/rp2040-status/claude-code-abc")
    assert k1 == k2 and len(k1) == 6

def test_build_frame_lists_sessions_newest_first(tmp_path):
    _write(str(tmp_path), "claude-code-a", status="WORKING", ts=100,
           source="claude-code", id="a", project="proj", branch="main", title="")
    _write(str(tmp_path), "codex-b", status="DONE", ts=200,
           source="codex", id="b", project="buddy", branch="dev", title="t")
    sessions = ds.read_sessions(str(tmp_path), stale_seconds=None, now=300)
    frame, key_map = ds.build_frame(sessions)
    lines = frame.splitlines()
    assert lines[0] == "LIST 2"
    assert lines[-1] == "END"
    assert lines[1].startswith("S ") and "|DONE|codex|buddy|dev|t" in lines[1]
    assert "|WORKING|claude-code|proj|main|" in lines[2]
    assert set(key_map.values()) == {
        os.path.join(str(tmp_path), "codex-b"),
        os.path.join(str(tmp_path), "claude-code-a"),
    }

def test_build_frame_sanitizes_pipe_and_newline(tmp_path):
    _write(str(tmp_path), "codex-x", status="WORKING", ts=1, source="codex",
           id="x", project="a|b\nc", branch="", title="")
    sessions = ds.read_sessions(str(tmp_path), stale_seconds=None, now=2)
    frame, _ = ds.build_frame(sessions)
    assert "a/b c" in frame

def test_build_frame_empty():
    frame, key_map = ds.build_frame([])
    assert frame == "LIST 0\nEND"
    assert key_map == {}

def test_read_sessions_filters_stale_without_deleting(tmp_path):
    _write(str(tmp_path), "codex-old", status="WORKING", ts=0, source="codex",
           id="old", project="", branch="", title="")
    sessions = ds.read_sessions(str(tmp_path), stale_seconds=600, now=1000)
    assert sessions == []
    assert os.path.exists(os.path.join(str(tmp_path), "codex-old"))

def test_handle_incoming_focus_calls_backend(monkeypatch):
    called = {}
    monkeypatch.setattr(ds, "focus_session", lambda obj: called.setdefault("obj", obj) or True)
    key_map = {"abc123": "/tmp/rp2040-status/codex-x"}
    monkeypatch.setattr(ds, "_read_focus", lambda path: {"backend": "iterm2", "session_id": "S"})
    resend = ds.handle_incoming("focus abc123", key_map)
    assert called["obj"] == {"backend": "iterm2", "session_id": "S"}
    assert resend is False

def test_handle_incoming_ready_requests_resend():
    assert ds.handle_incoming("ready", {}) is True

def test_handle_incoming_unknown_key_is_noop(monkeypatch):
    flag = {"called": False}
    monkeypatch.setattr(ds, "focus_session", lambda obj: flag.__setitem__("called", True))
    assert ds.handle_incoming("focus deadbe", {}) is False
    assert flag["called"] is False

def test_handle_incoming_act_calls_confirm(monkeypatch):
    called = {}
    monkeypatch.setattr(ds, "confirm_action",
                        lambda rec, action: called.setdefault("args", (rec, action)) or True)
    monkeypatch.setattr(ds, "_read_record",
                        lambda path: {"source": "codex", "focus": {"backend": "tmux", "pane": "%2"}})
    monkeypatch.setattr(ds, "_bump_working",
                        lambda path, rec: called.__setitem__("bumped", True))
    key_map = {"abc123": "/tmp/rp2040-status/codex-x"}
    resend = ds.handle_incoming("act abc123 approve", key_map)
    assert called["args"][1] == "approve"
    assert called["args"][0]["source"] == "codex"
    assert called.get("bumped") is True      # PERMISSION -> WORKING nach Erfolg
    assert resend is True                     # erzwingt sofortiges Resend (Feedback)

def test_handle_incoming_act_unknown_key_noop(monkeypatch):
    flag = {"called": False}
    monkeypatch.setattr(ds, "confirm_action",
                        lambda rec, action: flag.__setitem__("called", True))
    assert ds.handle_incoming("act deadbe approve", {}) is False
    assert flag["called"] is False

def test_handle_incoming_act_malformed_noop(monkeypatch):
    flag = {"called": False}
    monkeypatch.setattr(ds, "confirm_action",
                        lambda rec, action: flag.__setitem__("called", True))
    assert ds.handle_incoming("act abc123", {"abc123": "/x"}) is False  # fehlende action
    assert flag["called"] is False

def test_build_frame_includes_path_as_seventh_field(tmp_path):
    _write(str(tmp_path), "claude-code-a", status="WORKING", ts=100,
           source="claude-code", id="a", project="foo", branch="main",
           title="", path="~/Projects/foo")
    sessions = ds.read_sessions(str(tmp_path), stale_seconds=None, now=300)
    frame, _ = ds.build_frame(sessions)
    row = [l for l in frame.splitlines() if l.startswith("S ")][0]
    assert row[2:].split("|")[6] == "~/Projects/foo"

def test_act_bumps_session_to_working(tmp_path, monkeypatch):
    """Touch-Bestaetigung -> Session sofort PERMISSION->WORKING (Feedback), Felder erhalten."""
    import display_service as ds, json, os
    p = os.path.join(str(tmp_path), "claude-code-x")
    json.dump({"status": "PERMISSION", "ts": 1, "source": "claude-code", "id": "x",
               "project": "foo", "branch": "main", "path": "~/foo"}, open(p, "w"))
    key = ds.derive_key(p)
    monkeypatch.setattr(ds, "confirm_action", lambda rec, action: True)
    resend = ds.handle_incoming("act %s approve" % key, {key: p})
    rec = json.load(open(p))
    assert rec["status"] == "WORKING"
    assert rec["project"] == "foo" and rec["branch"] == "main" and rec["path"] == "~/foo"
    assert rec["ts"] > 1
    assert resend is True   # erzwingt sofortiges Resend ans Display

def test_act_no_bump_when_confirm_fails(tmp_path, monkeypatch):
    import display_service as ds, json, os
    p = os.path.join(str(tmp_path), "claude-code-y")
    json.dump({"status": "PERMISSION", "ts": 1, "source": "claude-code", "id": "y"}, open(p, "w"))
    key = ds.derive_key(p)
    monkeypatch.setattr(ds, "confirm_action", lambda rec, action: False)
    ds.handle_incoming("act %s reject" % key, {key: p})
    assert json.load(open(p))["status"] == "PERMISSION"   # unveraendert
