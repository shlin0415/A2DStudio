"""Tests for fanfiction pipeline CLI (AC-7)."""

import json
from pathlib import Path

import pytest

from ling_chat.core.fic_pipeline import main


FIC = Path("tmp/ref-article/ema-hiro-heart.md")


@pytest.fixture
def tmp_out(tmp_path: Path) -> Path:
    return tmp_path / "out"


@pytest.mark.skipif(not FIC.exists(), reason="fixture fanfiction missing")
class TestDryRun:
    def test_dry_run_exits_zero_without_llm(self, tmp_out: Path):
        rc = main(["--input", str(FIC), "--output", str(tmp_out), "--dry-run"])
        assert rc == 0
        # Dry-run must NOT create the output directory.
        assert not tmp_out.exists()

    def test_run_writes_manifest(self, tmp_out: Path, monkeypatch):
        # Mock the LLM so this tests pipeline wiring, not the live model.
        async def _fake_call(self, messages):
            return '{"speaker":"ema"}\n【高兴】你好<こんにちは>（笑う）'

        monkeypatch.setattr(
            "ling_chat.core.fic_runtime.FicRuntime._call_llm", _fake_call
        )
        rc = main(["--input", str(FIC), "--output", str(tmp_out), "--seed", "42"])
        assert rc == 0
        manifest = tmp_out / "fic_manifest.json"
        assert manifest.exists()
        data = json.loads(manifest.read_text(encoding="utf-8"))
        assert data["seed"] == 42
        # Real run emits a "lines" array (generated script lines).
        assert data["line_count"] == len(data["lines"])
        assert data["line_count"] >= 1

    def test_seed_reproducibility(self, tmp_out: Path, monkeypatch):
        """Same seed -> identical manifest (line count)."""
        async def _fake_call(self, messages):
            return '{"speaker":"ema"}\n【高兴】你好<こんにちは>（笑う）'

        monkeypatch.setattr(
            "ling_chat.core.fic_runtime.FicRuntime._call_llm", _fake_call
        )
        a = tmp_out / "a"
        b = tmp_out / "b"
        main(["--input", str(FIC), "--output", str(a), "--seed", "7"])
        main(["--input", str(FIC), "--output", str(b), "--seed", "7"])
        ma = json.loads((a / "fic_manifest.json").read_text(encoding="utf-8"))
        mb = json.loads((b / "fic_manifest.json").read_text(encoding="utf-8"))
        assert ma["line_count"] == mb["line_count"]


class TestNegative:
    def test_missing_input_arg(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main([])
        assert exc.value.code != 0
        err = capsys.readouterr().err
        assert "required" in err or "usage" in err

    def test_missing_file_exits_cleanly(self, tmp_out: Path, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["--input", "tmp/does_not_exist.md", "--output", str(tmp_out)])
        assert exc.value.code == 1
        assert "not found" in capsys.readouterr().err

    def test_invalid_chunk_max_chars(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(
                [
                    "--input",
                    str(FIC),
                    "--output",
                    "tmp/fic_out",
                    "--chunk-max-chars",
                    "0",
                ]
            )
        assert exc.value.code != 0
