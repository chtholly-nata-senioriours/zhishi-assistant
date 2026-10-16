# -*- coding: utf-8 -*-
"""Provider 抽象（纯 Python，零 Qt 依赖）。

新增一家模型服务 = 实现一个 `stream()` + 在 registry 注册。
调用方（SessionManager）只认这个接口，不认具体厂商。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterator, List, Optional

from .types import ChatMessage, ProviderError


class Provider(ABC):
    """模型服务提供方。"""

    name: str = "base"

    @abstractmethod
    def stream(
        self,
        messages: List[ChatMessage],
        model: str,
        **opts,
    ) -> Iterator[str]:
        """流式返回正文增量。

        Args:
            messages: 完整对话（含 system）
            model: 模型名
            **opts: temperature / max_tokens 等可选参数

        Yields:
            str: 正文片段

        Raises:
            ProviderError: 网络、鉴权或协议错误
        """
        raise NotImplementedError

    # ----- 可选能力 -----

    def supports_vision(self) -> bool:
        """是否支持多模态图片输入（截图问答需要）。"""
        return False

    def describe(self) -> dict:
        return {"name": self.name, "vision": self.supports_vision()}


def build_user_content(text: str, image_data_url: Optional[str] = None) -> object:
    """构造 user 消息的 content。

    无图时返回纯字符串（兼容所有服务）；
    有图时返回 OpenAI 多模态数组格式。
    """
    if not image_data_url:
        return text
    return [
        {"type": "text", "text": text},
        {"type": "image_url", "image_url": {"url": image_data_url}},
    ]


__all__ = ["Provider", "ProviderError", "build_user_content"]
