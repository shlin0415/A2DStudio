"""Unit tests for ASR eval artifact stripping (AC-6).

_calibration strips leading/trailing non-voiced symbols (ellipsis + join-separator
commas) from BOTH target and ASR so WER is no longer artifactually 100% on short
JP lines. Internal voiced punctuation stays untouched.
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# compute_metrics imports jiwer (only in asr-env); test the pure helpers instead.
from tests.a2d_asr_eval import _normalize, _strip_artifacts


# ── _strip_artifacts ─────────────────────────────────────────


class TestStripArtifacts:
    def test_leading_ellipsis_stripped(self):
        """Leading …… (→ .. after _normalize) stripped."""
        assert _strip_artifacts(_normalize("……おやすみ")) == "おやすみ"

    def test_trailing_ellipsis_stripped(self):
        """Trailing …… stripped."""
        assert _strip_artifacts(_normalize("おやすみ……")) == "おやすみ"

    def test_clean_sample_unchanged(self):
        """Calibration must not distort clean samples (no leading/trailing artifacts)."""
        assert _strip_artifacts(_normalize("Hello")) == "Hello"

    def test_internal_comma_preserved(self):
        """Join separator becomes internal , after _normalize; voiced, must stay."""
        assert _strip_artifacts(_normalize("T1、T2")) == "T1,T2"

    def test_multi_segment_leading_trailing_commas_stripped(self):
        """Joined target ',T1,T2,' → stripped to 'T1,T2'."""
        assert _strip_artifacts(",T1,T2,") == "T1,T2"

    def test_internal_punctuation_preserved(self):
        """Internal 。 voiced by GSV — must stay."""
        assert _strip_artifacts(_normalize("こんにちは。さようなら")) == "こんにちは.さようなら"

    def test_symmetric_on_both_sides(self):
        """Applied to BOTH target and ASR — symmetric."""
        target = _strip_artifacts(_normalize("……おやすみ"))
        asr = _strip_artifacts(_normalize("おやすみ"))
        assert target == asr == "おやすみ"


# ── compute_metrics end-to-end (jiwer required) ──────────────


class TestCalibrationReducesWer:
    @pytest.mark.slow
    def test_calibration_reduces_wer_on_ellipsis_sample(self):
        """Before calibration: ……おやすみ vs おやすみ → WER=100%.

        After _strip_artifacts: both → おやすみ → WER=0.
        Requires jiwer (skipped if not installed).
        """
        try:
            from tests.a2d_asr_eval import compute_metrics
        except ImportError:
            pytest.skip("jiwer not installed (only in asr-env)")

        # Before-calibration baseline: simulate by calling with already-stripped
        # target but uncalibrated would be 100%; with calibration both match.
        result = compute_metrics("……おやすみ", "おやすみ")
        assert result["wer"] < 1.0, f"Expected WER < 1.0 after calibration, got {result['wer']}"
        assert result["wer"] == 0.0, f"Expected WER=0 for matching strings, got {result['wer']}"
