# Touch-Display als zweites Gerät für rp2040-status

**Datum:** 2026-06-08
**Status:** Design freigegeben, bereit für Implementierungsplan

## Ziel

Das schlanke, push-basierte rp2040-status um ein **ESP32-S3-Touch-LCD** als zweites
Ausgabe-Gerät erweitern — parallel zur bestehenden RP2040-LED. Das Display zeigt eine
Liste aller aktiven Agent-Sessions mit Source-Theme, und ein Tap auf eine Session holt
den zugehörigen **iTerm2-Tab** in den Vordergrund.

Die bestehende Architektur (Agent-Hooks → `send.py` → Statusdateien → `broker.py` →
Gerät) bleibt erhalten. Der LED-Pfad wird **nicht** angefasst.

## Festgelegte Entscheidungen

| Aspekt | Entscheidung |
|---|---|
| Scope | Voll: Session-Liste + Source-Themes + Touch + Tap-to-focus |
| Display-Firmware | Neu in MicroPython (Toolchain wie rp2040-status: `mpremote`, kein PlatformIO) |
| Geräte | Parallel — Broker (LED) und Display-Service (Display) laufen gleichzeitig |
| Transport | USB-seriell jetzt; Architektur BLE-fähig geschnitten (BLE nicht in v1) |
| Fokus | iTerm2 via AppleScript, exakter Tab; Fokus-Backend austauschbar |
| `branch` | Einmal beim `WORKING`-Event erfasst und mitgeführt (kein `git`-Aufruf je Event) |
| `focus` | Strukturiertes Objekt `{backend, …}` (kein flacher String) |
| Aufräumen | Nur `broker.py` pruned stale Dateien; `display_service` filtert nur |

## Architektur

```
Agent-Hook ──► send.py ──► /tmp/rp2040-status/<source>-<session>   (eine Datei je Session)
                                   │
                  ┌────────────────┴────────────────┐
                  ▼                                  ▼
            broker.py  (UNVERÄNDERT)          display_service.py  (NEU)
              │ Aggregat (höchste Prio)         │ volle Session-Liste
              ▼ USB-serial                      ▼ USB-serial   ▲ Taps zurück
         RP2040-LED (VID 0x2E8A)           ESP32-S3-Display (VID 0x303A)
                                                 │ focus <key>
                                                 ▼
                                            focus.py ──osascript──► iTerm2-Tab
```

Das Dateisystem-Verzeichnis ist bereits ein Fan-out-Punkt: `send.py` schreibt heute schon
eine Datei je Session, `broker.py` kollabiert sie nur zum Aggregat. Das Display liest
dieselben Dateien als zweiter Konsument — die Event-Erfassung muss nicht umgebaut werden,
nur das Datei-Schema angereichert.

## Komponenten

### Host-Seite (Python, im rp2040-status-Repo)

**`send.py`** *(geändert)*
Erfasst zusätzlich `id`, `project`, `branch`, `title`, `focus` und **merged** statt zu
überschreiben: `status`/`ts` werden immer aktualisiert; `project`/`branch`/`title`/`focus`
werden aus dem neuen Event übernommen, sonst aus der existierenden Datei beibehalten.
Grund: Diese Felder sind nur beim `WORKING`-Event (Agent-Start) zuverlässig im
Shell-Kontext (`$PWD`, `$ITERM_SESSION_ID`, Git-Branch).

**`broker.py`** *(unverändert)*
Treibt weiter nur die LED, liest weiter nur `status`/`ts`. Bleibt der einzige Prozess,
der stale Dateien pruned.

**`serial_link.py`** *(neu)*
Kleines Modul: Geräte-Discovery per USB-VID, Serial öffnen, Zeilen lesen/schreiben,
Reconnect. Schnittstelle so geschnitten, dass später ein `ble_link.py` mit gleicher API
andocken kann (BLE-später-Seam). Wird in v1 von `display_service` genutzt; `broker.py`
wird dafür **nicht** umgebaut.

**`display_service.py`** *(neu, Daemon)*
- Pollt `/tmp/rp2040-status/*` (200 ms, wie der Broker).
- Baut die Session-Liste, filtert stale (löscht nicht), sortiert (z.B. nach `ts` absteigend).
- Leitet pro Datei einen stabilen `key` ab (erste 6 Hex von `sha1(<source>-<session>)`),
  hält eine `key → Pfad`-Map für den aktuellen Frame.
