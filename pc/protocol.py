"""Wire protocol shared with the Android app.

Frame: ASCII 'PM', one-byte kind, little-endian uint16 payload length, payload.
Audio is signed 16-bit little-endian PCM, mono, 16 kHz.
"""

from __future__ import annotations

from dataclasses import dataclass

MAGIC = b"PM"
AUDIO = 1
HOTKEY = 2
HEARTBEAT = 3
KEY = 4
TAKEOVER = 5
CONFIG_HOTKEY = 6
ACK = 7
MAX_PAYLOAD = 4096
KINDS = (AUDIO, HOTKEY, HEARTBEAT, KEY, TAKEOVER, CONFIG_HOTKEY, ACK)


@dataclass(frozen=True)
class Frame:
    kind: int
    payload: bytes


def encode_frame(kind: int, payload: bytes) -> bytes:
    if kind not in KINDS:
        raise ValueError("unknown frame kind")
    if len(payload) > MAX_PAYLOAD:
        raise ValueError("payload too large")
    return MAGIC + bytes((kind,)) + len(payload).to_bytes(2, "little") + payload


class FrameParser:
    def __init__(self) -> None:
        self.buffer = bytearray()

    def feed(self, data: bytes) -> list[Frame]:
        self.buffer.extend(data)
        frames: list[Frame] = []
        while len(self.buffer) >= 5:
            start = self.buffer.find(MAGIC)
            if start < 0:
                # A trailing 'P' may be the first half of the next magic.
                self.buffer[:] = self.buffer[-1:] if self.buffer[-1:] == b"P" else b""
                break
            if start:
                del self.buffer[:start]
            if len(self.buffer) < 5:
                break
            kind = self.buffer[2]
            length = int.from_bytes(self.buffer[3:5], "little")
            if kind not in KINDS or length > MAX_PAYLOAD:
                del self.buffer[0]
                continue
            end = 5 + length
            if len(self.buffer) < end:
                break
            frames.append(Frame(kind, bytes(self.buffer[5:end])))
            del self.buffer[:end]
        return frames
