# rp2040-status

Status-LED broker for [Claude Code](https://claude.com/claude-code) sessions, driven by a
Waveshare RP2040-Zero with an onboard WS2812B LED.

A small daemon watches all active Claude Code sessions on the host, picks the
highest-priority state, and forwards it over USB-serial to the RP2040, which
animates the LED accordingly.

## What the LED means

| State        | Color              | Meaning                          |
|--------------|--------------------|----------------------------------|
| `WORKING`    | blue               | Claude is working                |
| `INPUT`      | yellow, pulsing    | waiting for your input           |
| `PERMISSION` | red, pulsing       | needs your approval              |
| `DONE`       | green              | finished                         |
| `OFF`        | off                | no active session                |

Priority (high → low): `PERMISSION > INPUT > WORKING > DONE`.
With multiple concurrent sessions, the highest-priority state wins.

## Architecture

```
Claude Code session ──► send.py ──► /tmp/rp2040-status/<session_id>
                                            │
                                            ▼
                                       broker.py  ──USB-serial──►  RP2040 (main.py)
```

- `main.py` — MicroPython firmware on the RP2040. Reads commands line-by-line
  from USB-serial, drives the WS2812B on GPIO16.
- `broker.py` — host daemon. Polls `/tmp/rp2040-status/*` every 200 ms, resolves
  priority, sends only on state change, auto-reconnects on USB drop, prunes
  stale sessions (>600 s).
- `send.py` — writes one status file per session. Invoked from Claude Code
  hooks; reads `session_id` from stdin JSON.

## Setup

### 1. Flash the RP2040

Install MicroPython on the Waveshare RP2040-Zero, then copy `main.py` to the
device root:

```bash
mpremote fs cp main.py :main.py
mpremote reset
```

The LED runs a short red→green→blue→yellow startup sweep on boot.

### 2. Install the broker

Requires Python 3 and `pyserial`. `pyserial` lets the broker identify the
RP2040 by its USB vendor id (`0x2E8A`) instead of grabbing the first
`/dev/cu.usbmodem*` it sees — important if any other USB-serial board (e.g. an
ESP32) is also connected. Without it the broker falls back to `stty` + a raw
write and picks devices by name only, which can bind to the wrong board.

```bash
pip install pyserial
```

On Homebrew Python (PEP 668 "externally-managed"), install into a project venv
and point the service at it:

```bash
python3 -m venv .venv
.venv/bin/pip install pyserial
# then run the broker with .venv/bin/python3 (set this in the launchd plist /
# systemd unit)
```

### 3. Run the broker

**macOS (launchd):**

```bash
launchctl bootstrap gui/$UID ~/Library/LaunchAgents/com.rp2040-status.broker.plist
```

**Linux (systemd):**

```bash
cp rp2040-broker.service ~/.config/systemd/user/
systemctl --user enable --now rp2040-broker
```

**Foreground (debug):**

```bash
python3 broker.py
```

### 4. Wire up agent hooks

`send.py` is **source-agnostic**: it accepts a session id and a source label from
multiple channels, so any tool with shell hooks can drive the LED.

#### Claude Code

Hooks pipe a JSON payload on stdin — `send.py` picks `session_id` from it
automatically:

```bash
echo '{"session_id":"abc"}' | python3 send.py WORKING
```

A complete wiring in `~/.claude/settings.json` looks like this:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      { "hooks": [ { "type": "command",
        "command": "python3 /path/to/send.py WORKING", "timeout": 3 } ] }
    ],
    "PreToolUse": [
      { "hooks": [ { "type": "command",
        "command": "python3 /path/to/send.py WORKING", "timeout": 3 } ] }
    ],
    "Stop": [
      { "hooks": [ { "type": "command",
        "command": "python3 /path/to/send.py INPUT", "timeout": 3 } ] }
    ],
    "PermissionRequest": [
      { "hooks": [ { "type": "command",
        "command": "python3 /path/to/send.py PERMISSION", "timeout": 3 } ] }
    ]
  }
}
```

> **Don't use `--all` on `PreToolUse`.** Each hook invocation already
> carries the current session's `session_id` on stdin, so `send.py` updates
> exactly the right file. Adding `--all` overwrites *every* active session
> file — including the `INPUT` state another concurrent `claude` session
> just wrote — and was the main source of "LED stuck on blue" reports when
> running multiple Claude sessions in parallel.

> **Sub-agents (`Task` tool) and `SubagentStop`.** When the main session
> spawns a sub-agent, the sub-agent's hook payloads carry the **parent's**
> `session_id` (plus a separate `agent_id`). PreToolUse from inside the
> sub-agent therefore refreshes the parent's status file, and the parent's
> own `Stop` hook eventually flips it to `INPUT` — no extra hook needed.
>
> Do **not** wire `SubagentStop` → `OFF`. It would delete the parent's
> file (same `session_id`), causing a brief `OFF` flicker between
> sub-agent completion and the parent's next tool call.

#### Codex CLI

Codex has a Claude-Code-style hook system: drop a `hooks.json` into
`~/.codex/` with the events you want to react to. The `session_id` arrives
on stdin in the JSON payload (same shape as Claude Code, plus a `turn_id`
field that lets `send.py` auto-detect the source).

```json
{
  "UserPromptSubmit": [
    { "matcher": null, "hooks": [
      { "type": "command",
        "command": "python3 /path/to/send.py WORKING --source codex",
        "timeout": 5, "async": true }
    ] }
  ],
  "PermissionRequest": [
    { "matcher": null, "hooks": [
      { "type": "command",
        "command": "python3 /path/to/send.py PERMISSION --source codex",
        "timeout": 5, "async": true }
    ] }
  ],
  "Stop": [
    { "matcher": null, "hooks": [
      { "type": "command",
        "command": "python3 /path/to/send.py DONE --source codex",
        "timeout": 5, "async": true }
    ] }
  ]
}
```

> **One-time trust step:** Codex requires you to approve unfamiliar hooks
> on first use. Start `codex` interactively once — the startup review
> dialog will surface the new hooks; pick **Trust all and continue**.
> After that, both `codex` and `codex exec` will fire the hooks. If you
> later edit `hooks.json`, re-trust the same way.

#### Antigravity

Same pattern, with `RP2040_SOURCE=antigravity`:

```bash
RP2040_SOURCE=antigravity \
RP2040_SESSION_ID="$AG_SESSION_ID" \
python3 /path/to/send.py INPUT
```

#### Resolution order

| field        | priority (high → low)                                                     |
|--------------|----------------------------------------------------------------------------|
| `session_id` | `--session` → positional arg → `$RP2040_SESSION_ID` → stdin JSON → `manual` |
| `source`     | `--source` → `$RP2040_SOURCE` → stdin shape (Codex `turn_id` → Claude Code) → `unknown` |

Each `(source, session_id)` pair gets its own file (`/tmp/rp2040-status/<source>-<id>`),
so multiple tools running concurrently never collide on a shared `manual` slot.

#### Manual testing

```bash
python3 send.py PERMISSION
python3 send.py DONE
python3 send.py OFF
```

## Touch display (ESP32-S3)

An optional second device runs **alongside** the LED: a Waveshare
ESP32-S3-Touch-LCD-1.69 (240×280 ST7789, CST816T touch). It shows the current
session **colour-coded by status — the same colour language as the LED**
(WORKING blue, INPUT yellow, PERMISSION red, DONE green, IDLE grey); the provider
is shown by a small logo in the header pill, and the real working path
(`$HOME`→`~`) sits below it. A tap brings the matching terminal to the front;
swipe pages through sessions (dots show the position). The LED path (`broker.py`)
is untouched — both devices are driven in parallel from the same status files.

The screen is animated: the WORKING icon spins, the idle burst rotates,
INPUT/PERMISSION breathe (backlight PWM), DONE pops once on transition, and a path
that's too long to fit scrolls as a flicker-free marquee (rendered to an off-screen
buffer and blitted in one pass). Icons are anti-aliased (8-bit alpha, bilinear).

```
send.py ──► /tmp/rp2040-status/<source>-<session>
                     │  (one file per session, enriched: project/branch/title/focus)
        ┌────────────┴─────────────┐
        ▼                          ▼
   broker.py                 display_service.py
   │ aggregate               │ full session list
   ▼ USB-serial              ▼ USB-serial  ▲ taps back
 RP2040 LED              ESP32-S3 display ──focus <key>──► focus.py ──► iTerm2 / tmux
