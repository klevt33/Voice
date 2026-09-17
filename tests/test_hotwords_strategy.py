"""
Unit tests for hotwords and initial_prompt wiring in LocalGPUTranscriptionStrategy.

Verifies that the new WHISPER_HOTWORDS and WHISPER_INITIAL_PROMPT config values
are correctly passed to WhisperModel.transcribe() by LocalGPUTranscriptionStrategy.
"""
import io
import sys
import types
import unittest
from unittest.mock import MagicMock, patch, call


# ---------------------------------------------------------------------------
# Helpers to build a minimal fake WhisperModel so LocalGPUTranscriptionStrategy
# can be instantiated without torch / faster-whisper installed.
# ---------------------------------------------------------------------------

def _make_fake_segments():
    """Return a minimal iterable of fake segment objects."""
    seg = MagicMock()
    seg.text = "Claude wrote some code."
    return [seg]


def _build_strategy_with_mocked_model(hotwords, initial_prompt):
    """
    Instantiate LocalGPUTranscriptionStrategy with a mocked WhisperModel
    and the given hotwords / initial_prompt injected via config patching.
    Returns (strategy, mock_transcribe_call).
    """
    import sys
    import os

    # Ensure project root is on sys.path
    project_root = os.path.join(os.path.dirname(__file__), "..")
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from transcription_strategies import LocalGPUTranscriptionStrategy, StrategyConfig

    config = StrategyConfig(
        name="local_gpu",
        enabled=True,
        priority=1,
        timeout=30.0,
        retry_count=0,
        specific_config={},
    )

    with patch("transcription_strategies.LocalGPUTranscriptionStrategy._detect_device"):
        strategy = LocalGPUTranscriptionStrategy(config)
        strategy._device = "cpu"

    # Inject a pre-loaded fake model so load_model() is skipped
    mock_model = MagicMock()
    mock_model.transcribe.return_value = (_make_fake_segments(), MagicMock())
    strategy._model = mock_model

    # Build a fake audio segment
    fake_audio = MagicMock()
    import wave, struct
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(struct.pack("<100h", *([0] * 100)))
    fake_audio.get_wav_bytes.return_value = buf.getvalue()

    config_patch_values = {
        "LANGUAGE": "en",
        "BEAM_SIZE": 5,
        "WHISPER_HOTWORDS": hotwords,
        "WHISPER_INITIAL_PROMPT": initial_prompt,
    }

    import config as cfg_module
    with patch.multiple(cfg_module, **config_patch_values):
        result = strategy.transcribe(fake_audio)

    return result, mock_model.transcribe


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestHotwordsWiring(unittest.TestCase):

    def test_hotwords_passed_when_list_is_non_empty(self):
        """When WHISPER_HOTWORDS has entries, transcribe() receives the joined string."""
        hotwords = ["Claude", "Claude Code", "Sonnet"]
        result, mock_transcribe = _build_strategy_with_mocked_model(hotwords, None)

        _, kwargs = mock_transcribe.call_args
        self.assertEqual(kwargs["hotwords"], "Claude Claude Code Sonnet")

    def test_hotwords_none_when_list_is_empty(self):
        """When WHISPER_HOTWORDS is empty, transcribe() receives hotwords=None."""
        result, mock_transcribe = _build_strategy_with_mocked_model([], None)

        _, kwargs = mock_transcribe.call_args
        self.assertIsNone(kwargs["hotwords"])

    def test_initial_prompt_passed_when_set(self):
        """When WHISPER_INITIAL_PROMPT is a non-empty string, it is forwarded."""
        prompt = "Use proper capitalization."
        result, mock_transcribe = _build_strategy_with_mocked_model([], prompt)

        _, kwargs = mock_transcribe.call_args
        self.assertEqual(kwargs["initial_prompt"], prompt)

    def test_initial_prompt_none_when_empty_string(self):
        """When WHISPER_INITIAL_PROMPT is an empty string, transcribe() receives None."""
        result, mock_transcribe = _build_strategy_with_mocked_model([], "")

        _, kwargs = mock_transcribe.call_args
        self.assertIsNone(kwargs["initial_prompt"])

    def test_initial_prompt_none_when_none(self):
        """When WHISPER_INITIAL_PROMPT is None, transcribe() receives None."""
        result, mock_transcribe = _build_strategy_with_mocked_model([], None)

        _, kwargs = mock_transcribe.call_args
        self.assertIsNone(kwargs["initial_prompt"])

    def test_both_hotwords_and_prompt_together(self):
        """Both hotwords and initial_prompt can be active at the same time."""
        hotwords = ["Opus", "Fable"]
        prompt = "Proper punctuation."
        result, mock_transcribe = _build_strategy_with_mocked_model(hotwords, prompt)

        _, kwargs = mock_transcribe.call_args
        self.assertEqual(kwargs["hotwords"], "Opus Fable")
        self.assertEqual(kwargs["initial_prompt"], prompt)

    def test_transcription_result_text_returned(self):
        """The result text from the mock model is surfaced in TranscriptionResult."""
        result, _ = _build_strategy_with_mocked_model(["Claude"], "prompt")
        self.assertEqual(result.text, "Claude wrote some code.")

    def test_single_hotword_not_joined_with_space(self):
        """A single-element list produces the word itself (no trailing space)."""
        result, mock_transcribe = _build_strategy_with_mocked_model(["Astra"], None)

        _, kwargs = mock_transcribe.call_args
        self.assertEqual(kwargs["hotwords"], "Astra")


if __name__ == "__main__":
    unittest.main()
