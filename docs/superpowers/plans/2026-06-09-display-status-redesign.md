# Display Status-Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **NOTE:** This is firmware-only (MicroPython on the ESP32-S3). It is **not** pytest-driven — verification is on-board (visual) plus a host-regression guard. Visual layout values are taken from Figma but expect minor on-board tuning (font baselines, padding) like prior display work. The display LaunchAgent holds the serial port — stop it before each deploy (`launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.user.rp2040-display.plist`) and re-enable after.

**Goal:** Rebuild the touch-display firmware to the Figma status-redesign: background colour encodes the status (blue/yellow/red/green/grey — same as the LED), with a header pill (provider logo + status label), path+branch chip, status icons, dot navigation, and inline Approve/Reject/Continue buttons on PERMISSION.

**Architecture:** `display/main.py` `render()` becomes status-driven via a `RENDER` dispatch table; `STATUS_BG` + token palette replace `THEMES`/`_STATE`; a new `display/lib/icons.py` holds Figma-exported 1-bit icons; `handle_touch()` loses long-press/chevron/confirm-overlay and keeps swipe + tap-focus + PERMISSION button hit-boxes. Host side (`confirm.py`, `display_service.py`, `send.py`, `keymap.json`, `broker.py`, RP2040 `main.py`) is **untouched**.

**Tech Stack:** MicroPython, `st7789py` (`fill`/`fill_rect`/`write`/`blit_buffer`), CST816 touch, Figma asset export + 1-bit bitmap conversion.

**Spec:** `docs/superpowers/specs/2026-06-09-display-status-redesign-design.md`

---

## File Structure

- `display/main.py` — *modify:* colour constants, common helpers, per-state render fns + dispatch, simplified touch.
- `display/lib/icons.py` — *create:* 1-bit icons (refresh, check, idle-burst) as `bytes` + dimensions (mirrors `provider_logos.py`).
- `tools/fontgen/` — reuse for nothing here; icon conversion is a small inline script.
- **Untouched (host):** `confirm.py`, `display_service.py`, `send.py`, `serial_link.py`, `focus.py`, `keymap.json`, `broker.py`, `main.py`.

**Known layout values (from Figma frames, 240×280):**
- Header pill: ~`x64..176, y20, h31`, rounded; logo left, label right.
- Path line: `~/Dev/<project>` at ~`y71`; "on master" chip to its right (angled banner).
- Center badge (WORKING/DONE): `68×68` at ~`x85, y136`, dark circle, `48×48` icon centred.
- Permission buttons block: `176×113` at ~`x32, y113`; rows at local `y0 h43` (Approve), `y47 h31` (Reject), `y82 h31` (Continue).
- Dots: row at ~`y250`, centred; active = elongated pill.

**Sampled status backgrounds:** WORKING `#4088F8`, INPUT `#D09820`, DONE `#30A070`, PERMISSION `#F04848`, IDLE `#605870`.

---

## Task 0: Assets — sample tokens + export & convert icons

**Files:**
- Create: `display/lib/icons.py`

- [ ] **Step 1: Sample the INK / CHIP tokens from the Figma PNGs**

The status backgrounds are known; the dark pill (`INK`) and light chip (`CHIP`) tokens must be sampled. Re-download a Working + Permission PNG (the long-press URLs expire; re-fetch via `get_screenshot` for nodes `3:769` and `3:787`), then:
```bash
cd /tmp && /Users/christian/Dev/rp2040-status/.venv/bin/python - <<'PY'
from PIL import Image
from collections import Counter
for name,node in [("working","3:769"),("permission","3:787")]:
    im = Image.open(f"fig_{name}.png").convert("RGB"); w,h = im.size
    # Header pill sits ~y20..50, x75..165 -> sample INK there
    pill = [im.getpixel((x,y)) for x in range(80,150,4) for y in range(26,44,3)]
    def q(c): return tuple((v//8)*8 for v in c)
    print(name, "INK ~", Counter(q(p) for p in pill).most_common(1)[0][0])
PY
```
Record `INK` (dark pill ≈ `#3A3846`) and `CHIP` (light "on master" ≈ `#E8E8EC`). Use the measured values; the `~` values are fallbacks.

