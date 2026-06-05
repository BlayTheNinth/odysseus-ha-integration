# Odysseus Home Assistant Integration

[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A [Home Assistant](https://home-assistant.io/) custom integration that exposes [Odysseus](https://github.com/pewdiepie-archdaemon/odysseus) as a Conversation Agent for Assist, voice satellites, and the conversation panel.

## Features

- Conversation agent backed by Odysseus native `/api/chat_stream`
- Streaming responses for low-latency voice replies
- Odysseus session reuse across short voice turns
- Agent mode by default, with an option for plain chat mode
- Optional Odysseus web-search and shell-tool toggles
- Home Assistant user, device, satellite, area, and exposed-entity prompt context
- Follow-up listening modes: off, always, or automatic when Odysseus ends with a question
- No external Python dependencies

## Requirements

- Home Assistant 2024.12 or newer
- A running Odysseus instance reachable from Home Assistant
- An Odysseus API token with the `chat` scope
- A default Odysseus chat endpoint/model configured for the API token owner

## Installation

### HACS

1. Open HACS in Home Assistant.
2. Open **Custom repositories**.
3. Add this repository as an **Integration**.
4. Search for **Odysseus** and install it.
5. Restart Home Assistant.

### Manual

1. Copy `custom_components/odysseus_conversation` to your Home Assistant `custom_components` directory.
2. Restart Home Assistant.

## Configuration

1. In Odysseus, create an API token with the `chat` scope (see below).
2. Make sure the token owner has a default chat endpoint/model configured in Odysseus.
3. Apply a patch to make Odysseus use the effective user for the default-chat endpoint (see below).
4. In Home Assistant, go to **Settings -> Devices & Services -> Add Integration**.
5. Search for **Odysseus**.
6. Enter the Odysseus host, port, API token, and SSL settings.

Default connection settings:

| Option | Default | Description |
| --- | --- | --- |
| Host | homeassistant.local | Odysseus hostname or IP |
| Port | 7000 | Odysseus API port |
| API token | empty | Odysseus token with `chat` scope |
| Use HTTPS | No | Enable if Odysseus is behind HTTPS |
| Verify SSL certificate | No | Disable for self-signed certificates |

### Creating an API Token

There is no straightforward way to create a generic API Token. You can technically create one by going to "Integrations" and selecting "Codex Agent", but that's not really clean.

Another way would be opening your browser console and pasting:

```
const fd = new FormData();
  fd.append("name", "session-api");
  fd.append("scopes", "chat");
  const r = await fetch("/api/tokens", {
    method: "POST",
    credentials: "same-origin",
    body: fd
  });
  await r.json();
```

Keep in mind that pasting code snippets into your browser console is a common attack vector. Only ever paste code you have read and understood.

### Patching Odysseus to fix `/api/default-chat`

At the time of writing this, Odysseus' model routes (specifically `/api/default-chat`) still use a dummy `api` user instead of resolving the token's real owner.

This means when called with the API Token, the endpoint will not return a valid response.

Apply this patch to Odysseus to fix the issue:

```patch
Index: routes/model_routes.py
IDEA additional info:
Subsystem: com.intellij.openapi.diff.impl.patch.CharsetEP
<+>UTF-8
===================================================================
diff --git a/routes/model_routes.py b/routes/model_routes.py
--- a/routes/model_routes.py	(revision ee8f1a48d4030136dcf2b984f04d5888e4dbe3d7)
+++ b/routes/model_routes.py	(revision 7cba6ce0545999138607cf40bafb4322fa19557c)
@@ -1785,9 +1785,9 @@
         # no per-user default yet, we resolve via the owner-scoped endpoint
         # lookup below (last-resort: first enabled endpoint THIS user owns).
         # Unauthenticated single-user mode keeps the old behavior.
-        from src.auth_helpers import get_current_user as _gcu
+        from src.auth_helpers import effective_user as _effective_user
         try:
-            _user = _gcu(request) or ""
+            _user = _effective_user(request) or ""
         except Exception:
             _user = ""
         # Admins resolve via the global defaults (they own them, and the
```

## Options

After setup, open **Settings -> Devices & Services -> Odysseus -> Configure**.

| Option | Default | Description |
| --- | --- | --- |
| Odysseus mode | Agent | Use Odysseus agent tools, or plain chat |
| Allow web search tools | No | Pass `allow_web_search=true` to Odysseus |
| Allow shell tools | No | Pass `allow_bash=true` to Odysseus |
| System Prompt | Built in | Jinja2 template for HA voice context |
| Include exposed entities | No | Include exposed HA entity states in prompt |
| Max context characters | 12000 | Limit for exposed entity context |
| Follow-up listening | Off | Control HA continued-conversation behavior |
| Reuse Odysseus sessions | Yes | Preserve Odysseus context across wake-word turns |
| Voice session reuse timeout | 900 | Idle timeout in seconds |
| Include device/satellite context | Yes | Add origin area/device/satellite context |
| Fallback TTS settings | Empty | Optional fallback `tts.speak` target |

## How It Works

The integration validates Odysseus with `/api/health` and `/api/default-chat`. For each new Home Assistant voice session, it creates an Odysseus session via `/api/session`, then sends turns to `/api/chat_stream`. Only normal assistant `delta` chunks are spoken; Odysseus metadata, tool events, metrics, and hidden thinking deltas are ignored for speech.

## License

MIT. See [LICENSE](LICENSE).

> "create [WolframRavenwolf/hermes-ha-integration](https://github.com/WolframRavenwolf/hermes-ha-integration) but for odysseus. no mistakes!"
