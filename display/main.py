# display/main.py — MicroPython. Liest LIST-Frames ueber USB-Serial,
# rendert die Session-Liste mit Source-Theme. (boot.py hat SYS_EN bereits gehalten.)
import sys, select, time
from machine import Pin, SPI
import st7789py as st7789
import vga2_8x8 as font
import vga2_16x16 as bigfont
from cst816 import CST816

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

def wrap_text(text, max_chars, max_lines):
    """Bricht text in <=max_lines Zeilen a max_chars um; bevorzugt Trenner
    (-_./ ), sonst harter Umbruch. Mehrzeilig wie Buddys Title-Block."""
    out = []
    rest = text or ""
    while rest and len(out) < max_lines:
        if len(rest) <= max_chars:
            out.append(rest)
            return out
        cut = 0
        for i in range(min(max_chars, len(rest) - 1), 0, -1):
            if rest[i] in _WRAP_SEPS:
                cut = i + 1
                break
        if cut <= 0:
            cut = max_chars
        out.append(rest[:cut])
        rest = rest[cut:]
    return out

def render():
    if not sessions:
        tft.fill(st7789.BLACK)
        tft.text(font, "IDLE", W // 2 - 16, H // 2, st7789.color565(0, 200, 220), st7789.BLACK)
        return
    s = sessions[page]
    fg, bg, accent, soft = theme_for(s["source"])
    tft.fill(bg)
    # Provider-Akzentband (hoch genug fuer die runden Ecken), Status darin.
    tft.fill_rect(0, 0, W, BANNER_H, accent)
    tft.text(bigfont, s["status"][:12], PAD_X, (BANNER_H - 16) // 2, bg, accent)
    # Body: Projekt gross (mehrzeilig), Branch/Titel klein darunter.
    py = BODY_TOP
    for ln in wrap_text(s["project"], 12, 2):
        tft.text(bigfont, ln, PAD_X, py, fg, bg)
        py += 20
    py += 6
    if s["branch"]:
        tft.text(font, s["branch"][:24], PAD_X, py, soft, bg)
        py += 16
    if s["title"]:
        tft.text(font, s["title"][:24], PAD_X, py, fg, bg)
    # Nav-Strip unten: Chevrons + Zaehler, von der unteren Kante weggehalten.
    cy_big = NAV_TOP + (NAV_H - 16) // 2
    cy_txt = NAV_TOP + (NAV_H - 8) // 2
    marker = "%d / %d" % (page + 1, len(sessions))
    tft.text(font, marker, (W - len(marker) * 8) // 2, cy_txt, soft, bg)
    tft.text(bigfont, "<", PAD_X, cy_big, accent if page > 0 else bg, bg)
    tft.text(bigfont, ">", W - PAD_X - 16, cy_big, accent if page < len(sessions) - 1 else bg, bg)

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
