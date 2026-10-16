# -*- coding: utf-8 -*-
"""模式定义 —— 「功能 = 输入源 × 预设 × 投递」三元组的落地。

新增一个功能（比如「选中 → 摘要 → 替换原文」）只需要在 MODES 里加一条，
不需要写新的流程代码。这是执行框架公理 A3 的直接体现。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

# 输入源
SRC_TYPED = "typed"            # 用户手输
SRC_SELECTION = "selection"    # 取当前选中文本
SRC_SCREENSHOT = "screenshot"  # 框选屏幕区域


@dataclass(frozen=True)
class Mode:
    """一个具体功能。"""

    id: str
    title: str
    preset_id: str
    input_source: str
    hotkey_config_key: str
    auto_submit: bool = False
    activating: bool = True


MODES: Dict[str, Mode] = {
    "ask": Mode(
        id="ask",
        title="AI 问答",
        preset_id="ask",
        input_source=SRC_SELECTION,   # 有选中就预填，没有就等用户输入
        hotkey_config_key="hotkey_ask",
        auto_submit=False,
    ),
    "translate": Mode(
        id="translate",
        title="划词翻译",
        preset_id="translate",
        input_source=SRC_SELECTION,
        hotkey_config_key="hotkey_translate",
        auto_submit=True,             # 选中即译，无需回车
    ),
    "capture": Mode(
        id="capture",
        title="截图问答",
        preset_id="ask",
        input_source=SRC_SCREENSHOT,
        hotkey_config_key="hotkey_capture",
        auto_submit=False,
    ),
}


def get_mode(mode_id: str) -> Mode:
    return MODES.get(mode_id) or MODES["ask"]
