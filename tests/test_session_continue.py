# -*- coding: utf-8 -*-
"""「继续对话」链路回归测试（P2.10）。

守的是这一条链路：
    控制中心选中一条历史会话 → 载入 AI 面板 → 接着问
    → **落在同一条会话上**（而不是新建一条）

分三层：
    1. Store 层：`append_exchange()` 只追加提问，不动 created_at / 标题
    2. SessionManager 层：`ask(session_id=...)` 复用 id 且落库走 append
    3. UI 层：面板 `load_history()` 不暴露投递按钮；插件 `continue_session()`
       填好上下文；控制中心用鸭子类型调插件、缺插件时给出提示

运行:
    python dev_bootstrap.py -m pytest tests/test_session_continue.py -q
"""
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

from engine.ai import ChatMessage, Provider, SessionManager
from engine.ai.store import Store

# ============================================================
# 测试替身
# ============================================================


class _FakeProvider(Provider):
    """把回复逐字吐出来，并记录收到的消息（便于断言上下文）。"""

    def __init__(self, reply: str = "回复内容"):
        self.reply = reply
        self.seen: list = []

    def stream(self, messages, model):
        self.seen.append((list(messages), model))
        for ch in self.reply:
            yield ch


class _MuteSelection:
    def get_selected(self, timeout_ms: int = 250) -> str:
        return ""

    def set_clipboard(self, text: str) -> None:
        pass


def _wait_until(predicate, timeout=5.0):
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _make_plugin(manager=None, panel=None, selection=None):
    """构造一个不依赖真实 app 的插件实例。"""
    from extensions.system.ai_assistant.plugin import AIAssistantPlugin

    p = AIAssistantPlugin()
    p._panel = panel
    p._manager = manager
    p._selection = selection or _MuteSelection()
    # 不真去 build_from_config（需要 app.config）
    p._ensure_manager = lambda force=False: None
    return p


# ============================================================
# 1. Store 层：续接语义
# ============================================================


def test_append_exchange_only_appends_user_message(tmp_path):
    st = Store(tmp_path / "ai.db")
    st.create_session("s1", "ask", "原标题")
    st.append_message("s1", "user", "第一问")
    st.append_message("s1", "assistant", "第一答")

    st.append_exchange("s1", "第二问")

    assert [m.content for m in st.get_messages("s1")] == ["第一问", "第一答", "第二问"]


def test_append_exchange_keeps_created_at_and_title(tmp_path):
    """续接不能把创建时间重置、也不能用新问题覆盖标题。"""
    st = Store(tmp_path / "ai.db")
    st.create_session("s1", "ask", "原标题")
    before = next(s for s in st.list_sessions() if s["id"] == "s1")

    time.sleep(0.02)                      # 让 updated_at 有区分度
    st.append_exchange("s1", "很长的一段新提问，绝不该变成标题")

    after = next(s for s in st.list_sessions() if s["id"] == "s1")
    assert after["title"] == "原标题"
    assert after["created_at"] == before["created_at"]
    assert after["updated_at"] > before["updated_at"]


def test_session_exists(tmp_path):
    st = Store(tmp_path / "ai.db")
    assert st.session_exists("nope") is False
    st.create_session("s1", "ask", "t")
    assert st.session_exists("s1") is True


# ============================================================
# 2. SessionManager 层：session_id 复用
# ============================================================


def test_ask_with_session_id_reuses_the_id(tmp_path):
    st = Store(tmp_path / "ai.db")
    st.create_session("s1", "ask", "原标题")
    st.append_message("s1", "user", "第一问")
    st.append_message("s1", "assistant", "第一答")

    mgr = SessionManager(_FakeProvider(), "m", store=st)
    done = []
    mgr.done.connect(lambda sid, full: done.append(full))

    sid = mgr.ask("第二问", session_id="s1")
    assert sid == "s1", "续接必须复用传入的 id，否则会新建一条会话"
    assert _wait_until(lambda: done)
    mgr.shutdown()


def test_ask_with_session_id_does_not_duplicate_history(tmp_path):
    """关键回归：续接时整段历史已在库里，不能再写一遍。"""
    st = Store(tmp_path / "ai.db")
    st.create_session("s1", "ask", "原标题")
    st.append_message("s1", "user", "第一问")
    st.append_message("s1", "assistant", "第一答")

    mgr = SessionManager(_FakeProvider(), "m", store=st)
    done = []
    mgr.done.connect(lambda sid, full: done.append(full))

    history = [ChatMessage("user", "第一问"), ChatMessage("assistant", "第一答")]
    mgr.ask("第二问", history=history, session_id="s1")
    assert _wait_until(lambda: done)
    mgr.shutdown()

    contents = [m.content for m in st.get_messages("s1")]
    assert contents == ["第一问", "第一答", "第二问", "回复内容"], (
        f"续接后消息不对（历史被重复写入？）：{contents}"
    )
    # 标题与创建时间同样不该被动
    rec = next(s for s in st.list_sessions() if s["id"] == "s1")
    assert rec["title"] == "原标题"


