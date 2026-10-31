"""Time a local streaming recognizer on the same speech used for WeChat IME."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

import numpy as np
import sherpa_onnx

from measure_wechat import load_speech


MODEL_NAME = 'sherpa-onnx-streaming-zipformer-small-bilingual-zh-en-2023-02-16'


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', type=Path, default=Path(__file__).resolve().parents[1] / 'models' / MODEL_NAME)
    parser.add_argument('--audio', type=Path, default=Path(__file__).with_name('speech-test.wav'))
    parser.add_argument('--report', type=Path, default=Path(__file__).with_name('results') / 'local-asr.json')
    parser.add_argument('--runs', type=int, default=3)
    args = parser.parse_args()
    pcm, speech_end_seconds = load_speech(args.audio)
    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    model = args.model
    encoder = model / ('encoder.int8.onnx' if (model / 'encoder.int8.onnx').exists() else 'encoder-epoch-99-avg-1.int8.onnx')
    decoder = model / ('decoder.onnx' if (model / 'decoder.onnx').exists() else 'decoder-epoch-99-avg-1.int8.onnx')
    joiner = model / ('joiner.int8.onnx' if (model / 'joiner.int8.onnx').exists() else 'joiner-epoch-99-avg-1.int8.onnx')
    start_load = time.perf_counter()
    recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
        tokens=str(model / 'tokens.txt'),
        encoder=str(encoder),
        decoder=str(decoder),
        joiner=str(joiner),
        num_threads=4,
        sample_rate=16000,
    )
    load_ms = (time.perf_counter() - start_load) * 1000
    report = {'model': model.name, 'load_ms': round(load_ms, 1),
              'sample_seconds': round(len(samples) / 16000, 3),
              'speech_end_seconds': round(speech_end_seconds, 3), 'runs': []}

    for number in range(args.runs):
        stream = recognizer.create_stream()
        start = time.perf_counter()
        changes = []
        last_text = ''
        for offset in range(0, len(samples), 320):
            target = start + offset / 16000
            time.sleep(max(0.0, target - time.perf_counter()))
            stream.accept_waveform(16000, samples[offset:offset + 320])
            while recognizer.is_ready(stream):
                recognizer.decode_stream(stream)
            text = recognizer.get_result_all(stream).text
            if text != last_text:
                changes.append({'t_ms': round((time.perf_counter() - start) * 1000, 1),
                                'text': text})
                last_text = text
        # The transducer needs right context for the final syllable. Feed the
        # official example's half-second padding in one batch at release.
        stream.accept_waveform(16000, np.zeros(8000, dtype=np.float32))
        stream.input_finished()
        while recognizer.is_ready(stream):
            recognizer.decode_stream(stream)
        final_text = recognizer.get_result_all(stream).text
        final_ms = (time.perf_counter() - start) * 1000
        report['runs'].append({
            'run': number + 1,
            'first_text_ms': next((change['t_ms'] for change in changes if change['text']), None),
            'speech_end_to_final_ms': round(final_ms - speech_end_seconds * 1000, 1),
            'audio_end_to_final_ms': round(final_ms - len(samples) / 16, 1),
            'final_text': final_text,
            'changes': changes,
        })
        print(f'run {number + 1}: first={report["runs"][-1]["first_text_ms"]} ms, '
              f'end-to-final={report["runs"][-1]["speech_end_to_final_ms"]} ms, '
              f'text={final_text}', flush=True)

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'model load: {load_ms:.1f} ms; report: {args.report}', flush=True)


if __name__ == '__main__':
    main()
