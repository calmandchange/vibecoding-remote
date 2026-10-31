"""Measure Android button to Windows shortcut latency on the paired test phone.

Requires the regular Windows receiver, a connected Android device over ADB, and
the app in the foreground. The phone and PC clocks are calibrated with timed
ADB calls; the shortest round trip bounds the clock-offset uncertainty.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ADB = Path.home() / "AppData/Local/Android/Sdk/platform-tools/adb.exe"
PC_LOG = ROOT / "pc/logs/receiver.out.log"
RESULT = ROOT / "pc/benchmark/results/bluetooth-link.json"


def adb(*args: str) -> str:
    return subprocess.check_output([str(ADB), *args], encoding="utf-8", errors="replace")


def calibrate(count: int = 15) -> dict:
    samples = []
    with subprocess.Popen([str(ADB), "shell", "-T"], stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          encoding="utf-8", bufsize=1) as shell:
        assert shell.stdin and shell.stdout
        for _ in range(count):
            start = time.time_ns()
            shell.stdin.write("date +%s%N\n")
            shell.stdin.flush()
            while True:
                line = shell.stdout.readline().strip()
                if re.fullmatch(r"\d{18,20}", line):
                    break
            phone = int(line)
            end = time.time_ns()
            samples.append({
                "offset_ns": (start + end) // 2 - phone,
                "rtt_ms": (end - start) / 1e6,
            })
        shell.stdin.write("exit\n")
        shell.stdin.flush()
    best = min(samples, key=lambda item: item["rtt_ms"])
    return {"offset_ns": best["offset_ns"], "rtt_ms": best["rtt_ms"]}


def phone_events() -> list[dict]:
    output = adb("logcat", "-v", "epoch", "-d", "-s", "PhoneVoiceRemote:I", "*:S")
    events = []
    for line in output.splitlines():
        if "快捷键" not in line or "首帧音频" not in line:
            continue
        timestamp = re.match(r"\s*(\d+\.\d+)", line)
        timings = re.search(r"快捷键\s+(\d+)\s+ms；录音启动\s+(\d+)\s+ms；首帧音频\s+(\d+)\s+ms", line)
        if timestamp and timings:
            events.append({"log_epoch_ns": int(float(timestamp.group(1)) * 1e9),
                           "phone_hotkey_ms": int(timings.group(1)),
                           "phone_recording_ms": int(timings.group(2)),
                           "phone_first_audio_ms": int(timings.group(3))})
    return events


def pc_events() -> list[dict]:
    output = PC_LOG.read_text(encoding="utf-8", errors="replace")
    events = []
    for line in output.splitlines():
        match = re.search(r"pc_epoch_ns=(\d+)", line)
        if match:
            events.append({"pc_hotkey_ns": int(match.group(1))})
        match = re.search(r"首帧音频到达电脑：快捷键后\s+(\d+)\s+ms", line)
        if match and events:
            events[-1]["pc_first_audio_after_hotkey_ms"] = int(match.group(1))
    return events


def main() -> None:
    print("校准时钟…", flush=True)
    before = calibrate()
    adb("logcat", "-c")
    old_pc_count = len(pc_events())
    run_count = 10
    for i in range(run_count):
        print(f"手机按键测试 {i + 1}/{run_count}", flush=True)
        adb("shell", "input", "swipe", "420", "750", "420", "750", "700")
        time.sleep(1.2)
    after = calibrate()
    phones = phone_events()
    pcs = pc_events()[old_pc_count:]
    offset = (before["offset_ns"] + after["offset_ns"]) // 2
    paired = []
    for phone, pc in zip(phones, pcs):
        # Log emission occurs after the first audio frame. The Android log reports
        # elapsed time from finger down to both the hotkey write and that frame.
        down_ns = phone["log_epoch_ns"] - phone["phone_first_audio_ms"] * 1_000_000
        phone_hotkey_pc_ns = down_ns + phone["phone_hotkey_ms"] * 1_000_000 + offset
        paired.append({**phone, **pc,
                       "estimated_phone_down_to_pc_hotkey_ms": round((pc["pc_hotkey_ns"] - down_ns - offset) / 1e6, 1),
                       "estimated_bluetooth_and_windows_hotkey_ms": round((pc["pc_hotkey_ns"] - phone_hotkey_pc_ns) / 1e6, 1)})
    result = {"clock_calibration_before": before, "clock_calibration_after": after,
              "calibration_uncertainty_ms": round(max(before["rtt_ms"], after["rtt_ms"]) / 2, 1),
              "phone_events_count": len(phones), "pc_events_count": len(pcs), "runs": paired}
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