- [ ] **Step 2: Export the three icons from Figma as PNG**

Use `get_screenshot` (contentsOnly) for the icon nodes, `maxDimension` 96, then download:
- refresh (Working): node `3:623` (`MdOutlineCached`)
- check (Done): node `3:616` (`MdOutlineCheck`)
- idle-burst: node `3:846` (`Vector` in Idle `3:503`)
```bash
cd /tmp && curl -s -o ic_refresh.png "<url-3:623>" && curl -s -o ic_check.png "<url-3:616>" && curl -s -o ic_burst.png "<url-3:846>"
file ic_*.png
```

- [ ] **Step 3: Convert the icons to 1-bit `display/lib/icons.py`**

```bash
cd /Users/christian/Dev/rp2040-status && /Users/christian/Dev/rp2040-status/.venv/bin/python - <<'PY'
from PIL import Image
SIZE = 48
def to_1bit(path):
    im = Image.open(path).convert("RGBA").resize((SIZE,SIZE))
    px = im.load(); out = bytearray()
    stride = (SIZE+7)//8
    for y in range(SIZE):
        row = bytearray(stride)
        for x in range(SIZE):
            r,g,b,a = px[x,y]
            on = a > 100 and (r+g+b)/3 > 110   # sichtbares, helles Pixel = gesetzt
            if on: row[x>>3] |= (0x80 >> (x & 7))
        out += row
    return bytes(out)
icons = {"REFRESH":"/tmp/ic_refresh.png","CHECK":"/tmp/ic_check.png","BURST":"/tmp/ic_burst.png"}
lines = ['"""1-bit Status-Icons (48x48, MSB-first) — exportiert aus Figma."""','']
for name,p in icons.items():
    lines.append(f"{name} = bytes({to_1bit(p)!r})")
    lines.append(f"{name}_W = {SIZE}")
    lines.append(f"{name}_H = {SIZE}")
    lines.append("")
open("display/lib/icons.py","w").write("\n".join(lines))
print("geschrieben")
PY
```
> The `on` threshold may need tuning per icon (some Figma exports are dark-on-transparent vs light). Inspect each downloaded PNG; flip the luminance test if an icon comes out inverted. This is the one spot needing eyeballing before the board.

- [ ] **Step 4: Sanity + commit**

```bash
cd /Users/christian/Dev/rp2040-status
.venv/bin/python -c "import ast; ast.parse(open('display/lib/icons.py').read()); print('icons ok')"
.venv/bin/python -c "
import re,ast; src=open('display/lib/icons.py').read()
for n in ('REFRESH','CHECK','BURST'):
    b=ast.literal_eval(re.search(n+r' = (bytes\(.*?\))', src, re.S).group(1)); assert len(b)==48*48//8, (n,len(b))
print('all icons 288 bytes')
"
git add display/lib/icons.py
git commit -m "feat(display): Figma-exported 1-bit status icons (refresh/check/burst)"
```

---

## Task 1: Colour system + tokens (replace provider themes)

**Files:**
- Modify: `display/main.py`

- [ ] **Step 1: Replace `THEMES`/`_STATE`/`AMBER`/`INDIGO` with the status colour system**

Find the `THEMES = {...}`, `DEFAULT_THEME`, `theme_for`, `AMBER`, `INDIGO`, `_STATE`, `_LOGOS`, `_LOGO_SZ` block. Replace `THEMES`/`DEFAULT_THEME`/`theme_for`/`AMBER`/`INDIGO`/`_STATE` with:

