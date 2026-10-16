# -*- coding: utf-8 -*-
"""投递（`native/injector.py`）契约测试。

> ⚠ 2026-10-12：「替换原文 / 粘贴到前台」已**从产品里移除**（`AGENTS.md` §4.6），
> `Injector` 因此不再被 UI 调用。本文件保留 —— 它守的是这个模块自身的契约，
> 而模块本身也保留（是「跨应用投递」唯一的实测记录）。最后一节同时锁住
> 「面板只剩复制按钮」「插件不再持有 Injector」，防止移除被无意改回去。

背景
    `Injector` 曾**零测试覆盖**，而它承担「把答案送回用户手边」——
    最贴近用户感知的一环。2026-10-12 实测暴露两个真实缺陷：

    1. **REPLACE 与 PASTE 行为雷同**：两者都只是「写剪贴板 + Ctrl+V」，
       没有区分选区状态。选区还在时 PASTE 会把原文替换掉；选区丢了时
       REPLACE 退化成插入。用户看到「点了替换原文，原文还在」。
    2. **返回值恒为 True**：`_send_paste` 吞掉异常且不返回值，于是
       `paste_to_foreground` 只在「设置剪贴板」失败时才返回 False ——
       调用方的「粘贴失败」提示**永远不可达**。

    这两点都已修掉；但第 2 点的修复只覆盖「抛异常」的情况。当系统**静默
    丢弃**合成输入（受限会话 / 提权窗口）时没有任何异常，仍会误报成功 ——
    这正是投递功能被移除的直接原因。

本文件守住上述契约，以及「剪贴板必被还原」「失败不白等 120ms」等。
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

import native.injector as inj_mod
from engine.ai import DeliveryKind
from native.injector import DESELECT_DELAY, RESTORE_DELAY, Injector
from native.selection import SelectionService

# ============================================================
# 夹具
# ============================================================


class _FakeSelection(SelectionService):
    """假剪贴板服务：记录调用顺序，不碰系统剪贴板。"""

    def __init__(self):
        super().__init__()
        self.calls: list = []
        self.text = ""

    def backup(self):
        self.calls.append("backup")
        return {"text/plain": b"saved-content"}

    def restore(self, data):
        self.calls.append("restore")

    def set_clipboard(self, text):
        self.calls.append(("set", text))
        self.text = text


class _FakeKeyboard:
    """假 pynput 控制器：记录按键事件；`fail=True` 时注入即抛异常。"""

    def __init__(self, fail: bool = False):
        self.events: list = []
        self.fail = fail

    def press(self, key):
        if self.fail:
            raise RuntimeError("模拟 pynput 注入失败")
        self.events.append(("press", str(key)))

    def release(self, key):
        self.events.append(("release", str(key)))

    def type(self, ch):
        if self.fail:
            raise RuntimeError("模拟 pynput 注入失败")
        self.events.append(("type", ch))


def _run(clear_selection: bool, text: str = "译文结果", fail: bool = False):
    """跑一次投递，返回 (ok, 按键事件, 假剪贴板)。pump 不真等。"""
    kb = _FakeKeyboard(fail=fail)
    saved_kb = inj_mod.keyboard_controller
    inj_mod.keyboard_controller = lambda: kb
    try:
        svc = _FakeSelection()
        inj = Injector(svc)
        # 不真等 120ms：把 pump 记成事件
        inj._pump = lambda seconds: kb.events.append(("pump", seconds))
        ok = inj.paste_to_foreground(text, clear_selection=clear_selection)
    finally:
        inj_mod.keyboard_controller = saved_kb
    return ok, kb.events, svc


def _has_right(events) -> bool:
    return any(kind == "press" and "right" in name.lower() for kind, name in events)


def _paste_index(events) -> int:
    """Ctrl+V 里 `v` 键的 press 位置；找不到返回 -1。"""
    for i, (kind, name) in enumerate(events):
        if kind == "press" and name.strip("'\"") == "v":
            return i
    return -1


# ============================================================
# 语义分离：REPLACE 不动选区，PASTE 先取消选区
# ============================================================


def test_replace_keeps_selection():
    """「替换原文」不得取消选区 —— 否则 Ctrl+V 变成插入，原文不会被覆盖。"""
    ok, events, svc = _run(clear_selection=False)

    assert ok is True
    assert not _has_right(events), f"替换原文不该发 Right 键，实际事件: {events}"
    assert _paste_index(events) >= 0, "必须发出 Ctrl+V"


def test_paste_clears_selection_before_ctrl_v():
    """「粘贴到前台」必须先取消选区，且取消动作要**排在 Ctrl+V 之前**。"""
    ok, events, svc = _run(clear_selection=True)

    assert ok is True
    assert _has_right(events), f"粘贴到前台该先取消选区，实际事件: {events}"

    right_at = next(i for i, (k, n) in enumerate(events) if k == "press" and "right" in n.lower())
    assert right_at < _paste_index(events), "Right 必须在 Ctrl+V 之前发出"


def test_two_kinds_produce_different_key_sequences():
    """两种投递方式的按键序列必须不同 —— 这是本轮修掉的核心缺陷。"""
    _, replace_events, _ = _run(clear_selection=False)
    _, paste_events, _ = _run(clear_selection=True)

    assert replace_events != paste_events, "REPLACE 与 PASTE 仍走同一条路径"


# ============================================================
# 成功判定：失败必须如实上报
# ============================================================


def test_paste_returns_false_when_injection_fails():
    """按键注入失败时必须返回 False —— 否则「粘贴失败」提示不可达。"""
    ok, events, svc = _run(clear_selection=False, fail=True)

    assert ok is False, "注入失败却报了成功（旧缺陷回归）"


def test_paste_restores_clipboard_even_on_failure():
    """失败也要还原剪贴板 —— 不能因为注入失败就把用户剪贴板留在译文上。"""
    ok, events, svc = _run(clear_selection=False, fail=True)

    assert ok is False
    assert "restore" in svc.calls, f"剪贴板未被还原，调用序列: {svc.calls}"
    assert ("set", "译文结果") in svc.calls


def test_paste_skips_pump_when_injection_fails():
    """失败时不该再白等 120ms（pump 只为「等目标应用读走剪贴板」）。"""
    ok, events, svc = _run(clear_selection=False, fail=True)

    assert ok is False
    assert not any(k == "pump" for k, _ in events), "失败后仍执行了固定等待"


def test_paste_pumps_after_success():
    """成功时要等目标应用读走剪贴板再还原（否则会粘到旧内容）。"""
    ok, events, svc = _run(clear_selection=False)

    assert ok is True
    pumps = [v for k, v in events if k == "pump"]
    assert pumps and pumps[0] == RESTORE_DELAY


def test_restore_happens_after_pump():
    """还原必须晚于「等目标应用读走剪贴板」，否则粘贴会拿到旧内容。"""
    kb = _FakeKeyboard()
    saved_kb = inj_mod.keyboard_controller
    inj_mod.keyboard_controller = lambda: kb
    try:
        svc = _FakeSelection()
        inj = Injector(svc)
        inj._pump = lambda s: svc.calls.append("pump")
        inj.paste_to_foreground("译文", clear_selection=False)
    finally:
        inj_mod.keyboard_controller = saved_kb

    assert svc.calls.index("pump") < svc.calls.index("restore")


# ============================================================
# 边界
# ============================================================


def test_empty_text_is_a_noop():
    """空文本直接返回 False，且**完全不碰**剪贴板与键盘。"""
    ok, events, svc = _run(clear_selection=False, text="")

    assert ok is False
    assert svc.calls == [], f"空文本不该碰剪贴板，实际: {svc.calls}"
    assert events == [], f"空文本不该发按键，实际: {events}"


def test_restore_clipboard_can_be_skipped():
    """`restore_clipboard=False` 时只写不还原（供调用方自行管理剪贴板）。"""
    kb = _FakeKeyboard()
    saved_kb = inj_mod.keyboard_controller
    inj_mod.keyboard_controller = lambda: kb
    try:
        svc = _FakeSelection()
        inj = Injector(svc)
        inj._pump = lambda s: None
        ok = inj.paste_to_foreground("译文", restore_clipboard=False)
    finally:
        inj_mod.keyboard_controller = saved_kb

    assert ok is True
    assert "backup" not in svc.calls and "restore" not in svc.calls


def test_deselect_delay_is_small():
    """取消选区与 Ctrl+V 之间的缓冲要小 —— 否则投递手感发涩。"""
    assert 0 < DESELECT_DELAY <= 0.05


# ============================================================
# type_text（兜底通道）
# ============================================================


def test_type_text_reports_success_and_failure():
    kb = _FakeKeyboard()
    saved_kb = inj_mod.keyboard_controller
    inj_mod.keyboard_controller = lambda: kb
    try:
        inj = Injector(_FakeSelection())
        assert inj.type_text("abc", interval=0) is True
        assert [v for k, v in kb.events if k == "type"] == ["a", "b", "c"]

        bad = _FakeKeyboard(fail=True)
        inj_mod.keyboard_controller = lambda: bad
        assert Injector(_FakeSelection()).type_text("abc", interval=0) is False
    finally:
        inj_mod.keyboard_controller = saved_kb


def test_type_text_empty_is_false():
    inj = Injector(_FakeSelection())
    assert inj.type_text("") is False


# ============================================================
# 插件层：`_on_delivery` 现在只认「复制」
# ============================================================
#
# 2026-10-12：「替换原文 / 粘贴到前台」从产品里移除（见 AGENTS.md §4.6），
# 于是这一节从「按 kind 分流」变成「非 copy 一律不动」。下面同时锁住
# 「面板只剩一个按钮」——否则移除可能被无意改回去。


class _FakePanel:
    def __init__(self):
        self.status: list = []
        self._output = self

    def content(self) -> str:
        return ""


def _make_plugin():
    from extensions.system.ai_assistant.plugin import AIAssistantPlugin

    p = AIAssistantPlugin()
    p._last_result = "译文结果"
    p._selection = _FakeSelection()
    p._panel = _FakePanel()
    p._panel.set_status = p._panel.status.append
    return p


def test_copy_delivery_writes_clipboard_and_reports():
    """「复制」只写剪贴板。"""
    p = _make_plugin()
    p._on_delivery(DeliveryKind.COPY)

    assert ("set", "译文结果") in p._selection.calls
    assert p._panel.status[-1] == "已复制到剪贴板"


def test_removed_delivery_kinds_do_nothing():
    """replace / paste 已移除 —— 必须彻底无动作，不能偷偷退回「复制」。"""
    p = _make_plugin()
    for kind in (DeliveryKind.REPLACE, DeliveryKind.PASTE):
        p._on_delivery(kind)

    assert p._selection.calls == [], "已移除的投递方式不该碰剪贴板"
    assert p._panel.status == [], "已移除的投递方式不该给任何状态提示"


def test_plugin_no_longer_holds_an_injector():
    """插件不该再持有 Injector —— 接线已断，避免死代码被当成活的。"""
    p = _make_plugin()
    assert not hasattr(p, "_injector")


def test_delivery_without_result_is_noop():
    """没有结果时任何投递方式都不该动作。"""
    p = _make_plugin()
    p._last_result = ""
    for kind in DeliveryKind.ALL:
        p._on_delivery(kind)
    assert p._selection.calls == []
    assert p._panel.status == []


def test_panel_offers_only_the_copy_button():
    """面板的投递行只剩「复制」一个按钮。"""
    from PySide6.QtWidgets import QPushButton

    from presentation.ai_panel import AIPanel

    panel = AIPanel()
    labels = [b.text() for b in panel._actions.findChildren(QPushButton)]
    assert labels == ["复制"], f"投递按钮应为 ['复制']，实际 {labels}"
    assert "替换原文" not in labels
    assert "粘贴到前台" not in labels
    panel.deleteLater()

