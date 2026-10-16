# -*- coding: utf-8 -*-
"""预设与消息组装（纯 Python，零 Qt 依赖）。

「功能 = 输入源 × 预设 × 投递」中的「预设」维度。
新增一个功能（如「翻译成文言文」）在这里加一个 Preset 即可，不用写新流程。
"""
from __future__ import annotations

from typing import Dict, List, Optional

from .types import ChatMessage, Preset

# ---------------------------------------------------------------- 内置预设

BUILTIN_PRESETS: Dict[str, Preset] = {
    "ask": Preset(
        id="ask",
        name="问答",
        system_prompt=(
            "你是一个随时待命的桌面助手。回答要准确、直接、可操作。"
            "不要复述问题，不要客套开场，直接给结论。"
        ),
        default_delivery="panel",
        description="自由问答",
    ),
    "translate": Preset(
        id="translate",
        name="翻译",
        system_prompt=(
            "你是专业翻译。把用户给出的文本翻译成目标语言。"
            "只输出译文本身，不要加解释、不要加引号、不要复述原文。"
            "保持原文的换行与格式。"
        ),
        default_delivery="copy",
        description="选中即译",
    ),
    "summarize": Preset(
        id="summarize",
        name="摘要",
        system_prompt=(
            "把用户给出的内容压缩成要点。"
            "用简洁的中文条目输出，保留关键数字与结论，去掉铺垫与重复。"
        ),
        default_delivery="panel",
        description="长文压缩",
    ),
    "explain": Preset(
        id="explain",
        name="解释",
        system_prompt=(
            "解释用户选中的内容。先给一句话结论，再给必要的背景。"
            "面向不懂该领域的读者，避免堆砌术语。"
        ),
        default_delivery="panel",
        description="看不懂的东西讲清楚",
    ),
    "rewrite": Preset(
        id="rewrite",
        name="改写",
        system_prompt=(
            "润色用户给出的文本：保持原意与语气，修正语病，让表达更通顺自然。"
            "只输出改写后的文本。"
        ),
        default_delivery="copy",
        description="润色文字",
    ),
    "code": Preset(
        id="code",
        name="代码",
        system_prompt=(
            "你是资深工程师。回答代码问题时给出可直接运行的代码，"
            "并用一两句话说明关键点。不确定的地方要明确说出来。"
        ),
        default_delivery="copy",
        description="代码问题",
    ),
}

_LENGTH_HINTS = {
    "short": "回答尽量精简，控制在三句话以内。",
    "medium": "回答长度适中，控制在 200 字以内。",
    "long": "回答可以详细一些，必要时分点说明。",
}

_LANG_HINTS = {
    "zh": "用简体中文回答。",
    "en": "Answer in English.",
    "ja": "日本語で答えてください。",
    "auto": "",  # 跟随用户输入语言
}


def get_preset(preset_id: str) -> Preset:
    return BUILTIN_PRESETS.get(preset_id) or BUILTIN_PRESETS["ask"]


def list_presets() -> List[Preset]:
    return list(BUILTIN_PRESETS.values())


def build_system_prompt(
    preset: Preset,
    language: str = "zh",
    length: str = "auto",
) -> str:
    """在预设的 system prompt 上叠加语言与长度约束。"""
    parts = [preset.system_prompt]
    hint = _LANG_HINTS.get(language, "")
    if hint:
        parts.append(hint)
    hint = _LENGTH_HINTS.get(length, "")
    if hint:
        parts.append(hint)
    return "\n".join(p for p in parts if p)


def build_messages(
    preset: Preset,
    user_text: str,
    context: str = "",
    language: str = "zh",
    length: str = "auto",
    history: Optional[List[ChatMessage]] = None,
) -> List[ChatMessage]:
    """组装完整消息列表。

    Args:
        preset: 预设
        user_text: 用户输入（或选中的文本）
        context: 附加上下文（如截图前的窗口标题、文件路径）
        history: 多轮对话历史
    """
    messages: List[ChatMessage] = [
        ChatMessage("system", build_system_prompt(preset, language, length))
    ]
    if history:
        messages.extend(history)
    if context:
        messages.append(ChatMessage("user", f"[背景信息]\n{context}"))
    messages.append(ChatMessage("user", user_text))
    return messages
