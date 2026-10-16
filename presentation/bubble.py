# -*- coding: utf-8 -*-
"""独立顶层气泡 —— 桌宠与悬浮球共用。

为什么不做成「窗口内的 QLabel」（原来就是这么写的）
    外壳的窗口尺寸由**形态**决定：桌宠 200×200、球只有 64×64。
    气泡要 160px 宽，放进窗口里的话：
      · 球上根本放不下，会被窗口裁掉；
      · 桌宠上勉强放得下，但气泡压在精灵图顶上，看着像贴在脸上。
    改成独立顶层窗口后，两种形态共用一套气泡，且完全不占窗口尺寸 ——
    这是「形态可换」逼出来的必要改动，不是顺手美化。

为什么 `WA_TransparentForMouseEvents`
    气泡是**纯展示**。它浮在锚点上方几像素处，如果吃鼠标事件，
    用户点球的上半部分就会点空 —— 而球正是靠点击触发反馈的。
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

#: 气泡与锚点之间的间距（逻辑像素）。
_GAP = 6

#: 气泡最大宽度。够放一句完整的中文提示，又不会横着铺满屏幕。
_MAX_WIDTH = 240


class Bubble(QWidget):
    """浮在锚点控件上方的纯展示气泡。"""

    def __init__(self):
        super().__init__(None)          # 顶层窗口，刻意不挂父控件
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # 纯展示，不吃鼠标 —— 否则浮在球上方会挡住点球
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self._label = QLabel(self)
        self._label.setObjectName("petBubble")   # 样式沿用全局 QSS 的这条规则
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setWordWrap(True)
        self._label.setMaximumWidth(_MAX_WIDTH)
        lay.addWidget(self._label)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    # ----- 对外 -----

    def show_text(self, text: str, anchor: QWidget, duration_ms: int = 3000) -> None:
        """在 `anchor` 上方显示 `text`，`duration_ms` 后自动隐藏。"""
        if not text:
            return
        self._label.setText(text)
        self.adjustSize()
        self._place(anchor)
        self.show()
        self._timer.start(max(300, int(duration_ms)))

    def follow(self, anchor: QWidget) -> None:
        """锚点移动后重新摆位（拖动时跟着走）。未显示则什么都不做。"""
        if self.isVisible():
            self._place(anchor)

    def text(self) -> str:
        return self._label.text()

    # ----- 内部 -----

    def _place(self, anchor: QWidget) -> None:
        """摆在锚点上方居中；上方放不下就翻到下方；始终留在屏幕可用区内。"""
        rect = anchor.frameGeometry()
        screen = QGuiApplication.screenAt(rect.center()) or QGuiApplication.primaryScreen()
        if screen is None:
            self.move(rect.center().x(), rect.top() - self.height() - _GAP)
            return
        avail = screen.availableGeometry()

        x = rect.center().x() - self.width() // 2
        y = rect.top() - self.height() - _GAP
        if y < avail.top():
            # 上方放不下（球贴着屏幕顶端时很常见）→ 翻到下方
            y = rect.bottom() + _GAP
        x = max(avail.left(), min(x, avail.right() - self.width() + 1))
        y = max(avail.top(), min(y, avail.bottom() - self.height() + 1))
        self.move(QPoint(x, y))
