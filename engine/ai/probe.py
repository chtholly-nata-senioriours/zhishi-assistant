# -*- coding: utf-8 -*-
"""连接探测 —— 判断一组 API 配置是否真的可用（纯 Python，零 Qt 依赖）。

为什么单独一层
    「测试连接」是 UI 需求，但探测逻辑本身与界面无关：
    发一次 `GET /models` + 一次极短对话，把结论收敛成结构化结果。
    放在 L2 里，UI 只负责把它丢进线程池、把结果画出来 —— 于是它可被单测。

设计约束
    - **不阻塞调用方**：这里只提供同步函数，由调用方决定跑在哪个线程。
    - **不抛异常**：所有失败收敛成 `ProbeResult`，UI 不需要 try/except。
    - 不 import 任何 Qt 模块（L2 约束）。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import requests

from .providers.openai_compat import OpenAICompatProvider
from .stream import extract_error
from .types import ChatMessage

# 视觉模型的常见命名特征 —— 用于在 /models 列表里挑候选。
# 聚合平台（硅基流动 / OpenRouter）同一个平台上既有文本模型也有视觉模型，
# 唯一可靠的区分方式是模型名里的关键词。
VISION_HINTS = ("vl", "vision", "omni", "4v", "internvl", "minicpm-v", "ocr")


@dataclass
class ProbeResult:
    """一次探测的完整结论。"""

    ok: bool
    summary: str
    steps: List[Tuple[str, bool, str]] = field(default_factory=list)
    models: List[str] = field(default_factory=list)
    ttfb_ms: Optional[float] = None

    @property
    def failed_step(self) -> str:
        """第一个失败步骤的可读描述（供 UI 直接显示）。"""
        for name, ok, detail in self.steps:
            if not ok:
                return f"{name}：{detail}" if detail else name
        return ""


# ---------------------------------------------------------------- 候选模型


def suggest_models(ids: List[str], kind: str = "文本", limit: int = 10) -> List[str]:
    """从 /models 列表里挑出候选模型名。

    为什么需要它
        聚合平台的模型名带命名空间前缀（`Qwen/Qwen3-VL-8B-Instruct`），
        少写斜杠前缀就 404，而报错信息通常不直观。
        把候选直接列出来，用户改配置的成本从「查文档」降到「点一下」。
    """
    if kind == "视觉":
        cands = [i for i in ids if any(h in i.lower() for h in VISION_HINTS)]
    else:
        cands = [i for i in ids if not any(h in i.lower() for h in VISION_HINTS)]
    return cands[:limit]


# ---------------------------------------------------------------- 单步探测


def list_models(base_url: str, api_key: str = "",
                timeout: int = 20) -> Tuple[bool, str, List[str]]:
    """`GET {base_url}/models` —— 同时验证地址可达与鉴权正确。"""
    base = (base_url or "").rstrip("/")
    if not base:
        return False, "base_url 未配置", []
    url = base if base.endswith("/models") else f"{base}/models"

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
    except requests.RequestException as e:
        return False, f"请求失败：{e}", []

    # 与 provider 一致：不带 charset 时 requests 会猜编码，中文模型名可能乱码。
    resp.encoding = "utf-8"

    if resp.status_code >= 400:
        return False, f"HTTP {resp.status_code}：{extract_error(resp.text)}", []

    try:
        data = resp.json()
    except ValueError:
        return False, f"返回非 JSON（前 120 字）：{resp.text[:120]}", []

    items = data.get("data") if isinstance(data, dict) else None
    ids = [str(it["id"]) for it in (items or [])
           if isinstance(it, dict) and it.get("id")]
    return True, f"共 {len(ids)} 个模型", ids


def probe_chat(provider: OpenAICompatProvider, model: str,
               prompt: str = "ping") -> Tuple[bool, str, Optional[float]]:
    """发一次极短对话，只等**第一个 token** 就返回（省时省钱）。

    Returns:
        (ok, detail, ttfb_ms)
    """
    messages = [ChatMessage("user", prompt)]
    t0 = time.perf_counter()
    try:
        for delta in provider.stream(messages, model):
            ttfb = round((time.perf_counter() - t0) * 1000, 1)
            if delta:
                return True, f"首字节 {ttfb}ms", ttfb
    except Exception as e:  # noqa: BLE001 —— 探测层不允许把异常抛给 UI
        return False, f"{type(e).__name__}: {e}", None
    return False, "请求成功但没有返回任何内容", None


# ---------------------------------------------------------------- 总入口


def probe(
    base_url: str,
    api_key: str = "",
    model: str = "",
    vision_model: str = "",
    timeout: int = 20,
    check_chat: bool = True,
) -> ProbeResult:
    """完整探测一组配置。任何情况下都返回 `ProbeResult`，不抛异常。"""
    steps: List[Tuple[str, bool, str]] = []
    ids: List[str] = []

    # --- 1. 地址与鉴权 ---
    ok, detail, ids = list_models(base_url, api_key, timeout)
    steps.append(("地址与鉴权", ok, detail))
    if not ok:
        return ProbeResult(False, "接口地址或密钥不可用", steps)

    # --- 2. 模型名是否在可用列表里（只查列表，零成本）---
    if model:
        if model in ids:
            steps.append((f"文本模型 {model}", True, "在可用列表中"))
        else:
            hint = "、".join(suggest_models(ids, "文本", 5)) or "（列表为空）"
            steps.append((f"文本模型 {model}", False,
                          f"不在可用列表中。候选：{hint}"))

    if vision_model:
        if vision_model in ids:
            steps.append((f"视觉模型 {vision_model}", True, "在可用列表中"))
        else:
            hint = "、".join(suggest_models(ids, "视觉", 5)) or "（未找到视觉模型）"
            steps.append((f"视觉模型 {vision_model}", False,
                          f"不在可用列表中。候选：{hint}"))
    elif check_chat:
        steps.append(("视觉模型", False,
                      "未配置 —— 截图问答（Alt+S）会失败，建议填一个视觉模型"))

    # --- 3. 真实对话（可选）---
    ttfb = None
    if check_chat and model:
        provider = OpenAICompatProvider(
            base_url=base_url, api_key=api_key, timeout=max(timeout, 30)
        )
        ok, detail, ttfb = probe_chat(provider, model)
        steps.append((f"对话测试（{model}）", ok, detail))
        if not ok:
            return ProbeResult(False, "模型不可用或额度不足", steps, ids, ttfb)

    failed = [s for s in steps if not s[1]]
    if not failed:
        summary = f"连接正常 · {model}"
        if vision_model:
            summary += " · 视觉模型已就绪"
    else:
        summary = failed[0][2] or failed[0][0]
    return ProbeResult(not failed, summary, steps, ids, ttfb)


__all__ = ["ProbeResult", "probe", "list_models", "probe_chat", "suggest_models",
           "VISION_HINTS"]
