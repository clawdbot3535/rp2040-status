# Display-Politur: AA-Icons, Animationen, Laufschrift

**Datum:** 2026-06-09
**Status:** Design freigegeben, bereit für Implementierungsplan
**Baut auf:** `2026-06-09-display-status-redesign-design.md` (Status-Farbcodierung)

## Ziel

Das status-gefärbte Touch-Display lebendiger machen, in drei Punkten:
1. **Anti-Aliased Icons** — glatte Kanten statt 1-Bit-Treppen.
2. **Animationen** — WORKING-Icon rotiert, IDLE-Burst rotiert, INPUT/PERMISSION
   pulsieren (Backlight-Atmen), DONE einmaliger „Pop"-Effekt beim Wechsel.
3. **Laufschrift** — die Pfad-Zeile scrollt durchlaufend, wenn sie zu breit ist.

Reine **Display-Firmware**: Host-Seite (`confirm.py`, `display_service.py`,
`send.py`, `keymap.json`, `broker.py`, RP2040 `main.py`) bleibt **unverändert**.

## Festgelegte Entscheidungen

| Aspekt | Entscheidung |
|---|---|
| Icons | 8-Bit-Alpha (Coverage), `ink`-über-`bg`-Blend; weiterhin umfärbbar + gecacht |
| WORKING | Refresh-Icon rotiert (vorgerenderte AA-Frames, 12× 30°) |
| IDLE | Burst rotiert langsam (gleiche Frame-Technik) |
| INPUT/PERMISSION | Puls über **Backlight-PWM** (ganzer Screen atmet, kein Redraw) |
| DONE | Einmal-Effekt beim Wechsel auf DONE (Badge-Pop + Häkchen, ~250 ms), dann statisch |
| Laufschrift | durchlaufender Loop mit Lücke; Pfad-Zeile + großer INPUT-Pfad bei Überlauf |
| Architektur | `animate(now)`-Tick (~20 fps) im Loop; **Region-Redraw**, kein Vollbild im Tick |
| Host | unverändert |

## Architektur

Main-Loop bekommt neben `read_serial_lines()` + `handle_touch()` ein
`animate(now)`:

- Tick alle `ANIM_MS` (~50 ms ≈ 20 fps). Pro Tick: Phase hochzählen, **nur die
  animierte Teilregion** des aktuellen Status neu zeichnen (Badge-Icon bzw.
  Marquee-Streifen). Kein Vollbild-Redraw → kein Flackern.
- `render()` (Vollbild) läuft weiter nur bei Frame-/Seitenwechsel. Es setzt den
  Animations-State zurück (`_anim_phase=0`, `_marquee_off=0`) und erkennt den
  **Status-Wechsel** (vorheriger Status gemerkt) → triggert den DONE-Einmal-Effekt
  und setzt/entfernt den Backlight-Puls.
- **Backlight-PWM:** `bl = machine.PWM(Pin(15), freq=1000)` übernimmt die
  Beleuchtung (statt fix HIGH). Default-Duty = voll; in einem Puls-Status
  (INPUT/PERMISSION) wird die Duty sinusartig zwischen ~40 % und 100 % moduliert
  → der ganze Screen atmet ohne ein Pixel neu zu zeichnen.

Animations-State (Modul-global): `_anim_phase` (int), `_marquee_off` (px),
`_last_status` (für Wechsel-Erkennung), `_done_start_ms` (Einmal-Effekt-Start).

## Mechaniken

### AA-Icons (8-Bit-Alpha)

- Icons aus Figma als Graustufen/Alpha exportieren (Coverage 0–255 pro Pixel).
  Speicherung in `display/lib/icons.py` als `bytes` (1 Byte/Pixel) + Maße.
- Compositor `_blit_aa(cov, ink, bg, x, y, size, src, frame=None)`:
  pro Zielpixel `a = cov[...]`; `out = blend(ink, bg, a)` in RGB565
  (Kanäle linear mischen, dann packen). Gecacht je `(id(cov), ink, bg, size, frame)`.
- Skalierung nearest-neighbor auf `size` (wie bisher). Betrifft Badge-Icons
  (Refresh/Check), Burst, optional Header-Logos.

### WORKING-Spinner & IDLE-Rotation

- Refresh- und Burst-Icon werden beim Asset-Build in **N=12 Frames** vorgerendert
  (Python: Quelle um `i*30°` rotieren, dann zu 8-Bit-Alpha). Ablage als
  `REFRESH_FRAMES = (bytes, …)` bzw. `BURST_FRAMES`.
- Tick: WORKING blittet `REFRESH_FRAMES[_anim_phase % 12]` ins 68×68-Badge
  (Region: nur Badge). IDLE rotiert langsamer (z.B. Phase alle 2–3 Ticks weiter).
- Ein-Frame-Icons (Check) bleiben statisch (kein Frame-Array nötig).

