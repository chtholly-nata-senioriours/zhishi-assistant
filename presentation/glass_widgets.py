# -*- coding: utf-8 -*-
"""glass_widgets —— 通用"液态玻璃"风格自绘控件库

移植自 GiWiFi-AutoLogin (Yuanxi01/GiWiFi-AutoLogin) tray_app.py 的控件部分，
做了两处关键改造以适配桌宠项目：

1. 去全局化：原版用模块级全局变量 (theme_color/is_glass/APP_FONT 等) 传递主题，
   本版封装为 GlassTheme 类实例，控件通过构造参数注入，多窗口/多主题互不干扰。
2. 去 DWM：原版液态玻璃依赖 Win11 DWM backdrop，本版只用纯 QPainter 绘制，
   跨 Win10/11 安全，与桌宠常驻半透明窗口兼容。

包含控件:
    TrafficLight        macOS 红绿灯圆点按钮
    ToggleSwitch        iOS 风格滑动开关（Q弹回弹动画）
    GlassButton         经典按钮（hover 渐变 + OutElastic 回弹，带焦点环）
    LiquidGlassButton   液态玻璃胶囊按钮（三层自绘，发光 hover + 按压下沉回弹）
    SegmentedSelector   通用分段选择器（指示器滑动动画，可 2~4 段）
    SettingsButton      齿轮图标按钮（矢量绘制）
    ThemeToggleButton   太阳/月亮昼夜切换按钮（矢量绘制）

用法:
    from presentation.glass_widgets import GlassTheme, GlassButton, ToggleSwitch
    theme = GlassTheme(dark=False)
    btn = GlassButton("确定", primary=True, theme=theme, parent=window)
"""
import math

