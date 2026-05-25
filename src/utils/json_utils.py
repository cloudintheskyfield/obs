"""
统一的 JSON 加载工具 — 基于 json_repair 实现脏 JSON 容错解析。

所有业务代码应通过此模块加载 JSON，而不是直接调用 json.loads / json.load，
以确保遇到缺少花括号、引号、尾逗号、截断等格式问题时仍能解析出有效结果，
而不是直接抛出 JSONDecodeError。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, IO, Optional, Union

from loguru import logger

try:
    from json_repair import repair_json
    _HAS_JSON_REPAIR = True
except ImportError:  # 降级兜底
    _HAS_JSON_REPAIR = False
    logger.warning("json_repair not installed; falling back to stdlib json.loads (no dirty-JSON tolerance)")


def _repair(text: str) -> str:
    """若 json_repair 可用则修复，否则原样返回。"""
    if _HAS_JSON_REPAIR:
        return repair_json(text, return_objects=False, ensure_ascii=False)  # type: ignore[call-arg]
    return text


def safe_loads(text: str, *, default: Any = None, label: str = "") -> Any:
    """
    解析 JSON 字符串，容错脏 JSON。

    Args:
        text:    待解析字符串
        default: 解析彻底失败时的返回值（默认 None）
        label:   日志标注，方便定位来源（可选）

    Returns:
        解析后的 Python 对象，失败时返回 default。
    """
    if not text or not text.strip():
        return default

    # 1) 先尝试原始 stdlib 解析（最快且无副作用）
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2) 用 json_repair 修复后再解析
    try:
        repaired = _repair(text)
        result = json.loads(repaired)
        tag = f"[{label}] " if label else ""
        logger.debug(f"{tag}Dirty JSON repaired and parsed successfully.")
        return result
    except Exception as exc:
        tag = f"[{label}] " if label else ""
        logger.warning(f"{tag}JSON parse failed even after repair: {exc} | raw[:200]={text[:200]!r}")
        return default


def safe_load(fp: IO[str], *, default: Any = None, label: str = "") -> Any:
    """
    从文件对象读取并解析 JSON，容错脏 JSON。
    """
    try:
        return safe_loads(fp.read(), default=default, label=label or getattr(fp, "name", ""))
    except Exception as exc:
        logger.warning(f"[{label}] Failed to read from file object: {exc}")
        return default


def safe_load_path(path: Union[str, Path], *, default: Any = None, encoding: str = "utf-8") -> Any:
    """
    从文件路径读取并解析 JSON，容错脏 JSON。
    """
    p = Path(path)
    label = str(p)
    try:
        text = p.read_text(encoding=encoding)
        return safe_loads(text, default=default, label=label)
    except FileNotFoundError:
        logger.debug(f"[{label}] File not found, returning default.")
        return default
    except Exception as exc:
        logger.warning(f"[{label}] Failed to read file: {exc}")
        return default


def safe_loads_first_json(text: str, *, default: Any = None, label: str = "") -> Any:
    """
    从包含大段文本的字符串中提取第一个 JSON 对象/数组，支持脏 JSON。
    适用于 LLM 输出中夹杂着说明文字的情况。
    """
    if not text:
        return default

    import re
    # 先尝试直接解析整段
    result = safe_loads(text, default=_SENTINEL, label=label)
    if result is not _SENTINEL:
        return result

    # 尝试找第一个 { 或 [ 开始的块
    for start_char, end_char in [('{', '}'), ('[', ']')]:
        idx = text.find(start_char)
        if idx == -1:
            continue
        # 找最后一个对应的 end_char
        ridx = text.rfind(end_char)
        if ridx == -1 or ridx <= idx:
            continue
        candidate = text[idx:ridx + 1]
        result = safe_loads(candidate, default=_SENTINEL, label=label)
        if result is not _SENTINEL:
            return result

    logger.warning(f"[{label}] Could not extract any JSON from text[:200]={text[:200]!r}")
    return default


_SENTINEL = object()
