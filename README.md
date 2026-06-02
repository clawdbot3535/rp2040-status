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