from PySide6.QtCore import (
    Property, Qt, QEasingCurve, QPointF, QRectF, Signal,
    QPropertyAnimation,
)
from PySide6.QtGui import (
    QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import QPushButton, QWidget
from PySide6.QtCore import QSize


# ═══════════════════════════════════════════════════════
#  主题：颜色 token + 字体（替代原版的模块级全局状态）
# ═══════════════════════════════════════════════════════

_LIGHT = {
    "primary": "#3B82F6", "primary_hover": "#2F5FD0",
    "surface": "#FFFFFF", "surface_hover": "#F0F4FA",
    "input_bg": "#E8EEF7", "input_border": "#C9D4E5",
    "text": "#1A2233", "text_sec": "#5A6B85", "text_ter": "#8A99B0",
    "track_off": "#D5DEEC", "focus_ring": "#3B82F6",
}

_DARK = {
    "primary": "#3B82F6", "primary_hover": "#1D4ED8",
    "surface": "#141B2B", "surface_hover": "#1D2739",
    "input_bg": "#0B1120", "input_border": "#2A3648",
    "text": "#E8EEF7", "text_sec": "#9AA6BC", "text_ter": "#5A6B85",
    "track_off": "#253048", "focus_ring": "#60A5FA",
}


def _make_font(size: float, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    f = QFont()
    f.setFamilies(["Source Han Sans CN", "思源黑体", "Microsoft YaHei UI", "微软雅黑", "Segoe UI"])
    f.setPointSizeF(size)
    f.setWeight(weight)
    return f


class GlassTheme:
    """玻璃控件主题（浅色/深色 + 字体）。控件构造时注入，替换原版全局 theme_color()。"""

    def __init__(self, dark: bool = False, font: QFont = None, font_bold: QFont = None):
        self.dark = dark
        self._colors = dict(_DARK if dark else _LIGHT)
        self.font = font or _make_font(10)
        self.font_bold = font_bold or _make_font(10, QFont.Weight.DemiBold)

    def color(self, key: str) -> QColor:
        return QColor(self._colors.get(key, "#FF00FF"))

    def set_dark(self, dark: bool):
        self.dark = dark
        self._colors = dict(_DARK if dark else _LIGHT)


def lerp_color(c1: QColor, c2: QColor, t: float) -> QColor:
    """两色线性插值"""
    t = max(0.0, min(1.0, t))
    return QColor(
        round(c1.red() + (c2.red() - c1.red()) * t),
        round(c1.green() + (c2.green() - c1.green()) * t),
        round(c1.blue() + (c2.blue() - c1.blue()) * t),
        round(c1.alpha() + (c2.alpha() - c1.alpha()) * t),
    )


# ═══════════════════════════════════════════════════════
#  macOS 红绿灯圆点
# ═══════════════════════════════════════════════════════
class TrafficLight(QPushButton):
    def __init__(self, color: str, hover_color: str, parent=None):
        super().__init__(parent)
        self._color = QColor(color)
        self._hover_color = QColor(hover_color)
        self._hovered = False
        self.setFixedSize(14, 14)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def enterEvent(self, event):
        self._hovered = True
        self.update()

    def leaveEvent(self, event):
        self._hovered = False
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        from PySide6.QtCore import Qt
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self._hover_color if self._hovered else self._color)
        p.drawEllipse(1, 1, 12, 12)
        hl = QRadialGradient(QPointF(5, 5), 6)
        hl.setColorAt(0, QColor(255, 255, 255, 80))
        hl.setColorAt(1, QColor(255, 255, 255, 0))
        p.setBrush(hl)
        p.drawEllipse(1, 1, 12, 12)
        p.end()


# ═══════════════════════════════════════════════════════
#  iOS 风格滑动开关（Q弹回弹 + 颜色渐变动画）
# ═══════════════════════════════════════════════════════
class ToggleSwitch(QWidget):
    toggled = Signal(bool)

    # 轨道: x=2, w=50 → 滑块左位中心 x=12, 右位中心 x=42
    _LEFT_X = 1.0
    _RIGHT_X = 31.0

    def __init__(self, text: str = "", checked: bool = False,
                 theme: GlassTheme = None, parent=None):
        super().__init__(parent)
        self._theme = theme or GlassTheme()
        self._text = text
        self._checked = checked
        self._circle_x = self._RIGHT_X if checked else self._LEFT_X
        self._bg_color = self._theme.color("primary") if checked else self._theme.color("track_off")
        self.setFixedSize(58 + (len(text) * 13 + 8 if text else 0), 30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        # Q 弹回弹：滑块带轻微过冲再落位
        self._anim = QPropertyAnimation(self, b"circle_x")
        self._anim.setDuration(320)
        _back = QEasingCurve(QEasingCurve.Type.OutBack)
        _back.setOvershoot(1.0)
        self._anim.setEasingCurve(_back)

        self._color_anim = QPropertyAnimation(self, b"bg_color")
        self._color_anim.setDuration(250)
        self._color_anim.setEasingCurve(QEasingCurve.Type.InOutCubic)

    def _get_circle_x(self):
        return self._circle_x

    def _set_circle_x(self, v):
        self._circle_x = v
        self.update()

    circle_x = Property(float, _get_circle_x, _set_circle_x)

    def _get_bg_color(self):
        return self._bg_color

    def _set_bg_color(self, c):
        self._bg_color = c
        self.update()

    bg_color = Property(QColor, _get_bg_color, _set_bg_color)

    def isChecked(self):
        return self._checked

    def setChecked(self, v: bool):
        self._checked = v
        target_x = self._RIGHT_X if v else self._LEFT_X
        target_c = self._theme.color("primary") if v else self._theme.color("track_off")
        self._anim.stop()
        self._anim.setStartValue(self._circle_x)
        self._anim.setEndValue(target_x)
        self._anim.start()
        self._color_anim.stop()
        self._color_anim.setStartValue(QColor(self._bg_color))
        self._color_anim.setEndValue(target_c)
        self._color_anim.start()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._checked = not self._checked
            self.setChecked(self._checked)
            self.toggled.emit(self._checked)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        dark = self._theme.dark

        # 内凹轨道（Neumorphism 凹槽：上沿压暗、下沿提亮）
        track = QRectF(2, 4, 50, 22)
        tp = QPainterPath()
        tp.addRoundedRect(track, 11, 11)
        p.fillPath(tp, QColor("#E2E8F2") if not dark else QColor(9, 14, 26))
        p.save()
        p.setClipRect(QRectF(track.x(), track.y(), track.width(), track.height() / 2))
        p.setPen(QPen(QColor(0, 0, 0, 38) if not dark else QColor(0, 0, 0, 150), 2))
        p.drawPath(tp)
        p.restore()
        p.save()
        p.setClipRect(QRectF(track.x(), track.y() + track.height() / 2,
                             track.width(), track.height() / 2))
        p.setPen(QPen(QColor(255, 255, 255, 220) if not dark else QColor(255, 255, 255, 26), 2))
        p.drawPath(tp)
        p.restore()

        # 浮起滑块（投影 + 立体高光；选中态为品牌蓝）
        cx = self._circle_x + 11
        cy = 15.0
        r = 10.0
        p.setPen(Qt.PenStyle.NoPen)

        shadow = QRadialGradient(QPointF(cx, cy + 1.5), r + 4)
        shadow.setColorAt(0.35, QColor(0, 0, 0, 70) if not dark else QColor(0, 0, 0, 160))
        shadow.setColorAt(1, QColor(0, 0, 0, 0))
        p.setBrush(shadow)
        p.drawEllipse(QPointF(cx, cy + 0.5), r + 3, r + 3)

        knob = QRadialGradient(QPointF(cx - r * 0.35, cy - r * 0.4), r * 1.9)
        if self._checked:
            knob.setColorAt(0, QColor(0x5E, 0x8A, 0xF5) if not dark else QColor(0x3B, 0x82, 0xF6))
            knob.setColorAt(1, QColor(0x2F, 0x5F, 0xD0) if not dark else QColor(0x1D, 0x4E, 0xD8))
            ring = QColor(255, 255, 255, 70) if not dark else QColor(0, 0, 0, 60)
        else:
            knob.setColorAt(0, QColor(255, 255, 255) if not dark else QColor(0xD8, 0xDF, 0xEA))
            knob.setColorAt(1, QColor(0xEC, 0xF0, 0xF7) if not dark else QColor(0x9A, 0xA6, 0xBC))
            ring = QColor(0, 0, 0, 30) if not dark else QColor(0, 0, 0, 90)
        p.setBrush(knob)
        p.drawEllipse(QPointF(cx, cy), r, r)
        p.setPen(QPen(ring, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(cx, cy), r, r)

        # 文字
        if self._text:
            p.setPen(self._theme.color("text"))
            p.setFont(self._theme.font)
            p.drawText(QRectF(60, 0, self.width() - 60, 30),
                       Qt.AlignmentFlag.AlignVCenter, self._text)

        p.end()


# ═══════════════════════════════════════════════════════
#  经典玻璃按钮（hover 渐变 + OutElastic 回弹 + 焦点环）
# ═══════════════════════════════════════════════════════
class GlassButton(QPushButton):
    def __init__(self, text: str, primary: bool = False,
                 theme: GlassTheme = None, parent=None):
        super().__init__(text, parent)
        self._theme = theme or GlassTheme()
        self._primary = primary
        self._hover_progress = 0.0
        self._press_scale = 1.0

        self.setFixedHeight(38)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFont(self._theme.font_bold)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)

        self._hover_anim = QPropertyAnimation(self, b"hover_progress")
        self._hover_anim.setDuration(200)
        self._hover_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._bounce_anim = QPropertyAnimation(self, b"press_scale")
        self._bounce_anim.setDuration(350)
        self._bounce_anim.setEasingCurve(QEasingCurve.Type.OutElastic)

    def _get_hp(self):
        return self._hover_progress

    def _set_hp(self, v):
        self._hover_progress = v
        self.update()

    hover_progress = Property(float, _get_hp, _set_hp)

    def _get_ps(self):
        return self._press_scale

    def _set_ps(self, v):
        self._press_scale = v
        self.update()

    press_scale = Property(float, _get_ps, _set_ps)

    def enterEvent(self, event):
        self._hover_anim.setStartValue(self._hover_progress)
        self._hover_anim.setEndValue(1.0)
        self._hover_anim.start()

    def leaveEvent(self, event):
        self._hover_anim.setStartValue(self._hover_progress)
        self._hover_anim.setEndValue(0.0)
        self._hover_anim.start()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._bounce_anim.stop()
            self._press_scale = 0.92
            self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self._bounce_anim.setStartValue(0.92)
        self._bounce_anim.setEndValue(1.0)
        self._bounce_anim.start()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()

        # 应用回弹缩放
        p.translate(w / 2, h / 2)
        p.scale(self._press_scale, self._press_scale)
        p.translate(-w / 2, -h / 2)

        rect = QRectF(1, 1, w - 2, h - 2)
        path = QPainterPath()
        path.addRoundedRect(rect, 10, 10)
        th = self._theme

        if self._primary:
            fill = lerp_color(th.color("primary"), th.color("primary_hover"), self._hover_progress)
            p.fillPath(path, fill)
        else:
            # 浅色主题：淡灰蓝填充+实色描边，避免白底上白按钮糊成一片
            base = th.color("input_bg") if not th.dark else th.color("surface")
            hover = th.color("surface_hover") if not th.dark else th.color("surface_hover")
            fill = lerp_color(base, hover, self._hover_progress)
            p.fillPath(path, fill)
            border = th.color("input_border")
            p.setPen(QPen(QColor(border.red(), border.green(), border.blue(),
                                 200 if not th.dark else 255), 1.2))
            p.drawPath(path)

        # 键盘焦点环（可达性：焦点可见）
        if self.hasFocus():
            ring = QRectF(0.5, 0.5, w - 1, h - 1)
            ring_path = QPainterPath()
            ring_path.addRoundedRect(ring, 10, 10)
            p.setPen(QPen(th.color("focus_ring"), 2))
            p.drawPath(ring_path)

        p.setPen(QColor("white") if self._primary else th.color("text"))
        p.setFont(self.font())
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.text())

        p.end()


# ═══════════════════════════════════════════════════════
#  液态玻璃胶囊按钮（三层自绘：半透明基底 + 顶部高光带 + 白描边）
#  发光 hover（220ms OutCubic）+ 按压下沉 2px/缩放 0.98 回弹（260ms OutBack）
#  高 44px，圆角 = 高度一半（胶囊）；危险变体为红色玻璃
# ═══════════════════════════════════════════════════════
class LiquidGlassButton(QPushButton):
    # 玻璃绘制参数（原 themes/liquid_glass.py 的常量）
    BUTTON_HEIGHT = 44
    BUTTON_RADIUS_RATIO = 0.5
    BUTTON_PRESS_SINK_PX = 2.0
    BUTTON_PRESS_SCALE = 0.98
    BUTTON_BASE_ALPHA = 26
    BUTTON_BASE_HOVER_ALPHA = 66
    BUTTON_HIGHLIGHT_ALPHA = 60
    BUTTON_BORDER_ALPHA = 70
    BUTTON_BORDER_HOVER_ALPHA = 130

    def __init__(self, text: str, primary: bool = False,
                 theme: GlassTheme = None, parent=None):
        super().__init__(text, parent)
        self._theme = theme or GlassTheme()
        self._primary = primary      # 主按钮基底稍亮
        self._danger = False         # 红色玻璃变体（警示动作）
        self._hover_progress = 0.0
        self._press_t = 0.0
        self.setFixedHeight(self.BUTTON_HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFont(self._theme.font_bold)

        self._hover_anim = QPropertyAnimation(self, b"hover_progress")
        self._hover_anim.setDuration(220)
        self._hover_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._press_anim = QPropertyAnimation(self, b"press_t")
        self._press_anim.setDuration(260)
        self._press_anim.setEasingCurve(QEasingCurve.Type.OutBack)

    def _get_hover(self):
        return self._hover_progress

    def _set_hover(self, v):
        self._hover_progress = max(0.0, min(1.0, v))
        self.update()

    hover_progress = Property(float, _get_hover, _set_hover)

    def _get_press(self):
        return self._press_t

    def _set_press(self, v):
        self._press_t = max(0.0, min(1.0, v))
        self.update()

    press_t = Property(float, _get_press, _set_press)

    def set_danger(self, on: bool):
        """红色玻璃变体（用于「下线」等警示动作）"""
        self._danger = on
        self.update()

    def enterEvent(self, event):
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_progress)
        self._hover_anim.setEndValue(1.0)
        self._hover_anim.start()

    def leaveEvent(self, event):
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_progress)
        self._hover_anim.setEndValue(0.0)
        self._hover_anim.start()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_anim.stop()
            self._press_anim.setStartValue(self._press_t)
            self._press_anim.setEndValue(1.0)
            self._press_anim.start()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self._press_anim.stop()
        self._press_anim.setStartValue(self._press_t)
        self._press_anim.setEndValue(0.0)
        self._press_anim.start()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        # 按压派生量：下沉 + 缩放
        sink = self.BUTTON_PRESS_SINK_PX * self._press_t
        scale = 1.0 - (1.0 - self.BUTTON_PRESS_SCALE) * self._press_t
        p.translate(w / 2, h / 2)
        p.scale(scale, scale)
        p.translate(-w / 2, -h / 2 + sink)

        hv = self._hover_progress
        rect = QRectF(1, 1, w - 2, h - 2)
        path = QPainterPath()
        path.addRoundedRect(rect, h * self.BUTTON_RADIUS_RATIO, h * self.BUTTON_RADIUS_RATIO)

        # 第 1 层：半透明基底（悬浮动态加深；危险动作用红色玻璃）
        if self._danger:
            base_a = 110 + int(40 * hv)
            p.fillPath(path, QColor(255, 59, 48, base_a))
        elif not self._theme.dark:
            # 浅色主题：主题色淡染填充（非纯白），白底上轮廓清晰
            tint = self._theme.color("primary")
            base_a = 30 + int(45 * hv)
            if self._primary:
                base_a += 55  # 主按钮饱和度更高
            p.fillPath(path, QColor(tint.red(), tint.green(), tint.blue(), base_a))
        else:
            base_a = self.BUTTON_BASE_ALPHA + int(
                (self.BUTTON_BASE_HOVER_ALPHA - self.BUTTON_BASE_ALPHA) * hv)
            alpha = base_a + (20 if self._primary else 0)
            p.fillPath(path, QColor(255, 255, 255, alpha))

        # 第 2 层：顶部白色高光渐变（上浓下淡，玻璃的"高光带"）
        hl = QLinearGradient(QPointF(0, 0), QPointF(0, h * 0.55))
        top_a = int(self.BUTTON_HIGHLIGHT_ALPHA * (0.55 + 0.45 * hv))
        hl.setColorAt(0.0, QColor(255, 255, 255, top_a))
        hl.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillPath(path, hl)

        # 第 3 层：描边（浅色=主题色实线增强轮廓；深色=白描边玻璃感）
        border_a = self.BUTTON_BORDER_ALPHA + int(
            (self.BUTTON_BORDER_HOVER_ALPHA - self.BUTTON_BORDER_ALPHA) * hv)
        if self._danger:
            p.setPen(QPen(QColor(255, 150, 143, border_a), 1.2))
        elif not self._theme.dark:
            bc = self._theme.color("input_border")
            p.setPen(QPen(QColor(bc.red(), bc.green(), bc.blue(),
                                 180 + int(60 * hv)), 1.2))
        else:
            p.setPen(QPen(QColor(255, 255, 255, border_a), 1.2))
        p.drawPath(path)

        # 文字（深色玻璃上用白字；浅色淡染上用深字保证对比度）
        if self._theme.dark or self._danger:
            p.setPen(QColor("white"))
        else:
            p.setPen(self._theme.color("text"))
        p.setFont(self.font())
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.text())
        p.end()


