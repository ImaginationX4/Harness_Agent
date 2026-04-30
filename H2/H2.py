"""
v2 改动:
- 新增 http_check 工具: 验证 (HTTP 状态 + body + 关键字断言)
- 新增 browser_check 工具: 3 验证 (playwright 端到端, 输入->点击->读输出)
- done criteria 显式引用具体工具, 不再用模糊的 'verify_webpage'
- 工具内置 expect_contains 断言, LLM 必须给出可验证的预期, 防止自欺

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
from openai import OpenAI
from dotenv import load_dotenv
from config import API_KEY, MODEL_ID, BASE_URL


client = OpenAI(api_key=API_KEY, base_url=BASE_URL)


# ─────────────────────────────────────────
# Service FSM
# ─────────────────────────────────────────

class ServiceState(Enum):
    RUNNING = "running"
    DEAD = "dead"


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
            "description": "Start a long-running background service (server/daemon). Returns a service_id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "service_id": {"type": "string"},
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
            "description": "Check if a background service process is still alive (L0: only proves the process exists, not that the app works).",
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
        log_file = open(f"{service_id}.log", "w")
        proc = subprocess.Popen(
            cmd, shell=True, stdout=log_file, stderr=subprocess.STDOUT
        )
        time.sleep(2)
        state = check_service_alive(proc.pid)
        if state == ServiceState.DEAD:
            try:
                with open(f"{service_id}.log") as f:
                    log_tail = f.read()[-500:]
            except Exception:
                log_tail = "(log unreadable)"
            return f"[error] service '{service_id}' died immediately. log tail:\n{log_tail}"
        service_registry[service_id] = proc.pid
        return f"[ok] service '{service_id}' started pid={proc.pid} state={state.value}"

    elif tool_name == "stop_service":
        service_id = tool_input["service_id"]
        pid = service_registry.pop(service_id, None)
        if pid is None:
            # 幂等: 没注册过就当已经停了, 不让 LLM 把它当错误反复重试
            return f"[ok] service '{service_id}' not in registry (already stopped or never started)"
        status = stop_service_by_pid(pid)
        return f"[ok] service '{service_id}' stopped ({status}, pid was {pid})"

    elif tool_name == "check_service":
        service_id = tool_input["service_id"]
        pid = service_registry.get(service_id)
        if pid is None:
            return f"[error] service '{service_id}' not found in registry"
        state = check_service_alive(pid)
        if state == ServiceState.DEAD:
            # 维护 invariant: registry ⊆ alive processes
            service_registry.pop(service_id, None)
            try:
                with open(f"{service_id}.log") as f:
                    log_tail = f.read()[-500:]
            except Exception:
                log_tail = "(log unreadable)"
            return f"[fail] service '{service_id}' DIED (pid={pid}). removed from registry. log tail:\n{log_tail}"
        return f"[ok] service '{service_id}' state={state.value}"

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

                # 文本通道: console + 未捕获 JS 异常
                console_msgs = []
                page.on("console", lambda msg: console_msgs.append(f"{msg.type}: {msg.text}"))
                page.on("pageerror", lambda exc: console_msgs.append(f"PAGEERROR: {exc}"))

                # 网络通道: 抓所有 4xx/5xx 响应 + 网络层失败
                # 这是 LLM 诊断 "Failed to load resource" 的关键信息
                failed_responses = []

                def on_response(resp):
                    if resp.status >= 400:
                        try:
                            # 只抓 body 前 500 字, 避免大 payload 爆 context
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

        # 异常展开: 失败请求带完整 URL+status+body, 让 LLM 能直接定位
        if failed_responses:
            lines = ["FAILED NETWORK REQUESTS:"]
            for fr in failed_responses[-10:]:
                lines.append(
                    f"  [{fr['method']} {fr['status']}] {fr['url']}\n"
                    f"    body: {fr['body_preview'][:300]}"
                )
            parts.append("\n".join(lines))

        if console_msgs:
            # 不再截短: 'Failed to load resource: the server responded with a sta...' 类信息要看全
            parts.append("console / pageerror (last 15):\n  " + "\n  ".join(console_msgs[-15:]))
        parts.append(f"final visible text (first 3000 chars):\n{visible[:3000]}")
        return "\n".join(parts)

    return f"[error] unknown tool: {tool_name}"


# ─────────────────────────────────────────
# Harness 主循环
# ─────────────────────────────────────────

def run_agent(user_task: str):
    service_registry = {}

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
        f"[done criteria]\n"
        f"Task is complete only when ALL hold:\n"
        f"  1. start_service returned [ok]\n"
        f"  2. http_check on the homepage returned [ok] (HTTP 200 and homepage keywords present)\n"
        f"  3. browser_check executed a real user flow (fill a Chinese query, click submit, wait for result)\n"
        f"     and returned [ok] with expect_contains hitting result keywords (e.g. 收益率, 胜率)\n"
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
        # harness 强制兜底: 不信任 LLM 自觉, 也不信任进程一定还活着
        for service_id, pid in list(service_registry.items()):
            status = stop_service_by_pid(pid)
            print(f"[cleanup] {service_id} (pid={pid}): {status}")
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