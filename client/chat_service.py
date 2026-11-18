"""TaskForge client: an agent loop over MCP with live event streaming."""

import json
from threading import Lock
from typing import Any, AsyncIterator

from mcp.types import TextContent, TextResourceContents
from openai import AsyncOpenAI

MAX_ROUNDS = 10
MAX_HISTORY = 20

GUIDELINES_URI = "task://guidelines"

SYSTEM_TEMPLATE = """You are TaskForge, a task management assistant.

Use your MCP tools to actually create, update, complete and list tasks.
Follow these guidelines whenever they are relevant:

TASK GUIDELINES:

{guidelines}

Rules:
- Call tools whenever an action is needed; never claim you did something
  without calling a tool.
- Use task ids from list_tasks for complete/update/delete.
- Keep final answers short and concrete."""


class AgentService:
    def __init__(self, openai_client: AsyncOpenAI, mcp_client_factory,
                 model: str, max_rounds: int = MAX_ROUNDS):
        self.openai = openai_client
        self.mcp_factory = mcp_client_factory   # returns an async MCP Client
        self.model = model
        self.max_rounds = max_rounds
        self.sessions: dict[str, list[dict]] = {}
        self.lock = Lock()

    # ------------------------------------------------------------------ #
    # Session history (text turns only)
    # ------------------------------------------------------------------ #

    def history(self, sid: str) -> list[dict]:
        with self.lock:
            return list(self.sessions.get(sid, []))

    def clear(self, sid: str) -> None:
        with self.lock:
            self.sessions.pop(sid, None)

    def _commit(self, sid: str, message: str, reply: str) -> None:
        with self.lock:
            history = self.sessions.setdefault(sid, [])
            history.append({"role": "user", "content": message})
            history.append({"role": "assistant", "content": reply})
            if len(history) > MAX_HISTORY:
                del history[:-MAX_HISTORY]

    # ------------------------------------------------------------------ #
    # MCP helpers
    # ------------------------------------------------------------------ #

    async def _guidelines(self, client: Any) -> str:
        result = await client.read_resource(GUIDELINES_URI)
        content = result.contents[0]
        if not isinstance(content, TextResourceContents):
            raise TypeError("The task guidelines resource must contain text.")
        return content.text

    @staticmethod
    def _to_openai_tools(mcp_tools: list[Any]) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": tool.input_schema,
                },
            }
            for tool in mcp_tools
        ]

    @staticmethod
    def _tool_result_text(result: Any) -> str:
        values = []
        for block in result.content:
            if isinstance(block, TextContent):
                values.append(block.text)
            else:
                values.append(json.dumps(block.model_dump(mode="json")))
        return "\n".join(values)

    # ------------------------------------------------------------------ #
    # Streaming agent
    # ------------------------------------------------------------------ #

    async def ask_stream(self, sid: str, message: str) -> AsyncIterator[dict]:
        """Run the agent loop, yielding live events:
        status / tool_call / tool_result / text / done / error."""
        try:
            async with self.mcp_factory() as client:
                async for event in self._run(sid, message, client):
                    yield event
        except Exception as e:                       # noqa: BLE001
            yield {"type": "error",
                   "text": f"Agent failure: {e}"}
            yield {"type": "done"}

    async def _run(self, sid: str, message: str, client: Any):
        yield {"type": "status", "text": "connecting to MCP server…"}

        listed = await client.list_tools()
        tools = self._to_openai_tools(listed.tools)
        guidelines = await self._guidelines(client)
        system = SYSTEM_TEMPLATE.format(guidelines=guidelines)

        messages = [
            {"role": "system", "content": system},
            *self.history(sid),
            {"role": "user", "content": message},
        ]

        for round_no in range(1, self.max_rounds + 1):
            yield {"type": "status",
                   "text": f"thinking (round {round_no})…"}
            response = await self.openai.chat.completions.create(
                model=self.model,
                tools=tools,
                messages=messages,
            )
            reply = response.choices[0].message
            tool_calls = reply.tool_calls or []

            if not tool_calls:
                text = reply.content or ""
                self._commit(sid, message, text)
                yield {"type": "text", "text": text}
                yield {"type": "done"}
                return

            messages.append({
                "role": "assistant",
                "content": reply.content or "",
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.function.name,
                            "arguments": call.function.arguments,
                        },
                    }
                    for call in tool_calls
                ],
            })

            for call in tool_calls:
                args = json.loads(call.function.arguments or "{}")
                yield {"type": "tool_call",
                       "name": call.function.name,
                       "arguments": args}
                result = await client.call_tool(call.function.name, args)
                result_text = self._tool_result_text(result)
                yield {"type": "tool_result",
                       "name": call.function.name,
                       "result": result_text}
                messages.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": result_text,
                })

        yield {"type": "error",
               "text": "The model used too many tool-calling rounds."}
        yield {"type": "done"}

    # ------------------------------------------------------------------ #
    # Non-streaming variants (curl-friendly)
    # ------------------------------------------------------------------ #

    async def ask(self, sid: str, message: str) -> str:
        text = ""
        async for event in self.ask_stream(sid, message):
            if event["type"] == "text":
                text = event["text"]
            elif event["type"] == "error":
                text = event["text"]
        return text

    async def plan(self, hours: str) -> str:
        async with self.mcp_factory() as client:
            result = await client.get_prompt("plan_day",
                                             {"availableHours": hours})
            content = result.messages[0].content
            if not isinstance(content, TextContent):
                raise TypeError("The plan_day prompt must contain text.")
            return await self._run_plain(content.text)

    async def _run_plain(self, message: str) -> str:
        text = ""
        async for event in self.ask_stream("plan", message):
            if event["type"] == "text":
                text = event["text"]
            elif event["type"] == "error":
                text = event["text"]
        return text

    async def tasks_text(self) -> str:
        async with self.mcp_factory() as client:
            result = await client.call_tool("list_tasks", {})
            return self._tool_result_text(result)
