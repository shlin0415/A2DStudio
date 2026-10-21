from pathlib import Path

from ling_chat.api import chat_cache, frontend_routes
from ling_chat.core.TTS import tts_provider
from ling_chat.utils import function as function_module


def test_tts_writes_audio_into_the_directory_served_by_audio_route(monkeypatch, tmp_path):
    monkeypatch.delenv("TEMP_VOICE_DIR", raising=False)
    monkeypatch.setattr(tts_provider, "temp_path", tmp_path)
    monkeypatch.setattr(frontend_routes, "temp_path", tmp_path)

    tts = tts_provider.TTS()
    audio_route = frontend_routes.get_audio_files()

    assert tts.temp_dir.resolve() == Path(audio_route.directory).resolve()


def test_voice_cache_reads_from_the_directory_served_by_audio_route(monkeypatch, tmp_path):
    monkeypatch.delenv("TEMP_VOICE_DIR", raising=False)
    monkeypatch.setattr(chat_cache, "temp_path", tmp_path)
    monkeypatch.setattr(frontend_routes, "temp_path", tmp_path)

    audio_route = frontend_routes.get_audio_files()

    cache_directory = chat_cache._resolve_voice_cache_dir().resolve()
    served_directory = Path(audio_route.directory).resolve()
    assert cache_directory == served_directory


def test_voice_cleanup_removes_files_from_the_directory_served_by_audio_route(monkeypatch, tmp_path):
    monkeypatch.delenv("TEMP_VOICE_DIR", raising=False)
    monkeypatch.delenv("VOICE_FORMAT", raising=False)
    monkeypatch.setattr(function_module, "temp_path", tmp_path)
    monkeypatch.setattr(frontend_routes, "temp_path", tmp_path)
    audio_route = frontend_routes.get_audio_files()
    generated_voice = Path(audio_route.directory) / "test.wav"
    generated_voice.write_bytes(b"temporary voice data")

    function = function_module.Function.__new__(function_module.Function)
    function.clean_temp_files()

    assert not generated_voice.exists()
