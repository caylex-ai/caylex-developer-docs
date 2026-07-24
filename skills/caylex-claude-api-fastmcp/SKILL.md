---
name: integrate-caylex-fastmcp-claude-api
description: Adds a customer-managed FastMCP client to a Python agent built on Anthropic's Claude Messages API so it can discover and call Caylex Navigator tools without Anthropic's hosted MCP connector. Use when integrating Caylex with a custom Claude API harness where the application must control MCP tool discovery instead of relying on Anthropic's cached catalog.
disable-model-invocation: true
---

# Integrate Caylex with the Claude API using FastMCP

Modify the application's existing Claude Messages API harness to own its MCP connection, tool discovery, and tool execution. Do not migrate the application to the Claude Agent SDK.

## Non-negotiable architecture

- Use the regular `anthropic` Python SDK and Messages API.
- Use `fastmcp-slim[client]` as the MCP client.
- Connect directly to `https://navigator.caylex.ai/mcp` over Streamable HTTP.
- Do **not** pass `mcp_servers`, `mcp_toolset`, or an Anthropic MCP beta header to `messages.create()`.
- Do **not** use Anthropic's hosted MCP connector. Anthropic may cache its model-facing MCP catalog, while Caylex Navigator tool descriptions contain live, user-specific context.
- Call FastMCP `list_tools()` when the chat's Caylex connection is initialized, convert the result to Anthropic tool definitions, and reuse that stable catalog across turns.
- If the application already detects downstream authentication-status changes, it may refresh the catalog before the next turn. This is optional because runtime authentication and tool execution already use current credentials.
- Execute Claude's `tool_use` blocks with FastMCP `call_tool()` and return ordinary Anthropic `tool_result` blocks.

## Understand the Caylex Navigator

The Navigator exposes a compact, configurable set of meta-tools rather than every downstream tool. Their descriptions teach Claude how to discover schemas, execute downstream tools, use optional context or skills, and handle authentication.

Treat the discovered MCP catalog as opaque:

- Do not require, filter, or branch on specific Caylex tool names.
- Do not assume that any optional meta-tool is enabled.
- Pass every discovered tool to Claude and dispatch any returned `tool_use` by its discovered name.
- Let the tool descriptions instruct Claude on the correct workflow.

Tool descriptions are dynamic. The initial `tools/list` response can include the Navigator's custom instructions, available MCP servers for the current user, and available skills. The application must own that initial discovery instead of relying on Anthropic's hosted catalog. Once discovered, keep the catalog stable for the chat. Do not bypass the Navigator by inventing downstream tools as top-level Claude tools.

## Inspect the existing harness first

Before editing:

1. Find the code that creates the Anthropic client and calls `messages.create()`.
2. Find how conversation history, user identity, chat/session identity, streaming, retries, and tool approvals are represented.
3. Reuse the application's existing abstractions. Do not replace the whole harness if a narrow adapter is sufficient.
4. Determine whether the harness is async. Prefer `AsyncAnthropic` and FastMCP's async client. If the application is synchronous, isolate the async MCP loop at an existing async boundary rather than repeatedly calling `asyncio.run()`.
5. Preserve all non-Caylex tools. Merge the discovered Caylex definitions with existing Anthropic tool definitions and dispatch calls by tool name.

## Install dependencies

Use the repository's package manager to add:

```text
anthropic
fastmcp-slim[client]
```

The client-only package still uses this import:

```python
from fastmcp import Client
```

Do not install the full `fastmcp` package unless the application also defines or runs FastMCP servers.

## Authentication and session identity

Build one Caylex bearer token per user chat. It is base64url-encoded JSON containing the Navigator API key, end-user email, and a stable chat UUID.

```python
import base64
import json


def build_caylex_bearer_token(
    api_key: str,
    user_email: str,
    session_id: str,
) -> str:
    payload = {
        "api_key": api_key,
        "user_email": user_email,
        "session_id": session_id,
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload).encode("utf-8")
    ).decode("ascii")
    return encoded.rstrip("=")
```

Requirements:

- Read the Navigator API key from server-side secrets, never from browser code.
- Use the authenticated end user's exact email. It must match the email used on Caylex Auth Links.
- Generate `session_id` once with `str(uuid.uuid4())` when a chat starts and reuse it for every MCP request in that chat.
- If the application's chat table already uses a UUID primary key, prefer that UUID as the Caylex `session_id`. This avoids maintaining a second identifier and naturally keeps Caylex history aligned with the application's chat.
- Never share an MCP client or bearer token across users.
- The packed token is encoded, not encrypted or signed. Treat it as an API key.

## Create the FastMCP connection

