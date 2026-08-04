"""Backend round-trip test for A2D save persistence (Option B, DEC-1)."""
import json
import os
import tempfile
from pathlib import Path

import pytest

from tests import BACKEND_URL, backend_ok

pytestmark = pytest.mark.skipif(not backend_ok(), reason="backend not running")


def _post(path, data=None):
    import urllib.request
    req = urllib.request.Request(
        f"{BACKEND_URL}{path}",
        data=json.dumps(data).encode() if data else None,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read()), resp.status


def _get(path):
    import urllib.request
    with urllib.request.urlopen(f"{BACKEND_URL}{path}", timeout=10) as resp:
        return resp.read(), resp.status


def _make_envelope(lines):
    return {
        "version": 2,
        "script": {"lines": lines},
        "game": {"gameRoles": {}, "presentRoleIds": []},
    }


class TestA2DSave:
    def setup_method(self):
        # Seed a temp audio dir with real WAV bytes.
        self.tmp_dir = tempfile.mkdtemp(prefix="a2d_test_")
        self.wav_dir = Path(self.tmp_dir) / "audio"
        self.wav_dir.mkdir()
        # Two WAV files in the on-disk format: a2d_{line_id}.wav.
        (self.wav_dir / "a2d_lineA.wav").write_bytes(b"RIFF-lineA-wav-bytes")
        (self.wav_dir / "a2d_lineB.wav").write_bytes(b"RIFF-lineB-wav-bytes")
        # Point TEMP_VOICE_DIR at our temp dir.
        os.environ["TEMP_VOICE_DIR"] = str(self.wav_dir)

    def teardown_method(self):
        os.environ.pop("TEMP_VOICE_DIR", None)

    def test_save_copies_wavs_and_rewrites_paths(self):
        """Export 2-line envelope -> WAVs copied, audio_paths rewritten to per-save route."""
        envelope = _make_envelope([
            {"id": "l1", "audio_path": "/audio/a2d_lineA.wav"},
            {"id": "l2", "audio_path": "/audio/a2d_lineB.wav"},
        ])
        body, status = _post("/api/a2d/save", {"envelope": envelope})
        assert status == 200
        assert body["ok"] is True
        save_id = body["save_id"]
        assert save_id

        # Re-fetch snapshot: audio_paths rewritten to per-save route.
        snap_bytes, status = _get(f"/api/a2d/save/{save_id}")
        assert status == 200
        snap = json.loads(snap_bytes)
        lines = snap["script"]["lines"]
        assert lines[0]["audio_path"] == f"/api/a2d/save/audio/{save_id}/lineA.wav"
        assert lines[1]["audio_path"] == f"/api/a2d/save/audio/{save_id}/lineB.wav"

        # Served WAVs return the original bytes.
        wav_bytes, status = _get(f"/api/a2d/save/audio/{save_id}/lineA.wav")
        assert status == 200
        assert wav_bytes == b"RIFF-lineA-wav-bytes"

    def test_save_handles_missing_audio_gracefully(self):
        """Lines whose source WAV doesn't exist are skipped, not failed."""
        envelope = _make_envelope([
            {"id": "l1", "audio_path": "/audio/a2d_nonexistent.wav"},
        ])
        body, status = _post("/api/a2d/save", {"envelope": envelope})
        assert status == 200
        assert body["ok"] is True

    def test_path_traversal_rejected(self):
        """Backslash/.. in path components returns 400."""
        import urllib.error
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            _get("/api/a2d/save/audio/..%2F..%2Fetc/passwd.wav")
        assert excinfo.value.code in (400, 404)
