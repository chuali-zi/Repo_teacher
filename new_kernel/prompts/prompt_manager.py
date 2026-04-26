"""Prompt manager for the new kernel.

Responsibilities:
1. Load prompt files from ``prompts/<lang>/*.yaml``.
2. Cache parsed prompt mappings in-memory.
3. Provide ``get(agent_name, section, field=None, fallback="")`` lookup.

Constraints:
- Local YAML only.
- No global singleton state.
- No network, no remote stores, no hot reload, no A/B routing.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml


class PromptManager:
    """Local YAML prompt loader with small in-memory cache."""

    DEFAULT_LANGUAGE = "zh"
    DEFAULT_FALLBACK_LANGUAGE = "en"
    DEFAULT_FILE = "default.yaml"

    def __init__(self, prompts_root: str | Path | None = None, default_language: str = DEFAULT_LANGUAGE):
        root = Path(prompts_root) if prompts_root is not None else Path(__file__).resolve().parent
        self.prompts_root = root
        self.default_language = self._normalize_language(default_language)
        # cache key: (agent_name, language)
        self._cache: dict[tuple[str, str], dict[str, Any]] = {}

    @classmethod
    def _normalize_language(cls, language: str | None) -> str:
        if not language:
            return cls.DEFAULT_LANGUAGE
        normalized = language.strip().lower().replace("_", "-")
        if normalized.startswith("zh-"):
            return "zh"
        if normalized.startswith("en-"):
            return "en"
        return normalized

    @classmethod
    def _fallback_languages(cls, language: str | None) -> list[str]:
        normalized = cls._normalize_language(language)
        chain = [normalized, cls.DEFAULT_LANGUAGE, cls.DEFAULT_FALLBACK_LANGUAGE]
        deduped: list[str] = []
        for lang in chain:
            if lang and lang not in deduped:
                deduped.append(lang)
        return deduped

    @staticmethod
    def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        merged = dict(base)
        for key, value in override.items():
            current = merged.get(key)
            if isinstance(current, Mapping) and isinstance(value, Mapping):
                merged[key] = PromptManager._deep_merge(dict(current), dict(value))
            else:
                merged[key] = value
        return merged

    def _load_yaml_file(self, file_path: Path) -> dict[str, Any]:
        if not file_path.exists() or not file_path.is_file():
            return {}
        payload = yaml.safe_load(file_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
        return {}

    def _load_prompts(self, agent_name: str, language: str) -> dict[str, Any]:
        normalized_agent = Path(agent_name).name
        normalized_agent = normalized_agent[:-5] if normalized_agent.endswith(".yaml") else normalized_agent

        cache_key = (normalized_agent, language)
        if cache_key in self._cache:
            return self._cache[cache_key]

        prompts: dict[str, Any] = {}
        for lang in self._fallback_languages(language):
            lang_dir = self.prompts_root / lang
            # default.yaml first, then agent-specific file override defaults.
            for filename in (self.DEFAULT_FILE, f"{normalized_agent}.yaml"):
                loaded = self._load_yaml_file(lang_dir / filename)
                if loaded:
                    prompts = self._deep_merge(prompts, loaded)

        self._cache[cache_key] = prompts
        return prompts

    @staticmethod
    def _as_text(value: Any, fallback: str) -> str:
        if isinstance(value, str):
            return value
        return fallback

    def get(
        self,
        agent_name: str,
        section: str,
        field: str | None = None,
        fallback: str = "",
    ) -> str:
        """Get prompt by section/field from cached YAML config.

        Supports:
        - get(agent, section) => value
        - get(agent, section, field) => nested value
        - fallback for misses
        """
        prompts = self._load_prompts(agent_name, self.default_language)
        section_value = prompts.get(section)
        if field is None:
            return self._as_text(section_value, fallback)

        if isinstance(section_value, Mapping):
            return self._as_text(section_value.get(field), fallback)
        return fallback

    def clear_cache(self) -> None:
        """Clear in-memory prompt cache."""
        self._cache.clear()


__all__ = ["PromptManager"]
