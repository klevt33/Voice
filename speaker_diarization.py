# speaker_diarization.py
"""Client-side speaker diarization via pyannote.audio (optional dependency).

pyannote is intentionally NOT in requirements.in: installing it via
pip-compile would resolve its own torch dependency and could clobber the
pinned CUDA torch build.  Install it manually instead:

    pip install pyannote.audio

It also requires a HuggingFace account with accepted licenses for the gated
models and an HF_TOKEN environment variable — see SETUP_GUIDE.md.
"""
import io
import logging
import os
import time
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# A speaker turn: (start_seconds, end_seconds, speaker_label)
SpeakerTurn = Tuple[float, float, str]

_pipeline = None
_pipeline_failed = False


def diarization_available() -> bool:
    """True when pyannote/torchaudio are installed and an HF token is set."""
    from config import HF_TOKEN_ENV_VAR

    if not os.getenv(HF_TOKEN_ENV_VAR):
        return False
    try:
        import pyannote.audio  # noqa: F401
        import torchaudio  # noqa: F401
    except Exception:
        return False
    return True


def _load_pipeline():
    """Load the diarization pipeline once (GPU when available)."""
    global _pipeline, _pipeline_failed
    if _pipeline is not None or _pipeline_failed:
        return _pipeline
    try:
        import torch
        from pyannote.audio import Pipeline
        from config import DIARIZATION_MODEL, HF_TOKEN_ENV_VAR

        token = os.getenv(HF_TOKEN_ENV_VAR)
        try:
            pipeline = Pipeline.from_pretrained(DIARIZATION_MODEL, token=token)
        except TypeError:
            # pyannote.audio 3.x names the argument use_auth_token
            pipeline = Pipeline.from_pretrained(DIARIZATION_MODEL, use_auth_token=token)

        from config import (
            DIARIZATION_CLUSTERING_THRESHOLD, DIARIZATION_MIN_CLUSTER_SIZE,
        )
        if DIARIZATION_CLUSTERING_THRESHOLD is not None:
            pipeline.instantiate({
                "clustering": {
                    "method": "average",
                    "threshold": DIARIZATION_CLUSTERING_THRESHOLD,
                    # Smaller clusters survive — short turns (quick answers)
                    # are otherwise absorbed into neighbouring speakers.
                    "min_cluster_size": DIARIZATION_MIN_CLUSTER_SIZE,
                }
            })
            logger.info(
                f"Diarization clustering threshold: "
                f"{DIARIZATION_CLUSTERING_THRESHOLD}, "
                f"min_cluster_size: {DIARIZATION_MIN_CLUSTER_SIZE}"
            )

        device = "cuda" if torch.cuda.is_available() else "cpu"
        pipeline.to(torch.device(device))
        logger.info(f"Diarization pipeline '{DIARIZATION_MODEL}' loaded on {device}")
        _pipeline = pipeline
    except Exception as exc:
        logger.error(
            f"Failed to load diarization pipeline: {exc}. "
            "Check pyannote.audio is installed, HF_TOKEN is set and the gated "
            "model licenses have been accepted (see SETUP_GUIDE.md)."
        )
        _pipeline_failed = True
    return _pipeline


def diarize(wav_bytes: bytes) -> Optional[List[SpeakerTurn]]:
    """Return speaker turns [(start, end, label), ...] sorted by start, or None.

    Failures (model unavailable, decode errors) return None so the caller can
    fall back to a single unsplit topic.
    """
    pipeline = _load_pipeline()
    if pipeline is None:
        return None
    try:
        import torchaudio

        waveform, sample_rate = torchaudio.load(io.BytesIO(wav_bytes))
        t0 = time.time()
        output = pipeline({"waveform": waveform, "sample_rate": sample_rate})
        elapsed = time.time() - t0

        # pyannote.audio 4.x wraps the Annotation in a DiarizeOutput object.
        annotation = getattr(output, "speaker_diarization", output)
        turns = [
            (turn.start, turn.end, speaker)
            for turn, _, speaker in annotation.itertracks(yield_label=True)
        ]
        turns.sort(key=lambda t: t[0])
        logger.info(f"Diarization took {elapsed:.1f}s for "
                    f"{waveform.shape[1] / sample_rate:.1f}s audio: "
                    f"{len(turns)} turns, "
                    f"{len({t[2] for t in turns})} distinct speakers")
        logger.info(f"Diarization turns: "
                    f"{[(round(s, 2), round(e, 2), l) for s, e, l in turns]}")
        return turns
    except Exception as exc:
        logger.error(f"Diarization failed: {exc}")
        return None
