# Confirm-from-device Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the touch display send Approve / Reject / Continue keystrokes to a waiting agent via a long-press confirm screen, injected over tmux `send-keys` or iTerm2 `write text`.

**Architecture:** New host module `confirm.py` (keymap + injection backends, isolated from `focus.py`). `display_service.handle_incoming` gains an `act <key> <action>` branch that reads the session record and calls `confirm_action`. Firmware adds long-press → confirm overlay → button tap that emits `act`.

**Tech Stack:** Python 3 + pytest (host), MicroPython (device), tmux `send-keys` + iTerm2 AppleScript (injection).

**Spec:** `docs/superpowers/specs/2026-06-08-confirm-from-device-design.md`

---

## File Structure

**Host (Python, repo root):**
- `confirm.py` — *create:* keymap resolution + `confirm_action(record, action)` with tmux/iterm2 backends + kill-switch.
- `display_service.py` — *modify:* `act <key> <action>` branch + `_read_record(path)` helper; import `confirm_action`.
- `keymap.json` — *create:* default override file (generic y/n/Enter, `enabled: true`).

**Device (MicroPython):**
- `display/main.py` — *modify:* long-press detection, confirm overlay render, button hit-boxes, emit `act <key> <action>`, suppress frame redraw while overlay is up.

**Tests:**
- `tests/test_confirm.py` — *create.*
- `tests/test_display_service.py` — *modify* (extend with `act` handling).

**Constants verified from existing code:** `focus._guid(session_id)` strips `wNtMpK:` → GUID. Status file record keys: `status, ts, source, id, project, branch, title, focus`. `focus` = `{"backend":"tmux","pane":"%N",...}` or `{"backend":"iterm2","session_id":"wNtMpK:GUID"}`. Display→host protocol lines today: `ready`, `focus <key>`.

---

## Task 1: Keymap resolution + kill-switch

**Files:**
- Create: `confirm.py`
- Test: `tests/test_confirm.py`

- [ ] **Step 1: Write the failing test**

```python
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
    # nicht ueberschriebene Aktion faellt auf Default
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Dev/rp2040-status && .venv/bin/pytest tests/test_confirm.py -v`
Expected: FAIL (`confirm` module does not exist).

