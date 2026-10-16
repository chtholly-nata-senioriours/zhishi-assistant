# -*- coding: utf-8 -*-
"""通用控件 —— 全部走 QSS + Theme token，不含自绘颜色。

设计取向（VS Code / Win11 原生）
    · 扁平、1px 描边、2~3px 圆角、无阴影
    · 交互态由 QSS 的 :hover / :pressed / :checked / :disabled 表达
    · 需要换主题时只重取图标与属性，不重建控件树

所有控件都自己订阅 `theme().changed`，因此新增控件不会漏掉主题切换 ——
这是「统一 UI」在代码层面的保障：**订阅制**而不是切换方逐个枚举。
"""
from __future__ import annotations

import html
import re

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QBrush, QCursor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import icons
from .theme import theme
from .tokens import (
    CONTROL_HEIGHT,
    FONT_SIZE_SMALL,
    ICON_SIZE,
    RADIUS,
    ROW_HEIGHT,
    SPACING,
)


# ================================================================
# 基类：自动跟随主题
# ================================================================

class ThemedWidget:
    """订阅 `theme().changed`，主题一变就调用 `refresh_theme()`。

    为什么用订阅而不是让切换方枚举
        枚举一定会漏掉「将来新增的窗口」。订阅制下，新控件只要继承本类
        就自动获得换肤能力，漏不了。
    """

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

    def _bind_theme(self) -> None:
        theme().changed.connect(self.refresh_theme)

    def refresh_theme(self) -> None:
        """子类覆盖：重新取图标 / 重设属性。默认什么都不做。"""


# ================================================================
# 工具栏按钮
# ================================================================

