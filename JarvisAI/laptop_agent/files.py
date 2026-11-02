"""Serve laptop files to the hub on request (for show_file).

The hub asks for a file's details (file_stat) and then for byte ranges
(file_read); the agent streams each range in 64 KB binary frames and ends
with file_end. Nothing is uploaded anywhere else, and nothing is copied: the
hub forwards the bytes straight to the phone that asked for them.
"""
from __future__ import annotations

import mimetypes
import os
from pathlib import Path

from hub import protocol

CHUNK = 64 * 1024


class FileServer:
    def __init__(self, client):
        self.client = client

    def handle(self, msg: dict) -> None:
        rid = int(msg.get("id", 0))
        path = Path(os.path.expandvars(os.path.expanduser(str(msg.get("path") or ""))))
        if msg.get("type") == "file_stat":
            if not path.is_file():
                self.client.send_threadsafe({"type": "file_info", "id": rid, "exists": False})
                return
            st = path.stat()
            mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            self.client.send_threadsafe({"type": "file_info", "id": rid, "exists": True, "name": path.name,
                                         "size": st.st_size, "mime": mime, "mtime": st.st_mtime,
                                         "path": str(path)})
            return
        offset = max(0, int(msg.get("offset") or 0))
        length = int(msg.get("length") or 0)
        try:
            with path.open("rb") as fh:
                fh.seek(offset)
                remaining = length if length > 0 else None
                while remaining is None or remaining > 0:
                    data = fh.read(CHUNK if remaining is None else min(CHUNK, remaining))
                    if not data:
                        break
                    self.client.send_bytes_threadsafe(protocol.file_frame(rid, data))
                    if remaining is not None:
                        remaining -= len(data)
            self.client.send_threadsafe({"type": "file_end", "id": rid})
        except OSError as exc:
            self.client.send_threadsafe({"type": "file_end", "id": rid, "error": str(exc)})
