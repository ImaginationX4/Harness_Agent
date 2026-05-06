"""
v2.1 改动:
- service_registry 从 Map<id, pid> 升级为 Map<id, ServiceInfo>
- ServiceInfo 包含 {pid, command, log_path, started_at, port}
- start_service 新增 port 参数 (LLM 必须显式声明)
- 新增 list_services 工具: LLM 在 http_check 前查 port
- check_service / stop_service / cleanup 全部改用 ServiceInfo
- prompt 加 [port discipline] 段, 强制 LLM 走 list_services 流程

依赖:
    pip install requests playwright python-dotenv openai
    playwright install chromium
"""

import os
import json
import time
import signal
import subprocess
from enum import Enum
from dataclasses import dataclass
from typing import Optional
from openai import OpenAI
from dotenv import load_dotenv
from config import API_KEY, MODEL_ID, BASE_URL


client = OpenAI(api_key=API_KEY, base_url=BASE_URL)


# ─────────────────────────────────────────
# Service FSM + ServiceInfo
# ─────────────────────────────────────────

class ServiceState(Enum):
    RUNNING = "running"
    DEAD = "dead"


@dataclass
class ServiceInfo:
    """registry 的值类型. 不变量:
       ∀ id ∈ registry, registry[id] 至少有 pid + command + log_path + started_at,
       port 可为 None (LLM 启动时未声明)。
    """
    pid: int
    command: str
    log_path: str
    port: Optional[int] = None


def check_service_alive(pid: int) -> ServiceState:
    try:
        os.kill(pid, 0)
        return ServiceState.RUNNING
    except ProcessLookupError:
        return ServiceState.DEAD


def stop_service_by_pid(pid: int) -> str:
    """幂等: 无论进程死活, 调用后保证它不在了. 返回状态描述."""
    try:
        os.kill(pid, signal.SIGTERM)
        return "sent SIGTERM"
    except ProcessLookupError:
        return "already dead"


# ─────────────────────────────────────────
# Tools 定义
# ─────────────────────────────────────────

tools = [
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run a short-lived shell command and return output. Do NOT use for long-running servers. Do NOT use this for HTTP verification — use http_check instead.",
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
                "Start a long-running background service (server/daemon). "
                "If the service listens on a port, you MUST pass `port` so subsequent "
                "http_check / browser_check can target the right URL. "
                "Returns service_id, pid and port."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "service_id": {"type": "string"},
                    "port": {"type": "integer", "description": "Port the service listens on, if any."},
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
            "description": "Check if a background service process is still alive (L0: only proves the process exists, not that the app works). Returns pid + port + log path.",
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
            "description": (
                "List all registered services with pid, port, log_path, state. "
                "Call this before http_check / browser_check to confirm which port to hit. "
                "Call this if you forgot what is running."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "http_check",
            "description": (
                "L1/L2 verification. Send an HTTP request and return status code + body snippet. "
                "Use expect_contains to assert keywords in the response — the tool will tell you which hit/missed. "
                "Use this instead of curl. Use this to verify static pages and JSON APIs."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "method": {"type": "string", "enum": ["GET", "POST"], "default": "GET"},
                    "url": {"type": "string"},
                    "json_body": {"type": "object", "description": "JSON payload for POST"},
                    "expect_contains": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Keywords expected in response body. Tool reports hit/miss for each.",
                    },
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
                "L3 verification. Open a URL in headless Chromium, run a sequence of user actions "
                "(fill / click / wait / wait_ms), then read final visible text. "
                "Use this to verify end-to-end user interaction — JS rendering, form submission, async results. "
                "expect_contains asserts keywords in the FINAL visible text after all actions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "actions": {
                        "type": "array",
                        "description": "Ordered list of user actions",
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string", "enum": ["fill", "click", "wait", "wait_ms"]},
                                "selector": {"type": "string", "description": "CSS selector (for fill/click/wait)"},
                                "value": {"type": "string", "description": "Text to fill (for fill)"},
                                "ms": {"type": "integer", "description": "Milliseconds (for wait_ms)"},
                                "timeout": {"type": "integer", "description": "Wait timeout in ms (for wait), default 10000"},
                            },
                            "required": ["type"],
                        },
                    },
                    "expect_contains": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Keywords expected in final visible text. Tool reports hit/miss.",
                    },
                },
                "required": ["url"],
            },
        },
    },
]


# ─────────────────────────────────────────
# Tool 执行层
# ─────────────────────────────────────────

