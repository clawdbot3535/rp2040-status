#!/usr/bin/env python3
"""Host-Simulator des Touch-Displays: bildet das Firmware-Rendering
(display/main.py) pixelgenau in PIL nach und erzeugt PNGs + animierte GIFs
fuer die README. Nutzt dieselben Assets wie das Geraet: round15/round24
(Bitmap-Fonts), provider_logos (1-Bit) und icons.bin (8-Bit-AA-Coverage).

    python tools/sim_display.py        # schreibt nach docs/screens/

Kein Geraet noetig. Reproduzierbar — bei Layout-/Farbaenderungen neu laufen lassen.
"""
import os, sys, math

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "display", "lib"))

import round24 as fbig
import round15 as fsm
import provider_logos as PL
from PIL import Image

OUT = os.path.join(ROOT, "docs", "screens")
W, H = 240, 280
SCALE = 2                      # PNG/GIF-Hochskalierung (nearest -> Panel-Look)
CORNER_R = 26                  # runde Hardware-Ecken nachbilden

# --- Farbe: st7789.color565 -> auf dem Panel angezeigtes RGB (565-Quantisierung) ---
def RGB(r, g, b):
    return (r & 0xF8, g & 0xFC, b & 0xF8)

STATUS_BG = {
    "WORKING":    RGB(0x40, 0x88, 0xF8),
    "INPUT":      RGB(0xD0, 0x98, 0x20),
    "DONE":       RGB(0x30, 0xA0, 0x70),
    "PERMISSION": RGB(0xF0, 0x48, 0x48),
    "IDLE":       RGB(0x60, 0x58, 0x70),
}
INK     = RGB(0x60, 0x58, 0x70)
ON_INK  = RGB(0xFF, 0xFF, 0xFF)
CHIP    = RGB(0xD8, 0xD8, 0xD8)
SOFT    = RGB(0xFF, 0xFF, 0xFF)
INK_TXT = RGB(0x28, 0x26, 0x30)
STATUS_LABEL = {"WORKING": "Working", "INPUT": "Input", "DONE": "Done",
                "PERMISSION": "Permission"}
LH = fsm.HEIGHT
PAD_X = 16
HEADER_Y, HEADER_H, HLOGO = 14, 34, 22
PATH_Y = 80
BADGE_CY, BADGE_R = 162, 34
DOTS_Y = 252
PBTN = (("Approve", 112, 42, True), ("Reject", 160, 30, False),
        ("Continue", 194, 30, False))
_LOGOS = {"codex": PL.OPENAI, "claude-code": PL.CLAUDE, "claude": PL.CLAUDE, "pi": PL.PI}
IDLE_LOGOS = (PL.OPENAI, PL.CLAUDE, PL.PI)

# --- icons.bin in Frames schneiden (wie der Geraete-Loader) ---
_d = open(os.path.join(ROOT, "display", "lib", "icons.bin"), "rb").read()
_rf, _bf, _cf, _o = 48 * 48, 64 * 64, 48 * 48, 0
REFRESH = [_d[_o + i * _rf:_o + (i + 1) * _rf] for i in range(12)]; _o += 12 * _rf
BURST = [_d[_o + i * _bf:_o + (i + 1) * _bf] for i in range(12)]; _o += 12 * _bf
CHECK = _d[_o:_o + _cf]


