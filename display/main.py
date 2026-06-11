# display/main.py — MicroPython. Liest LIST-Frames ueber USB-Serial und rendert
# die aktuelle Session status-gefaerbt (Farbe = Status, wie die LED).
import sys, select, time, math
from machine import Pin, SPI
import st7789py as st7789
import round24 as fbig          # proportionaler grosser Font (Arial Rounded Bold)
import round15 as fsm           # proportionaler kleiner Font
from cst816 import CST816
from provider_logos import OPENAI, CLAUDE, CLAUDE_DETAIL, PI
from sel import resolve_page
import icons

LH = fsm.HEIGHT
LH_BIG = fbig.HEIGHT

# --- Display (ST7789, 240x280, row-offset 20; eigene Rotationstabelle) ---
_ROTATIONS = (
    (0x00, 240, 280, 0, 20, False),
    (0x60, 280, 240, 20, 0, False),
    (0xc0, 240, 280, 0, 20, False),
    (0xa0, 280, 240, 20, 0, False),
)
spi = SPI(1, baudrate=40_000_000, sck=Pin(6), mosi=Pin(7))
tft = st7789.ST7789(spi, 240, 280, reset=Pin(8, Pin.OUT), dc=Pin(4, Pin.OUT),
                    cs=Pin(5, Pin.OUT), backlight=None, rotation=0,
                    custom_rotations=_ROTATIONS)
tp = CST816()

from machine import PWM
bl = PWM(Pin(15), freq=20000)      # >20kHz -> kein hoerbares Fiepen
BL_FULL = 65535
def bl_set(frac):                  # frac 0.0..1.0 -> Helligkeit (Backlight-Atmen)
    bl.duty_u16(int(max(0.0, min(1.0, frac)) * BL_FULL))
bl_set(1.0)

W, H = 240, 280
PAD_X = 16

# --- Farb-System: Status -> Hintergrund (aus Figma gesampelt) == LED-Systematik ---
STATUS_BG = {
    "WORKING":    st7789.color565(0x40, 0x88, 0xF8),   # blau
    "INPUT":      st7789.color565(0xD0, 0x98, 0x20),   # gelb/gold
    "DONE":       st7789.color565(0x30, 0xA0, 0x70),   # gruen
    "PERMISSION": st7789.color565(0xF0, 0x48, 0x48),   # rot
    "IDLE":       st7789.color565(0x60, 0x58, 0x70),   # slate-grau
}
FALLBACK_BG = STATUS_BG["IDLE"]

# Token-Palette (Pillen/Badges/Text auf dem Farbhintergrund)
INK     = st7789.color565(0x60, 0x58, 0x70)   # dunkle Pille / Kreis-Badge / Primaer-Button (== idle bg)
ON_INK  = st7789.WHITE                        # Text/Icon auf INK
CHIP    = st7789.color565(0xD8, 0xD8, 0xD8)   # heller "on master"-Chip / Sekundaer-Button
SOFT    = st7789.WHITE                         # Pfad-Text auf Farbe
INK_TXT = st7789.color565(0x28, 0x26, 0x30)   # dunkler Text auf hellem Chip/Button

STATUS_LABEL = {"WORKING": "Working", "INPUT": "Input",
                "DONE": "Done", "PERMISSION": "Permission"}

def bg_for(status):
    return STATUS_BG.get(status, FALLBACK_BG)

_LOGOS = {"codex": OPENAI, "claude-code": CLAUDE, "claude": CLAUDE, "pi": PI}

# --- Layout ---
HEADER_Y = 14
HEADER_H = 34
HLOGO = 22                 # Provider-Logo-Groesse in der Header-Pille
PATH_Y = 80
BADGE_CY = 162
BADGE_R = 34
DOTS_Y = 252
# Permission-Buttons: (action, label, y, h, primary)
PBTN = (("approve",  "Approve",  112, 42, True),
        ("reject",   "Reject",   160, 30, False),
        ("continue", "Continue", 194, 30, False))

# --- Animations-State ---
ANIM_MS = 50            # ~20 fps
PULSE_STATES = ("INPUT", "PERMISSION")
DONE_POP_MS = 260
_anim_phase = 0
_anim_last = -1000
_last_status = None
_done_start = -10000
_marquee_off = 0
_path_over = False

# --- Modell ---
sessions = []   # Liste dicts: {key,status,source,project,branch,title}
page = 0
sel_key = None  # per Wisch angewaehlter Session-Key; haelt die Auswahl ueber
                # Reorder/Add/Remove hinweg stabil (None = Positions-Default)

