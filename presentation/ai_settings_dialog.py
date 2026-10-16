# -*- coding: utf-8 -*-
"""AI 服务设置对话框 —— `AIConfigForm` 的对话框外壳。

字段与校验都在 `presentation/ai_config_form.py`（控制中心的「AI 服务」页
用的是同一份实现），这里只负责摆按钮、处理保存前的确认。

热切换靠什么
    `plugin._signature()` 已经是配置指纹，`_ensure_manager()` 在指纹变化时
    重建 `SessionManager`。所以这里只要把配置写回并 emit `applied`，
    插件立刻重建 —— 无需重启。
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QMessageBox, QVBoxLayout

from presentation.design.tokens import SPACING
from presentation.design.widgets import Button
from presentation.dialogs import AppDialog, message_box

from .ai_config_form import AIConfigForm


class AISettingsDialog(AppDialog):
    """AI 服务设置。保存后 emit `applied`，由插件完成热切换。"""

    applied = Signal()

    def __init__(self, parent=None, config=None,
                 busy_check: Optional[Callable[[], bool]] = None):
        super().__init__(parent, title="AI 服务设置")
        self.setFixedSize(600, 500)

        root = QVBoxLayout(self)
        root.setContentsMargins(SPACING["lg"], SPACING["md"], SPACING["lg"], SPACING["md"])
        root.setSpacing(SPACING["sm"])
        root.addWidget(self.make_title_bar("AI 服务设置"))

        self._form = AIConfigForm(self, config=config, busy_check=busy_check)
        self._form.applied.connect(self.applied.emit)
        self._form.busy_changed.connect(self._on_busy)
        root.addWidget(self._form, 1)

        self._btn_test = Button("测试连接", parent=self)
        self._btn_test.clicked.connect(self._form.test)
        cancel = Button("取消", parent=self)
        cancel.clicked.connect(self.reject)
        self._btn_save = Button("保存并生效", "accent", parent=self)
        self._btn_save.clicked.connect(self._save)
        root.addLayout(self.button_row(self._btn_test, cancel, self._btn_save))

        # accept() / reject() 不走 closeEvent，但都会发 finished —— 在这里断开，
        # 保证「测试中关窗」不会让迟到的结果回写到已销毁的控件。
        self.finished.connect(self._form.detach_probe)

    def _on_busy(self, busy: bool) -> None:
        self._btn_test.setEnabled(not busy)
        self._btn_save.setEnabled(not busy)

    def _save(self) -> None:
        ok, title, text = self._form.validate()
        if not ok:
            message_box(self, QMessageBox.Icon.Warning, title, text)
            return

        vals = self._form.collect()
        if not vals["vision_model"]:
            reply = message_box(
                self, QMessageBox.Icon.Question, "视觉模型为空",
                "截图问答（Alt+S）需要一个能看图的模型。\n"
                "留空会让截图问答直接失败。\n\n仍要保存吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        if self._form._busy_check and self._form._busy_check():
            reply = message_box(
                self, QMessageBox.Icon.Question, "正在生成回答",
                "当前有回答正在生成，切换配置会中断它。\n\n继续吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        if self._form.save():
            self.accept()

    def closeEvent(self, event):
        self._form.detach_probe()
        super().closeEvent(event)
