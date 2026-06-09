# Display Animation / Marquee / AA-Icons Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **NOTE:** Firmware-only (MicroPython on the ESP32-S3). Not pytest-driven — verification is on-board (visual) plus a host-regression guard (44 pytest must stay green). Layout/animation values are starting points; expect on-board tuning (tick rate, pulse depth, marquee speed). Stop the display LaunchAgent before each deploy (`launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.user.rp2040-display.plist`) and re-enable after.

**Goal:** Make the status display lively — anti-aliased icons, a rotating WORKING spinner, a rotating IDLE burst, a one-shot DONE "pop", a backlight breathing pulse on INPUT/PERMISSION, and a continuous marquee for overflowing path text.

**Architecture:** An `animate(now)` tick in the main loop redraws only the animated region (~20 fps); `render()` (full screen) runs only on frame/page change and resets animation state + detects status transitions. Icons become 8-bit alpha (coverage) blended `ink`-over-`bg` via a cached compositor; rotation uses pre-rendered frames. The pulse is **backlight PWM** (whole screen breathes, no redraw). Host side untouched.

**Tech Stack:** MicroPython, `st7789py`, `machine.PWM` (backlight), CST816 touch, PIL asset build (AA + rotation frames).

**Spec:** `docs/superpowers/specs/2026-06-09-display-animation-marquee-design.md`

---

## File Structure

- `display/lib/icons.py` — *regenerate:* 8-bit alpha icons + rotation frame arrays (`REFRESH_FRAMES`, `BURST_FRAMES`, `CHECK`).
- `display/main.py` — *modify:* backlight PWM, `_blit_aa` compositor, animation state + `animate(now)`, `_marquee(...)`, loop wiring, `render()` reset/transition.
- **Untouched (host):** `confirm.py`, `display_service.py`, `send.py`, `keymap.json`, `serial_link.py`, `focus.py`, `broker.py`, RP2040 `main.py`, `tests/`.

**Current relevant `main.py` shape (from the status redesign):** display init holds `backlight=Pin(15, ...)`; helpers `_disc`, `_rrect`, `_wcenter`, `_blit_1bit(bmp, detail, ink, band, x, y, size, src=48)` + `_BUF_CACHE`; components `draw_header`/`draw_path`/`draw_dots`/`draw_badge`; per-state `_r_working/_r_done/_r_input/_r_permission/_r_idle` + `RENDER` + `render()`; touch `handle_touch`/`_nav`; loop `read_serial_lines(); handle_touch(); time.sleep_ms(20)`. `icons.REFRESH/CHECK/BURST` are 1-bit today.

---

## Task 0: Regenerate icons.py — AA (8-bit alpha) + rotation frames

**Files:**
- Regenerate: `display/lib/icons.py`

- [ ] **Step 1: Re-export the icon PNGs from Figma (if /tmp copies are gone)**

`get_screenshot` (contentsOnly, maxDimension 96) for nodes `3:623` (refresh), `3:616` (check), `3:846` (burst); download to `/tmp/ic_refresh.png`, `/tmp/ic_check.png`, `/tmp/ic_burst.png`. (Icons are white glyphs on transparent → the alpha channel is the coverage.)

- [ ] **Step 2: Build AA icons + 12 rotation frames**

```bash
cd /Users/christian/Dev/rp2040-status && /Users/christian/Dev/rp2040-status/.venv/bin/python - <<'PY'
from PIL import Image
def alpha_bytes(im, size):
    im = im.convert("RGBA").resize((size, size), Image.LANCZOS)
    a = im.split()[3]
    return bytes(a.tobytes())                      # 1 Byte/Pixel Coverage
def frames(path, size, n=12):
    src = Image.open(path).convert("RGBA").resize((size, size), Image.LANCZOS)
    out = []
    for i in range(n):
        rot = src.rotate(-i * (360 // n), resample=Image.BICUBIC, expand=False)
        out.append(bytes(rot.split()[3].tobytes()))
    return out
REFRESH = frames("/tmp/ic_refresh.png", 48)        # 12 Frames, je 48*48 = 2304 B
BURST   = frames("/tmp/ic_burst.png", 64)          # 12 Frames, je 64*64 = 4096 B
CHECK   = alpha_bytes(Image.open("/tmp/ic_check.png"), 48)   # statisch
lines = ['"""8-bit alpha-coverage Status-Icons + Rotations-Frames (Figma)."""', '']
lines.append("REFRESH_FRAMES = (" + ", ".join(f"bytes({f!r})" for f in REFRESH) + ")")
lines.append("REFRESH_W = 48"); lines.append("")
lines.append("BURST_FRAMES = (" + ", ".join(f"bytes({f!r})" for f in BURST) + ")")
lines.append("BURST_W = 64"); lines.append("")
lines.append(f"CHECK = bytes({CHECK!r})"); lines.append("CHECK_W = 48"); lines.append("")
open("display/lib/icons.py", "w").write("\n".join(lines))
print("geschrieben")
PY
```

