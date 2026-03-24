"""
Property-based test for the shared hallucination filter.

**Validates: Requirements 1.5**

Property 2: apply_hallucination_filter (transcription_strategies.py) is the
single canonical implementation used by LocalGPUTranscriptionStrategy,
GroqAPITranscriptionStrategy, and transcription_server.py.
"""

from hypothesis import given, settings
import hypothesis.strategies as st

from transcription_strategies import apply_hallucination_filter


# ---------------------------------------------------------------------------
# Known-value unit tests
# ---------------------------------------------------------------------------

def test_short_text_filtered():
    assert apply_hallucination_filter("Hi") == ""

def test_exactly_10_chars_filtered():
    assert apply_hallucination_filter("a" * 10) == ""

def test_11_chars_passes():
    assert apply_hallucination_filter("a" * 11) == "a" * 11

def test_thank_you_short_filtered():
    assert apply_hallucination_filter("Thank you.") == ""

def test_thank_you_long_passes():
    # > 40 chars with "thank" — should NOT be filtered
    long_text = "Thank you for watching this very long video presentation today"
    assert apply_hallucination_filter(long_text) == long_text

def test_subtitles_short_filtered():
    assert apply_hallucination_filter("Subtitles by community") == ""

def test_captions_short_filtered():
    assert apply_hallucination_filter("Captions by community") == ""

def test_normal_speech_passes():
    text = "The meeting starts at nine o'clock in the morning."
    assert apply_hallucination_filter(text) == text


# ---------------------------------------------------------------------------
# Property test
# ---------------------------------------------------------------------------

@given(st.text())
@settings(max_examples=500)
def test_filter_never_raises(text: str):
    """apply_hallucination_filter must never raise for any string input."""
    result = apply_hallucination_filter(text)
    assert isinstance(result, str)
    assert result == "" or result == text