def execute_tool(tool_name, tool_input, service_registry: dict) -> str:

    if tool_name == "run_command":
        result = subprocess.run(
            tool_input["command"], shell=True, capture_output=True, text=True
        )
        parts = [f"[exit code: {result.returncode}]"]
        if result.stdout:
            parts.append(f"[stdout]\n{result.stdout}")
        if result.stderr:
            parts.append(f"[stderr]\n{result.stderr}")
        if not result.stdout and not result.stderr:
            parts.append("[no output]")
        return "\n".join(parts)

    elif tool_name == "start_service":
        cmd = tool_input["command"]
        service_id = tool_input["service_id"]
        port = tool_input.get("port")
        #log_path = f"{service_id}.log"
        log_path = f"{service_id}_{int(time.time())}.log"
        log_file = open(log_path, "w")
        proc = subprocess.Popen(cmd, shell=True, stdout=log_file, stderr=subprocess.STDOUT)
        time.sleep(2)
        state = check_service_alive(proc.pid)
        if state == ServiceState.DEAD:
            try:
                with open(log_path) as f:
                    log_tail = f.read()[-500:]
            except Exception:
                log_tail = "(log unreadable)"
            return f"[error] service '{service_id}' died immediately. log tail:\n{log_tail}"
        service_registry[service_id] = ServiceInfo(
            pid=proc.pid,
            command=cmd,
            log_path=log_path,
            port=port,
        )
        port_msg = f"port={port}" if port else "port=UNDECLARED (you should have passed port; downstream http_check may fail)"
        return f"[ok] service '{service_id}' started pid={proc.pid} {port_msg} log={log_path}"

    elif tool_name == "stop_service":
        service_id = tool_input["service_id"]
        info = service_registry.pop(service_id, None)
        if info is None:
            return f"[ok] service '{service_id}' not in registry (already stopped or never started)"
        status = stop_service_by_pid(info.pid)
        return f"[ok] service '{service_id}' stopped ({status}, pid was {info.pid}, port was {info.port})"

    elif tool_name == "check_service":
        service_id = tool_input["service_id"]
        info = service_registry.get(service_id)
        if info is None:
            return f"[error] service '{service_id}' not found in registry"
        state = check_service_alive(info.pid)
        if state == ServiceState.DEAD:
            service_registry.pop(service_id, None)
            try:
                with open(info.log_path) as f:
                    log_tail = f.read()[-500:]
            except Exception:
                log_tail = "(log unreadable)"
            return (
                f"[fail] service '{service_id}' DIED (pid={info.pid}, port={info.port}). "
                f"removed from registry. log tail:\n{log_tail}"
            )
        return (
            f"[ok] service '{service_id}' state={state.value} "
            f"pid={info.pid} port={info.port} log={info.log_path}"
        )

    elif tool_name == "list_services":
        if not service_registry:
            return "[ok] no services running"
        lines = ["[ok] running services:"]
        for sid, info in service_registry.items():
            state = check_service_alive(info.pid).value
            lines.append(
                f"  - {sid}: pid={info.pid} port={info.port} "
                f"state={state} log={info.log_path} cmd={info.command!r}"
            )
        return "\n".join(lines)

    elif tool_name == "http_check":
        try:
            import requests
        except ImportError:
            return "[error] requests not installed. Run: pip install requests"

        method = tool_input.get("method", "GET").upper()
        url = tool_input["url"]
        json_body = tool_input.get("json_body")
        expect = tool_input.get("expect_contains", []) or []

        try:
            if method == "GET":
                r = requests.get(url, timeout=15)
            else:
                r = requests.post(url, json=json_body, timeout=15)
        except Exception as e:
            return f"[error] {type(e).__name__}: {e}"

        body = r.text
        hits = {kw: (kw in body) for kw in expect}
        all_hit = all(hits.values()) if hits else True
        status_tag = "[ok]" if r.ok and all_hit else "[fail]"

        parts = [f"{status_tag} {method} {url} -> HTTP {r.status_code}"]
        if hits:
            parts.append(f"keyword hits: {hits}")
        parts.append(f"body (first 2000 chars):\n{body[:2000]}")
        return "\n".join(parts)

    elif tool_name == "browser_check":
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return (
                "[error] playwright not installed. Run:\n"
                "  pip install playwright\n"
                "  playwright install chromium"
            )

        url = tool_input["url"]
        actions = tool_input.get("actions", []) or []
        expect = tool_input.get("expect_contains", []) or []

        logs = []
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context()
                page = context.new_page()

                console_msgs = []
                page.on("console", lambda msg: console_msgs.append(f"{msg.type}: {msg.text}"))
                page.on("pageerror", lambda exc: console_msgs.append(f"PAGEERROR: {exc}"))

                failed_responses = []

                def on_response(resp):
                    if resp.status >= 400:
                        try:
                            body_preview = resp.text()[:500]
                        except Exception:
                            body_preview = "(body unreadable)"
                        failed_responses.append({
                            "url": resp.url,
                            "status": resp.status,
                            "method": resp.request.method,
                            "body_preview": body_preview,
                        })

                def on_requestfailed(req):
                    failed_responses.append({
                        "url": req.url,
                        "status": "NETWORK_FAILED",
                        "method": req.method,
                        "body_preview": req.failure or "(no failure reason)",
                    })

                page.on("response", on_response)
                page.on("requestfailed", on_requestfailed)

                page.goto(url, timeout=15000)
                logs.append(f"goto {url}")

                for a in actions:
                    t = a["type"]
                    if t == "fill":
                        page.fill(a["selector"], a["value"])
                        logs.append(f"fill {a['selector']!r} <- {a['value'][:40]!r}")
                    elif t == "click":
                        page.click(a["selector"])
                        logs.append(f"click {a['selector']!r}")
                    elif t == "wait":
                        page.wait_for_selector(a["selector"], timeout=a.get("timeout", 10000))
                        logs.append(f"wait_selector {a['selector']!r}")
                    elif t == "wait_ms":
                        page.wait_for_timeout(a.get("ms", 1000))
                        logs.append(f"wait {a.get('ms', 1000)}ms")
                    else:
                        logs.append(f"[skip] unknown action type: {t}")

                visible = page.inner_text("body")
                browser.close()
        except Exception as e:
            return f"[error] browser_check failed during interaction: {type(e).__name__}: {e}\nlogs so far: {logs}"

        hits = {kw: (kw in visible) for kw in expect}
        all_hit = all(hits.values()) if hits else True
        status_tag = "[ok]" if all_hit and not failed_responses else "[fail]"

        parts = [
            f"{status_tag} browser_check on {url}",
            f"actions executed:\n  " + "\n  ".join(logs),
        ]
        if hits:
            parts.append(f"keyword hits: {hits}")

        if failed_responses:
            lines = ["FAILED NETWORK REQUESTS:"]
            for fr in failed_responses[-10:]:
                lines.append(
                    f"  [{fr['method']} {fr['status']}] {fr['url']}\n"
                    f"    body: {fr['body_preview'][:300]}"
                )
            parts.append("\n".join(lines))

        if console_msgs:
            parts.append("console / pageerror (last 15):\n  " + "\n  ".join(console_msgs[-15:]))
        parts.append(f"final visible text (first 3000 chars):\n{visible[:3000]}")
        return "\n".join(parts)

    return f"[error] unknown tool: {tool_name}"


