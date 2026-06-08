# Confirm-from-device: Aktionen vom Touch-Display an den Agenten

**Datum:** 2026-06-08
**Status:** Design freigegeben, bereit für Implementierungsplan

## Ziel

Das Touch-Display von einem reinen **Melder + Fokus-Fernbedienung** zu einer
**Fernbedienung mit Aktion** erweitern: Wenn ein Agent auf eine Genehmigung oder
Eingabe wartet (`PERMISSION`/`INPUT`), kann der Nutzer per Long-press einen
Confirm-Screen öffnen und **Approve / Reject / Continue** direkt an den Agenten
senden — ohne ins Terminal zu wechseln.

Der bestehende Single-Tap (= Fokus) und Swipe (= Navigation) bleiben unverändert.

## Festgelegte Entscheidungen

| Aspekt | Entscheidung |
|---|---|
| Aktionen | Approve, Reject, Continue (3) |
| Trigger | Long-press (>600 ms, geringe Bewegung) → Confirm-Screen mit 3 Buttons; Tap daneben = abbrechen |
| Verfügbarkeit | Nur bei wartenden Agenten: Status `PERMISSION` (APPROVAL) oder `INPUT` (QUESTION) |
| Tastenfolgen | Defaults im Code, pro Quelle via `keymap.json` überschreibbar; als Token-Sequenzen (`["y","Enter"]`) |
| Architektur | Eigenes Host-Modul `confirm.py` (getrennt von `focus.py`) |
| Kill-Switch | Feature default **an**, per Config `"enabled": false` abschaltbar |
| Backends | tmux `send-keys`, iTerm2 AppleScript „write text" — reuse des Fokus-Targets |

## Architektur & Protokoll

```
Display ──long-press──► Confirm-Screen ──Button-Tap──► "act <key> <action>"  (USB-serial)
                                                            │
                                                display_service.handle_incoming
                                                            │  key → Statusdatei (source + focus)
                                                            ▼
                                                confirm.confirm_action(record, action)
                                                            │  keymap[source][action]
                                        ┌───────────────────┴───────────────────┐
                                  tmux send-keys                         iTerm2 write text
```

Neue Display→Host-Protokollzeile (zusätzlich zu `focus <key>` und `ready`):

```
act <key> approve
act <key> reject
act <key> continue
```

Reuse der einen seriellen Leitung und von `display_service.handle_incoming`.

## Komponenten

### Host: `confirm.py` *(neu)*

```python
def confirm_action(record: dict, action: str) -> bool:
    """Sendet die fuer (source, action) konfigurierte Tastenfolge an das Ziel
    des Agenten (tmux-Pane bzw. iTerm2-Session aus record['focus']).
    True bei erfolgreichem Senden, sonst False (no-op)."""
```

- Validiert `action in ("approve", "reject", "continue")` → sonst False.
- Liest `focus = record.get("focus")`; ohne Backend → False.
- Tastenfolge via `resolve_keys(record.get("source"), action)`.
- Dispatch auf `focus["backend"]`:
  - `tmux`: `subprocess.run(["tmux", "send-keys", "-t", pane, *tokens])`.
    tmux interpretiert Tokens wie `Enter`, `Up`, `C-c`, oder literale Strings (`y`).
  - `iterm2`: AppleScript an die Session-GUID via `write text`. iTerm2 hängt an
    `write text "y"` automatisch ein Newline an → `["y","Enter"]` = `write text "y"`,
    `["Enter"]` = `write text ""`. **v1-Scope:** iTerm2 unterstützt literale Tokens
    + Enter (deckt alle Defaults ab). Spezialtasten-Tokens (`Up`/`Down`/`C-c`) sind
    in v1 **tmux-only** (`send-keys` kann sie nativ); ein iTerm2-Token, das keine
    Literal/Enter-Abbildung hat, wird übersprungen und geloggt.
- Globaler Kill-Switch: wenn Config `enabled` False → sofort False (no-op).

### Host: Keymap

- Defaults im Code:
  ```python
  _DEFAULTS = {"approve": ["y", "Enter"], "reject": ["n", "Enter"], "continue": ["Enter"]}
  ```
- Optionale Override-Datei `keymap.json` (Repo-Root bzw. `~/.config/rp2040-status/keymap.json`).
  v1 startet ohne Quell-Overrides — alle Quellen (inkl. `claude-code`) nutzen die
  generischen `y/n`-Defaults; pro-Quelle-Overrides werden bei Bedarf am echten Prompt
  feinjustiert:
  ```json
  { "enabled": true,
    "*": { "approve": ["y","Enter"], "reject": ["n","Enter"], "continue": ["Enter"] } }
  ```
- Auflösung pro Aktion: `keymap[source][action]` → `keymap["*"][action]` → `_DEFAULTS[action]`.
- `enabled` (default True) ist der Kill-Switch.

