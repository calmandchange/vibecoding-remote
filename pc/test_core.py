import unittest

from audio import AudioQueue, expand_pcm16_16k_to_48k_stereo
from hotkey import KEY_ACTIONS, parse_hotkey
from protocol import ACK, AUDIO, CONFIG_HOTKEY, HEARTBEAT, HOTKEY, KEY, TAKEOVER, Frame, FrameParser, encode_frame


class ProtocolTests(unittest.TestCase):
    def test_fragmented_and_corrupt_prefix(self):
        parser = FrameParser()
        wire = b"garbage" + encode_frame(AUDIO, b"\x01\x02") + encode_frame(HOTKEY, b"\x01")
        found = []
        for byte in wire:
            found.extend(parser.feed(bytes((byte,))))
        self.assertEqual(found, [Frame(AUDIO, b"\x01\x02"), Frame(HOTKEY, b"\x01")])

    def test_invalid_header_resynchronizes(self):
        parser = FrameParser()
        self.assertEqual(parser.feed(b"PM\xff\x00\x00" + encode_frame(HOTKEY, b"\x01")), [Frame(HOTKEY, b"\x01")])

    def test_heartbeat(self):
        self.assertEqual(FrameParser().feed(encode_frame(HEARTBEAT, b"")), [Frame(HEARTBEAT, b"")])

    def test_phone_settings_and_ack_can_share_fragmented_stream(self):
        parser = FrameParser()
        wire = (encode_frame(CONFIG_HOTKEY, b"Ctrl+Shift+V") +
                encode_frame(TAKEOVER, b"\x01") +
                encode_frame(ACK, bytes((TAKEOVER, 1, 1))))
        found = []
        for at in range(0, len(wire), 3):
            found.extend(parser.feed(wire[at:at + 3]))
        self.assertEqual(found, [Frame(CONFIG_HOTKEY, b"Ctrl+Shift+V"),
                                 Frame(TAKEOVER, b"\x01"), Frame(ACK, bytes((TAKEOVER, 1, 1)))])

    def test_quick_key_frames_and_selection(self):
        frames = FrameParser().feed(encode_frame(KEY, b"\x02") + encode_frame(KEY, b"\x07"))
        self.assertEqual(frames, [Frame(KEY, b"\x02"), Frame(KEY, b"\x07")])
        self.assertEqual(KEY_ACTIONS[2][1], [0x08])
        self.assertEqual(KEY_ACTIONS[7][1], [0x10, 0x25])

    def test_audio_expansion(self):
        self.assertEqual(expand_pcm16_16k_to_48k_stereo(b"\x34\x12"), b"\x34\x12" * 6)

    def test_queue_drops_stale_sound_and_fills_silence(self):
        queue = AudioQueue(max_bytes=4)
        queue.push(b"abcd")
        queue.push(b"efgh")
        self.assertEqual(queue.read(6), b"efgh\x00\x00")

    def test_shortcut(self):
        self.assertEqual(parse_hotkey("Ctrl+Win"), [0x11, 0x5B])
        self.assertEqual(parse_hotkey("Ctrl+Shift+V"), [0x11, 0x10, ord("V")])
        with self.assertRaises(ValueError):
            parse_hotkey("Win")
        with self.assertRaises(ValueError):
            parse_hotkey("Ctrl+NoSuchKey")


if __name__ == "__main__":
    unittest.main()
