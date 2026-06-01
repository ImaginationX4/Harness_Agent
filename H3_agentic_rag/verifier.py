"""verifier.py — 无状态验证工具。不依赖 service_registry。"""
from __future__ import annotations
import subprocess


def run_command(tool_input: dict) -> str:
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


def http_check(tool_input: dict) -> str:
    try:
        import requests
    except ImportError:
        return "[error] requests not installed. Run: pip install requests"

    method = tool_input.get("method", "GET").upper()
    url = tool_input["url"]
    json_body = tool_input.get("json_body")
    expect = tool_input.get("expect_contains") or []

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
    tag = "[ok]" if r.ok and all_hit else "[fail]"

    parts = [f"{tag} {method} {url} -> HTTP {r.status_code}"]
    if hits:
        parts.append(f"keyword hits: {hits}")
    parts.append(f"body (first 2000 chars):\n{body[:2000]}")
    return "\n".join(parts)


def browser_check(tool_input: dict) -> str:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return "[error] playwright not installed. Run: pip install playwright && playwright install chromium"

    url = tool_input["url"]
    actions = tool_input.get("actions") or []
    expect = tool_input.get("expect_contains") or []

    logs: list[str] = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_context().new_page()

            console_msgs: list[str] = []
            page.on("console", lambda m: console_msgs.append(f"{m.type}: {m.text}"))
            page.on("pageerror", lambda e: console_msgs.append(f"PAGEERROR: {e}"))

            failed_responses: list[dict] = []

            def on_response(resp):
                if resp.status >= 400:
                    try:
                        preview = resp.text()[:500]
                    except Exception:
                        preview = "(body unreadable)"
                    failed_responses.append({"url": resp.url, "status": resp.status,
                                             "method": resp.request.method, "body_preview": preview})

            def on_requestfailed(req):
                failed_responses.append({"url": req.url, "status": "NETWORK_FAILED",
                                         "method": req.method, "body_preview": req.failure or ""})

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
                    logs.append(f"[skip] unknown action: {t}")

            visible = page.inner_text("body")
            browser.close()
    except Exception as e:
        return f"[error] browser_check failed: {type(e).__name__}: {e}\nlogs: {logs}"

    hits = {kw: (kw in visible) for kw in expect}
    all_hit = all(hits.values()) if hits else True
    tag = "[ok]" if all_hit and not failed_responses else "[fail]"

    parts = [f"{tag} browser_check on {url}",
             "actions:\n  " + "\n  ".join(logs)]
    if hits:
        parts.append(f"keyword hits: {hits}")
    if failed_responses:
        lines = ["FAILED NETWORK REQUESTS:"]
        for fr in failed_responses[-10:]:
            lines.append(f"  [{fr['method']} {fr['status']}] {fr['url']}\n    {fr['body_preview'][:300]}")
        parts.append("\n".join(lines))
    if console_msgs:
        parts.append("console (last 15):\n  " + "\n  ".join(console_msgs[-15:]))
    parts.append(f"final visible text (first 3000 chars):\n{visible[:3000]}")
    return "\n".join(parts)