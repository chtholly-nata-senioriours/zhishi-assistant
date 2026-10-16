# -*- coding: utf-8 -*-
"""交互对话框（统一扁平风格）。

统一由 `AppDialog` 提供：
    · 无边框 + 2px 圆角 + 1px 描边（自绘，不用阴影）
    · 与悬浮球 / AI 面板同处「置顶层」，点击即置顶
    · 标题区可拖拽、`Esc` 关闭
    · 按钮顺序遵循平台习惯：**次要动作在左、确定在右**

为什么不用 `QMessageBox` 做提示框
    1. 按钮顺序固定（Windows 上「确定」在左），改不了。
    2. `QMessageBox.setWindowModality()` 内部会重新套用自己的窗口标志，
       把刚加上的 `WindowStaysOnTopHint` 抹掉 —— 于是提示框会被置顶的
       AI 面板压住。实测：`setWindowFlags(+TOP)` → `0x8043103`（topmost），
       紧接着 `setWindowModality` → `0x8003003`（topmost 没了）。
    3. 静态方法（`QMessageBox.warning()`）只把 parent 设为 owner，
       **不**继承置顶标志。
    所以提示框自己实现，见 `MessageDialog`。
"""
from __future__ import annotations

import re

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QMouseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from engine.ai.types import DeliveryKind, Preset
from presentation.design import icons
from presentation.design.theme import theme
from presentation.design.tokens import SPACING
from presentation.design.widgets import (
    Button,
    IconButton,
    apply_dialog_surface,
    paint_dialog_surface,
)
from presentation.window_behavior import RaiseOnClickMixin
from tools.timer_tool import TomatoTimer

#: 标题区高度（此区域按下鼠标 = 拖拽窗口）
_TITLE_DRAG_H = 44


# ============================================================
# 基类
# ============================================================

class AppDialog(RaiseOnClickMixin, QDialog):
    """所有交互对话框的统一基类。"""

    def __init__(self, parent=None, dark: bool | None = None, title: str = ""):
        super().__init__(parent)
        # dark 参数保留但忽略：主题现在是全局单例，所有窗口天然一致。
        # 留着是为了不破坏老调用方（第三方插件会传 dark=）。
        apply_dialog_surface(self)
        self._drag_pos = None
        self.setWindowTitle(title)
        self._title = title
        theme().changed.connect(self._on_theme_changed)

    # ----- 主题 -----

    @property
    def _theme(self):
        """老代码会读 `dialog._theme.color(...)`。"""
        return theme()

    def _on_theme_changed(self) -> None:
        apply_dialog_surface(self)
        self.update()

    # ----- 绘制 -----

    def paintEvent(self, event):
        paint_dialog_surface(self)

    # ----- 拖拽 + 点击置顶 -----

    def mousePressEvent(self, event: QMouseEvent):
        self.raise_to_front()
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() < _TITLE_DRAG_H:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._drag_pos and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    # ----- 供子类复用的部件 -----

    def make_title_bar(self, text: str) -> QWidget:
        """标题栏：标题 + 右侧关闭按钮（无边框窗口的唯一退出入口）。"""
        bar = QWidget(self)
        bar.setFixedHeight(28)
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(SPACING["sm"])

        lbl = QLabel(text, bar)
        lbl.setFont(theme().font_title)
        row.addWidget(lbl)
        row.addStretch()

        btn = IconButton("close", "关闭（Esc）", bar, danger=True, size=24)
        btn.clicked.connect(self.reject)
        row.addWidget(btn)
        return bar

    def make_section_label(self, text: str) -> QLabel:
        lbl = QLabel(text, self)
        lbl.setObjectName("sectionLabel")
        return lbl

    def make_hint_label(self, text: str) -> QLabel:
        lbl = QLabel(text, self)
        lbl.setObjectName("pageHint")
        lbl.setWordWrap(True)
        return lbl

    def make_status_label(self, text: str, role: str = "text_secondary") -> QLabel:
        """状态文字（带语义色圆点）。"""
        lbl = QLabel(text, self)
        lbl.setTextFormat(Qt.TextFormat.RichText)
        lbl.setText(f'<span style="color:{theme().color(role).name()}">●</span> {text}')
        return lbl

    def button_row(self, *buttons: QPushButton, align_right: bool = True) -> QHBoxLayout:
        """按钮行：默认靠右（次要动作在左、确定在右）。"""
        row = QHBoxLayout()
        row.setSpacing(SPACING["sm"])
        if align_right:
            row.addStretch()
        for b in buttons:
            row.addWidget(b)
        return row


