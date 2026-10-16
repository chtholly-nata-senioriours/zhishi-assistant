# -*- coding: utf-8 -*-
"""AI 核心层（L2）。

设计约束
    - **不得 import `presentation` / `extensions` / `native`**（依赖单向向上）。
    - 除 `session.py` 使用 `PySide6.QtCore`（QObject/Signal）外，
      **不得 import 任何 Qt 模块**。除 session 外全部是纯 Python，可脱离 Qt 单测。

「功能 = 输入源 × 预设 × 投递」中，本层负责「预设」与「推理」。

快速上手
    from engine.ai import build_from_config
    mgr = build_from_config(config_manager)
    mgr.chunk.connect(on_chunk)
    sid = mgr.ask("你好", get_preset("ask"))
"""
from __future__ import annotations

from typing import Optional

from .probe import ProbeResult, list_models, probe, probe_chat, suggest_models
from .prompt import BUILTIN_PRESETS, build_messages, build_system_prompt, get_preset, list_presets
from .provider import Provider, build_user_content
from .registry import available_providers, create_provider, register_provider
from .session import SessionManager, make_session_manager
from .store import Store, close_shared_store, default_db_path, shared_store
from .stream import extract_error, iter_openai_deltas, iter_sse_data
from .types import ChatMessage, DeliveryKind, Preset, ProviderError, SessionRecord

__all__ = [
    # 类型
    "ChatMessage", "Preset", "DeliveryKind", "ProviderError", "SessionRecord",
    # 预设
    "BUILTIN_PRESETS", "get_preset", "list_presets", "build_messages", "build_system_prompt",
    # Provider
    "Provider", "build_user_content", "register_provider", "create_provider",
    "available_providers",
    # 会话与存储
    "SessionManager", "make_session_manager", "Store", "default_db_path",
    "shared_store", "close_shared_store",
    # 连接探测
    "ProbeResult", "probe", "list_models", "probe_chat", "suggest_models",
    # SSE
    "iter_sse_data", "iter_openai_deltas", "extract_error",
    # 便捷
    "build_from_config", "resolve_api_key",
]


def build_from_config(config, store: Optional[Store] = None) -> SessionManager:
    """按配置节 `ai` 组装一个 SessionManager。

    Args:
        config: ConfigManager 实例（或其兼容对象，需有 get(key, default)）
        store: 可选的外部 Store；不传则按默认路径创建

    Returns:
        SessionManager（未配置 api_key 时也能构造，只是调用会报错）
    """
    provider_name = config.get("ai.provider", "openai_compat")
    base_url = config.get("ai.base_url", "")
    api_key = resolve_api_key(config)
    timeout = int(config.get("ai.request_timeout", 60) or 60)
    model = config.get("ai.model", "")
    vision_model = config.get("ai.vision_model", "") or ""

    provider = create_provider(
        provider_name,
        base_url=base_url,
        api_key=api_key,
        timeout=timeout,
    )
    return SessionManager(
        provider, model, store=store or Store(), vision_model=vision_model
    )


def resolve_api_key(config) -> str:
    """取 API Key：**系统密钥库优先**，明文配置只作老用户的回退。

    为什么这是全项目唯一读密钥的地方
        密钥的存放方式（密钥库 / 明文）只有这里知道。别处直接
        `config.get("ai.api_key")` 会把「已经迁到密钥库」的用户
        悄悄降级成明文读取 —— 界面显示已保存，实际取不到，最难查的那类。

    引用存在但取不到时怎么办
        返回空串，让上层报「没配 API Key」。**不要**在这里做别的兜底 ——
        悄悄换一把错的 key，比明确失败难查十倍。
    """
    from data.key_store import REF_PREFIX, load_key

    ref = str(config.get("ai.api_key_ref", "") or "")
    if ref.startswith(REF_PREFIX):
        value = load_key(ref)
        if value:
            return value
    return str(config.get("ai.api_key", "") or "")
