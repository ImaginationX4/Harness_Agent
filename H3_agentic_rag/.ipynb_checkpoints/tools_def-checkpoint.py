"""tools_def.py — 工具 schema 列表。纯数据，无副作用。"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run a short-lived shell command and return output. Do NOT use for long-running servers or HTTP verification.",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "start_service",
            "description": (
                "Start a long-running background service. "
                "If it listens on a port, you MUST pass `port`."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "service_id": {"type": "string"},
                    "port": {"type": "integer"},
                },
                "required": ["command", "service_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "stop_service",
            "description": "Stop a background service by service_id.",
            "parameters": {
                "type": "object",
                "properties": {"service_id": {"type": "string"}},
                "required": ["service_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_service",
            "description": "Check if a service process is alive. Returns pid + port + log path.",
            "parameters": {
                "type": "object",
                "properties": {"service_id": {"type": "string"}},
                "required": ["service_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_services",
            "description": "List all registered services. Call before http_check/browser_check to confirm the port.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "http_check",
            "description": (
                "L1/L2 verification. Send HTTP GET/POST, assert keywords via expect_contains. "
                "Use instead of curl."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "method": {"type": "string", "enum": ["GET", "POST"], "default": "GET"},
                    "url": {"type": "string"},
                    "json_body": {"type": "object"},
                    "expect_contains": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_check",
            "description": (
                "L3 verification. Headless Chromium, run user actions (fill/click/wait), "
                "assert final visible text via expect_contains."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "actions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string", "enum": ["fill", "click", "wait", "wait_ms"]},
                                "selector": {"type": "string"},
                                "value": {"type": "string"},
                                "ms": {"type": "integer"},
                                "timeout": {"type": "integer"},
                            },
                            "required": ["type"],
                        },
                    },
                    "expect_contains": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_kb",
            "description": (
                "Search the local knowledge base (markdown files). "
                "Use when you need background knowledge, methodology, or past context. "
                "Returns ranked text chunks. Call this before answering questions that "
                "require domain knowledge."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Keywords to search for"},
                    "k": {"type": "integer", "default": 5, "description": "Max chunks to return"},
                },
                "required": ["query"],
            },
        },
    },
]