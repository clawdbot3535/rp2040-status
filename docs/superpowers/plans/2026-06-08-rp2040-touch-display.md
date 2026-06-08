# Touch-Display als zweites Gerät — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ein ESP32-S3-Touch-LCD parallel zur RP2040-LED als zweites Ausgabe-Gerät anbinden — Session-Liste mit Source-Themes anzeigen, Tap holt den iTerm2-Tab nach vorne.

**Architecture:** `send.py` reichert pro-Session-Statusdateien an. `broker.py` bleibt unangetastet (LED). Ein neuer Daemon `display_service.py` liest dieselben Dateien, sendet dem ESP32 per USB-serial eine Session-Liste und verarbeitet Tap-Events über `focus.py` (iTerm2/AppleScript). Display-Firmware neu in MicroPython.

**Tech Stack:** Python 3 + pyserial (Host), MicroPython + st7789py + CST816T-Direkt-I2C (Gerät), AppleScript/osascript (Fokus), pytest (Tests).

**Spec:** `docs/superpowers/specs/2026-06-08-rp2040-touch-display-design.md`

---

## File Structure

**Host (Python, Repo-Root):**
- `send.py` — *modify:* Schema-Felder `id/project/branch/title/focus` + Merge.
- `broker.py` — *unverändert.*
- `serial_link.py` — *create:* VID-Discovery + Serial-Link (BLE-später-Seam).
- `display_service.py` — *create:* Daemon — Liste bauen, Frame senden, Taps/`ready` lesen.
- `focus.py` — *create:* Fokus-Backends, Dispatch auf `focus.backend`; `iterm2` via osascript.
- `tools/mock_display.py` — *create:* Host-Emulator des Displays (Frames anzeigen, Taps senden).
- `launchd/com.user.rp2040-display.plist` — *create:* LaunchAgent für `display_service.py`.

**Gerät (MicroPython, neuer Ordner `display/`):**
- `display/boot.py` — *create:* Power-Latch GPIO41 HIGH (früh).
- `display/main.py` — *create:* Frame-Parser, Listen-Rendering, Touch → `focus`/Navigation.
- `display/lib/` — *create:* `st7789py.py` (Vendor-Driver), `cst816.py` (eigener kleiner Treiber).

**Tests:**
- `tests/test_send.py`, `tests/test_display_service.py`, `tests/test_focus.py`, `tests/test_serial_link.py`.

**Hardware-Konstanten (aus Buddys `src/main.cpp` verifiziert):**
ST7789 SPI DC=4 CS=5 SCK=6 MOSI=7 RST=8 BL=15, 240×280, row-offset 20.
CST816T I2C SDA=11 SCL=10 @0x15, TP_RST=13, TP_INT=14, Read-Reg 0x01/6B.
Power-Latch SYS_EN=GPIO41 HIGH. ESP32-S3 USB-VID 0x303A. RP2040 USB-VID 0x2E8A.

---

## Setup (einmalig)

- [ ] **Step 1: Test-Deps ins venv**

Run:
```bash
cd ~/Dev/rp2040-status && .venv/bin/pip install pytest pyserial
```
Expected: „Successfully installed pytest… pyserial…"

- [ ] **Step 2: tests-Ordner anlegen**

Run:
```bash
cd ~/Dev/rp2040-status && mkdir -p tests && touch tests/__init__.py
```
Expected: `tests/__init__.py` existiert.

- [ ] **Step 3: Commit**

```bash
cd ~/Dev/rp2040-status
git add tests/__init__.py
git commit -m "chore: add tests package and dev deps"
```

---

## Phase 0 — Hardware-Spike (Firmware-Treiber zuerst verifizieren)

> Diese Phase ist hardware-gated und nicht per pytest testbar — Schritte haben **erwartete sichtbare Resultate**. Schlägt 0.2 oder 0.3 fehl (kein brauchbarer MicroPython-Treiber), greift der Fallback aus dem Spec (Buddys C++-Firmware, Host-Seite bleibt). Voraussetzung: MicroPython auf dem ESP32-S3 geflasht (`ESP32_GENERIC_S3-SPIRAM_OCT`), `mpremote` im venv.

### Task 0.1: Power-Latch in boot.py

**Files:**
- Create: `display/boot.py`

- [ ] **Step 1: boot.py schreiben**

```python
# display/boot.py — läuft VOR main.py. Haelt die Board-Stromversorgung (SYS_EN).
from machine import Pin

# Waveshare ESP32-S3-Touch-LCD-1.69: SYS_EN = GPIO41, HIGH = Power gehalten.
_sys_en = Pin(41, Pin.OUT)
_sys_en.value(1)
```

- [ ] **Step 2: Auf Gerät kopieren**

Run:
```bash
cd ~/Dev/rp2040-status && .venv/bin/mpremote connect PORT fs cp display/boot.py :boot.py && .venv/bin/mpremote connect PORT reset
```
(PORT = der ESP32-S3-Port, z.B. `/dev/cu.usbmodem101`.)
Expected: Board bootet, bleibt am USB an. Akku-Test optional: ohne USB darf es nicht sofort abschalten.

- [ ] **Step 3: Commit**

```bash
cd ~/Dev/rp2040-status
git add display/boot.py
git commit -m "feat(display): power-latch in boot.py"
```

### Task 0.2: ST7789-Display-Bring-up

**Files:**
- Create: `display/lib/st7789py.py` (Vendor: russhughes/st7789py_mpy, `st7789py.py`)
- Create: `display/spike_lcd.py` (temporär)

- [ ] **Step 1: Vendor-Treiber holen**

