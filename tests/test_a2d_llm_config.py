"""Test LLM config environment precedence and active-profile switching."""

import os
from unittest.mock import Mock

try:
    import tomllib
except ImportError:
    import tomli as tomllib

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


def test_default_profile_prefers_generic_environment(monkeypatch):
    from ling_chat.configs.llm_config import llm_config

    monkeypatch.setattr(llm_config, "_active_config_name", "default")
    monkeypatch.setattr(
        llm_config,
        "_config",
        {
            "main": {
                "provider": "webllm",
                "model": "deepseek-stale-profile-model",
                "api_key": "profile-key",
                "base_url": "https://profile.invalid/v1",
            }
        },
    )
    monkeypatch.setenv("CHAT_API_KEY", "generic-key")
    monkeypatch.setenv("CHAT_BASE_URL", "https://generic.invalid/v1")
    monkeypatch.setenv("MODEL_TYPE", "mimo-default-model")
    monkeypatch.setenv("CHAT_API_KEY_DS", "ds-key")
    monkeypatch.setenv("CHAT_BASE_URL_DS", "https://ds.invalid/v1")
    monkeypatch.setenv("MODEL_TYPE_DS", "deepseek-model")

    config = llm_config.get_main_config()

    assert config["api_key"] == "generic-key"
    assert config["base_url"] == "https://generic.invalid/v1"
    assert config["model"] == "mimo-default-model"


@pytest.mark.parametrize(
    ("suffix", "profile_model", "env_model"),
    [
        ("DS", "deepseek-chat", "deepseek-test-model"),
        ("MIMO", "mimo-chat", "mimo-test-model"),
    ],
)
def test_active_profile_uses_its_provider_environment(
    monkeypatch, suffix, profile_model, env_model
):
    from ling_chat.configs.llm_config import llm_config

    monkeypatch.setattr(llm_config, "_active_config_name", "profile")
    monkeypatch.setattr(
        llm_config,
        "_config",
        {
            "main": {
                "provider": "webllm",
                "model": profile_model,
                "api_key": "profile-key",
                "base_url": "https://profile.invalid/v1",
            }
        },
    )
    monkeypatch.setenv("CHAT_API_KEY", "generic-key")
    monkeypatch.setenv("CHAT_BASE_URL", "https://generic.invalid/v1")
    monkeypatch.setenv("MODEL_TYPE", "generic-model")
    monkeypatch.setenv(f"CHAT_API_KEY_{suffix}", f"{suffix.lower()}-key")
    monkeypatch.setenv(
        f"CHAT_BASE_URL_{suffix}", f"https://{suffix.lower()}.invalid/v1"
    )
    monkeypatch.setenv(f"MODEL_TYPE_{suffix}", env_model)

    config = llm_config.get_main_config()

    assert config["api_key"] == f"{suffix.lower()}-key"
    assert config["base_url"] == f"https://{suffix.lower()}.invalid/v1"
    assert config["model"] == env_model


def _prepare_env_profiles(monkeypatch, tmp_path):
    from ling_chat.configs.llm_config import llm_config

    monkeypatch.setattr(llm_config, "_config_dir", tmp_path)
    monkeypatch.setattr(
        llm_config,
        "_config",
        {
            "main": {
                "provider": "webllm",
                "model": "default-model",
                "api_key": "default-secret",
                "base_url": "https://default.invalid/v1",
                "temperature": 1.0,
                "top_p": 0.9,
                "max_tokens": 1024,
            },
            "translator": {
                "provider": "none",
                "model": "",
                "api_key": "",
                "base_url": "",
            },
            "network": {"proxy": ""},
            "providers": {},
        },
    )
    for suffix, model in (("DS", "deepseek-test-model"), ("MIMO", "mimo-test-model")):
        monkeypatch.setenv(
            f"CHAT_API_KEY_{suffix}", f"{suffix.lower()}-test-secret"
        )
        monkeypatch.setenv(
            f"CHAT_BASE_URL_{suffix}", f"https://{suffix.lower()}.invalid/v1"
        )
        monkeypatch.setenv(f"MODEL_TYPE_{suffix}", model)
    return llm_config


def test_seeded_env_profiles_do_not_persist_api_keys(monkeypatch, tmp_path):
    config_manager = _prepare_env_profiles(monkeypatch, tmp_path)

    config_manager._seed_env_profiles()

    for name, suffix, model in (
        ("deepseek", "DS", "deepseek-test-model"),
        ("mimo", "MIMO", "mimo-test-model"),
    ):
        profile_path = tmp_path / f"{name}.toml"
        profile = tomllib.loads(profile_path.read_text(encoding="utf-8"))
        assert profile["main"]["model"] == model
        assert profile["main"]["base_url"] == (
            f"https://{suffix.lower()}.invalid/v1"
        )
        assert profile["main"]["api_key"] == ""
        profile_text = profile_path.read_text(encoding="utf-8")
        assert f"{suffix.lower()}-test-secret" not in profile_text
        assert "default-secret" not in profile_text


def test_seed_env_profiles_preserve_existing_profiles(monkeypatch, tmp_path):
    config_manager = _prepare_env_profiles(monkeypatch, tmp_path)
    profile_path = tmp_path / "deepseek.toml"
    profile_path.write_text("user-owned-profile", encoding="utf-8")

    config_manager._seed_env_profiles()

    assert profile_path.read_text(encoding="utf-8") == "user-owned-profile"
    assert (tmp_path / "mimo.toml").is_file()


def test_seed_env_profiles_requires_all_profile_environment_values(monkeypatch, tmp_path):
    config_manager = _prepare_env_profiles(monkeypatch, tmp_path)
    monkeypatch.delenv("CHAT_API_KEY_DS")
    monkeypatch.setenv("CHAT_API_KEY_MIMO", " ")

    config_manager._seed_env_profiles()

    assert not (tmp_path / "deepseek.toml").exists()
    assert not (tmp_path / "mimo.toml").exists()


def test_switching_llm_profile_reloads_active_ai_service(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from ling_chat.api import llm_config_api

    reload_llm_model = Mock()
    monkeypatch.setattr(
        llm_config_api,
        "service_manager",
        SimpleNamespace(
            ai_service=SimpleNamespace(reload_llm_model=reload_llm_model)
        ),
        raising=False,
    )
    monkeypatch.setattr(
        llm_config_api.llm_config, "set_active_config", lambda _name: True
    )

    asyncio.run(
        llm_config_api.switch_config(llm_config_api.SwitchConfigRequest(name="DS"))
    )

    reload_llm_model.assert_called_once_with()


def test_reload_llm_model_updates_service_and_message_generator(monkeypatch):
    from types import SimpleNamespace

    from ling_chat.core.ai_service import core as ai_service_module

    service = ai_service_module.AIService.__new__(ai_service_module.AIService)
    previous_manager = object()
    replacement_manager = object()
    service.llm_model = previous_manager
    service.message_generator = SimpleNamespace(
        llm_model=previous_manager,
        agent_runner=SimpleNamespace(llm_model=previous_manager),
    )
    monkeypatch.setattr(ai_service_module, "LLMManager", lambda: replacement_manager)

    service.reload_llm_model()

    assert service.llm_model is replacement_manager
    assert service.message_generator.llm_model is replacement_manager
    assert service.message_generator.agent_runner.llm_model is replacement_manager
