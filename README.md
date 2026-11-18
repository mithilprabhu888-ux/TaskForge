# TaskForge

**A task agent where you can watch the tools think.**

TaskForge is an MCP (Model Context Protocol) project: a Python MCP **server**
exposes real task tools, resources and prompts, and an AI **client** agent
calls them live while you watch every tool call happen in the chat UI.

Built with **FastAPI + Groq + the MCP SDK** (streamable HTTP transport).

## What it does

- 🛠 **6 MCP tools** — `create_task`, `list_tasks`, `complete_task`,
  `delete_task`, `update_task`, `task_stats` — over a rich task model
  (id, title, priority, due date, status) with **JSON file persistence**,
  so tasks survive restarts
- 👀 **Live tool trace** — the client streams agent events over SSE, so you
  see 🔧 `create_task({...})` and ✅ its result appear in the chat *before*
  the final answer
- 📋 **Task sidebar** — always-up-to-date task list (priority chips, due
  dates, done strikethrough) fed by a real MCP tool call
- 🧠 **Memory** — the agent remembers your conversation across messages
- 📚 **2 resources** (`task://guidelines`, `task://stats`) and
  **2 prompts** (`plan_day`, `prioritize`) — full MCP surface, not just tools

## Setup

```bash
# 1. Start the MCP server (port 8081)
cd server
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
python server.py

# 2. Start the client (port 8080) — new terminal
cd client
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env        # then fill in GROQ_API_KEY
uvicorn main:app --host 127.0.0.1 --port 8080
```

Open http://127.0.0.1:8080 and talk to your tasks:

> “Add a high-priority task to ship the demo by Friday”
> “What's pending this week?”
> “Complete task 1 and show stats”

## MCP surface

| Kind | Name | What it does |
|---|---|---|
| Tool | `create_task(title, priority?, due?)` | Create; validates priority + date |
| Tool | `list_tasks(status?, priority?)` | Filtered list, sorted high→low |
| Tool | `complete_task(task_id)` | Mark done |
| Tool | `delete_task(task_id)` | Remove |
| Tool | `update_task(task_id, ...)` | Edit title/priority/due |
| Tool | `task_stats()` | Counts incl. overdue |
| Resource | `task://guidelines` | Task-management guidelines (fed to the agent) |
| Resource | `task://stats` | Live snapshot |
| Prompt | `plan_day(availableHours)` | Day-plan prompt → `/plan?hours=4` |
| Prompt | `prioritize` | Urgency ranking prompt |

## Client API

| Method | Route | Description |
|---|---|---|
| `POST` | `/ask/stream?message=` | SSE: `status` / `tool_call` / `tool_result` / `text` / `done` events |
| `GET` | `/ask?message=` | Plain final answer (curl-friendly) |
| `GET` | `/plan?hours=` | Uses the MCP `plan_day` prompt |
| `GET` | `/api/tasks` | Task list via a real MCP tool call |
| `POST` | `/api/clear` | Clear this session's memory |

## How it works

1. The client fetches `task://guidelines` from the MCP server and folds it
   into the system prompt
2. MCP tools are exposed to the LLM as OpenAI-style function tools
3. Each tool-call round is streamed to the UI as it happens
4. Tool results go back to the model until it produces the final answer
5. Conversation memory is kept per browser session (capped, in-memory)
