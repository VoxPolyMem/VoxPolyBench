"""Guard the demo's audio upload boundary without optional model packages."""

from io import BytesIO
import unittest
import wave

from server import validate_audio_payload


class AudioValidationTest(unittest.TestCase):
    @staticmethod
    def wav(frames: int) -> bytes:
        buffer = BytesIO()
        with wave.open(buffer, "wb") as clip:
            clip.setnchannels(1)
            clip.setsampwidth(2)
            clip.setframerate(16000)
            clip.writeframes(b"\0\0" * frames)
        return buffer.getvalue()

    def test_nonempty_wav_is_accepted(self):
        validate_audio_payload(self.wav(256), ".wav")

    def test_header_only_wav_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "contain a recording"):
            validate_audio_payload(self.wav(0), ".wav")

    def test_mismatched_format_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "declared format"):
            validate_audio_payload(b"FORM" + b"\0" * 512, ".wav")


if __name__ == "__main__":
    unittest.main()
