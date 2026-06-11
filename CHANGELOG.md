# Changelog

Alle nennenswerten Änderungen an diesem Projekt werden hier dokumentiert.
Format orientiert sich an [Keep a Changelog](https://keepachangelog.com/),
Versionierung nach [SemVer](https://semver.org/).

## [1.0.0] - 2026-06-11

Erstes stabiles Release. Zeigt den Status aktiver Agenten-Sessions (Claude Code,
Codex, …) auf dedizierter Hardware an — als Status-LED und als Touch-Display.

### Hardware-Targets
- **RP2040-Zero (WS2812B-LED)**: status-gefärbte LED, vom Broker getrieben;
  Port-Erkennung per USB-Vendor-ID (`0x2E8A`), nicht per Gerätename.
- **ESP32-S3 Touch-LCD**: vollwertiges Touch-Display mit einem Screen pro Session,
  Wisch-Navigation, Inline-Permission-Buttons, status-gefärbtem Hintergrund,
  Provider-Logos, AA-Kompositor, Backlight-Puls und Lauftext für lange Pfade.

### Host
- **Broker** (`broker.py`): aggregiert alle aktiven Sessions, wählt den
  höchstpriorisierten Status und sendet ihn an die LED.
- **Display-Service** (`display_service.py`): sendet die Session-Liste ans
  Touch-LCD, verarbeitet Touch-Rückkanäle (`focus`, `act`).
- **`send.py`**: quell-agnostischer Status-Writer (Claude Code, Codex,
  Antigravity, beliebige Quelle) mit angereicherten Feldern (Projekt, Branch,
  Pfad, Fokus-Backend) und stabilem `created`-Zeitstempel.

### Integrationen
- **Claude Code**: Hook-Wiring in `~/.claude/settings.json`.
- **Codex CLI**: lokales Marketplace-Plugin unter `codex/` (Codex liest keine
  freistehende `hooks.json`); mappt UserPromptSubmit/PreToolUse/PostToolUse →
  WORKING, PermissionRequest → PERMISSION, Stop → DONE.

### Tooling
- Host-Simulator (`tools/sim_display.py`) erzeugt die README-Screenshots/GIFs
  pixelnah zum Firmware-Rendering.
- Test-Suite (pytest), 62 Tests grün.

### Bemerkenswerte Fixes auf dem Weg zu 1.0
- Touch-LCD per VID **und** PID finden, damit ein zweites Espressif-Board
  (z. B. eine BLE-Bridge im JTAG-Modus) nach einem Reboot nicht den falschen
  Port greift.
- Touch-Bestätigung hebt die Session sofort PERMISSION → WORKING (instantes
  Feedback statt hängendem Rot).
- Stabile Session-Reihenfolge: Sortierung nach unveränderlichem `created` statt
  volatilem `ts` — der Screen springt bei Aktivität nicht mehr von selbst weiter.
- Display-Firmware bindet die angewählte Session an ihre Identität (`sel_key`),
  bleibt also bei Reorder/Add/Remove unter dem Finger stehen.

[1.0.0]: https://github.com/clawdbot3535/rp2040-status/releases/tag/v1.0.0
