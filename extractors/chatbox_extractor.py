import json
import os
import time
from typing import Any, Dict, List, Optional

from extractors.base import BaseExtractor


class ChatboxExtractor(BaseExtractor):
    name = "chatbox"

    def extract(self, input_path: str, output_dir: str):
        if not os.path.exists(input_path):
            raise FileNotFoundError(f"找不到输入文件: {input_path}")

        with open(input_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            raise ValueError("Chatbox 导出文件格式不正确：顶层应为 dict")

        sessions_list = data.get("chat-sessions-list", [])
        id_to_title = self._build_title_map(sessions_list)

        sessions: List[Dict[str, Any]] = []

        for key, value in data.items():
            if not isinstance(key, str) or not key.startswith("session:"):
                continue
            if not isinstance(value, dict):
                continue

            try:
                session = self._parse_session(key, value, id_to_title)
                if session and session.get("messages"):
                    sessions.append(session)
            except Exception as e:
                print(f"[ChatboxExtractor] 跳过会话 {key}，原因: {e}")

        sessions.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        return sessions

    # =========================
    # Session
    # =========================
    def _parse_session(
        self,
        key: str,
        value: Dict[str, Any],
        id_to_title: Dict[str, str]
    ) -> Optional[Dict[str, Any]]:
        session_id = key.split("session:", 1)[1].strip()
        title = id_to_title.get(session_id, "未命名存档")

        raw_messages = value.get("messages", [])
        if not isinstance(raw_messages, list) or not raw_messages:
            return None

        processed_messages: List[Dict[str, Any]] = []

        for idx, msg in enumerate(raw_messages):
            if not isinstance(msg, dict):
                continue

            parsed = self._parse_message(msg, idx)
            if parsed:
                processed_messages.append(parsed)

        if not processed_messages:
            return None

        session_ts = processed_messages[0].get("timestamp", 0) or int(time.time() * 1000)
        created_at = self._format_time(session_ts)
        updated_ts = processed_messages[-1].get("timestamp", session_ts) or session_ts
        updated_at = self._format_time(updated_ts)

        return {
            "id": f"chatbox_{session_id}",
            "title": title,
            "source": "Chatbox",
            "sourceSessionId": session_id,
            "timestamp": session_ts,
            "createdAt": created_at,
            "updatedAt": updated_at,
            "messages": processed_messages,
            "meta": {
                "platform": "Chatbox",
                "messageCount": len(processed_messages),
            }
        }

    def _build_title_map(self, sessions_list: Any) -> Dict[str, str]:
        result: Dict[str, str] = {}
        if not isinstance(sessions_list, list):
            return result

        for item in sessions_list:
            if not isinstance(item, dict):
                continue
            sid = self._safe_str(item.get("id"))
            name = self._safe_str(item.get("name")) or "无标题对话"
            if sid:
                result[sid] = name
        return result

    # =========================
    # Message
    # =========================
    def _parse_message(self, msg: Dict[str, Any], index: int) -> Optional[Dict[str, Any]]:
        raw_role = self._safe_str(msg.get("role")).lower()
        role = self._normalize_role(raw_role)

        # system 先跳过，通用版暂不保留
        if role == "system":
            return None

        content_parts = msg.get("contentParts", [])
        if not isinstance(content_parts, list):
            content_parts = []

        content_fragments: List[str] = []
        images: List[str] = []

        for part in content_parts:
            if not isinstance(part, dict):
                continue

            part_type = self._safe_str(part.get("type")).lower()

            if part_type == "text":
                text = self._safe_str(part.get("text"))
                if text:
                    content_fragments.append(text)
                continue

            if part_type == "image_url":
                image_url = self._extract_image_from_part(part)
                if image_url:
                    images.append(image_url)
                continue

            # 兜底：有些结构可能直接带 text/imageUrl
            fallback_text = self._safe_str(part.get("text"))
            if fallback_text:
                content_fragments.append(fallback_text)

            fallback_image = self._extract_image_from_part(part)
            if fallback_image:
                images.append(fallback_image)

        content_text = "".join(content_fragments).strip()
        images = self._dedupe_keep_order(images)

        if not content_text and not images:
            return None

        model = self._safe_str(msg.get("model")) or None
        display_role = self._build_display_role(role, model)

        ts = self._normalize_timestamp_ms(msg.get("timestamp"))
        if ts == 0:
            ts = int(time.time() * 1000)

        time_str = self._format_time(ts)

        msg_id = (
            self._safe_str(msg.get("id"))
            or self._safe_str(msg.get("messageId"))
            or f"msg_{index + 1}"
        )

        return {
            "id": msg_id,
            "role": role,
            "displayRole": display_role,
            "model": model,
            "content": content_text,
            "reasoning": "",
            "timestamp": ts,
            "time": time_str,
            "images": images
        }

    # =========================
    # Helpers
    # =========================
    def _extract_image_from_part(self, part: Dict[str, Any]) -> str:
        img_data = part.get("imageUrl")
        if img_data is None:
            img_data = part.get("image_url")

        image_url = ""

        if isinstance(img_data, str):
            image_url = img_data.strip()
        elif isinstance(img_data, dict):
            image_url = self._safe_str(img_data.get("url"))

        if not image_url:
            return ""

        # base64 或 http/https 直接保留
        if image_url.startswith("data:image"):
            return image_url
        if image_url.startswith("http://") or image_url.startswith("https://"):
            return image_url

        # 本地路径统一映射到 images/chatbox/
        normalized = image_url.replace("\\", "/")
        filename = os.path.basename(normalized.split("?")[0]).strip()
        if filename:
            return f"images/chatbox/{filename}"

        return ""

    def _normalize_role(self, raw_role: str) -> str:
        raw_role = (raw_role or "").strip().lower()

        if raw_role in {"user", "assistant", "system", "tool"}:
            return raw_role

        if raw_role == "human":
            return "user"
        if raw_role == "ai":
            return "assistant"

        return "assistant" if raw_role else "assistant"

    def _build_display_role(self, role: str, model: Optional[str]) -> str:
        if role == "user":
            return "我"
        if role == "system":
            return "system"
        if role == "tool":
            return "tool"
        if model:
            return model
        return "AI"

    def _normalize_timestamp_ms(self, ts: Any) -> int:
        if ts is None or ts == "":
            return 0

        if isinstance(ts, (int, float)):
            val = float(ts)
            if val <= 0:
                return 0
            if val < 1e11:
                val *= 1000
            return int(val)

        if isinstance(ts, str):
            raw = ts.strip()
            if not raw:
                return 0
            try:
                val = float(raw)
                if val <= 0:
                    return 0
                if val < 1e11:
                    val *= 1000
                return int(val)
            except Exception:
                return 0

        return 0

    def _format_time(self, timestamp_ms: int) -> str:
        if not timestamp_ms:
            return ""
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(timestamp_ms / 1000))

    def _safe_str(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        return str(value).strip()

    def _dedupe_keep_order(self, items: List[str]) -> List[str]:
        seen = set()
        result: List[str] = []
        for item in items:
            if not item:
                continue
            if item in seen:
                continue
            seen.add(item)
            result.append(item)
        return result