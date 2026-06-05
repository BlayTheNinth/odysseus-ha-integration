from __future__ import annotations

import json
import unittest

from tests.test_support import FakeClientTimeout
from custom_components.odysseus_conversation.api import (
    OdysseusApiClient,
    OdysseusConfigError,
    OdysseusStreamSetupError,
)


class FakeResponse:
    def __init__(self, *, status=200, headers=None, json_data=None, text_data="", chunks=None):
        self.status = status
        self.headers = headers or {}
        self._json_data = json_data or {}
        self._text_data = text_data
        self.content = self
        self._chunks = [chunk.encode("utf-8") for chunk in (chunks or [])]

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self):
        return self._json_data

    async def text(self):
        return self._text_data

    async def iter_any(self):
        for chunk in self._chunks:
            yield chunk


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, *, headers=None, json=None, data=None, timeout=None, ssl=None):
        self.calls.append(
            {
                "method": "POST",
                "url": url,
                "headers": headers,
                "json": json,
                "data": data,
                "timeout": timeout,
                "ssl": ssl,
            }
        )
        return self.responses.pop(0)

    def get(self, url, *, headers=None, timeout=None, ssl=None):
        self.calls.append(
            {
                "method": "GET",
                "url": url,
                "headers": headers,
                "timeout": timeout,
                "ssl": ssl,
            }
        )
        return self.responses.pop(0)


class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_check_connection_requires_default_chat(self):
        session = FakeSession(
            [
                FakeResponse(json_data={"status": "healthy"}),
                FakeResponse(json_data={"endpoint_id": "", "endpoint_url": "", "model": ""}),
            ]
        )
        client = OdysseusApiClient(
            session=session,
            host="odysseus.local",
            port=7000,
            api_key="ody_secret",
        )

        with self.assertRaises(OdysseusConfigError):
            await client.async_check_connection()

        self.assertEqual(session.calls[0]["url"], "http://odysseus.local:7000/api/health")
        self.assertEqual(session.calls[1]["url"], "http://odysseus.local:7000/api/default-chat")
        self.assertEqual(session.calls[0]["headers"]["Authorization"], "Bearer ody_secret")

    async def test_streaming_creates_session_from_default_chat(self):
        chunks = [
            "data: " + json.dumps({"type": "model_info", "model": "ignored"}) + "\n",
            "data: " + json.dumps({"delta": "Blue"}) + "\n",
            "data: " + json.dumps({"delta": " hidden", "thinking": True}) + "\n",
            "data: " + json.dumps({"delta": " sky"}) + "\n",
            "data: [DONE]\n",
        ]
        session = FakeSession(
            [
                FakeResponse(
                    json_data={
                        "endpoint_id": "ep-1",
                        "endpoint_url": "http://llm/v1/chat/completions",
                        "model": "qwen",
                    }
                ),
                FakeResponse(json_data={"id": "sess-new"}),
                FakeResponse(chunks=chunks),
            ]
        )
        client = OdysseusApiClient(
            session=session,
            host="odysseus.local",
            port=7000,
            request_timeout=12,
            stream_timeout=30,
        )

        parts = []
        async for part in client.async_stream_message(
            [{"role": "system", "content": "be brief"}, {"role": "user", "content": "hi"}],
            mode="agent",
            allow_web_search=True,
            allow_bash=False,
        ):
            parts.append(part)

        self.assertEqual("".join(parts), "Blue sky")
        self.assertEqual(client.last_session_id, "sess-new")
        self.assertEqual(session.calls[1]["url"], "http://odysseus.local:7000/api/session")
        self.assertEqual(session.calls[1]["data"]["endpoint_id"], "ep-1")
        self.assertEqual(session.calls[1]["data"]["model"], "qwen")
        self.assertEqual(session.calls[1]["data"]["skip_validation"], "true")
        self.assertEqual(session.calls[2]["url"], "http://odysseus.local:7000/api/chat_stream")
        self.assertEqual(session.calls[2]["data"]["session"], "sess-new")
        self.assertEqual(session.calls[2]["data"]["mode"], "agent")
        self.assertEqual(session.calls[2]["data"]["allow_web_search"], "true")
        self.assertIn("Home Assistant context:", session.calls[2]["data"]["message"])
        self.assertIsInstance(session.calls[2]["timeout"], FakeClientTimeout)
        self.assertEqual(session.calls[2]["timeout"].total, 30)
        self.assertEqual(session.calls[2]["timeout"].sock_read, 12)

    async def test_streaming_reuses_existing_session(self):
        session = FakeSession(
            [
                FakeResponse(
                    chunks=[
                        "data: " + json.dumps({"delta": "Done"}) + "\n",
                        "data: [DONE]\n",
                    ]
                )
            ]
        )
        client = OdysseusApiClient(session=session, host="odysseus.local", port=7000)

        parts = []
        async for part in client.async_stream_message(
            [{"role": "user", "content": "hi"}], session_id="sess-existing"
        ):
            parts.append(part)

        self.assertEqual(parts, ["Done"])
        self.assertEqual(client.last_session_id, "sess-existing")
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(session.calls[0]["data"]["session"], "sess-existing")

    async def test_non_streaming_extracts_response(self):
        session = FakeSession([FakeResponse(json_data={"response": "hello"})])
        client = OdysseusApiClient(session=session, host="odysseus.local", port=7000)

        result = await client.async_send_message(
            [{"role": "user", "content": "hi"}], session_id="sess-1"
        )

        self.assertEqual(result.text, "hello")
        self.assertEqual(result.session_id, "sess-1")
        self.assertEqual(session.calls[0]["url"], "http://odysseus.local:7000/api/chat")
        self.assertEqual(session.calls[0]["json"]["session"], "sess-1")

    async def test_streaming_rejected_status_raises_setup_error(self):
        session = FakeSession([FakeResponse(status=400, text_data="stream unsupported")])
        client = OdysseusApiClient(session=session, host="odysseus.local", port=7000)

        with self.assertRaises(OdysseusStreamSetupError):
            async for _part in client.async_stream_message(
                [{"role": "user", "content": "hi"}], session_id="sess-1"
            ):
                pass


if __name__ == "__main__":
    unittest.main()