class ToolButton(QToolButton, ThemedWidget):
    """工具栏按钮 —— iconOnly + tooltip，四态由 QSS 表达。"""

    def __init__(self, icon_name: str, tooltip: str = "", parent=None,
                 checkable: bool = False, accent: bool = False):
        super().__init__(parent)
        self._icon_name = icon_name
        self.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self.setToolTip(tooltip)
        self.setCheckable(checkable)
        self.setAutoRaise(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty("accent", "true" if accent else "false")
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.refresh_theme()
        self._bind_theme()

    def refresh_theme(self) -> None:
        self.setIcon(icons.themed(self._icon_name))

    def set_icon(self, name: str) -> None:
        self._icon_name = name
        self.refresh_theme()


class IconButton(QPushButton, ThemedWidget):
    """标题栏 / 行内的小图标按钮。"""

    def __init__(self, icon_name: str, tooltip: str = "", parent=None,
                 danger: bool = False, size: int = ICON_SIZE + 12):
        super().__init__(parent)
        self._icon_name = icon_name
        self.setObjectName("iconButtonDanger" if danger else "iconButton")
        self.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self.setFixedSize(size, size)
        self.setToolTip(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_theme()
        self._bind_theme()

    def refresh_theme(self) -> None:
        # danger 变体：**常态图标用次级文字色，hover 才变红底**（底色由 QSS
        # 的 #iconButtonDanger:hover 给）。VS Code / Win11 的关闭按钮都是这个
        # 行为 —— 一个常年红着的 ✕ 太吵，会抢走标题行的注意力。
        self.setIcon(icons.themed(self._icon_name, "text_secondary"))

    def set_icon(self, name: str) -> None:
        self._icon_name = name
        self.refresh_theme()


# ================================================================
# 普通按钮
# ================================================================

class Button(QPushButton):
    """按钮。`variant` 取 default / accent / danger / flat。"""

    def __init__(self, text: str, variant: str = "default", parent=None,
                 icon_name: str | None = None):
        super().__init__(text, parent)
        self._variant = variant
        self._icon_name = icon_name
        if variant == "accent":
            self.setProperty("accent", "true")
        elif variant == "danger":
            self.setProperty("variant", "danger")
        elif variant == "flat":
            self.setProperty("flat", "true")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(CONTROL_HEIGHT)
        if icon_name:
            self.setIcon(icons.themed(icon_name, "accent_text" if variant == "accent" else "text"))
            self.setIconSize(QSize(ICON_SIZE - 2, ICON_SIZE - 2))

    def set_variant(self, variant: str) -> None:
        self._variant = variant
        for key in ("accent", "variant", "flat"):
            self.setProperty(key, None)
        if variant == "accent":
            self.setProperty("accent", "true")
        elif variant == "danger":
            self.setProperty("variant", "danger")
        elif variant == "flat":
            self.setProperty("flat", "true")
        self.style().unpolish(self)
        self.style().polish(self)


# ================================================================
# 布尔开关（勾选框形态，与扁平工具风格一致）
# ================================================================

class ToggleSwitch(QCheckBox):
    """布尔开关。名字沿用历史 API，形态改成本项目的扁平勾选框。

    早期版本是一个 iOS 风格的胶囊滑块（自绘、带弹性动画），
    与「2px 圆角、1px 描边、不用阴影」的工具风格冲突，故统一成勾选框。
    """

    toggled = Signal(bool)          # 与 QCheckBox 同名信号，显式保留以便类型检查

    def __init__(self, text: str = "", checked: bool = False, theme=None, parent=None):
        super().__init__(text, parent)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def isChecked(self) -> bool:      # noqa: N802 —— 保留历史命名
        return super().isChecked()

    def setChecked(self, value: bool) -> None:  # noqa: N802
        super().setChecked(value)


# ================================================================
# 分段选择器
# ================================================================

class SegmentedControl(QWidget):
    """扁平分段选择器（如「浅色 / 深色」）。

    实现方式刻意用一组 QToolButton + QSS 的 `:checked`，
    而不是自绘指示器 —— 自绘要自己处理主题、动画、DPI，
    而这套风格本来就不需要滑动动画。
    """

    changed = Signal(int)

    def __init__(self, options: list[str], current: int = 0, parent=None,
                 expand: bool = False):
        """分段选择器。

        Args:
            expand: False（默认）按内容收缩，左对齐 —— 放在 QFormLayout 里
                时**必须**保持这个行为：QFormLayout 会把字段控件拉满宽，
                而 QToolButton 的默认尺寸策略是 Expanding，不锁死就会把
                两个分段撑成各占一半、看起来像一条空长条。
                True 时占满可用宽度（如工具栏里的整行切换）。
        """
        super().__init__(parent)
        self._expand = bool(expand)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        for i, label in enumerate(options):
            btn = QToolButton(self)
            btn.setText(label)
            btn.setCheckable(True)
            btn.setAutoRaise(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setProperty("segment", "true")
            btn.setMinimumHeight(CONTROL_HEIGHT)
            btn.setMinimumWidth(64)
            btn.setSizePolicy(
                QSizePolicy.Policy.Expanding if self._expand else QSizePolicy.Policy.Minimum,
                QSizePolicy.Policy.Fixed,
            )
            self._group.addButton(btn, i)
            row.addWidget(btn, 1 if self._expand else 0)
        if not self._expand:
            row.addStretch(1)          # 把分段推到左侧，右边留白
        self._group.idClicked.connect(self.changed.emit)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding if self._expand else QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Fixed,
        )
        self.set_index(current)

    def index(self) -> int:
        return self._group.checkedId()

    def set_index(self, i: int, emit: bool = False) -> None:
        btn = self._group.button(i)
        if btn is not None:
            btn.setChecked(True)
        if emit:
            self.changed.emit(i)


# ================================================================
# 容器类
# ================================================================

class Card(QFrame):
    """分组卡片：1px 描边 + 2px 圆角，不用阴影。"""

    def __init__(self, parent=None, margins: int = SPACING["md"], spacing: int = SPACING["sm"]):
        super().__init__(parent)
        self.setObjectName("card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(margins, margins, margins, margins)
        lay.setSpacing(spacing)
        self._layout = lay

    def layout_(self) -> QVBoxLayout:
        return self._layout


class Hairline(QFrame):
    """1px 分割线（前景色 12% 透明度）。"""

    def __init__(self, vertical: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("vHairline" if vertical else "hairline")
        if vertical:
            self.setFixedWidth(1)
        else:
            self.setFixedHeight(1)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)


class SectionLabel(QLabel):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setObjectName("sectionLabel")


class PageTitle(QLabel):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setObjectName("pageTitle")


class PageHint(QLabel):
    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setObjectName("pageHint")
        self.setWordWrap(True)


class EmptyState(QWidget):
    """空状态：图标 + 标题 + 引导文案（而不是一片空白）。"""

    def __init__(self, icon_name: str, title: str, hint: str = "",
                 parent=None, action: QPushButton | None = None):
        super().__init__(parent)
        self._icon_name = icon_name
        lay = QVBoxLayout(self)
        lay.setContentsMargins(SPACING["xl"], SPACING["xl"], SPACING["xl"], SPACING["xl"])
        lay.setSpacing(SPACING["sm"])
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._icon = QLabel(self)
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._icon, alignment=Qt.AlignmentFlag.AlignCenter)

        self._title = QLabel(title, self)
        self._title.setObjectName("emptyTitle")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._title)

        # 引导文案的标签**总是建**（即使这次没传）—— 这样 `set_text()`
        # 就能在同一块空状态上换文案，不必按「有没有 hint」分两种构造。
        self._hint = QLabel(hint, self)
        self._hint.setObjectName("emptyHint")
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint.setWordWrap(True)
        # 布局用了 AlignCenter，标签会收缩到 sizeHint 宽度 —— 自动换行的
        # 标签在那种情况下会一路缩到「一行两三个字」，把句子折得七零八落。
        # 给一个有意义的宽度区间，换行点才落在词与词之间。
        self._hint.setMinimumWidth(320)
        self._hint.setMaximumWidth(460)
        self._hint.setVisible(bool(hint))
        lay.addWidget(self._hint)

        if action is not None:
            lay.addSpacing(SPACING["xs"])
            lay.addWidget(action, alignment=Qt.AlignmentFlag.AlignCenter)

        self._refresh_icon()
        theme().changed.connect(self._refresh_icon)

    def set_text(self, title: str, hint: str = "") -> None:
        """换掉标题与引导文案 —— 同一块空状态要表达几种不同的「为什么空」。"""
        self._title.setText(title or "")
        self._hint.setText(hint or "")
        self._hint.setVisible(bool(hint))

    def title(self) -> str:
        return self._title.text()

    def hint(self) -> str:
        return self._hint.text()

    def _refresh_icon(self) -> None:
        px = icons.pixmap(self._icon_name, theme().color("text_disabled").name(), 40)
        self._icon.setPixmap(px)


class BusyIndicator(QWidget):
    """忙碌反馈：文字 + 不确定进度条。

    规格要求「禁止界面卡死无提示」，所以任何超过一帧的操作都必须
    有可见反馈 —— 这个控件就是统一的那一份。
    """

    def __init__(self, text: str = "处理中…", parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(SPACING["sm"])
        self._label = QLabel(text, self)
        self._label.setObjectName("statusInfo")
        self._bar = QProgressBar(self)
        self._bar.setRange(0, 0)          # 不确定模式
        self._bar.setTextVisible(False)
        self._bar.setFixedWidth(120)
        row.addWidget(self._label)
        row.addWidget(self._bar)
        row.addStretch()
        self.hide()

    def start(self, text: str | None = None) -> None:
        if text:
            self._label.setText(text)
        self.show()

    def stop(self) -> None:
        self.hide()


class busy_cursor:
    """`with busy_cursor():` —— 耗时操作期间光标转圈。

    用引用计数而不是直接 setOverrideCursor/restoreOverrideCursor：
    嵌套调用时 restore 会过早弹出等待光标。
    """

    _depth = 0

    def __enter__(self):
        busy_cursor._depth += 1
        if busy_cursor._depth == 1:
            QApplication.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))
        return self

    def __exit__(self, *exc):
        busy_cursor._depth = max(0, busy_cursor._depth - 1)
        if busy_cursor._depth == 0:
            try:
                QApplication.restoreOverrideCursor()
            except RuntimeError:
                pass
        return False


