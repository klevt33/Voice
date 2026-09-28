"""
Property-based test for the shared hallucination filter.

**Validates: Requirements 1.5**

Property 2: apply_hallucination_filter (transcription_strategies.py) is the
single canonical implementation used by LocalGPUTranscriptionStrategy,
GroqAPITranscriptionStrategy, and transcription_server.py.
"""

from hypothesis import given, settings
import hypothesis.strategies as st

from transcription_strategies import apply_hallucination_filter, process_whisper_segments

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
# "transcription by" filter
# ---------------------------------------------------------------------------

def test_transcription_by_filtered():
    assert apply_hallucination_filter("Transcription by ESO. Translation by —") == ""

def test_transcription_by_lowercase_filtered():
    assert apply_hallucination_filter("transcription by someone") == ""

def test_transcription_by_uppercase_filtered():
    assert apply_hallucination_filter("TRANSCRIPTION BY AI") == ""

def test_transcription_by_only_filtered():
    # Even the bare two-word phrase should be filtered
    assert apply_hallucination_filter("Transcription by") == ""

def test_word_transcription_not_at_start_passes():
    # "transcription by" appearing mid-sentence is real speech
    text = "The transcription by the service was accurate and complete today."
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
# Prompt echo variants that used to leak through the filter.
#
# The previous implementation compared the transcription against raw prompt
# substrings with plain string equality, so any echo that differed from the
# prompt by a single character — a missing final full stop, a dropped space,
# a British spelling — passed the filter untouched.
# ---------------------------------------------------------------------------

def test_echo_without_trailing_period_filtered():
    # Whisper frequently drops the prompt's final full stop.
    text = "The following is a spoken transcript. Use proper capitalization and punctuation"
    assert apply_hallucination_filter(text, SAMPLE_PROMPT) == ""

def test_echo_first_sentence_without_period_filtered():
    text = "The following is a spoken transcript"
    assert apply_hallucination_filter(text, SAMPLE_PROMPT) == ""

def test_echo_with_shouty_capitalisation_filtered():
    text = SAMPLE_PROMPT.upper()
    assert apply_hallucination_filter(text, SAMPLE_PROMPT) == ""

def test_echo_without_space_after_sentence_stop_filtered():
    # Segments joined without a leading space produce "transcript.Use ...".
    text = "The following is a spoken transcript.Use proper capitalization and punctuation"
    assert apply_hallucination_filter(text, SAMPLE_PROMPT) == ""

def test_echo_with_near_miss_spelling_filtered():
    # "capitalisation" vs "capitalization" must not defeat the check.
    text = "The following is a spoken transcript. Use proper capitalisation and punctuation."
    assert apply_hallucination_filter(text, SAMPLE_PROMPT) == ""

def test_echo_truncated_mid_word_filtered():
    # Whisper cut the last word off mid-way.
    text = "The following is a spoken transcript. Use proper capitalization and punctua"
    assert apply_hallucination_filter(text, SAMPLE_PROMPT) == ""

def test_echo_with_extra_inner_whitespace_filtered():
    text = "The  following   is a spoken transcript.  Use proper capitalization and punctuation."
    assert apply_hallucination_filter(text, SAMPLE_PROMPT) == ""

def test_prompt_tail_echo_filtered():
    # Whisper can echo only the second half of the prompt, which is not a prefix.
    text = "Use proper capitalization and punctuation."
    assert apply_hallucination_filter(text, SAMPLE_PROMPT) == ""


# ---------------------------------------------------------------------------
# Prompt echo followed by real speech: the echo is stripped, the speech kept.
# ---------------------------------------------------------------------------

def test_echo_then_thanks_fully_filtered():
    text = (
        "The following is a spoken transcript. Use proper capitalization "
        "and punctuation. Thank you."
    )
    assert apply_hallucination_filter(text, SAMPLE_PROMPT) == ""

def test_echo_then_speech_keeps_only_speech():
    text = (
        "The following is a spoken transcript. Use proper capitalization "
        "and punctuation. And then we talked about the roadmap in detail."
    )
    assert apply_hallucination_filter(text, SAMPLE_PROMPT) == (
        "And then we talked about the roadmap in detail."
    )

def test_echo_then_speech_keeps_only_speech_without_spaces():
    text = (
        "The following is a spoken transcript.Use proper capitalization "
        "and punctuation. And then we talked about the roadmap in detail."
    )
    assert apply_hallucination_filter(text, SAMPLE_PROMPT) == (
        "And then we talked about the roadmap in detail."
    )

def test_repeated_echo_fully_filtered():
    text = (
        "The following is a spoken transcript. "
        "The following is a spoken transcript. Use proper capitalization and punctuation."
    )
    assert apply_hallucination_filter(text, SAMPLE_PROMPT) == ""

def test_weak_echo_does_not_truncate_real_speech():
    # Only 3 echoed words followed by real speech: too weak to strip, and the
    # text must be returned untouched rather than half-deleted.
    text = "The following is a plan for the quarter and it should be reviewed."
    assert apply_hallucination_filter(text, SAMPLE_PROMPT) == text

