# display/main.py — MicroPython. Liest LIST-Frames ueber USB-Serial,
# rendert die Session-Liste mit Source-Theme. (boot.py hat SYS_EN bereits gehalten.)
import sys, select, time
from machine import Pin, SPI
import st7789py as st7789
import round24 as fbig          # proportionaler Headline-/Titel-Font (Arial Rounded Bold)
import round15 as fsm           # proportionaler Meta-/Nav-Font
from cst816 import CST816
from provider_logos import OPENAI, CLAUDE, CLAUDE_DETAIL, PI

LH = fsm.HEIGHT                 # Zeilenhoehe klein
LH_BIG = fbig.HEIGHT            # Zeilenhoehe gross

# --- Display (ST7789, 240x280, row-offset 20) ---
# st7789py kennt 240x280 nicht ab Werk -> eigene Rotationstabelle.
# Format je Rotation: (madctl, width, height, xstart, ystart, needs_swap).
# 280-Zeilen-Fenster sitzt mit ystart=20 im 240x320-Controller (am Board verifiziert).
_ROTATIONS = (
    (0x00, 240, 280, 0, 20, False),
    (0x60, 280, 240, 20, 0, False),
    (0xc0, 240, 280, 0, 20, False),
    (0xa0, 280, 240, 20, 0, False),
)
spi = SPI(1, baudrate=40_000_000, sck=Pin(6), mosi=Pin(7))
tft = st7789.ST7789(spi, 240, 280, reset=Pin(8, Pin.OUT), dc=Pin(4, Pin.OUT),
                    cs=Pin(5, Pin.OUT), backlight=Pin(15, Pin.OUT), rotation=0,
                    custom_rotations=_ROTATIONS)
tp = CST816()

W, H = 240, 280
# Layout an Buddy angelehnt: hohes Akzentband + Nav-Strip halten Inhalt von den
# runden Display-Ecken weg; grosszuegiges horizontales Padding.
BANNER_H = 59
NAV_H = 80
PAD_X = 17
BODY_TOP = BANNER_H + 18   # 77
NAV_TOP = H - NAV_H        # 200
BANNER_CY = BANNER_H // 2  # 29
LOGO_SIZE = 48
LOGO_CX = 36               # Provider-Logo links im Banner
IND_CX = 207               # Status-Indikator rechts im Banner

# Status -> (Headline, Akzent-Override). Override=None -> Provider-Akzent behalten.
AMBER = st7789.color565(245, 158, 11)
INDIGO = st7789.color565(99, 102, 241)
_STATE = {
    "WORKING":    ("WORKING", None),
    "DONE":       ("DONE", None),
    "PERMISSION": ("APPROVAL", AMBER),
    "INPUT":      ("QUESTION", INDIGO),
}

_LOGOS = {"codex": OPENAI, "claude-code": CLAUDE, "claude": CLAUDE, "pi": PI}
_LOGO_SZ = {"codex": 40}   # OpenAI-Marke fuellt ihr Feld staerker -> optisch kleiner rendern

# Theme: (fg, bg, accent, soft) je Source. accent = Provider-Farbband oben.
THEMES = {
    "codex":       (st7789.color565(24, 28, 32),   st7789.color565(236, 240, 234), st7789.color565(16, 170, 95),  st7789.color565(120, 130, 130)),
    "claude-code": (st7789.color565(40, 24, 16),   st7789.color565(236, 222, 202), st7789.color565(196, 92, 52),  st7789.color565(150, 122, 96)),
    "antigravity": (st7789.color565(225, 228, 240), st7789.color565(18, 18, 28),   st7789.color565(96, 140, 255),  st7789.color565(140, 146, 165)),
}
DEFAULT_THEME = (st7789.WHITE, st7789.BLACK, st7789.color565(0, 200, 220), st7789.color565(120, 120, 120))

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
    while poll.poll(0):
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

_WRAP_SEPS = "-_./ "

def _char_w(fnt, ch):
    try:
        return fnt.WIDTHS[fnt.MAP.index(ch)]
    except ValueError:
        return fnt.MAX_WIDTH