class Canvas:
    """PIL-Leinwand mit denselben Primitiven wie st7789py + main.py."""
    def __init__(self):
        self.im = Image.new("RGB", (W, H), (0, 0, 0))
        self.px = self.im.load()

    def fill(self, c):
        self.im.paste(c, (0, 0, W, H)); self.px = self.im.load()

    def fill_rect(self, x, y, w, h, c):
        for yy in range(y, y + h):
            if 0 <= yy < H:
                for xx in range(x, x + w):
                    if 0 <= xx < W:
                        self.px[xx, yy] = c

    def disc(self, cx, cy, r, c):
        for dy in range(-r, r + 1):
            dx = int((r * r - dy * dy) ** 0.5)
            self.fill_rect(cx - dx, cy + dy, 2 * dx + 1, 1, c)

    def rrect(self, x, y, w, h, r, c):
        if r > h // 2:
            r = h // 2
        self.fill_rect(x + r, y, w - 2 * r, h, c)
        self.fill_rect(x, y + r, r, h - 2 * r, c)
        self.fill_rect(x + w - r, y + r, r, h - 2 * r, c)
        self.disc(x + r, y + r, r, c)
        self.disc(x + w - r - 1, y + r, r, c)
        self.disc(x + r, y + h - r - 1, r, c)
        self.disc(x + w - r - 1, y + h - r - 1, r, c)

    # Bitmap-Font-Blit (wie st7789py.write / main._buf_text)
    def write(self, font, text, x, y, fg, bg=None):
        OW = font.OFFSET_WIDTH
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
            for p in range(cw * font.HEIGHT):
                on = font.BITMAPS[bs >> 3] & (1 << (7 - (bs & 7)))
                xx, yy = x + p % cw, y + p // cw
                if 0 <= xx < W and 0 <= yy < H:
                    if on:
                        self.px[xx, yy] = fg
                    elif bg is not None:
                        self.px[xx, yy] = bg
                bs += 1
            x += cw

    def wwidth(self, font, text):
        return sum(font.WIDTHS[font.MAP.index(c)] for c in text if c in font.MAP)

    def wcenter(self, font, text, y, fg, bg=None):
        self.write(font, text, max(0, (W - self.wwidth(font, text)) // 2), y, fg, bg)

    # AA-Blit mit bilinearer Abtastung (wie main._blit_aa)
    def blit_aa(self, cov, ink, bg, x, y, size, src):
        sm1 = src - 1
        scale = src / size
        ir, ig, ib = ink
        br, bgc, bb = bg
        for row in range(size):
            fy = row * scale
            y0 = int(fy); y1 = y0 + 1 if y0 < sm1 else y0
            ty = fy - y0
            r0, r1 = y0 * src, y1 * src
            for col in range(size):
                fx = col * scale
                x0 = int(fx); x1 = x0 + 1 if x0 < sm1 else x0
                tx = fx - x0
                a = (cov[r0 + x0] * (1 - tx) * (1 - ty) + cov[r0 + x1] * tx * (1 - ty)
                     + cov[r1 + x0] * (1 - tx) * ty + cov[r1 + x1] * tx * ty) / 255.0
                xx, yy = x + col, y + row
                if 0 <= xx < W and 0 <= yy < H:
                    self.px[xx, yy] = (int(ir * a + br * (1 - a)),
                                       int(ig * a + bgc * (1 - a)),
                                       int(ib * a + bb * (1 - a)))


def logo_cov(bmp, detail=None, src=48):
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
    return cov


def blend(c1, c2, a):
    return tuple(int(c1[i] * a + c2[i] * (1 - a)) for i in range(3))


# --- Komponenten (Port aus main.py) ---
def draw_header(cv, status, source):
    label = STATUS_LABEL.get(status, status[:12])
    lw = cv.wwidth(fsm, label)
    pw = 8 + HLOGO + 6 + lw + 12
    px = (W - pw) // 2
    cv.rrect(px, HEADER_Y, pw, HEADER_H, HEADER_H // 2, INK)
    ly = HEADER_Y + (HEADER_H - HLOGO) // 2
    bmp = _LOGOS.get(source)
    if bmp is not None:
        detail = PL.CLAUDE_DETAIL if source in ("claude-code", "claude") else None
        cv.blit_aa(logo_cov(bmp, detail), ON_INK, INK, px + 8, ly, HLOGO, 48)
    cv.write(fsm, label, px + 8 + HLOGO + 6, HEADER_Y + (HEADER_H - LH) // 2, ON_INK, INK)


def pathline_strip(cv, path, branch, bg):
    """PIL-Image der scrollbaren Pfad+Chip-Zeile (Hoehe = Chip-Hoehe)."""
    h = LH + 6
    ty = (h - fsm.HEIGHT) // 2
    pw = cv.wwidth(fsm, path)
    chipw = (cv.wwidth(fsm, branch[:14]) + 16) if branch else 0
    content = pw + ((8 + chipw) if branch else 0)
    strip = Canvas.__new__(Canvas)
    strip.im = Image.new("RGB", (content, h), bg)
    strip.px = strip.im.load()
    strip.write(fsm, path, 0, ty, SOFT, None)
    if branch:
        cx = pw + 8
        strip.rrect(cx, 0, chipw, h, 5, CHIP)
        strip.write(fsm, branch[:14], cx + 8, ty, INK_TXT, CHIP)
    return strip.im, content


def draw_path(cv, path, branch, bg, off=0):
    avail = W - 2 * PAD_X
    pw = cv.wwidth(fsm, path)
    chipw = (cv.wwidth(fsm, branch[:14]) + 16) if branch else 0
    content = pw + ((8 + chipw) if branch else 0)
    if content <= avail:
        cv.write(fsm, path, PAD_X, PATH_Y, SOFT, bg)
        if branch:
            cx = PAD_X + pw + 8
            cv.rrect(cx, PATH_Y - 3, chipw, LH + 6, 5, CHIP)
            cv.write(fsm, branch[:14], cx + 8, PATH_Y, INK_TXT, CHIP)
        return False
    strip, period = pathline_strip(cv, path, branch, bg)
    period += 26
    wide = Image.new("RGB", (period, strip.height), bg)
    wide.paste(strip, (0, 0))
    o = off % period
    win = Image.new("RGB", (avail, strip.height), bg)
    first = min(avail, period - o)
    win.paste(wide.crop((o, 0, o + first, strip.height)), (0, 0))
    if first < avail:
        win.paste(wide.crop((0, 0, avail - first, strip.height)), (first, 0))
    cv.im.paste(win, (PAD_X, PATH_Y - 3)); cv.px = cv.im.load()
    return True


def draw_dots(cv, n, page):
    if n <= 1:
        return
    n = min(n, 6)
    dot, act, gap, h = 8, 26, 12, 8
    total = sum(act if i == page else dot for i in range(n)) + gap * (n - 1)
    x = (W - total) // 2
    inactive = RGB(0xC8, 0xC8, 0xD0)
    for i in range(n):
        wdt = act if i == page else dot
        cv.rrect(x, DOTS_Y, wdt, h, h // 2, ON_INK if i == page else inactive)
        x += wdt + gap


def draw_badge(cv, cov, src, target=44, scale=1.0):
    cx, cy = W // 2, BADGE_CY
    cv.disc(cx, cy, int(BADGE_R * scale), INK)
    t = int(target * scale)
    cv.blit_aa(cov, ON_INK, INK, cx - t // 2, cy - t // 2, t, src)


def render(cv, s, page=0, n=1, spin=0, pop=1.0, idle_alpha=None, idle_logo=None,
           marquee_off=0):
    status = s["status"]
    if status == "IDLE":
        bg = STATUS_BG["IDLE"]
        cv.fill(bg)
        pw = cv.wwidth(fsm, "Idle") + 24
        cv.rrect((W - pw) // 2, HEADER_Y, pw, HEADER_H, HEADER_H // 2, CHIP)
        cv.wcenter(fsm, "Idle", HEADER_Y + (HEADER_H - LH) // 2, INK_TXT, CHIP)
        bmp = idle_logo if idle_logo is not None else PL.OPENAI
        a = 1.0 if idle_alpha is None else idle_alpha
        ink = blend(ON_INK, bg, a)
        detail = PL.CLAUDE_DETAIL if bmp is PL.CLAUDE else None
        cv.blit_aa(logo_cov(bmp, detail), ink, bg, W // 2 - 32, BADGE_CY - 32, 64, 48)
        return
    bg = STATUS_BG[status]
    cv.fill(bg)
    draw_header(cv, status, s["source"])
    if status == "INPUT":
        p = s.get("path") or s["project"]
        cv.wcenter(fbig, p, 116, ON_INK, bg)
        if s["branch"]:
            bw = cv.wwidth(fsm, s["branch"][:16]) + 16
            cv.rrect((W - bw) // 2, 150, bw, LH + 8, 5, CHIP)
            cv.wcenter(fsm, s["branch"][:16], 154, INK_TXT, CHIP)
    else:
        draw_path(cv, s.get("path") or s["project"], s["branch"], bg, marquee_off)
        if status == "WORKING":
            f = spin % 12
            draw_badge(cv, REFRESH[f], 48)
        elif status == "DONE":
            draw_badge(cv, CHECK, 48, scale=pop)
        elif status == "PERMISSION":
            for label, y, h, primary in PBTN:
                col = INK if primary else CHIP
                txt = ON_INK if primary else INK_TXT
                cv.rrect(PAD_X, y, W - 2 * PAD_X, h, 8, col)
                cv.wcenter(fsm, label, y + (h - LH) // 2, txt, col)
    draw_dots(cv, n, page)


# --- Ausgabe-Helfer ---
def _mask():
    m = Image.new("L", (W, H), 0)
    from PIL import ImageDraw
    ImageDraw.Draw(m).rounded_rectangle([0, 0, W - 1, H - 1], CORNER_R, fill=255)
    return m

_MASK = _mask()

def finish(im, scale=SCALE, opaque=False):
    if opaque:
        out = Image.new("RGB", (W, H), (0, 0, 0))     # schwarze runde Ecken = Panel-Rand
    else:
        out = Image.new("RGBA", (W, H), (0, 0, 0, 0))  # transparente Ecken (PNG)
    out.paste(im, (0, 0), _MASK)
    if scale != 1:
        out = out.resize((W * scale, H * scale), Image.NEAREST)
    return out

def save_png(name, s, **kw):
    cv = Canvas(); render(cv, s, **kw)
    finish(cv.im).save(os.path.join(OUT, name))
    print("  ", name)

def save_gif(name, frames, duration, scale=SCALE):
    imgs = [finish(f, scale, opaque=True).convert("P", palette=Image.ADAPTIVE, colors=64)
            for f in frames]
    imgs[0].save(os.path.join(OUT, name), save_all=True, append_images=imgs[1:],
                 duration=duration, loop=0, optimize=True)
    print("  ", name, "(%d frames)" % len(frames))


def main():
    os.makedirs(OUT, exist_ok=True)
    S = {
        "WORKING": {"status": "WORKING", "source": "claude-code", "project": "chromatic", "branch": "main", "path": "~/Dev/chromatic"},
        "INPUT":   {"status": "INPUT", "source": "claude-code", "project": "chromatic", "branch": "main", "path": "~/Dev/chromatic"},
        "DONE":    {"status": "DONE", "source": "codex", "project": "chromatic", "branch": "main", "path": "~/Dev/chromatic"},
        "PERMISSION": {"status": "PERMISSION", "source": "claude-code", "project": "chromatic", "branch": "main", "path": "~/Dev/chromatic"},
        "IDLE":    {"status": "IDLE", "source": "", "project": "", "branch": "", "path": ""},
    }
    print("Static PNGs:")
    save_png("working.png", S["WORKING"], page=0, n=4)
    save_png("input.png", S["INPUT"], page=1, n=4)
    save_png("done.png", S["DONE"], page=2, n=4)
    save_png("permission.png", S["PERMISSION"], page=3, n=4)
    save_png("idle.png", S["IDLE"])

    # Galerie: alle 5 nebeneinander
    tiles = [finish(c.im) for c in
             [_one(S["IDLE"]), _one(S["WORKING"], n=4, page=0),
              _one(S["INPUT"], n=4, page=1), _one(S["DONE"], n=4, page=2),
              _one(S["PERMISSION"], n=4, page=3)]]
    gap = 16
    gw = sum(t.width for t in tiles) + gap * (len(tiles) - 1)
    gallery = Image.new("RGBA", (gw, tiles[0].height), (0, 0, 0, 0))
    x = 0
    for t in tiles:
        gallery.paste(t, (x, 0), t); x += t.width + gap
    gallery.save(os.path.join(OUT, "states.png"))
    print("   states.png (gallery)")

    print("GIFs:")
    # Spinner (WORKING)
    save_gif("anim-working.gif",
             [_one(S["WORKING"], n=4, page=0, spin=i // 2).im for i in range(24)], 70)
    # DONE-Pop -> dann statisch
    pops = [0.7 + 0.3 * (i / 6) for i in range(7)] + [1.0] * 6
    save_gif("anim-done.gif", [_one(S["DONE"], n=4, page=2, pop=p).im for p in pops], 90)
    # Puls (PERMISSION) ueber Backlight-Helligkeit
    from PIL import ImageEnhance
    pulse = []
    for i in range(24):
        ph = i / 24.0
        frac = 0.45 + 0.55 * (0.5 - 0.5 * math.cos(ph * 2 * math.pi))
        base = _one(S["PERMISSION"], n=4, page=3).im
        pulse.append(ImageEnhance.Brightness(base).enhance(frac))
    save_gif("anim-permission.gif", pulse, 90)
    # Marquee (langer Pfad)
    long_s = {"status": "DONE", "source": "codex", "project": "backend",
              "branch": "main", "path": "~/Projects/clients/acme/backend-service"}
    period = _marquee_period(long_s)
    save_gif("anim-marquee.gif",
             [_one(long_s, n=4, page=2, marquee_off=(i * 6) % period).im
              for i in range(period // 6)], 70)
    # Idle-Cross-Fade
    frames = []
    for li, logo in enumerate(IDLE_LOGOS):
        for a in [i / 6 for i in range(7)] + [1.0] * 6 + [(6 - i) / 6 for i in range(7)]:
            frames.append(_one(S["IDLE"], idle_alpha=a, idle_logo=logo).im)
    save_gif("anim-idle.gif", frames, 80)
    print("Fertig ->", OUT)


def _one(s, **kw):
    cv = Canvas(); render(cv, s, **kw); return cv

def _marquee_period(s):
    cv = Canvas()
    _, content = pathline_strip(cv, s["path"], s["branch"], STATUS_BG[s["status"]])
    return content + 26


if __name__ == "__main__":
    main()
