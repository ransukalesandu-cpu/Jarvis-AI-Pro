#!/usr/bin/env python3
"""A stand-in for the `adb` command line, driven by a JSON state file.

FAKE_ADB_STATE points at {"devices": {"SERIAL": {"state": "device", "usb": true,
"packages": [...]}}, "log": [...]} ; every call is appended to "log".
"""
import contextlib
import json
import os
import sys
import tempfile

def _png(w=4, h=4) -> bytes:
    import struct
    import zlib

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + b"\x40\x80\xc0" * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


PNG = _png()


@contextlib.contextmanager
def _exclusive(path):
    """Serialise the read-modify-write of the state file across concurrent adb calls
    (the agent's heartbeat polls adb while a test command runs)."""
    with open(path + ".lock", "a+b") as lock:
        if os.name == "nt":
            import msvcrt
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def main(argv):
    path = os.environ["FAKE_ADB_STATE"]
    with _exclusive(path):
        return _run(path, argv)


def _run(path, argv):
    with open(path, encoding="utf-8") as fh:
        state = json.load(fh)
    serial = None
    if argv[:1] == ["-s"]:
        serial, argv = argv[1], argv[2:]
    state.setdefault("log", []).append({"serial": serial, "args": argv})
    out, code = "", 0
    devs = state.setdefault("devices", {})
    cmd = argv[0] if argv else ""
    if cmd == "devices":
        out = "List of devices attached\n" + "".join(
            f"{s}\t{d['state']} {'usb:1-1 ' if d.get('usb') else ''}model:{d.get('model', 'X')}\n"
            for s, d in devs.items())
    elif cmd == "connect":
        addr = argv[1]
        if addr in state.get("reachable", []):
            devs[addr] = {"state": "device", "usb": False, "packages": state.get("phone_packages", [])}
            out = f"connected to {addr}"
        else:
            out, code = f"failed to connect to {addr}", 1
    elif serial not in devs or devs[serial]["state"] != "device":
        out, code = f"error: device '{serial}' not found", 1
    elif cmd == "exec-out":
        sys.stdout.buffer.write(PNG)
    elif cmd in ("reverse", "push", "pull", "pair"):
        if cmd == "pull":
            open(argv[2], "w").write("pulled")
        if cmd == "push":
            devs[serial].setdefault("files", []).append(argv[2])
    elif cmd == "shell":
        line = argv[1]
        if line.startswith("pm list packages"):
            out = "".join(f"package:{p}\n" for p in devs[serial].get("packages", []))
        elif line == "wm size":
            out = "Physical size: 1200x1920\n"
        elif line == "dumpsys battery":
            out = "  AC powered: false\n  USB powered: true\n  level: 81\n"
        elif line == "cat /proc/meminfo":
            out = "MemTotal:        3825000 kB\n"
        elif line.startswith("df"):
            out = "Filesystem 1K-blocks Used Available Use% Mounted\n/dev/x 52000000 20000000 32000000 39% /data\n"
        elif line == "getprop ro.build.version.release":
            out = devs[serial].get("android", "11") + "\n"
        elif line == "getprop ro.build.version.sdk":
            out = "30\n"
        elif line == "getprop ro.product.model":
            out = devs[serial].get("model", "X") + "\n"
        else:
            out = f"ran: {line}\n"
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(state, fh)
    os.replace(tmp, path)                  # readers always see a whole file
    sys.stdout.write(out)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
