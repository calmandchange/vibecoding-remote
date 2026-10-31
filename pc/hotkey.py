"""Small, explicit Windows shortcut sender using SendInput."""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

MODIFIERS = {"CTRL": 0x11, "ALT": 0x12, "SHIFT": 0x10, "WIN": 0x5B}
ALIASES = {"CONTROL": "CTRL", "WINDOWS": "WIN", "ESC": "ESCAPE", "RETURN": "ENTER"}
NAMED = {"SPACE": 0x20, "ENTER": 0x0D, "TAB": 0x09, "ESCAPE": 0x1B}
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_UNICODE = 0x0004
INPUT_KEYBOARD = 1
KEY_ACTIONS = {
    1: ("回车", [0x0D]),
    2: ("删除", [0x08]),
    3: ("左移", [0x25]),
    4: ("右移", [0x27]),
    5: ("上移", [0x26]),
    6: ("下移", [0x28]),
    7: ("向左选择", [0x10, 0x25]),
    8: ("向右选择", [0x10, 0x27]),
    9: ("向上选择", [0x10, 0x26]),
    10: ("向下选择", [0x10, 0x28]),
}


def parse_hotkey(value: str) -> list[int]:
    parts = [ALIASES.get(part.strip().upper(), part.strip().upper()) for part in value.split("+")]
    if not parts or any(not part for part in parts):
        raise ValueError("快捷键格式应为 Ctrl+Win 或 Ctrl+Shift+V")
    keys: list[int] = []
    for part in parts:
        if part in MODIFIERS:
            key = MODIFIERS[part]
        elif part in NAMED:
            key = NAMED[part]
        elif len(part) == 1 and part.isascii() and part.isalnum():
            key = ord(part)
        elif part.startswith("F") and part[1:].isdigit() and 1 <= int(part[1:]) <= 12:
            key = 0x70 + int(part[1:]) - 1
        else:
            raise ValueError(f"不支持的按键：{part}")
        if key in keys:
            raise ValueError(f"重复按键：{part}")
        keys.append(key)
    if len(keys) == 1 and keys[0] in MODIFIERS.values():
        raise ValueError("至少需要两个按键")
    return keys


ULONG_PTR = ctypes.c_size_t


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("data", INPUT_UNION)]


def _send_keys(keys: list[int], key_up: bool) -> None:
    ordered = reversed(keys) if key_up else keys
    events = [
        INPUT(INPUT_KEYBOARD, INPUT_UNION(ki=KEYBDINPUT(
            key, 0,
            (KEYEVENTF_KEYUP if key_up else 0) |
            (KEYEVENTF_EXTENDEDKEY if key in (0x25, 0x26, 0x27, 0x28) else 0),
            0, 0,
        )))
        for key in ordered
    ]
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
    user32.SendInput.restype = wintypes.UINT
    batch = (INPUT * len(events))(*events)
    sent = user32.SendInput(len(batch), batch, ctypes.sizeof(INPUT))
    if sent != len(batch):
        raise OSError(ctypes.get_last_error(), "SendInput 发送快捷键失败")


def press_hotkey(keys: list[int]) -> None:
    _send_keys(keys, key_up=False)


def release_hotkey(keys: list[int]) -> None:
    _send_keys(keys, key_up=True)


def send_hotkey(keys: list[int], hold_seconds: float = 1.0) -> None:
    try:
        press_hotkey(keys)
        time.sleep(hold_seconds)
    finally:
        release_hotkey(keys)


def send_key_action(code: int) -> str:
    name, keys = KEY_ACTIONS[code]
    send_hotkey(keys, hold_seconds=0.01)
    return name


def send_unicode_text(value: str) -> None:
    """Type UTF-16 characters into the foreground edit control via SendInput."""
    if not value:
        return
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
    user32.SendInput.restype = wintypes.UINT
    utf16 = value.encode("utf-16-le")
    units = [int.from_bytes(utf16[i:i + 2], "little") for i in range(0, len(utf16), 2)]
    for offset in range(0, len(units), 32):
        events = []
        for unit in units[offset:offset + 32]:
            events.append(INPUT(INPUT_KEYBOARD, INPUT_UNION(ki=KEYBDINPUT(
                0, unit, KEYEVENTF_UNICODE, 0, 0))))
            events.append(INPUT(INPUT_KEYBOARD, INPUT_UNION(ki=KEYBDINPUT(
                0, unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, 0))))
        batch = (INPUT * len(events))(*events)
        sent = user32.SendInput(len(batch), batch, ctypes.sizeof(INPUT))
        if sent != len(batch):
            raise OSError(ctypes.get_last_error(), "SendInput 发送识别文字失败")