poll = select.poll()
poll.register(sys.stdin, select.POLLIN)
_inbuf = ""
_pending = None

def read_serial_lines():
    global _inbuf
    while poll.poll(0):
        _inbuf += sys.stdin.read(1)
    while "\n" in _inbuf:
        line, _inbuf = _inbuf.split("\n", 1)
        handle_line(line.strip())

def handle_line(line):
    global _pending, sessions, page, sel_key
    if line.startswith("LIST"):
        _pending = []
    elif line == "END":
        if _pending is not None:
            sessions = _pending
            _pending = None
            keys = [s["key"] for s in sessions]
            page = resolve_page(keys, sel_key, page)
            # Auswahl verloren (Session beendet) -> zurueck auf Positions-Default.
            if sel_key is not None and sel_key not in keys:
                sel_key = None
            render()
    elif line.startswith("S ") and _pending is not None:
        parts = line[2:].split("|")
        while len(parts) < 7:
            parts.append("")
        _pending.append({"key": parts[0], "status": parts[1], "source": parts[2],
                         "project": parts[3], "branch": parts[4], "title": parts[5],
                         "path": parts[6]})

# --- Zeichen-Primitive ---
def _disc(cx, cy, r, color):
    for dy in range(-r, r + 1):
        dx = int((r * r - dy * dy) ** 0.5)
        tft.fill_rect(cx - dx, cy + dy, 2 * dx + 1, 1, color)

def _rrect(x, y, w, h, r, color):
    """Abgerundetes Rechteck (Pille/Button/Chip)."""
    if r > h // 2:
        r = h // 2
    tft.fill_rect(x + r, y, w - 2 * r, h, color)
    tft.fill_rect(x, y + r, r, h - 2 * r, color)
    tft.fill_rect(x + w - r, y + r, r, h - 2 * r, color)
    _disc(x + r, y + r, r, color)
    _disc(x + w - r - 1, y + r, r, color)
    _disc(x + r, y + h - r - 1, r, color)
    _disc(x + w - r - 1, y + h - r - 1, r, color)