```python
# Status -> Hintergrundfarbe (aus Figma gesampelt) == LED-Systematik.
STATUS_BG = {
    "WORKING":    st7789.color565(0x40, 0x88, 0xF8),
    "INPUT":      st7789.color565(0xD0, 0x98, 0x20),
    "DONE":       st7789.color565(0x30, 0xA0, 0x70),
    "PERMISSION": st7789.color565(0xF0, 0x48, 0x48),
    "IDLE":       st7789.color565(0x60, 0x58, 0x70),
}
FALLBACK_BG = STATUS_BG["IDLE"]

# Token-Palette (Pillen/Badges/Text auf dem Farbhintergrund).
INK    = st7789.color565(0x3A, 0x38, 0x46)   # ggf. aus Task-0-Messung ersetzen
ON_INK = st7789.WHITE
CHIP   = st7789.color565(0xE8, 0xE8, 0xEC)
SOFT   = st7789.color565(0xF0, 0xF0, 0xF0)
INK_TXT = st7789.color565(0x20, 0x1E, 0x28)   # Text auf hellem CHIP/Button

# Status -> Headline-Wort in der Header-Pille.
STATUS_LABEL = {
    "WORKING": "Working", "INPUT": "Input",
    "DONE": "Done", "PERMISSION": "Permission",
}

def bg_for(status):
    return STATUS_BG.get(status, FALLBACK_BG)
```

Keep `_LOGOS`, `_LOGO_SZ`, `_LOGO_CACHE`, `_draw_logo`, `_disc`, `wrap_px`, `_char_w`, `_wcenter` — still used.

- [ ] **Step 2: Sanity parse**

```bash
cd /Users/christian/Dev/rp2040-status && .venv/bin/python -c "import ast; ast.parse(open('display/main.py').read()); print('ok')"
```

- [ ] **Step 3: Commit**

```bash
cd /Users/christian/Dev/rp2040-status
git add display/main.py
git commit -m "feat(display): status->colour system replacing provider themes"
```

---

## Task 2: Common frame helpers (header / path / dots / badge)

**Files:**
- Modify: `display/main.py`

- [ ] **Step 1: Add the shared draw helpers (place after `_draw_logo`)**

```python
import icons

# Header-Pille (oben): Provider-Logo + Status-Label, auf INK.
HEADER_Y = 14
HEADER_H = 34
def draw_header(status, source):
    label = STATUS_LABEL.get(status, status[:12])
    lw = tft.write_width(fsm, label)
    pill_w = 30 + lw + 16            # Logo + Label + Padding
    px = (W - pill_w) // 2
    tft.fill_rect(px, HEADER_Y, pill_w, HEADER_H, INK)
    _draw_logo_small(source, px + 6, HEADER_Y + (HEADER_H - 18) // 2)
    tft.write(fsm, label, px + 30, HEADER_Y + (HEADER_H - LH) // 2, ON_INK, INK)

# Provider-Logo klein (18px) in INK-Pille; nutzt den vorhandenen blit_buffer-Pfad.
def _draw_logo_small(source, x, y):
    bmp = _LOGOS.get(source)
    if bmp is None:
        _disc(x + 9, y + 9, 8, ON_INK); return
    _blit_logo(bmp, source, x, y, 18, INK)   # siehe Hinweis unten

# Pfad + "on master"-Chip.
PATH_Y = 78
def draw_path(project, branch):
    p = "~/Dev/" + (project or "")
    tft.write(fsm, p[:22], PAD_X, PATH_Y, SOFT, None)  # bg=None -> transparent ueber Farbe? -> nutze bg=bg
    if branch:
        cx = PAD_X + tft.write_width(fsm, p[:22]) + 8
        bw = tft.write_width(fsm, branch[:14]) + 16
        tft.fill_rect(cx, PATH_Y - 3, bw, LH + 6, CHIP)
        tft.write(fsm, branch[:14], cx + 8, PATH_Y, INK_TXT, CHIP)

# Punkt-Navigation unten.
DOTS_Y = 250
def draw_dots(page, n, bg):
    if n <= 1:
        return
    n = min(n, 6)
    gap = 14; dot = 8; act = 28
    total = sum(act if i == page else dot for i in range(n)) + gap * (n - 1)
    x = (W - total) // 2
    for i in range(n):
        wdt = act if i == page else dot
        col = ON_INK if i == page else st7789.color565(0xC8, 0xC8, 0xD0)
        tft.fill_rect(x, DOTS_Y, wdt, dot, col)
        x += wdt + gap

# Zentrales Kreis-Badge mit 48er-Icon.
def draw_badge(icon, iw, ih):
    cx, cy = W // 2, 150
    _disc(cx, cy, 34, INK)
    _blit_icon(icon, iw, ih, cx - 24, cy - 24, ON_INK, INK)
```

