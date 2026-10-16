# -*- coding: utf-8 -*-
"""窗口生命周期回归测试：关闭对话框**不应**退出应用

背景（用户实测报的 bug）
    打开「AI 服务设置」对话框，关掉它 —— 整个应用退出了。

根因
    `QApplication.quitOnLastWindowClosed` 默认 True，而本项目两个常驻窗口
    （ShellWindow / AIPanel）都带 `Qt.Tool` 标志；Tool 窗口不计入「最后窗口」
    判定。于是关掉任意 QDialog 时 Qt 认为没有窗口了 → quit。

修复
    presentation/ui_renderer.py::UIManager.initialize() 里
    `app.setQuitOnLastWindowClosed(False)`，退出只由显式 app.quit() 触发
    （托盘/右键菜单「退出」）。

⚠ 这里只做**进程内**的轻量验证；真正的「关掉对话框后事件循环还在不在」
  由 spikes/s6_window_lifecycle.py 用**独立子进程 + 真事件循环**验证 ——
  因为 QApplication 无法销毁重建、quitOnLastWindowClosed 是全局状态，
  同一个进程里没法干净地跑多个对照用例。

运行:
    python tests/test_window_lifecycle.py
    pytest tests/test_window_lifecycle.py -v
"""
import os
import sys
from pathlib import Path

# offscreen 平台：无显示环境也能建窗口（必须在 QApplication 创建前设置）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication

from presentation.ui_renderer import UIManager
from presentation.dialogs import GlassDialog


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


# 进程内只建一次真实 UIManager：QApplication 不能销毁重建，ShellWindow 也别重复建
_MGR = None


def _fresh_manager() -> UIManager:
    """建（或复用）真实 UIManager，并走一遍 initialize()。"""
    global _MGR
    if _MGR is None:
        app = _app()
        # 先还原成 Qt 默认值，这样断言的就是 initialize() 的效果，而不是残留状态
        app.setQuitOnLastWindowClosed(True)
        _MGR = UIManager()
        _MGR.initialize()
    return _MGR


def test_initialize_disables_quit_on_last_window_closed():
    """initialize() 必须把 quitOnLastWindowClosed 关掉（Qt 默认是 True）。"""
    app = _app()
    _fresh_manager()
    assert app.quitOnLastWindowClosed() is False, (
        "initialize() 没有关闭 quitOnLastWindowClosed —— "
        "关闭任意对话框（AI 服务设置等）都会导致整个应用退出"
    )


def test_closing_dialog_does_not_quit_app():
    """真事件循环下：常驻 Tool 窗口在 + 关掉对话框 → 应用存活。

    这是对用户 bug 的最小复现：ShellWindow 是 Qt.Tool 常驻窗口，
    GlassDialog 是普通 QDialog；关掉后者后事件循环必须还活着。
    """
    app = _app()
    mgr = _fresh_manager()

    resident = mgr.window          # 真实 ShellWindow（Qt.Tool）
    assert resident is not None, "UIManager.initialize() 没有创建 ShellWindow"
    resident.show()

    dlg = GlassDialog()
    dlg.show()

    state = {"survived": False}

    QTimer.singleShot(60, dlg.close)   # ← 用户点「关闭」的时刻

    def _probe():
        # 能跑到这里，说明关对话框没有把事件循环带走
        state["survived"] = True
        app.exit(0)

    QTimer.singleShot(400, _probe)
    app.exec()                          # ← 必须真跑事件循环

    dlg.deleteLater()
    assert state["survived"] is True, "关闭对话框后应用退出了（事件循环已结束）"


# ============================================================
# 点击置顶（用户报的「打开多窗口时确保点击的窗口在上层」）
# ============================================================

def _press(widget):
    """给控件投递一次鼠标左键按下事件。"""
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent

    pos = QPointF(5, 5)
    ev = QMouseEvent(
        QEvent.Type.MouseButtonPress, pos, pos,
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    widget.mousePressEvent(ev)


def test_raise_to_front_raises_and_activates():
    """混入类本身：raise_to_front 要同时 raise_ + activateWindow。"""
    from PySide6.QtWidgets import QWidget

    from presentation.window_behavior import RaiseOnClickMixin

    calls = []

    class Probe(RaiseOnClickMixin, QWidget):
        def raise_(self):
            calls.append("raise")

        def activateWindow(self):
            calls.append("activate")

    Probe().raise_to_front()
    assert calls == ["raise", "activate"]


def test_raise_to_front_survives_deleted_window():
    """窗口正在关闭时底层对象可能已销毁，层级调整失败不该让点击崩掉。"""
    from PySide6.QtWidgets import QWidget

    from presentation.window_behavior import RaiseOnClickMixin

    class Boom(RaiseOnClickMixin, QWidget):
        def raise_(self):
            raise RuntimeError("Signal source has been deleted")

    Boom().raise_to_front()      # 不抛异常即通过


def test_panel_raises_on_click():
    from presentation.ai_panel import AIPanel

    panel = AIPanel()
    called = []
    panel.raise_to_front = lambda: called.append(1)
    _press(panel)
    assert called == [1], "点击面板没有置顶"


def test_pet_window_flags_and_raise_on_click():
    """桌宠与面板 / 对话框同处置顶层，且点击会置顶。"""
    from PySide6.QtCore import Qt as _Qt

    mgr = _fresh_manager()
    pet = mgr.window
    flags = pet.windowFlags()
    assert bool(flags & _Qt.WindowType.WindowStaysOnTopHint)
    assert bool(flags & _Qt.WindowType.Tool)

    called = []
    pet.raise_to_front = lambda: called.append(1)
    _press(pet)
    assert called == [1], "点击桌宠没有置顶"


def test_dialog_raises_on_click():
    dlg = GlassDialog()
    called = []
    dlg.raise_to_front = lambda: called.append(1)
    _press(dlg)
    assert called == [1], "点击对话框没有置顶"


if __name__ == "__main__":
    test_initialize_disables_quit_on_last_window_closed()
    print("[PASS] test_initialize_disables_quit_on_last_window_closed")
    test_closing_dialog_does_not_quit_app()
    print("[PASS] test_closing_dialog_does_not_quit_app")
    test_raise_to_front_raises_and_activates()
    print("[PASS] test_raise_to_front_raises_and_activates")
    test_raise_to_front_survives_deleted_window()
    print("[PASS] test_raise_to_front_survives_deleted_window")
    test_panel_raises_on_click()
    print("[PASS] test_panel_raises_on_click")
    test_pet_window_flags_and_raise_on_click()
    print("[PASS] test_pet_window_flags_and_raise_on_click")
    test_dialog_raises_on_click()
    print("[PASS] test_dialog_raises_on_click")
    print("\n全部通过")
