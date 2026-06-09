# Touch-Display Status-Redesign (Farb-Systematik LED ↔ Display)

**Datum:** 2026-06-09
**Status:** Design freigegeben, bereit für Implementierungsplan
**Referenz:** Figma `F8A5Ceh9xsP3kB2kqqWMss` (Screens: Idle/Input/Working/Done/Permission, 240×280)

## Ziel

Die Farb-Systematik von LED (rp2040) und Touch-Display vereinheitlichen: Die
**Farbe codiert künftig den Status** (nicht mehr den Provider), exakt wie die LED.
Das Touch-Display wird komplett auf das Figma-Design umgebaut — status-gefärbter
Vollhintergrund, Header-Pille mit Provider-Logo + Status-Label, zentrale
Status-Icons, Pfad+Branch-Chip, Punkt-Navigation, und PERMISSION mit
Inline-Action-Buttons.

Reine **Display-Firmware-Neugestaltung**: Host-Seite (`confirm.py`,
`display_service.py`, `send.py`, `keymap.json`) und LED-Pfad (`broker.py`,
`main.py`) bleiben **unverändert**. Das `act`/`focus`-Protokoll bleibt gleich.

## Festgelegte Entscheidungen

| Aspekt | Entscheidung |
|---|---|
| Umfang | Voll: Figma-Redesign der Display-Firmware |
| Farbe | codiert Status (blau/gelb/rot/grün/grau) — wie die LED |
| Provider | Logo klein in der Header-Pille; Idle: generischer ✳-Burst |
| PERMISSION | Inline-Buttons (Approve/Reject/Continue), Tap = Aktion |
| INPUT | reine Anzeige (kein Inline-Action) |
| Long-press | entfällt (inkl. `_await_lift`, `render_confirm`, Chevron-Tap) |
| Navigation | Swipe blättert · Punkte = Position · Tap = Fokus |
| Host | unverändert (confirm/act/focus/keymap/broker/LED) |

## Farb-System

Status → Hintergrundfarbe (aus den Figma-PNGs gesampelt):

```
WORKING    #4088F8  rgb(64,136,248)   blau
INPUT      #D09820  rgb(208,152,32)   gold/gelb
DONE       #30A070  rgb(48,160,112)   grün
PERMISSION #F04848  rgb(240,72,72)    rot
IDLE       #605870  rgb(96,88,112)    slate-grau
```

Token-Palette (für Pillen/Badges/Text auf dem Farbhintergrund):

```
INK     ~#3A3846   dunkle Pille / Kreis-Badge / primärer Button
ON_INK   #FFFFFF   Text/Icon auf INK
CHIP    ~#E8E8EC   heller "on master"-Chip
SOFT    ~#F0F0F0   gedämpftes Weiß (Pfad-Text)
```

Diese werden als `st7789.color565(...)`-Konstanten abgelegt. Status→Farbe
entspricht der LED-Mapping-Tabelle (README „What the LED means").

Unbekannter/zukünftiger Status: Fallback-Hintergrund (neutral, z.B. IDLE-Grau)
mit dem rohen Status-String als Label.

## Layout & Komponenten (240×280, runde Ecken)

Gemeinsamer Rahmen auf status-farbigem Vollhintergrund (`tft.fill(bg)`):

- **Header-Pille** (oben, `INK`, abgerundet): kleines **Provider-Logo** (links) +
  **Status-Label** in `ON_INK`. Idle: helle Pille mit „Idle" (kein Logo).
- **Pfad-Zeile**: `~/Dev/<project>` (`SOFT`) + **„on master"-Chip** (heller,
  abgeschrägter Banner mit Branch).
- **Center** je Status:
  - WORKING → `INK`-Kreis-Badge + Refresh-Icon (`ON_INK`)
  - DONE → `INK`-Kreis-Badge + Häkchen (`ON_INK`)
  - INPUT → großer Pfad zentral, kein Center-Icon
  - PERMISSION → 3 Buttons: Approve (`INK` gefüllt), Reject & Continue (`CHIP`/weiß)
  - IDLE → großer weißer Burst/Spark
- **Punkt-Navigation** unten: `n` Punkte, aktiver = längliche Pille; zeigt die
  Position in der Session-Liste.

Maße/Positionen werden im Plan aus den Figma-Frames übernommen (Header ~y20,
Pfad ~y71/113, Center-Badge ~y136 68×68, Buttons-Block ~y113 176×113, Punkte ~y250).

