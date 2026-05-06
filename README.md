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

Requires Python 3 and (optionally) `pyserial`:

```bash
pip install pyserial   # optional; falls back to stty + raw write
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

### 4. Wire up Claude Code hooks

Call `send.py` from your hook configuration so that each session reports its
state. Example hook payload:

```bash
echo '{"session_id":"abc"}' | python3 send.py WORKING
```

Manual testing:

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
- **State stuck after crash** — clear `/tmp/rp2040-status/` and restart the
  broker.

## Hardware

- [Waveshare RP2040-Zero](https://www.waveshare.com/rp2040-zero.htm)
- WS2812B on GPIO16 (built into the board)
- USB-C cable to the host
