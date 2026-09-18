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

SAMPLE_PROMPT = "The following is a spoken transcript. Use proper capitalization and punctuation."


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

def test_closed_caption_short_filtered():
    assert apply_hallucination_filter("Closed Caption") == ""

def test_closed_caption_mixed_case_filtered():
    assert apply_hallucination_filter("CLOSED CAPTION by AI") == ""

def test_closed_caption_under_65_filtered():
    # 64 chars starting with "closed caption"
    text = "Closed captioning provided by the network" + " " * 23
    text = text[:64]
    assert apply_hallucination_filter(text) == ""

def test_closed_caption_65_or_more_passes():
    # Exactly 65 chars starting with "closed caption" should pass
    text = ("Closed captioning provided by the network" + "x" * 30)[:65]
    assert apply_hallucination_filter(text) == text

def test_closed_caption_long_passes():
    # A long sentence that happens to start with "closed caption"
    text = "Closed captioning provided by the network for all viewers watching at home today."
    assert len(text) >= 65
    assert apply_hallucination_filter(text) == text

# ---------------------------------------------------------------------------
# "for more information visit" filter
# ---------------------------------------------------------------------------

def test_for_more_information_visit_basic_filtered():
    assert apply_hallucination_filter("For more information visit www.example.com") == ""

def test_for_more_information_visit_with_comma_filtered():
    # Comma between "information" and "visit" should be stripped away
    assert apply_hallucination_filter("For more information, visit www.fema.gov.au") == ""

def test_for_more_information_visit_uppercase_filtered():
    assert apply_hallucination_filter("FOR MORE INFORMATION VISIT OUR WEBSITE") == ""

def test_for_more_information_visit_mixed_punctuation_filtered():
    assert apply_hallucination_filter("For more information, visit: www.site.org") == ""

def test_for_more_information_does_not_filter_without_visit():
    # "for more information" alone, without "visit", should pass
    text = "For more information on this topic, please read the attached document carefully."
    assert apply_hallucination_filter(text) == text

# ---------------------------------------------------------------------------
# Initial prompt echo filter
# ---------------------------------------------------------------------------

def test_exact_prompt_match_filtered():
    assert apply_hallucination_filter(SAMPLE_PROMPT, SAMPLE_PROMPT) == ""

def test_prompt_match_with_surrounding_whitespace_filtered():
    # Leading/trailing whitespace on the transcription is stripped before comparison
    assert apply_hallucination_filter("  " + SAMPLE_PROMPT + "  ", SAMPLE_PROMPT) == ""

def test_prompt_match_no_prompt_arg_passes():
    # Without the prompt argument the echo should NOT be filtered
    assert apply_hallucination_filter(SAMPLE_PROMPT) == SAMPLE_PROMPT

def test_prompt_none_passes():
    # Explicit None prompt disables the check
    assert apply_hallucination_filter(SAMPLE_PROMPT, None) == SAMPLE_PROMPT

def test_partial_prompt_first_sentence_filtered():
    # Whisper sometimes echoes only the opening sentence of the prompt
    first_sentence = "The following is a spoken transcript."
    assert apply_hallucination_filter(first_sentence, SAMPLE_PROMPT) == ""

def test_partial_prompt_case_insensitive_filtered():
    # Capitalisation in the echo should not matter
    echo = "the following is a spoken transcript."
    assert apply_hallucination_filter(echo, SAMPLE_PROMPT) == ""

def test_partial_prompt_4_words_filtered():
    # Exactly 4 words — at the minimum threshold, should be filtered
    four_words = " ".join(SAMPLE_PROMPT.split()[:4])
    assert apply_hallucination_filter(four_words, SAMPLE_PROMPT) == ""

def test_partial_prompt_3_words_passes():
    # 3 words is below the threshold — should NOT be filtered
    three_words = " ".join(SAMPLE_PROMPT.split()[:3])
    assert apply_hallucination_filter(three_words, SAMPLE_PROMPT) == three_words

def test_different_text_not_filtered_by_prompt():
    text = "This is genuine transcribed speech from the meeting."
    assert apply_hallucination_filter(text, SAMPLE_PROMPT) == text


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
