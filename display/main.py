# display/main.py — MicroPython. Liest LIST-Frames ueber USB-Serial,
# rendert die Session-Liste mit Source-Theme. (boot.py hat SYS_EN bereits gehalten.)
import sys, select, time
from machine import Pin, SPI
import st7789py as st7789
import vga2_8x8 as font
from cst816 import CST816

# --- Display (ST7789, 240x280, row-offset 20) ---
spi = SPI(1, baudrate=40_000_000, sck=Pin(6), mosi=Pin(7))
tft = st7789.ST7789(spi, 240, 280, reset=Pin(8, Pin.OUT), dc=Pin(4, Pin.OUT),
                    cs=Pin(5, Pin.OUT), backlight=Pin(15, Pin.OUT), rotation=0)
tp = CST816()

W, H = 240, 280
NAV_H = 48

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
    marker = "%d / %d" % (page + 1, len(sessions))
    tft.text(font, marker, W // 2 - 24, H - NAV_H + 16, fg, bg)
    tft.text(font, "<", 16, H - NAV_H + 16, accent if page > 0 else bg, bg)
    tft.text(font, ">", W - 24, H - NAV_H + 16, accent if page < len(sessions) - 1 else bg, bg)

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