### Host: `display_service.handle_incoming` *(erweitern)*

- Neuer Zweig: Zeile `act <key> <action>` → `key_map.get(key)` → Statusdatei lesen
  (ganzer Record, nicht nur `focus`) → `confirm_action(record, action)`.
- Bestehende Zweige (`ready`, `focus <key>`) unverändert.
- Hilfsfunktion `_read_record(path)` (analog `_read_focus`, liefert den ganzen Datensatz).

### Firmware: Long-press + Confirm-Screen *(`display/main.py`)*

- **Long-press-Erkennung:** Touch gehalten > `LONGPRESS_MS` (~600 ms) mit Bewegung
  ≤ `TAP_MAX_MOVE`, und aktuelle Session-Status ∈ {`PERMISSION`, `INPUT`} →
  Confirm-Modus betreten (Flag `_confirm = True`), Overlay zeichnen.
- **Overlay:** Titel/Projekt + Status oben, darunter 3 Buttons (APPROVE / REJECT /
  CONTINUE) mit definierten Hit-Boxen (y-Bereiche), unten Hinweis „Tap daneben = zurück".
- **Im Confirm-Modus:**
  - Tap auf einen Button → `sys.stdout.write("act <key> <action>\n")` → kurzer
    „SENT"-Toast → Confirm-Modus verlassen, normale Session neu zeichnen.
  - Tap außerhalb der Buttons → Confirm-Modus verlassen (abbrechen).
  - Swipe/Long-press im Confirm-Modus: ignoriert.
- Single-Tap und Swipe außerhalb des Confirm-Modus: unverändert (Fokus/Navigation).

## Datenfluss (Ende zu Ende)

1. Agent wartet → Statusdatei `PERMISSION`/`INPUT` → Display zeigt sie (amber/indigo).
2. Long-press auf die Session → Confirm-Screen.
3. Tap „APPROVE" → Display sendet `act <key> approve`.
4. `display_service` mappt key → Datei → `confirm_action(record, "approve")`.
5. Keymap liefert z.B. `["y","Enter"]`; tmux/iTerm2 injiziert das in den Agenten.
6. Agent erhält die Eingabe wie getippt → fährt fort.

## Fehlerbehandlung

- Unbekannte `action` / fehlender key / kein `focus`-Backend → `confirm_action` no-op (False).
- `enabled: false` → jeder `act …` ist no-op.
- tmux/AppleScript-Fehler (Pane/Session weg) → gefangen, False, kein Crash.
- Firmware: Confirm-Modus nur betreten, wenn Status aktionsbedürftig; Frame-Updates
  während des Confirm-Modus pausieren das Overlay nicht (Modell aktualisiert, Overlay
  bleibt bis Tap) — der `key` der long-pressten Session wird beim Eintritt festgehalten.

## Sicherheit

- **Zwei bewusste Schritte:** Long-press **und** expliziter Button-Tap.
- **Nur bei wartenden Agenten** (`PERMISSION`/`INPUT`) — kein Senden an beschäftigte Agenten.
- **Kill-Switch** (`enabled: false`) für sofortiges globales Deaktivieren.
- **Keine Freitext-Eingabe** — nur kuratierte Token-Sequenzen aus dem Keymap.
- `confirm_action` ist die einzige Stelle, die Eingaben injiziert (isoliert, prüfbar).

## Tests

- **pytest (`tests/test_confirm.py`):**
  - Keymap-Auflösung: source-spezifisch > `*` > Code-Default; `enabled`-Kill-Switch.
  - `confirm_action` tmux: ruft `tmux send-keys -t <pane>` mit den richtigen Tokens.
  - `confirm_action` iterm2: baut den AppleScript-/Tokens-Aufruf korrekt (osascript gemockt).
  - Unbekannte action / fehlendes focus / disabled → no-op (False).
- **pytest (`tests/test_display_service.py` erweitern):**
  - `handle_incoming("act abc123 approve", key_map)` ruft `confirm_action` mit dem
    Record der Datei und `"approve"`; unbekannter key → kein Aufruf.
- **Firmware:** Long-press-Erkennung + Button-Hit-Box-Logik (durch Lesen geprüft),
  am Board manuell verifiziert.
- **E2E am Board:** tmux-Agent mit echtem y/n-Prompt → long-press → APPROVE →
  Prompt wird bestätigt (sichtbar im tmux-Pane).

## Nicht im Scope (v1)

- Freitext-Antworten auf QUESTIONs (Touch-Display ungeeignet).
- Menü-aware Auto-Navigation (Pfeiltasten-Erkennung des Prompt-Zustands) — der
  Keymap erlaubt zwar Spezialtasten-Tokens, aber kein automatisches Auslesen des
  Agent-Menüs.
- Bestätigen an LED-only-Setups (Feature ist display-spezifisch).