# ================================================================
# 左侧导航
# ================================================================

#: 导航项自存的图标名（`UserRole` 已被业务数据占用，另取一格）
_ROLE_NAV_ICON = Qt.ItemDataRole.UserRole + 10


class NavList(QListWidget, ThemedWidget):
    """左侧导航：图标 + 文字，行高紧凑，选中整行高亮。

    支持**分组标题行**（`add_group`）—— 导航项多了以后平铺一长条很难找，
    分成「数据 / 功能 / 系统」三组。分组行不可选中，键盘上下键会自动跳过。
    """

    def __init__(self, parent=None, width: int = 208):
        super().__init__(parent)
        self.setObjectName("navList")
        self.setFixedWidth(width)
        self.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self.setUniformItemSizes(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._items: list[tuple[str, str]] = []
        self._groups: list[QListWidgetItem] = []
        self._bind_theme()

    def add_nav(self, icon_name: str, text: str, data=None) -> QListWidgetItem:
        item = QListWidgetItem(icons.themed(icon_name), text)
        item.setData(Qt.ItemDataRole.UserRole, data if data is not None else text)
        item.setData(_ROLE_NAV_ICON, icon_name)
        item.setSizeHint(QSize(0, ROW_HEIGHT + 4))
        self.addItem(item)
        self._items.append((icon_name, text))
        return item

    def add_group(self, text: str) -> QListWidgetItem:
        """加一个分组标题行（不可选中）。

        为什么用「Enabled 但不可选中」而不是 `NoItemFlags`
            `NoItemFlags` 会让 Qt 按**禁用态**渲染：委托取的是
            `QPalette.Disabled` 组的文字色，`setForeground` 设的
            `QPalette.Normal` 组刷子**不生效**，分组标题会淡到看不见。
            只留 `ItemIsEnabled`（去掉 `ItemIsSelectable`）既选不中、
            又保持正常前景色；键盘上下键会自动跳过它，正是想要的。
        """
        item = QListWidgetItem(text)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        item.setSizeHint(QSize(0, ROW_HEIGHT + 4))
        self.addItem(item)
        self._groups.append(item)
        self._style_group(item)
        return item

    def _style_group(self, item: QListWidgetItem) -> None:
        font = QFont(theme().font)
        font.setPointSize(FONT_SIZE_SMALL)
        font.setBold(True)
        item.setFont(font)
        item.setForeground(QBrush(theme().color("text_secondary")))

    def refresh_theme(self) -> None:
        # 按**条目自身**存的图标名刷新，不再用「行号 → self._items」索引 ——
        # 插了分组标题行以后行号与 _items 下标会错位（会取错图标）。
        for row in range(self.count()):
            item = self.item(row)
            icon_name = item.data(_ROLE_NAV_ICON)
            if icon_name:
                item.setIcon(icons.themed(icon_name))
        for item in self._groups:
            self._style_group(item)


# ================================================================
# 日志视图
# ================================================================

_LOG_RE = re.compile(
    r"^(?P<time>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}[,.]?\d*)\s*"
    r"\[(?P<level>[A-Z]+)\]\s*"
    r"(?P<rest>.*)$"
)

_LEVEL_ROLE = {
    "DEBUG": "log_debug",
    "INFO": "log_info",
    "WARNING": "log_warn",
    "WARN": "log_warn",
    "ERROR": "log_error",
    "CRITICAL": "log_error",
}


class LogView(QPlainTextEdit, ThemedWidget):
    """日志视图：**只有级别标签着色**，正文保持常规灰。

    规格明确「禁止整段彩色文字」—— 整行上色会让长日志无法阅读，
    只有级别标签着色才能在扫读时定位问题行。
    """

    MAX_LINES = 5000

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("logView")
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setFont(theme().font_mono)
        self.setMaximumBlockCount(self.MAX_LINES)
        self._bind_theme()

    def refresh_theme(self) -> None:
        self.setFont(theme().font_mono)

    def set_lines(self, lines) -> None:
        self.clear()
        for line in lines:
            self.append_line(line.rstrip("\n"))
        self.move_to_end()

    def append_line(self, line: str) -> None:
        self.appendHtml(self._render(line))

    def move_to_end(self) -> None:
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _render(self, line: str) -> str:
        m = _LOG_RE.match(line)
        t = theme()
        if not m:
            return f'<span style="color:{t.color("text").name()}">{html.escape(line)}</span>'

        level = m.group("level")
        role = _LEVEL_ROLE.get(level, "log_info")
        time_color = t.color("log_time").name()
        level_color = t.color(role).name()
        text_color = t.color("text").name()
        return (
            f'<span style="color:{time_color}">{html.escape(m.group("time"))}</span> '
            f'<span style="color:{level_color}">[{html.escape(level)}]</span> '
            f'<span style="color:{text_color}">{html.escape(m.group("rest"))}</span>'
        )


# ================================================================
# 数据视图统一配置
# ================================================================

def configure_table(view) -> None:
    """表格/树：紧凑行高 + 整行选中 + 表头区分 + 无网格噪声。"""
    view.setAlternatingRowColors(True)
    view.setShowGrid(False)
    view.setWordWrap(False)
    view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    view.setFrameShape(QFrame.Shape.NoFrame)
    if hasattr(view, "setUniformRowHeights"):
        view.setUniformRowHeights(True)

    vh = view.verticalHeader()
    vh.setDefaultSectionSize(ROW_HEIGHT)
    vh.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
    vh.setVisible(False)

    hh = view.horizontalHeader()
    hh.setHighlightSections(False)
    hh.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    hh.setStretchLastSection(True)


def configure_list(view) -> None:
    """列表：紧凑行高 + 整行选中。"""
    view.setUniformItemSizes(True)
    view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    view.setFrameShape(QFrame.Shape.NoFrame)
    view.setWordWrap(False)


def small_font() -> QFont:
    f = QFont(theme().font)
    f.setPointSizeF(FONT_SIZE_SMALL)
    return f


# ================================================================
# 无边框对话框的公共外观
# ================================================================

#: 无边框窗口靠自绘圆角，必须让窗口背景透明
_DIALOG_QSS_TAIL = """
/* 无边框对话框：窗口本身透明，圆角与描边由 paint_dialog_surface 自绘。
   必须放在最后 —— Qt QSS 中同等特异度下「后写的规则胜出」。 */
QDialog { background: transparent; }
QDialog > QWidget { background: transparent; }
"""


def apply_dialog_surface(dialog) -> None:
    """把无边框 + 置顶 + 透明背景 + 应用样式表一次性装到对话框上。

    为什么对话框要和桌宠 / 面板同处「置顶层」
        Windows 上 `WS_EX_TOPMOST` 窗口**始终**高于非置顶窗口。置顶的
        AI 面板会永久压住没置顶的设置对话框 —— 点也翻不上去。
    """
    dialog.setWindowFlags(
        dialog.windowFlags()
        | Qt.WindowType.FramelessWindowHint
        | Qt.WindowType.WindowStaysOnTopHint
    )
    dialog.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    dialog.setStyleSheet(theme().qss() + _DIALOG_QSS_TAIL)


def paint_dialog_surface(dialog, t=None) -> None:
    """自绘对话框底板：1px 描边 + 2px 圆角，**不用阴影**。

    在对话框子类的 paintEvent 开头调用。
    """
    from PySide6.QtGui import QPainter, QPen

    t = t or theme()
    p = QPainter(dialog)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    r = RADIUS["window"]
    p.setPen(QPen(t.color("border_strong"), 1))
    p.setBrush(t.color("panel"))
    p.drawRoundedRect(dialog.rect().adjusted(0, 0, -1, -1), r, r)
    p.end()