- [ ] **Step 3: Sanity (sizes + frame counts) + commit**

```bash
cd /Users/christian/Dev/rp2040-status
.venv/bin/python -c "
ns={}; exec(open('display/lib/icons.py').read(), ns)
assert len(ns['REFRESH_FRAMES'])==12 and all(len(f)==48*48 for f in ns['REFRESH_FRAMES'])
assert len(ns['BURST_FRAMES'])==12 and all(len(f)==64*64 for f in ns['BURST_FRAMES'])
assert len(ns['CHECK'])==48*48
print('icons AA+frames ok')
"
git add display/lib/icons.py
git commit -m "feat(display): AA (8-bit alpha) icons + 12-frame rotation sets"
```

---

## Task 1: Backlight PWM (own the LCD backlight)

**Files:**
- Modify: `display/main.py`

- [ ] **Step 1: Hand the backlight to PWM instead of a held-high pin**

Change the display init: pass `backlight=None` to `ST7789(...)` and add a PWM right after `tp = CST816()`:

```python
spi = SPI(1, baudrate=40_000_000, sck=Pin(6), mosi=Pin(7))
tft = st7789.ST7789(spi, 240, 280, reset=Pin(8, Pin.OUT), dc=Pin(4, Pin.OUT),
                    cs=Pin(5, Pin.OUT), backlight=None, rotation=0,
                    custom_rotations=_ROTATIONS)
tp = CST816()

from machine import PWM
bl = PWM(Pin(15), freq=20000)      # >20kHz -> kein hoerbares Fiepen
BL_FULL = 65535
def bl_set(frac):                  # frac 0.0..1.0
    bl.duty_u16(int(max(0, min(1, frac)) * BL_FULL))
bl_set(1.0)
```

- [ ] **Step 2: Deploy-check (board) — backlight stays full-on, screen unchanged**

```bash
cd /Users/christian/Dev/rp2040-status && PORT=/dev/cu.usbmodem11334201
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.user.rp2040-display.plist 2>/dev/null; sleep 0.5
.venv/bin/python -c "import ast; ast.parse(open('display/main.py').read()); print('ok')"
mpremote connect $PORT fs cp display/main.py :main.py && mpremote connect $PORT reset
```
Expected: display lights normally (PWM at full = same as before).

- [ ] **Step 3: Commit**

```bash
cd /Users/christian/Dev/rp2040-status
git add display/main.py
git commit -m "feat(display): manage backlight via PWM (enables breathing pulse)"
```

---

## Task 2: AA compositor + use it for icons

**Files:**
- Modify: `display/main.py`

- [ ] **Step 1: Add `_blit_aa` (alpha compositor) next to `_blit_1bit`**

```python
_AA_CACHE = {}
def _unpack565(c):
    return ((c >> 11) & 0x1F) << 3, ((c >> 5) & 0x3F) << 2, (c & 0x1F) << 3

def _blit_aa(cov, ink, bg, x, y, size, src, frame=0):
    """8-bit-Coverage-Bitmap ink-ueber-bg geblendet, skaliert, gecacht."""
    ck = (id(cov), ink, bg, size, frame)
    buf = _AA_CACHE.get(ck)
    if buf is None:
        ir, ig, ib = _unpack565(ink)
        br, bg_, bb = _unpack565(bg)
        buf = bytearray(size * size * 2)
        o = 0
        for row in range(size):
            sr = (row * src // size) * src
            for col in range(size):
                a = cov[sr + (col * src // size)]
                r = (ir * a + br * (255 - a)) // 255
                g = (ig * a + bg_ * (255 - a)) // 255
                b = (ib * a + bb * (255 - a)) // 255
                c = st7789.color565(r, g, b)
                buf[o] = c >> 8; buf[o + 1] = c & 0xFF
                o += 2
        _AA_CACHE[ck] = buf
    tft.blit_buffer(buf, x, y, size, size)
```

