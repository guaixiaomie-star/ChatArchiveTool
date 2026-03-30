from __future__ import annotations

import os
import re
import json
import time
import shutil
from datetime import datetime, timedelta
from typing import Any, List, Optional, Tuple


def safe_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return str(value)


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def format_ts_ms(ts_ms: int) -> str:
    if not ts_ms:
        return ""
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts_ms / 1000))


def normalize_timestamp(raw_ts: Any) -> Tuple[int, str]:
    """
    输入可能是：
    - None
    - 秒级/毫秒级 int float
    - 数字字符串
    - ISO 时间字符串
    """
    if raw_ts in (None, "", 0):
        return 0, ""

    if isinstance(raw_ts, (int, float)):
        ts = float(raw_ts)
        if ts < 1e11:
            ts *= 1000
        ts = int(ts)
        return ts, format_ts_ms(ts)

    if isinstance(raw_ts, str):
        s = raw_ts.strip()
        if not s:
            return 0, ""

        # 数字字符串
        try:
            val = float(s)
            if val < 1e11:
                val *= 1000
            ts = int(val)
            return ts, format_ts_ms(ts)
        except Exception:
            pass

        # ISO 风格
        iso_try = s.replace("Z", "")
        iso_try = iso_try[:19]
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                dt = datetime.strptime(iso_try, fmt)
                # 这里保持本地时间语义
                ts = int(dt.timestamp() * 1000)
                return ts, format_ts_ms(ts)
            except Exception:
                continue

    return 0, ""


def first_non_empty(*values: Any) -> str:
    for v in values:
        sv = safe_str(v).strip()
        if sv:
            return sv
    return ""


def clean_text(text: Any) -> str:
    s = safe_str(text)
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    return s.strip()


def normalize_model_name(model: Any) -> Optional[str]:
    model_str = clean_text(model)
    return model_str or None


def display_name_from_model(model: Optional[str], role: str) -> str:
    if role == "user":
        return "我"
    if role == "system":
        return "system"
    if role == "tool":
        return "tool"
    if not model:
        return "AI"
    return model.replace("-", " ")


def normalize_image_ref(
    raw: Any,
    image_dir: Optional[str] = None,
    default_ext: Optional[str] = None
) -> Optional[str]:
    if not raw:
        return None

    if isinstance(raw, dict):
        raw = raw.get("url") or raw.get("image_url") or raw.get("imageUrl") or raw.get("src")

    if not isinstance(raw, str):
        return None

    value = raw.strip()
    if not value:
        return None

    if value.startswith("data:image"):
        return value

    if value.startswith("http://") or value.startswith("https://"):
        return value

    normalized = value.replace("\\", "/")
    filename = os.path.basename(normalized.split("?")[0])

    if not filename:
        return None

    if "." not in filename and default_ext:
        filename = f"{filename}.{default_ext.lstrip('.')}"

    if image_dir:
        return f"{image_dir}/{filename}"
    return filename


def merge_text_parts(parts: List[str], joiner: str = "\n") -> str:
    cleaned = [clean_text(p) for p in parts if clean_text(p)]
    return joiner.join(cleaned).strip()


def copy_file_if_needed(src_path: str, dst_path: str) -> bool:
    if not os.path.isfile(src_path):
        return False
    ensure_dir(os.path.dirname(dst_path))
    if not os.path.exists(dst_path):
        shutil.copy2(src_path, dst_path)
    return True


def detect_upload_refs(text: str) -> List[str]:
    if not text:
        return []
    return re.findall(r'upload[/\\]([a-zA-Z0-9\-_\.]+)', text)


def remove_markdown_images(text: str) -> Tuple[str, List[str]]:
    if not text:
        return "", []

    found: List[str] = []

    def _repl(match: re.Match) -> str:
        found.append(match.group(1))
        return ""

    new_text = re.sub(r'!\[.*?\]\((.*?)\)', _repl, text)
    return new_text.strip(), found