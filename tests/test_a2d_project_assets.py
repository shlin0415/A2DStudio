from pathlib import Path

import pytest

from ling_chat.core.a2d_project_assets import resolve_reference_audio_path


def test_reference_audio_resolves_inside_character_resources(tmp_path: Path) -> None:
    character_root = tmp_path / "character"
    reference_path = character_root / "voices" / "reference.wav"
    reference_path.parent.mkdir(parents=True)
    reference_path.write_bytes(b"RIFF----WAVE")

    resolved_path = resolve_reference_audio_path(reference_path, character_root, False)

    assert resolved_path == reference_path.resolve()


def test_reference_audio_rejects_path_outside_character_resources(tmp_path: Path) -> None:
    character_root = tmp_path / "character"
    reference_path = tmp_path / "outside.wav"
    character_root.mkdir()
    reference_path.write_bytes(b"RIFF----WAVE")

    with pytest.raises(ValueError, match="角色资源目录"):
        resolve_reference_audio_path(reference_path, character_root, False)


def test_reference_audio_rejects_missing_file(tmp_path: Path) -> None:
    character_root = tmp_path / "character"
    character_root.mkdir()

    with pytest.raises(FileNotFoundError):
        resolve_reference_audio_path(character_root / "missing.wav", character_root, False)


def test_reference_audio_rejects_environment_override_without_echoing_value(tmp_path: Path) -> None:
    character_root = tmp_path / "character"
    reference_path = character_root / "reference.wav"
    character_root.mkdir()
    reference_path.write_bytes(b"RIFF----WAVE")

    with pytest.raises(ValueError) as error:
        resolve_reference_audio_path(reference_path, character_root, True)

    assert "环境覆盖" in str(error.value)
    assert "reference.wav" not in str(error.value)