- [ ] **Step 2: Point the badge + idle burst at AA icons**

Replace `draw_badge` and the burst draw in `_r_idle`:

```python
def draw_badge(cov, src, frame, target=44):
    cx, cy = W // 2, BADGE_CY
    _disc(cx, cy, BADGE_R, INK)
    _blit_aa(cov, ON_INK, INK, cx - target // 2, cy - target // 2, target, src, frame)
```
- `_r_done` → `draw_badge(icons.CHECK, icons.CHECK_W, 0)`.
- `_r_working` → `draw_badge(icons.REFRESH_FRAMES[_anim_phase % 12], icons.REFRESH_W, _anim_phase % 12)` (the phase var lands in Task 3; for now pass frame `0`: `icons.REFRESH_FRAMES[0]`).
- `_r_idle` burst → `_blit_aa(icons.BURST_FRAMES[0], ON_INK, STATUS_BG["IDLE"], W//2-36, BADGE_CY-36, 72, icons.BURST_W, 0)`.

(The provider header logos stay on `_blit_1bit` for now — 1-bit at 22px is acceptable; AA-ing them is a later option.)

- [ ] **Step 3: Deploy + board check (static AA), commit**

```bash
cd /Users/christian/Dev/rp2040-status && PORT=/dev/cu.usbmodem11334201
.venv/bin/python -c "import ast; ast.parse(open('display/main.py').read()); print('ok')"
mpremote connect $PORT fs cp display/lib/icons.py :lib/icons.py && mpremote connect $PORT fs cp display/main.py :main.py && mpremote connect $PORT reset
# Frame senden (WORKING/DONE/IDLE) und Icon-Kanten pruefen (sollten glatt sein)
git add display/main.py && git commit -m "feat(display): alpha-blended icons (smooth edges)"
```
Expected: check/refresh/burst now have smooth, anti-aliased edges.

---

## Task 3: Animation tick scaffold (state + loop wiring + render reset)

**Files:**
- Modify: `display/main.py`

- [ ] **Step 1: Add animation state + `animate(now)` + reset/transition in `render()`**

Near the touch constants add:
```python
ANIM_MS = 50            # ~20 fps
PULSE_STATES = ("INPUT", "PERMISSION")
_anim_phase = 0
_anim_last = -1000
_last_status = None
_done_start = -10000    # ms; DONE-Pop laeuft fuer DONE_POP_MS danach
DONE_POP_MS = 260
```

In `render()`, at the top (before drawing), detect transition + reset:
```python
def render():
    global _last_status, _done_start, _anim_phase
    if not sessions:
        if _last_status != "IDLE":
            _anim_phase = 0
        _last_status = "IDLE"; _r_idle(); _pulse_apply("IDLE"); return
    s = sessions[page]; status = s["status"]
    if status != _last_status:
        _anim_phase = 0
        if status == "DONE":
            _done_start = time.ticks_ms()
        _last_status = status
    bg = bg_for(status); tft.fill(bg)
    fn = RENDER.get(status)
    if fn: fn(s, bg)
    else:
        draw_header(status, s["source"]); draw_path(s["project"], s["branch"], bg); draw_dots(len(sessions))
    _pulse_apply(status)

def _pulse_apply(status):
    if status not in PULSE_STATES:
        bl_set(1.0)   # voll, falls vorher gepulst

def animate(now):
    global _anim_phase, _anim_last
    if time.ticks_diff(now, _anim_last) < ANIM_MS:
        return
    _anim_last = now
    _anim_phase += 1
    if not sessions:
        return _tick_idle()
    status = sessions[page]["status"]
    if status == "WORKING":
        _tick_working()
    elif status == "DONE":
        _tick_done(now)
    elif status in PULSE_STATES:
        _tick_pulse(now)
    # Marquee laeuft statusunabhaengig (Task 7)
```

Add stubs so it parses (filled in later tasks):
```python
def _tick_idle(): pass
def _tick_working(): pass
def _tick_done(now): pass
def _tick_pulse(now): pass
```

- [ ] **Step 2: Wire into the main loop**