```python
from fastmcp import Client as FastMCPClient
from fastmcp.client.transports import StreamableHttpTransport


def create_caylex_client(token: str) -> FastMCPClient:
    transport = StreamableHttpTransport(
        "https://navigator.caylex.ai/mcp",
        headers={"Authorization": f"Bearer {token}"},
    )
    return FastMCPClient(transport)
```

All FastMCP operations must run inside `async with client:`. Prefer one connection for the active chat or request lifecycle. Always close it on cancellation and errors.

### Include the server description in the system prompt

`list_tools()` returns only tools. The Navigator's server-level description arrives through the MCP initialize handshake, which FastMCP performs automatically when the connection opens. Read it from `initialize_result` and append it to the system prompt:

```python
async with create_caylex_client(token) as mcp:
    server_instructions = mcp.initialize_result.instructions or ""
    system_prompt = f"{BASE_SYSTEM_PROMPT}\n\n{server_instructions}".strip()
```

Like the tool catalog, capture this once per chat and keep the system prompt byte-stable across turns so it remains prompt-cache eligible.

## Convert discovered MCP tools for Claude

FastMCP returns MCP tool objects; Claude expects `name`, `description`, and `input_schema`.

```python
async def load_claude_tools(mcp: FastMCPClient) -> list[dict]:
    mcp_tools = await mcp.list_tools()
    return [
        {
            "name": tool.name,
            "description": tool.description or "",
            "input_schema": tool.inputSchema,
        }
        for tool in mcp_tools
    ]
```

Invoke this when the chat's Caylex connection is initialized. Store the resulting JSON-serializable definitions with the chat or in chat-scoped state and reuse them across turns, preserving the server's ordering. Never share them across users or unrelated chats.

Keeping the catalog stable avoids an MCP round trip before every agent turn and preserves Anthropic prompt-cache eligibility. Tools render at the start of Claude's prompt prefix, so any changed description, schema, or ordering invalidates the cache from the tools section onward. Reusing the stored list guarantees a byte-identical `tools` array on every turn.

Run a new `tools/list` request whenever a new chat begins. If the application already has a mechanism that detects when a user's authentication status changes for a connector, it may also use that event to refresh the catalog before the next user turn. Be aware that changed tool descriptions will invalidate Anthropic's cached prompt prefix and require a cache rebuild.

## Convert MCP results to Anthropic tool results

Use structured content when available and preserve errors. Fall back to serializing standard MCP content blocks.

```python
import json

from mcp.types import TextContent


def mcp_result_to_text(result) -> str:
    if result.structured_content is not None:
        return json.dumps(result.structured_content, default=str)

    parts: list[str] = []
    for block in result.content:
        if isinstance(block, TextContent):
            parts.append(block.text)
        else:
            parts.append(json.dumps(block.model_dump(mode="json"), default=str))
    return "\n".join(parts)
```

Call tools with `raise_on_error=False` so MCP failures can be returned to Claude as `is_error: true` rather than crashing the whole turn.

## Implement the Messages API tool loop

Adapt this reference implementation to the application's existing persistence, streaming, retry, and approval layers:

```python
from anthropic import AsyncAnthropic
from fastmcp import Client as FastMCPClient


async def run_claude_turn(
    *,
    claude: AsyncAnthropic,
    mcp: FastMCPClient,
    caylex_tools: list[dict],
    messages: list[dict],
    system_prompt: str,
    model: str,
) -> str:
    while True:
        response = await claude.messages.create(
            model=model,
            max_tokens=2048,
            system=system_prompt,
            messages=messages,
            tools=caylex_tools,
        )
        messages.append({"role": "assistant", "content": response.content})

        tool_uses = [
            block for block in response.content if block.type == "tool_use"
        ]
        if not tool_uses:
            if response.stop_reason != "end_turn":
                raise RuntimeError(
                    f"Claude stopped without a final answer: {response.stop_reason}"
                )
            return "\n".join(
                block.text for block in response.content if block.type == "text"
            )

        tool_results = []
        for tool_use in tool_uses:
            result = await mcp.call_tool(
                tool_use.name,
                dict(tool_use.input),
                raise_on_error=False,
            )
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": mcp_result_to_text(result),
                    "is_error": bool(result.is_error),
                }
            )

        # Return exactly one result for every tool_use. All results belong in
        # the immediately following user message.
        messages.append({"role": "user", "content": tool_results})
```

Integrate it at the chat boundary:

```python
import os

from anthropic import AsyncAnthropic


async def handle_chat_turn(user_email: str, messages: list[dict]) -> str:
    chat = load_chat()  # Prefer chat.id when it is already a UUID.
    session_id = str(chat.id)
    token = build_caylex_bearer_token(
        api_key=os.environ["CAYLEX_API_KEY"],
        user_email=user_email,
        session_id=session_id,
    )
    claude = AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    base_prompt = (
        "You are a helpful assistant. Use the available Caylex tools "
        "when needed. Follow the instructions in their descriptions."
    )

    async with create_caylex_client(token) as mcp:
        caylex_tools = chat.caylex_tools
        if caylex_tools is None:
            caylex_tools = await load_claude_tools(mcp)
            save_caylex_tools(
                chat_id=chat.id,
                tools=caylex_tools,
            )

        server_instructions = mcp.initialize_result.instructions or ""
        system_prompt = f"{base_prompt}\n\n{server_instructions}".strip()

        return await run_claude_turn(
            claude=claude,
            mcp=mcp,
            caylex_tools=caylex_tools,
            messages=messages,
            system_prompt=system_prompt,
            model="claude-opus-4-8",
        )
```

`messages` must contain only `user` and `assistant` roles. Send the system prompt through the top-level `system` parameter.

## Preserve existing tools and approvals

If the harness already has local tools:

1. Merge local definitions with the discovered Caylex definitions.
2. Fail startup or the turn on duplicate tool names; never dispatch ambiguously.
3. Route Caylex names to `mcp.call_tool()` and local names to their existing handlers.
4. Apply existing approval policy before executing sensitive Caylex calls if the product requires human approval.
5. If Claude emits several independent tool calls, return one `tool_result` per `tool_use` in the same next user message. They may be executed sequentially or concurrently according to the harness's policy.

## Handle authentication changes

Refreshing after authentication is optional. Even without a refresh, the newly authenticated server is available at runtime. If exposed by the Navigator, the agent can call `get_authentication_status_and_link` again to retrieve current authentication statuses in context.

If the customer application already detects connector authentication changes through its UI or backend, it may use that event to run `tools/list` before the next user turn so the Navigator's descriptive server list is updated. Do not add name-based detection to the generic MCP adapter. A changed tools array will invalidate Anthropic's prompt cache from the tools prefix onward.

## Verification checklist

Add or update tests for the harness:

- `list_tools()` runs once when a chat's catalog is initialized and is not repeated on ordinary turns.
- A tool call to a server the user authenticated into mid-chat succeeds without a catalog refresh.
- The stored catalog and system prompt remain byte-stable across ordinary turns.
- MCP `inputSchema` becomes Anthropic `input_schema` without alteration.
- A Claude `tool_use` calls the matching FastMCP tool with the same JSON input.
- Dispatch works for arbitrary discovered tool names and does not require optional Caylex tools.
- Every tool call receives a matching `tool_result` with the correct `tool_use_id`.
- Multiple tool calls in one assistant response all receive results.
- MCP errors become `is_error: true` results and do not terminate the loop.
- The same chat UUID is reused across turns; different chats and users are isolated.
- Existing local tools still dispatch correctly and duplicate names are rejected.
- No Anthropic request contains `mcp_servers`, `mcp_toolset`, or hosted-connector beta configuration.
- The FastMCP connection closes on success, error, timeout, and cancellation.

Run the repository's formatter, linter, type checker, and focused tests after implementation.

## Common mistakes

- Listing tools globally at process startup instead of once per user chat.
- Caching Caylex tool definitions across users or chats.
- Refreshing tools before every turn without accepting the latency and prompt-cache tradeoff.
- Requiring a catalog refresh before newly authenticated servers can be used.
- Hard-coding optional Caylex meta-tool names into dispatch or availability logic.
- Using Anthropic's hosted MCP connector because its example is shorter.
- Installing or migrating to the Claude Agent SDK.
- Reusing one user's bearer token for another user.
- Creating a new chat UUID for every tool call.
- Returning only the first tool call when Claude requests several.
- Omitting the assistant `tool_use` message from history before appending results.
- Sending `tool_result` blocks in a separate or delayed message.
- Treating the base64url bearer token as encrypted.

## Further reading

- [Caylex: Claude API integration](https://docs.caylex.ai/integration/claude-api)
- [Caylex: Connecting Your Agent](https://docs.caylex.ai/integration/connecting)
- [FastMCP Client](https://gofastmcp.com/clients/client)
- [FastMCP client-only package](https://gofastmcp.com/clients/client-only-package)
- [FastMCP HTTP transports](https://gofastmcp.com/clients/transports)
- [FastMCP tool calls and results](https://gofastmcp.com/clients/tools)
- [Anthropic: Handle tool calls](https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls)
- [Anthropic: Build a tool-using agent](https://platform.claude.com/docs/en/agents-and-tools/tool-use/build-a-tool-using-agent)
- [Anthropic: Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)

The [FastMCP Anthropic integration](https://gofastmcp.com/integrations/anthropic) demonstrates Anthropic's hosted MCP connector. It is useful background, but do not copy that client pattern for Caylex: it delegates tool discovery to Anthropic, whose catalog cache offers no supported way to force a fresh `tools/list`.