def _wcenter(fnt, s, y, fg, bg):
    tft.write(fnt, s, max(0, (W - tft.write_width(fnt, s)) // 2), y, fg, bg)

# --- Laufschrift (Pfad-Overflow) ---
MARQUEE_SPEED = 2      # px / Tick
MARQUEE_GAP = 26       # Luecke zwischen den Loop-Kopien

def _pathstr(s):
    return s["path"] or s["project"] or ""

def _buf_text(buf, period, font, text, bx, by, fg):
    """Rastert Text (nur fg-Pixel) in einen vorgefuellten RGB565-Puffer an (bx, by)."""
    fh, fl = fg >> 8, fg & 0xFF
    OW = font.OFFSET_WIDTH
    x = bx
    for ch in text:
        try:
            ci = font.MAP.index(ch)
        except ValueError:
            continue
        off = ci * OW
        bs = font.OFFSETS[off]
        if OW > 1:
            bs = (bs << 8) + font.OFFSETS[off + 1]
        if OW > 2:
            bs = (bs << 8) + font.OFFSETS[off + 2]
        cw = font.WIDTHS[ci]
        for px in range(cw * font.HEIGHT):
            if font.BITMAPS[bs >> 3] & (1 << (7 - (bs & 7))):
                di = (((by + px // cw) * period) + (x + px % cw)) * 2
                buf[di] = fh; buf[di + 1] = fl
            bs += 1
        x += cw

def _buf_rrect(buf, period, x, y, w, h, r, color):
    """Abgerundetes Rechteck in den Puffer (mitscrollender Branch-Chip)."""
    ch, cl = color >> 8, color & 0xFF
    for ry in range(h):
        for rx in range(w):
            dx = dy = 0
            if rx < r and ry < r:
                dx, dy = r - 1 - rx, r - 1 - ry
            elif rx >= w - r and ry < r:
                dx, dy = rx - (w - r), r - 1 - ry
            elif rx < r and ry >= h - r:
                dx, dy = r - 1 - rx, ry - (h - r)
            elif rx >= w - r and ry >= h - r:
                dx, dy = rx - (w - r), ry - (h - r)
            if dx * dx + dy * dy > r * r:
                continue
            di = ((y + ry) * period + (x + rx)) * 2
            buf[di] = ch; buf[di + 1] = cl

def _render_text_buf(font, text, fg, bg):
    """Nur-Text-Laufzeile (z.B. grosser INPUT-Pfad)."""
    period = tft.write_width(font, text) + MARQUEE_GAP
    h = font.HEIGHT
    buf = bytearray(bytes((bg >> 8, bg & 0xFF)) * (period * h))
    _buf_text(buf, period, font, text, 0, 0, fg)
    return buf, period, h

def _render_pathline_buf(path, branch, bg):
    """Pfad + mitscrollender Branch-Chip in einen Puffer (Hoehe = Chip-Hoehe)."""
    h = LH + 6
    ty = (h - fsm.HEIGHT) // 2
    pw = tft.write_width(fsm, path)
    chipw = (tft.write_width(fsm, branch[:14]) + 16) if branch else 0
    content = pw + ((8 + chipw) if branch else 0)
    period = content + MARQUEE_GAP
    buf = bytearray(bytes((bg >> 8, bg & 0xFF)) * (period * h))
    _buf_text(buf, period, fsm, path, 0, ty, SOFT)
    if branch:
        cx = pw + 8
        _buf_rrect(buf, period, cx, 0, chipw, h, 5, CHIP)
        _buf_text(buf, period, fsm, branch[:14], cx + 8, ty, INK_TXT)
    return buf, period, h

# Marquee-Cache (eine aktive Laufschrift): periodischer Puffer + Fenster.
_mq_key = None
_mq_buf = None
_mq_period = 0
_mq_h = 0
_mq_win = None

def _mq_ensure(key, builder, avail):
    global _mq_key, _mq_buf, _mq_period, _mq_h, _mq_win
    if key != _mq_key:
        _mq_buf, _mq_period, _mq_h = builder()
        _mq_win = bytearray(avail * _mq_h * 2)
        _mq_key = key
    elif _mq_win is None or len(_mq_win) != avail * _mq_h * 2:
        _mq_win = bytearray(avail * _mq_h * 2)

def _mq_blit(x, y, avail, off):
    # Fenster [off, off+avail) mit Wrap im RAM bauen -> ein blit_buffer (flackerfrei).
    o = off % _mq_period
    stride = _mq_period * 2
    aw = avail * 2
    for r in range(_mq_h):
        src = r * stride
        dst = r * aw
        first = (_mq_period - o) * 2
        if first >= aw:
            _mq_win[dst:dst + aw] = _mq_buf[src + o * 2:src + o * 2 + aw]
        else:
            _mq_win[dst:dst + first] = _mq_buf[src + o * 2:src + stride]
            _mq_win[dst + first:dst + aw] = _mq_buf[src:src + (aw - first)]
    tft.blit_buffer(_mq_win, x, y, avail, _mq_h)

# 1-Bit-Bitmap (Logo/Icon) via blit_buffer, skaliert, eingefaerbt; gecacht.
_BUF_CACHE = {}
def _blit_1bit(bmp, detail, ink, band, x, y, size, src=48):
    ck = (id(bmp), ink, band, size)
    buf = _BUF_CACHE.get(ck)
    if buf is None:
        srow = (src + 7) // 8
        ih, il = ink >> 8, ink & 0xFF
        bh, bl = band >> 8, band & 0xFF
        buf = bytearray(size * size * 2)
        o = 0
        for row in range(size):
            rb = (row * src // size) * srow
            for col in range(size):
                sc = col * src // size
                m = 0x80 >> (sc & 7)
                on = bmp[rb + (sc >> 3)] & m
                if on and detail is not None and (detail[rb + (sc >> 3)] & m):
                    on = 0
                if on:
                    buf[o] = ih; buf[o + 1] = il
                else:
                    buf[o] = bh; buf[o + 1] = bl
                o += 2
        _BUF_CACHE[ck] = buf
    tft.blit_buffer(buf, x, y, size, size)

# 8-Bit-Coverage-Bitmap ink-ueber-bg geblendet (AA), skaliert, gecacht.
_AA_CACHE = {}
def _unpack565(c):
    return ((c >> 11) & 0x1F) << 3, ((c >> 5) & 0x3F) << 2, (c & 0x1F) << 3

def _blit_aa(cov, ink, bg, x, y, size, src, frame=0):
    ck = (id(cov), ink, bg, size, frame)
    buf = _AA_CACHE.get(ck)
    if buf is None:
        ir, ig, ib = _unpack565(ink)
        br, bgc, bb = _unpack565(bg)
        buf = bytearray(size * size * 2)
        o = 0
        sm1 = src - 1
        scale = src / size
        for row in range(size):
            fy = row * scale
            y0 = int(fy); y1 = y0 + 1 if y0 < sm1 else y0
            ty = fy - y0
            r0 = y0 * src; r1 = y1 * src
            for col in range(size):
                fx = col * scale
                x0 = int(fx); x1 = x0 + 1 if x0 < sm1 else x0
                tx = fx - x0
                # bilineare Coverage -> glatte Kanten bei jeder Skalierung
                a = (cov[r0 + x0] * (1 - tx) * (1 - ty) + cov[r0 + x1] * tx * (1 - ty)
                     + cov[r1 + x0] * (1 - tx) * ty + cov[r1 + x1] * tx * ty)
                r = int((ir * a + br * (255 - a)) / 255)
                g = int((ig * a + bgc * (255 - a)) / 255)
                b = int((ib * a + bb * (255 - a)) / 255)
                c = st7789.color565(r, g, b)
                buf[o] = c >> 8; buf[o + 1] = c & 0xFF
                o += 2
        _AA_CACHE[ck] = buf
    tft.blit_buffer(buf, x, y, size, size)

# --- Gemeinsame Komponenten ---
def draw_header(status, source):
    label = STATUS_LABEL.get(status, status[:12])
    lw = tft.write_width(fsm, label)
    pw = 8 + HLOGO + 6 + lw + 12
    px = (W - pw) // 2
    _rrect(px, HEADER_Y, pw, HEADER_H, HEADER_H // 2, INK)
    ly = HEADER_Y + (HEADER_H - HLOGO) // 2
    bmp = _LOGOS.get(source)
    if bmp is not None:
        detail = CLAUDE_DETAIL if source in ("claude-code", "claude") else None
        _blit_1bit(bmp, detail, ON_INK, INK, px + 8, ly, HLOGO)
    else:
        _disc(px + 8 + HLOGO // 2, HEADER_Y + HEADER_H // 2, HLOGO // 2 - 2, ON_INK)
    tft.write(fsm, label, px + 8 + HLOGO + 6, HEADER_Y + (HEADER_H - LH) // 2, ON_INK, INK)

def draw_path(path, branch, bg, off=0):
    avail = W - 2 * PAD_X
    pw = tft.write_width(fsm, path)
    chipw = (tft.write_width(fsm, branch[:14]) + 16) if branch else 0
    content = pw + ((8 + chipw) if branch else 0)
    if content <= avail:                        # passt -> statisch (Pfad, Chip dahinter)
        tft.fill_rect(PAD_X, PATH_Y - 3, avail, LH + 6, bg)
        tft.write(fsm, path, PAD_X, PATH_Y, SOFT, bg)
        if branch:
            cx = PAD_X + pw + 8
            _rrect(cx, PATH_Y - 3, chipw, LH + 6, 5, CHIP)
            tft.write(fsm, branch[:14], cx + 8, PATH_Y, INK_TXT, CHIP)
        return False
    _mq_ensure(("P", path, branch, bg), lambda: _render_pathline_buf(path, branch, bg), avail)
    _mq_blit(PAD_X, PATH_Y - 3, avail, off)      # Pfad + Branch-Chip scrollen zusammen
    return True

def _scroll_path(s, bg, off):
    return draw_path(_pathstr(s), s["branch"], bg, off)

def draw_dots(n):
    if n <= 1:
        return
    n = min(n, 6)
    dot, act, gap, h = 8, 26, 12, 8
    total = sum(act if i == page else dot for i in range(n)) + gap * (n - 1)
    x = (W - total) // 2
    inactive = st7789.color565(0xC8, 0xC8, 0xD0)
    for i in range(n):
        wdt = act if i == page else dot
        _rrect(x, DOTS_Y, wdt, h, h // 2, ON_INK if i == page else inactive)
        x += wdt + gap

def draw_badge(cov, src, frame=0, target=44):
    cx, cy = W // 2, BADGE_CY
    _disc(cx, cy, BADGE_R, INK)
    _blit_aa(cov, ON_INK, INK, cx - target // 2, cy - target // 2, target, src, frame)

# --- Per-Status-Renderer ---
def _r_working(s, bg):
    global _path_over
    draw_header("WORKING", s["source"])
    _path_over = draw_path(_pathstr(s), s["branch"], bg, _marquee_off)
    draw_badge(icons.REFRESH_FRAMES[_anim_phase % 12], icons.REFRESH_W, _anim_phase % 12)
    draw_dots(len(sessions))

def _r_done(s, bg):
    global _path_over
    draw_header("DONE", s["source"])
    _path_over = draw_path(_pathstr(s), s["branch"], bg, _marquee_off)
    draw_badge(icons.CHECK, icons.CHECK_W, 0); draw_dots(len(sessions))

def _input_path(s, bg, off):
    p = _pathstr(s)
    avail = W - 2 * PAD_X
    if tft.write_width(fbig, p) <= avail:
        tft.fill_rect(0, 116, W, fbig.HEIGHT, bg)
        _wcenter(fbig, p, 116, ON_INK, bg)
        return False
    _mq_ensure(("I", p, bg), lambda: _render_text_buf(fbig, p, ON_INK, bg), avail)
    _mq_blit(PAD_X, 116, avail, off)
    return True

def _r_input(s, bg):
    global _path_over
    draw_header("INPUT", s["source"])
    _path_over = _input_path(s, bg, _marquee_off)
    if s["branch"]:
        bw = tft.write_width(fsm, s["branch"][:16]) + 16
        _rrect((W - bw) // 2, 150, bw, LH + 8, 5, CHIP)
        _wcenter(fsm, s["branch"][:16], 154, INK_TXT, CHIP)
    draw_dots(len(sessions))

def _r_permission(s, bg):
    global _path_over
    draw_header("PERMISSION", s["source"])
    _path_over = draw_path(_pathstr(s), s["branch"], bg, _marquee_off)
    for action, label, y, h, primary in PBTN:
        col = INK if primary else CHIP
        txt = ON_INK if primary else INK_TXT
        _rrect(PAD_X, y, W - 2 * PAD_X, h, 8, col)
        _wcenter(fsm, label, y + (h - LH) // 2, txt, col)
    draw_dots(len(sessions))

# Idle: die drei Provider-Marken sanft nacheinander ein-/ausblenden.
IDLE_LOGOS = (OPENAI, CLAUDE, PI)
IDLE_SLOT_MS = 2800
IDLE_FADE_MS = 750

# 1-Bit-Logo -> 8-Bit-Coverage (Detail erodiert), damit _blit_aa bilinear glaettet.
_LOGO_COV = {}
def _logo_cov(bmp, detail, src=48):
    cov = _LOGO_COV.get(id(bmp))
    if cov is None:
        srow = (src + 7) // 8
        cov = bytearray(src * src)
        for row in range(src):
            rb = row * srow
            for col in range(src):
                m = 0x80 >> (col & 7)
                on = bmp[rb + (col >> 3)] & m
                if on and detail is not None and (detail[rb + (col >> 3)] & m):
                    on = 0
                cov[row * src + col] = 255 if on else 0
        _LOGO_COV[id(bmp)] = cov
    return cov

def _blend565(c1, c2, a):
    r1, g1, b1 = _unpack565(c1)
    r2, g2, b2 = _unpack565(c2)
    return st7789.color565(int(r1 * a + r2 * (1 - a)),
                           int(g1 * a + g2 * (1 - a)),
                           int(b1 * a + b2 * (1 - a)))

def _idle_logo(now):
    cyc = IDLE_SLOT_MS * len(IDLE_LOGOS)
    t = now % cyc
    idx = t // IDLE_SLOT_MS
    w = t % IDLE_SLOT_MS
    if w < IDLE_FADE_MS:
        a = w / IDLE_FADE_MS
    elif w > IDLE_SLOT_MS - IDLE_FADE_MS:
        a = (IDLE_SLOT_MS - w) / IDLE_FADE_MS
    else:
        a = 1.0
    return IDLE_LOGOS[idx], round(a * 6) / 6     # quantisiert -> Cache-freundlich

def _draw_idle_logo(now):
    bg = STATUS_BG["IDLE"]
    bmp, a = _idle_logo(now)
    ink = _blend565(ON_INK, bg, a)
    detail = CLAUDE_DETAIL if bmp is CLAUDE else None
    _blit_aa(_logo_cov(bmp, detail), ink, bg, W // 2 - 32, BADGE_CY - 32, 64, 48,
             frame=int(a * 6))

def _r_idle():
    bg = STATUS_BG["IDLE"]
    tft.fill(bg)
    pw = tft.write_width(fsm, "Idle") + 24
    _rrect((W - pw) // 2, HEADER_Y, pw, HEADER_H, HEADER_H // 2, CHIP)
    _wcenter(fsm, "Idle", HEADER_Y + (HEADER_H - LH) // 2, INK_TXT, CHIP)
    _draw_idle_logo(time.ticks_ms())

RENDER = {"WORKING": _r_working, "DONE": _r_done,
          "INPUT": _r_input, "PERMISSION": _r_permission}

def _pulse_apply(status):
    if status not in PULSE_STATES:
        bl_set(1.0)

def render():
    global _last_status, _done_start, _anim_phase, _marquee_off, _path_over
    if not sessions:
        if _last_status != "IDLE":
            _anim_phase = 0
        _last_status = "IDLE"; _path_over = False
        _r_idle(); _pulse_apply("IDLE"); return
    s = sessions[page]
    status = s["status"]
    if status != _last_status:
        _anim_phase = 0
        _marquee_off = 0
        if status == "DONE":
            _done_start = time.ticks_ms()
        _last_status = status
    bg = bg_for(status)
    tft.fill(bg)
    fn = RENDER.get(status)
    if fn:
        fn(s, bg)
    else:                       # unbekannter Status -> Fallback
        draw_header(status, s["source"])
        _path_over = draw_path(_pathstr(s), s["branch"], bg, _marquee_off)
        draw_dots(len(sessions))
    _pulse_apply(status)

# --- Animations-Ticks (zeichnen nur die animierte Region) ---
def _tick_working():
    f = (_anim_phase // 2) % 12     # halbe Geschwindigkeit -> ruhiger
    cx, cy = W // 2, BADGE_CY
    _blit_aa(icons.REFRESH_FRAMES[f], ON_INK, INK, cx - 22, cy - 22, 44, icons.REFRESH_W, f)

def _tick_idle():
    _draw_idle_logo(time.ticks_ms())

def _tick_done(now):
    dt = time.ticks_diff(now, _done_start)
    if dt > DONE_POP_MS:
        return
    k = 0.7 + 0.3 * (dt / DONE_POP_MS)
    t = int(44 * k)
    cx, cy = W // 2, BADGE_CY
    tft.fill_rect(cx - 34, cy - 34, 68, 68, bg_for("DONE"))
    _disc(cx, cy, int(BADGE_R * k), INK)
    _blit_aa(icons.CHECK, ON_INK, INK, cx - t // 2, cy - t // 2, t, icons.CHECK_W, 0)

PULSE_MIN = 0.45
PULSE_MS = 2800
def _tick_pulse(now):
    ph = (time.ticks_ms() % PULSE_MS) / PULSE_MS
    frac = PULSE_MIN + (1 - PULSE_MIN) * (0.5 - 0.5 * math.cos(ph * 2 * math.pi))
    bl_set(frac)

def animate(now):
    global _anim_phase, _anim_last, _marquee_off
    if time.ticks_diff(now, _anim_last) < ANIM_MS:
        return
    _anim_last = now
    _anim_phase += 1
    if not sessions:
        _tick_idle(); return
    s = sessions[page]
    status = s["status"]
    if status == "WORKING":
        _tick_working()
    elif status == "DONE":
        _tick_done(now)
    elif status in PULSE_STATES:
        _tick_pulse(now)
    # Pfad-Laufschrift (nur wenn er ueberlaeuft)
    if _path_over:
        bg = bg_for(status)
        _marquee_off += MARQUEE_SPEED
        if status == "INPUT":
            _input_path(s, bg, _marquee_off)
        else:
            _scroll_path(s, bg, _marquee_off)

# --- Touch ---
TAP_MAX_MOVE = 28
TAP_DEBOUNCE_MS = 280
GESTURE_LEFT = 0x03     # CST816: Wisch links  -> naechste Session
GESTURE_RIGHT = 0x04    # CST816: Wisch rechts -> vorige Session
_touch_start = None
_last_xy = None
_last_action_ms = -1000

def _nav(delta, now):
    global page, _last_action_ms, _marquee_off, sel_key
    np = page + delta
    if 0 <= np < len(sessions):
        page = np
        sel_key = sessions[page]["key"]   # Auswahl an Identitaet binden
        _marquee_off = 0
        _last_action_ms = now
        render()

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
    if not deb or abs(dx) > TAP_MAX_MOVE or abs(dy) > TAP_MAX_MOVE or not sessions:
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

# --- Main Loop ---
sys.stdout.write("ready\n")
render()
while True:
    read_serial_lines()
    handle_touch()
    animate(time.ticks_ms())
    time.sleep_ms(20)
