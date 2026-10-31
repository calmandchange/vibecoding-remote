"""Check the actual VB-CABLE playback-to-recording path without a phone."""

from __future__ import annotations

from array import array
import math

import sounddevice as sd

from audio import CablePlayer


def main() -> None:
    inputs = [
        (i, device)
        for i, device in enumerate(sd.query_devices())
        if "CABLE Output" in device["name"] and device["max_input_channels"] >= 2
    ]
    if not inputs:
        raise RuntimeError("找不到 CABLE Output 录音设备")
    inputs.sort(key=lambda item: "wasapi" not in sd.query_hostapis(item[1]["hostapi"])["name"].lower())
    input_id = inputs[0][0]

    samples = array("h", (int(6000 * math.sin(2 * math.pi * 440 * n / 16000)) for n in range(320)))
    frame = samples.tobytes()
    peaks = []
    with sd.RawInputStream(samplerate=48000, channels=2, dtype="int16", device=input_id) as receiver:
        with CablePlayer() as player:
            for _ in range(25):
                player.play(frame)
                data, _overflow = receiver.read(960)
                pcm = array("h")
                pcm.frombytes(data)
                peaks.append(max(abs(value) for value in pcm))
    peak = max(peaks)
    print(f"VB-CABLE loopback peak: {peak}")
    if peak < 1000:
        raise RuntimeError("没有检测到测试音频；请重启 Windows 后重试")
    print("VB-CABLE 输入到输出的音频通路正常")


if __name__ == "__main__":
    main()
