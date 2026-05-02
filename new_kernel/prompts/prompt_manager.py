"""Local YAML prompt manager for the new kernel.

The prompts module is intentionally a leaf dependency: it reads local files and returns
template strings. It does not know about agents, LLM clients, sessions, events, or API
contracts.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

try:  # PyYAML is preferred when available, but the module keeps a local fallback.
    import yaml as _pyyaml
except ModuleNotFoundError:  # pragma: no cover - exercised only in minimal installs.
    _pyyaml = None


class PromptLoadError(ValueError):
    """Raised when a local prompt file cannot be parsed as a mapping."""


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
    def _language_load_order(cls, language: str | None) -> list[str]:
        normalized = cls._normalize_language(language)
        order = [cls.DEFAULT_FALLBACK_LANGUAGE]
        if normalized != cls.DEFAULT_FALLBACK_LANGUAGE:
            order.append(cls.DEFAULT_LANGUAGE)
        order.append(normalized)

        languages: list[str] = []
        for item in order:
            if item and item not in languages:
                languages.append(item)
        return languages

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

    @staticmethod
    def _parse_scalar(value: str) -> str:
        stripped = value.strip()
        if stripped in {'""', "''"}:
            return ""
        if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in {"'", '"'}:
            return stripped[1:-1]
        return stripped

    @classmethod
    def _load_minimal_yaml(cls, text: str, file_path: Path) -> dict[str, Any]:
        """Parse the small YAML subset used by bundled prompt files.

        This fallback supports top-level string keys, one-level nested mappings, and
        literal block scalars. Full YAML remains delegated to PyYAML when installed.
        """

        result: dict[str, Any] = {}
        lines = text.splitlines()
        index = 0

        while index < len(lines):
            line = lines[index]
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                index += 1
                continue
            if line[:1].isspace():
                raise PromptLoadError(f"Unexpected indentation in {file_path}: {line!r}")

            key, separator, raw_value = line.partition(":")
            if not separator or not key.strip():
                raise PromptLoadError(f"Invalid mapping line in {file_path}: {line!r}")

            key = key.strip()
            value = raw_value.strip()
            if value in {"|", "|-", "|+"}:
                block_lines, index = cls._consume_block(lines, index + 1)
                result[key] = "\n".join(block_lines).rstrip("\n")
                continue
            if value == "":
                nested, index = cls._consume_nested_mapping(lines, index + 1, file_path)
                result[key] = nested
                continue

            result[key] = cls._parse_scalar(value)
            index += 1

        return result

    @classmethod
    def _consume_block(cls, lines: list[str], index: int) -> tuple[list[str], int]:
        block_lines: list[str] = []
        block_indent: int | None = None

        while index < len(lines):
            line = lines[index]
            if not line.strip():
                block_lines.append("")
                index += 1
                continue

            indent = len(line) - len(line.lstrip(" "))
            if indent == 0:
                break
            if block_indent is None:
                block_indent = indent
            block_lines.append(line[min(indent, block_indent) :])
            index += 1

        return block_lines, index

    @classmethod
    def _consume_nested_mapping(
        cls,
        lines: list[str],
        index: int,
        file_path: Path,
    ) -> tuple[dict[str, str], int]:
        nested: dict[str, str] = {}

        while index < len(lines):
            line = lines[index]
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                index += 1
                continue

            indent = len(line) - len(line.lstrip(" "))
            if indent == 0:
                break

            key, separator, raw_value = stripped.partition(":")
            if not separator or not key.strip():
                raise PromptLoadError(f"Invalid nested mapping line in {file_path}: {line!r}")
            nested[key.strip()] = cls._parse_scalar(raw_value)
            index += 1

        return nested, index

    def _load_yaml_file(self, file_path: Path) -> dict[str, Any]:
        if not file_path.exists() or not file_path.is_file():
            return {}

        text = file_path.read_text(encoding="utf-8")
        if _pyyaml is None:
            return self._load_minimal_yaml(text, file_path)

        payload = _pyyaml.safe_load(text)
        if isinstance(payload, dict):
            return payload
        if payload is None:
            return {}
        raise PromptLoadError(f"Prompt file must contain a mapping: {file_path}")

    def _load_prompts(self, agent_name: str, language: str) -> dict[str, Any]:
        normalized_agent = Path(agent_name).name
        normalized_agent = normalized_agent[:-5] if normalized_agent.endswith(".yaml") else normalized_agent

        cache_key = (normalized_agent, language)
        if cache_key in self._cache:
            return self._cache[cache_key]

        prompts: dict[str, Any] = {}
        for lang in self._language_load_order(language):
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


__all__ = ["PromptLoadError", "PromptManager"]