- [ ] **Step 3: Write minimal implementation**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/Dev/rp2040-status && .venv/bin/pytest tests/test_confirm.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
cd ~/Dev/rp2040-status
git add confirm.py tests/test_confirm.py
git commit -m "feat(confirm): keymap resolution and kill-switch"
```

---

## Task 2: confirm_action dispatch (tmux + iTerm2)

**Files:**
- Modify: `confirm.py`
- Test: `tests/test_confirm.py` (extend)

- [ ] **Step 1: Write the failing test (append to `tests/test_confirm.py`)**

```python
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
    # GUID + payload "n" landen als argv
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
    assert captured["cmd"][-1] == ""   # nur Enter -> leerer write-text-Payload

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
    # iTerm2 v1 kann 'Up' nicht abbilden -> no-op
    flag = {"ran": False}
    def fake_run(cmd, **kw):
        flag["ran"] = True
        class R: returncode = 0; stdout = "ok"
        return R()
    monkeypatch.setattr(confirm.subprocess, "run", fake_run)
    ok = confirm.confirm_action(
        {"source": "codex", "focus": {"backend": "iterm2", "session_id": "x:y"}}, "approve")
    assert ok is False and flag["ran"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Dev/rp2040-status && .venv/bin/pytest tests/test_confirm.py -v`
Expected: FAIL (`confirm_action`, `subprocess` not present).

- [ ] **Step 3: Write minimal implementation (add to `confirm.py`)**

Add `import subprocess` and `import focus` to the imports, then append:

```python
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
        return ""
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
        r = subprocess.run(
            ["osascript", "-e", _ITERM2_WRITE, focus._guid(session_id), payload],
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/Dev/rp2040-status && .venv/bin/pytest tests/test_confirm.py -v`
Expected: PASS (all confirm tests).

- [ ] **Step 5: Verify iTerm2 AppleScript live (manual, from an iTerm2 tab)**

Run (in an iTerm2 tab; this types `echo hi` + Enter into THIS shell):
```bash
cd ~/Dev/rp2040-status && .venv/bin/python -c "import confirm,os; print(confirm.confirm_action({'source':'x','focus':{'backend':'iterm2','session_id':os.environ['ITERM_SESSION_ID']}}, 'continue'))"
```
Expected: prints `True`, and a blank line (Enter) appears in the terminal. If `False`, check `unique id` vs `id` in `_ITERM2_WRITE`.

- [ ] **Step 6: Commit**

```bash
cd ~/Dev/rp2040-status
git add confirm.py tests/test_confirm.py
git commit -m "feat(confirm): tmux send-keys and iTerm2 write-text injection backends"
```

---

## Task 3: display_service handles `act <key> <action>`

**Files:**
- Modify: `display_service.py`
- Test: `tests/test_display_service.py` (extend)

- [ ] **Step 1: Write the failing test (append to `tests/test_display_service.py`)**

```python
def test_handle_incoming_act_calls_confirm(monkeypatch):
    called = {}
    monkeypatch.setattr(ds, "confirm_action",
                        lambda rec, action: called.setdefault("args", (rec, action)) or True)
    monkeypatch.setattr(ds, "_read_record",
                        lambda path: {"source": "codex", "focus": {"backend": "tmux", "pane": "%2"}})
    key_map = {"abc123": "/tmp/rp2040-status/codex-x"}
    resend = ds.handle_incoming("act abc123 approve", key_map)
    assert called["args"][1] == "approve"
    assert called["args"][0]["source"] == "codex"
    assert resend is False

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Dev/rp2040-status && .venv/bin/pytest tests/test_display_service.py -v`
Expected: FAIL (`confirm_action`/`_read_record` not in `display_service`, no `act` branch).

- [ ] **Step 3: Implement in `display_service.py`**

Add the import below the existing `from focus import focus_session`:
```python
from confirm import confirm_action
```

Add the helper next to `_read_focus`:
```python
def _read_record(path: str):
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
```

In `handle_incoming`, add the `act` branch before the final `return False`:
```python
    if line.startswith("act "):
        parts = line.split()
        if len(parts) == 3:
            key, action = parts[1], parts[2]
            path = key_map.get(key)
            if path:
                confirm_action(_read_record(path), action)
        return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/Dev/rp2040-status && .venv/bin/pytest tests/ -v`
Expected: PASS (whole suite green, including the 3 new tests).

- [ ] **Step 5: Commit**

```bash
cd ~/Dev/rp2040-status
git add display_service.py tests/test_display_service.py
git commit -m "feat(display-service): handle 'act <key> <action>' -> confirm_action"
```

---

## Task 4: Default keymap file

**Files:**
- Create: `keymap.json`

- [ ] **Step 1: Create `keymap.json`**

```json
{
  "enabled": true,
  "*": { "approve": ["y", "Enter"], "reject": ["n", "Enter"], "continue": ["Enter"] }
}
```

- [ ] **Step 2: Sanity + suite still green**

Run:
```bash
cd ~/Dev/rp2040-status && .venv/bin/python -c "import json; json.load(open('keymap.json')); print('keymap ok')"
.venv/bin/pytest tests/ -q | tail -1
```
Expected: `keymap ok` and all tests pass (the file makes `resolve_keys` use the `*` block, identical to defaults).

- [ ] **Step 3: Commit**

```bash
cd ~/Dev/rp2040-status
git add keymap.json
git commit -m "feat(confirm): default keymap.json (generic y/n/Enter, enabled)"
```

---

## Task 5: Firmware — long-press + confirm overlay (board)

> Hardware-gated. The display LaunchAgent holds the serial port — stop it first:
> `launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.user.rp2040-display.plist`
> Re-enable after: `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.user.rp2040-display.plist`

**Files:**
- Modify: `display/main.py`

- [ ] **Step 1: Add confirm-mode constants + state**

Near the touch constants (`TAP_DEBOUNCE_MS` etc.), add:
```python
LONGPRESS_MS = 600
ACTIONABLE = ("PERMISSION", "INPUT")
_BTN = (("approve", "APPROVE"), ("reject", "REJECT"), ("continue", "CONTINUE"))
# Button-Hit-Boxen (y0, y1) im Confirm-Overlay
_BTN_Y = (95, 135, 175)
_BTN_H = 34
_confirm_key = None     # key der Session im Confirm-Modus, oder None
_lp_fired = False       # Long-press in dieser Touch-Sequenz schon ausgeloest?
```

- [ ] **Step 2: Add the confirm-overlay renderer (place after `render()`)**

```python
def render_confirm():
    s = sessions[page]
    fg, bg, accent, soft = theme_for(s["source"])
    tft.fill(bg)
    tft.fill_rect(0, 0, W, BANNER_H, accent)
    _wcenter(fbig, "CONFIRM", (BANNER_H - LH_BIG) // 2, bg, accent)
    tft.write(fsm, (s["project"] or s["source"])[:24], PAD_X, BANNER_H + 8, soft, bg)
    for (action, label), y in zip(_BTN, _BTN_Y):
        tft.fill_rect(PAD_X, y, W - 2 * PAD_X, _BTN_H, accent)
        tft.write(fbig, label, PAD_X + 12, y + (_BTN_H - LH_BIG) // 2, bg, accent)
    tft.write(fsm, "tap outside = cancel", PAD_X, H - LH - 6, soft, bg)
```

- [ ] **Step 3: Rework `handle_touch` for long-press + confirm mode**

Replace the whole `handle_touch` function with:
```python
def _send_act(action, now):
    global _confirm_key, _last_action_ms
    sys.stdout.write("act %s %s\n" % (_confirm_key, action))
    _confirm_key = None
    _last_action_ms = now
    render()  # zurueck zur Session

def handle_touch():
    global _touch_start, _last_xy, _last_action_ms, _confirm_key, _lp_fired
    touched, x, y, gesture = tp.read()
    now = time.ticks_ms()
    deb = time.ticks_diff(now, _last_action_ms) >= TAP_DEBOUNCE_MS

    # --- Confirm-Modus: nur Taps auf Buttons / daneben ---
    if _confirm_key is not None:
        if touched:
            if _touch_start is None:
                _touch_start = (x, y, now)
            _last_xy = (x, y)
            return
        if _touch_start is None:
            return
        ex, ey = _last_xy
        _touch_start = None
        _last_xy = None
        if not deb:
            return
        for (action, _label), by in zip(_BTN, _BTN_Y):
            if PAD_X <= ex <= W - PAD_X and by <= ey <= by + _BTN_H:
                _send_act(action, now)
                return
        _confirm_key = None  # Tap daneben -> abbrechen
        render()
        return

    # --- Hardware-Swipe ---
    if deb and gesture == GESTURE_LEFT:
        _nav(1, now); _touch_start = None; _last_xy = None; _lp_fired = False; return
    if deb and gesture == GESTURE_RIGHT:
        _nav(-1, now); _touch_start = None; _last_xy = None; _lp_fired = False; return

    if touched:
        if _touch_start is None:
            _touch_start = (x, y, now); _lp_fired = False
        _last_xy = (x, y)
        # Long-press: gehalten, kaum Bewegung, Session wartet -> Confirm-Screen
        sx, sy, st_ms = _touch_start
        if (not _lp_fired and deb and sessions
                and sessions[page]["status"] in ACTIONABLE
                and time.ticks_diff(now, st_ms) >= LONGPRESS_MS
                and abs(x - sx) <= TAP_MAX_MOVE and abs(y - sy) <= TAP_MAX_MOVE):
            _lp_fired = True
            _confirm_key = sessions[page]["key"]
            _last_action_ms = now
            render_confirm()
        return

    # --- Release: Tap (wenn kein Long-press) ---
    if _touch_start is None or _last_xy is None:
        _touch_start = None
        return
    sx, sy, st_ms = _touch_start
    ex, ey = _last_xy
    dx, dy = ex - sx, ey - sy
    _touch_start = None
    _last_xy = None
    if _lp_fired:
        _lp_fired = False
        return
    if not deb:
        return
    if abs(dx) <= TAP_MAX_MOVE and abs(dy) <= TAP_MAX_MOVE:
        if sy >= H - NAV_H:
            _nav(-1 if ex < W // 2 else 1, now)
        elif sessions:
            _last_action_ms = now
            sys.stdout.write("focus %s\n" % sessions[page]["key"])
```

- [ ] **Step 4: Suppress frame redraw while overlay is up**

In `handle_line`, change the `END` branch so an incoming frame updates the model but does NOT redraw over the confirm overlay:
```python
    elif line == "END":
        if _pending is not None:
            sessions = _pending
            _pending = None
            page = min(page, max(0, len(sessions) - 1))
            if _confirm_key is None:
                render()
```

- [ ] **Step 5: ast-parse + deploy**

Run:
```bash
cd ~/Dev/rp2040-status && PORT=/dev/cu.usbmodem11334201
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.user.rp2040-display.plist 2>/dev/null; sleep 0.5
.venv/bin/python -c "import ast; ast.parse(open('display/main.py').read()); print('OK')"
mpremote connect $PORT fs cp display/main.py :main.py
mpremote connect $PORT reset
```
Expected: `OK`, files copied, board resets.

- [ ] **Step 6: Manual verify on board**

Send a PERMISSION frame, then long-press → confirm screen → tap APPROVE; watch the serial for the emitted `act`:
```bash
.venv/bin/python - <<'PY'
import serial, time
s = serial.Serial("/dev/cu.usbmodem11334201", 115200, timeout=0.3)
time.sleep(0.5); s.read(300)
s.write(b"LIST 1\nS k1|PERMISSION|claude-code|some-repo|feature/x|\nEND\n")
print("Frame gesendet. Long-press die Session, dann APPROVE tippen (15s).")
t0=time.time()
buf=b""
while time.time()-t0 < 15:
    buf += s.read(64)
print("vom Display empfangen:", repr(buf))
s.close()
PY
```
Expected: after long-press the confirm screen appears; tapping APPROVE prints `b'act k1 approve\n'`. Tapping outside cancels (no output). A long-press on a `WORKING`/`DONE` session does nothing.

- [ ] **Step 7: Commit + re-enable daemon**

```bash
cd ~/Dev/rp2040-status
git add display/main.py
git commit -m "feat(display): long-press confirm overlay emits 'act <key> <action>'"
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.user.rp2040-display.plist
```

---

## Task 6: End-to-end on board (tmux agent)

- [ ] **Step 1: Create a throwaway tmux agent waiting at a y/n prompt**

Run:
```bash
tmux kill-session -t confirmdemo 2>/dev/null
tmux new-session -d -s confirmdemo -c ~/Dev/rp2040-status
tmux send-keys -t confirmdemo 'read -p "Approve? [y/n] " ans; echo "GOT=$ans" > /tmp/confirm_demo.txt' Enter
PANE=$(tmux list-panes -t confirmdemo -F "#{pane_id}" | head -1)
echo "Demo-Pane: $PANE"
```

- [ ] **Step 2: Write a PERMISSION session file pointing at that pane**

Run (substitute the `$PANE` from Step 1):
```bash
.venv/bin/python - "$PANE" <<'PY'
import json, time, sys
pane = sys.argv[1]
rec = {"status":"PERMISSION","ts":time.time()+3600,"source":"claude-code",
       "id":"confirmdemo","project":"confirm-demo","branch":"","title":"Approve?",
       "focus":{"backend":"tmux","pane":pane}}
open("/tmp/rp2040-status/claude-code-confirmdemo","w").write(json.dumps(rec))
print("Demo-Session geschrieben ->", rec["focus"])
PY
```

- [ ] **Step 3: Confirm from the display**

The running `display_service` LaunchAgent pushes the PERMISSION session to the display (amber, top). On the display: long-press it → tap **APPROVE**. Then check the agent received `y`:
```bash
sleep 2; cat /tmp/confirm_demo.txt 2>/dev/null
```
Expected: `GOT=y` — the display's APPROVE injected `y`+Enter into the tmux pane's `read` prompt.

- [ ] **Step 4: Clean up**

```bash
tmux kill-session -t confirmdemo 2>/dev/null
rm -f /tmp/rp2040-status/claude-code-confirmdemo /tmp/confirm_demo.txt
```

- [ ] **Step 5: Document + commit**

Add a "Confirm from the display" subsection to the README's touch-display section (long-press → APPROVE/REJECT/CONTINUE; keymap.json + kill-switch; injects via tmux/iTerm2). Then:
```bash
cd ~/Dev/rp2040-status
git add README.md
git commit -m "docs: document confirm-from-device (long-press actions, keymap, kill-switch)"
```

---

## Self-Review-Notiz (vom Autor)

- **Spec-Abdeckung:** Protokoll `act <key> <action>` (Task 3, 5), `confirm.py` + Keymap + Kill-Switch (Task 1, 2, 4), tmux/iTerm2-Injektion (Task 2), `display_service`-Branch + `_read_record` (Task 3), Long-press + Confirm-Overlay + nur bei `PERMISSION`/`INPUT` (Task 5), Overlay-Redraw-Suppression (Task 5 Step 4), E2E tmux (Task 6), Doku (Task 6 Step 5). Alle Spec-Punkte abgedeckt.
- **Namens-Konsistenz:** `confirm_action(record, action)`, `resolve_keys(source, action)`, `is_enabled()`, `_iterm_payload`, `_send_tmux`/`_send_iterm2`, `_read_record`, `render_confirm`, `_confirm_key`, `_send_act` — über Tasks hinweg identisch.
- **Offene Verifikationspunkte (hardware-/umgebungsabhängig):** iTerm2 `unique id` vs `id` (Task 2 Step 5), Long-press-Ergonomie + Button-Hit-Boxen (Task 5 Step 6), tmux-E2E (Task 6).
- **YAGNI bewusst:** keine Freitext-Antworten, kein Menü-Auto-Navigieren; iTerm2-Spezialtasten v1 übersprungen+geloggt.