```

- `display_service.py` — host daemon. Discovers the display by USB vendor id
  `0x303A`, sends a line-based `LIST` frame on every change, and resolves taps
  (`focus <key>`) through `focus.py`. Reads the same files as the broker but
  **never deletes** them (the broker owns pruning).
- `focus.py` — focus backends. `send.py` auto-selects per session: if the agent
  runs inside a tmux pane it stores `{"backend":"tmux","pane":"%N"}` (the pane is
  found via process-tree matching, so it works even when `$TMUX` is absent from
  the hook environment); otherwise `{"backend":"iterm2","session_id":...}` from
  `$ITERM_SESSION_ID`. A tmux tap runs `select-pane`/`switch-client`; an iTerm2
  tap reveals the session via AppleScript.
- `display/` — MicroPython firmware: `boot.py` (holds the SYS_EN power latch on
  GPIO41 early), `main.py` (frame parser, themed render, touch), and `lib/`
  drivers (`st7789py`, `cst816`, fonts).

### Flash and deploy

The display runs MicroPython. Flash the firmware once, then copy the files:

```bash
PORT=/dev/cu.usbmodemXXXX   # the 0x303A device — use `mpremote connect list`
# 1. MicroPython (once). The image is the ESP32-S3 SPIRAM_OCT build.
esptool --port $PORT erase-flash
esptool --port $PORT --baud 460800 write-flash 0 ESP32_GENERIC_S3-SPIRAM_OCT-*.bin
# 2. App + drivers
mpremote connect $PORT fs cp display/boot.py :boot.py
mpremote connect $PORT fs mkdir lib
mpremote connect $PORT fs cp display/lib/st7789py.py :lib/st7789py.py
mpremote connect $PORT fs cp display/lib/cst816.py :lib/cst816.py
mpremote connect $PORT fs cp display/lib/provider_logos.py :lib/provider_logos.py
mpremote connect $PORT fs cp display/lib/round24.py :lib/round24.py
mpremote connect $PORT fs cp display/lib/round15.py :lib/round15.py
mpremote connect $PORT fs cp display/main.py :main.py
mpremote connect $PORT reset
```

Then run the display daemon (a LaunchAgent template is in
`launchd/com.user.rp2040-display.plist` — substitute your username):

```bash
.venv/bin/python3 display_service.py
```

The host-side tests cover `send.py`, `display_service.py`, `focus.py` and
`serial_link.py`: `.venv/bin/pytest tests/`.

### Notes from bring-up

- **240×280 needs a custom rotation table.** The stock `st7789py` only knows
  240×320 / 240×240 / 135×240 / 128×128; `main.py` passes `custom_rotations`
  with `ystart=20` (the 280-row window sits centred in the 320-row controller).
- **After flashing, physically replug the board.** The ESP32-S3 USB-Serial-JTAG
  unit does not cleanly restart MicroPython's REPL after an esptool reset until a
  real power cycle — unplug/replug, then `mpremote` works.
- **No C++ fallback was needed.** MicroPython drives the panel, touch and power
  latch fine on this board; the native-firmware fallback in the design doc stayed
  unused.

### Confirm from the display

When an agent needs approval (`PERMISSION`), the screen shows **Approve / Reject /
Continue** buttons directly — tap one to answer without switching to the terminal.
The display sends `act <key> <action>` back; `display_service` looks up the session
and `confirm.py` injects the configured keystrokes into the agent's terminal — tmux
via `send-keys`, iTerm2 via `write text`. A tap anywhere else (or on a non-permission
screen) focuses the terminal instead; swipe pages through sessions.

The keystrokes are configurable in `keymap.json` (repo root or
`~/.config/rp2040-status/keymap.json`):

```json
{
  "enabled": true,
  "*": { "approve": ["y", "Enter"], "reject": ["n", "Enter"], "continue": ["Enter"] }
}
```

- Resolution per action: `source` block → `"*"` block → built-in default.
- Tokens are tmux key names; literals + a trailing `Enter` also work over iTerm2
  (`write text`). Special keys (`Up`/`C-c`/…) are tmux-only in v1.
- `"enabled": false` is a global kill-switch.

The display daemon shells out to `tmux`, so its LaunchAgent sets `PATH` (to reach
Homebrew `tmux`) and `WorkingDirectory` (to find `keymap.json`) — see
`launchd/com.user.rp2040-display.plist`.

## Configuration

Stale-session pruning can be toggled at runtime:

```bash
python3 send.py TIMEOUT-OFF   # keep sessions forever
python3 send.py TIMEOUT-ON    # prune after 600 s (default)
```

Config lives in `/tmp/rp2040-status/.config`.

## Troubleshooting

- **LED dark, broker running** — check that `broker.py` holds the serial port
  (`lsof /dev/cu.usbmodem*`). If a previous instance is hung, `launchctl
  kickstart -k gui/$UID/com.rp2040-status.broker` recycles it.
- **Broker can't find device** — confirm the RP2040 enumerates as
  `/dev/cu.usbmodem*` (macOS) or `/dev/ttyACM*` (Linux).
- **LED never updates, broker "connected" to the wrong board** — with another
  USB-serial device attached (e.g. an ESP32), make sure `pyserial` is installed
  so the broker can select by vendor id `0x2E8A`. The log line `Verbunden: …`
  shows which port it actually bound to. Without `pyserial` it picks the first
  `usbmodem`/`ttyACM` by name and may silently write to the wrong device.
- **State stuck after crash** — clear `/tmp/rp2040-status/` and restart the
  broker.

## Hardware

- [Waveshare RP2040-Zero](https://www.waveshare.com/rp2040-zero.htm)
- WS2812B on GPIO16 (built into the board)
- USB-C cable to the host

Optional touch display:

- [Waveshare ESP32-S3-Touch-LCD-1.69](https://www.waveshare.com/esp32-s3-touch-lcd-1.69.htm)
  (240×280 ST7789, CST816T touch, 8 MB octal PSRAM / 16 MB flash)
- USB-C cable to the host (USB vendor id `0x303A`)