def test_ask_without_session_id_creates_a_new_one(tmp_path):
    st = Store(tmp_path / "ai.db")
    st.create_session("s1", "ask", "原标题")

    mgr = SessionManager(_FakeProvider(), "m", store=st)
    done = []
    mgr.done.connect(lambda sid, full: done.append(full))

    sid = mgr.ask("新问题")
    assert sid != "s1"
    assert _wait_until(lambda: done)
    mgr.shutdown()
    assert len(st.list_sessions()) == 2


def test_history_reaches_the_model(tmp_path):
    """上下文必须真的送进模型 —— 只落库不送上下文等于没续接。"""
    st = Store(tmp_path / "ai.db")
    st.create_session("s1", "ask", "t")
    st.append_message("s1", "user", "第一问")

    prov = _FakeProvider()
    mgr = SessionManager(prov, "m", store=st)
    done = []
    mgr.done.connect(lambda sid, full: done.append(full))

    mgr.ask("第二问", history=[ChatMessage("user", "第一问")], session_id="s1")
    assert _wait_until(lambda: prov.seen)
    mgr.shutdown()

    sent = [m.content for m in prov.seen[0][0]]
    assert "第一问" in sent and "第二问" in sent


# ============================================================
# 3. 面板层：历史展示
# ============================================================


def test_load_history_renders_both_roles():
    from presentation.ai_panel import AIPanel

    panel = AIPanel()
    panel.load_history([ChatMessage("user", "第一问"), ChatMessage("assistant", "第一答")],
                       title="标题")

    text = panel._output.content()
    assert "第一问" in text and "第一答" in text
    assert "你" in text and "助手" in text


def test_load_history_does_not_offer_delivery():
    """载入历史后不能露出投递按钮 —— 否则「替换原文」会把整段历史投出去。"""
    from presentation.ai_panel import AIPanel

    panel = AIPanel()
    panel.load_history([ChatMessage("assistant", "很久以前的回答")])

    assert panel._has_result is False, "载入历史不该被当成「有结果」"


def test_load_history_handles_empty():
    from presentation.ai_panel import AIPanel

    panel = AIPanel()
    panel.load_history([])
    assert panel._output.content().strip() != ""


# ============================================================
# 4. 插件层：上下文维护与续接入口
# ============================================================


def test_continue_session_loads_history_and_target():
    from presentation.ai_panel import AIPanel

    mgr = SessionManager(_FakeProvider(), "m", store=None)
    panel = AIPanel()
    plugin = _make_plugin(manager=mgr, panel=panel)

    msgs = [ChatMessage("user", "第一问"), ChatMessage("assistant", "第一答")]
    ok = plugin.continue_session("s1", msgs)

    assert ok is True
    assert plugin._active_session_id == "s1"
    assert len(plugin._history) == 2
    assert "第一问" in panel._output.content()
    mgr.shutdown()


def test_continue_session_without_panel_returns_false():
    """面板没就绪要如实返回 False —— 调用方据此给提示，而不是静默失败。"""
    plugin = _make_plugin(manager=SessionManager(_FakeProvider(), "m", store=None), panel=None)
    assert plugin.continue_session("s1", []) is False


def test_continue_session_without_session_id_returns_false():
    from presentation.ai_panel import AIPanel

    plugin = _make_plugin(
        manager=SessionManager(_FakeProvider(), "m", store=None), panel=AIPanel()
    )
    assert plugin.continue_session("", [ChatMessage("user", "x")]) is False


def test_submit_sends_history_and_reuses_session_id():
    from presentation.ai_panel import AIPanel

    prov = _FakeProvider()
    mgr = SessionManager(prov, "m", store=None)
    panel = AIPanel()
    plugin = _make_plugin(manager=mgr, panel=panel)

    plugin._history = [ChatMessage("user", "旧问"), ChatMessage("assistant", "旧答")]
    plugin._active_session_id = "s1"
    plugin._on_submit("新问题")

    assert plugin._active_sid == "s1", "续接会话必须沿用原 id"
    assert _wait_until(lambda: prov.seen)

    sent = [m.content for m in prov.seen[0][0]]
    assert "旧问" in sent and "旧答" in sent, f"历史没送进模型：{sent}"
    assert "新问题" in sent
    assert sent.count("新问题") == 1, "当前问题被重复送进模型"
    # 本地上下文也要记下这次提问
    assert plugin._history[-1].content == "新问题"
    mgr.shutdown()