### DONE-Einmal-Effekt

- Bei `render()` mit Wechsel **auf** DONE: `_done_start_ms = now`.
- Im Tick, solange `now - _done_start_ms < ~250 ms`: Badge mit wachsender Skala
  (z.B. 0.7→1.0 über 5–6 Frames) + Häkchen neu zeichnen. Danach einmal statisch
  zeichnen und nicht mehr animieren.

### Puls (INPUT/PERMISSION)

- Backlight-PWM-Atmen wie oben. Reine Helligkeits-Modulation, kein Pixel-Redraw.
- Atemfrequenz ~1 Zyklus / 1.5 s; Duty-Range im Plan final getunt (Flacker/Helligkeit
  am Board).

### Laufschrift (Marquee)

- Helfer `_marquee(text, x, y, avail, fg, bg, off)`:
  - Wenn `write_width(text) <= avail`: statisch zeichnen (kein Scroll).
  - Sonst: Hintergrundbalken (`bg`) über die Streifen-Region, dann Text bei
    `x - off` und eine zweite Kopie bei `x - off + textw + gap` → nahtloser Loop.
    Streifen links/rechts auf `avail` clippen (Schreiben außerhalb vermeiden).
- Tick: `_marquee_off = (_marquee_off + SPEED) % (textw + gap)`; nur der
  Marquee-Streifen wird neu gezeichnet. Gilt für die Pfad-Zeile und den großen
  INPUT-Pfad. Kurze Texte (Branch-Chip, Status-Label) scrollen nie.
- Clipping: `st7789py` hat kein Hardware-Clip → der Helfer zeichnet zuerst den
  `bg`-Balken exakt in Streifenbreite und schreibt nur Zeichen, die hineinpassen
  (per `write_width`-Vorabschnitt), damit nichts über den Streifen hinausläuft.

## Code-Struktur (`display/main.py` + `display/lib/icons.py`)

- `icons.py` regeneriert: 8-Bit-Alpha-Icons + Rotations-Frame-Arrays
  (`REFRESH_FRAMES`, `BURST_FRAMES`, `CHECK`).
- `main.py`:
  - `bl = machine.PWM(Pin(15), freq=1000, duty_u16=65535)` ersetzt das feste
    Backlight-Pin (st7789py bekommt `backlight=None`, BL extern verwaltet).
  - `_blit_aa(...)` (neuer Alpha-Compositor) neben/statt `_blit_1bit`.
  - Animations-State + `animate(now)`; `_marquee(...)`-Helfer.
  - `render()` behält Struktur; markiert animierte Regionen / merkt `_last_status`.
  - `draw_path`/`_r_input` nutzen `_marquee(...)` statt direktem `write`.
- Main-Loop: `read_serial_lines(); handle_touch(); animate(now); sleep_ms(20)`.

**Host unverändert** — kein Diff an `confirm.py`/`display_service.py`/`send.py`/
`keymap.json`/`serial_link.py`/`focus.py`/`broker.py`/RP2040 `main.py`.

## Edge-Cases / Risiken

- **Tick-Tempo / Flacker:** Region-Redraw ist günstig; Backlight-Puls ist
  redraw-frei. Falls der Spinner ruckelt → Frame-Region minimal halten / Phase-Rate
  senken. Am Board getunt.
- **Backlight-PWM-Verfügbarkeit:** Pin 15 ist die LCD-Backlight; PWM via
  `machine.PWM` Standard. Falls die Duty hörbar fiept → `freq` erhöhen (>20 kHz).
- **Marquee-Clipping:** kein HW-Clip → Streifen-bg + Zeichen-Vorabschnitt
  verhindern Überlauf; am Board verifizieren.
- **PSRAM:** Frame-Arrays (12× ~2.3 KB AA-48px) + Caches → unkritisch bei 8 MB.
- **Render-Reset:** Tick darf nicht parallel zu `render()` halb zeichnen — beide
  laufen sequentiell im selben Loop (kein Threading), also unkritisch.

## Tests

- **Host-Regression:** 44 pytest bleiben grün; `git diff` gegen die Host-Dateien leer.
- **Asset-Build:** `ast.parse(icons.py)` + Anzahl Frames (12) + Byte-Längen
  (AA: `size*size`, nicht `/8`) je Icon/Frame prüfen.
- **Board (manuell):** WORKING-Spin flüssig; IDLE-Rotation langsam; INPUT/PERMISSION
  atmen sichtbar & ruhig (kein Flacker); DONE-Pop einmalig beim Wechsel; Laufschrift
  bei langem Pfad sauber durchlaufend + korrekt geclippt; kurze Pfade statisch.

## Nicht im Scope

- Double-Buffering / Tearing-freie Vollbild-Animation (Treiber/Hardware-Limit).
- Per-Provider farbige Logos (separate Option B aus der Icon-Diskussion).
- Sound/Haptik.
