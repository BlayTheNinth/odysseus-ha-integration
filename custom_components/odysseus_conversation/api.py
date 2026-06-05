"""HTTP client for the Odysseus API."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, AsyncGenerator

import aiohttp

from .const import (
    API_CHAT,
    API_CHAT_STREAM,
    API_DEFAULT_CHAT,
    API_HEALTH,
    API_SESSION,
    DEFAULT_STREAM_TIMEOUT,
    DEFAULT_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)


class OdysseusApiError(Exception):
    """Base exception for Odysseus API errors."""


class OdysseusConnectionError(OdysseusApiError):
    """Cannot reach the Odysseus API."""


class OdysseusAuthError(OdysseusApiError):
    """Authentication failed."""


class OdysseusConfigError(OdysseusApiError):
    """Odysseus is reachable but not ready for chat."""


class OdysseusStreamSetupError(OdysseusApiError):
    """Streaming request was rejected before a stream was established."""


@dataclass(slots=True, frozen=True)
class OdysseusDefaultChat:
    """Odysseus default chat target."""

    endpoint_id: str
    endpoint_url: str
    model: str


@dataclass(slots=True)
class OdysseusApiResult:
    """Result wrapper for Odysseus chat calls."""

    text: str
    session_id: str | None


class OdysseusApiClient:
    """Client for the Odysseus native API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        port: int,
        api_key: str | None = None,
        use_ssl: bool = False,
        verify_ssl: bool = False,
        request_timeout: int = DEFAULT_TIMEOUT,
        stream_timeout: int = DEFAULT_STREAM_TIMEOUT,
    ) -> None:
        self._session = session
        scheme = "https" if use_ssl else "http"
        self._base_url = f"{scheme}://{host}:{port}"
        self._api_key = api_key
        self._request_timeout = max(1, int(request_timeout))
        self._stream_timeout = max(self._request_timeout, int(stream_timeout))
        # ssl=False disables certificate verification (for self-signed certs)
        self._ssl: bool | None = None if not use_ssl else (None if verify_ssl else False)
        self._last_session_id: str | None = None

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def last_session_id(self) -> str | None:
        """Most recent Odysseus session ID used by this client."""
        return self._last_session_id

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    async def async_check_connection(self) -> bool:
        """Check if the Odysseus API is reachable and auth is valid."""
        try:
            async with self._session.get(
                f"{self._base_url}{API_HEALTH}",
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=10),
                ssl=self._ssl,
            ) as resp:
                if resp.status == 401:
                    raise OdysseusAuthError("Invalid API token")
                if resp.status == 403:
                    raise OdysseusAuthError("Access denied")
                if resp.status >= 400:
                    raise OdysseusConnectionError(
                        f"Health check failed with HTTP {resp.status}"
                    )
            await self.async_get_default_chat()
            return True
        except (OdysseusAuthError, OdysseusConfigError, OdysseusConnectionError):
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise OdysseusConnectionError(
                f"Cannot connect to Odysseus at {self._base_url}: {err}"
            ) from err

    async def async_get_default_chat(self) -> OdysseusDefaultChat:
        """Fetch the caller's default Odysseus chat endpoint and model."""
        try:
            async with self._session.get(
                f"{self._base_url}{API_DEFAULT_CHAT}",
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=10),
                ssl=self._ssl,
            ) as resp:
                if resp.status == 401:
                    raise OdysseusAuthError("Invalid API token")
                if resp.status == 403:
                    raise OdysseusAuthError("Access denied")
                if resp.status >= 400:
                    body = await resp.text()
                    raise OdysseusConfigError(
                        f"Default chat lookup failed with HTTP {resp.status}: {body[:500]}"
                    )
                data = await resp.json()
        except (OdysseusApiError, asyncio.TimeoutError):
            raise
        except aiohttp.ClientError as err:
            raise OdysseusConnectionError(
                f"Cannot fetch Odysseus default chat: {err}"
            ) from err

        endpoint_id = str(data.get("endpoint_id") or "").strip()
        endpoint_url = str(data.get("endpoint_url") or "").strip()
        model = str(data.get("model") or "").strip()
        if not endpoint_id or not endpoint_url or not model:
            raise OdysseusConfigError(
                "Odysseus has no default chat endpoint/model for this API token owner"
            )
        return OdysseusDefaultChat(
            endpoint_id=endpoint_id,
            endpoint_url=endpoint_url,
            model=model,
        )

    async def async_create_session(self) -> str:
        """Create an Odysseus chat session using the caller's default chat target."""
        default_chat = await self.async_get_default_chat()
        try:
            async with self._session.post(
                f"{self._base_url}{API_SESSION}",
                headers=self._headers(),
                data={
                    "name": "Home Assistant Voice",
                    "endpoint_id": default_chat.endpoint_id,
                    "model": default_chat.model,
                    "skip_validation": "true",
                },
                timeout=aiohttp.ClientTimeout(total=10),
                ssl=self._ssl,
            ) as resp:
                if resp.status == 401:
                    raise OdysseusAuthError("Invalid API token")
                if resp.status == 403:
                    raise OdysseusAuthError("Access denied")
                if resp.status >= 400:
                    body = await resp.text()
                    raise OdysseusApiError(
                        f"Session creation failed with HTTP {resp.status}: {body[:500]}"
                    )
                data = await resp.json()
        except OdysseusApiError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise OdysseusConnectionError(
                f"Cannot create Odysseus session: {err}"
            ) from err

        session_id = str(data.get("id") or "").strip()
        if not session_id:
            raise OdysseusApiError("Odysseus did not return a session ID")
        self._last_session_id = session_id
        return session_id

    async def _ensure_session(self, session_id: str | None = None) -> str:
        if session_id:
            self._last_session_id = session_id
            return session_id
        return await self.async_create_session()

    async def async_send_message(
        self,
        messages: list[dict[str, str]],
        session_id: str | None = None,
        *,
        mode: str = "agent",
        allow_web_search: bool = False,
        allow_bash: bool = False,
    ) -> OdysseusApiResult:
        """Send a non-streaming Odysseus chat request."""
        resolved_session_id = await self._ensure_session(session_id)
        message = _last_user_message(messages)
        if not message:
            return OdysseusApiResult(text="", session_id=resolved_session_id)

        payload = {
            "message": _build_odysseus_message(messages),
            "session": resolved_session_id,
            "use_web": bool(allow_web_search),
        }

        try:
            async with self._session.post(
                f"{self._base_url}{API_CHAT}",
                headers=self._headers(),
                json=payload,
                timeout=aiohttp.ClientTimeout(total=self._request_timeout),
                ssl=self._ssl,
            ) as resp:
                if resp.status == 401:
                    raise OdysseusAuthError("Invalid API token")
                if resp.status == 403:
                    raise OdysseusAuthError("Access denied")
                if resp.status >= 400:
                    body = await resp.text()
                    raise OdysseusApiError(
                        f"API error {resp.status}: {body[:500]}"
                    )
                data = await resp.json()
                return OdysseusApiResult(
                    text=str(data.get("response") or ""),
                    session_id=resolved_session_id,
                )
        except OdysseusApiError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise OdysseusConnectionError(f"Connection error: {err}") from err

    async def async_stream_message(
        self,
        messages: list[dict[str, str]],
        session_id: str | None = None,
        *,
        mode: str = "agent",
        allow_web_search: bool = False,
        allow_bash: bool = False,
    ) -> AsyncGenerator[str, None]:
        """Send a streaming Odysseus chat request. Yields speakable deltas."""
        resolved_session_id = await self._ensure_session(session_id)
        message = _last_user_message(messages)
        if not message:
            return

        form_data = {
            "message": _build_odysseus_message(messages),
            "session": resolved_session_id,
            "mode": mode,
            "allow_web_search": "true" if allow_web_search else "false",
            "allow_bash": "true" if allow_bash else "false",
        }

        try:
            async with self._session.post(
                f"{self._base_url}{API_CHAT_STREAM}",
                headers=self._headers(),
                data=form_data,
                timeout=aiohttp.ClientTimeout(
                    total=self._stream_timeout,
                    sock_read=self._request_timeout,
                ),
                ssl=self._ssl,
            ) as resp:
                if resp.status == 401:
                    raise OdysseusAuthError("Invalid API token")
                if resp.status == 403:
                    raise OdysseusAuthError("Access denied")
                if resp.status >= 400:
                    body = await resp.text()
                    raise OdysseusStreamSetupError(
                        f"API error {resp.status}: {body[:500]}"
                    )

                self._last_session_id = resolved_session_id

                buffer = ""
                event_name = "message"
                async for chunk in resp.content.iter_any():
                    buffer += chunk.decode("utf-8", errors="replace")
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        line = line.rstrip("\r")

                        if not line:
                            event_name = "message"
                            continue
                        line = line.strip()
                        if line.startswith(":"):
                            continue
                        if line.startswith("event:"):
                            event_name = line[6:].strip() or "message"
                            continue
                        if line == "data: [DONE]":
                            return
                        if event_name != "message" or not line.startswith("data: "):
                            continue

                        try:
                            data = json.loads(line[6:])
                        except json.JSONDecodeError:
                            continue
                        delta = data.get("delta")
                        if data.get("thinking") is True:
                            continue
                        if isinstance(delta, str) and delta:
                            yield delta
        except OdysseusApiError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise OdysseusConnectionError(
                f"Stream connection error: {err}"
            ) from err


def _last_user_message(messages: list[dict[str, str]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            content = message.get("content")
            return content if isinstance(content, str) else ""
    return ""


def _build_odysseus_message(messages: list[dict[str, str]]) -> str:
    """Fold HA-only system prompt context into the user turn Odysseus receives."""
    user_text = _last_user_message(messages)
    system_parts = [
        str(message.get("content") or "")
        for message in messages
        if message.get("role") == "system" and message.get("content")
    ]
    last_index = len(messages) - 1
    transcript_parts = [
        f"{str(message.get('role') or 'message').title()}: {message.get('content')}"
        for index, message in enumerate(messages)
        if index != last_index
        and message.get("role") in ("user", "assistant")
        and message.get("content")
    ]
    parts: list[str] = []
    if system_parts:
        parts.extend(["Home Assistant context:", *system_parts])
    if transcript_parts:
        parts.extend(["Previous conversation:", *transcript_parts])
    parts.extend(["User request:", user_text])
    return "\n\n".join(parts)
