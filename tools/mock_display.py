#!/usr/bin/env python3
"""Emuliert das Touch-Display am Host: verbindet sich mit dem Display-Service-Port,
zeigt empfangene LIST-Frames und sendet auf Eingabe Tap-Events.

Nutzung (direkt gegen den echten ESP ODER ein virtuelles PTY-Paar):
    python3 tools/mock_display.py /dev/cu.usbmodemXXX
Befehle (stdin): 'r' = ready senden, '<key>' = 'focus <key>' senden, 'q' = quit.
"""
import sys
import threading
import serial


def reader(conn):
    buf = b""
    while True:
        buf += conn.read(256)
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            print("RX:", line.decode(errors="replace").strip())


def main():
    if len(sys.argv) < 2:
        print("usage: mock_display.py <serial-port>")
        return 1
    conn = serial.Serial(sys.argv[1], 115200, timeout=0.1)
    threading.Thread(target=reader, args=(conn,), daemon=True).start()
    print("ready 'r' | focus '<key>' | quit 'q'")
    for line in sys.stdin:
        cmd = line.strip()
        if cmd == "q":
            break
        elif cmd == "r":
            conn.write(b"ready\n")
        elif cmd:
            conn.write(f"focus {cmd}\n".encode())
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
