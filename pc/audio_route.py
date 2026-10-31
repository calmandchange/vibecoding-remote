"""Switch the Windows default capture endpoint only while the phone requests it."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


SCRIPT = Path(__file__).with_suffix(".ps1")


class AudioRoute:
    def __init__(self, script: Path = SCRIPT) -> None:
        self.script = script
        self.enabled = False

    def _call(self, action: str) -> dict:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-File", str(self.script), "-Action", action],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15,
            check=False,
        )
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or
                               f"切换录音设备失败，退出码 {result.returncode}")
        status = json.loads(result.stdout.strip().splitlines()[-1])
        self.enabled = bool(status["enabled"])
        return status

    def enable(self) -> dict:
        return self._call("enable")

    def disable(self) -> dict:
        return self._call("disable")
