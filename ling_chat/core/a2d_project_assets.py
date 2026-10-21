from pathlib import Path

MAX_REFERENCE_AUDIO_BYTES = 128 * 1024 * 1024


def resolve_reference_audio_path(
    reference_path: str | Path,
    character_root: str | Path,
    has_environment_override: bool,
) -> Path:
    """Return a configured WAV only when it resolves inside its character folder."""
    if has_environment_override:
        raise ValueError("环境覆盖启用时不能导出角色参考音频")
    if not str(reference_path).strip() or not str(character_root).strip():
        raise ValueError("缺少角色参考音频或角色资源目录")

    resolved_root = Path(character_root).resolve(strict=True)
    if not resolved_root.is_dir():
        raise FileNotFoundError("角色资源目录不存在")

    resolved_reference = Path(reference_path).resolve(strict=True)
    try:
        resolved_reference.relative_to(resolved_root)
    except ValueError:
        raise ValueError("参考音频必须位于角色资源目录内") from None

    if not resolved_reference.is_file():
        raise FileNotFoundError("角色参考音频不存在")
    if resolved_reference.suffix.lower() != ".wav":
        raise ValueError("角色参考音频必须是 WAV 文件")
    if resolved_reference.stat().st_size > MAX_REFERENCE_AUDIO_BYTES:
        raise ValueError("角色参考音频超过项目资源大小限制")
    return resolved_reference