#: 历史名字 —— 第三方插件（giwifi）按这个名字导入。
GlassDialog = AppDialog


# ============================================================
# 消息框
# ============================================================

_ICON_MAP = {
    QMessageBox.Icon.Information: ("info", "accent"),
    QMessageBox.Icon.Question: ("info", "accent"),
    QMessageBox.Icon.Warning: ("alert", "warning"),
    QMessageBox.Icon.Critical: ("x-circle", "error"),
}

_BUTTON_TEXT = {
    QMessageBox.StandardButton.Ok: "确定",
    QMessageBox.StandardButton.Yes: "是",
    QMessageBox.StandardButton.No: "否",
    QMessageBox.StandardButton.Cancel: "取消",
    QMessageBox.StandardButton.Close: "关闭",
    QMessageBox.StandardButton.Save: "保存",
    QMessageBox.StandardButton.Discard: "不保存",
    QMessageBox.StandardButton.Apply: "应用",
    QMessageBox.StandardButton.Reset: "重置",
    QMessageBox.StandardButton.Retry: "重试",
    QMessageBox.StandardButton.Abort: "中止",
    QMessageBox.StandardButton.Ignore: "忽略",
    QMessageBox.StandardButton.YesToAll: "全是",
    QMessageBox.StandardButton.NoToAll: "全否",
}

#: 这些是「肯定」按钮 —— 用强调色，并放在最右
_PRIMARY_BUTTONS = {
    QMessageBox.StandardButton.Ok,
    QMessageBox.StandardButton.Yes,
    QMessageBox.StandardButton.Save,
    QMessageBox.StandardButton.Apply,
    QMessageBox.StandardButton.Retry,
    QMessageBox.StandardButton.YesToAll,
}

#: 按钮从左到右的固定顺序（次要 → 主要），保证「确定在右」
_ORDER = [
    QMessageBox.StandardButton.Cancel,
    QMessageBox.StandardButton.NoToAll,
    QMessageBox.StandardButton.No,
    QMessageBox.StandardButton.Discard,
    QMessageBox.StandardButton.Close,
    QMessageBox.StandardButton.Ignore,
    QMessageBox.StandardButton.Abort,
    QMessageBox.StandardButton.Reset,
    QMessageBox.StandardButton.Apply,
    QMessageBox.StandardButton.Retry,
    QMessageBox.StandardButton.YesToAll,
    QMessageBox.StandardButton.Yes,
    QMessageBox.StandardButton.Save,
    QMessageBox.StandardButton.Ok,
]


class MessageDialog(AppDialog):
    """统一提示框：图标 + 标题 + 正文 + 按钮（确定在右），`Esc` 关闭。"""

    def __init__(self, parent=None, icon=QMessageBox.Icon.Information,
                 title: str = "", text: str = "", buttons=None, default=None):
        super().__init__(parent, title=title)
        self._result = QMessageBox.StandardButton.NoButton

        root = QVBoxLayout(self)
        root.setContentsMargins(SPACING["lg"], SPACING["md"], SPACING["lg"], SPACING["md"])
        root.setSpacing(SPACING["md"])

        head = QHBoxLayout()
        head.setSpacing(SPACING["sm"])
        name, role = _ICON_MAP.get(icon, ("info", "accent"))
        glyph = QLabel(self)
        glyph.setPixmap(icons.pixmap(name, theme().color(role).name(), 20))
        glyph.setFixedWidth(24)
        head.addWidget(glyph, 0, Qt.AlignmentFlag.AlignTop)

        col = QVBoxLayout()
        col.setSpacing(SPACING["xs"])
        title_lbl = QLabel(title, self)
        title_lbl.setFont(theme().font_bold)
        col.addWidget(title_lbl)
        body = QLabel(text, self)
        body.setWordWrap(True)
        body.setMinimumWidth(280)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        col.addWidget(body)
        head.addLayout(col, 1)
        root.addLayout(head)

        row = QHBoxLayout()
        row.setSpacing(SPACING["sm"])
        row.addStretch()
        flags = buttons or QMessageBox.StandardButton.Ok
        # 按 _ORDER 展开成「次要动作在前、确定在后」，于是渲染出来
        # 从左到右就是 取消 / 否 / 是 / 确定 —— 确定永远在最右。
        specs = []
        for flag in _ORDER:
            if (flags & flag) == flag and flag in _BUTTON_TEXT and flag not in [s[0] for s in specs]:
                specs.append((flag, _BUTTON_TEXT[flag]))
        if not specs:                       # 传了未收录的按钮，兜底给一个确定
            specs = [(QMessageBox.StandardButton.Ok, _BUTTON_TEXT[QMessageBox.StandardButton.Ok])]

        self._default_button = None
        for flag, label in specs:
            is_primary = flag in _PRIMARY_BUTTONS
            btn = Button(label, variant="accent" if is_primary else "default", parent=self)
            btn.clicked.connect(lambda _=False, f=flag: self._choose(f))
            row.addWidget(btn)
            if default is not None and flag == default:
                self._default_button = btn
        if self._default_button is None and specs:
            self._default_button = row.itemAt(row.count() - 1).widget()
        root.addLayout(row)

    def _choose(self, flag) -> None:
        self._result = flag
        self.accept()

    def result_button(self):
        return self._result

    def showEvent(self, event):
        super().showEvent(event)
        if self._default_button is not None:
            self._default_button.setDefault(True)
            self._default_button.setFocus()