## Icons

`st7789py` kann keine Vektoren → Icons als 1-Bit-Bitmaps (MSB-first, wie
`provider_logos.py`), gerendert via `blit_buffer` mit Farb-Cache.

- Quelle: **Export aus dem Figma** (Nodes: `MdOutlineCheck`, `MdOutlineCached`,
  Idle-Burst-Vector) als PNG → 1-Bit-Konvertierung mit demselben Toolchain-Ansatz
  wie die Logos. Ablage in `display/lib/icons.py` (neu).
- Provider-Logos: für die kleine Header-Größe runterskaliert (der vorhandene
  `_draw_logo`/`blit_buffer`-Pfad skaliert bereits per Ziel-Größe).

## Touch-Modell

- **Swipe** (CST816-Hardware-Geste, vorhanden) → blättern; Punkte folgen.
- **Tap außerhalb von Buttons** → Terminal fokussieren (`focus <key>`, unverändert).
- **PERMISSION**: Tap auf eine Button-Hit-Box → `act <key> <action>`
  (`approve`/`reject`/`continue`, Protokoll unverändert).
- **Entfällt:** Long-press, `_await_lift`, `render_confirm`, Confirm-Overlay,
  Chevron-Tap-Navigation, `ACTIONABLE`/`LONGPRESS_MS`.

## Code-Struktur (`display/main.py`)

- `STATUS_BG = {…}` + Token-Konstanten ersetzen `THEMES`, `_STATE`, `AMBER`, `INDIGO`.
- Gemeinsame Helfer: `draw_header(status, source)`, `draw_path(project, branch)`,
  `draw_dots(page, n)`, `draw_badge(icon)`, `draw_buttons()`.
- **Dispatch-Tabelle** `RENDER = {"WORKING": _r_working, …}`; `render()` setzt
  Hintergrund + gemeinsamen Rahmen und ruft die Status-Render-Funktion (Fallback
  für unbekannten Status).
- `display/lib/icons.py` (neu): exportierte 1-Bit-Icons + Maße.
- `handle_touch()` vereinfacht: Swipe + Tap (Fokus / Permission-Button-Hit-Boxen);
  Long-press/Chevron/Confirm-Overlay-Logik entfernt.
- Frame-Parser (`handle_line`), Modell (`sessions`/`page`), Main-Loop, Font-/
  Display-/Touch-Init bleiben strukturell wie bisher.

**Host unverändert** — kein Diff an `confirm.py`, `display_service.py`, `send.py`,
`keymap.json`, `serial_link.py`, `focus.py`, `broker.py`, `main.py` (RP2040).

## Edge-Cases / Fehler

- Unbekannter Status → Fallback-Farbe + roher Status-Text.
- Langer Projekt-/Branch-Name → per `write_width` kürzen (wie bisher).
- Mehr Sessions als sinnvoll als Punkte darstellbar → Punkte deckeln (Detail im
  Plan; z.B. max. N Punkte, aktiver hervorgehoben).
- Render-Tempo: ein `fill` (Vollfläche) + wenige `blit_buffer`/`write`; Icons/Logos
  gecacht (wie bestehender `_LOGO_CACHE`).
- Leere Liste → IDLE-Screen.

## Tests

- **Host (Regression):** die bestehenden 44 pytest bleiben grün — Beleg, dass die
  Host-Seite nicht angefasst wurde. Kein neuer Host-Code.
- **Icon-Konvertierung:** `ast.parse` der generierten `icons.py` + Maß-/Byte-Längen-
  Check (wie bei `provider_logos.py`).
- **Firmware (am Board, manuell):** je Status ein Frame → korrekte Farbe/Layout;
  Swipe blättert; Punkte folgen; Tap = Fokus; PERMISSION-Buttons → richtige
  `act <key> <action>`-Emission (über die Serial-Leitung geprüft, wie beim
  Confirm-E2E).

## Nicht im Scope

- Änderungen an LED-Firmware oder Host-Logik (beide schon farb-konform bzw.
  protokoll-stabil).
- Animationen der Status-Icons (Buddy-Stil) — statisch in v1.
- Pulsierende Hintergründe analog der LED (`INPUT`/`PERMISSION` pulsen auf der LED;
  das Display bleibt statisch farbig in v1).
- Fuller-Path-Anzeige über das `project`-Feld (basename) hinaus — v1 zeigt
  `~/Dev/<project>` mit dem vorhandenen `project`-Wert.
