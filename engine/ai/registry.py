# -*- coding: utf-8 -*-
"""Provider 注册表（纯 Python，零 Qt 依赖）。

新增厂商：register_provider("myapi", MyProvider) 即可，调用方无需改动。
"""
from __future__ import annotations

from typing import Callable, Dict, List

from .provider import Provider
from .providers.openai_compat import OpenAICompatProvider
from .types import ProviderError

_FACTORIES: Dict[str, Callable[..., Provider]] = {}


def register_provider(name: str, factory: Callable[..., Provider]) -> None:
    _FACTORIES[name] = factory


def create_provider(name: str, **config) -> Provider:
    factory = _FACTORIES.get(name)
    if factory is None:
        raise ProviderError(
            f"未注册的 provider: {name!r}（可用: {', '.join(sorted(_FACTORIES))}）"
        )
    return factory(**config)


def available_providers() -> List[str]:
    return sorted(_FACTORIES)


# 内置
register_provider("openai_compat", OpenAICompatProvider)
