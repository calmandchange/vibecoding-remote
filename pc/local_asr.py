"""Optional, offline streaming Chinese speech recognition for the Bluetooth receiver."""

from __future__ import annotations

from pathlib import Path
import time


DEFAULT_MODEL = Path(__file__).resolve().parent / "models/sherpa-onnx-streaming-zipformer-zh-int8-2025-06-30"


class LocalRecognizer:
    def __init__(self, model_dir: Path = DEFAULT_MODEL) -> None:
        try:
            import numpy as np
            import sherpa_onnx
        except ImportError as exc:
            raise RuntimeError("本地识别缺少依赖；请安装 sherpa-onnx、sherpa-onnx-bin 和 numpy") from exc
        model_dir = Path(model_dir)
        if not (model_dir / "tokens.txt").is_file():
            raise FileNotFoundError(f"本地识别模型不存在：{model_dir}")
        self.np = np
        started = time.perf_counter()
        self.recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
            tokens=str(model_dir / "tokens.txt"),
            encoder=str(model_dir / "encoder.int8.onnx"),
            decoder=str(model_dir / "decoder.onnx"),
            joiner=str(model_dir / "joiner.int8.onnx"),
            num_threads=4,
            sample_rate=16000,
        )
        self.load_ms = (time.perf_counter() - started) * 1000
        self.stream = None
        self.started_at = None

    def start(self) -> None:
        self.stream = self.recognizer.create_stream()
        self.started_at = time.perf_counter()

    def accept(self, pcm16: bytes) -> None:
        if self.stream is None:
            return
        samples = self.np.frombuffer(pcm16, dtype="<i2").astype(self.np.float32) / 32768.0
        self.stream.accept_waveform(16000, samples)
        while self.recognizer.is_ready(self.stream):
            self.recognizer.decode_stream(self.stream)

    def finish(self) -> tuple[str, float]:
        if self.stream is None:
            return "", 0.0
        started = time.perf_counter()
        # This supplies the transducer's right context at button release without
        # adding half a second of wall-clock wait.
        self.stream.accept_waveform(16000, self.np.zeros(8000, dtype=self.np.float32))
        self.stream.input_finished()
        while self.recognizer.is_ready(self.stream):
            self.recognizer.decode_stream(self.stream)
        text = self.recognizer.get_result_all(self.stream).text.strip()
        self.stream = None
        self.started_at = None
        return text, (time.perf_counter() - started) * 1000

    def cancel(self) -> None:
        self.stream = None
        self.started_at = None
