# -*- coding: utf-8 -*-
"""AI 核心层单元测试（不依赖网络、不依赖真实 API）。

覆盖：SSE 解析 / 预设组装 / 会话存储 / SessionManager 流式与取消。
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.ai.prompt import build_messages, build_system_prompt, get_preset
from engine.ai.provider import Provider
from engine.ai.session import SessionManager
from engine.ai.store import Store
from engine.ai.stream import (
    SSE_ENCODING,
    decode_lines,
    extract_error,
    iter_openai_deltas,
    iter_sse_data,
)
from engine.ai.types import ChatMessage, Preset


# ---------------------------------------------------------------- SSE 解析


def test_iter_sse_data_skips_heartbeat_and_blank():
    lines = ["", ": keep-alive", "data: hello", "   ", "data: world"]
    assert list(iter_sse_data(lines)) == ["hello", "world"]


def test_iter_openai_deltas_streaming():
    lines = [
        'data: {"choices":[{"delta":{"content":"你"}}]}',
        "",
        'data: {"choices":[{"delta":{"content":"好"}}]}',
        "data: [DONE]",
        'data: {"choices":[{"delta":{"content":"不该出现"}}]}',
    ]
    assert "".join(iter_openai_deltas(lines)) == "你好"


def test_iter_openai_deltas_non_streaming_fallback():
    """部分网关忽略 stream 参数，直接返回 message 而非 delta。"""
    lines = ['data: {"choices":[{"message":{"content":"hi"}}]}']
    assert "".join(iter_openai_deltas(lines)) == "hi"


def test_iter_openai_deltas_ignores_malformed():
    lines = ["data: {不是 json", 'data: {"choices":[]}', "data: {}"]
    assert "".join(iter_openai_deltas(lines)) == ""


def test_extract_error_reads_message():
    assert extract_error('{"error":{"message":"bad key"}}') == "bad key"
    assert extract_error("plain text") == "plain text"


# ---------------------------------------------------------------- 字节行解码


def test_decode_lines_decodes_utf8_bytes():
    """回归：SSE 行流必须以 UTF-8 解码。

    历史 bug：provider 用 `resp.iter_lines(decode_unicode=True)`，而服务端返回
    `text/event-stream` 不带 charset 时 requests 回退 ISO-8859-1，
    中文被逐字节解码成 `ç¿»è¯`（「翻译」2 字 → 6 字符）。
    """
    raw = 'data: {"choices":[{"delta":{"content":"翻译"}}]}'
    assert SSE_ENCODING == "utf-8"   # SSE 规范固定 UTF-8
    lines = [raw.encode("utf-8")]
    out = list(decode_lines(lines))
    assert out == [raw]
    assert "翻译" in out[0]

    # 反面样本：按 Latin-1 解会变成乱码，且长度翻倍
    wrong = lines[0].decode("iso-8859-1")
    assert "翻译" not in wrong
    assert len(wrong) > len(out[0])


def test_decode_lines_passes_through_str():
    """调用方已经解过码时不应二次解码。"""
    assert list(decode_lines(["已经是 str"])) == ["已经是 str"]


def test_decode_lines_skips_none():
    assert list(decode_lines([None, b"a", None])) == ["a"]


def test_decode_lines_survives_truncated_sequence():
    """被截断的多字节序列不应抛异常（errors=replace）。"""
    broken = "翻译".encode("utf-8")[:-1]
    out = list(decode_lines([broken]))
    assert len(out) == 1
    assert out[0].startswith("翻")


def test_decode_lines_handles_multibyte_across_byte_split():
    """UTF-8 多字节序列不含 0x0A/0x0D，按字节切行不会切坏字符。

    这里模拟 requests 已经切好行的情形：一行含全角标点 + emoji（4 字节序列）。
    """
    text = "你好，世界！（含全角）✅"
    lines = [("data: " + text).encode("utf-8")]
    assert list(decode_lines(lines)) == ["data: " + text]


# ---------------------------------------------------------------- 预设


def test_get_preset_falls_back_to_ask():
    assert get_preset("不存在的预设").id == "ask"
    assert get_preset("translate").id == "translate"


def test_build_system_prompt_appends_language_and_length():
    p = get_preset("ask")
    s = build_system_prompt(p, language="zh", length="short")
    assert p.system_prompt in s
    assert "简体中文" in s
    assert "三句话" in s


def test_build_messages_structure():
    p = get_preset("translate")
    msgs = build_messages(p, "Hello", context="来自 Chrome")
    assert msgs[0].role == "system"
    assert msgs[-1].role == "user"
    assert msgs[-1].content == "Hello"
    assert any("来自 Chrome" in m.content for m in msgs)


def test_build_messages_with_history():
    p = get_preset("ask")
    history = [ChatMessage("user", "上一问"), ChatMessage("assistant", "上一答")]
    msgs = build_messages(p, "新问题", history=history)
    assert [m.role for m in msgs] == ["system", "user", "assistant", "user"]


# ---------------------------------------------------------------- 存储


def test_store_session_roundtrip():
    st = Store(":memory:")
    st.create_session("s1", "ask", "标题")
    st.append_message("s1", "user", "问题")
    st.append_message("s1", "assistant", "回答")

    sessions = st.list_sessions()
    assert len(sessions) == 1 and sessions[0]["id"] == "s1"

    msgs = st.get_messages("s1")
    assert [(m.role, m.content) for m in msgs] == [("user", "问题"), ("assistant", "回答")]

    st.delete_session("s1")
    assert st.list_sessions() == []
    st.close()


def test_store_presets_roundtrip():
    st = Store(":memory:")
    st.save_preset(Preset("custom", "自定义", "系统提示", "replace", "说明"))
    got = st.list_presets()
    assert len(got) == 1
    assert got[0].id == "custom"
    assert got[0].default_delivery == "replace"
    st.delete_preset("custom")
    assert st.list_presets() == []
    st.close()


# ---------------------------------------------------------------- 会话编排


class _FakeProvider(Provider):
    name = "fake"

    def __init__(self, tokens=("你", "好", "！"), fail=False, delay=0.0):
        self.tokens = tokens
        self.fail = fail
        self.delay = delay
        self.seen_messages = None
        self.seen_model = None

    def stream(self, messages, model, **opts):
        self.seen_messages = messages
        self.seen_model = model
        if self.fail:
            raise RuntimeError("模拟失败")
        for t in self.tokens:
            if self.delay:
                time.sleep(self.delay)
            yield t


def _wait_until(predicate, timeout=5.0, app=None):
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        if app is not None:
            app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _qt_app():
    from PySide6.QtCore import QCoreApplication

    return QCoreApplication.instance() or QCoreApplication([])


def test_session_manager_streams_and_signals():
    app = _qt_app()
    mgr = SessionManager(_FakeProvider(), "test-model", store=Store(":memory:"))

    chunks, done = [], []
    mgr.chunk.connect(lambda sid, d: chunks.append(d))
    mgr.done.connect(lambda sid, f: done.append(f))

    sid = mgr.ask("你好", persist=False)
    assert isinstance(sid, str) and sid

    assert _wait_until(lambda: done, app=app)
    assert "".join(chunks) == "你好！"
    assert done == ["你好！"]
    assert mgr.provider.seen_model == "test-model"
    mgr.shutdown()


def test_session_manager_reports_error():
    app = _qt_app()
    mgr = SessionManager(_FakeProvider(fail=True), "m", store=None)

    errors = []
    mgr.error.connect(lambda sid, e: errors.append(e))

    mgr.ask("x", persist=False)
    assert _wait_until(lambda: errors, app=app)
    assert "模拟失败" in errors[0]
    mgr.shutdown()


def test_session_manager_cancel_stops_early():
    app = _qt_app()
    mgr = SessionManager(_FakeProvider(tokens=tuple("abcdefghij"), delay=0.05), "m",
                         store=None)

    got = []
    mgr.chunk.connect(lambda sid, d: got.append(d))
    done = []
    mgr.done.connect(lambda sid, f: done.append(f))

    sid = mgr.ask("x", persist=False)
    time.sleep(0.08)
    mgr.cancel(sid)

    assert _wait_until(lambda: done, app=app)
    assert len("".join(got)) < 10, "取消后不应收到全部 token"
    mgr.shutdown()


def test_session_manager_persists_when_store_given():
    app = _qt_app()
    st = Store(":memory:")
    mgr = SessionManager(_FakeProvider(), "m", store=st)

    done = []
    mgr.done.connect(lambda sid, f: done.append(f))
    sid = mgr.ask("持久化测试", persist=True)
    assert _wait_until(lambda: done, app=app)

    msgs = st.get_messages(sid)
    assert any(m.role == "assistant" and m.content == "你好！" for m in msgs)
    mgr.shutdown()
    st.close()


def test_session_manager_routes_vision_model():
    """带图请求必须走视觉模型，纯文本请求走主模型。"""
    app = _qt_app()
    p = _FakeProvider()
    mgr = SessionManager(p, "text-model", store=None, vision_model="vision-model")

    done = []
    mgr.done.connect(lambda sid, f: done.append(f))
    mgr.ask("看图", image_data_url="data:image/png;base64,AAAA", persist=False)
    assert _wait_until(lambda: done, app=app)
    assert p.seen_model == "vision-model"
    assert mgr.vision_model == "vision-model"
    assert mgr.model_for(True) == "vision-model"
    assert mgr.model_for(False) == "text-model"
    mgr.shutdown()


def test_session_manager_vision_falls_back_to_main_model():
    """未配置 vision_model 时，带图请求回退主模型（行为与改造前一致）。"""
    app = _qt_app()
    p = _FakeProvider()
    mgr = SessionManager(p, "text-model", store=None)

    done = []
    mgr.done.connect(lambda sid, f: done.append(f))
    mgr.ask("看图", image_data_url="data:image/png;base64,AAAA", persist=False)
    assert _wait_until(lambda: done, app=app)
    assert p.seen_model == "text-model"
    assert mgr.vision_model == "text-model"
    mgr.shutdown()


def test_session_manager_text_request_uses_main_model():
    """纯文本请求不受 vision_model 影响。"""
    app = _qt_app()
    p = _FakeProvider()
    mgr = SessionManager(p, "text-model", store=None, vision_model="vision-model")

    done = []
    mgr.done.connect(lambda sid, f: done.append(f))
    mgr.ask("纯文本", persist=False)
    assert _wait_until(lambda: done, app=app)
    assert p.seen_model == "text-model"
    mgr.shutdown()


def test_session_manager_configure_vision_model():
    app = _qt_app()
    mgr = SessionManager(_FakeProvider(), "m", store=None)
    assert mgr.vision_model == "m"
    mgr.configure(vision_model=" v ")
    assert mgr.vision_model == "v"
    mgr.shutdown()


def test_build_from_config_reads_vision_model():
    """build_from_config 必须把 ai.vision_model 传进 SessionManager。"""
    from engine.ai import build_from_config

    class _Cfg:
        def __init__(self, data):
            self._d = data

        def get(self, key, default=None):
            node = self._d
            for part in key.split("."):
                if not isinstance(node, dict) or part not in node:
                    return default
                node = node[part]
            return node

    cfg = _Cfg({"ai": {
        "provider": "openai_compat",
        "base_url": "https://example.invalid/v1",
        "model": "text-model",
        "vision_model": "vision-model",
        "api_key": "k",
    }})
    mgr = build_from_config(cfg, store=Store(":memory:"))
    assert mgr.model == "text-model"
    assert mgr.vision_model == "vision-model"
    mgr.shutdown()


# ---------------------------------------------------------------- 连接探测


def test_suggest_models_splits_text_and_vision():
    from engine.ai.probe import suggest_models

    ids = [
        "Qwen/Qwen3-8B",
        "deepseek-ai/DeepSeek-V3",
        "Qwen/Qwen3-VL-8B-Instruct",
        "deepseek-ai/DeepSeek-OCR",
        "gpt-4o",
    ]
    text = suggest_models(ids, "文本")
    vision = suggest_models(ids, "视觉")

    assert "Qwen/Qwen3-8B" in text
    assert "Qwen/Qwen3-VL-8B-Instruct" not in text
    assert "Qwen/Qwen3-VL-8B-Instruct" in vision
    assert "deepseek-ai/DeepSeek-OCR" in vision
    # 启发式的**已知局限**：`gpt-4o` 名字里没有 vl/vision/omni 等关键词，
    # 会被归到文本候选里。这只影响「候选推荐」的准确度，不影响手填 ——
    # 候选本来就是辅助，模型名最终以用户输入为准。这里把行为固化下来，
    # 免得以后有人误以为它是个 bug。
    assert "gpt-4o" in text


def test_probe_rejects_empty_base_url():
    from engine.ai.probe import probe

    res = probe("", "", "m")
    assert res.ok is False
    assert "base_url" in res.summary or "base_url" in res.failed_step


def test_probe_reports_missing_model(monkeypatch):
    """模型名不在 /models 列表里时要给出候选，而不是只说「失败」。"""
    import importlib

    # 注意：不能用 `import engine.ai.probe as m` ——
    # 包 __init__ 里 `from .probe import probe` 会让 `engine.ai.probe`
    # 指向**函数**而不是模块（同名遮蔽）。走 sys.modules 拿真模块。
    probe_mod = importlib.import_module("engine.ai.probe")

    class _Resp:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {"data": [{"id": "good-model"}, {"id": "good-vl-1"}]}

    monkeypatch.setattr(probe_mod.requests, "get", lambda *a, **k: _Resp())

    res = probe_mod.probe("https://x.invalid/v1", "k", "typo-model",
                          "good-vl-1", check_chat=False)
    assert res.ok is False
    assert "不在可用列表" in res.failed_step
    assert "good-model" in res.failed_step       # 候选被列出来了


def test_probe_ok_end_to_end_with_fake_transport(monkeypatch):
    """成功路径：/models 通 + 对话拿到首字节。全程无网络。"""
    import importlib

    # 注意：不能用 `import engine.ai.probe as m` ——
    # 包 __init__ 里 `from .probe import probe` 会让 `engine.ai.probe`
    # 指向**函数**而不是模块（同名遮蔽）。走 sys.modules 拿真模块。
    probe_mod = importlib.import_module("engine.ai.probe")

    class _Resp:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {"data": [{"id": "m1"}, {"id": "vl-1"}]}

    monkeypatch.setattr(probe_mod.requests, "get", lambda *a, **k: _Resp())

    class _FakeProvider:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def stream(self, messages, model, **opts):
            yield "pong"

    monkeypatch.setattr(probe_mod, "OpenAICompatProvider", _FakeProvider)

    res = probe_mod.probe("https://x.invalid/v1", "k", "m1", "vl-1")
    assert res.ok is True
    assert res.ttfb_ms is not None
    assert len(res.models) == 2
    assert all(ok for _, ok, _ in res.steps)


def test_probe_http_error_is_reported_not_raised(monkeypatch):
    """探测层绝不把异常抛给 UI —— HTTP 401 要变成可读结论。"""
    import importlib

    # 注意：不能用 `import engine.ai.probe as m` ——
    # 包 __init__ 里 `from .probe import probe` 会让 `engine.ai.probe`
    # 指向**函数**而不是模块（同名遮蔽）。走 sys.modules 拿真模块。
    probe_mod = importlib.import_module("engine.ai.probe")

    class _Resp:
        status_code = 401
        text = '{"error": {"message": "Invalid token"}}'

        @staticmethod
        def json():
            return {}

    monkeypatch.setattr(probe_mod.requests, "get", lambda *a, **k: _Resp())

    res = probe_mod.probe("https://x.invalid/v1", "bad", "m1")
    assert res.ok is False
    assert "401" in res.failed_step
    assert "Invalid token" in res.failed_step


def test_probe_network_exception_is_swallowed(monkeypatch):
    import importlib

    # 注意：不能用 `import engine.ai.probe as m` ——
    # 包 __init__ 里 `from .probe import probe` 会让 `engine.ai.probe`
    # 指向**函数**而不是模块（同名遮蔽）。走 sys.modules 拿真模块。
    probe_mod = importlib.import_module("engine.ai.probe")

    def _boom(*a, **k):
        raise probe_mod.requests.RequestException("DNS 挂了")

    monkeypatch.setattr(probe_mod.requests, "get", _boom)

    res = probe_mod.probe("https://x.invalid/v1", "k", "m1")
    assert res.ok is False
    assert "DNS 挂了" in res.failed_step


def test_probe_flags_missing_vision_model(monkeypatch):
    """未配视觉模型要明确警告 —— 否则截图问答会在用户那里才炸。"""
    import importlib

    # 注意：不能用 `import engine.ai.probe as m` ——
    # 包 __init__ 里 `from .probe import probe` 会让 `engine.ai.probe`
    # 指向**函数**而不是模块（同名遮蔽）。走 sys.modules 拿真模块。
    probe_mod = importlib.import_module("engine.ai.probe")

    class _Resp:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {"data": [{"id": "m1"}]}

    monkeypatch.setattr(probe_mod.requests, "get", lambda *a, **k: _Resp())

    class _FakeProvider:
        def __init__(self, **kwargs):
            pass

        def stream(self, messages, model, **opts):
            yield "pong"

    monkeypatch.setattr(probe_mod, "OpenAICompatProvider", _FakeProvider)

    res = probe_mod.probe("https://x.invalid/v1", "k", "m1", vision_model="")
    assert res.ok is False
    assert "视觉模型" in res.failed_step


# ---------------------------------------------------------------- 真实 HTTP 边界（集成）
#
# 为什么单独列一节：m1/m2 的验证用的是**进程内假 Provider**，绕过了 HTTP 层；
# 唯一走真 HTTP 的 s4 spike 又恰好带了 charset=utf-8。于是
# `iter_lines(decode_unicode=True)` 的编码 bug 长期没人发现 —— 真机一接就乱码。
# 这一节把「SessionManager + 真实 OpenAICompatProvider + 真 HTTP」这个组合锁住。


def _start_sse_server(content_type: str, chunks):
    """起一个 OpenAI 兼容的假 SSE 服务，返回 (base_url, shutdown)。

    content_type 由调用方决定 —— 这是本用例的关键：真实服务返回的
    `text/event-stream` **不带 charset**，requests 会回退 ISO-8859-1。
    """
    import json as _json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    body = "".join(
        "data: " + _json.dumps({"choices": [{"delta": {"content": c}}]}, ensure_ascii=False) + "\n\n"
        for c in chunks
    ) + "data: [DONE]\n\n"
    payload = body.encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def do_POST(self):  # noqa: N802
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.end_headers()
            self.wfile.write(payload)
            self.wfile.flush()

        def log_message(self, *args):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    def shutdown():
        srv.shutdown()
        srv.server_close()

    return f"http://127.0.0.1:{srv.server_address[1]}/v1", shutdown


def test_session_manager_real_http_without_charset_keeps_chinese():
    """集成回归：SSE 不带 charset 时，SessionManager 产出的中文必须完好。

    这正是用户报的 bug —— 划词翻译返回 `ç¿»è¯` 这类乱码。
    """
    from engine.ai.providers.openai_compat import OpenAICompatProvider

    app = _qt_app()
    expected = "翻译结果：你好，世界！这是一段中文测试（含全角标点）✅。"
    chunks_in = ["翻译结果：", "你好，世界！", "这是一段中文测试", "（含全角标点）", "✅", "。"]

    base_url, shutdown = _start_sse_server("text/event-stream", chunks_in)
    try:
        provider = OpenAICompatProvider(base_url=base_url)
        mgr = SessionManager(provider, "any-model", store=None)

        chunks, done = [], []
        mgr.chunk.connect(lambda sid, d: chunks.append(d))
        mgr.done.connect(lambda sid, f: done.append(f))

        mgr.ask("translate me", persist=False)
        assert _wait_until(lambda: done, app=app), "未收到 done 信号"

        got = "".join(chunks)
        assert got == expected, f"乱码：{got!r}"
        assert "ç" not in got, f"出现 Latin-1 误解码特征：{got!r}"
        mgr.shutdown()
    finally:
        shutdown()


def test_session_manager_real_http_with_charset_also_ok():
    """带了 charset=utf-8 的网关（如 s4 假服务）同样要正确。"""
    from engine.ai.providers.openai_compat import OpenAICompatProvider

    app = _qt_app()
    base_url, shutdown = _start_sse_server(
        "text/event-stream; charset=utf-8", ["中文", "也", "要", "对"]
    )
    try:
        mgr = SessionManager(OpenAICompatProvider(base_url=base_url), "m", store=None)
        done = []
        mgr.done.connect(lambda sid, f: done.append(f))
        mgr.ask("x", persist=False)
        assert _wait_until(lambda: done, app=app)
        assert done == ["中文也要对"]
        mgr.shutdown()
    finally:
        shutdown()


def test_provider_error_body_is_utf8_decoded():
    """错误响应体里的中文也不该乱码（错误分支同样受 encoding 影响）。"""
    from engine.ai.providers.openai_compat import OpenAICompatProvider
    from engine.ai.types import ProviderError

    import json as _json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    body = _json.dumps(
        {"error": {"message": "模型不存在，请检查名称"}}, ensure_ascii=False
    ).encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def do_POST(self):  # noqa: N802
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            self.send_response(404)
            # 故意也不带 charset —— 模拟真实网关
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        provider = OpenAICompatProvider(base_url=f"http://127.0.0.1:{srv.server_address[1]}/v1")
        try:
            list(provider.stream([ChatMessage("user", "hi")], "m"))
            raise AssertionError("应当抛出 ProviderError")
        except ProviderError as e:
            assert "模型不存在" in str(e), f"错误信息乱码：{e}"
    finally:
        srv.shutdown()
        srv.server_close()


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