Run:
```bash
cd ~/Dev/rp2040-status && mkdir -p display/lib && \
curl -fsSL https://raw.githubusercontent.com/russhughes/st7789py_mpy/master/lib/st7789py.py -o display/lib/st7789py.py && \
curl -fsSL https://raw.githubusercontent.com/russhughes/st7789py_mpy/master/romfonts/vga2_8x8.py -o display/lib/vga2_8x8.py
```
Expected: zwei Dateien geladen.

- [ ] **Step 2: Spike-Skript schreiben**

```python
# display/spike_lcd.py — temporär: prueft ST7789-Bring-up + Offset.
from machine import Pin, SPI
import st7789py as st7789
from lib import vga2_8x8 as font

spi = SPI(1, baudrate=40_000_000, sck=Pin(6), mosi=Pin(7))
tft = st7789.ST7789(
    spi, 240, 280,
    reset=Pin(8, Pin.OUT),
    dc=Pin(4, Pin.OUT),
    cs=Pin(5, Pin.OUT),
    backlight=Pin(15, Pin.OUT),
    rotation=0,
)
# 240x280-Panel: y-Offset 20 (wie Buddys Arduino_ST7789(...,0,20,0,0)).
# st7789py nutzt rotation-Tabellen; falls oben ein 20px-Versatz sichtbar ist,
# in der Treiber-Instanz die _offset-Werte auf (0, 20) setzen (Spike-Aufgabe).
tft.fill(st7789.BLACK)
tft.text(font, "LCD OK", 60, 130, st7789.WHITE, st7789.BLACK)
print("lcd drawn")
```

- [ ] **Step 3: Ausführen**

Run:
```bash
cd ~/Dev/rp2040-status && .venv/bin/mpremote connect PORT fs cp display/lib/st7789py.py :lib/st7789py.py && \
.venv/bin/mpremote connect PORT fs cp display/lib/vga2_8x8.py :lib/vga2_8x8.py && \
.venv/bin/mpremote connect PORT run display/spike_lcd.py
```
Expected: „LCD OK" zentriert auf dem Display, **kein** vertikaler Versatz. Bei Versatz: Offset (0,20) im Treiber setzen und wiederholen.

- [ ] **Step 4: Ergebnis festhalten + Spike entfernen**

Notiere den final funktionierenden Offset in `display/main.py` (Task 8) als Kommentar.
```bash
cd ~/Dev/rp2040-status && rm display/spike_lcd.py
git add display/lib/st7789py.py display/lib/vga2_8x8.py
git commit -m "feat(display): vendor ST7789 MicroPython driver (spike verified)"
```