def message_box(parent, icon, title: str, text: str, buttons=None, default=None):
    """统一的模态提示框 —— **强制置顶**，返回用户点击的按钮。

    用法::

        message_box(self, QMessageBox.Icon.Warning, "配置不完整", "接口地址不能为空。")
        yes = message_box(self, QMessageBox.Icon.Question, "确认", "继续吗？",
                          buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                          default=QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes
    """
    dlg = MessageDialog(parent, icon, title, text, buttons, default)
    dlg.exec()
    return dlg.result_button()


def _build_message_box(parent, icon, title: str, text: str,
                       buttons=None, default=None) -> MessageDialog:
    """构造（不 exec）—— 拆出来是为了能单测窗口标志，不必真的弹窗阻塞。"""
    return MessageDialog(parent, icon, title, text, buttons, default)


# ============================================================
# 文本输入对话框（替代 QInputDialog）
# ============================================================

class TextInputDialog(AppDialog):
    """单行 / 多行文本输入。返回 `(文本, 是否确定)`。"""

    def __init__(self, parent=None, title: str = "", label: str = "",
                 text: str = "", multiline: bool = False):
        super().__init__(parent, title=title)
        root = QVBoxLayout(self)
        root.setContentsMargins(SPACING["lg"], SPACING["md"], SPACING["lg"], SPACING["md"])
        root.setSpacing(SPACING["sm"])
        root.addWidget(self.make_title_bar(title))
        if label:
            root.addWidget(self.make_section_label(label))

        if multiline:
            self._edit = QPlainTextEdit(text, self)
            self._edit.setMinimumSize(360, 160)
        else:
            self._edit = QLineEdit(text, self)
            self._edit.setMinimumWidth(320)
            self._edit.returnPressed.connect(self._ok)
        root.addWidget(self._edit)

        cancel = Button("取消", parent=self)
        cancel.clicked.connect(self.reject)
        ok = Button("确定", variant="accent", parent=self)
        ok.clicked.connect(self._ok)
        root.addLayout(self.button_row(cancel, ok))

        if not multiline:
            self._edit.setFocus()
            self._edit.selectAll()

    def _ok(self) -> None:
        self.accept()

    def value(self) -> str:
        if isinstance(self._edit, QPlainTextEdit):
            return self._edit.toPlainText()
        return self._edit.text()


def ask_text(parent, title: str, label: str, text: str = "",
             multiline: bool = False):
    """`QInputDialog.getText()` 的统一替代。返回 `(文本, ok)`。"""
    dlg = TextInputDialog(parent, title=title, label=label, text=text, multiline=multiline)
    ok = dlg.exec() == QDialog.DialogCode.Accepted
    return dlg.value(), ok


# ============================================================
# 预设编辑
# ============================================================

#: 投递方式展示名（与 `DeliveryKind` 一一对应）。
#: 保留 REPLACE / PASTE 是为了**读旧数据** —— 数据库里可能有历史预设
#: 存着这两个值，展示时不能显示成裸字符串。
DELIVERY_LABELS = [
    (DeliveryKind.PANEL, "面板显示"),
    (DeliveryKind.COPY, "复制到剪贴板"),
    (DeliveryKind.REPLACE, "替换原文（已移除）"),
    (DeliveryKind.PASTE, "粘贴到前台（已移除）"),
    (DeliveryKind.TTS, "语音播报"),
]

