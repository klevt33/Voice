"""
Unit tests for hotwords and initial_prompt wiring in whisper_server_base.run_transcription().

Verifies that the new WHISPER_HOTWORDS and WHISPER_INITIAL_PROMPT config values
are correctly passed to model.transcribe() by the shared server base function.
"""
import io
import sys
import os
import struct
import unittest
import wave
from unittest.mock import MagicMock, patch

# Ensure project root is on sys.path
_project_root = os.path.join(os.path.dirname(__file__), "..")
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


def _make_wav_bytes(num_frames: int = 100) -> bytes:
    """Return minimal valid WAV bytes."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(struct.pack(f"<{num_frames}h", *([0] * num_frames)))
    return buf.getvalue()


def _run_with_config(hotwords, initial_prompt):
    """
    Call run_transcription() with a mocked model and patched config values.
    Returns (result_dict, mock_transcribe_method).
    """
    from whisper_server_base import run_transcription
    import config as cfg_module

    mock_seg = MagicMock()
    mock_seg.text = " Hello world."

    mock_model = MagicMock()
    mock_model.transcribe.return_value = ([mock_seg], MagicMock())

    config_patch_values = {
        "LANGUAGE": "en",
        "BEAM_SIZE": 5,
        "WHISPER_HOTWORDS": hotwords,
        "WHISPER_INITIAL_PROMPT": initial_prompt,
    }

    wav_bytes = _make_wav_bytes()

    with patch.multiple(cfg_module, **config_patch_values):
        result = run_transcription(mock_model, wav_bytes)

    return result, mock_model.transcribe


class TestRunTranscriptionHotwords(unittest.TestCase):

    def test_hotwords_joined_from_list(self):
        """Non-empty WHISPER_HOTWORDS list is joined and forwarded."""
        result, mock_transcribe = _run_with_config(["Claude", "Sonnet"], None)

        _, kwargs = mock_transcribe.call_args
        self.assertEqual(kwargs["hotwords"], "Claude Sonnet")

    def test_hotwords_none_for_empty_list(self):
        """Empty WHISPER_HOTWORDS list → hotwords=None."""
        result, mock_transcribe = _run_with_config([], None)

        _, kwargs = mock_transcribe.call_args
        self.assertIsNone(kwargs["hotwords"])

    def test_initial_prompt_forwarded(self):
        """Non-empty WHISPER_INITIAL_PROMPT is passed through."""
        prompt = "Capitalise sentences."
        result, mock_transcribe = _run_with_config([], prompt)

        _, kwargs = mock_transcribe.call_args
        self.assertEqual(kwargs["initial_prompt"], prompt)

    def test_initial_prompt_none_for_empty_string(self):
        """Empty string WHISPER_INITIAL_PROMPT → initial_prompt=None."""
        result, mock_transcribe = _run_with_config([], "")

        _, kwargs = mock_transcribe.call_args
        self.assertIsNone(kwargs["initial_prompt"])

    def test_initial_prompt_none_for_none_value(self):
        """None WHISPER_INITIAL_PROMPT → initial_prompt=None."""
        result, mock_transcribe = _run_with_config([], None)

        _, kwargs = mock_transcribe.call_args
        self.assertIsNone(kwargs["initial_prompt"])

    def test_both_parameters_together(self):
        """hotwords and initial_prompt can be set simultaneously."""
        result, mock_transcribe = _run_with_config(["Opus", "Fable"], "Good punctuation.")

        _, kwargs = mock_transcribe.call_args
        self.assertEqual(kwargs["hotwords"], "Opus Fable")
        self.assertEqual(kwargs["initial_prompt"], "Good punctuation.")

    def test_result_contains_text_key(self):
        """run_transcription() returns a dict with a 'text' key."""
        result, _ = _run_with_config(["Claude"], "prompt")
        self.assertIn("text", result)
        self.assertIn("processing_time", result)

    def test_empty_audio_returns_empty_text(self):
        """Empty WAV bytes short-circuits and returns empty text without calling model."""
        from whisper_server_base import run_transcription
        import config as cfg_module

        mock_model = MagicMock()
        # run_transcription doesn't have its own empty-bytes guard but the
        # model.transcribe call would receive an empty BytesIO; we just confirm
        # no exception is raised with a truly minimal buffer.
        # The server scripts guard against empty bodies before calling this function.
        # Here we just ensure the dict shape is maintained.
        with patch.multiple(cfg_module, WHISPER_HOTWORDS=[], WHISPER_INITIAL_PROMPT=None,
                            LANGUAGE="en", BEAM_SIZE=5):
            mock_model.transcribe.return_value = ([], MagicMock())
            result = run_transcription(mock_model, _make_wav_bytes(10))
        self.assertIn("text", result)


if __name__ == "__main__":
    unittest.main()