# ═══════════════════════════════════════════════════════
#  通用分段选择器（2~4 段，指示器 OutBack 滑动）
# ═══════════════════════════════════════════════════════
class SegmentedSelector(QWidget):
    modeChanged = Signal(str)

    def __init__(self, mode: str = "light", modes=None, labels=None,
                 theme: GlassTheme = None, tooltip: str = "", parent=None):
        super().__init__(parent)
        self._theme = theme or GlassTheme()
        self._MODES = modes or ["light", "dark", "auto"]
        self._LABELS = labels or ["白天", "黑夜", "跟随系统"]
        if len(self._MODES) != len(self._LABELS):
            raise ValueError("modes 与 labels 数量必须一致")
        if mode not in self._MODES:
            mode = self._MODES[0]
        self._mode = mode
        self._index = self._MODES.index(mode)
        self._pos = float(self._index)  # 指示器滑动位置（单位：段）
        self.setFixedHeight(36)
        self._hint_width = max(120, len(self._MODES) * 70)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tooltip or " / ".join(self._LABELS))

        self._anim = QPropertyAnimation(self, b"indicator_pos")
        self._anim.setDuration(320)
        ec = QEasingCurve(QEasingCurve.Type.OutBack)
        ec.setOvershoot(1.0)
        self._anim.setEasingCurve(ec)

    def sizeHint(self):
        return QSize(self._hint_width, 36)

    def _get_pos(self):
        return self._pos

    def _set_pos(self, v):
        self._pos = v
        self.update()

    indicator_pos = Property(float, _get_pos, _set_pos)

    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str, animate: bool = True):
        if mode not in self._MODES:
            return
        target = self._MODES.index(mode)
        self._index = target
        self._mode = mode
        self._anim.stop()
        if animate and self._pos != float(target):
            self._anim.setStartValue(self._pos)
            self._anim.setEndValue(float(target))
            self._anim.start()
        else:
            self._pos = float(target)
        self.update()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        seg_w = self.width() / len(self._MODES)
        idx = max(0, min(len(self._MODES) - 1, int(event.position().x() / seg_w)))
        if self._MODES[idx] != self._mode:
            self.set_mode(self._MODES[idx])
            self.modeChanged.emit(self._mode)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        th = self._theme

        # 轨道
        track = QRectF(0.5, 0.5, w - 1, h - 1)
        tp = QPainterPath()
        tp.addRoundedRect(track, 10, 10)
        p.fillPath(tp, th.color("input_bg"))
        p.setPen(QPen(th.color("input_border"), 1))
        p.drawPath(tp)

        # 滑动指示器（Q 弹回弹）
        seg_w = w / len(self._MODES)
        pad = 3.0
        ind = QRectF(pad + self._pos * seg_w, pad, seg_w - pad * 2, h - pad * 2)
        ip = QPainterPath()
        ip.addRoundedRect(ind, 8, 8)
        p.fillPath(ip, th.color("surface"))
        p.setPen(QPen(th.color("input_border"), 1))
        p.drawPath(ip)

        # 各段文字
        for i, label in enumerate(self._LABELS):
            rect = QRectF(i * seg_w, 0, seg_w, h)
            if i == self._index:
                p.setPen(th.color("primary"))
                p.setFont(th.font_bold)
            else:
                p.setPen(th.color("text_sec"))
                p.setFont(th.font)
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)

        p.end()


