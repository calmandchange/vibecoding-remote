"""Measure WeChat IME latency without the Android phone or Bluetooth link.

Focuses a disposable text field, injects a fixed speech sample through VB-CABLE,
and timestamps the shortcut, spoken audio, visible IME window, and inserted text.
"""

from __future__ import annotations

import argparse
import audioop
import csv
import ctypes
from ctypes import wintypes
import io
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import tkinter as tk
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audio import CablePlayer
from hotkey import parse_hotkey, press_hotkey, release_hotkey


def wechat_pids() -> set[int]:
    output = subprocess.check_output(
        ["tasklist", "/FI", "IMAGENAME eq WeChatAppEx.exe", "/FO", "CSV", "/NH"],
        text=True, errors="replace",
    )
    result = set()
    for row in csv.reader(io.StringIO(output)):
        if len(row) >= 2 and row[0].lower() == "wechatappex.exe":
            result.add(int(row[1]))
    return result


def visible_wechat_windows(pids: set[int]) -> dict[int, dict[str, str]]:
    user32 = ctypes.windll.user32
    found = {}
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def visit(hwnd: int, _parameter: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        if process_id.value not in pids:
            return True
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        if rect.right <= rect.left or rect.bottom <= rect.top:
            return True
        name = ctypes.create_unicode_buffer(256)
        title = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, name, len(name))
        user32.GetWindowTextW(hwnd, title, len(title))
        found[int(hwnd)] = {"class": name.value, "title": title.value,
                            "pid": str(process_id.value)}
        return True

    user32.EnumWindows(callback_type(visit), 0)
    return found


def foreground_info() -> str:
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    process_id = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
    title = ctypes.create_unicode_buffer(256)
    class_name = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, title, len(title))
    user32.GetClassNameW(hwnd, class_name, len(class_name))
    return f"hwnd={hwnd}, pid={process_id.value}, class={class_name.value}, title={title.value}"


def load_speech(path: Path) -> tuple[bytes, float]:
    with wave.open(str(path), "rb") as source:
        if source.getnchannels() != 1 or source.getsampwidth() != 2:
            raise ValueError("测试语音必须是单声道 16 位 WAV")
        pcm = source.readframes(source.getnframes())
        rate = source.getframerate()
    pcm, _ = audioop.ratecv(pcm, 2, 1, rate, 16000, None)
    frame_bytes = 640
    voiced = [i for i in range(0, len(pcm), frame_bytes)
              if audioop.rms(pcm[i:i + frame_bytes], 2) > 200]
    if not voiced:
        raise ValueError("测试语音没有检测到声音")
    # Keep a little natural silence around the synthesized phrase.
    begin = max(0, voiced[0] - frame_bytes * 5)
    end = min(len(pcm), voiced[-1] + frame_bytes * 6)
    trimmed = pcm[begin:end]
    speech_end = (voiced[-1] + frame_bytes - begin) / 32000
    return trimmed, speech_end


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", type=Path, default=Path(__file__).with_name("speech-test.wav"))
    parser.add_argument("--report", type=Path, default=Path(__file__).with_name("wechat-measurement.json"))
    args = parser.parse_args()
    pcm, speech_end_seconds = load_speech(args.audio)
    keys = parse_hotkey("Ctrl+Win")
    pids = wechat_pids()

    root = tk.Tk()
    root.title("语音输入延迟测试（独立输入框）")
    root.geometry("760x300+280+220")
    root.attributes("-topmost", True)
    label = tk.Label(root, text="测试会自动开始。请暂时不要操作键盘或鼠标。", font=("Microsoft YaHei", 14))
    label.pack(padx=15, pady=20)
    editor = tk.Text(root, font=("Microsoft YaHei", 20), height=4)
    editor.pack(fill="both", expand=True, padx=15, pady=12)
    root.update()
    editor.focus_force()

    baseline = visible_wechat_windows(pids)
    report = {"audio_file": str(args.audio), "phrase": "今天我们测试语音输入的响应速度。",
              "wechat_pids": sorted(pids), "initial_windows": baseline,
              "events": [], "new_windows": {}, "final_text": ""}
    start = time.perf_counter()
    lock = threading.Lock()
    finished = threading.Event()
    last_text = ""
    last_change = start

    def mark(name: str, detail: str = "") -> None:
        with lock:
            report["events"].append({"name": name, "t_ms": round((time.perf_counter() - start) * 1000, 1),
                                     "detail": detail})

    def worker() -> None:
        try:
            with CablePlayer() as player:
                mark("foreground_before_hotkey", foreground_info())
                mark("hotkey_press_start")
                press_hotkey(keys)
                mark("hotkey_pressed")
                time.sleep(0.09)
                mark("foreground_after_hotkey", foreground_info())
                audio_start = time.perf_counter()
                mark("audio_injection_start")
                for offset in range(0, len(pcm), 640):
                    player.play(pcm[offset:offset + 640])
                    target = audio_start + (offset + 640) / 32000
                    time.sleep(max(0.0, target - time.perf_counter()))
                with lock:
                    report["events"].append({"name": "last_speech_sound_estimated",
                                             "t_ms": round((audio_start + speech_end_seconds + player.stream.latency - start) * 1000, 1),
                                             "detail": "last voiced WAV chunk plus reported playback latency"})
                mark("audio_injection_end")
                # Allow the 22 ms playback pipeline and final speech samples to drain.
                time.sleep(0.1)
                release_hotkey(keys)
                mark("hotkey_released")
                mark("foreground_after_release", foreground_info())
        except Exception as exc:
            mark("error", repr(exc))
            try:
                release_hotkey(keys)
            except Exception:
                pass
        finally:
            finished.set()

    def poll() -> None:
        nonlocal last_text, last_change
        now = time.perf_counter()
        current = editor.get("1.0", "end-1c")
        if current != last_text:
            mark("text_changed", current)
            last_text = current
            last_change = now
        windows = visible_wechat_windows(pids)
        for handle, details in windows.items():
            if handle not in baseline and str(handle) not in report["new_windows"]:
                report["new_windows"][str(handle)] = details
                mark("wechat_window_visible", f"{handle}: {details}")
        if finished.is_set() and now - last_change > 2.5 and now - start > 6:
            report["final_text"] = current
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
            root.destroy()
            return
        if now - start > 20:
            mark("timeout")
            report["final_text"] = current
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
            root.destroy()
            return
        root.after(10, poll)

    def focus_test_field() -> None:
        root.lift()
        ctypes.windll.user32.SetForegroundWindow(root.winfo_id())
        editor.focus_force()

    root.after(1200, focus_test_field)
    root.after(1600, lambda: threading.Thread(target=worker, daemon=True).start())
    root.after(10, poll)
    root.mainloop()


if __name__ == "__main__":
    main()
