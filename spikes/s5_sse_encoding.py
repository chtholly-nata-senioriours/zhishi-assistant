#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""S5 — SSE 响应编码（真 HTTP 边界）

背景（为什么以前的验证没抓到）
    m1_verify / m2_verify 用的是**进程内假 Provider**（直接继承 `Provider`），
    完全绕过了 `OpenAICompatProvider.stream()` —— 那行 `iter_lines` 从没被执行过。
    s4_stream 是唯一走真实 HTTP 的，但它的假服务 Content-Type **带了 charset=utf-8**，
    于是 requests 解码正确，把 bug 盖住了。
    真实服务（硅基流动 / DeepSeek 等）返回 `text/event-stream` **不带 charset**，
    requests 按 RFC 2616 回退到 ISO-8859-1 → UTF-8 中文变成 `ç¿»è¯`。

假设
    响应头不带 charset 时，provider 收到的增量会与原文不一致（乱码）；
    带上 charset 时一致。两者**都应当一致** —— SSE 规范规定 UTF-8。

判定
    用同一个中文样本，分别经「不带 charset」和「带 charset」的假服务，
    断言 provider.stream() 拼出的文本与原文**逐字相等**。

用法
    python dev_bootstrap.py spikes/s5_sse_encoding.py
"""
from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from spikes._common import Report, bootstrap  # noqa: E402

bootstrap()

from engine.ai.providers.openai_compat import OpenAICompatProvider  # noqa: E402
from engine.ai.types import ChatMessage  # noqa: E402

# 故意混入中文标点、全角字符、emoji —— 覆盖 3/4 字节 UTF-8 序列
SAMPLE_CHUNKS = [
    "翻译结果：",
    "你好，世界！",
    "这是一段中文测试",
    "（含全角标点）",
    " ✅",
    "。",
]
EXPECTED = "".join(SAMPLE_CHUNKS)


def _sse_body(chunks: list[str]) -> bytes:
    """构造 OpenAI 兼容的 SSE 响应体（UTF-8 字节）。"""
    out = []
    for c in chunks:
        payload = {"choices": [{"delta": {"content": c}}]}
        out.append("data: " + json.dumps(payload, ensure_ascii=False) + "\n\n")
    out.append("data: [DONE]\n\n")
    return "".join(out).encode("utf-8")


def _make_server(charset: str | None) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            self.rfile.read(length)

            content_type = "text/event-stream"
            if charset:
                content_type += f"; charset={charset}"

            body = _sse_body(SAMPLE_CHUNKS)
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()

        def log_message(self, *args):  # 静音
            pass

    return ThreadingHTTPServer(("127.0.0.1", 0), Handler)


def _call(charset: str | None) -> tuple[str, str]:
    """返回 (收到的文本, 假服务实际发出的 Content-Type)。"""
    srv = _make_server(charset)
    port = srv.server_address[1]
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        provider = OpenAICompatProvider(base_url=f"http://127.0.0.1:{port}/v1")
        got = "".join(
            provider.stream([ChatMessage("user", "hi")], model="fake-model")
        )
        header = "text/event-stream" + (f"; charset={charset}" if charset else "")
        return got, header
    finally:
        srv.shutdown()
        srv.server_close()


def main() -> int:
    rep = Report(
        "S5",
        "SSE 响应编码（真 HTTP 边界）",
        "Content-Type 不带 charset 时，provider 仍应正确解出 UTF-8 中文",
        "两种响应头下，provider 拼出的文本都与原文逐字相等 → PASS",
    )

    rep.metric("样本", EXPECTED)
    rep.metric("样本 UTF-8 字节数", len(EXPECTED.encode("utf-8")))
    print()

    # 演示乱码是怎么产生的（便于人工核对症状）
    as_latin1 = EXPECTED.encode("utf-8").decode("iso-8859-1")
    rep.metric("按 ISO-8859-1 误解码会得到", as_latin1[:40] + "…")
    print()

    all_ok = True
    for charset, label in ((None, "不带 charset（真实服务形态）"), ("utf-8", "带 charset=utf-8")):
        got, header = _call(charset)
        ok = got == EXPECTED
        all_ok = all_ok and ok
        rep.check(
            f"{label} → 文本一致",
            ok,
            f"header={header!r} len={len(got)}" if ok else f"实收 {got[:40]!r}…",
        )
        if not ok:
            rep.note(f"{label} 收到乱码：{got[:60]!r}")

    # 逐字符差异（只在失败时打印，帮助定位是整体偏移还是个别字符）
    got_no_charset, _ = _call(None)
    if got_no_charset != EXPECTED:
        diff_at = next(
            (i for i, (a, b) in enumerate(zip(got_no_charset, EXPECTED)) if a != b),
            min(len(got_no_charset), len(EXPECTED)),
        )
        rep.metric("首个不一致位置", diff_at)
        rep.metric("原文长度 / 实收长度", f"{len(EXPECTED)} / {len(got_no_charset)}")

    print()
    rep.finish("PASS" if all_ok else "FAIL")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
