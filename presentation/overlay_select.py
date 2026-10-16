# -*- coding: utf-8 -*-
"""全屏区域选择遮罩（截图问答用）。

覆盖整个虚拟桌面，半透明压暗背景，拖拽出一个明亮选区。
Esc 取消，松开鼠标即完成。
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

_DIM = QColor(0, 0, 0, 110)
_BORDER = QColor(120, 170, 255, 230)
_MIN_SIZE = 6


class OverlaySelect(QWidget):
    """截图选区遮罩。"""

    selected = Signal(QRect)   # 全局坐标下的选区
    cancelled = Signal()

    def __init__(self, parent=None):
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)

        self._origin: QPoint | None = None
        self._current: QPoint | None = None
        self._spanning = False

    # ----- 生命周期 -----

    def warm_up(self) -> None:
        """启动期预热：在最终尺寸下强制走一遍布局与**首次绘制**，随后隐藏。

        为什么需要（实测）
            遮罩覆盖整个虚拟桌面，且用 `CompositionMode_Clear` 自绘 ——
            首次绘制的代价很高。M2 实测：不预热时按 `Alt+S` 会稳定阻塞主线程
            **94–111ms**（每次必现）；预热后降到与面板同一量级。

            这与 `AIPanel.warm_up()` 是同一个教训：**冷绘制不能留在热路径上**。
            只 `show()`+`hide()` 不够 —— 那会取消首次绘制，成本照样留到真正唤起时。
        """
        from PySide6.QtWidgets import QApplication

        geo = self._virtual_geometry()
        if not geo.isNull():
            self.setGeometry(geo)
        self.setWindowOpacity(0.0)
        self.show()
        self.ensurePolished()
        QApplication.processEvents()
        self.repaint()                 # 真正画一次
        QApplication.processEvents()
        self.hide()
        self.setWindowOpacity(1.0)

    def start(self) -> None:
        """覆盖整个虚拟桌面并显示。"""
        geo = self._virtual_geometry()
        if not geo.isNull():
            self.setGeometry(geo)
        self._origin = None
        self._current = None
        self._spanning = False
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()

    @staticmethod
    def _virtual_geometry() -> QRect:
        screens = QGuiApplication.screens()
        if not screens:
            return QRect()
        union = QRect(screens[0].geometry())
        for s in screens[1:]:
            union = union.united(s.geometry())
        return union

    # ----- 绘制 -----

    def paintEvent(self, event):
        painter = QPainter(self)
        rect = self._selection_rect()

        if rect.isNull() or rect.width() < _MIN_SIZE or rect.height() < _MIN_SIZE:
            painter.fillRect(self.rect(), _DIM)
        else:
            # 选区外压暗
            painter.fillRect(self.rect(), _DIM)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.fillRect(rect, Qt.GlobalColor.transparent)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            pen = QPen(_BORDER)
            pen.setWidth(1)
            painter.setPen(pen)
            painter.drawRect(rect)

        painter.setPen(QColor(230, 230, 230))
        painter.drawText(16, 26, "拖拽框选区域　·　Esc 取消")
        painter.end()

    def _selection_rect(self) -> QRect:
        if self._origin is None or self._current is None:
            return QRect()
        return QRect(self._origin, self._current).normalized()

    # ----- 交互 -----

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._origin = event.position().toPoint()
            self._current = self._origin
            self._spanning = True
            self.update()

    def mouseMoveEvent(self, event):
        if self._spanning:
            self._current = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or not self._spanning:
            return
        self._spanning = False
        rect = self._selection_rect()
        self.hide()

        if rect.width() < _MIN_SIZE or rect.height() < _MIN_SIZE:
            self.cancelled.emit()
            return

        # 转为全局坐标
        top_left = self.mapToGlobal(rect.topLeft())
        self.selected.emit(QRect(top_left, rect.size()))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            self.cancelled.emit()
            return
        super().keyPressEvent(event)
