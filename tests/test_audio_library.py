"""测试 AudioLibraryIndex — FTS5 加载 + 搜索（需 ref_audio_library/）"""
import os
import pytest
from ling_chat.core.audio_library import AudioLibraryIndex


def _ema_list_path():
    return os.path.join("ref_audio_library", "ema", "ema.list")


def _ema_audio_dir():
    return os.path.join("ref_audio_library", "ema", "ema_audio")


def _skip_if_no_data():
    if not os.path.exists(_ema_list_path()):
        pytest.skip("ref_audio_library/ema not available")


@pytest.fixture
def ema_index(tmp_path):
    """用真实 ema.list 建索引（在临时 DB 中，不污染生产数据）"""
    _skip_if_no_data()
    db_path = str(tmp_path / "audio_test.db")
    idx = AudioLibraryIndex(db_path)
    n = idx.load_list(_ema_list_path(), "ema", _ema_audio_dir())
    assert n > 0, f"Expected clips loaded, got {n}"
    return idx


class TestIndexLoading:
    def test_loads_clips(self, ema_index):
        """真实 ema.list 应加载 > 0 条"""
        pass  # fixture 中已 assert n > 0

    def test_missing_list_file_returns_zero(self, tmp_path):
        idx = AudioLibraryIndex(str(tmp_path / "test.db"))
        n = idx.load_list("/nonexistent/path.list", "test", "/tmp")
        assert n == 0


class TestSearch:
    def test_search_returns_results(self, ema_index):
        results = ema_index.search("ema", "牢屋", limit=5)
        assert len(results) > 0

    def test_search_no_match(self, ema_index):
        results = ema_index.search("ema", "XYZZY_DOES_NOT_EXIST_12345", limit=5)
        assert len(results) == 0

    def test_search_result_has_required_fields(self, ema_index):
        results = ema_index.search("ema", "はい", limit=1)
        assert len(results) > 0
        r = results[0]
        assert "file_path" in r
        assert "text" in r
        assert "character" in r
        assert r["character"] == "ema"

    def test_search_respects_limit(self, ema_index):
        results = ema_index.search("ema", "はい", limit=3)
        assert len(results) <= 3


class TestGetClip:
    def test_get_existing_clip(self, ema_index):
        results = ema_index.search("ema", "はい", limit=1)
        assert len(results) > 0
        clip = ema_index.get_clip(results[0]["id"])
        assert clip is not None
        assert clip["id"] == results[0]["id"]

    def test_get_nonexistent_clip(self, ema_index):
        clip = ema_index.get_clip(99999999)
        assert clip is None
