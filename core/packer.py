from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List

from core.utils import ensure_dir


def pack_archive(sessions: List[Dict[str, Any]]) -> Dict[str, Any]:
    sessions = sessions or []
    sessions.sort(key=lambda x: x.get("timestamp", 0), reverse=True)

    total_message_count = 0
    sources = {}

    for session in sessions:
        msg_count = len(session.get("messages", []) or [])
        total_message_count += msg_count

        source = session.get("source") or "Unknown"
        sources[source] = sources.get(source, 0) + 1

    return {
        "version": "2.0",
        "exportedAt": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        "sessionCount": len(sessions),
        "messageCount": total_message_count,
        "sources": sources,
        "sessions": sessions,
    }


def save_archive(data: Dict[str, Any], output_dir: str, filename: str = "archive.json") -> str:
    ensure_dir(output_dir)
    out_path = os.path.join(output_dir, filename)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return out_path