- Sendet bei Änderung einen LIST-Frame ans Display (Diff gegen letzten Frame).
- Liest Rückmeldungen: `focus <key>` → `key → Pfad → focus`-Objekt → `focus.py`;
  `ready` → letzter Frame als „ungesendet" markieren, Resend erzwingen.

**`focus.py`** *(neu)*
Fokus-Backends mit Dispatch auf `focus.backend`. v1: `iterm2` via `osascript` (revealt die
Session per ID, selektiert Tab + Fenster, aktiviert iTerm2). Fehlt das `focus`-Objekt oder
schlägt AppleScript fehl: loggen, no-op (optional iTerm2 nur aktivieren). Backend-Seam für
spätere `tmux`/`app`-Backends.

**`rp2040-display.service`** *(neu)*
Zweiter LaunchAgent analog zu `rp2040-broker.service`, startet `display_service.py` mit dem
venv-Python.

### Geräte-Seite (MicroPython auf ESP32-S3, neuer Ordner `display/`)

**`boot.py`** — hält den Power-Latch-GPIO **früh**, vor `main.py`.

**`main.py`** — liest LIST-Frames über USB-serial, rendert die Session-Liste mit
Source-Theme, behandelt Touch: Tap = `focus <key>` zurücksenden; Swipe in der unteren
Leiste = blättern; Anzeige „n / N". Sendet `ready` nach Boot.

**`display/lib/`** — Display- und Touch-Treiber (siehe Risiken).

## Datei-Schema

Eine Datei je Session unter `/tmp/rp2040-status/<source>-<session_id>`:

```jsonc
{
  "status":  "WORKING",                    // bestehend: WORKING|INPUT|PERMISSION|DONE
  "ts":      1749384000.12,                // bestehend: Unix-Zeit
  "source":  "claude-code",                // bestehend: → Theme-Palette
  "id":      "abc123",                     // NEU: aufgelöste session_id (stabiler Schlüssel)
  "project": "rp2040-status",              // NEU: basename(cwd)
  "branch":  "main",                       // NEU: git branch, "" wenn kein Repo
  "title":   "Refactor broker",            // NEU: optional, sonst ""
  "focus": {                               // NEU: nur host-seitig, Display sieht es NIE
    "backend":    "iterm2",
    "session_id": "w0t1p0:9C3A-...-F1"      // aus $ITERM_SESSION_ID
  }
}
```

| Feld | Typ | Pflicht | Quelle in `send.py` | Konsument |
|---|---|---|---|---|
| `status` | str | ✓ | CLI-Arg | LED + Display |
| `ts` | float | ✓ | `time.time()` | beide (Staleness, Sortierung) |
| `source` | str | ✓ | wie heute aufgelöst | Display (Theme) |
| `id` | str | ✓ | aufgelöste `session_id` | Display (Tap-Mapping) |
| `project` | str | – | `basename($PWD)` / `cwd` aus stdin-JSON | Display |
| `branch` | str | – | `git -C <cwd> rev-parse --abbrev-ref HEAD`, einmal beim `WORKING` | Display |
| `title` | str | – | `--title` oder leer | Display |
| `focus` | obj | – | `{backend, session_id}` aus `$ITERM_SESSION_ID` | **nur Host** (`focus.py`) |

**Rückwärtskompatibilität:** Neue Felder sind rein additiv. `broker.py` ignoriert sie.

## Wire-Protokoll (zeilenbasiert, USB-serial)

**Host → Display** (nur bei Änderung):
```
LIST 3
S 4f9c12|WORKING|claude-code|rp2040-status|main|Refactor broker
S a1b8e0|INPUT|codex|Buddy|ble-bridge|
S 77d3aa|DONE|antigravity|notes||
END
```
Feldreihenfolge je `S`-Zeile: `key|status|source|project|branch|title`. Trennzeichen `|`;
das `title`-Feld ist optional und steht zuletzt (kann leer sein). Das Display ersetzt sein
Modell bei jedem LIST-Frame vollständig.

**Display → Host:**
```
focus <key>           Tap auf eine Session
ready                 nach Boot → Host erzwingt Resend des aktuellen Frames
```

Der `key` ist ein reines Transport-Detail (von `display_service` aus dem Dateinamen
abgeleitet), kein Schema-Feld. Die lange `session_id`/UUID geht nie über die Leitung.

## Datenfluss (Ende zu Ende)

