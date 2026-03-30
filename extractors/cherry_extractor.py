import json
import os
import re
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from extractors.base import BaseExtractor


class CherryExtractor(BaseExtractor):
    name = "cherry"

    def extract(self, input_path: str, output_dir: str):
        if not os.path.exists(input_path):
            raise FileNotFoundError(f"找不到输入文件: {input_path}")

        with open(input_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            raise ValueError("Cherry Studio 导出文件格式不正确：顶层应为 dict")

        global_title_map = self._extract_global_title_map(data)
        content_map, image_map = self._extract_message_blocks(data)

        sessions: List[Dict[str, Any]] = []
        db = data.get("indexedDB", {}) or {}
        raw_topics = db.get("topics", [])

        if isinstance(raw_topics, dict):
            raw_topics = raw_topics.get("topics", list(raw_topics.values()))

        if not isinstance(raw_topics, list):
            raw_topics = []

        for topic in raw_topics:
            if not isinstance(topic, dict):
                continue

            try:
                session = self._parse_topic(topic, global_title_map, content_map, image_map)
                if session and session.get("messages"):
                    sessions.append(session)
            except Exception as e:
                topic_id = self._safe_str(topic.get("id"))
                print(f"[CherryExtractor] 跳过会话 {topic_id or '<unknown>'}，原因: {e}")

        sessions.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        return sessions

    # =========================
    # Session
    # =========================
    def _parse_topic(
        self,
        topic: Dict[str, Any],
        global_title_map: Dict[str, str],
        content_map: Dict[str, List[str]],
        image_map: Dict[str, List[str]]
    ) -> Optional[Dict[str, Any]]:
        topic_id = self._safe_str(topic.get("id")) or self._make_fallback_id()
        raw_messages = topic.get("messages", [])

        if not isinstance(raw_messages, list) or not raw_messages:
            return None

        processed_messages: List[Dict[str, Any]] = []

        for idx, msg in enumerate(raw_messages):
            if not isinstance(msg, dict):
                continue

            parsed = self._parse_message(msg, idx, content_map, image_map)
            if parsed:
                processed_messages.append(parsed)

        if not processed_messages:
            return None

        session_ts = processed_messages[0].get("timestamp", 0) or int(time.time() * 1000)
        created_at = self._format_time(session_ts)
        updated_ts = processed_messages[-1].get("timestamp", session_ts) or session_ts
        updated_at = self._format_time(updated_ts)

        title = (
            global_title_map.get(topic_id)
            or self._safe_str(topic.get("name"))
            or self._guess_title_from_messages(processed_messages)
            or "无标题对话"
        )

        return {
            "id": f"cherry_{topic_id}",
            "title": title,
            "source": "Cherry",
            "sourceSessionId": topic_id,
            "timestamp": session_ts,
            "createdAt": created_at,
            "updatedAt": updated_at,
            "messages": processed_messages,
            "meta": {
                "platform": "Cherry",
                "messageCount": len(processed_messages),
            }
        }

    # =========================
    # Message
    # =========================
    def _parse_message(
        self,
        msg: Dict[str, Any],
        index: int,
        content_map: Dict[str, List[str]],
        image_map: Dict[str, List[str]]
    ) -> Optional[Dict[str, Any]]:
        msg_id = (
            self._safe_str(msg.get("id"))
            or self._safe_str(msg.get("messageId"))
            or f"msg_{index + 1}"
        )

        raw_role = self._safe_str(msg.get("role")).lower()
        role = self._normalize_role(raw_role)

        if role == "system":
            return None

        model = self._extract_model(msg)
        display_role = self._build_display_role(role, model)

        text_parts = content_map.get(msg_id, [])
        final_content = "".join([self._safe_str(x) for x in text_parts if self._safe_str(x)]).strip()

        images = []
        for file_name in image_map.get(msg_id, []):
            if file_name:
                images.append(f"images/cherry/{file_name}")

        # 兼容 Markdown 图片
        markdown_images, cleaned_content = self._extract_markdown_images(final_content)
        if markdown_images:
            images.extend(markdown_images)
            final_content = cleaned_content

        images = self._dedupe_keep_order(images)

        if not final_content and not images:
            return None

        raw_ts = msg.get("createdAt")
        if raw_ts is None or raw_ts == "":
            raw_ts = msg.get("updateAt")
        if raw_ts is None or raw_ts == "":
            raw_ts = msg.get("updatedAt")

        ts = self._normalize_timestamp_ms(raw_ts)
        if ts == 0:
            ts = int(time.time() * 1000)

        time_str = self._format_time(ts)

        return {
            "id": msg_id,
            "role": role,
            "displayRole": display_role,
            "model": model,
            "content": final_content,
            "reasoning": "",
            "timestamp": ts,
            "time": time_str,
            "images": images
        }

    # =========================
    # Title / blocks
    # =========================
    def _extract_global_title_map(self, data: Dict[str, Any]) -> Dict[str, str]:
        result: Dict[str, str] = {}

        local_storage = data.get("localStorage", {}) or {}
        persist_str = local_storage.get("persist:cherry-studio")

        if not persist_str or not isinstance(persist_str, str):
            return result

        try:
            persist_data = json.loads(persist_str)
            assistants_str = persist_data.get("assistants")
            if not assistants_str:
                return result

            assistants_data = json.loads(assistants_str)
            ast_list = assistants_data.get("assistants", [])

            if not isinstance(ast_list, list):
                return result

            for ast in ast_list:
                if not isinstance(ast, dict):
                    continue

                topics = ast.get("topics", [])
                if not isinstance(topics, list):
                    continue

                for topic in topics:
                    if not isinstance(topic, dict):
                        continue
                    t_id = self._safe_str(topic.get("id"))
                    t_name = self._safe_str(topic.get("name"))
                    if t_id and t_name:
                        result[t_id] = t_name
        except Exception:
            pass

        return result

    def _extract_message_blocks(
        self,
        data: Dict[str, Any]
    ) -> (Dict[str, List[str]], Dict[str, List[str]]):
        db = data.get("indexedDB", {}) or {}
        raw_blocks = db.get("message_blocks", [])

        if isinstance(raw_blocks, dict):
            raw_blocks = raw_blocks.get("message_blocks", list(raw_blocks.values()))

        if not isinstance(raw_blocks, list):
            raw_blocks = []

        content_map: Dict[str, List[str]] = {}
        image_map: Dict[str, List[str]] = {}

        for block in raw_blocks:
            if not isinstance(block, dict):
                continue

            msg_id = self._safe_str(block.get("messageId"))
            if not msg_id:
                continue

            block_type = self._safe_str(block.get("type")).lower()

            # 文本块
            if block_type in {"main_text", "text"} or ("content" in block and block_type != "image"):
                text = self._safe_str(block.get("content"))
                if text:
                    content_map.setdefault(msg_id, []).append(text)

            # 图片块
            if block_type == "image" and isinstance(block.get("file"), dict):
                file_name = self._safe_str(block["file"].get("name"))
                if file_name:
                    image_map.setdefault(msg_id, []).append(file_name)

        return content_map, image_map

    # =========================
    # Markdown image parsing
    # =========================
    def _extract_markdown_images(self, text: str):
        if not text:
            return [], text

        matches = re.findall(r'!\[.*?\]\((.*?)\)', text)
        images: List[str] = []

        for raw_url in matches:
            url = self._safe_str(raw_url)
            if not url:
                continue

            if url.startswith("data:image"):
                images.append(url)
                continue

            normalized = url.replace("\\", "/")
            filename = os.path.basename(normalized.split("?")[0]).strip()
            if filename:
                images.append(f"images/cherry/{filename}")

        cleaned = re.sub(r'!\[.*?\]\((.*?)\)', '', text).strip()
        return images, cleaned

    # =========================
    # Helpers
    # =========================
    def _extract_model(self, msg: Dict[str, Any]) -> Optional[str]:
        model_id = self._safe_str(msg.get("modelId"))
        if model_id:
            return model_id

        model_field = msg.get("model")
        if isinstance(model_field, dict):
            model_name = self._safe_str(model_field.get("name"))
            if model_name:
                return model_name

            model_id2 = self._safe_str(model_field.get("id"))
            if model_id2:
                return model_id2

        model_str = self._safe_str(model_field)
        if model_str:
            return model_str

        return None

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

    def _normalize_timestamp_ms(self, raw_ts: Any) -> int:
        if raw_ts is None or raw_ts == "":
            return 0

        if isinstance(raw_ts, (int, float)):
            val = float(raw_ts)
            if val <= 0:
                return 0
            if val < 1e11:
                val *= 1000
            return int(val)

        if isinstance(raw_ts, str):
            raw = raw_ts.strip()
            if not raw:
                return 0

            # ISO 时间
            try:
                dt = datetime.strptime(raw[:19], "%Y-%m-%dT%H:%M:%S")
                if raw.endswith("Z"):
                    dt += timedelta(hours=8)
                return int(dt.timestamp() * 1000)
            except Exception:
                pass

            # 数字字符串
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

    def _guess_title_from_messages(self, messages: List[Dict[str, Any]]) -> str:
        for msg in messages:
            content = self._safe_str(msg.get("content"))
            if content:
                return content[:20]
        return ""

    def _make_fallback_id(self) -> str:
        return f"topic_{int(time.time() * 1000)}"