> **Note on `_blit_logo`/`_blit_icon`:** the existing `_draw_logo` composes a logo into a `blit_buffer` against a *band* colour and blits at `LOGO_CX/BANNER_CY`. Refactor its inner compositor into a reusable `_blit_1bit_buf(bmp, detail, ink, band, x, y, size, srcW=48)` that both the header logo (band=`INK`) and the badge icons (band=`INK`) use. Define it in this task and have `_draw_logo` (legacy callers removed in Task 3) and these helpers call it. Exact code is produced when editing against the current `_draw_logo` body.

- [ ] **Step 2: Sanity parse + commit**

```bash
cd /Users/christian/Dev/rp2040-status && .venv/bin/python -c "import ast; ast.parse(open('display/main.py').read()); print('ok')"
git add display/main.py
git commit -m "feat(display): header pill, path+chip, dots, badge helpers"
```

---

## Task 3: Per-state render functions + dispatch (replace render)

**Files:**
- Modify: `display/main.py`

- [ ] **Step 1: Replace the whole `render()` (and remove `render_confirm`) with state renderers + dispatch**

```python
def _frame(status, s):
    bg = bg_for(status)
    tft.fill(bg)
    return bg

def _r_working(s, bg):
    draw_header("WORKING", s["source"]); draw_path(s["project"], s["branch"])
    draw_badge(icons.REFRESH, icons.REFRESH_W, icons.REFRESH_H)
    draw_dots(page, len(sessions), bg)

def _r_done(s, bg):
    draw_header("DONE", s["source"]); draw_path(s["project"], s["branch"])
    draw_badge(icons.CHECK, icons.CHECK_W, icons.CHECK_H)
    draw_dots(page, len(sessions), bg)

def _r_input(s, bg):
    draw_header("INPUT", s["source"])
    p = "~/Dev/" + (s["project"] or "")
    _wcenter(fbig, p[:14], 120, ON_INK, bg)
    if s["branch"]:
        _wcenter(fsm, s["branch"][:18], 150, INK_TXT, bg)  # auf Chip optional
    draw_dots(page, len(sessions), bg)

# Permission-Button-Hit-Boxen (global, auch im Touch-Handler genutzt).
PBTN = (("approve", "Approve", 113, 43, True),
        ("reject",  "Reject",  160, 31, False),
        ("continue","Continue",195, 31, False))
def _r_permission(s, bg):
    draw_header("PERMISSION", s["source"]); draw_path(s["project"], s["branch"])
    for action, label, y, h, primary in PBTN:
        col = INK if primary else CHIP
        txt = ON_INK if primary else INK_TXT
        tft.fill_rect(PAD_X, y, W - 2 * PAD_X, h, col)
        _wcenter(fsm, label, y + (h - LH) // 2, txt, col)
    draw_dots(page, len(sessions), bg)

def _r_idle():
    tft.fill(STATUS_BG["IDLE"])
    pill_w = tft.write_width(fsm, "Idle") + 24
    tft.fill_rect((W - pill_w)//2, HEADER_Y, pill_w, HEADER_H, CHIP)
    _wcenter(fsm, "Idle", HEADER_Y + (HEADER_H - LH)//2, INK_TXT, CHIP)
    _blit_icon(icons.BURST, icons.BURST_W, icons.BURST_H, W//2 - 24, 150 - 24, ON_INK, STATUS_BG["IDLE"])

RENDER = {"WORKING": _r_working, "DONE": _r_done, "INPUT": _r_input, "PERMISSION": _r_permission}

def render():
    if not sessions:
        _r_idle(); return
    s = sessions[page]
    status = s["status"]
    bg = _frame(status, s)
    fn = RENDER.get(status)
    if fn:
        fn(s, bg)
    else:                       # unbekannter Status -> Fallback
        draw_header(status, s["source"]); draw_path(s["project"], s["branch"])
        draw_dots(page, len(sessions), bg)
```

