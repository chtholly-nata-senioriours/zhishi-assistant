# -*- coding: utf-8 -*-
"""SSE 流式解析（纯函数，零依赖，可脱离网络单测）。

拆成两层：
    iter_sse_data()        —— SSE 协议层：从行流里抠出 `data:` 负载
    iter_openai_deltas()   —— OpenAI 兼容协议层：从负载里抠出正文增量
"""
from __future__ import annotations

import json
from typing import Iterable, Iterator

# SSE 规范（WHATWG HTML Living Standard §9.2.5）规定事件流**必须是 UTF-8**。
SSE_ENCODING = "utf-8"


def decode_lines(lines: Iterable[bytes], encoding: str = SSE_ENCODING) -> Iterator[str]:
    """把**字节行流**按 UTF-8 解码成 str 行流。

    为什么不能直接用 `requests` 的 `iter_lines(decode_unicode=True)`
        服务端返回 `text/event-stream` 时通常**不带 charset**，
        而 requests 按 RFC 2616 对 `text/*` 回退到 **ISO-8859-1**，
        于是 UTF-8 中文被逐字节解码成 `ç¿»è¯` 这类乱码
        （「翻译」→ 6 个字符，长度翻倍）。

        这类乱码在 m1/m2 里抓不到：它们用的是进程内假 Provider，
        绕过了 HTTP 层；而唯一走真 HTTP 的 s4 spike 恰好带了 charset=utf-8。
        真机一接硅基流动就现形。详见 spikes/s5_sse_encoding.py。

    为什么按字节切行是安全的
        UTF-8 多字节序列的每个字节都在 0x80–0xFF，**不会出现 0x0A / 0x0D**，
        所以按 `\\n` / `\\r\\n` 在字节层切行不会切断任何字符。
    """
    for raw in lines:
        if raw is None:
            continue
        if isinstance(raw, str):      # 已经是 str（调用方自己解过码）
            yield raw
            continue
        yield raw.decode(encoding, errors="replace")


def iter_sse_data(lines: Iterable[str]) -> Iterator[str]:
    """从 SSE 行流中提取 data 负载。

    处理规则（按 SSE 规范）：
      - 空行是事件分隔符，跳过
      - 以 `:` 开头的是注释（心跳），跳过
      - 以 `data:` 开头的取冒号后的内容
    """
    for raw in lines:
        if raw is None:
            continue
        line = raw.strip()
        if not line or line.startswith(":"):
            continue
        if line.startswith("data:"):
            yield line[5:].strip()


def iter_openai_deltas(lines: Iterable[str]) -> Iterator[str]:
    """从 OpenAI 兼容的 SSE 流中提取正文增量。

    兼容两种返回形态：
      - 流式：choices[0].delta.content
      - 非流式（部分网关忽略 stream 参数）：choices[0].message.content
    """
    for payload in iter_sse_data(lines):
        if payload == "[DONE]":
            return
        try:
            obj = json.loads(payload)
        except (ValueError, TypeError):
            continue

        for choice in obj.get("choices") or []:
            if not isinstance(choice, dict):
                continue
            delta = choice.get("delta") or {}
            content = delta.get("content")
            if content:
                yield content
                continue
            message = choice.get("message") or {}
            content = message.get("content")
            if content:
                yield content


def extract_error(payload: str) -> str:
    """从错误负载里提取可读信息。"""
    try:
        obj = json.loads(payload)
    except (ValueError, TypeError):
        return payload[:200]
    err = obj.get("error")
    if isinstance(err, dict):
        return str(err.get("message") or err)[:200]
    if err:
        return str(err)[:200]
    return payload[:200]
