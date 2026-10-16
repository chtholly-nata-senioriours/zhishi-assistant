# -*- coding: utf-8 -*-
"""glass_widgets —— **兼容垫片**（已废弃）。

本模块原本是一套自绘的「液态玻璃」控件库：20px 大圆角、半透明底、
顶部高光带、OutElastic 回弹动画、Neumorphism 凹槽……它服务于早期的
iOS 风格，与本项目现在的设计取向（VS Code / Win11 原生：扁平、
1px 描边、2~3px 圆角、无阴影、不用弹性动画）**直接冲突**。

现在整个设计系统搬到了 `presentation/design/`：
    tokens / theme / qss / icons / widgets

保留本模块的**唯一**原因
    `extensions/user/` 下的第三方插件（如 giwifi）按老名字导入这里的
    符号。删掉会让它们 import 失败。于是这里把老名字映射到新实现，
    行为按新设计系统走 —— 老插件不需要改一行代码就自动换了皮肤。

**新代码请直接用 `presentation.design`。**
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QPushButton, QWidget

from .design import icons, tokens
from .design.theme import Theme, theme as _theme_fn
from .design.widgets import (
    Button,
    IconButton,
    SegmentedControl,
    ToggleSwitch,
    apply_dialog_surface as _apply_dialog_surface,
    paint_dialog_surface as _paint_dialog_surface,
)

# ================================================================
# 主题
# ================================================================

#: 老名字 → 新 Theme。控件构造参数里的 `theme=` 现在是被忽略的：
#: 主题是全局单例，控件自己订阅 `changed`，不再需要逐个注入。
GlassTheme = Theme


def lerp_color(c1: QColor, c2: QColor, t: float) -> QColor:
    """两色线性插值（纯函数，与主题无关）。"""
    t = max(0.0, min(1.0, t))
    return QColor(
        round(c1.red() + (c2.red() - c1.red()) * t),
        round(c1.green() + (c2.green() - c1.green()) * t),
        round(c1.blue() + (c2.blue() - c1.blue()) * t),
        round(c1.alpha() + (c2.alpha() - c1.alpha()) * t),
    )


# ================================================================
# 设计 token（老键名全部保留）
# ================================================================

SPACING = dict(tokens.SPACING)

#: 老键名 sm/md/lg/dialog 都是「圆角」语义，在新系统里统一收敛到 2px。
#: 保留键名是为了让老代码的 `RADIUS["dialog"]` 还能取到值。
RADIUS = {
    **tokens.RADIUS,
    "sm": tokens.RADIUS["control"],
    "md": tokens.RADIUS["control"],
    "lg": tokens.RADIUS["window"],
    "dialog": tokens.RADIUS["window"],
}


class _StatusColors:
    """语义色的**惰性**取值器。

    老代码写 `STATUS_COLOR["offline"]` 取一个写死的红。现在改成按当前
    主题实时解析 —— 否则深浅两套主题会共用同一个色值，浅色下对比度不够。
    """

    _ROLES = {
        "online": "success",
        "offline": "error",
        "warning": "warning",
        "info": "accent",
    }

    def __getitem__(self, key: str) -> str:
        return _theme_fn().color(self._ROLES.get(key, "accent")).name()

    def get(self, key: str, default=None):
        return self[key] if key in self._ROLES else default

    def keys(self):
        return self._ROLES.keys()

    def __contains__(self, key) -> bool:
        return key in self._ROLES


STATUS_COLOR = _StatusColors()


# ================================================================
# 控件
# ================================================================

class GlassButton(Button):
    """老名字 → 扁平按钮。`primary=True` 映射到强调变体。"""

    def __init__(self, text: str, primary: bool = False, theme=None, parent=None):
        super().__init__(text, variant="accent" if primary else "default", parent=parent)


class LiquidGlassButton(Button):
    """老名字 → 扁平按钮；`set_danger(True)` 映射到危险变体。"""

    #: 老代码会读这个常量算高度
    BUTTON_HEIGHT = tokens.CONTROL_HEIGHT

    def __init__(self, text: str, primary: bool = False, theme=None, parent=None):
        super().__init__(text, variant="accent" if primary else "default", parent=parent)
        self._primary = bool(primary)
        self._danger = False

    def set_danger(self, on: bool) -> None:
        self._danger = bool(on)
        if on:
            self.set_variant("danger")
        else:
            self.set_variant("accent" if self._primary else "default")


class SegmentedSelector(QWidget):
    """老名字 → 扁平分段选择器（无滑动动画）。"""

    modeChanged = Signal(str)

    def __init__(self, mode: str = "light", modes=None, labels=None,
                 theme=None, tooltip: str = "", parent=None):
        super().__init__(parent)
        self._MODES = list(modes or ["light", "dark", "auto"])
        self._LABELS = list(labels or ["白天", "黑夜", "跟随系统"])
        if len(self._MODES) != len(self._LABELS):
            raise ValueError("modes 与 labels 数量必须一致")
        if mode not in self._MODES:
            mode = self._MODES[0]
        self._mode = mode

        from PySide6.QtWidgets import QHBoxLayout

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        self._inner = SegmentedControl(self._LABELS, self._MODES.index(mode), self)
        row.addWidget(self._inner)
        if tooltip:
            self.setToolTip(tooltip)
        self._inner.changed.connect(self._on_changed)

    def _on_changed(self, index: int) -> None:
        self._mode = self._MODES[index]
        self.modeChanged.emit(self._mode)

    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str, animate: bool = True) -> None:
        if mode not in self._MODES:
            return
        self._mode = mode
        self._inner.set_index(self._MODES.index(mode))


class SettingsButton(IconButton):
    """老名字 → 齿轮图标按钮。"""

    def __init__(self, theme=None, parent=None):
        super().__init__("gear", "设置", parent=parent, size=24)


class ThemeToggleButton(IconButton):
    """昼夜切换按钮：浅色时显示月亮，深色时显示太阳。

    行为与老版不同（刻意的）
        老版把「当前是不是深色」当成按钮自己的状态，外部改主题后必须
        手动 `set_dark()` 同步，漏一次图标就和主题对不上。
        新版**只认 `theme()`**：按钮永远反映真实主题。所以 `set_dark()`
        退化成「重新同步一次」，传什么值都不影响结果 —— 保留它是为了让
        老插件不报 AttributeError。
    """

    def __init__(self, dark: bool = False, theme=None, parent=None):
        # dark 参数仅作兼容占位；真正的取值由 refresh_theme 从主题读。
        super().__init__("moon", "切换浅色 / 深色主题", parent=parent, size=24)

    def set_dark(self, dark: bool) -> None:
        """兼容老调用：忽略入参，直接与当前主题对齐。"""
        self.refresh_theme()

    def set_theme(self, t) -> None:
        """主题变了 → 重取图标（颜色与形状一起变）。"""
        self.refresh_theme()

    def refresh_theme(self) -> None:
        # 注意：**不能**调 self.set_icon(...) —— IconButton.set_icon 内部会
        # 反过来调 self.refresh_theme()，而这里已经覆盖了基类实现，
        # 于是变成 refresh_theme → set_icon → refresh_theme 的死循环
        # （实测 RecursionError）。直接改字段再交给基类实现取图标。
        self._dark = _theme_fn().dark
        self._icon_name = "sun" if self._dark else "moon"
        super().refresh_theme()


class TrafficLight(QPushButton):
    """红绿灯圆点（历史遗留，仅少数地方引用）。扁平化：纯色圆点，无高光。"""

    def __init__(self, color: str, hover_color: str, parent=None):
        super().__init__(parent)
        self._color = QColor(color)
        self._hover_color = QColor(hover_color)
        self._hovered = False
        self.setFixedSize(12, 12)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def enterEvent(self, event):
        self._hovered = True
        self.update()

    def leaveEvent(self, event):
        self._hovered = False
        self.update()

    def paintEvent(self, event):
        from PySide6.QtGui import QPainter

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self._hover_color if self._hovered else self._color)
        p.drawEllipse(0, 0, 12, 12)
        p.end()


# ================================================================
# 对话框外观（老 API）
# ================================================================

def apply_dialog_style(dialog, theme=None, dark: bool = False):
    """老 API：给对话框装上无边框 + 置顶 + 透明底 + 应用样式表。

    返回当前 Theme（老代码会拿它去 `theme.color(...)`）。
    """
    _apply_dialog_surface(dialog)
    return _theme_fn()


def paint_dialog_background(dialog, theme=None):
    """老 API：自绘对话框底板（1px 描边 + 2px 圆角，无阴影）。"""
    _paint_dialog_surface(dialog, theme)


def build_card(title: str = "", theme=None) -> tuple:
    """老 API：分组卡片。返回 `(card, layout)`。"""
    from PySide6.QtWidgets import QLabel, QVBoxLayout

    from .design.widgets import Card

    card = Card()
    if title:
        lbl = QLabel(title)
        lbl.setObjectName("sectionLabel")
        card.layout_().addWidget(lbl)
    return card, card.layout_()


__all__ = [
    "GlassTheme", "lerp_color", "SPACING", "RADIUS", "STATUS_COLOR",
    "GlassButton", "LiquidGlassButton", "SegmentedSelector",
    "SettingsButton", "ThemeToggleButton", "TrafficLight", "ToggleSwitch",
    "apply_dialog_style", "paint_dialog_background", "build_card",
]