```python
while True:
    read_serial_lines()
    handle_touch()
    animate(time.ticks_ms())
    time.sleep_ms(20)
```

- [ ] **Step 3: Parse + deploy + commit (no visible change yet)**

```bash
cd /Users/christian/Dev/rp2040-status && PORT=/dev/cu.usbmodem11334201
.venv/bin/python -c "import ast; ast.parse(open('display/main.py').read()); print('ok')"
mpremote connect $PORT fs cp display/main.py :main.py && mpremote connect $PORT reset
git add display/main.py && git commit -m "feat(display): animation tick scaffold (state, animate(), reset/transition)"
```

---

## Task 4: WORKING spinner + IDLE rotation

**Files:**
- Modify: `display/main.py`

- [ ] **Step 1: Implement the rotation ticks (redraw only the badge region)**

```python
def _tick_working():
    f = _anim_phase % 12
    cx, cy = W // 2, BADGE_CY
    _blit_aa(icons.REFRESH_FRAMES[f], ON_INK, INK, cx - 22, cy - 22, 44, icons.REFRESH_W, f)

def _tick_idle():
    f = (_anim_phase // 3) % 12     # langsamer
    _blit_aa(icons.BURST_FRAMES[f], ON_INK, STATUS_BG["IDLE"],
             W // 2 - 36, BADGE_CY - 36, 72, icons.BURST_W, f)
```
Also make `_r_working`/`_r_idle` draw their starting frame so the first paint matches:
- `_r_working` badge → `_blit_aa(icons.REFRESH_FRAMES[0], ON_INK, INK, ...)` (via `draw_badge` already passing frame 0 is fine).

- [ ] **Step 2: Deploy + board check (spin/rotation smooth), commit**

```bash
cd /Users/christian/Dev/rp2040-status && PORT=/dev/cu.usbmodem11334201
.venv/bin/python -c "import ast; ast.parse(open('display/main.py').read()); print('ok')"
mpremote connect $PORT fs cp display/main.py :main.py && mpremote connect $PORT reset
# WORKING-Frame senden -> Refresh dreht; leere Liste -> Burst dreht langsam
git add display/main.py && git commit -m "feat(display): rotating WORKING spinner and IDLE burst"
```
Expected: WORKING refresh spins smoothly; IDLE burst rotates slowly. Tune `// 3` / `ANIM_MS` on-board if jerky/too fast.

---

## Task 5: DONE one-shot pop

**Files:**
- Modify: `display/main.py`

- [ ] **Step 1: Implement `_tick_done` (scale 0.7→1.0 over DONE_POP_MS, then static)**

```python
def _tick_done(now):
    dt = time.ticks_diff(now, _done_start)
    if dt > DONE_POP_MS:
        return                       # fertig -> statisch (kein Redraw mehr)
    k = 0.7 + 0.3 * (dt / DONE_POP_MS)   # 0.7..1.0
    t = int(44 * k)
    cx, cy = W // 2, BADGE_CY
    tft.fill_rect(cx - 34, cy - 34, 68, 68, bg_for("DONE"))   # Badge-Region leeren
    _disc(cx, cy, int(BADGE_R * k), INK)
    _blit_aa(icons.CHECK, ON_INK, INK, cx - t // 2, cy - t // 2, t, icons.CHECK_W, 0)
```

- [ ] **Step 2: Deploy + board check (DONE pops once on transition), commit**

```bash
cd /Users/christian/Dev/rp2040-status && PORT=/dev/cu.usbmodem11334201
.venv/bin/python -c "import ast; ast.parse(open('display/main.py').read()); print('ok')"
mpremote connect $PORT fs cp display/main.py :main.py && mpremote connect $PORT reset
# WORKING-Frame, dann denselben key auf DONE -> Badge ploppt einmal
git add display/main.py && git commit -m "feat(display): one-shot DONE badge pop on transition"
```
Expected: switching a session to DONE plays a brief badge pop, then stays static. Tune `DONE_POP_MS` / scale range on-board.

---

## Task 6: Backlight breathing pulse (INPUT / PERMISSION)

**Files:**
- Modify: `display/main.py`

- [ ] **Step 1: Implement `_tick_pulse` (sine breathe via backlight duty)**

