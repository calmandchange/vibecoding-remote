"""Route 16 kHz phone PCM into a 48 kHz stereo virtual playback device."""

from __future__ import annotations

from collections import deque
from threading import Lock


def expand_pcm16_16k_to_48k_stereo(pcm: bytes) -> bytes:
    """Triplicate each mono sample and duplicate it into both channels."""
    if len(pcm) % 2:
        raise ValueError("PCM16 needs an even number of bytes")
    out = bytearray(len(pcm) * 6)
    pos = 0
    for i in range(0, len(pcm), 2):
        sample = pcm[i : i + 2]
        out[pos : pos + 12] = sample * 6
        pos += 12
    return bytes(out)


class AudioQueue:
    """Short bounded queue; drop stale audio to keep live speech responsive."""

    def __init__(self, max_bytes: int = 48_000 * 2 * 2 // 4) -> None:
        self.max_bytes = max_bytes
        self.chunks: deque[bytes] = deque()
        self.head_offset = 0
        self.queued = 0
        self.lock = Lock()

    def push(self, data: bytes) -> None:
        with self.lock:
            self.chunks.append(data)
            self.queued += len(data)
            while self.queued > self.max_bytes and self.chunks:
                oldest = self.chunks.popleft()
                available = len(oldest) - self.head_offset
                self.queued -= available
                self.head_offset = 0

    def read(self, size: int) -> bytes:
        out = bytearray(size)
        at = 0
        with self.lock:
            while at < size and self.chunks:
                head = self.chunks[0]
                count = min(size - at, len(head) - self.head_offset)
                out[at : at + count] = head[self.head_offset : self.head_offset + count]
                at += count
                self.head_offset += count
                self.queued -= count
                if self.head_offset == len(head):
                    self.chunks.popleft()
                    self.head_offset = 0
        return bytes(out)

    def clear(self) -> None:
        with self.lock:
            self.chunks.clear()
            self.head_offset = 0
            self.queued = 0


def find_cable_device(sd: object, name: str = "CABLE Input") -> int:
    matches = [
        (index, device)
        for index, device in enumerate(sd.query_devices())
        if name.lower() in device["name"].lower() and device["max_output_channels"] >= 2
    ]
    if not matches:
        raise RuntimeError(f"未找到输出设备 {name!r}；请安装 VB-CABLE，或使用 --list-devices。")
    # The Windows WASAPI endpoint is generally preferable to MME/DirectSound copies.
    matches.sort(key=lambda item: "wasapi" not in sd.query_hostapis(item[1]["hostapi"])["name"].lower())
    return matches[0][0]


class CablePlayer:
    def __init__(self, device_name: str = "CABLE Input") -> None:
        import sounddevice as sd

        self.queue = AudioQueue()
        device = find_cable_device(sd, device_name)
        self.device_info = sd.query_devices(device)["name"]
        self.stream = sd.RawOutputStream(
            samplerate=48_000,
            channels=2,
            dtype="int16",
            blocksize=480,
            device=device,
            callback=self._callback,
        )

    def _callback(self, outdata: memoryview, frames: int, _time: object, _status: object) -> None:
        outdata[:] = self.queue.read(frames * 4)

    def __enter__(self) -> "CablePlayer":
        self.stream.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.stream.stop()
        self.stream.close()

    def play(self, pcm: bytes) -> None:
        self.queue.push(expand_pcm16_16k_to_48k_stereo(pcm))

    def clear(self) -> None:
        self.queue.clear()

