# Codex-Integration (Plugin)

Spiegelt den Session-Status der **Codex CLI** auf das rp2040-status Touch-Display —
analog zur Claude-Code-Anbindung, aber über Codex' Plugin-/Hook-System.

## Warum ein Plugin (und nicht `~/.codex/hooks.json`)?

Codex liest **keine** freistehende `~/.codex/hooks.json` (das ist ein Claude-Code-Muster).
Codex lädt Hooks ausschließlich aus **Marketplace-Plugins**, die in `~/.codex/config.toml`
unter `[plugins."<name>@<marketplace>"]` aktiviert und per `[hooks.state…]`-Hash *getrustet*
sind. Dieses Verzeichnis ist genau so ein lokales Marketplace-Plugin.

## Aufbau

```
codex/                                  <- Marketplace-Root
  .agents/plugins/marketplace.json      <- Codex-Marketplace-Manifest (source: local)
  plugins/rp2040-display/
    .codex-plugin/
      plugin.json                       <- Plugin-Manifest
      hooks.json                        <- die 5 Events -> send.py
```

Gemappte Events (alle rufen `send.py … --source codex`):

| Codex-Event        | Status      |
|--------------------|-------------|
| `UserPromptSubmit` | `WORKING`   |
| `PreToolUse`       | `WORKING`   |
| `PostToolUse`      | `WORKING`   |
| `PermissionRequest`| `PERMISSION`|
| `Stop`             | `DONE`      |

## Installation

```bash
codex plugin marketplace add /Users/christian/Dev/rp2040-status/codex
codex plugin add rp2040-display@rp2040-status
```

Danach **einmal `codex` interaktiv starten** und beim Trust-Prompt die Hooks bestätigen.
Erst dann feuern die Hooks (Codex verlangt persistenten Hook-Trust). Der Trust landet als
`[hooks.state."rp2040-display@rp2040-status:…"]` mit `trusted_hash` in `config.toml`.

Prüfen:

```bash
codex plugin list | grep rp2040          # -> installed, enabled
grep rp2040 ~/.codex/config.toml         # nach dem Trust: hooks.state-Einträge
```

## Wichtig: Edits brauchen Re-Install

Codex installiert das Plugin als **Kopie** nach
`~/.codex/plugins/cache/rp2040-status/rp2040-display/<version>/`.
Änderungen an `hooks.json`/`plugin.json` hier im Repo wirken erst nach:

```bash
# Version in beiden Manifests bumpen, dann:
codex plugin remove rp2040-display@rp2040-status
codex plugin marketplace upgrade
codex plugin add rp2040-display@rp2040-status
```

Da die Hook-Inhalte sich ändern, fragt Codex beim nächsten Start erneut nach Trust.
