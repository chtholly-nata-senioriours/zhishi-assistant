# -*- coding: utf-8 -*-
"""流式 Markdown 渲染视图。

为什么需要节流
    `QTextDocument.setMarkdown()` 是**全量重排**（O(n)），逐 token 调用总成本 O(n²)。
    S4 spike 实测：200 tokens 时单次重排阻塞主线程约 35ms，尚可接受；
    但回答更长时会线性恶化。因此这里做 60ms 节流 —— 既保证肉眼流畅，
    又把重排次数从「token 数」降到「秒数 × 16」。
"""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QTextBrowser

from .design.theme import theme

_FLUSH_INTERVAL_MS = 60


class MarkdownView(QTextBrowser):
    """支持增量追加的 Markdown 视图。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setOpenExternalLinks(True)
        self.setFrameShape(QTextBrowser.Shape.NoFrame)
        # 字号跟随主题（9pt），**不写死** —— 写死会在高 DPI 或换主题后
        # 与周围控件不一致（原先这里硬编码了 10pt）。
        self._apply_font()
        theme().changed.connect(self._apply_font)

        self._buffer = ""
        self._dirty = False
        self._timer = QTimer(self)
        self._timer.setInterval(_FLUSH_INTERVAL_MS)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._flush)

    def _apply_font(self) -> None:
        self.setFont(theme().font)
        self.document().setDefaultFont(theme().font)

    # ----- 内容 -----

    def clear_content(self) -> None:
        self._buffer = ""
        self._dirty = False
        self._timer.stop()
        self.clear()

    def append_chunk(self, delta: str) -> None:
        """追加一段增量（不立即重排）。"""
        self._buffer += delta
        self._dirty = True
        if not self._timer.isActive():
            self._timer.start()

    def set_content(self, markdown: str) -> None:
        """直接设定完整内容并立即渲染（用于收尾，保证最终结果准确）。"""
        self._buffer = markdown
        self._timer.stop()
        self._dirty = False
        self._render()

    def content(self) -> str:
        return self._buffer

    def flush(self) -> None:
        """强制立即渲染（收尾或需要立刻可见时调用）。"""
        self._timer.stop()
        self._render()

    # ----- 内部 -----

    def _flush(self) -> None:
        if self._dirty:
            self._render()

    def _render(self) -> None:
        self._dirty = False
        scrollbar = self.verticalScrollBar()
        at_bottom = scrollbar.value() >= scrollbar.maximum() - 8
        self.setMarkdown(self._buffer)
        if at_bottom:
            scrollbar.setValue(scrollbar.maximum())
