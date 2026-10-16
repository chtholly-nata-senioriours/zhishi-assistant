# -*- coding: utf-8 -*-
"""AI 核心层的数据类型（纯 Python，零 Qt 依赖）。

「功能 = 输入源 × 预设 × 投递」三元组里的两个维度在这里定义。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ChatMessage:
    """一条对话消息。"""

    role: str       # "system" | "user" | "assistant"
    content: str

    def to_dict(self) -> dict:
        return {"role": self.role, "content": self.content}


@dataclass
class Preset:
    """预设 —— 决定「怎么问」。"""

    id: str
    name: str
    system_prompt: str
    default_delivery: str = "panel"   # 见 DeliveryKind
    description: str = ""
    builtin: bool = True

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "system_prompt": self.system_prompt,
            "default_delivery": self.default_delivery,
            "description": self.description,
        }

    @classmethod
    def from_row(cls, row: dict) -> "Preset":
        return cls(
            id=row["id"],
            name=row["name"],
            system_prompt=row["system_prompt"],
            default_delivery=row.get("default_delivery", "panel"),
            description=row.get("description", ""),
            builtin=False,
        )


class DeliveryKind:
    """投递方式 —— 决定「答案送到哪」。

    REPLACE / PASTE 已于 2026-10-12 **从产品里移除**（见 `AGENTS.md` §4.6）。
    常量本身保留：数据库里的历史预设可能还存着这两个值，删掉会让读取报错。
    """

    PANEL = "panel"       # 面板显示
    COPY = "copy"         # 复制到剪贴板
    REPLACE = "replace"   # 【已移除】替换原文（覆盖选中区）
    PASTE = "paste"       # 【已移除】粘贴到前台
    TTS = "tts"           # 语音播报

    ALL = (PANEL, COPY, REPLACE, PASTE, TTS)
    #: 当前**可用**的投递方式（UI 只该提供这些）
    AVAILABLE = (PANEL, COPY, TTS)


@dataclass
class SessionRecord:
    """一次问答的落库结构。"""

    id: str
    preset_id: str
    title: str = ""
    messages: List[ChatMessage] = field(default_factory=list)
    created_at: float = 0.0
    image_path: Optional[str] = None


class ProviderError(RuntimeError):
    """Provider 调用失败（网络 / 鉴权 / 协议）。"""
