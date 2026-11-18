"""Tests for the TaskForge agent loop using fakes (no network, no MCP server)."""

import asyncio
import unittest
from types import SimpleNamespace

from mcp.types import TextContent, TextResourceContents

from chat_service import AgentService

GUIDELINES = "1. Be tidy. 2. Use ids from list_tasks."
TOOLS = [
    SimpleNamespace(name="create_task", description="Create a task",
                    input_schema={"type": "object", "properties": {}}),
    SimpleNamespace(name="list_tasks", description="List tasks",
                    input_schema={"type": "object", "properties": {}}),
]


class FakeMCP:
    """Minimal async MCP client double."""

    def __init__(self, tool_results=None):
        self.tool_results = tool_results or {}
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def list_tools(self):
        return SimpleNamespace(tools=TOOLS)

    async def read_resource(self, uri):
        assert uri == "task://guidelines"
        return SimpleNamespace(contents=[TextResourceContents(
            uri=uri, text=GUIDELINES)])

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        text = self.tool_results.get(name, f"{name} ok")
        return SimpleNamespace(content=[TextContent(type="text", text=text)])

    async def get_prompt(self, name, arguments):
        return SimpleNamespace(messages=[SimpleNamespace(content=TextContent(
            type="text", text=f"Prompt {name} {arguments}"))])


class FakeOpenAI:
    """Scripted chat completions: script items are (name, args) tuples for a
    tool-call round, or the string "final" for a plain answer."""

    def __init__(self, script):
        self.script = list(script)
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(
            create=self._make()))

    def _make(self):
        script = self.script

        async def create(**kwargs):
            self.requests.append(kwargs)
            step = script.pop(0)
            if step == "final":
                message = SimpleNamespace(content="All done!",
                                          tool_calls=None)
            else:
                name, arguments = step
                message = SimpleNamespace(
                    content="",
                    tool_calls=[SimpleNamespace(
                        id="call-1",
                        function=SimpleNamespace(name=name,
                                                 arguments=arguments))])
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

        return create


def run(coro):
    return asyncio.run(coro)


def make_agent(script, mcp=None):
    openai = FakeOpenAI(script)
    mcp = mcp or FakeMCP()
    agent = AgentService(openai_client=openai,
                         mcp_client_factory=lambda: mcp,
                         model="test-model")
    return agent, openai, mcp


async def collect(agent, message="do things"):
    return [evt async for evt in agent.ask_stream("sid-1", message)]


class AgentTest(unittest.TestCase):
    def test_plain_answer_no_tools(self):
        agent, openai, _ = make_agent(["final"])
        events = run(collect(agent))
        types = [e["type"] for e in events]
        self.assertEqual(types, ["status", "status", "text", "done"])
        text = [e for e in events if e["type"] == "text"][0]["text"]
        self.assertEqual(text, "All done!")
        # The system prompt included the guidelines from the MCP resource.
        sent = openai.requests[0]["messages"]
        self.assertIn(GUIDELINES, sent[0]["content"])

    def test_tool_rounds_are_streamed(self):
        script = [
            ("create_task", '{"title": "Ship", "priority": "high"}'),
            ("list_tasks", "{}"),
            "final",
        ]
        mcp = FakeMCP(tool_results={"create_task": "Created task #1: Ship",
                                    "list_tasks": "[ ] #1 Ship"})
        agent, openai, _ = make_agent(script, mcp)
        events = run(collect(agent))
        types = [e["type"] for e in events]
        self.assertEqual(types.count("tool_call"), 2)
        self.assertEqual(types.count("tool_result"), 2)
        self.assertEqual(types[-2:], ["text", "done"])

        first_call = [e for e in events if e["type"] == "tool_call"][0]
        self.assertEqual(first_call["name"], "create_task")
        self.assertEqual(first_call["arguments"]["title"], "Ship")

        first_result = [e for e in events if e["type"] == "tool_result"][0]
        self.assertIn("Created task #1", first_result["result"])
        self.assertEqual(mcp.calls, [
            ("create_task", {"title": "Ship", "priority": "high"}),
            ("list_tasks", {}),
        ])

        # Both tool results were fed back to the model as tool messages.
        last_request = openai.requests[-1]["messages"]
        tool_messages = [m for m in last_request if m["role"] == "tool"]
        self.assertEqual(len(tool_messages), 2)
        self.assertIn("Created task #1", tool_messages[0]["content"])

    def test_history_commit_and_cleanup(self):
        agent, _, _ = make_agent(["final"])
        run(collect(agent, "first question"))
        self.assertEqual(len(agent.history("sid-1")), 2)
        agent.clear("sid-1")
        self.assertEqual(agent.history("sid-1"), [])

    def test_error_event_on_mcp_failure(self):
        class BrokenMCP(FakeMCP):
            async def read_resource(self, uri):
                raise RuntimeError("connection refused")

        agent, _, _ = make_agent(["final"], BrokenMCP())
        events = run(collect(agent))
        types = [e["type"] for e in events]
        self.assertIn("error", types)
        self.assertEqual(types[-1], "done")
        error = [e for e in events if e["type"] == "error"][0]
        self.assertIn("connection refused", error["text"])

    def test_plan_uses_prompt(self):
        agent, openai, _ = make_agent(["final"])
        text = run(agent.plan("4"))
        self.assertEqual(text, "All done!")
        sent = openai.requests[0]["messages"]
        self.assertEqual(sent[-1]["content"],
                         "Prompt plan_day {'availableHours': '4'}")


if __name__ == "__main__":
    unittest.main()
