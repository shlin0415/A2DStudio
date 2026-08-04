"""Backend test for A2D save persistence (Option B, DEC-1).

Tests the pure persist_envelope() logic WITHOUT FastAPI (the env has a
FastAPI 0.104.1 / Starlette 1.3.1 mismatch that breaks TestClient).
This keeps the test runnable in the default `pytest` invocation so the
copy/rewrite path is actually exercised (not skipif-gated).
"""
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from ling_chat.api.a2d_persist import persist_envelope


def _make_envelope(lines):
    return {
        "version": 2,
        "script": {"lines": lines},
        "game": {"gameRoles": {}, "presentRoleIds": []},
    }


class TestPersistEnvelope:
    def setup_method(self):
        # Seed real WAV bytes in a temp audio dir.
        self.tmp_dir = tempfile.mkdtemp(prefix="a2d_test_")
        self.wav_dir = Path(self.tmp_dir) / "audio"
        self.wav_dir.mkdir()
        (self.wav_dir / "a2d_lineA.wav").write_bytes(b"RIFF-lineA-wav-bytes")
        (self.wav_dir / "a2d_lineB.wav").write_bytes(b"RIFF-lineB-wav-bytes")
        # Isolated save dir per test.
        self.save_dir = Path(tempfile.mkdtemp(prefix="a2d_save_")) / "save001"
        self.audio_dir = self.save_dir / "audio"
        self.audio_dir.mkdir(parents=True)

    def teardown_method(self):
        os.environ.pop("TEMP_VOICE_DIR", None)

    def test_copies_wavs_and_rewrites_paths(self):
        """WAVs copied to bare line_id path; audio_paths rewritten to per-save route."""
        with patch.dict(os.environ, {"TEMP_VOICE_DIR": str(self.wav_dir)}):
            envelope = _make_envelope([
                {"id": "l1", "audio_path": "/audio/a2d_lineA.wav"},
                {"id": "l2", "audio_path": "/audio/a2d_lineB.wav"},
            ])
            copied = persist_envelope(envelope, self.save_dir, self.audio_dir)

        assert copied == 2
        # Destination uses bare line_id (matches serve route).
        assert (self.audio_dir / "lineA.wav").exists()
        assert (self.audio_dir / "lineB.wav").exists()
        # Bytes preserved.
        assert (self.audio_dir / "lineA.wav").read_bytes() == b"RIFF-lineA-wav-bytes"
        # Paths rewritten to per-save route.
        lines = envelope["script"]["lines"]
        assert lines[0]["audio_path"] == "/api/a2d/save/audio/save001/lineA.wav"
        assert lines[1]["audio_path"] == "/api/a2d/save/audio/save001/lineB.wav"

    def test_missing_audio_graceful(self):
        """Lines whose source WAV doesn't exist are skipped, not failed."""
        with patch.dict(os.environ, {"TEMP_VOICE_DIR": str(self.wav_dir)}):
            envelope = _make_envelope([
                {"id": "l1", "audio_path": "/audio/a2d_nonexistent.wav"},
            ])
            copied = persist_envelope(envelope, self.save_dir, self.audio_dir)

        assert copied == 0
        # Path still rewritten even when copy failed.
        assert envelope["script"]["lines"][0]["audio_path"] == "/api/a2d/save/audio/save001/nonexistent.wav"

    def test_non_audio_lines_untouched(self):
        """Lines without audio_path or with non-matching paths are left alone."""
        with patch.dict(os.environ, {"TEMP_VOICE_DIR": str(self.wav_dir)}):
            envelope = _make_envelope([
                {"id": "l1", "audio_path": None},
                {"id": "l2", "audio_path": "/some/other/file.mp3"},
                {"id": "l3", "audio_path": "/audio/a2d_lineA.wav"},
            ])
            copied = persist_envelope(envelope, self.save_dir, self.audio_dir)

        assert copied == 1
        lines = envelope["script"]["lines"]
        assert lines[0]["audio_path"] is None
        assert lines[1]["audio_path"] == "/some/other/file.mp3"
        assert lines[2]["audio_path"] == "/api/a2d/save/audio/save001/lineA.wav"
