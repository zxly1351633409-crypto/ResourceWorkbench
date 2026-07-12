from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path

from .settings import deepseek_api_key


def request_card_suggestion(card: dict, settings: dict, timeout_seconds: int = 60, tier: str | None = None) -> dict:
    api_key = deepseek_api_key(settings)
    if not api_key:
        return {"ok": False, "error": "未设置 DeepSeek API Key 环境变量。"}

    base_url = str(settings.get("deepseek_base_url") or "https://api.deepseek.com").rstrip("/")
    model = selected_model(settings, tier)
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是资源整理助手。只根据给定文本信息提出保守建议，"
                    "不要编造图片地点、年代、真实尺度或文件中没有的信息。"
                ),
            },
            {
                "role": "user",
                "content": _card_prompt(card, settings),
            },
        ],
        "stream": False,
    }
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {"ok": False, "error": f"DeepSeek 请求失败：HTTP {exc.code} {body[-300:]}"}
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": f"DeepSeek 请求失败：{exc}"}

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return {"ok": False, "error": "DeepSeek 返回格式无法解析。", "raw": data}
    return {"ok": True, "content": content, "raw": data, "model": model}


def request_structured_card_suggestion(
    card: dict, settings: dict, timeout_seconds: int = 60, tier: str | None = None
) -> dict:
    """请求 DeepSeek 输出结构化 JSON 建议。

    成功时返回:
        {"ok": True, "suggestion": {...}, "content": <原始文本>, "raw": <完整响应>}
    其中 suggestion 含字段:
        translated_name, target_path, new_folder_needed,
        confidence, review_reason, tags(可选)
    """
    api_key = deepseek_api_key(settings)
    if not api_key:
        return {"ok": False, "error": "未设置 DeepSeek API Key 环境变量。"}

    base_url = str(settings.get("deepseek_base_url") or "https://api.deepseek.com").rstrip("/")
    model = selected_model(settings, tier)
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是资源整理助手。只根据给定文本信息提出保守建议，"
                    "不要编造图片地点、年代、真实尺度或文件中没有的信息。"
                    "必须只输出一个 JSON 对象，不要输出多余文字或解释。"
                ),
            },
            {
                "role": "user",
                "content": _structured_card_prompt(card, settings),
            },
        ],
        "stream": False,
        "response_format": {"type": "json_object"},
    }
    last_error = ""
    data = None
    for attempt in range(2):
        try:
            req = urllib.request.Request(
                f"{base_url}/chat/completions",
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            last_error = f"HTTP {exc.code} {body[-300:]}"
            # 某些部署不支持 response_format，去掉后重试一次
            if attempt == 0 and "response_format" in payload:
                payload.pop("response_format", None)
                continue
            return {"ok": False, "error": f"DeepSeek 请求失败：{last_error}"}
        except (OSError, json.JSONDecodeError) as exc:
            return {"ok": False, "error": f"DeepSeek 请求失败：{exc}"}
    if data is None:
        return {"ok": False, "error": f"DeepSeek 请求失败：{last_error}"}

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return {"ok": False, "error": "DeepSeek 返回格式无法解析。", "raw": data}

    parsed = parse_structured_suggestion(content)
    if not parsed.get("ok"):
        return {
            "ok": False,
            "error": parsed.get("error", "无法解析 DeepSeek JSON。"),
            "content": content,
            "raw": data,
        }
    return {"ok": True, "suggestion": parsed["suggestion"], "content": content, "raw": data, "model": model}


def parse_structured_suggestion(content: str) -> dict:
    """从模型文本中提取并规范化结构化建议 JSON。

    兼容三种情况：纯 JSON、代码块包裹、JSON 前后有少量解释文字。
    """
    raw = _extract_json_object(content)
    if raw is None:
        return {"ok": False, "error": "未在 DeepSeek 回复中找到 JSON 对象。"}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": f"DeepSeek JSON 解析失败：{exc}"}
    if not isinstance(data, dict):
        return {"ok": False, "error": "DeepSeek 返回的不是 JSON 对象。"}
    return {"ok": True, "suggestion": _normalize_suggestion(data)}


def _normalize_suggestion(data: dict) -> dict:
    def _first(*keys: str):
        for key in keys:
            if key in data and data[key] not in (None, ""):
                return data[key]
        return None

    confidence = _first("confidence", "置信度")
    if isinstance(confidence, (int, float)):
        confidence = "high" if confidence >= 0.75 else "medium" if confidence >= 0.4 else "low"
    elif isinstance(confidence, str):
        confidence = confidence.strip().lower() or None

    new_folder = _first("new_folder_needed", "needs_create_target", "新建目录")
    if isinstance(new_folder, str):
        new_folder = new_folder.strip().lower() in {"true", "yes", "1", "是", "需要"}
    else:
        new_folder = bool(new_folder)

    tags = _first("tags", "标签") or []
    if isinstance(tags, str):
        tags = [item.strip() for item in re.split(r"[,/、，;；]", tags) if item.strip()]
    elif isinstance(tags, list):
        tags = [str(item).strip() for item in tags if str(item).strip()]
    else:
        tags = []

    return {
        "translated_name": _as_text(_first("translated_name", "中文名", "name", "整理名")),
        "target_path": _as_text(_first("target_path", "目标分类", "目标路径", "target")),
        "new_folder_needed": new_folder,
        "confidence": confidence,
        "review_reason": _as_text(_first("review_reason", "不确定点", "理由", "reason")),
        "tags": tags,
    }


def _as_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return " / ".join(str(item) for item in value)
    return str(value).strip()


def _extract_json_object(content: str) -> str | None:
    if not content:
        return None
    text = content.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        return fence.group(1)
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def test_deepseek_connection(settings: dict, timeout_seconds: int = 20, tier: str | None = None) -> dict:
    api_key = deepseek_api_key(settings)
    if not api_key:
        return {"ok": False, "error": "未设置 DeepSeek API Key 环境变量。"}

    base_url = str(settings.get("deepseek_base_url") or "https://api.deepseek.com").rstrip("/")
    model = selected_model(settings, tier)
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "stream": False,
        "max_tokens": 8,
    }
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {"ok": False, "error": f"DeepSeek 验证失败：HTTP {exc.code} {body[-300:]}", "model": model}
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": f"DeepSeek 验证失败：{exc}", "model": model}
    return {"ok": True, "model": model, "raw": data}


