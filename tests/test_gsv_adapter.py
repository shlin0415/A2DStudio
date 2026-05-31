"""测试 GSVAdapter — _split_text 切分逻辑 + anti_clipping"""
from ling_chat.core.TTS.gsv_adapter import GPTSoVITSAdapter


def make_adapter(**kwargs):
    return GPTSoVITSAdapter(ref_audio_path="test.wav", prompt_text="test", **kwargs)


class TestSplitText:
    def test_empty_string(self):
        assert make_adapter()._split_text("") == []

    def test_single_sentence(self):
        chunks = make_adapter()._split_text("こんにちは。")
        assert len(chunks) == 1
        assert "こんにちは。" in chunks[0]

    def test_splits_on_japanese_period(self):
        chunks = make_adapter()._split_text("はい。いいえ。")
        assert len(chunks) >= 2

    def test_splits_on_question_and_period(self):
        chunks = make_adapter()._split_text("そうですか？違います。")
        assert len(chunks) >= 2

    def test_long_text_produces_chunks(self):
        long_text = "これはとても長い文章です" * 5
        chunks = make_adapter()._split_text(long_text)
        assert len(chunks) > 0

    def test_realistic_dialogue_splits(self):
        text = "希罗ちゃん、今日も一緒にいてくれるの？本当にありがとう。"
        chunks = make_adapter()._split_text(text)
        assert len(chunks) > 1


class TestAntiClipping:
    def test_default_enabled(self):
        assert make_adapter().anti_clipping is True

    def test_can_disable(self):
        assert make_adapter(anti_clipping=False).anti_clipping is False

    def test_api_url_with_anti_clipping(self):
        a = make_adapter(api_url="http://127.0.0.1:31801", anti_clipping=True)
        assert a.api_url == "http://127.0.0.1:31801"
        assert a.anti_clipping is True
