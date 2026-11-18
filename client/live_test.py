"""Manual live test: streaming agent events through the real MCP server."""
import json
import sys

import requests

sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://127.0.0.1:8080"

r = requests.post(f"{BASE}/ask/stream",
                  params={"message": "Add a low priority task: read the MCP spec"},
                  timeout=120, stream=True)
print("stream status:", r.status_code)
types = []
for line in r.iter_lines(decode_unicode=True):
    if not line.startswith("data:"):
        continue
    evt = json.loads(line[5:].strip())
    types.append(evt["type"])
    if evt["type"] == "tool_call":
        print(f"  TOOL_CALL   {evt['name']} {json.dumps(evt['arguments'])}")
    elif evt["type"] == "tool_result":
        print(f"  TOOL_RESULT {evt['name']}: {evt['result'][:70]}")
    elif evt["type"] == "text":
        print(f"  ANSWER      {evt['text'][:100]}")
print("event types:", types)

r = requests.get(f"{BASE}/api/tasks", timeout=60)
print("tasks now:", r.json()["text"])