def selected_model(settings: dict, tier: str | None = None) -> str:
    selected_tier = tier or str(settings.get("deepseek_default_tier") or "flash")
    if selected_tier == "pro":
        return str(settings.get("deepseek_pro_model") or "deepseek-v4-pro")
    return str(settings.get("deepseek_flash_model") or "deepseek-v4-flash")


def _selected_model(settings: dict, tier: str | None = None) -> str:
    return selected_model(settings, tier)


def _translation_mode_label(settings: dict) -> str:
    mode = str(settings.get("translation_name_mode") or "zh_en")
    labels = {
        "zh_en": "中文名 + 原英文名",
        "en_zh": "原英文名 + 中文名",
        "zh_only": "只有中文名",
        "en_only": "保留原英文名",
    }
    return labels.get(mode, labels["zh_en"])


def _structured_card_prompt(card: dict, settings: dict) -> str:
    samples = _prompt_samples(card)
    reasons = card.get("reasons") or []
    targets = card.get("target_path_hints") or []
    extensions = [str(item) for item in (card.get("top_extensions") or {})]
    batch_name = Path(str(card.get("batch_source_path") or "")).name
    return "\n".join(
        [
            "请审阅这张资源卡片，并只输出一个 JSON 对象，字段如下：",
            "{",
            '  "translated_name": "按下方命名格式给出的整理名",',
            '  "target_path": "从候选分类里选一个最稳妥的完整路径；候选都不合适时给出建议的完整子分类路径",',
            '  "new_folder_needed": true/false,',
            '  "confidence": "high|medium|low",',
            '  "review_reason": "需要人工确认的原因或不确定点；没有则留空字符串",',
            '  "tags": ["可选补充标签"]',
            "}",
            "约束：不要编造文件中没有的地点、年代或真实尺度；不确定就降低 confidence。",
            "",
            f"翻译命名格式：{_translation_mode_label(settings)}",
            f"名称：{card.get('name', '')}",
            f"类型建议：{card.get('suggested_type', '')}",
            f"当前置信度：{card.get('confidence', '')}",
            f"标签：{' / '.join(card.get('content_tags') or [])}",
            f"来源批次：{batch_name}",
            f"外层文件类型：{' / '.join(extensions[:15])}",
            f"候选分类：{'; '.join(str(item) for item in targets[:5])}",
            f"判断原因：{'; '.join(str(item) for item in reasons[:8])}",
            f"目录样例：{'; '.join(str(item) for item in samples[:20])}",
        ]
    )


def _card_prompt(card: dict, settings: dict) -> str:
    samples = _prompt_samples(card)
    reasons = card.get("reasons") or []
    targets = card.get("target_path_hints") or []
    extensions = [str(item) for item in (card.get("top_extensions") or {})]
    batch_name = Path(str(card.get("batch_source_path") or "")).name
    return "\n".join(
        [
            "请帮我审阅这张资源卡片，输出：",
            "1. 中文整理名建议；",
            "2. 是否需要深度解压分析；",
            "3. 从候选目标分类里选择一个最稳妥的；",
            "4. 不确定点。",
            "",
            f"翻译命名格式：{_translation_mode_label(settings)}",
            f"名称：{card.get('name', '')}",
            f"类型建议：{card.get('suggested_type', '')}",
            f"置信度：{card.get('confidence', '')}",
            f"标签：{' / '.join(card.get('content_tags') or [])}",
            f"来源批次：{batch_name}",
            f"外层文件类型：{' / '.join(extensions[:15])}",
            f"候选分类：{'; '.join(str(item) for item in targets[:5])}",
            f"判断原因：{'; '.join(str(item) for item in reasons[:8])}",
            f"目录样例：{'; '.join(str(item) for item in samples[:20])}",
        ]
    )


def _prompt_samples(card: dict) -> list[str]:
    items: list[str] = [str(item) for item in (card.get("archive_entry_samples") or []) if str(item).strip()]
    samples = card.get("samples") or {}
    if isinstance(samples, dict):
        for paths in samples.values():
            items.extend(str(item) for item in (paths or []) if str(item).strip())
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
        if len(result) >= 30:
            break
    return result