1. Agent-Hook feuert → `send.py WORKING` (stdin-JSON mit `session_id`, `cwd`; Env
   `$ITERM_SESSION_ID`) → schreibt/merged Statusdatei mit `project`/`branch`(gecacht)/`focus`.
2. `broker.py` (unverändert) → höchste Priorität → LED.
3. `display_service.py` pollt dasselbe Verzeichnis → baut Liste → Diff gegen letzten Frame →
   bei Änderung LIST-Frame ans Display.
4. Tap auf eine Session → Display sendet `focus <key>` → `display_service` mappt
   `key → Datei → focus` → `focus.py` revealt den iTerm2-Tab.
5. Display-Boot → sendet `ready` → `display_service` erzwingt Resend.

## Fehlerbehandlung

- **Gerät fehlt:** Jeder Daemon retryt unabhängig alle 5 s. Fehlt das Display, läuft die LED
  ungestört (getrennte Prozesse).
- **Serial-Schreibfehler:** schließen, reconnecten, Resend erzwingen (Broker-Muster).
- **Kaputte/stale Statusdatei:** `display_service` überspringt sie; Löschen bleibt allein
  beim Broker (kein Lösch-Race).
- **Fokus fehlgeschlagen** (kein `focus`-Objekt / AppleScript-Fehler): loggen, no-op;
  optional iTerm2 nur aktivieren.
- **Power-Latch:** `boot.py` setzt den GPIO früh; auf Akku Risiko, am USB-Tether unkritisch.

## Tests

- **pytest (Host):**
  - `send.py`-Merge: `project`/`branch`/`title`/`focus` bleiben über ein nachfolgendes
    `DONE` erhalten; `status`/`ts` werden aktualisiert.
  - Key-Ableitung stabil und kollisionsarm.
  - Listen-Diff: identische Liste → kein Resend; Änderung → Resend.
  - `key → focus`-Mapping.
  - Fokus-Dispatch mit gemocktem `osascript`.
- **Protokoll:** Serial-Loopback prüft LIST-Frame-Format und `focus <key>`-Verarbeitung.
- **Firmware:** `tools/mock_display.py` (Host) hängt sich an die Leitung, zeigt empfangene
  Frames und sendet Test-Taps — manuelle Verifikation ohne Hardware-Flash.

## Risiken & offene Verifikation

Buddy ging bewusst auf nativen C++-Code; mit MicroPython gibt es echte Unbekannte:

1. **MicroPython-Display-Treiber** für den 1.69"-LCD-Controller (vermutlich ST7789):
   existiert ein gepflegter Treiber, der eine Liste schnell genug rendert? — **größtes Risiko.**
2. **MicroPython-Touch-Treiber** für den I2C-Touch-Chip (vermutlich CST816). Ohne ihn keine
   Taps/Swipes.
3. **Power-Latch-Timing** in `boot.py` — auf Akku evtl. zu spät; am USB-Tether unkritisch.
4. **iTerm2-AppleScript** zum Reveal per Session-ID — exakte Inkantation verifizieren.

### Phase 0 — Spike (vor jeder UI-Arbeit, freigegeben)

Zuerst auf dem realen Board verifizieren:
- Display-Treiber bringt Pixel/Text auf den 1.69"-LCD.
- Touch-Treiber liefert Tap-/Swipe-Koordinaten.
- `boot.py` hält den Power-Latch (zumindest am USB getestet).

### Dokumentierter Fallback (freigegeben)

Falls Phase 0 zeigt, dass **kein brauchbarer MicroPython-Treiber** für Display oder Touch
existiert: Rückfall auf **Buddys bestehende C++-Firmware** (`src/main.cpp`) für das Display,
geflasht via PlatformIO. Die gesamte **Host-Seite dieses Designs bleibt dann unverändert** —
`display_service.py` + `focus.py` + das Wire-Protokoll sind firmware-agnostisch; nur Buddys
Firmware müsste auf dasselbe LIST-/`focus`-Protokoll angepasst werden (Buddy nutzt bereits ein
sehr ähnliches Pipe-Format und Tap-Events).

## Nicht im Scope (v1)

- BLE-Transport (Architektur lässt ihn zu, Implementierung später).
- Weitere Fokus-Backends (tmux, app-name) — Seam vorhanden, nicht gebaut.
- Buddy-Features wie Mute/Unmute-Töne, „OPENING MAC"-Toast, 25-Session-Limit-Feintuning.
