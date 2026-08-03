"""Sanitize Strands stream_async events into JSON-safe UI trace events."""

from __future__ import annotations

import json
from typing import Any


def _truncate(val: Any, limit: int = 2500) -> Any:
    if val is None:
        return None
    if isinstance(val, (dict, list)):
        try:
            s = json.dumps(val, default=str)
        except Exception:
            s = str(val)
        if len(s) > limit:
            return s[:limit] + "…"
        return val
    s = str(val)
    return s if len(s) <= limit else s[:limit] + "…"


def _content_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                if "text" in block:
                    parts.append(str(block["text"]))
                elif "json" in block:
                    parts.append(json.dumps(block["json"], default=str))
                else:
                    parts.append(json.dumps(block, default=str)[:800])
            else:
                parts.append(str(block))
        return "\n".join(parts)
    return str(content)


def sanitize_event(event: Any) -> list[dict[str, Any]]:
    """Return zero or more UI events from one Strands stream event."""
    if not isinstance(event, dict):
        return []

    out: list[dict[str, Any]] = []

    # Avoid dumping non-serializable agent/span blobs from prepare()
    if "data" in event and isinstance(event.get("data"), str) and event["data"]:
        out.append({"type": "text", "content": event["data"]})

    reasoning = event.get("reasoningText")
    if reasoning:
        out.append({"type": "thinking", "content": str(reasoning)})

    tool = event.get("current_tool_use")
    if isinstance(tool, dict) and tool.get("name"):
        out.append(
            {
                "type": "tool",
                "status": "running",
                "name": tool.get("name"),
                "toolUseId": tool.get("toolUseId") or tool.get("id"),
                "input": _truncate(tool.get("input")),
            }
        )

    msg = event.get("message")
    if isinstance(msg, dict):
        for block in msg.get("content") or []:
            if not isinstance(block, dict):
                continue
            if "toolUse" in block:
                tu = block["toolUse"] or {}
                out.append(
                    {
                        "type": "tool",
                        "status": "running",
                        "name": tu.get("name"),
                        "toolUseId": tu.get("toolUseId"),
                        "input": _truncate(tu.get("input")),
                    }
                )
            if "toolResult" in block:
                tr = block["toolResult"] or {}
                out.append(
                    {
                        "type": "tool",
                        "status": "done",
                        "toolUseId": tr.get("toolUseId"),
                        "name": tr.get("name"),
                        "output": _truncate(_content_text(tr.get("content"))),
                    }
                )
            if "text" in block and block["text"]:
                # Avoid duplicating streamed assistant text; only keep tool messages.
                pass

    if "result" in event:
        result = event["result"]
        text = ""
        message = getattr(result, "message", None)
        if isinstance(message, dict):
            text = _content_text(message.get("content"))
        elif message is not None:
            text = _content_text(getattr(message, "content", None) or message)
        if not text:
            # Prefer message text over full AgentResult repr
            for attr in ("text", "content", "output"):
                val = getattr(result, attr, None)
                if isinstance(val, str) and val.strip():
                    text = val
                    break
        if not text:
            try:
                text = str(result)
            except Exception:
                text = ""
        # Drop noisy AgentResult repr wrappers if present
        if text.startswith("AgentResult("):
            text = ""
        out.append({"type": "result", "content": text})

    if event.get("force_stop"):
        out.append(
            {
                "type": "error",
                "content": str(event.get("force_stop_reason") or "force_stop"),
            }
        )

    return out


def dedupe_tool_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse noisy tool_use_stream deltas into meaningful updates."""
    last_sig: dict[str, str] = {}
    kept: list[dict[str, Any]] = []
    for ev in events:
        if ev.get("type") != "tool":
            kept.append(ev)
            continue
        tid = str(ev.get("toolUseId") or ev.get("name") or "")
        sig = f"{ev.get('status')}|{ev.get('name')}|{json.dumps(ev.get('input'), default=str)[:200]}|{str(ev.get('output'))[:80]}"
        if last_sig.get(tid) == sig:
            continue
        last_sig[tid] = sig
        kept.append(ev)
    return kept
