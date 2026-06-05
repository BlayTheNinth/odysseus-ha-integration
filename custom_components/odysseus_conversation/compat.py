"""Compatibility helpers for Odysseus config entries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry

from .const import (
    CONF_API_KEY,
    CONF_CONTINUED_CONVERSATION_MODE,
    CONF_ENABLE_CONTINUED_CONVERSATION,
    CONF_HOST,
    CONF_PORT,
    CONF_USE_SSL,
    CONF_VERIFY_SSL,
    DEFAULT_CONTINUED_CONVERSATION_MODE,
    DEFAULT_HOST,
    DEFAULT_ENABLE_CONTINUED_CONVERSATION,
    DEFAULT_PORT,
    FOLLOW_UP_MODE_ALWAYS,
    FOLLOW_UP_MODES,
)


@dataclass(slots=True, frozen=True)
class OdysseusConnectionConfig:
    """Resolved connection config for an Odysseus API entry."""

    host: str
    port: int
    api_key: str | None
    use_ssl: bool
    verify_ssl: bool


def entry_value(
    entry: ConfigEntry,
    key: str,
    default: Any = None,
    *,
    legacy_keys: tuple[str, ...] = (),
    prefer_options: bool = True,
) -> Any:
    """Read a value from options/data with optional legacy-key fallback."""
    sources = (entry.options, entry.data) if prefer_options else (entry.data, entry.options)

    for source in sources:
        if key in source and source[key] is not None:
            return source[key]
        for legacy_key in legacy_keys:
            if legacy_key in source and source[legacy_key] is not None:
                return source[legacy_key]

    return default


def resolve_connection_config(entry: ConfigEntry) -> OdysseusConnectionConfig:
    """Resolve connection details from the config entry."""
    host = entry_value(entry, CONF_HOST, prefer_options=False)
    port = entry_value(entry, CONF_PORT, prefer_options=False)
    api_key = entry_value(entry, CONF_API_KEY, prefer_options=False) or None
    use_ssl = entry_value(entry, CONF_USE_SSL, prefer_options=False)
    verify_ssl = entry_value(entry, CONF_VERIFY_SSL, prefer_options=False)

    if host and port is not None:
        return OdysseusConnectionConfig(
            host=str(host),
            port=_coerce_int(port, DEFAULT_PORT),
            api_key=api_key,
            use_ssl=False if use_ssl is None else bool(use_ssl),
            verify_ssl=False if verify_ssl is None else bool(verify_ssl),
        )

    return OdysseusConnectionConfig(
        host=DEFAULT_HOST,
        port=DEFAULT_PORT,
        api_key=api_key,
        use_ssl=False if use_ssl is None else bool(use_ssl),
        verify_ssl=False if verify_ssl is None else bool(verify_ssl),
    )


def resolve_continued_conversation_mode(entry: ConfigEntry) -> str:
    """Resolve follow-up listening mode with legacy boolean compatibility."""
    mode = entry_value(entry, CONF_CONTINUED_CONVERSATION_MODE)
    if mode in FOLLOW_UP_MODES:
        return str(mode)

    legacy_enabled = entry_value(
        entry,
        CONF_ENABLE_CONTINUED_CONVERSATION,
        DEFAULT_ENABLE_CONTINUED_CONVERSATION,
    )
    if bool(legacy_enabled):
        return FOLLOW_UP_MODE_ALWAYS

    return DEFAULT_CONTINUED_CONVERSATION_MODE


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
