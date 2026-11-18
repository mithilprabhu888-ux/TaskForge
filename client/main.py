import json
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from mcp import Client
from openai import AsyncOpenAI
from sse_starlette.sse import EventSourceResponse

from chat_service import AgentService

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")

if not os.getenv("GROQ_API_KEY"):
    raise RuntimeError("Set GROQ_API_KEY in the .env file")

MCP_URL = os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8081/mcp")
SESSION_COOKIE = "taskforge_sid"

agent = AgentService(
    openai_client=AsyncOpenAI(
        api_key=os.getenv("GROQ_API_KEY"),
        base_url="https://api.groq.com/openai/v1",
    ),
    mcp_client_factory=lambda: Client(MCP_URL),
    model=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
)


def sid_or_new(request: Request) -> str:
    return request.cookies.get(SESSION_COOKIE) or secrets.token_urlsafe(24)


def set_cookie(response: Response, sid: str) -> Response:
    response.set_cookie(SESSION_COOKIE, sid, max_age=7 * 24 * 60 * 60,
                        httponly=True, samesite="Lax")
    return response


app = FastAPI(title="TaskForge Client")


@app.post("/ask/stream")
async def ask_stream(request: Request, message: str = Query(min_length=1)):
    sid = sid_or_new(request)

    async def generate():
        async for event in agent.ask_stream(sid, message):
            yield {"data": json.dumps(event)}

    return set_cookie(EventSourceResponse(generate()), sid)


@app.get("/ask", response_class=PlainTextResponse)
async def ask(request: Request, message: str) -> str:
    return await agent.ask(sid_or_new(request), message)


@app.get("/plan", response_class=PlainTextResponse)
async def plan(request: Request, hours: str) -> str:
    return await agent.plan(hours)


@app.get("/api/tasks")
async def tasks():
    return {"text": await agent.tasks_text()}


@app.post("/api/clear")
async def clear(request: Request):
    agent.clear(sid_or_new(request))
    return {"ok": True}


@app.get("/")
def index():
    response = FileResponse(HERE / "static" / "index.html")
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
