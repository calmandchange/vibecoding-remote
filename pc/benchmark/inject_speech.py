"""Inject a fixed spoken phrase into VB-CABLE and timestamp WeChat IME output."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audio import CablePlayer
from hotkey import parse_hotkey, press_hotkey, release_hotkey
from measure_wechat import load_speech


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--audio', type=Path, default=Path(__file__).with_name('speech-test.wav'))
    parser.add_argument('--events', type=Path, default=Path(__file__).with_name('injection-events.jsonl'))
    args = parser.parse_args()
    pcm, speech_end_seconds = load_speech(args.audio)
    if args.events.exists():
        args.events.unlink()

    def mark(name: str, detail: str = '', t_ns: int | None = None) -> None:
        event = {'name': name, 't_ns': t_ns or time.time_ns(), 'detail': detail}
        with args.events.open('a', encoding='utf-8') as output:
            output.write(json.dumps(event, ensure_ascii=False) + '\n')

    keys = parse_hotkey('Ctrl+Win')
    with CablePlayer() as player:
        time.sleep(0.5)
        mark('hotkey_press_start')
        press_hotkey(keys)
        mark('hotkey_pressed')
        try:
            time.sleep(0.09)
            audio_start_ns = time.time_ns()
            audio_start = time.perf_counter()
            mark('audio_injection_start', t_ns=audio_start_ns)
            for offset in range(0, len(pcm), 640):
                player.play(pcm[offset:offset + 640])
                target = audio_start + (offset + 640) / 32000
                time.sleep(max(0.0, target - time.perf_counter()))
            mark('last_speech_sound_estimated', 'last voiced WAV frame plus VB-CABLE playback latency',
                 audio_start_ns + int((speech_end_seconds + player.stream.latency) * 1e9))
            mark('audio_injection_end')
            time.sleep(0.1)
        finally:
            release_hotkey(keys)
            mark('hotkey_released')
    print(args.events)


if __name__ == '__main__':
    main()
