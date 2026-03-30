import json
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from extractors.base import BaseExtractor


class OpenAIWebExtractor(BaseExtractor):
    name = "openai_web"

    def extract(self, input_path: str, output_dir: str):
        if not os.path.exists(input_path):
            raise FileNotFoundError(f"找不到输入文件: {input_path}")

        with open(input_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, list):
            raise ValueError("OpenAI 官网导出文件格式不正确：顶层应为 list")

        sessions: List[Dict[str, Any]] = []

        for conv in data:
            try:
                session = self._parse_conversation(conv, output_dir)
                if session and session.get("messages"):
                    sessions.append(session)
            except Exception as e:
                print(f"[OpenAIWebExtractor] 跳过一条对话，原因: {e}")

        sessions.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        return sessions

    # =========================
    # Conversation
    # =========================
    def _parse_conversation(self, conv: Dict[str, Any], output_dir: str) -> Optional[Dict[str, Any]]:
        conv_id = self._safe_str(conv.get("id")) or self._safe_str(conv.get("conversation_id")) or self._make_fallback_id()
        title = self._safe_str(conv.get("title")) or "无标题对话"
        create_time = conv.get("create_time")
        update_time = conv.get("update_time") or create_time

        mapping = conv.get("mapping", {})
        current_node_id = conv.get("current_node")

        if not isinstance(mapping, dict) or not mapping:
            return None

        linear_messages = self._rebuild_linear_messages(mapping, current_node_id)
        if not linear_messages:
            return None

        processed_messages: List[Dict[str, Any]] = []
        pending_reasoning = ""

        for i, msg in enumerate(linear_messages):
            parsed = self._parse_message(msg, i, linear_messages, pending_reasoning)
            if not parsed:
                continue

            if parsed["kind"] == "reasoning_only":
                pending_reasoning = parsed["reasoning"]
                continue

            message_obj = parsed["message"]
            if pending_reasoning and message_obj["role"] == "assistant":
                if not message_obj.get("reasoning"):
                    message_obj["reasoning"] = pending_reasoning
                pending_reasoning = ""

            processed_messages.append(message_obj)

        if not processed_messages:
            return None

        session_ts = self._normalize_timestamp_ms(create_time)
        if session_ts == 0:
            session_ts = processed_messages[0].get("timestamp", 0) or int(time.time() * 1000)

        created_at = self._format_time(session_ts)
        updated_ts = self._normalize_timestamp_ms(update_time) or session_ts
        updated_at = self._format_time(updated_ts)

        return {
            "id": f"openai_{conv_id}",
            "title": title,
            "source": "OpenAI",
            "sourceSessionId": conv_id,
            "timestamp": session_ts,
            "createdAt": created_at,
            "updatedAt": updated_at,
            "messages": processed_messages,
            "meta": {
                "platform": "OpenAI",
                "messageCount": len(processed_messages),
            }
        }

    def _rebuild_linear_messages(self, mapping: Dict[str, Any], current_node_id: Optional[str]) -> List[Dict[str, Any]]:
        messages_reversed: List[Dict[str, Any]] = []
        visited = set()
        node_id = current_node_id

        while node_id:
            if node_id in visited:
                break
            visited.add(node_id)

            node = mapping.get(node_id)
            if not node:
                break

            message = node.get("message")
            if isinstance(message, dict):
                messages_reversed.append(message)

            node_id = node.get("parent")

        return list(reversed(messages_reversed))

    # =========================
    # Message
    # =========================
    def _parse_message(
        self,
        msg: Dict[str, Any],
        index: int,
        linear_messages: List[Dict[str, Any]],
        pending_reasoning: str
    ) -> Optional[Dict[str, Any]]:
        author = msg.get("author", {}) or {}
        raw_role = self._safe_str(author.get("role")).lower()

        if raw_role == "system":
            return None

        role = self._normalize_role(raw_role)

        metadata = msg.get("metadata", {}) or {}
        model = self._extract_model(metadata)
        display_role = self._build_display_role(role, model)

        content_text, reasoning_text, images = self._extract_content(msg)

        if not content_text and not reasoning_text and not images:
            return None

        msg_ts = self._normalize_timestamp_ms(msg.get("create_time"))
        if msg_ts == 0:
            msg_ts = int(time.time() * 1000)

        time_str = self._format_time(msg_ts)
        msg_id = self._safe_str(msg.get("id")) or f"msg_{index+1}"

        # 尝试兼容“思考过程单独一条，下一条才是正式回答”的场景
        if role == "assistant" and self._looks_like_reasoning_only(content_text, reasoning_text, images, linear_messages, index):
            return {
                "kind": "reasoning_only",
                "reasoning": reasoning_text or content_text or ""
            }

        message_obj = {
            "id": msg_id,
            "role": role,
            "displayRole": display_role,
            "model": model,
            "content": content_text or "",
            "reasoning": reasoning_text or "",
            "timestamp": msg_ts,
            "time": time_str,
            "images": images
        }

        return {
            "kind": "normal",
            "message": message_obj
        }

    # =========================
    # Content extraction
    # =========================
    def _extract_content(self, msg: Dict[str, Any]) -> Tuple[str, str, List[str]]:
        content = msg.get("content", {}) or {}
        parts = content.get("parts", []) or []

        content_fragments: List[str] = []
        reasoning_fragments: List[str] = []
        images: List[str] = []

        for part in parts:
            if isinstance(part, str):
                content_fragments.append(part)
                continue

            if not isinstance(part, dict):
                continue

            content_type = self._safe_str(part.get("content_type")).lower()

            # 1) 纯文本
            if content_type == "text":
                text = self._extract_text_from_part(part)
                if text:
                    content_fragments.append(text)
                continue

            # 2) 有些导出会把 reasoning / thinking 放在字段里
            if content_type in {"reasoning", "thinking"}:
                text = self._extract_text_from_part(part)
                if text:
                    reasoning_fragments.append(text)
                continue

            # 3) 图片 asset 指针
            if content_type == "image_asset_pointer":
                asset = self._safe_str(part.get("asset_pointer"))
                if asset:
                    file_id = asset.replace("file-service://", "").strip()
                    if file_id:
                        images.append(f"images/openai_web/{file_id}.png")
                continue

            # 4) 图片 URL
            if content_type == "image_url":
                img_url = self._extract_image_url(part.get("image_url"))
                if img_url:
                    images.append(img_url)
                continue

            # 5) 兜底：某些 part 里可能直接带 text
            fallback_text = self._extract_text_from_part(part)
            if fallback_text:
                content_fragments.append(fallback_text)

        # metadata 里再补捞一遍 reasoning
        metadata = msg.get("metadata", {}) or {}
        metadata_reasoning = self._extract_reasoning_from_metadata(metadata)
        if metadata_reasoning:
            reasoning_fragments.append(metadata_reasoning)

        # 去重、清洗
        content_text = self._clean_joined_text(content_fragments)
        reasoning_text = self._clean_joined_text(reasoning_fragments)
        images = self._dedupe_keep_order(images)

        return content_text, reasoning_text, images

    def _extract_text_from_part(self, part: Dict[str, Any]) -> str:
        # 常见结构 1: {"content_type":"text","parts":["xxx"]}
        parts_list = part.get("parts")
        if isinstance(parts_list, list):
            buffer = []
            for item in parts_list:
                if isinstance(item, str):
                    buffer.append(item)
                elif isinstance(item, dict):
                    maybe_text = self._safe_str(item.get("text"))
                    if maybe_text:
                        buffer.append(maybe_text)
            text = "\n".join([x for x in buffer if x.strip()])
            if text.strip():
                return text.strip()

        # 常见结构 2: {"text":"xxx"}
        direct_text = self._safe_str(part.get("text"))
        if direct_text:
            return direct_text.strip()

        # 常见结构 3: {"content":"xxx"}
        content_text = self._safe_str(part.get("content"))
        if content_text:
            return content_text.strip()

        return ""

    def _extract_reasoning_from_metadata(self, metadata: Dict[str, Any]) -> str:
        candidates = [
            metadata.get("reasoning"),
            metadata.get("thinking"),
            metadata.get("reasoning_content"),
            metadata.get("thoughts"),
        ]

        for item in candidates:
            if isinstance(item, str) and item.strip():
                return item.strip()
            if isinstance(item, list):
                texts = [str(x).strip() for x in item if str(x).strip()]
                if texts:
                    return "\n".join(texts)

        return ""

    def _extract_image_url(self, image_url_field: Any) -> str:
        if isinstance(image_url_field, str):
            return image_url_field.strip()

        if isinstance(image_url_field, dict):
            url = self._safe_str(image_url_field.get("url"))
            if url:
                return url

        return ""

    # =========================
    # Reasoning heuristic
    # =========================
    def _looks_like_reasoning_only(
        self,
        content_text: str,
        reasoning_text: str,
        images: List[str],
        linear_messages: List[Dict[str, Any]],
        index: int
    ) -> bool:
        if images:
            return False

        # 已经明确抽到了 reasoning，就优先视为 reasoning-only
        if reasoning_text and not content_text.strip():
            return True

        text = (content_text or "").strip()
        if not text:
            return False

        # 兼容旧版导出中“思考块”常见格式
        maybe_reasoning_prefix = [
            "分析：", "思路：", "推理：", "让我思考", "我来分析",
            "**分析", "**思路", "**推理", "Thought process", "Reasoning"
        ]
        looks_like_reasoning = any(text.startswith(p) for p in maybe_reasoning_prefix)

        if not looks_like_reasoning:
            return False

        # 向后看：如果下一个 assistant 很快又来一条，更像“思考块 + 正式回答”
        for k in range(index + 1, len(linear_messages)):
            next_msg = linear_messages[k]
            next_role = self._normalize_role(self._safe_str((next_msg.get("author", {}) or {}).get("role")).lower())
            if next_role == "assistant":
                return True
            if next_role == "user":
                return False

        return False

    # =========================
    # Helpers
    # =========================
    def _extract_model(self, metadata: Dict[str, Any]) -> Optional[str]:
        candidates = [
            metadata.get("model_slug"),
            metadata.get("default_model_slug"),
            metadata.get("model"),
        ]
        for item in candidates:
            model = self._safe_str(item)
            if model:
                return model
        return None

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

    def _normalize_role(self, role: str) -> str:
        role = (role or "").strip().lower()
        if role in {"user", "assistant", "system", "tool"}:
            return role
        if role == "critic":
            return "assistant"
        return "assistant" if role else "assistant"

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

            # 纯数字字符串
            if re.fullmatch(r"\d+(\.\d+)?", raw):
                val = float(raw)
                if val < 1e11:
                    val *= 1000
                return int(val)

            # ISO 时间简单兜底
            iso_try = raw.replace("Z", "+00:00")
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(iso_try)
                return int(dt.timestamp() * 1000)
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

    def _clean_joined_text(self, fragments: List[str]) -> str:
        cleaned = []
        for frag in fragments:
            text = self._safe_str(frag)
            if text:
                cleaned.append(text)
        return "\n".join(cleaned).strip()

    def _dedupe_keep_order(self, items: List[str]) -> List[str]:
        seen = set()
        result = []
        for item in items:
            if not item:
                continue
            if item in seen:
                continue
            seen.add(item)
            result.append(item)
        return result

    def _make_fallback_id(self) -> str:
        return f"conv_{int(time.time() * 1000)}"