```python
import math
PULSE_MIN = 0.45
PULSE_MS = 1500     # ein Atemzyklus
def _tick_pulse(now):
    ph = (time.ticks_ms() % PULSE_MS) / PULSE_MS
    frac = PULSE_MIN + (1 - PULSE_MIN) * (0.5 - 0.5 * math.cos(ph * 2 * math.pi))
    bl_set(frac)
```
(`_pulse_apply` already resets `bl_set(1.0)` when leaving a pulse state on the next full `render()`.)

- [ ] **Step 2: Deploy + board check (INPUT/PERMISSION breathe, no flicker), commit**

```bash
cd /Users/christian/Dev/rp2040-status && PORT=/dev/cu.usbmodem11334201
.venv/bin/python -c "import ast; ast.parse(open('display/main.py').read()); print('ok')"
mpremote connect $PORT fs cp display/main.py :main.py && mpremote connect $PORT reset
# INPUT- bzw. PERMISSION-Frame -> ganzer Screen atmet hell/dunkel; WORKING/DONE bleiben voll hell
git add display/main.py && git commit -m "feat(display): backlight breathing pulse for INPUT/PERMISSION"
```
Expected: INPUT/PERMISSION screens breathe smoothly (no redraw, no flicker); other states stay full brightness. Tune `PULSE_MIN`/`PULSE_MS` on-board.

---

## Task 7: Marquee for overflowing path text

**Files:**
- Modify: `display/main.py`

- [ ] **Step 1: Add `_marquee` + per-status marquee state, use in path drawing**

```python
MARQUEE_SPEED = 2      # px / Tick
MARQUEE_GAP = 24
_marquee_off = 0

def _fit_prefix(fnt, text, max_px):
    """Laengster Prefix, der in max_px passt (zum Clippen ohne HW-Clip)."""
    w = 0
    for i, ch in enumerate(text):
        w += _char_w(fnt, ch)
        if w > max_px:
            return text[:i]
    return text

def _marquee(fnt, text, x, y, avail, fg, bg, off):
    tw = tft.write_width(fnt, text)
    tft.fill_rect(x, y, avail, fnt.HEIGHT, bg)      # Streifen leeren
    if tw <= avail:
        tft.write(fnt, text, x, y, fg, bg)
        return False
    period = tw + MARQUEE_GAP
    o = off % period
    for base in (x - o, x - o + period):            # zwei Kopien -> nahtloser Loop
        if base >= x + avail:
            continue
        if base >= x:
            seg = _fit_prefix(fnt, text, x + avail - base)
            tft.write(fnt, seg, base, y, fg, bg)
        else:
            # links abgeschnitten: ueberspringe Zeichen bis sichtbar
            skip_px = x - base
            # zeichne ab dem Punkt; einfacher: ganze Zeile schreiben, Streifen-bg clippt links nicht -> daher Vorab-bg + Prefix ab x
            vis = text
            tft.write(fnt, vis, base, y, fg, bg)
    # rechten Rand sauber halten
    tft.fill_rect(x + avail, y, 1, fnt.HEIGHT, bg)
    return True
```
> The left-clip case has no hardware clip; the `fill_rect` strip + drawing within `[x, x+avail]` keeps it bounded on the right. The left edge may briefly show a glyph entering — acceptable for a path ticker. Refine on-board (e.g., draw the strip bg, then only the right copy) if the left edge looks messy.

In `draw_path`, replace the static path `write` with a marquee call (path occupies `PAD_X..chip_start`):
```python
def draw_path(project, branch, bg):
    p = "~/Dev/" + (project or "")
    # Chip-Breite reservieren, Rest ist die Marquee-Spur
    chipw = (tft.write_width(fsm, branch[:14]) + 16) if branch else 0
    avail = W - 2 * PAD_X - (chipw + 8 if branch else 0)
    over = _marquee(fsm, p, PAD_X, PATH_Y, avail, SOFT, bg, _marquee_off)
    if branch:
        cx = W - PAD_X - chipw
        _rrect(cx, PATH_Y - 3, chipw, LH + 6, 5, CHIP)
        tft.write(fsm, branch[:14], cx + 8, PATH_Y, INK_TXT, CHIP)
    return over
```
And the big INPUT path in `_r_input` uses `_marquee(fbig, ...)` centred (or left-padded) likewise.

- [ ] **Step 2: Drive the marquee from `animate()`**

