import json
import os
import re
import shutil
import sqlite3
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from extractors.base import BaseExtractor


class RikkaExtractor(BaseExtractor):
    name = "rikka"

    def __init__(self, upload_dir: Optional[str] = None):
        self.upload_dir = upload_dir

    def extract(self, input_path: str, output_dir: str):
        if not os.path.exists(input_path):
            raise FileNotFoundError(f"找不到数据库文件: {input_path}")

        self._setup_images(output_dir)

        conn = sqlite3.connect(input_path)
        cursor = conn.cursor()

        sessions: List[Dict[str, Any]] = []

        try:
            cursor.execute("SELECT id, title, create_at FROM ConversationEntity")
            conversations = cursor.fetchall()
        except Exception as e:
            conn.close()
            raise RuntimeError(f"读取 ConversationEntity 失败: {e}")

        for conv in conversations:
            try:
                session = self._parse_conversation(cursor, conv)
                if session and session.get("messages"):
                    sessions.append(session)
            except Exception as e:
                conv_id = str(conv[0]) if conv and len(conv) > 0 else "<unknown>"
                print(f"[RikkaExtractor] 跳过会话 {conv_id}，原因: {e}")

        conn.close()

        sessions.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        return sessions

    # =========================
    # Images
    # =========================
    def _setup_images(self, output_dir: str) -> None:
        if not self.upload_dir:
            return

        if not os.path.exists(self.upload_dir):
            print(f"⚠️ Rikka upload 目录不存在，跳过图片复制：{self.upload_dir}")
            return

        image_output_dir = os.path.join(output_dir, "images", "rikka")
        os.makedirs(image_output_dir, exist_ok=True)

        count = 0
        for filename in os.listdir(self.upload_dir):
            src_path = os.path.join(self.upload_dir, filename)
            if not os.path.isfile(src_path):
                continue

            dst_name = filename if "." in filename else f"{filename}.png"
            dst_path = os.path.join(image_output_dir, dst_name)

            if not os.path.exists(dst_path):
                shutil.copy2(src_path, dst_path)
            count += 1

        if count > 0:
            print(f"🖼️ Rikka 图片已准备完成：{count} 个文件 -> {image_output_dir}")

    # =========================
    # Session
    # =========================
    def _parse_conversation(self, cursor, conv_row) -> Optional[Dict[str, Any]]:
        conv_id, title, create_at = conv_row
        source_session_id = self._safe_str(conv_id)
        session_title = self._safe_str(title) or "无标题对话"

        cursor.execute(
            "SELECT messages FROM message_node WHERE conversation_id = ? ORDER BY node_index ASC",
            (conv_id,)
        )
        nodes = cursor.fetchall()

        if not nodes:
            return None

        processed_messages: List[Dict[str, Any]] = []

        for node in nodes:
            if not node or not node[0]:
                continue

            raw_json_str = node[0]

            try:
                msg_list = json.loads(raw_json_str)
            except Exception:
                continue

            if not isinstance(msg_list, list):
                continue

            for idx, msg in enumerate(msg_list):
                if not isinstance(msg, dict):
                    continue

                parsed = self._parse_message(msg, idx)
                if parsed:
                    processed_messages.append(parsed)

        if not processed_messages:
            return None

        session_ts = self._normalize_timestamp_ms(create_at)
        if session_ts == 0:
            session_ts = processed_messages[0].get("timestamp", 0) or int(time.time() * 1000)

        created_at_str = self._format_time(session_ts)
        updated_ts = processed_messages[-1].get("timestamp", session_ts) or session_ts
        updated_at = self._format_time(updated_ts)

        return {
            "id": f"rikka_{source_session_id}",
            "title": session_title,
            "source": "Rikka",
            "sourceSessionId": source_session_id,
            "timestamp": session_ts,
            "createdAt": created_at_str,
            "updatedAt": updated_at,
            "messages": processed_messages,
            "meta": {
                "platform": "Rikka",
                "messageCount": len(processed_messages),
            }
        }

    # =========================
    # Message
    # =========================
    def _parse_message(self, msg: Dict[str, Any], index: int) -> Optional[Dict[str, Any]]:
        raw_role = self._safe_str(msg.get("role")).lower()
        role = self._normalize_role(raw_role)

        if role == "system":
            return None

        model = self._extract_model(msg)
        display_role = self._build_display_role(role, model)

        content = self._extract_text_content(msg).strip()
        images = self._extract_images(msg)

        if not content and not images:
            return None

        raw_ts = msg.get("createdAt")
        if raw_ts is None or raw_ts == "":
            raw_ts = msg.get("updatedAt")
        if raw_ts is None or raw_ts == "":
            raw_ts = msg.get("createAt")

        ts = self._normalize_timestamp_ms(raw_ts)
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
            "content": content,
            "reasoning": "",
            "timestamp": ts,
            "time": time_str,
            "images": images
        }

    # =========================
    # Content / model / images
    # =========================
    def _extract_text_content(self, msg: Dict[str, Any]) -> str:
        buffer: List[str] = []

        parts = msg.get("parts")
        if isinstance(parts, list):
            for part in parts:
                if not isinstance(part, dict):
                    continue

                text = self._safe_str(part.get("text"))
                if text:
                    buffer.append(text)

                # 兼容部分结构：{"type":"text","content":"..."}
                if not text and self._safe_str(part.get("type")).lower() == "text":
                    fallback = self._safe_str(part.get("content"))
                    if fallback:
                        buffer.append(fallback)

        if buffer:
            return "".join(buffer).strip()

        content = msg.get("content")
        if isinstance(content, str):
            return content.strip()

        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    item_type = self._safe_str(item.get("type")).lower()
                    if item_type == "text":
                        text = self._safe_str(item.get("text"))
                        if text:
                            buffer.append(text)

                        fallback = self._safe_str(item.get("content"))
                        if fallback:
                            buffer.append(fallback)
                elif isinstance(item, str):
                    buffer.append(item)

        if buffer:
            return "".join(buffer).strip()

        return ""

    def _extract_model(self, msg: Dict[str, Any]) -> Optional[str]:
        candidates = [
            msg.get("modelId"),
            msg.get("model"),
            msg.get("modelName"),
        ]

        for item in candidates:
            if isinstance(item, dict):
                for key in ("name", "id", "slug"):
                    value = self._safe_str(item.get(key))
                    if value:
                        return value
            else:
                value = self._safe_str(item)
                if value:
                    return value

        return None

    def _extract_images(self, msg: Dict[str, Any]) -> List[str]:
        images: List[str] = []

        # 保留你原来最有效的做法：全文搜索 upload/代号
        try:
            msg_dump = json.dumps(msg, ensure_ascii=False)
        except Exception:
            msg_dump = str(msg)

        upload_matches = re.findall(r'upload[/\\]([a-zA-Z0-9\-_\.]+)', msg_dump)
        for match in upload_matches:
            filename = match
            if "." not in filename:
                filename = f"{filename}.png"
            images.append(f"images/rikka/{filename}")

        # 顺手兼容 content 里的 markdown 图片
        text_content = self._extract_text_content(msg)
        if text_content:
            md_matches = re.findall(r'!\[.*?\]\((.*?)\)', text_content)
            for raw_url in md_matches:
                url = self._safe_str(raw_url)
                if not url:
                    continue

                if url.startswith("data:image"):
                    images.append(url)
                    continue

                if url.startswith("http://") or url.startswith("https://"):
                    images.append(url)
                    continue

                normalized = url.replace("\\", "/")
                filename = os.path.basename(normalized.split("?")[0]).strip()
                if filename:
                    if "." not in filename:
                        filename = f"{filename}.png"
                    images.append(f"images/rikka/{filename}")

        return self._dedupe_keep_order(images)

    # =========================
    # Helpers
    # =========================
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