def wrap_px(text, max_px, max_lines, fnt):
    """Bricht text in <=max_lines Zeilen, gemessen in Pixeln (proportionaler Font);
    bevorzugt Trenner (-_./ ), sonst harter Umbruch."""
    out = []
    rest = text or ""
    while rest and len(out) < max_lines:
        w = 0
        cut = len(rest)
        for i, ch in enumerate(rest):
            w += _char_w(fnt, ch)
            if w > max_px:
                cut = i
                break
        if cut >= len(rest):
            out.append(rest)
            return out
        br = 0
        for i in range(cut, 0, -1):
            if rest[i - 1] in _WRAP_SEPS:
                br = i
                break
        if br <= 0:
            br = cut if cut > 0 else 1
        out.append(rest[:br])
        rest = rest[br:]
    return out

def _disc(cx, cy, r, color):
    # gefuellter Kreis als horizontale Spannen (eine fill_rect je Zeile) -> schnell.
    for dy in range(-r, r + 1):
        dx = int((r * r - dy * dy) ** 0.5)
        tft.fill_rect(cx - dx, cy + dy, 2 * dx + 1, 1, color)

_LOGO_CACHE = {}

def _draw_logo(source, ink, band):
    """Provider-Logo links im Banner via blit_buffer (eine SPI-Schreiboperation).
    Logo-Bits -> ink, Hintergrund -> band; Claude-Detail erodiert zurueck auf band.
    Komponierte Puffer werden je (source, ink, band) gecacht."""
    bmp = _LOGOS.get(source)
    if bmp is None:
        _disc(LOGO_CX, BANNER_CY, 18, ink)
        return
    sz = _LOGO_SZ.get(source, 48)
    x = LOGO_CX - sz // 2
    y = BANNER_CY - sz // 2
    ck = (source, ink, band)
    buf = _LOGO_CACHE.get(ck)
    if buf is None:
        detail = CLAUDE_DETAIL if source in ("claude-code", "claude") else None
        ih, il = ink >> 8, ink & 0xFF
        bh, bl = band >> 8, band & 0xFF
        buf = bytearray(sz * sz * 2)
        o = 0
        for row in range(sz):
            rb = (row * 48 // sz) * 6
            for col in range(sz):
                sc = col * 48 // sz
                m = 0x80 >> (sc & 7)
                on = bmp[rb + (sc >> 3)] & m
                if on and detail is not None and (detail[rb + (sc >> 3)] & m):
                    on = 0
                if on:
                    buf[o] = ih; buf[o + 1] = il
                else:
                    buf[o] = bh; buf[o + 1] = bl
                o += 2
        _LOGO_CACHE[ck] = buf
    tft.blit_buffer(buf, x, y, sz, sz)

def _draw_indicator(status, cx, cy, ink, band):
    """Status-Icon rechts im Banner (in ink-Farbe auf dem Band)."""
    if status == "WORKING":
        for i in range(3):
            _disc(cx - 8 + i * 8, cy, 2, ink)
    elif status == "DONE":
        tft.line(cx - 8, cy + 1, cx - 3, cy + 6, ink)
        tft.line(cx - 3, cy + 6, cx + 8, cy - 7, ink)
        tft.line(cx - 8, cy + 2, cx - 3, cy + 7, ink)
        tft.line(cx - 3, cy + 7, cx + 8, cy - 6, ink)
    elif status == "PERMISSION":
        tft.line(cx, cy - 8, cx + 9, cy, ink)
        tft.line(cx + 9, cy, cx, cy + 8, ink)
        tft.line(cx, cy + 8, cx - 9, cy, ink)
        tft.line(cx - 9, cy, cx, cy - 8, ink)
        tft.fill_rect(cx - 1, cy - 4, 3, 8, ink)
    elif status == "INPUT":
        tft.write(fbig, "?", cx - tft.write_width(fbig, "?") // 2, cy - LH_BIG // 2, ink, band)
    else:
        _disc(cx, cy, 3, ink)

def _wcenter(fnt, s, y, fg, bg, floor_x=0):
    x = max(floor_x, (W - tft.write_width(fnt, s)) // 2)
    tft.write(fnt, s, x, y, fg, bg)

def render():
    if not sessions:
        tft.fill(st7789.BLACK)
        _wcenter(fbig, "IDLE", H // 2 - LH_BIG // 2, st7789.color565(0, 200, 220), st7789.BLACK)
        return
    s = sessions[page]
    fg, bg, accent, soft = theme_for(s["source"])
    headline, override = _STATE.get(s["status"], (s["status"][:12], None))
    band = override if override is not None else accent
    tft.fill(bg)
    # --- Banner: Logo | zentrierte Headline | Status-Indikator (alles in bg auf dem Band) ---
    tft.fill_rect(0, 0, W, BANNER_H, band)
    _draw_logo(s["source"], bg, band)
    _wcenter(fbig, headline, (BANNER_H - LH_BIG) // 2, bg, band,
             floor_x=LOGO_CX + LOGO_SIZE // 2 + 4)
    _draw_indicator(s["status"], IND_CX, BANNER_CY, bg, band)
    # --- Body: grosser Titel (sonst Projekt) + Meta-Zeile Projekt . Branch ---
    title = s["title"] or s["project"]
    py = BODY_TOP
    for ln in wrap_px(title, W - 2 * PAD_X, 2, fbig):
        tft.write(fbig, ln, PAD_X, py, fg, bg)
        py += LH_BIG + 2
    meta_y = NAV_TOP - LH - 6
    proj = s["project"]
    tft.write(fsm, proj, PAD_X, meta_y, soft, bg)
    if s["branch"]:
        bx = PAD_X + tft.write_width(fsm, proj) + 6
        _disc(bx + 3, meta_y + LH // 2, 1, soft)
        tft.write(fsm, s["branch"], bx + 9, meta_y, soft, bg)
    # --- Nav-Strip: Chevrons + Zaehler ---
    cy_big = NAV_TOP + (NAV_H - LH_BIG) // 2
    cy_txt = NAV_TOP + (NAV_H - LH) // 2
    marker = "%d / %d" % (page + 1, len(sessions))
    _wcenter(fsm, marker, cy_txt, soft, bg)
    tft.write(fbig, "<", PAD_X, cy_big, accent if page > 0 else bg, bg)
    tft.write(fbig, ">", W - PAD_X - tft.write_width(fbig, ">"), cy_big,
              accent if page < len(sessions) - 1 else bg, bg)

# --- Touch-Verarbeitung ---
TAP_MAX_MOVE = 28
TAP_DEBOUNCE_MS = 280   # ein Fingerdruck = eine Aktion (gegen Touch-Jitter)
GESTURE_LEFT = 0x03     # CST816: Wisch nach links  -> naechste Session
GESTURE_RIGHT = 0x04    # CST816: Wisch nach rechts -> vorige Session
_touch_start = None  # (x, y, t)
_last_xy = None
_last_action_ms = -1000

def _nav(delta, now):
    global page, _last_action_ms
    np = page + delta
    if 0 <= np < len(sessions):
        page = np
        _last_action_ms = now
        render()

def handle_touch():
    global _touch_start, _last_xy, _last_action_ms
    touched, x, y, gesture = tp.read()
    now = time.ticks_ms()
    deb = time.ticks_diff(now, _last_action_ms) >= TAP_DEBOUNCE_MS
    # Hardware-Swipe-Geste des CST816 (ueberall am Schirm, kein Jitter-Problem)
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
    if not deb:
        return
    # Tap (kleine Bewegung): Nav-Strip -> Blaettern, sonst -> Session fokussieren
    if abs(dx) <= TAP_MAX_MOVE and abs(dy) <= TAP_MAX_MOVE:
        if sy >= H - NAV_H:
            _nav(-1 if ex < W // 2 else 1, now)
        elif sessions:
            _last_action_ms = now
            sys.stdout.write("focus %s\n" % sessions[page]["key"])

# --- Main Loop ---
sys.stdout.write("ready\n")
render()
while True:
    read_serial_lines()
    handle_touch()
    time.sleep_ms(20)