#: 新建 / 编辑预设时**可选项**。投递到前台（replace / paste）已于 2026-10-12
#: 移除（见 `AGENTS.md` §4.6），所以不再作为选项出现。
DELIVERY_CHOICES = [
    (DeliveryKind.PANEL, "面板显示"),
    (DeliveryKind.COPY, "复制到剪贴板"),
    (DeliveryKind.TTS, "语音播报"),
]


def delivery_label(kind: str) -> str:
    """把投递方式常量翻译成人话（未知值原样返回）。"""
    for value, label in DELIVERY_LABELS:
        if value == kind:
            return label
    return kind or "面板显示"


class PresetEditDialog(AppDialog):
    """新建 / 编辑**自定义**预设。

    「预设」决定「怎么问」—— 系统提示词 + 默认投递方式。内置预设不可改
    （它们有专门的代码路径与测试），所以这里只产出自定义预设。
    """

    def __init__(self, parent=None, preset: Preset | None = None,
                 taken_ids=()):
        editing = preset is not None
        super().__init__(parent, title="编辑预设" if editing else "新建预设")
        self._taken = {str(i).lower() for i in taken_ids}
        self._editing_id = preset.id if editing else ""
        self.setMinimumWidth(480)

        root = QVBoxLayout(self)
        root.setContentsMargins(SPACING["lg"], SPACING["md"], SPACING["lg"], SPACING["md"])
        root.setSpacing(SPACING["sm"])
        root.addWidget(self.make_title_bar(self.windowTitle()))

        form = QFormLayout()
        form.setSpacing(SPACING["sm"])
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self._edit_name = QLineEdit(self)
        self._edit_name.setPlaceholderText("例如：翻译成文言文")
        form.addRow("名称", self._edit_name)

        self._edit_id = QLineEdit(self)
        self._edit_id.setPlaceholderText("小写字母 / 数字 / - _")
        form.addRow("标识", self._edit_id)

        self._combo_delivery = QComboBox(self)
        for value, label in DELIVERY_CHOICES:
            self._combo_delivery.addItem(label, value)
        form.addRow("默认投递", self._combo_delivery)

        self._edit_desc = QLineEdit(self)
        self._edit_desc.setPlaceholderText("一句话说明这个预设干什么")
        form.addRow("说明", self._edit_desc)
        root.addLayout(form)

        root.addWidget(self.make_section_label("系统提示词"))
        self._edit_prompt = QPlainTextEdit(self)
        self._edit_prompt.setPlaceholderText(
            "写给模型的角色与规则，例如：\n你是专业翻译，只输出译文本身，不要解释……"
        )
        self._edit_prompt.setMinimumHeight(140)
        root.addWidget(self._edit_prompt, 1)

        self._err = self.make_hint_label("")
        self._err.setObjectName("statusErr")
        root.addWidget(self._err)

        cancel = Button("取消", parent=self)
        cancel.clicked.connect(self.reject)
        ok = Button("保存", variant="accent", parent=self)
        ok.clicked.connect(self._on_ok)
        root.addLayout(self.button_row(cancel, ok))

        if editing:
            self._edit_name.setText(preset.name)
            self._edit_id.setText(preset.id)
            # 标识是主键：改了等于「另存为新预设」，容易造成重复条目，故锁死。
            self._edit_id.setEnabled(False)
            self._edit_desc.setText(preset.description)
            self._edit_prompt.setPlainText(preset.system_prompt)
            idx = self._combo_delivery.findData(preset.default_delivery)
            self._combo_delivery.setCurrentIndex(max(0, idx))
        else:
            self._edit_id.setText(self._next_id())

        self._edit_name.setFocus()

    # ----- 内部 -----

    def _next_id(self) -> str:
        n = 1
        while f"custom-{n}" in self._taken:
            n += 1
        return f"custom-{n}"

    @staticmethod
    def _is_safe_id(pid: str) -> bool:
        return bool(re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,31}", pid))

    def _on_ok(self) -> None:
        name = self._edit_name.text().strip()
        pid = self._edit_id.text().strip().lower()
        prompt = self._edit_prompt.toPlainText().strip()

        if not name:
            self._err.setText("名称不能为空。")
            return
        if not pid:
            self._err.setText("标识不能为空。")
            return
        if not self._is_safe_id(pid):
            self._err.setText("标识只能用小写字母、数字、短横线或下划线，且以字母/数字开头。")
            return
        if pid != self._editing_id.lower() and pid in self._taken:
            self._err.setText(f"标识「{pid}」已被占用，换一个。")
            return
        if not prompt:
            self._err.setText("系统提示词不能为空。")
            return

        self._err.setText("")
        self.accept()

    # ----- 结果 -----

    def result_preset(self) -> Preset:
        return Preset(
            id=self._edit_id.text().strip().lower(),
            name=self._edit_name.text().strip(),
            system_prompt=self._edit_prompt.toPlainText().strip(),
            default_delivery=self._combo_delivery.currentData() or DeliveryKind.PANEL,
            description=self._edit_desc.text().strip(),
            builtin=False,
        )


