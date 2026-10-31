"""Manually check local-mode phone press and desktop text injection."""

from __future__ import annotations

from pathlib import Path
import subprocess
import tkinter as tk


ADB = Path.home() / "AppData/Local/Android/Sdk/platform-tools/adb.exe"


def main() -> None:
    root = tk.Tk()
    root.title("手机本地识别测试输入框")
    root.geometry("700x180")
    entry = tk.Entry(root, font=("Microsoft YaHei UI", 17))
    entry.pack(fill="both", padx=25, pady=30)
    root.update()
    entry.focus_force()

    def trigger() -> None:
        subprocess.run([str(ADB), "shell", "input", "swipe", "420", "750", "420", "750", "1300"], check=True)
        root.after(1600, finish)

    def finish() -> None:
        print("输入框文字：" + entry.get(), flush=True)
        root.destroy()

    root.after(350, trigger)
    root.mainloop()


if __name__ == "__main__":
    main()