# ═══════════════════════════════════════════════════════
#  设置图标按钮（自绘齿轮矢量）
# ═══════════════════════════════════════════════════════
class SettingsButton(QPushButton):
    def __init__(self, theme: GlassTheme = None, parent=None):
        super().__init__(parent)
        self._theme = theme or GlassTheme()
        self._hovered = False
        self.setFixedSize(20, 20)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def enterEvent(self, event):
        self._hovered = True
        self.update()

    def leaveEvent(self, event):
        self._hovered = False
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        th = self._theme

        accent = th.color("primary") if self._hovered else th.color("text_ter")
        bg_color = QColor(accent.red(), accent.green(), accent.blue(), 38)
        border_color = QColor(accent.red(), accent.green(), accent.blue(), 102)
        p.setPen(QPen(border_color, 1))
        p.setBrush(bg_color)
        p.drawEllipse(1, 1, 18, 18)

        p.setPen(QPen(accent, 1.3, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.setBrush(Qt.BrushStyle.NoBrush)

        cx, cy = 10.0, 10.0

        # 齿轮外圈（8 个齿）
        outer_r = 7.0
        inner_r = 5.0
        teeth = 8
        angle_step = 360.0 / teeth

        path = QPainterPath()
        for i in range(teeth):
            angle1 = math.radians(i * angle_step - angle_step * 0.2)
            angle2 = math.radians(i * angle_step + angle_step * 0.2)
            angle3 = math.radians(i * angle_step + angle_step * 0.35)
            angle4 = math.radians((i + 1) * angle_step - angle_step * 0.35)

            if i == 0:
                path.moveTo(cx + inner_r * math.cos(angle1), cy + inner_r * math.sin(angle1))

            path.lineTo(cx + outer_r * math.cos(angle1), cy + outer_r * math.sin(angle1))
            path.lineTo(cx + outer_r * math.cos(angle2), cy + outer_r * math.sin(angle2))
            path.lineTo(cx + inner_r * math.cos(angle3), cy + inner_r * math.sin(angle3))
            path.lineTo(cx + inner_r * math.cos(angle4), cy + inner_r * math.sin(angle4))

        path.closeSubpath()
        p.drawPath(path)

        # 中心圆 + 镂空
        p.setBrush(accent)
        p.drawEllipse(QPointF(cx, cy), 2.5, 2.5)
        p.setBrush(bg_color)
        p.drawEllipse(QPointF(cx, cy), 1.2, 1.2)

        p.end()


# ═══════════════════════════════════════════════════════
#  昼夜切换按钮（自绘太阳 / 月亮矢量；亮色显示月亮，暗色显示太阳）
# ═══════════════════════════════════════════════════════
class ThemeToggleButton(QPushButton):
    def __init__(self, dark: bool = False, theme: GlassTheme = None, parent=None):
        super().__init__(parent)
        self._theme = theme or GlassTheme(dark=dark)
        self._dark = dark
        self._hovered = False
        self.setFixedSize(20, 20)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("切换白天 / 黑夜模式")

    def set_dark(self, dark: bool):
        self._dark = dark
        self.update()

    def enterEvent(self, event):
        self._hovered = True
        self.update()

    def leaveEvent(self, event):
        self._hovered = False
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        th = self._theme

        accent = th.color("primary") if self._hovered else th.color("text_ter")
        bg_color = QColor(accent.red(), accent.green(), accent.blue(), 38)
        border_color = QColor(accent.red(), accent.green(), accent.blue(), 102)

        p.setPen(QPen(border_color, 1))
        p.setBrush(bg_color)
        p.drawEllipse(1, 1, 18, 18)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(accent)
        cx, cy = 10.0, 10.0

        if self._dark:
            # 太阳：中心圆 + 8 条光芒
            p.drawEllipse(QPointF(cx, cy), 3.2, 3.2)
            p.setPen(QPen(accent, 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.setBrush(Qt.BrushStyle.NoBrush)
            for i in range(8):
                a = math.radians(i * 45)
                x1, y1 = cx + 5.0 * math.cos(a), cy + 5.0 * math.sin(a)
                x2, y2 = cx + 7.2 * math.cos(a), cy + 7.2 * math.sin(a)
                p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
        else:
            # 月亮：两圆相减得到月牙
            moon = QPainterPath()
            moon.addEllipse(QPointF(cx, cy), 6.0, 6.0)
            cut = QPainterPath()
            cut.addEllipse(QPointF(cx + 2.6, cy - 2.2), 5.2, 5.2)
            p.drawPath(moon.subtracted(cut))

        p.end()


# ═══════════════════════════════════════════════════════
#  统一设计规范（参考同类桌宠 app 的毛玻璃/圆角卡片风格）
#  所有交互对话框共用：间距/圆角 token + 统一样式函数
# ═══════════════════════════════════════════════════════

# 间距 token（像素）
SPACING = {
    "xs": 4,    # 控件内元素间距
    "sm": 8,    # 紧凑行间距
    "md": 12,   # 常规控件间距
    "lg": 16,   # 分组间距
    "xl": 24,   # 页面边距
}

# 圆角 token
RADIUS = {
    "sm": 8,       # 输入框/小控件
    "md": 12,      # 按钮/列表
    "lg": 16,      # 卡片
    "dialog": 20,  # 对话框整体
}

# 语义色（状态圆点/提示）
STATUS_COLOR = {
    "online": "#34C759",   # 绿：在线/成功
    "offline": "#FF3B30",  # 红：离线/错误/危险
    "warning": "#FF9F0A",  # 橙：进行中/警告
    "info": "#3B82F6",     # 蓝：信息/主色
}


def apply_dialog_style(dialog, theme: GlassTheme = None, dark: bool = False) -> GlassTheme:
    """统一对话框外观：无边框 + 透明背景（配合 paint_dialog_background 绘制圆角卡片），
    并统一样式化输入框/列表/滚动条。

    Args:
        dialog: QDialog 实例
        theme: 复用已有 GlassTheme（保持明暗一致）；None 则新建
        dark: theme 为 None 时的明暗选择
    Returns:
        实际使用的 GlassTheme（供控件注入 / paintEvent 使用）
    """
    from PySide6.QtCore import Qt as _Qt

    if theme is None:
        theme = GlassTheme(dark=dark)

    c = theme.color

    dialog.setWindowFlags(dialog.windowFlags() | _Qt.WindowType.FramelessWindowHint)
    dialog.setAttribute(_Qt.WidgetAttribute.WA_TranslucentBackground)

    dialog.setStyleSheet(f"""
        QDialog {{
            background: transparent;
        }}
        QLabel {{ color: {c('text').name()}; background: transparent; }}
        QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox {{
            background: {c('input_bg').name()};
            border: 1px solid {c('input_border').name()};
            border-radius: {RADIUS['sm']}px;
            padding: 6px 10px;
            color: {c('text').name()};
            selection-background-color: {c('primary').name()};
        }}
        QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus {{
            border: 1px solid {c('primary').name()};
        }}
        QListWidget {{
            background: {c('surface_hover').name()};
            border: 1px solid {c('input_border').name()};
            border-radius: {RADIUS['md']}px;
            padding: 4px;
            color: {c('text').name()};
            outline: none;
        }}
        QListWidget::item {{
            border-radius: {RADIUS['sm'] - 2}px;
            padding: 6px 8px;
            margin: 1px 2px;
        }}
        QListWidget::item:selected {{
            background: {c('primary').name()};
            color: #FFFFFF;
        }}
        QListWidget::item:hover:!selected {{
            background: {c('input_bg').name()};
        }}
        QScrollBar:vertical {{
            background: transparent; width: 6px; margin: 4px 2px;
        }}
        QScrollBar::handle:vertical {{
            background: {c('input_border').name()};
            border-radius: 3px; min-height: 30px;
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        QScrollBar:horizontal {{ background: transparent; height: 6px; margin: 2px 4px; }}
        QScrollBar::handle:horizontal {{
            background: {c('input_border').name()};
            border-radius: 3px; min-width: 30px;
        }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
    """)
    return theme


def paint_dialog_background(dialog, theme: GlassTheme):
    """无边框透明对话框的背景绘制：在对话框子类的 paintEvent 开头调用，
    绘制圆角毛玻璃卡片（近不透明保证可读性 + 顶部高光条的玻璃质感）。"""
    from PySide6.QtGui import QPainter, QColor, QPen
    from PySide6.QtCore import Qt as _Qt

    p = QPainter(dialog)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    r = RADIUS["dialog"]
    c = theme.color
    p.setPen(QPen(QColor(c("input_border").red(), c("input_border").green(),
                         c("input_border").blue(), 120), 1))
    p.setBrush(QColor(c("surface").red(), c("surface").green(),
                      c("surface").blue(), 242))
    p.drawRoundedRect(dialog.rect().adjusted(0, 0, -1, -1), r, r)
    # 顶部细高光条（玻璃质感）
    p.setPen(QPen(_Qt.PenStyle.NoPen))
    highlight = QColor(255, 255, 255, 26 if theme.dark else 90)
    p.setBrush(highlight)
    p.drawRoundedRect(0, 0, dialog.width(), r, r, r)
    p.end()


def build_card(title: str = "", theme: GlassTheme = None) -> tuple:
    """创建统一风格的分组卡片容器。

    Returns:
        (card_frame, card_layout) — 把内容控件加入 card_layout 即可
    """
    from PySide6.QtWidgets import QFrame, QVBoxLayout, QLabel

    theme = theme or GlassTheme()
    card = QFrame()
    card.setStyleSheet(f"""
        QFrame {{
            background: {theme.color('surface_hover').name()};
            border-radius: {RADIUS['lg']}px;
        }}
    """)
    layout = QVBoxLayout(card)
    layout.setContentsMargins(SPACING["lg"], SPACING["md"], SPACING["lg"], SPACING["md"])
    layout.setSpacing(SPACING["sm"])
    if title:
        lbl = QLabel(title)
        lbl.setFont(theme.font_bold)
        lbl.setStyleSheet(f"color: {theme.color('text_sec').name()}; border: none;")
        layout.addWidget(lbl)
    return card, layout
