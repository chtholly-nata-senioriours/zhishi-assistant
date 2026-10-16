# -*- coding: utf-8 -*-
"""OpenAI 兼容协议 Provider。

覆盖绝大多数国内外服务：DeepSeek / Kimi / 通义 / 硅基流动 / OpenRouter /
本地 Ollama、vLLM、LM Studio 等 —— 只要实现了 /chat/completions 就能接。
"""
from __future__ import annotations

from typing import Iterator, List, Optional

import requests

from ..provider import Provider, build_user_content
from ..stream import SSE_ENCODING, decode_lines, extract_error, iter_openai_deltas
from ..types import ChatMessage, ProviderError


class OpenAICompatProvider(Provider):
    name = "openai_compat"

    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        timeout: int = 60,
        vision: bool = False,
    ):
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or ""
        self.timeout = timeout
        self._vision = vision

    # ----- 协议 -----

    def _endpoint(self) -> str:
        url = self.base_url
        if not url:
            raise ProviderError("base_url 未配置")
        if not url.endswith("/chat/completions"):
            url = f"{url}/chat/completions"
        return url

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    @staticmethod
    def _encode(messages: List[ChatMessage]) -> list:
        out = []
        for m in messages:
            if isinstance(m.content, str):
                out.append({"role": m.role, "content": m.content})
            else:
                out.append({"role": m.role, "content": m.content})
        return out

    # ----- 调用 -----

    def stream(self, messages: List[ChatMessage], model: str, **opts) -> Iterator[str]:
        payload = {
            "model": model,
            "messages": self._encode(messages),
            "stream": True,
        }
        for key in ("temperature", "max_tokens", "top_p"):
            value = opts.get(key)
            if value is not None:
                payload[key] = value

        try:
            resp = requests.post(
                self._endpoint(),
                json=payload,
                headers=self._headers(),
                stream=True,
                timeout=self.timeout,
            )
        except requests.RequestException as e:
            raise ProviderError(f"请求失败: {e}") from e

        with resp:
            # SSE 规范规定 UTF-8，但服务端往往不带 charset；requests 对 text/*
            # 会回退到 ISO-8859-1（RFC 2616），中文会变成 ç¿»è¯ 这类乱码。
            # 这里显式钉死编码，让 resp.text（错误分支）也走 UTF-8。
            resp.encoding = SSE_ENCODING

            if resp.status_code >= 400:
                detail = ""
                try:
                    detail = extract_error(resp.text)
                except Exception:
                    detail = resp.reason or ""
                raise ProviderError(f"HTTP {resp.status_code}: {detail}")

            try:
                # 关键：不要用 iter_lines(decode_unicode=True) —— 它受 resp.encoding
                # 影响且依赖 requests 的推断；这里取原始字节自己按 UTF-8 解。
                byte_lines = resp.iter_lines(decode_unicode=False)
                for delta in iter_openai_deltas(decode_lines(byte_lines)):
                    yield delta
            except requests.RequestException as e:
                raise ProviderError(f"流中断: {e}") from e

    def supports_vision(self) -> bool:
        return self._vision


def build_user_message(text: str, image_data_url: Optional[str] = None) -> ChatMessage:
    return ChatMessage("user", build_user_content(text, image_data_url))
