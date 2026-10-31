"""Windows Bluetooth SPP receiver for the Android remote microphone."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from audio import CablePlayer
from audio_route import AudioRoute
from hotkey import KEY_ACTIONS, parse_hotkey, press_hotkey, release_hotkey, send_hotkey, send_key_action, send_unicode_text
from local_asr import DEFAULT_MODEL, LocalRecognizer
from protocol import ACK, AUDIO, CONFIG_HOTKEY, HOTKEY, KEY, TAKEOVER, FrameParser, encode_frame


def list_devices() -> None:
    import sounddevice as sd

    for index, device in enumerate(sd.query_devices()):
        if device["max_output_channels"]:
            print(f"{index:>3}  {device['name']}")


def list_ports() -> None:
    from serial.tools import list_ports as serial_ports

    ports = list(serial_ports.comports())
    if not ports:
        print("未找到 COM 端口。请先在 Windows 蓝牙设置中添加手机的传出串口。")
    for port in ports:
        print(f"{port.device:>6}  {port.description}")


def candidate_ports(configured: str) -> list[str]:
    if configured.lower() != "auto":
        return [configured]
    from serial.tools import list_ports as serial_ports

    return [
        port.device
        for port in serial_ports.comports()
        if "bluetooth" in f"{port.description} {port.hwid}".lower()
        or "bthenum" in port.hwid.lower()
    ]


def run(port: str, hotkey: str, output: str, dry_run: bool = False,
        mode: str = "wechat", model: Path = DEFAULT_MODEL) -> None:
    import serial

    heartbeat_file = Path(__file__).resolve().parent / "logs" / "receiver.heartbeat"
    heartbeat_file.parent.mkdir(parents=True, exist_ok=True)
    last_pulse = 0.0

    def pulse() -> None:
        nonlocal last_pulse
        now = time.monotonic()
        if now - last_pulse >= 5:
            heartbeat_file.touch()
            last_pulse = now

    default_keys = parse_hotkey(hotkey)
    print(f"模式：{mode}；快捷键：{hotkey}；蓝牙串口：{port}", flush=True)
    local = LocalRecognizer(model) if mode == "local" else None
    if local:
        print(f"本地识别模型已加载：{model}（{local.load_ms:.0f} ms）", flush=True)
    route = AudioRoute() if not dry_run and not local else None
    if route:
        # Also recovers the previous microphone after a crash or forced process exit.
        status = route.disable()
        print(f"默认录音设备：{status['default']['name']}（等待手机开启接管）", flush=True)

    def receive() -> None:
        while True:
            pulse()
            ports = candidate_ports(port)
            if not ports:
                print("等待蓝牙 COM 端口。请先配对手机并添加传出串口。", flush=True)
                time.sleep(5)
                continue
            for current_port in ports:
                try:
                    pulse()
                    print(f"正在连接 {current_port} …", flush=True)
                    with serial.Serial(current_port, 115200, timeout=0.05) as connection:
                        parser = FrameParser()
                        last_frame = time.monotonic()
                        active = False
                        held = False
                        hotkey_at = None
                        keys = default_keys
                        held_keys = None
                        pending_keys = None
                        takeover = False
                        player = None

                        def acknowledge(kind: int, ok: bool, message: str = "") -> None:
                            payload = bytes((kind, int(ok), int(takeover) if kind == TAKEOVER else 0)) + message.encode("utf-8")[:180]
                            connection.write(encode_frame(ACK, payload))

                        def release_current() -> None:
                            nonlocal held, held_keys, hotkey_at
                            if held and held_keys and not local and not dry_run:
                                release_hotkey(held_keys)
                            if local and held:
                                local.cancel()
                            held = False
                            held_keys = None
                            hotkey_at = None

                        def stop_takeover() -> None:
                            nonlocal player, takeover
                            release_current()
                            if player:
                                player.clear()
                                player.__exit__(None, None, None)
                                player = None
                            if route and (takeover or route.enabled):
                                status = route.disable()
                                print(f"已恢复电脑麦克风：{status['default']['name']}", flush=True)
                            takeover = False

                        try:
                            while True:
                                pulse()
                                # Read available bytes immediately; a large fixed read delayed short key frames.
                                data = connection.read(connection.in_waiting or 1)
                                pulse()
                                if not data:
                                    if time.monotonic() - last_frame > 10:
                                        raise TimeoutError("10 秒未收到手机的保活帧")
                                    continue
                                for frame in parser.feed(data):
                                    last_frame = time.monotonic()
                                    if not active:
                                        active = True
                                        print(f"已连接 {current_port}。等待手机开启麦克风接管。", flush=True)
                                    if frame.kind == AUDIO and len(frame.payload) % 2 == 0:
                                        if player and takeover:
                                            player.play(frame.payload)
                                        if local and takeover and held:
                                            local.accept(frame.payload)
                                        if takeover and hotkey_at is not None:
                                            print(f"首帧音频到达电脑：快捷键后 {(time.perf_counter() - hotkey_at) * 1000:.0f} ms", flush=True)
                                            hotkey_at = None
                                    elif frame.kind == TAKEOVER and frame.payload in (b"\x00", b"\x01"):
                                        requested = frame.payload == b"\x01"
                                        try:
                                            if requested and not takeover:
                                                if route:
                                                    status = route.enable()
                                                    print(f"已接管电脑麦克风：{status['default']['name']}", flush=True)
                                                if not local and not dry_run:
                                                    player = CablePlayer(output)
                                                    player.__enter__()
                                                    print(f"虚拟音频输出：{player.device_info}", flush=True)
                                                takeover = True
                                            elif not requested:
                                                stop_takeover()
                                            acknowledge(TAKEOVER, True, "已接管" if takeover else "已恢复电脑麦克风")
                                        except Exception as exc:
                                            print(f"麦克风切换失败：{exc}", flush=True)
                                            try:
                                                stop_takeover()
                                            except Exception as restore_exc:
                                                print(f"恢复电脑麦克风失败：{restore_exc}", flush=True)
                                            acknowledge(TAKEOVER, False, str(exc))
                                        last_frame = time.monotonic()
                                    elif frame.kind == CONFIG_HOTKEY:
                                        try:
                                            if not 1 <= len(frame.payload) <= 64:
                                                raise ValueError("快捷键长度无效")
                                            new_hotkey = frame.payload.decode("utf-8")
                                            new_keys = parse_hotkey(new_hotkey)
                                            if held:
                                                pending_keys = new_keys
                                            else:
                                                keys = new_keys
                                            print(f"手机设置语音快捷键：{new_hotkey}", flush=True)
                                            acknowledge(CONFIG_HOTKEY, True, new_hotkey)
                                        except (UnicodeError, ValueError) as exc:
                                            acknowledge(CONFIG_HOTKEY, False, str(exc))
                                    elif frame.kind == HOTKEY:
                                        if frame.payload == b"\x01" and not held and takeover:
                                            if local:
                                                local.start()
                                            elif not dry_run:
                                                press_hotkey(keys)
                                            held = True
                                            held_keys = keys[:]
                                            hotkey_at = time.perf_counter()
                                            if player:
                                                player.clear()
                                            print(f"按住快捷键 pc_epoch_ns={time.time_ns()}", flush=True)
                                        elif frame.payload == b"\x02" and held:
                                            if not local and not dry_run:
                                                release_hotkey(held_keys)
                                            held = False
                                            held_keys = None
                                            hotkey_at = None
                                            if local:
                                                text, decode_ms = local.finish()
                                                if text and not dry_run:
                                                    send_unicode_text(text)
                                                print(f"本地识别完成：{decode_ms:.0f} ms；文字：{text}", flush=True)
                                            else:
                                                print("释放快捷键", flush=True)
                                            if pending_keys:
                                                keys, pending_keys = pending_keys, None
                                        elif frame.payload == b"\x03" and not held and takeover:
                                            print("单次长按快捷键", flush=True)
                                            if not dry_run:
                                                send_hotkey(keys)
                                    elif frame.kind == KEY and len(frame.payload) == 1:
                                        code = frame.payload[0]
                                        if code in KEY_ACTIONS and not held:
                                            if not dry_run:
                                                name = send_key_action(code)
                                            else:
                                                name = KEY_ACTIONS[code][0]
                                            print(f"快捷操作：{name}", flush=True)
                        finally:
                            try:
                                stop_takeover()
                            except Exception as exc:
                                print(f"断线恢复麦克风失败：{exc}", flush=True)
                except (serial.SerialException, OSError) as exc:
                    print(f"{current_port} 连接中断：{exc}", flush=True)
            time.sleep(3)

    try:
        receive()
    finally:
        if route and route.enabled:
            route.disable()


def main() -> None:
    parser = argparse.ArgumentParser(description="手机蓝牙麦克风及快捷键接收器")
    parser.add_argument("--port", default="auto", help="蓝牙传出 COM 端口，如 COM7；默认自动搜索")
    parser.add_argument("--hotkey", default="Ctrl+Win", help="手机按钮触发的电脑快捷键，默认 Ctrl+Win")
    parser.add_argument("--output", default="CABLE Input", help="虚拟音频播放设备名称片段")
    parser.add_argument("--list-devices", action="store_true", help="列出音频输出设备")
    parser.add_argument("--list-ports", action="store_true", help="列出 COM 端口")
    parser.add_argument("--dry-run", action="store_true", help="只解析音频和按键帧，不输出声音或按键")
    parser.add_argument("--mode", choices=("wechat", "local"), default="wechat",
                        help="wechat=微信输入法；local=电脑离线流式识别并直接输入文字")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL, help="本地识别模型目录")
    args = parser.parse_args()
    if args.list_devices:
        list_devices()
        return
    if args.list_ports:
        list_ports()
        return
    run(args.port, args.hotkey, args.output, args.dry_run, args.mode, args.model)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已停止")
