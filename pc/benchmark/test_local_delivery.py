"""Manual end-to-end local ASR test with a temporary Windows input box."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import time
import tkinter as tk

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hotkey import send_unicode_text
from local_asr import LocalRecognizer
from measure_wechat import load_speech


def main() -> None:
    pcm, speech_end_seconds = load_speech(Path(__file__).with_name("speech-test.wav"))
    recognizer = LocalRecognizer()
    root = tk.Tk()
    root.title("本地识别文字输入测试")
    root.geometry("700x180")
    entry = tk.Entry(root, font=("Microsoft YaHei UI", 17))
    entry.pack(fill="both", padx=25, pady=30)
    root.update()
    entry.focus_force()
    events = {"model_load_ms": round(recognizer.load_ms, 1),
              "speech_end_seconds": speech_end_seconds}

    def run() -> None:
        recognizer.start()
        started = time.perf_counter()
        for offset in range(0, len(pcm), 640):
            target = started + offset / 32000
            time.sleep(max(0.0, target - time.perf_counter()))
            recognizer.accept(pcm[offset:offset + 640])
        release_at = time.perf_counter()
        text, decode_ms = recognizer.finish()
        send_unicode_text(text)
        events.update({"recognized": text, "decode_after_release_ms": round(decode_ms, 1),
                       "release_to_injection_ms": round((time.perf_counter() - release_at) * 1000, 1),
                       "speech_end_to_injection_ms": round((time.perf_counter() - started - speech_end_seconds) * 1000, 1)})
        root.after(350, finish)

    def finish() -> None:
        events["input_box_text"] = entry.get()
        path = Path(__file__).with_name("results") / "local-delivery.json"
        path.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(events, ensure_ascii=False, indent=2), flush=True)
        root.destroy()

    root.after(300, run)
    root.mainloop()


if __name__ == "__main__":
    main()