def test_real_speech_mentioning_prompt_words_not_stripped():
    # Uses prompt vocabulary but diverges after two words — genuine speech.
    text = "The following roadmap items are all dependent on the migration finishing first."
    assert apply_hallucination_filter(text, SAMPLE_PROMPT) == text

def test_prompt_echo_check_disabled_without_prompt():
    # Everything above is prompt-relative; without the prompt nothing is echoed.
    text = "The following is a spoken transcript. Use proper capitalization and punctuation."
    assert apply_hallucination_filter(text) == text
    assert apply_hallucination_filter(text, None) == text

def test_prompt_echo_check_disabled_for_empty_prompt():
    text = "The following is a spoken transcript. Use proper capitalization and punctuation."
    assert apply_hallucination_filter(text, "") == text


# ---------------------------------------------------------------------------
# Additional junk patterns
# ---------------------------------------------------------------------------

def test_sound_marker_filtered():
    assert apply_hallucination_filter("[MUSIC]") == ""
    assert apply_hallucination_filter("(applause)") == ""
    assert apply_hallucination_filter("\u266a\u266a") == ""

def test_amara_org_filtered():
    assert apply_hallucination_filter("Subtitles by the Amara.org community") == ""


# ---------------------------------------------------------------------------
# process_whisper_segments forwards initial_prompt to the filter
# (regression test for whisper_server_base.py bug where initial_prompt
#  was computed but not passed to process_whisper_segments)
# ---------------------------------------------------------------------------

class _FakeSegment:
    """Minimal stand-in for a faster-whisper segment object."""
    def __init__(self, text):
        self.text = text

def test_process_whisper_segments_filters_prompt_echo():
    # Simulate Whisper echoing the full initial prompt as a single segment
    segments = [_FakeSegment(SAMPLE_PROMPT)]
    assert process_whisper_segments(segments, SAMPLE_PROMPT) == ""

def test_process_whisper_segments_filters_partial_prompt_echo():
    # Simulate Whisper echoing only the first sentence of the prompt
    first_sentence = "The following is a spoken transcript."
    segments = [_FakeSegment(first_sentence)]
    assert process_whisper_segments(segments, SAMPLE_PROMPT) == ""

def test_process_whisper_segments_no_prompt_does_not_filter_echo():
    # Without initial_prompt, the echo should pass through unchanged
    segments = [_FakeSegment(SAMPLE_PROMPT)]
    assert process_whisper_segments(segments) == SAMPLE_PROMPT

def test_process_whisper_segments_passes_real_speech():
    text = "The quarterly results exceeded all analyst expectations."
    segments = [_FakeSegment(text)]
    assert process_whisper_segments(segments, SAMPLE_PROMPT) == text

def test_process_whisper_segments_drops_echo_segment():
    # Whisper emitted the echo as its own segment, then real speech.
    segments = [
        _FakeSegment(" The following is a spoken transcript."),
        _FakeSegment(" And then we talked about the roadmap."),
    ]
    assert process_whisper_segments(segments, SAMPLE_PROMPT) == (
        "And then we talked about the roadmap."
    )

def test_process_whisper_segments_drops_prompt_tail_fragment_segment():
    # The middle segment echoes the tail of the prompt, so it is not a prefix
    # and can only be recognised as a whole prompt fragment.
    segments = [
        _FakeSegment(" The following is a spoken transcript."),
        _FakeSegment(" Use proper capitalization and punctuation."),
        _FakeSegment(" And then we talked about pricing."),
    ]
    assert process_whisper_segments(segments, SAMPLE_PROMPT) == (
        "And then we talked about pricing."
    )

def test_process_whisper_segments_keeps_short_real_segments():
    # Segment-level filtering must not swallow short genuine speech.
    segments = [_FakeSegment(" Okay."), _FakeSegment(" Sure, let's start with pricing.")]
    assert process_whisper_segments(segments, SAMPLE_PROMPT) == (
        "Okay. Sure, let's start with pricing."
    )

def test_process_whisper_segments_handles_empty_segment_text():
    segments = [_FakeSegment(""), _FakeSegment("   ")]
    assert process_whisper_segments(segments, SAMPLE_PROMPT) == ""

def test_process_whisper_segments_empty_input():
    assert process_whisper_segments([], SAMPLE_PROMPT) == ""


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

@given(st.text())
@settings(max_examples=200)
def test_filter_with_prompt_returns_text_or_empty(text: str):
    """With a prompt, the filter either drops everything or only cuts a leading echo."""
    result = apply_hallucination_filter(text, SAMPLE_PROMPT)
    assert isinstance(result, str)
    # Stripping a prompt echo can only remove a leading chunk, so whatever
    # survives must still be a slice of the original text.
    assert result == "" or result in text

@given(st.text())
@settings(max_examples=200)
def test_process_whisper_segments_never_raises(text: str):
    """process_whisper_segments must never raise, whatever a segment contains."""
    result = process_whisper_segments([_FakeSegment(text)], SAMPLE_PROMPT)
    assert isinstance(result, str)