In `animate(now)`, after the per-status branch, add:
```python
    global _marquee_off
    if sessions:
        _marquee_off += MARQUEE_SPEED
        # nur neu zeichnen, wenn die aktuelle Session ueberlaeuft -> draw_path/_r_input neu
        s = sessions[page]
        if s["status"] in ("WORKING", "DONE", "PERMISSION"):
            draw_path(s["project"], s["branch"], bg_for(s["status"]))
        elif s["status"] == "INPUT":
            _input_path_marquee(s, bg_for("INPUT"))
```
(`_input_path_marquee` draws just the big INPUT path strip with `_marquee`.)
> Only redraw the path strip when it actually overflows — `_marquee` returns `over`; cache that per page to avoid needless redraws of short paths. Detail tuned on-board.

- [ ] **Step 3: Deploy + board check (long path scrolls, short path static), commit**

```bash
cd /Users/christian/Dev/rp2040-status && PORT=/dev/cu.usbmodem11334201
.venv/bin/python -c "import ast; ast.parse(open('display/main.py').read()); print('ok')"
mpremote connect $PORT fs cp display/main.py :main.py && mpremote connect $PORT reset
# Frame mit langem project (z.B. 'a-very-long-project-name-here') -> Pfad scrollt; kurzer -> statisch
git add display/main.py && git commit -m "feat(display): marquee scroll for overflowing path text"
```
Expected: a too-wide path scrolls continuously with a gap; short paths stay still; branch chip stays put.

---

## Task 8: Verify + finalize

- [ ] **Step 1: Full board sweep (all states + interactions)**

Send the 4-status frame (+ a long-project variant) and confirm: WORKING spins, DONE pops once, INPUT/PERMISSION breathe, IDLE rotates, long path scrolls; swipe pages; tap focuses; PERMISSION buttons emit `act` (`/tmp/rp2040_tap_test.py`).

- [ ] **Step 2: Host regression + untouched check**

```bash
cd /Users/christian/Dev/rp2040-status
.venv/bin/pytest tests/ -q | tail -1     # 44 passed
git diff main..HEAD --stat -- confirm.py display_service.py send.py keymap.json broker.py main.py serial_link.py focus.py   # leer
```

- [ ] **Step 3: Re-enable daemon + README + commit**

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.user.rp2040-display.plist
```
Add a short note to the README touch-display section: the display animates (spinning WORKING, breathing INPUT/PERMISSION via backlight, DONE pop, rotating idle) and scrolls long paths. Commit:
```bash
cd /Users/christian/Dev/rp2040-status
git add README.md
git commit -m "docs: note display animations + path marquee"
```

---

## Self-Review-Notiz (vom Autor)

- **Spec-Abdeckung:** AA-Icons (Task 0, 2), WORKING-Spin + IDLE-Rotation (Task 0 Frames, Task 4), DONE-Pop (Task 3 Transition, Task 5), Backlight-Puls (Task 1 PWM, Task 6), Marquee (Task 7), Animations-Tick/Region-Redraw-Architektur (Task 3), Host-Regression (Task 8). Alle Spec-Punkte abgedeckt.
- **Namens-Konsistenz:** `_blit_aa`, `_AA_CACHE`, `bl`/`bl_set`/`BL_FULL`, `animate`/`_anim_phase`/`_anim_last`/`_last_status`/`_done_start`/`DONE_POP_MS`, `_tick_working/_tick_idle/_tick_done/_tick_pulse`, `PULSE_STATES`/`_pulse_apply`, `_marquee`/`_marquee_off`/`MARQUEE_SPEED`/`MARQUEE_GAP`/`_fit_prefix`, `icons.REFRESH_FRAMES`/`BURST_FRAMES`/`CHECK` — über Tasks hinweg identisch.
- **Bewusste Board-Tuning-Punkte (kein TBD-Logikloch, sondern visuelles Feintuning):** `ANIM_MS`, Burst-Rate `//3`, `DONE_POP_MS`+Skala, `PULSE_MIN`/`PULSE_MS`, `MARQUEE_SPEED`/`GAP`, Marquee-Links-Clip-Feinschliff. Jeweils im Deploy-Schritt als Tuning markiert.
- **Risiko Marquee-Linksrand:** ohne HW-Clip im Plan benannt (Task 7 Step 1 Hinweis) — am Board verfeinerbar, ohne die Architektur zu ändern.