def test_done_appends_assistant_reply_to_history():
    """助手回复要进上下文，否则多轮续接只有 user 侧。"""
    plugin = _make_plugin(manager=SessionManager(_FakeProvider(), "m", store=None))
    plugin._active_sid = "s1"
    plugin._history = [ChatMessage("user", "问")]

    plugin._on_done("s1", "答")

    assert plugin._history[-1].role == "assistant"
    assert plugin._history[-1].content == "答"


def test_invoke_resets_to_a_fresh_session():
    """热键唤起 = 全新会话：不能带着上一次的上下文与续接目标。"""
    plugin = _make_plugin(manager=SessionManager(_FakeProvider(), "m", store=None),
                          panel=_StubPanel())
    plugin._history = [ChatMessage("user", "上一轮的问")]
    plugin._active_session_id = "s1"
    plugin._context_text = "上一轮的选区"

    plugin.invoke("ask")

    assert plugin._history == []
    assert plugin._active_session_id is None
    assert plugin._context_text == ""


class _StubPanel:
    """`invoke()` 只需这几个方法。"""

    _mode = "ask"

    def __init__(self):
        self.hints: list = []

    def move_to_cursor_screen(self):
        pass

    def show_passive(self, mode):
        pass

    def activate_for_input(self):
        pass

    def set_context(self, text):
        pass

    def set_hint(self, text):
        self.hints.append(text)


# ============================================================
# 5. 控制中心层：鸭子类型调用
# ============================================================


class _FakePlugin:
    def __init__(self, ok=True):
        self.ok = ok
        self.calls: list = []

    def continue_session(self, sid, msgs):
        self.calls.append((sid, msgs))
        return self.ok


class _FakePM:
    """够控制中心 9 个页面用的最小插件管理器。"""

    def __init__(self, plugin):
        self._plugin = plugin

    def get_plugin(self, name):
        return self._plugin if name == "ai_assistant" else None

    def get_all_plugins(self):
        # 插件页会遍历 manifest；本文件只关心 get_plugin，给空表最省事
        return {}


class _FakeApp:
    def __init__(self, pm):
        self.plugin_manager = pm


def _make_center(app_obj):
    from presentation.control_center import ControlCenter, reset_instance

    reset_instance()
    win = ControlCenter(app=app_obj)
    warns: list = []
    win.warn = lambda t, x="": warns.append((t, x))
    return win, warns


def test_control_center_forwards_to_plugin():
    from presentation.control_center import reset_instance

    plugin = _FakePlugin(ok=True)
    win, warns = _make_center(_FakeApp(_FakePM(plugin)))
    try:
        msgs = [ChatMessage("user", "第一问")]
        assert win.continue_session("s1", msgs) is True
        assert plugin.calls == [("s1", msgs)]
        assert warns == []
    finally:
        win.close()
        reset_instance()


def test_control_center_warns_when_plugin_missing():
    """AI 插件没加载时要明确提示 —— 不是静默失败。"""
    from presentation.control_center import reset_instance

    win, warns = _make_center(None)          # app=None → 没有 plugin_manager
    try:
        assert win.continue_session("s1", []) is False
        assert warns, "缺插件时必须给用户提示"
        assert "插件" in warns[0][1]
    finally:
        win.close()
        reset_instance()


def test_control_center_warns_when_panel_not_ready():
    from presentation.control_center import reset_instance

    plugin = _FakePlugin(ok=False)           # 插件在，但面板没就绪
    win, warns = _make_center(_FakeApp(_FakePM(plugin)))
    try:
        assert win.continue_session("s1", []) is False
        assert warns and "未就绪" in warns[0][1]
    finally:
        win.close()
        reset_instance()


def test_sessions_page_has_continue_button_disabled_without_selection(tmp_path):
    """没有选中会话时「继续对话」必须禁用。"""
    from presentation.control_center import SessionsPage

    class _Center:
        app = None

        def __init__(self, store):
            self._store = store

        def store(self):
            return self._store

        def confirm(self, *_a, **_k):
            return True

        def info(self, *_a, **_k):
            pass

        def warn(self, *_a, **_k):
            pass

        def statusMessage(self, *_a, **_k):
            pass

    store = Store(tmp_path / "ai.db")
    page = SessionsPage(_Center(store))
    assert page._btn_continue.isEnabled() is False
