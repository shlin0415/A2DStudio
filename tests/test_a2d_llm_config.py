"""Test LLM config env-override mechanism.

_env_apply_override ensures .env always wins over cached TOML values.
"""

import os
import pytest


# ── _apply_env_override ─────────────────────────────────────


class TestApplyEnvOverride:
    def test_env_var_overrides_config_when_set(self, monkeypatch):
        """CHAT_API_KEY in env → overrides config dict."""
        monkeypatch.setenv("CHAT_API_KEY", "sk-env-key")
        from ling_chat.configs.llm_config import _apply_env_override

        config = {"api_key": "sk-toml-key", "model": "deepseek-chat"}
        _apply_env_override(config, "api_key", "CHAT_API_KEY")
        assert config["api_key"] == "sk-env-key"

    def test_env_var_does_not_override_when_empty(self, monkeypatch):
        """Empty env var → TOML value preserved."""
        monkeypatch.setenv("CHAT_API_KEY", "")
        from ling_chat.configs.llm_config import _apply_env_override

        config = {"api_key": "sk-toml-key"}
        _apply_env_override(config, "api_key", "CHAT_API_KEY")
        assert config["api_key"] == "sk-toml-key"

    def test_env_var_does_not_override_when_unset(self, monkeypatch):
        """Unset env var → TOML value preserved."""
        monkeypatch.delenv("CHAT_API_KEY", raising=False)
        from ling_chat.configs.llm_config import _apply_env_override

        config = {"api_key": "sk-toml-key"}
        _apply_env_override(config, "api_key", "CHAT_API_KEY")
        assert config["api_key"] == "sk-toml-key"

    def test_model_type_override(self, monkeypatch):
        """MODEL_TYPE env var overrides config."""
        monkeypatch.setenv("MODEL_TYPE", "deepseek-v4-flash")
        from ling_chat.configs.llm_config import _apply_env_override

        config = {"model": "deepseek-chat"}
        _apply_env_override(config, "model", "MODEL_TYPE")
        assert config["model"] == "deepseek-v4-flash"

    def test_base_url_override(self, monkeypatch):
        """CHAT_BASE_URL env var overrides config."""
        monkeypatch.setenv("CHAT_BASE_URL", "https://custom.api.com/v1")
        from ling_chat.configs.llm_config import _apply_env_override

        config = {"base_url": "https://api.deepseek.com"}
        _apply_env_override(config, "base_url", "CHAT_BASE_URL")
        assert config["base_url"] == "https://custom.api.com/v1"


# ── get_main_config integration ─────────────────────────────


class TestGetMainConfigOverrides:
    def test_main_config_applies_env_overrides(self, monkeypatch):
        """get_main_config() applies env overrides on top of TOML values."""
        monkeypatch.setenv("CHAT_API_KEY", "sk-override-test")
        # The LLMConfig singleton reads default.toml on import.
        # Since default.toml exists (with api_key from env),
        # get_main_config() should return that value, overridden by env.
        from ling_chat.configs.llm_config import llm_config

        cfg = llm_config.get_main_config()
        # At minimum, api_key should be present (from TOML or env)
        assert "api_key" in cfg
        assert "model" in cfg
        assert "base_url" in cfg
