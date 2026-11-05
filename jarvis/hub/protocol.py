"""Wire format shared by the hub, the web client and the laptop agent.

Text frames are JSON objects with a ``type``. Binary frames start with one tag
byte:

    0x01  audio      client -> hub: 16 kHz mono PCM16 (20-40 ms)
                     hub -> client: 24 kHz mono PCM16
    0x02  file data  agent -> hub: 4-byte big-endian request id, then bytes

Close codes: 4401 not paired / bad token, 4403 refused (revoked or wrong
role), 4408 heartbeat timeout, 4409 replaced by a newer connection.
"""
from __future__ import annotations

import json
import struct

PROTOCOL_VERSION = 1
TAG_AUDIO = 0x01
TAG_FILE = 0x02

CLOSE_UNAUTHORIZED = 4401
CLOSE_REFUSED = 4403
CLOSE_TIMEOUT = 4408
CLOSE_REPLACED = 4409

MIC_RATE = 16000
SPEAKER_RATE = 24000


def encode(msg: dict) -> str:
    return json.dumps(msg, ensure_ascii=False, separators=(",", ":"))


def decode(text: str) -> dict:
    msg = json.loads(text)
    if not isinstance(msg, dict) or "type" not in msg:
        raise ValueError("message must be an object with a type")
    return msg


def audio_frame(pcm: bytes) -> bytes:
    return bytes([TAG_AUDIO]) + pcm


def file_frame(request_id: int, data: bytes) -> bytes:
    return bytes([TAG_FILE]) + struct.pack(">I", request_id) + data


def split_binary(frame: bytes) -> tuple[int, bytes]:
    if not frame:
        raise ValueError("empty binary frame")
    return frame[0], frame[1:]


def split_file(payload: bytes) -> tuple[int, bytes]:
    return struct.unpack(">I", payload[:4])[0], payload[4:]