def ask_preset(parent, preset: Preset | None = None, taken_ids=()) -> Preset | None:
    """弹出预设编辑框；用户取消时返回 `None`。"""
    dlg = PresetEditDialog(parent, preset=preset, taken_ids=taken_ids)
    if dlg.exec() == QDialog.DialogCode.Accepted:
        return dlg.result_preset()
    return None


# ============================================================
# 番茄钟
# ============================================================

class TomatoDialog(AppDialog):
    """番茄钟对话框。"""

    def __init__(self, timer: TomatoTimer, parent=None):
        super().__init__(parent, title="番茄钟")
        self.timer = timer
        self.setFixedSize(340, 268)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACING["lg"], SPACING["md"], SPACING["lg"], SPACING["md"])
        layout.setSpacing(SPACING["sm"])
        layout.addWidget(self.make_title_bar("番茄钟"))

        self._time_label = QLabel("25:00", self)
        self._time_label.setObjectName("tomatoClock")
        self._time_label.setProperty("role", "normal")
        self._time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        f = QFont(theme().font_mono)
        f.setPointSizeF(theme().font.pointSizeF() + 22)
        f.setWeight(QFont.Weight.DemiBold)
        self._time_label.setFont(f)
        layout.addWidget(self._time_label)

        self._status_label = QLabel("就绪", self)
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setObjectName("pageHint")
        layout.addWidget(self._status_label)
        layout.addStretch()

        self._btn_start = Button("开始工作", "accent", self)
        self._btn_pause = Button("暂停", parent=self)
        self._btn_resume = Button("继续", "accent", parent=self)
        self._btn_stop = Button("停止", "danger", parent=self)
        self._btn_start.clicked.connect(lambda: self.timer.start("work"))
        self._btn_pause.clicked.connect(self.timer.pause)
        self._btn_resume.clicked.connect(self.timer.resume)
        self._btn_stop.clicked.connect(self.timer.stop)
        layout.addLayout(self.button_row(
            self._btn_start, self._btn_pause, self._btn_resume, self._btn_stop))

        self._tick = QTimer(self)
        self._tick.timeout.connect(self._refresh)
        self._tick.start(1000)
        self._refresh()

    def _refresh(self):
        status = self.timer.get_status()
        state = status["state"]

        # 空闲时显示「本次将要专注多久」，而不是计时器给的 00:00。
        # 后者在一只番茄钟上看起来像坏了 —— 用户第一眼会以为设置丢了。
        # 计时器自身的 `formatted` 语义（空闲 = 00:00，有测试守着）不动，
        # 只改这一处显示。`finished` 仍显示 00:00（倒计时确实走完了）。
        if state == "idle":
            self._time_label.setText(f"{self.timer.work_duration:02d}:00")
        else:
            self._time_label.setText(status["formatted"])

        role = "normal"
        if state == "idle":
            self._status_label.setText(f"就绪 · 今日完成 {status['today_count']} 个")
        elif state == "running":
            if status["type"] == "work":
                self._status_label.setText("专注中，加油")
                role = "accent"
            else:
                self._status_label.setText("休息中，放松一下")
                role = "ok"
        elif state == "paused":
            self._status_label.setText("已暂停")
            role = "warn"
        elif state == "finished":
            self._status_label.setText("已完成")

        # 颜色交给全局 QSS 的 [role="..."] 选择器，这里只切换语义属性
        self._time_label.setProperty("role", role)
        self._time_label.style().unpolish(self._time_label)
        self._time_label.style().polish(self._time_label)

        self._btn_start.setVisible(state in ("idle", "finished"))
        self._btn_pause.setVisible(state == "running")
        self._btn_resume.setVisible(state == "paused")
        self._btn_stop.setVisible(state in ("running", "paused"))

    def closeEvent(self, event):
        self._tick.stop()
        super().closeEvent(event)