> **Gate:** Erscheint kein Text → Treiber/Pins/Offset prüfen; wenn auch nach Offset-Tuning erfolglos, **Fallback** aktivieren (Spec-Abschnitt „Dokumentierter Fallback").

### Task 0.3: CST816T-Touch-Bring-up (eigener kleiner Treiber)

**Files:**
- Create: `display/lib/cst816.py`
- Create: `display/spike_touch.py` (temporär)

- [ ] **Step 1: cst816.py schreiben**

```python
# display/lib/cst816.py — minimaler CST816T-Treiber (Register aus Buddys main.cpp).
from machine import Pin, I2C
import time

ADDR = 0x15

class CST816:
    def __init__(self, sda=11, scl=10, rst=13, freq=400_000):
        self._rst = Pin(rst, Pin.OUT)
        self._rst.value(0); time.sleep_ms(10)
        self._rst.value(1); time.sleep_ms(50)
        self.i2c = I2C(0, sda=Pin(sda), scl=Pin(scl), freq=freq)

    def read(self):
        """Gibt (touched, x, y, gesture) zurueck. touched=False wenn kein Finger."""
        try:
            d = self.i2c.readfrom_mem(ADDR, 0x01, 6)
        except OSError:
            return (False, 0, 0, 0)
        gesture = d[0]
        fingers = d[1] & 0x0F
        if fingers == 0:
            return (False, 0, 0, gesture)
        x = ((d[2] & 0x0F) << 8) | d[3]
        y = ((d[4] & 0x0F) << 8) | d[5]
        return (True, x, y, gesture)
```

- [ ] **Step 2: Spike-Skript schreiben**

```python
# display/spike_touch.py — temporär: prueft Touch-Reads.
from lib.cst816 import CST816
import time

tp = CST816()
print("touch spike: tippe aufs Display")
last = False
for _ in range(2000):
    touched, x, y, g = tp.read()
    if touched and not last:
        print("TAP", x, y, "gesture", hex(g))
    last = touched
    time.sleep_ms(20)
```

- [ ] **Step 3: Ausführen**

Run:
```bash
cd ~/Dev/rp2040-status && .venv/bin/mpremote connect PORT fs cp display/lib/cst816.py :lib/cst816.py && \
.venv/bin/mpremote connect PORT run display/spike_touch.py
```
Expected: bei jedem Tippen eine `TAP x y gesture …`-Zeile mit plausiblen Koordinaten (0–239 / 0–279).

- [ ] **Step 4: Spike entfernen + Commit**

```bash
cd ~/Dev/rp2040-status && rm display/spike_touch.py
git add display/lib/cst816.py
git commit -m "feat(display): minimal CST816T touch driver (spike verified)"
```

> **Gate:** Keine/abwegige Koordinaten → I2C-Pins/Adresse/Reset prüfen; sonst Fallback.

---

## Phase 1 — Host: send.py anreichern (TDD)

### Task 1: Schema-Felder + Merge in send.py

**Files:**
- Modify: `send.py`
- Test: `tests/test_send.py`

- [ ] **Step 1: Failing test**

```python
# tests/test_send.py
import json, os, tempfile, importlib, sys

def _load_send(tmp, monkeypatch):
    monkeypatch.setattr("send.STATUS_DIR", tmp, raising=False)
    import send
    importlib.reload(send)
    monkeypatch.setattr(send, "STATUS_DIR", tmp)
    return send

def test_working_writes_enriched_fields(tmp_path, monkeypatch):
    import send; monkeypatch.setattr(send, "STATUS_DIR", str(tmp_path))
    monkeypatch.setenv("ITERM_SESSION_ID", "w0t1p0:UUID-1")
    monkeypatch.setattr(send, "resolve_branch", lambda cwd: "main")
    send.write_status("abc", "WORKING", "claude-code",
                      project="rp2040-status", branch="main",
                      title="", focus={"backend": "iterm2", "session_id": "w0t1p0:UUID-1"})
    rec = json.load(open(os.path.join(str(tmp_path), "claude-code-abc")))
    assert rec["id"] == "abc"
    assert rec["project"] == "rp2040-status"
    assert rec["branch"] == "main"
    assert rec["focus"] == {"backend": "iterm2", "session_id": "w0t1p0:UUID-1"}

def test_done_preserves_sticky_fields(tmp_path, monkeypatch):
    import send; monkeypatch.setattr(send, "STATUS_DIR", str(tmp_path))
    send.write_status("abc", "WORKING", "claude-code",
                      project="rp2040-status", branch="main", title="x",
                      focus={"backend": "iterm2", "session_id": "S1"})
    # DONE-Event ohne project/branch/focus -> muss erhalten bleiben
    send.write_status("abc", "DONE", "claude-code",
                      project="", branch=None, title="", focus=None)
    rec = json.load(open(os.path.join(str(tmp_path), "claude-code-abc")))
    assert rec["status"] == "DONE"
    assert rec["project"] == "rp2040-status"
    assert rec["branch"] == "main"
    assert rec["focus"] == {"backend": "iterm2", "session_id": "S1"}
```

- [ ] **Step 2: Run — soll fehlschlagen**

Run: `cd ~/Dev/rp2040-status && .venv/bin/pytest tests/test_send.py -v`
Expected: FAIL (`write_status()` akzeptiert die neuen Keyword-Args noch nicht).

- [ ] **Step 3: send.py implementieren**

`write_status` in `send.py` ersetzen + Helfer ergänzen:

```python
import subprocess

def resolve_project(cwd: str) -> str:
    return os.path.basename(os.path.normpath(cwd)) if cwd else ""

def resolve_branch(cwd: str) -> str:
    if not cwd:
        return ""
    try:
        out = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=2,
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""

def resolve_focus() -> Optional[dict]:
    sid = os.environ.get("ITERM_SESSION_ID")
    if sid:
        return {"backend": "iterm2", "session_id": sid}
    return None

def _read_existing(path: str) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def write_status(session_id: str, status: str, source: str,
                 project: str = "", branch=None, title: str = "",
                 focus: Optional[dict] = None) -> None:
    """Schreibt/merged Status-Datei. status/ts immer neu; project/branch/title/focus
    werden beibehalten, wenn das neue Event sie nicht liefert."""
    os.makedirs(STATUS_DIR, exist_ok=True)
    path = session_path(session_id, source)

    if status == "OFF":
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        return

    old = _read_existing(path)

    def pick(new, key):
        return new if new else old.get(key, "")

    record = {
        "status": status,
        "ts": time.time(),
        "source": source or old.get("source", "") or "unknown",
        "id": session_id,
        "project": pick(project, "project"),
        "branch": pick(branch, "branch"),
        "title": pick(title, "title"),
        "focus": focus if focus else old.get("focus"),
    }
    with open(path, "w") as f:
        json.dump(record, f)
```

`main()` anpassen, damit die neuen Werte erfasst werden (branch **nur** beim WORKING):

```python
def main() -> int:
    args = parse_args(sys.argv[1:])
    cmd = args.status.upper()

    if cmd == "TIMEOUT-ON":
        set_timeout(True); return 0
    if cmd == "TIMEOUT-OFF":
        set_timeout(False); return 0
    if cmd not in VALID:
        print(f"Unknown: {cmd}. Valid: {', '.join(sorted(VALID))}, TIMEOUT-ON, TIMEOUT-OFF",
              file=sys.stderr)
        return 1

    if args.all:
        update_all_sessions(cmd); return 0

    stdin_data = read_stdin_json()
    explicit_sid = args.session or args.session_pos
    sid = resolve_session_id(explicit_sid, stdin_data)
    source = resolve_source(args.source, stdin_data)

    cwd = stdin_data.get("cwd") or os.environ.get("PWD", "")
    project = resolve_project(cwd)
    branch = resolve_branch(cwd) if cmd == "WORKING" else None
    title = args.title or ""
    focus = resolve_focus()

    write_status(sid, cmd, source, project=project, branch=branch,
                 title=title, focus=focus)
    return 0
```

`parse_args` um `--title` ergänzen:

```python
    p.add_argument("--title", default="", help="Optionaler Kurztitel fuer die Session.")
```

- [ ] **Step 4: Run — soll bestehen**

Run: `cd ~/Dev/rp2040-status && .venv/bin/pytest tests/test_send.py -v`
Expected: PASS (beide Tests).

- [ ] **Step 5: Backwards-Compat des Brokers prüfen**

Run: `cd ~/Dev/rp2040-status && .venv/bin/python -c "import broker, json; print('broker import ok')"`
Expected: „broker import ok" — `broker.py` liest weiter nur `status`/`ts`, neue Felder stören nicht.

- [ ] **Step 6: Commit**

```bash
cd ~/Dev/rp2040-status
git add send.py tests/test_send.py
git commit -m "feat(send): enrich status files with id/project/branch/title/focus and merge"
```

---

## Phase 2 — Host: display_service Kernlogik (TDD, ohne Hardware)

### Task 2: Pure Funktionen — Sessions lesen, Key, Frame, Diff

**Files:**
- Create: `display_service.py`
- Test: `tests/test_display_service.py`

- [ ] **Step 1: Failing test**

```python
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
    # newest (ts=200, codex-b) zuerst
    assert lines[1].startswith("S ") and "|DONE|codex|buddy|dev|t" in lines[1]
    assert "|WORKING|claude-code|proj|main|" in lines[2]
    # key_map zeigt auf echte Pfade
    assert set(key_map.values()) == {
        os.path.join(str(tmp_path), "codex-b"),
        os.path.join(str(tmp_path), "claude-code-a"),
    }

def test_build_frame_sanitizes_pipe_and_newline(tmp_path):
    _write(str(tmp_path), "codex-x", status="WORKING", ts=1, source="codex",
           id="x", project="a|b\nc", branch="", title="")
    sessions = ds.read_sessions(str(tmp_path), stale_seconds=None, now=2)
    frame, _ = ds.build_frame(sessions)
    assert "a/b c" in frame  # | und newline ersetzt
    assert frame.count("\n") == frame.count(chr(10))  # nur die Frame-Newlines

def test_read_sessions_filters_stale_without_deleting(tmp_path):
    _write(str(tmp_path), "codex-old", status="WORKING", ts=0, source="codex",
           id="old", project="", branch="", title="")
    sessions = ds.read_sessions(str(tmp_path), stale_seconds=600, now=1000)
    assert sessions == []
    assert os.path.exists(os.path.join(str(tmp_path), "codex-old"))  # NICHT geloescht
```

- [ ] **Step 2: Run — soll fehlschlagen**

Run: `cd ~/Dev/rp2040-status && .venv/bin/pytest tests/test_display_service.py -v`
Expected: FAIL (`display_service` existiert nicht).

- [ ] **Step 3: display_service.py (pure Funktionen) implementieren**

```python
#!/usr/bin/env python3
"""Display-Service — sendet die Session-Liste ans ESP32-S3-Touch-LCD und
verarbeitet Tap-Events (focus). Treibt KEINE LED (das macht broker.py)."""

import glob
import hashlib
import json
import os
import time

STATUS_DIR = "/tmp/rp2040-status"
CONFIG_FILE = os.path.join(STATUS_DIR, ".config")
POLL_MS = 200
DEFAULT_STALE_SECONDS = 600
ESP32S3_VID = 0x303A  # Espressif — Touch-LCD


def derive_key(path: str) -> str:
    """Kurzer, stabiler Schluessel aus dem Dateinamen (Transport-Detail)."""
    base = os.path.basename(path)
    return hashlib.sha1(base.encode()).hexdigest()[:6]


def _sanitize(value: str) -> str:
    """| und Zeilenumbrueche raus — sie sind Protokoll-Trenner."""
    return str(value or "").replace("|", "/").replace("\n", " ").replace("\r", " ")


def read_sessions(status_dir: str, stale_seconds, now: float):
    """Liste von (path, record). Filtert stale, loescht NICHTS."""
    if not os.path.isdir(status_dir):
        return []
    out = []
    for path in glob.glob(os.path.join(status_dir, "*")):
        if os.path.basename(path).startswith("."):
            continue
        try:
            with open(path) as f:
                rec = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        ts = rec.get("ts", 0)
        if stale_seconds is not None and now - ts > stale_seconds:
            continue
        out.append((path, rec))
    return out


def build_frame(sessions):
    """Baut den LIST-Frame-String + key->path-Map. Neueste Session zuerst."""
    sessions = sorted(sessions, key=lambda pr: pr[1].get("ts", 0), reverse=True)
    lines = [f"LIST {len(sessions)}"]
    key_map = {}
    for path, rec in sessions:
        key = derive_key(path)
        key_map[key] = path
        row = "|".join([
            key,
            _sanitize(rec.get("status", "")),
            _sanitize(rec.get("source", "")),
            _sanitize(rec.get("project", "")),
            _sanitize(rec.get("branch", "")),
            _sanitize(rec.get("title", "")),
        ])
        lines.append(f"S {row}")
    lines.append("END")
    return "\n".join(lines), key_map


def read_config() -> dict:
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def get_stale_seconds():
    cfg = read_config()
    if not cfg.get("timeout_enabled", True):
        return None
    return cfg.get("stale_seconds", DEFAULT_STALE_SECONDS)
```

- [ ] **Step 4: Run — soll bestehen**

Run: `cd ~/Dev/rp2040-status && .venv/bin/pytest tests/test_display_service.py -v`
Expected: PASS (4 Tests).

- [ ] **Step 5: Commit**

```bash
cd ~/Dev/rp2040-status
git add display_service.py tests/test_display_service.py
git commit -m "feat(display-service): session reading, key derivation, frame building"
```

---

## Phase 3 — Host: Fokus-Backend (TDD)

### Task 3: focus.py mit iTerm2-Backend

**Files:**
- Create: `focus.py`
- Test: `tests/test_focus.py`

- [ ] **Step 1: Failing test**

```python
# tests/test_focus.py
import focus

def test_dispatch_iterm2_calls_osascript(monkeypatch):
    calls = {}
    def fake_run(cmd, **kw):
        calls["cmd"] = cmd
        class R: returncode = 0
        return R()
    monkeypatch.setattr(focus.subprocess, "run", fake_run)
    ok = focus.focus_session({"backend": "iterm2", "session_id": "w0t1p0:GUID-9"})
    assert ok is True
    assert calls["cmd"][0] == "osascript"
    assert "GUID-9" in calls["cmd"][-1]  # GUID landet im AppleScript

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
```

- [ ] **Step 2: Run — soll fehlschlagen**

Run: `cd ~/Dev/rp2040-status && .venv/bin/pytest tests/test_focus.py -v`
Expected: FAIL (`focus` existiert nicht).

- [ ] **Step 3: focus.py implementieren**

```python
#!/usr/bin/env python3
"""Fokus-Backends. focus_session(focus_obj) holt das richtige Ziel nach vorne.
Backend-Dispatch ueber focus_obj['backend']. v1: iterm2 (AppleScript)."""

import subprocess

# $ITERM_SESSION_ID hat die Form "w0t1p0:GUID"; iTerm2-AppleScript matcht die GUID
# gegen 'unique id of session'. Skript selektiert Tab+Window und aktiviert iTerm2.
_ITERM2_SCRIPT = '''
on run argv
  set targetId to item 1 of argv
  tell application "iTerm2"
    repeat with w in windows
      repeat with t in tabs of w
        repeat with s in sessions of t
          if (unique id of s) is targetId then
            select t
            select w
            activate
            return "ok"
          end if
        end repeat
      end repeat
    end repeat
  end tell
  return "notfound"
end run
'''


def _guid(session_id: str) -> str:
    # "w0t1p0:GUID" -> "GUID"; ohne Doppelpunkt unveraendert.
    return session_id.split(":", 1)[1] if ":" in session_id else session_id


def _focus_iterm2(session_id: str) -> bool:
    if not session_id:
        return False
    try:
        res = subprocess.run(
            ["osascript", "-e", _ITERM2_SCRIPT, _guid(session_id)],
            capture_output=True, text=True, timeout=5,
        )
        return res.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def focus_session(focus_obj) -> bool:
    """True bei erfolgreichem Fokus, sonst False (no-op)."""
    if not focus_obj or not isinstance(focus_obj, dict):
        return False
    backend = focus_obj.get("backend")
    if backend == "iterm2":
        return _focus_iterm2(focus_obj.get("session_id", ""))
    return False
```

- [ ] **Step 4: Run — soll bestehen**

Run: `cd ~/Dev/rp2040-status && .venv/bin/pytest tests/test_focus.py -v`
Expected: PASS (4 Tests).

- [ ] **Step 5: AppleScript real verifizieren (manuell)**

In einem iTerm2-Tab:
```bash
cd ~/Dev/rp2040-status && python3 -c "import focus,os; print(focus.focus_session({'backend':'iterm2','session_id':os.environ['ITERM_SESSION_ID']}))"
```
Expected: `True`, und iTerm2 kommt nach vorne. Schlägt das fehl → `unique id` ggf. durch `id` ersetzen und erneut testen.

- [ ] **Step 6: Commit**

```bash
cd ~/Dev/rp2040-status
git add focus.py tests/test_focus.py
git commit -m "feat(focus): iTerm2 tab focus backend via AppleScript"
```

---

## Phase 4 — Host: Serial-Link (TDD der Discovery)

### Task 4: serial_link.py

**Files:**
- Create: `serial_link.py`
- Test: `tests/test_serial_link.py`

- [ ] **Step 1: Failing test**

```python
# tests/test_serial_link.py
import serial_link

class _Port:
    def __init__(self, vid, device): self.vid = vid; self.device = device

def test_find_device_matches_vid(monkeypatch):
    ports = [_Port(0x2E8A, "/dev/cu.led"), _Port(0x303A, "/dev/cu.display")]
    monkeypatch.setattr(serial_link, "_list_ports", lambda: ports)
    assert serial_link.find_device(0x303A) == "/dev/cu.display"
    assert serial_link.find_device(0x2E8A) == "/dev/cu.led"

def test_find_device_none_when_absent(monkeypatch):
    monkeypatch.setattr(serial_link, "_list_ports", lambda: [_Port(0x2E8A, "/dev/cu.led")])
    assert serial_link.find_device(0x303A) is None
```

- [ ] **Step 2: Run — soll fehlschlagen**

Run: `cd ~/Dev/rp2040-status && .venv/bin/pytest tests/test_serial_link.py -v`
Expected: FAIL (`serial_link` existiert nicht).

- [ ] **Step 3: serial_link.py implementieren**

```python
#!/usr/bin/env python3
"""USB-Serial-Link mit VID-Discovery. Schnittstelle bewusst transport-neutral,
damit spaeter ein ble_link.py mit gleicher API (open/read_line/write_line/close)
andocken kann."""

import serial
from serial.tools import list_ports


def _list_ports():
    return list(list_ports.comports())


def find_device(vid: int):
    """Erstes Geraet mit passender USB-Vendor-ID, oder None."""
    matches = sorted(p.device for p in _list_ports() if getattr(p, "vid", None) == vid)
    return matches[0] if matches else None


class SerialLink:
    """Duenne, zeilenbasierte Serial-Verbindung. Reconnect macht der Aufrufer."""

    def __init__(self, baud: int = 115200):
        self.baud = baud
        self._conn = None
        self._buf = b""

    def open(self, device: str) -> None:
        self._conn = serial.Serial(device, self.baud, timeout=0, dsrdtr=False)
        self._buf = b""

    def is_open(self) -> bool:
        return self._conn is not None

    def write_line(self, text: str) -> None:
        self._conn.write((text + "\n").encode())

    def read_lines(self):
        """Nicht-blockierend: liefert komplette Zeilen seit dem letzten Aufruf."""
        if self._conn is None:
            return
        self._buf += self._conn.read(256)
        while b"\n" in self._buf:
            line, self._buf = self._buf.split(b"\n", 1)
            yield line.decode(errors="replace").strip()

    def close(self) -> None:
        try:
            if self._conn:
                self._conn.close()
        except Exception:
            pass
        self._conn = None
```

- [ ] **Step 4: Run — soll bestehen**

Run: `cd ~/Dev/rp2040-status && .venv/bin/pytest tests/test_serial_link.py -v`
Expected: PASS (2 Tests).

- [ ] **Step 5: Commit**

```bash
cd ~/Dev/rp2040-status
git add serial_link.py tests/test_serial_link.py
git commit -m "feat(serial-link): VID discovery and line-based serial link"
```

---

## Phase 5 — Host: Daemon-Loop + Tap/Ready (TDD mit Fake-Link)

### Task 5: display_service Event-Verarbeitung

**Files:**
- Modify: `display_service.py`
- Test: `tests/test_display_service.py` (ergänzen)

- [ ] **Step 1: Failing test ergänzen**

In `tests/test_display_service.py` anhängen:

```python
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
```

- [ ] **Step 2: Run — soll fehlschlagen**

Run: `cd ~/Dev/rp2040-status && .venv/bin/pytest tests/test_display_service.py -v`
Expected: FAIL (`handle_incoming` / `_read_focus` / `focus_session` fehlen).

- [ ] **Step 3: display_service.py ergänzen**

Oben ergänzen:
```python
from focus import focus_session
from serial_link import SerialLink, find_device
```

Funktionen hinzufügen:
```python
def _read_focus(path: str):
    try:
        with open(path) as f:
            return json.load(f).get("focus")
    except (json.JSONDecodeError, OSError):
        return None


def handle_incoming(line: str, key_map: dict) -> bool:
    """Verarbeitet eine Zeile vom Display. Gibt True zurueck, wenn ein Resend
    erzwungen werden soll (z.B. nach 'ready')."""
    line = line.strip()
    if line == "ready":
        return True
    if line.startswith("focus "):
        key = line[len("focus "):].strip()
        path = key_map.get(key)
        if path:
            focus_session(_read_focus(path))
    return False


def main() -> None:
    print(f"Display-Service gestartet (poll: {POLL_MS}ms)")
    os.makedirs(STATUS_DIR, exist_ok=True)
    link = SerialLink()
    last_frame = None
    key_map = {}
    last_device_check = 0

    while True:
        now = time.time()

        if not link.is_open() and now - last_device_check > 5:
            device = find_device(ESP32S3_VID)
            if device:
                try:
                    link.open(device)
                    last_frame = None  # Resend nach (Re)connect
                    print(f"Display verbunden: {device}")
                except Exception as e:
                    print(f"Verbindungsfehler: {e}")
            last_device_check = now

        if link.is_open():
            try:
                for line in link.read_lines():
                    if handle_incoming(line, key_map):
                        last_frame = None
            except Exception:
                link.close()
                last_device_check = 0

        frame, key_map = build_frame(read_sessions(STATUS_DIR, get_stale_seconds(), now))
        if frame != last_frame and link.is_open():
            try:
                link.write_line(frame)
                last_frame = frame
            except Exception:
                link.close()
                last_device_check = 0
                print("Schreibfehler — Reconnect erzwungen")

        time.sleep(POLL_MS / 1000)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nDisplay-Service beendet.")
```

- [ ] **Step 4: Run — soll bestehen**

Run: `cd ~/Dev/rp2040-status && .venv/bin/pytest tests/ -v`
Expected: PASS (alle Tests, inkl. der neuen drei).

- [ ] **Step 5: Commit**

```bash
cd ~/Dev/rp2040-status
git add display_service.py tests/test_display_service.py
git commit -m "feat(display-service): daemon loop with focus/ready handling and reconnect"
```

---

## Phase 6 — Host: Mock-Display + LaunchAgent

### Task 6: tools/mock_display.py

**Files:**
- Create: `tools/mock_display.py`

- [ ] **Step 1: Mock schreiben**

```python
#!/usr/bin/env python3
"""Emuliert das Touch-Display am Host: verbindet sich mit dem Display-Service-Port,
zeigt empfangene LIST-Frames und sendet auf Eingabe Tap-Events.

Nutzung (zwei PTYs via socat ODER direkt gegen echten ESP):
    python3 tools/mock_display.py /dev/cu.usbmodemXXX
Befehle (stdin): 'r' = ready senden, '<key>' = 'focus <key>' senden, 'q' = quit.
"""
import sys
import threading
import serial


def reader(conn):
    buf = b""
    while True:
        buf += conn.read(256)
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            print("RX:", line.decode(errors="replace").strip())


def main():
    if len(sys.argv) < 2:
        print("usage: mock_display.py <serial-port>"); return 1
    conn = serial.Serial(sys.argv[1], 115200, timeout=0.1)
    threading.Thread(target=reader, args=(conn,), daemon=True).start()
    print("ready 'r' | focus '<key>' | quit 'q'")
    for line in sys.stdin:
        cmd = line.strip()
        if cmd == "q":
            break
        elif cmd == "r":
            conn.write(b"ready\n")
        elif cmd:
            conn.write(f"focus {cmd}\n".encode())
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Commit**

```bash
cd ~/Dev/rp2040-status
git add tools/mock_display.py
git commit -m "feat(tools): host-side mock display for protocol verification"
```

### Task 7: LaunchAgent für display_service

**Files:**
- Create: `launchd/com.user.rp2040-display.plist`

- [ ] **Step 1: Plist schreiben** (Pfade an dein System anpassen — `USERNAME`, venv-Pfad)

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.user.rp2040-display</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/USERNAME/Dev/rp2040-status/.venv/bin/python3</string>
    <string>/Users/USERNAME/Dev/rp2040-status/display_service.py</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/tmp/rp2040-display.log</string>
  <key>StandardErrorPath</key><string>/tmp/rp2040-display.err</string>
</dict>
</plist>
```

- [ ] **Step 2: Installieren + laden**

Run:
```bash
cp ~/Dev/rp2040-status/launchd/com.user.rp2040-display.plist ~/Library/LaunchAgents/ && \
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.user.rp2040-display.plist && \
launchctl print gui/$(id -u)/com.user.rp2040-display | head -20
```
Expected: Service gelistet, state = running.

- [ ] **Step 3: Commit**

```bash
cd ~/Dev/rp2040-status
git add launchd/com.user.rp2040-display.plist
git commit -m "feat(launchd): LaunchAgent for display_service"
```

---

## Phase 7 — Firmware: Display-UI (nach Phase 0 grün)

### Task 8: display/main.py — Frame-Parser + Rendering

**Files:**
- Create: `display/main.py`

- [ ] **Step 1: main.py — Setup, Themes, Frame-Parser, Render**

```python
# display/main.py — MicroPython. Liest LIST-Frames ueber USB-Serial,
# rendert die Session-Liste mit Source-Theme. (boot.py hat SYS_EN bereits gehalten.)
import sys, select, time
from machine import Pin, SPI
import st7789py as st7789
from lib import vga2_8x8 as font
from lib.cst816 import CST816

# --- Display (ST7789, 240x280, row-offset 20 aus Phase-0-Spike) ---
spi = SPI(1, baudrate=40_000_000, sck=Pin(6), mosi=Pin(7))
tft = st7789.ST7789(spi, 240, 280, reset=Pin(8, Pin.OUT), dc=Pin(4, Pin.OUT),
                    cs=Pin(5, Pin.OUT), backlight=Pin(15, Pin.OUT), rotation=0)
tp = CST816()

W, H = 240, 280
NAV_H = 48
ROW_H = 8 * 3

# Theme: (fg, bg, accent) je Source
THEMES = {
    "codex":       (st7789.color565(20, 24, 28), st7789.color565(245, 245, 240), st7789.color565(40, 200, 120)),
    "claude-code": (st7789.color565(30, 20, 16), st7789.color565(245, 238, 228), st7789.color565(210, 110, 70)),
    "antigravity": (st7789.color565(230, 230, 240), st7789.color565(18, 18, 26), st7789.color565(120, 160, 255)),
}
DEFAULT_THEME = (st7789.WHITE, st7789.BLACK, st7789.color565(0, 200, 220))

def theme_for(source):
    return THEMES.get(source, DEFAULT_THEME)

# --- Modell ---
sessions = []   # Liste dicts: {key,status,source,project,branch,title}
page = 0

poll = select.poll()
poll.register(sys.stdin, select.POLLIN)
_inbuf = ""
_pending = None  # akkumulierter Frame waehrend LIST..END

def read_serial_lines():
    global _inbuf
    if not poll.poll(0):
        return
    _inbuf += sys.stdin.read(1)
    while "\n" in _inbuf:
        line, _inbuf = _inbuf.split("\n", 1)
        handle_line(line.strip())

def handle_line(line):
    global _pending, sessions, page
    if line.startswith("LIST"):
        _pending = []
    elif line == "END":
        if _pending is not None:
            sessions = _pending
            _pending = None
            page = min(page, max(0, len(sessions) - 1))
            render()
    elif line.startswith("S ") and _pending is not None:
        parts = line[2:].split("|")
        while len(parts) < 6:
            parts.append("")
        _pending.append({"key": parts[0], "status": parts[1], "source": parts[2],
                         "project": parts[3], "branch": parts[4], "title": parts[5]})

def render():
    if not sessions:
        tft.fill(st7789.BLACK)
        tft.text(font, "IDLE", W // 2 - 16, H // 2, st7789.color565(0, 200, 220), st7789.BLACK)
        return
    s = sessions[page]
    fg, bg, accent = theme_for(s["source"])
    tft.fill(bg)
    tft.fill_rect(0, 0, W, 3, accent)
    tft.text(font, s["status"][:20], 8, 16, accent, bg)
    tft.text(font, s["project"][:28], 8, 40, fg, bg)
    tft.text(font, s["branch"][:28], 8, 60, fg, bg)
    if s["title"]:
        tft.text(font, s["title"][:28], 8, 84, fg, bg)
    # Footer: n / N + Nav-Pfeile
    marker = "%d / %d" % (page + 1, len(sessions))
    tft.text(font, marker, W // 2 - 24, H - NAV_H + 16, fg, bg)
    tft.text(font, "<", 16, H - NAV_H + 16, accent if page > 0 else bg, bg)
    tft.text(font, ">", W - 24, H - NAV_H + 16, accent if page < len(sessions) - 1 else bg, bg)
```

- [ ] **Step 2: Auf Gerät kopieren + manuell prüfen (mit Mock-Frame)**

Run:
```bash
cd ~/Dev/rp2040-status && .venv/bin/mpremote connect PORT fs cp display/main.py :main.py && \
.venv/bin/mpremote connect PORT reset
# In einem zweiten Terminal einen Frame schicken:
printf 'LIST 1\nS abc123|WORKING|claude-code|rp2040-status|main|hello\nEND\n' > PORT
```
Expected: Display zeigt Claude-Theme mit „WORKING / rp2040-status / main / hello".

- [ ] **Step 3: Commit**

```bash
cd ~/Dev/rp2040-status
git add display/main.py
git commit -m "feat(display): frame parser and themed session rendering"
```

### Task 9: display/main.py — Touch (Tap→focus, Swipe→Navigation, ready)

**Files:**
- Modify: `display/main.py`

- [ ] **Step 1: Touch-Loop + ready ergänzen**

Ans Ende von `display/main.py` anhängen:

```python
# --- Touch-Verarbeitung ---
TAP_MAX_MOVE = 28
SWIPE_MIN = 46
_touch_start = None  # (x, y, t)
_last_xy = None

def handle_touch():
    global _touch_start, _last_xy, page
    touched, x, y, gesture = tp.read()
    now = time.ticks_ms()
    if touched:
        if _touch_start is None:
            _touch_start = (x, y, now)
        _last_xy = (x, y)
        return
    # Loslassen
    if _touch_start is None or _last_xy is None:
        _touch_start = None
        return
    sx, sy, st_ms = _touch_start
    ex, ey = _last_xy
    dx, dy = ex - sx, ey - sy
    _touch_start = None
    _last_xy = None
    in_nav = sy >= H - NAV_H
    if in_nav and abs(dx) >= SWIPE_MIN and abs(dx) > abs(dy):
        if dx < 0 and page < len(sessions) - 1:
            page += 1; render()
        elif dx > 0 and page > 0:
            page -= 1; render()
        return
    if abs(dx) <= TAP_MAX_MOVE and abs(dy) <= TAP_MAX_MOVE:
        if in_nav:
            # Tap auf Nav-Leiste: linke Haelfte zurueck, rechte vor
            if ex < W // 2 and page > 0:
                page -= 1; render()
            elif ex >= W // 2 and page < len(sessions) - 1:
                page += 1; render()
        elif sessions:
            sys.stdout.write("focus %s\n" % sessions[page]["key"])

# --- Main Loop ---
sys.stdout.write("ready\n")
render()
while True:
    read_serial_lines()
    handle_touch()
    time.sleep_ms(20)
```

- [ ] **Step 2: Auf Gerät + Ende-zu-Ende mit mock_display.py prüfen**

Run:
```bash
cd ~/Dev/rp2040-status && .venv/bin/mpremote connect PORT fs cp display/main.py :main.py && \
.venv/bin/mpremote connect PORT reset
.venv/bin/python tools/mock_display.py PORT
```
Erwartung im Mock:
- Beim Display-Boot erscheint `RX: ready`.
- Tap auf eine Session → `RX: focus <key>`.
- Swipe in der unteren Leiste blättert die Anzeige.

> Hinweis: `mock_display.py` belegt den Port — der echte `display_service` darf parallel **nicht** denselben Port halten. Für den Mock-Test den LaunchAgent kurz stoppen:
> `launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.user.rp2040-display.plist`

- [ ] **Step 3: Commit**

```bash
cd ~/Dev/rp2040-status
git add display/main.py
git commit -m "feat(display): touch handling — tap to focus, swipe to navigate, ready signal"
```

---

## Phase 8 — Ende-zu-Ende-Verifikation

### Task 10: Voller Durchstich (LED + Display parallel)

- [ ] **Step 1: Beide Geräte anstecken, beide Services laufen**

Run:
```bash
launchctl print gui/$(id -u)/com.user.rp2040-display | grep -i state
launchctl print gui/$(id -u)/$(basename ~/Dev/rp2040-status/rp2040-broker.service .service 2>/dev/null) 2>/dev/null || echo "broker-service-label pruefen"
```
Expected: Display-Service `running`; Broker-Service ebenfalls aktiv.

- [ ] **Step 2: Status aus einem iTerm2-Tab senden**

Run (in einem iTerm2-Tab im rp2040-status-Repo):
```bash
echo '{"session_id":"e2e1","cwd":"'"$PWD"'"}' | .venv/bin/python send.py WORKING --source claude-code
```
Expected:
- LED wird blau (WORKING) — Broker unverändert.
- Display zeigt die Session „WORKING / rp2040-status / <branch>" im Claude-Theme.
- `/tmp/rp2040-status/claude-code-e2e1` enthält `focus.session_id` = aktueller `$ITERM_SESSION_ID`.

- [ ] **Step 3: Tap-to-focus prüfen**

Wechsle in eine andere App, dann **tippe** auf die Session am Display.
Expected: iTerm2 kommt nach vorne, exakt der ausgehende Tab wird aktiviert.

- [ ] **Step 4: Aufräumen-Race verifizieren**

Run:
```bash
echo '{"session_id":"e2e1"}' | .venv/bin/python send.py DONE --source claude-code
sleep 1; ls /tmp/rp2040-status/
```
Expected: Datei existiert noch (DONE), Display zeigt DONE, LED grün. Erst nach Stale-Timeout pruned **nur** der Broker.

- [ ] **Step 5: README ergänzen**

In `README.md` einen Abschnitt „Touch-Display (ESP32-S3)" ergänzen: Geräte parallel, `display_service` + `focus`, Flash via `mpremote`, Fallback-Hinweis. (Kurz, an bestehenden Stil angelehnt.)

```bash
cd ~/Dev/rp2040-status
git add README.md
git commit -m "docs: document touch-display device setup"
```

---

## Self-Review-Notiz (vom Autor)

- **Spec-Abdeckung:** Schema (Task 1), Wire-Protokoll/Frame (Task 2), Fokus iTerm2 (Task 3), VID-Discovery/Transport-Seam (Task 4), Daemon + Tap/Ready + Reconnect (Task 5), Mock (Task 6), LaunchAgent (Task 7), Firmware boot/UI/Touch (Task 0.1, 8, 9), Phase-0-Spike + Fallback (Phase 0), „nur Broker pruned" (Task 2/Task 10 Step 4). Alle Spec-Punkte haben einen Task.
- **Namens-Konsistenz:** `build_frame`/`read_sessions`/`derive_key`/`handle_incoming`/`_read_focus` (display_service); `focus_session` (focus.py); `find_device`/`SerialLink.read_lines/write_line` (serial_link) — über Tasks hinweg identisch verwendet.
- **Offene Verifikationspunkte (bewusst, hardware-/umgebungsabhängig):** ST7789-Offset (0.2), CST816-Register (0.3), iTerm2 `unique id` vs `id` (Task 3 Step 5). Jeweils mit Fallback/Anpassungshinweis im Schritt.