- [ ] **Step 2: Sanity parse + commit**

```bash
cd /Users/christian/Dev/rp2040-status && .venv/bin/python -c "import ast; ast.parse(open('display/main.py').read()); print('ok')"
git add display/main.py
git commit -m "feat(display): per-status render functions + dispatch (Figma layout)"
```

---

## Task 4: Simplify touch (swipe + tap-focus + permission buttons)

**Files:**
- Modify: `display/main.py`

- [ ] **Step 1: Remove long-press/confirm/chevron logic; keep swipe, tap-focus, add permission button taps**

Remove constants `LONGPRESS_MS`, `ACTIONABLE`, `_BTN`, `_BTN_Y`, `_BTN_H`, `_confirm_key`, `_lp_fired`, `_await_lift`, and the functions `_send_act`, `render_confirm`. Replace `handle_touch` with:

```python
def handle_touch():
    global _touch_start, _last_xy, _last_action_ms
    touched, x, y, gesture = tp.read()
    now = time.ticks_ms()
    deb = time.ticks_diff(now, _last_action_ms) >= TAP_DEBOUNCE_MS
    if deb and gesture == GESTURE_LEFT:
        _nav(1, now); _touch_start = None; _last_xy = None; return
    if deb and gesture == GESTURE_RIGHT:
        _nav(-1, now); _touch_start = None; _last_xy = None; return
    if touched:
        if _touch_start is None:
            _touch_start = (x, y, now)
        _last_xy = (x, y)
        return
    if _touch_start is None or _last_xy is None:
        _touch_start = None
        return
    sx, sy, st_ms = _touch_start
    ex, ey = _last_xy
    dx, dy = ex - sx, ey - sy
    _touch_start = None
    _last_xy = None
    if not deb or abs(dx) > TAP_MAX_MOVE or abs(dy) > TAP_MAX_MOVE:
        return
    if not sessions:
        return
    s = sessions[page]
    # PERMISSION: Tap auf einen Button -> act
    if s["status"] == "PERMISSION":
        for action, _label, by, h, _p in PBTN:
            if PAD_X <= ex <= W - PAD_X and by <= ey <= by + h:
                _last_action_ms = now
                sys.stdout.write("act %s %s\n" % (s["key"], action))
                return
    # sonst: Terminal fokussieren
    _last_action_ms = now
    sys.stdout.write("focus %s\n" % s["key"])
```

Also revert the `handle_line` `END` branch (no `_confirm_key` guard needed anymore):
```python
    elif line == "END":
        if _pending is not None:
            sessions = _pending
            _pending = None
            page = min(page, max(0, len(sessions) - 1))
            render()
```

- [ ] **Step 2: Verify no orphan references**

```bash
cd /Users/christian/Dev/rp2040-status
.venv/bin/python -c "import ast; ast.parse(open('display/main.py').read()); print('ok')"
grep -nE '_confirm_key|_await_lift|render_confirm|LONGPRESS|ACTIONABLE|_send_act|_BTN_Y' display/main.py || echo "(keine Reste)"
```

- [ ] **Step 3: Commit**

```bash
cd /Users/christian/Dev/rp2040-status
git add display/main.py
git commit -m "feat(display): swipe + tap-focus + inline permission buttons (drop long-press)"
```

---

## Task 5: Deploy + on-board verification (all states)

- [ ] **Step 1: Stop daemon, deploy icons + main.py, reset**

```bash
cd /Users/christian/Dev/rp2040-status && PORT=/dev/cu.usbmodem11334201
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.user.rp2040-display.plist 2>/dev/null; sleep 0.5
.venv/bin/python -c "import ast; ast.parse(open('display/main.py').read()); print('ok')"
mpremote connect $PORT fs cp display/lib/icons.py :lib/icons.py
mpremote connect $PORT fs cp display/main.py :main.py
mpremote connect $PORT reset
```

- [ ] **Step 2: Send one frame per status and look**

