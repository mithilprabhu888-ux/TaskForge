"""TaskForge MCP server: 6 tools, 2 resources, 2 prompts over a persistent store."""

from mcp.server import MCPServer

from task_store import TaskError, TaskStore

store = TaskStore()
mcp = MCPServer("taskforge-mcp-server", version="1.0.0")


# ---------------------------------------------------------------------- #
# Tools
# ---------------------------------------------------------------------- #

@mcp.tool()
def create_task(title: str, priority: str = "medium", due: str = None) -> str:
    """Create a new task. priority is one of: low, medium, high.
    due is an optional ISO date like 2026-11-20 (must not be in the past)."""
    try:
        task = store.create(title, priority=priority, due=due)
    except TaskError as e:
        return f"Error: {e}"
    due_text = f", due {task['due']}" if task["due"] else ""
    return (f"Created task #{task['id']}: {task['title']} "
            f"[{task['priority']}]{due_text}")


@mcp.tool()
def list_tasks(status: str = None, priority: str = None) -> str:
    """List tasks, newest context first. Optionally filter by status
    (pending or done) and priority (low, medium, high). Sorted by priority."""
    try:
        tasks = store.list(status=status, priority=priority)
    except TaskError as e:
        return f"Error: {e}"
    if not tasks:
        return "No tasks match."
    lines = []
    for t in tasks:
        due = f", due {t['due']}" if t["due"] else ""
        marker = "✓" if t["status"] == "done" else " "
        lines.append(f"[{marker}] #{t['id']} {t['title']} "
                     f"({t['priority']}, {t['status']}{due})")
    return "\n".join(lines)


@mcp.tool()
def complete_task(task_id: int) -> str:
    """Mark a task done by its numeric id (from list_tasks)."""
    try:
        task = store.complete(task_id)
    except TaskError as e:
        return f"Error: {e}"
    return f"Completed task #{task['id']}: {task['title']}"


@mcp.tool()
def delete_task(task_id: int) -> str:
    """Permanently delete a task by its numeric id."""
    try:
        store.delete(task_id)
    except TaskError as e:
        return f"Error: {e}"
    return f"Deleted task #{task_id}"


@mcp.tool()
def update_task(task_id: int, title: str = None, priority: str = None,
                due: str = None) -> str:
    """Update a task's title, priority (low/medium/high) or due date
    (ISO date). Only provided fields are changed."""
    try:
        task = store.update(task_id, title=title, priority=priority, due=due)
    except TaskError as e:
        return f"Error: {e}"
    due_text = f", due {task['due']}" if task["due"] else ""
    return (f"Updated task #{task['id']}: {task['title']} "
            f"[{task['priority']}]{due_text}")


@mcp.tool()
def task_stats() -> str:
    """Get counts: total, pending/done, pending by priority, overdue."""
    stats = store.stats()
    return (f"Total: {stats['total']} | "
            f"pending: {stats['by_status']['pending']} "
            f"(high {stats['pending_by_priority']['high']}, "
            f"medium {stats['pending_by_priority']['medium']}, "
            f"low {stats['pending_by_priority']['low']}) | "
            f"done: {stats['by_status']['done']} | "
            f"overdue: {stats['overdue']}")


# ---------------------------------------------------------------------- #
# Resources
# ---------------------------------------------------------------------- #

@mcp.resource(
    "task://guidelines",
    name="task-guidelines",
    description="Guidelines for managing and prioritizing tasks",
    mime_type="text/plain",
)
def task_guidelines() -> str:
    return (
        "Task management guidelines:\n"
        "1. Capture every request as a task with a clear, actionable title.\n"
        "2. Use priority: high = today, medium = this week, low = someday.\n"
        "3. Set a due date whenever the user mentions a deadline.\n"
        "4. Complete tasks by id (never guess an id — list first).\n"
        "5. Prefer updating over deleting when plans change.\n"
        "6. When planning a day, work high → medium → low and mention due dates."
    )


@mcp.resource(
    "task://stats",
    name="task-stats",
    description="Live snapshot of task counts",
    mime_type="text/plain",
)
def task_stats_resource() -> str:
    return task_stats()


# ---------------------------------------------------------------------- #
# Prompts
# ---------------------------------------------------------------------- #

@mcp.prompt(name="plan_day",
            description="Plan pending tasks for the available time")
def plan_day(availableHours: str) -> str:
    """Plan pending tasks for the available time."""
    return (
        f"I have {availableHours} hours available today. Here are my tasks:\n\n"
        "{pending_tasks}\n\n"
        "Propose a realistic schedule for the available time. Work from high "
        "to low priority, respect due dates, and say what to defer."
    )


@mcp.prompt(name="prioritize",
            description="Re-order pending tasks by urgency and impact")
def prioritize() -> str:
    """Re-order pending tasks by urgency and impact."""
    return (
        "Here are my pending tasks:\n\n{pending_tasks}\n\n"
        "Rank them by urgency and impact. Point out anything overdue, and "
        "suggest which low-value tasks I should drop or defer."
    )


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="127.0.0.1", port=8081)
