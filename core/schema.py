from __future__ import annotations

from typing import Any, Dict, List, Optional


def build_message(
    msg_id: str,
    role: str,
    content: str = "",
    display_role: Optional[str] = None,
    model: Optional[str] = None,
    reasoning: str = "",
    timestamp: int = 0,
    time_str: str = "",
    images: Optional[List[str]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "id": msg_id,
        "role": role,  # user / assistant / system / tool
        "displayRole": display_role or ("我" if role == "user" else "AI"),
        "model": model,
        "content": content or "",
        "reasoning": reasoning or "",
        "timestamp": int(timestamp or 0),
        "time": time_str or "",
        "images": images or [],
        "extra": extra or {},
    }


def build_session(
    session_id: str,
    title: str,
    source: str,
    source_session_id: str,
    timestamp: int,
    created_at: str,
    updated_at: str,
    messages: List[Dict[str, Any]],
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "id": session_id,
        "title": title or "未命名对话",
        "source": source,
        "sourceSessionId": source_session_id,
        "timestamp": int(timestamp or 0),
        "createdAt": created_at or "",
        "updatedAt": updated_at or "",
        "messages": messages,
        "meta": {
            "messageCount": len(messages),
            **(extra or {})
        }
    }


def build_archive(sessions: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "version": "2.0",
        "sessions": sorted(sessions, key=lambda x: x.get("timestamp", 0), reverse=True),
    }