```bash
.venv/bin/python - <<'PY'
import serial, time
s = serial.Serial("/dev/cu.usbmodem11334201", 115200, timeout=0.3); time.sleep(0.5); s.read(300)
s.write(("LIST 4\n"
  "S k1|WORKING|claude-code|chromatic|master|\n"
  "S k2|DONE|codex|chromatic|master|\n"
  "S k3|INPUT|claude-code|chromatic|master|\n"
  "S k4|PERMISSION|claude-code|chromatic|master|\n"
  "END\n").encode())
time.sleep(0.5); s.close(); print("Frame gesendet — durchwischen.")
PY
```
Expected (swipe between them): WORKING blue + refresh badge, DONE green + check, INPUT yellow + big path, PERMISSION red + 3 buttons. Dots track position. Empty list (`LIST 0`) → IDLE grey + burst. **Iterate layout values on-board if needed** (header/path/badge/button/dot positions, logo size, colour tweaks) and re-deploy.

- [ ] **Step 3: Verify interactions (serial capture)**

```bash
.venv/bin/python /tmp/rp2040_tap_test.py   # zeigt RX-Zeilen; auf PERMISSION Buttons tippen -> 'act k4 approve/reject/continue', sonst Tap -> 'focus <key>'
```
Expected: tapping an Approve/Reject/Continue button on the PERMISSION screen emits `act k4 <action>`; tapping elsewhere (or on a non-permission screen) emits `focus <key>`; swipe changes page.

- [ ] **Step 4: Host regression + re-enable daemon + commit any on-board tweaks**

```bash
cd /Users/christian/Dev/rp2040-status
.venv/bin/pytest tests/ -q | tail -1     # erwartet: 44 passed (Host unangetastet)
git diff --stat -- confirm.py display_service.py send.py keymap.json broker.py main.py   # erwartet: leer
git add display/main.py display/lib/icons.py
git commit -m "fix(display): on-board layout tuning for status redesign" --allow-empty
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.user.rp2040-display.plist
```

- [ ] **Step 5: Update README**

In `README.md`, update the touch-display section: colour now encodes status (same table as the LED), provider shown via the small header logo, PERMISSION shows inline Approve/Reject/Continue (no long-press). Remove the "long-press confirm" subsection's gesture description (keep keymap/kill-switch — the `act` backend is unchanged). Commit:
```bash
git add README.md
git commit -m "docs: display now status-coloured (LED-aligned); inline permission buttons"
```

---

## Self-Review-Notiz (vom Autor)

- **Spec-Abdeckung:** Farb-System (Task 1), Layout/Komponenten Header/Pfad/Dots/Badge (Task 2), per-Status-Layouts + Dispatch + Fallback (Task 3), Touch-Modell swipe/tap/permission + Long-press-Entfall (Task 4), Icons aus Figma (Task 0), Punkt-Deckel + Edge-Cases (Task 2 draw_dots cap, Task 3 idle/empty + unknown-status), Tests Host-Regression + Board + Icon-Maße (Task 0/5). Host-unverändert wird in Task 5 Step 4 verifiziert.
- **Namens-Konsistenz:** `STATUS_BG`/`bg_for`/`INK`/`ON_INK`/`CHIP`/`SOFT`/`INK_TXT`, `draw_header`/`draw_path`/`draw_dots`/`draw_badge`, `_blit_icon`/`_blit_1bit_buf`, `PBTN`, `RENDER` — über Tasks hinweg identisch verwendet.
- **Bewusst offen (Board-Iteration):** exakte Pixel-Baselines/Paddings, Icon-Threshold-Richtung, INK/CHIP-Feinwerte — alle in Task 0/5 als Tuning-Punkte markiert (nicht als TBD-Logik, sondern visuelles Feintuning, das nur am Panel entschieden werden kann).
- **`_blit_1bit_buf`-Refactor:** Task 2 extrahiert den Compositor aus dem bestehenden `_draw_logo`; der exakte Code entsteht gegen den Ist-Stand von `_draw_logo` (ein klar abgegrenzter Refactor, kein Platzhalter-Verhalten).