# ─────────────────────────────────────────
# Harness 主循环
# ─────────────────────────────────────────

def run_agent(user_task: str):
    service_registry: dict[str, ServiceInfo] = {}

    plan_prompt = (
        f"{user_task}\n\n"
        f"[verification policy]\n"
        f"You MUST verify your work, not assume it works. Use the verification hierarchy:\n"
        f"  L0 check_service     -> only proves the process is alive (weak)\n"
        f"  L1 http_check GET    -> proves the page/route renders\n"
        f"  L2 http_check POST   -> proves the API logic works (if you have a JSON API)\n"
        f"  L3 browser_check     -> proves end-to-end user interaction works\n"
        f"For every assertion, pass expect_contains with concrete keywords you predict will appear.\n"
        f"If a check returns [fail], DO NOT call it 'done' — diagnose, fix, retry.\n\n"
        f"[port discipline]\n"
        f"When you start a service, ALWAYS pass `port` to start_service.\n"
        f"Before any http_check / browser_check against your service, call list_services to confirm the port.\n"
        f"NEVER hardcode a port (e.g. 8000) from memory — read it from list_services.\n"
        f"If you change the port for any reason, stop the old service first, then start_service with the new port.\n\n"
        f"[done criteria]\n"
        f"Task is complete only when ALL hold:\n"
        f"  1. start_service returned [ok] with a declared port\n"
        f"  2. http_check on the homepage returned [ok] (HTTP 200 and homepage keywords present)\n"
        f"  3. browser_check executed a real user flow (fill an input, click submit, wait for result)\n"
        f"     and returned [ok] with expect_contains hitting result keywords\n"
        f"  4. stop_service was called for every service you started\n"
    )

    messages = [{"role": "user", "content": plan_prompt}]
    max_iterations = 50

    try:
        for _ in range(max_iterations):
            response = client.chat.completions.create(
                model=MODEL_ID,
                messages=messages,
                tools=tools,
                tool_choice="auto",
            )

            response_message = response.choices[0].message
            messages.append(response_message)

            if not response_message.tool_calls:
                print(f"[DONE] {response_message.content}")
                break

            for tool_call in response_message.tool_calls:
                function_name = tool_call.function.name
                function_args = json.loads(tool_call.function.arguments)

                print(f"[TOOL] {function_name}({function_args})")
                output = execute_tool(function_name, function_args, service_registry)
                print(f"[RESULT] {output[:300]}")

                messages.append({
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "name": function_name,
                    "content": output,
                })
    finally:
        # 兜底: 不信任 LLM 自觉, 也不信任进程一定还活着
        for service_id, info in list(service_registry.items()):
            status = stop_service_by_pid(info.pid)
            print(f"[cleanup] {service_id} (pid={info.pid}, port={info.port}): {status}")
        service_registry.clear()

    return messages


if __name__ == "__main__":
    prompt = (
        "做一个可以互动的网页，不调用额外的需要联网的api"
    )
    messages = run_agent(prompt)
    with open(f"run_{int(time.time())}.json", "w") as f:
        json.dump(
            [m if isinstance(m, dict) else m.model_dump() for m in messages],
            f, indent=2, ensure_ascii=False, default=str,
        )