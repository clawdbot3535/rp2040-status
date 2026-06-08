#!/usr/bin/env python3
"""Fokus-Backends. focus_session(focus_obj) holt das richtige Ziel nach vorne.
Backend-Dispatch ueber focus_obj['backend']. v1: iterm2 (AppleScript)."""

import subprocess

# $ITERM_SESSION_ID hat die Form "w0t1p0:GUID"; iTerm2-AppleScript matcht die GUID
# gegen 'unique id of session'. Skript selektiert Tab+Window und aktiviert iTerm2.
_ITERM2_SCRIPT = '''
on run argv
  set targetId to item 1 of argv
  tell application "iTerm2"
    repeat with w in windows
      repeat with t in tabs of w
        repeat with s in sessions of t
          if (unique id of s) is targetId then
            select t
            select w
            activate
            return "ok"
          end if
        end repeat
      end repeat
    end repeat
  end tell
  return "notfound"
end run
'''


def _guid(session_id: str) -> str:
    # "w0t1p0:GUID" -> "GUID"; ohne Doppelpunkt unveraendert.
    return session_id.split(":", 1)[1] if ":" in session_id else session_id


def _focus_iterm2(session_id: str) -> bool:
    if not session_id:
        return False
    try:
        res = subprocess.run(
            ["osascript", "-e", _ITERM2_SCRIPT, _guid(session_id)],
            capture_output=True, text=True, timeout=5,
        )
        return res.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def focus_session(focus_obj) -> bool:
    """True bei erfolgreichem Fokus, sonst False (no-op)."""
    if not focus_obj or not isinstance(focus_obj, dict):
        return False
    backend = focus_obj.get("backend")
    if backend == "iterm2":
        return _focus_iterm2(focus_obj.get("session_id", ""))
    return False
