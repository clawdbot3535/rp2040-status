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
