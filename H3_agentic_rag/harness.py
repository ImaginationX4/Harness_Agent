"""harness.py — 协调层。只做两件事：dispatch tool calls，跑 agent 主循环。"""
from __future__ import annotations
import json
import time
from pathlib import Path

from openai import OpenAI
from config import API_KEY, MODEL_ID, BASE_URL

import service_ops
import verifier
import search_kb as _kb
from tools_def import TOOLS

client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

# 知识库目录：默认与 harness.py 同层的 knowledge/，启动前可覆盖
KB_DIR = Path(__file__).parent / "knowledge"


# ── dispatch ──────────────────────────────────────────────────────────────────

_SERVICE_TOOLS = {
    "start_service": service_ops.start_service,
    "stop_service":  service_ops.stop_service,
    "check_service": service_ops.check_service,
}
_PURE_TOOLS = {
    "run_command":   verifier.run_command,
    "http_check":    verifier.http_check,
    "browser_check": verifier.browser_check,
}


def _do_search_kb(args: dict) -> str:
    _kb.KB_DIR = KB_DIR          # 运行时绑定，保持 search_kb 自身无全局依赖
    chunks = _kb.search_kb(args["query"], args.get("k", 5))
    if not chunks:
        return "[ok] no relevant chunks found"
    lines = []
    for i, c in enumerate(chunks, 1):
        lines.append(f"[{i}] {Path(c.source).stem} :: {c.heading} (score={c.score})\n{c.text[:600]}")
    return "\n\n".join(lines)


def execute_tool(name: str, args: dict, registry: dict) -> str:
    if name in _SERVICE_TOOLS:
        return _SERVICE_TOOLS[name](args, registry)
    if name == "list_services":
        return service_ops.list_services(registry)
    if name in _PURE_TOOLS:
        return _PURE_TOOLS[name](args)
    if name == "search_kb":
        return _do_search_kb(args)
    return f"[error] unknown tool: {name}"


# ── agent loop ────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
[verification policy]
Use the verification hierarchy:
  L0 check_service     -> only proves the process is alive (weak)
  L1 http_check GET    -> proves the page/route renders
  L2 http_check POST   -> proves the API logic works
  L3 browser_check     -> proves end-to-end user interaction
Pass expect_contains with concrete keywords. If a check returns [fail], diagnose and fix.

[port discipline]
Always pass `port` to start_service.
Before http_check / browser_check, call list_services to confirm the port.
Never hardcode a port from memory.

[knowledge base]
Use search_kb to look up domain knowledge, methodology, or past context before answering.

[done criteria]
1. start_service returned [ok] with a declared port
2. http_check on homepage returned [ok]
3. browser_check executed a real user flow and returned [ok]
4. stop_service called for every service started
"""


def run_agent(user_task: str, max_iterations: int = 50) -> list:
    registry: dict = {}
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user",   "content": user_task},
    ]

    try:
        for _ in range(max_iterations):
            response = client.chat.completions.create(
                model=MODEL_ID,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
            )
            msg = response.choices[0].message
            messages.append(msg)

            if not msg.tool_calls:
                print(f"[DONE] {msg.content}")
                break

            for tc in msg.tool_calls:
                name = tc.function.name
                args = json.loads(tc.function.arguments)
                print(f"[TOOL] {name}({args})")
                out = execute_tool(name, args, registry)
                print(f"[RESULT] {out[:300]}")
                messages.append({"tool_call_id": tc.id, "role": "tool",
                                 "name": name, "content": out})
    finally:
        service_ops.cleanup(registry)

    return messages


# ── entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    task = "做一个可以互动的网页，不调用额外的需要联网的api"
    msgs = run_agent(task)
    out_file = f"run_{int(time.time())}.json"
    with open(out_file, "w") as f:
        json.dump(
            [m if isinstance(m, dict) else m.model_dump() for m in msgs],
            f, indent=2, ensure_ascii=False, default=str,
        )
    print(f"[saved] {out_file}")