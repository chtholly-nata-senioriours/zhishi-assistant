# -*- coding: utf-8 -*-
"""活动建议对话框（纯 UI，只发信号，不碰业务）。

与 `presentation/ai_panel.py` 同样的分工：对话框负责「显示」与「发出意图」；
数据从哪来、要不要发网络、发什么内容，全部由 `plugin.py` 决定。
这样对话框可以脱离网络与数据库单测。
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
)

from presentation.design.tokens import SPACING
from presentation.design.widgets import Button
from presentation.dialogs import AppDialog

#: 统计范围下拉的选项：(显示名, 天数)
_RANGE_CHOICES = (("今天", 1), ("近 3 天", 3), ("近 7 天", 7))

_DISABLED_HINT = (
    "活动采集当前是关闭的。\n"
    "\n"
    "开启方式：把配置文件里的 activity.enabled 改成 true，然后重启。\n"
    "配置文件位置：~/.pet_demo/user_config.json\n"
    "\n"
    "开启后本插件只记录这些：\n"
    "  · 应用名（如 code.exe）\n"
    "  · 类别（工作 / 娱乐 / 其他）\n"
    "  · 停留时长\n"
    "  · 键盘敲击次数（只有次数，没有按键内容）\n"
    "\n"
    "不会记录：窗口标题、按键内容、剪贴板、截图。"
)


class ActivityAdvisorDialog(AppDialog):
    """活动建议对话框。

    信号
        analyze_requested(int) —— 用户点了「生成建议」，参数是天数
        clear_requested()      —— 用户点了「清空数据」
        range_changed(int)     —— 切换了统计范围（概览需要跟着刷新）
    """

    analyze_requested = Signal(int)
    clear_requested = Signal()
    range_changed = Signal(int)

    def __init__(self, *, target_label: str = "", enabled: bool = True, parent=None):
        super().__init__(parent, title="活动建议")
        self.setMinimumSize(560, 540)

        root = QVBoxLayout(self)
        root.setContentsMargins(
            SPACING["lg"], SPACING["md"], SPACING["lg"], SPACING["md"]
        )
        root.setSpacing(SPACING["sm"])
        root.addWidget(self.make_title_bar("活动建议"))

        # --- 控制行 ---
        row = QHBoxLayout()
        row.setSpacing(SPACING["sm"])
        row.addWidget(QLabel("统计范围", self))
        self._combo_days = QComboBox(self)
        for label, days in _RANGE_CHOICES:
            self._combo_days.addItem(label, days)
        self._combo_days.setCurrentIndex(len(_RANGE_CHOICES) - 1)   # 默认近 7 天
        self._combo_days.currentIndexChanged.connect(
            lambda _=0: self.range_changed.emit(self.selected_days())
        )
        row.addWidget(self._combo_days)
        row.addStretch()
        self._btn_analyze = Button("生成建议", "accent", self, icon_name="send")
        self._btn_analyze.clicked.connect(self._emit_analyze)
        row.addWidget(self._btn_analyze)
        root.addLayout(row)

        # --- 隐私提示：明确写出「什么会出网」 ---
        self._privacy = QLabel(self._privacy_text(target_label), self)
        self._privacy.setObjectName("pageHint")
        self._privacy.setWordWrap(True)
        root.addWidget(self._privacy)

        # --- 本机概览 ---
        root.addWidget(self.make_section_label("本机概览（不出网）"))
        self._overview = QPlainTextEdit(self)
        self._overview.setReadOnly(True)
        self._overview.setPlaceholderText("暂无记录")
        root.addWidget(self._overview, 1)

        # --- AI 建议 ---
        root.addWidget(self.make_section_label("AI 建议"))
        self._advice = QPlainTextEdit(self)
        self._advice.setReadOnly(True)
        self._advice.setPlaceholderText("点「生成建议」后显示")
        root.addWidget(self._advice, 1)

        # --- 底部 ---
        foot = QHBoxLayout()
        self._status = QLabel("", self)
        self._status.setObjectName("pageHint")
        foot.addWidget(self._status, 1)
        self._btn_clear = Button("清空数据", "danger", self)
        self._btn_clear.clicked.connect(self.clear_requested.emit)
        foot.addWidget(self._btn_clear)
        root.addLayout(foot)

        if not enabled:
            self._overview.setPlainText(_DISABLED_HINT)
            self.set_analyzing(False, enabled=False)

    # ----- 对外 -----

    def selected_days(self) -> int:
        return int(self._combo_days.currentData() or 7)

    def set_overview(self, text: str) -> None:
        self._overview.setPlainText(text)

    def set_advice(self, text: str) -> None:
        self._advice.setPlainText(text)

    def append_advice(self, delta: str) -> None:
        """流式追加（AI 逐块回传时用）。"""
        cursor = self._advice.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(delta)
        self._advice.setTextCursor(cursor)

    def clear_advice(self) -> None:
        self._advice.clear()

    def set_status(self, text: str) -> None:
        self._status.setText(text)

    def set_analyzing(self, running: bool, enabled: bool = True) -> None:
        self._btn_analyze.setEnabled(enabled and not running)
        self._btn_analyze.setText("分析中…" if running else "生成建议")
        self._combo_days.setEnabled(enabled and not running)
        self._btn_clear.setEnabled(enabled and not running)

    # ----- 内部 -----

    def _emit_analyze(self) -> None:
        self.analyze_requested.emit(self.selected_days())

    @staticmethod
    def _privacy_text(target_label: str) -> str:
        where = target_label or "你配置的 AI 服务"
        return (
            f"分析时只把「本机概览」那份摘要发送到 {where}；"
            "窗口标题、按键内容、剪贴板、截图都不会发送。"
        )
