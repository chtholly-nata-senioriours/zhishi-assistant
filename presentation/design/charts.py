# -*- coding: utf-8 -*-
"""图表类控件 —— 数字块 / 排行条 / 时间轴 / 柱状图。

为什么单独一个文件
    `widgets.py` 放的是「通用控件」（按钮 / 列表 / 日志视图），
    这里放的是「把数据画成形状」的控件。两者的改动理由完全不同，
    混在一起会让 `widgets.py` 越来越难读。

两条硬规矩
    1. **颜色一律从 `theme().color(...)` 取**，绝不写死 `#RRGGBB`。
       图表是最容易顺手写死颜色的地方，一旦写死，换主题时时间轴还是
       深色那套颜色，跟周围控件对不上。
    2. **合并 / 聚合逻辑不在这里** —— 那些在 `engine.activity.timeline`
       （纯函数、有测试钉死）。这里只负责「拿到已经是最终形状的数据，画出来」。
       渲染代码里的计算没法单测，一旦算错是**静默画错**。
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import icons
from .theme import theme
from .tokens import ICON_SIZE, SPACING
from .widgets import ThemedWidget

#: 类别 → 颜色 token。没匹配上的走 `chart_other`。
_CATEGORY_TOKENS: Dict[str, str] = {
    "工作": "chart_work",
    "沟通": "chart_comm",
    "浏览": "chart_browse",
}

DEFAULT_CATEGORY_TOKEN = "chart_other"


def category_color_token(category: Optional[str]) -> str:
    """把活动类别映射到图表颜色 token。"""
    return _CATEGORY_TOKENS.get(str(category or "").strip(), DEFAULT_CATEGORY_TOKEN)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


# ================================================================
# 数字块
# ================================================================

class StatTile(QFrame, ThemedWidget):
    """概览区的数字块：图标 + 小字标签，下面一个大数字。

    `value` 用字符串而不是数字：调用方要显示的是「4h30m」这种已经
    格式化好的文本（格式化在 `engine.activity.summary.human_duration`，
    那里有测试）。控件不该再实现一遍时长格式。

    为什么加图标（P2.15）
        概览是「数据」这条核心的头条区，但四个数字块原来长得一模一样 ——
        没有识别锚点，扫视时只能逐个读文字。图标给每块一个一眼可辨的身份，
        也让这一块和下面自绘的时间轴 / 排行条看起来是同一套语言。

    为什么有 `primary` 变体
        四个指标不是同等重要：「今日总时长」是这一页的**头条数字**，
        其余三个是它的分解。全部一样大等于没有重点。primary 那格
        换 accent 软底 + 更大字号 + accent 色数字 —— 是整页唯一的彩色底块。
    """

    def __init__(self, label: str, value: str = "—", parent=None,
                 icon_name: Optional[str] = None, primary: bool = False):
        super().__init__(parent)
        self.setObjectName("statTile")
        self._icon_name = icon_name
        self._primary = bool(primary)
        if self._primary:
            self.setProperty("primary", "true")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(SPACING["md"], SPACING["md"], SPACING["md"], SPACING["md"])
        lay.setSpacing(SPACING["xs"])

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(SPACING["xs"])

        self._icon = QLabel(self)
        self._icon.setObjectName("statTileIcon")
        self._label = QLabel(label, self)
        self._label.setObjectName("statTileLabel")
        self._value = QLabel(value, self)
        self._value.setObjectName("statTileValue")
        if self._primary:
            # 属性同时挂在值标签上：QSS 的后代选择器（父带属性、子改样式）
            # 在这种场景下不够稳，直接给子控件也打一份最省事。
            self._value.setProperty("primary", "true")

        head.addWidget(self._icon)
        head.addWidget(self._label)
        head.addStretch(1)
        lay.addLayout(head)
        lay.addWidget(self._value)

        self._sync_icon()
        self._bind_theme()

    # ----- 图标 -----

    def _sync_icon(self) -> None:
        """按当前主题重画图标。primary 那格用强调色，其余用次要文字色。"""
        if not self._icon_name:
            self._icon.hide()
            return
        role = "accent" if self._primary else "text_secondary"
        size = ICON_SIZE - 2
        self._icon.setPixmap(icons.themed(self._icon_name, role, size).pixmap(size, size))
        self._icon.show()

    def refresh_theme(self) -> None:
        self._sync_icon()

    # ----- 数据 -----

    def set_value(self, text: str) -> None:
        self._value.setText(text)

    def set_label(self, text: str) -> None:
        self._label.setText(text)

    def value(self) -> str:
        return self._value.text()

    def label(self) -> str:
        return self._label.text()

    def is_primary(self) -> bool:
        return self._primary


class OverviewBoard(QFrame):
    """概览仪表盘：顶边一条 accent 强调线 + 标题 + 一排指标格。

    为什么要给概览单独做一块「台面」
        「今日 / 趋势」是产品两个核心之一，可它们的头条数字原来只是几个
        `surface_alt` 灰块直接摊在页面底色上 —— 浅色主题下 `surface_alt`
        (#F7F7F7) 与 `window` (#F3F3F3) **只差 4 级**，看上去跟「什么都没有」
        一样。结果整页最该被看见的信息，反而是最不显眼的。

        现在收进一块有描边、有标题、顶边一条 accent 线的台面：整页只有
        这一处长这样，扫一眼就知道「这里是重点」。

    为什么顶边线不单独做一个 rule 控件
        `border-top: 3px solid accent` 一行 QSS 就够，多一个控件就多一处
        要跟着主题重刷的地方。
    """

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("overviewBoard")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(SPACING["lg"], SPACING["md"],
                                 SPACING["lg"], SPACING["md"])
        outer.setSpacing(SPACING["sm"])

        self._title = QLabel(title, self)
        self._title.setObjectName("overviewTitle")
        outer.addWidget(self._title)

        self._row = QHBoxLayout()
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(0)
        outer.addLayout(self._row)

        self._tiles: Dict[str, StatTile] = {}

    def add_tile(self, key: str, tile: StatTile, stretch: int = 1) -> None:
        """按加入顺序排成一行；格与格之间自动插一条竖分隔线。"""
        if self._tiles:
            self._row.addWidget(self._separator())
        self._row.addWidget(tile, stretch)
        self._tiles[key] = tile

    def _separator(self) -> QFrame:
        sep = QFrame(self)
        sep.setObjectName("vHairline")
        sep.setFixedWidth(1)
        # 竖向 hairline 必须显式给 Expanding 的高度策略：`Hairline` 控件的
        # 默认竖向策略是 Fixed，直接放进 HBox 会缩成一个点。
        sep.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        return sep

    # ----- 只读访问器（测试与页面回填用）-----

    def tile(self, key: str) -> Optional[StatTile]:
        return self._tiles.get(key)

    def tiles(self) -> List[StatTile]:
        return list(self._tiles.values())

    def stretch_of(self, key: str) -> int:
        """该格在行里的伸展因子 —— 头条格应当比其余格大。

        暴露出来是因为「头条更宽」这个设计意图没法用像素断言：
        页面本身在测试里不会真正 show，布局不跑，`width()` 全是默认值。
        所以改成断言页面**给对了伸展因子**，而「伸展因子真的会变宽」
        由 `test_design.py` 的组件级像素用例守。
        """
        tile = self._tiles.get(key)
        if tile is None:
            return 0
        return self._row.stretch(self._row.indexOf(tile))

    def title(self) -> str:
        return self._title.text()


# ================================================================
# 比例条
# ================================================================

class RatioBar(QWidget):
    """一条按比例填充的横条。

    自绘而不是用 `QProgressBar`：后者的样式受平台 style 影响，
    在 Windows 上很难做出「无边框、两端圆角」的效果。
    """

    def __init__(self, parent=None, height: int = 6):
        super().__init__(parent)
        self._ratio = 0.0
        self._token = DEFAULT_CATEGORY_TOKEN
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        theme().changed.connect(self.update)

    def set_ratio(self, ratio: float, token: str = DEFAULT_CATEGORY_TOKEN) -> None:
        self._ratio = _clamp01(ratio)
        self._token = token
        self.update()

    def ratio(self) -> float:
        return self._ratio

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect()
        radius = rect.height() / 2.0
        painter.setPen(Qt.PenStyle.NoPen)

        painter.setBrush(theme().color("chart_track"))
        painter.drawRoundedRect(QRectF(rect), radius, radius)

        width = rect.width() * self._ratio
        if width > 0.5:
            # 最短也画成一个圆点，否则 1% 的条会细得看不见
            painter.setBrush(theme().color(self._token))
            painter.drawRoundedRect(
                QRectF(rect.x(), rect.y(), max(width, float(rect.height())),
                       float(rect.height())),
                radius, radius,
            )


# ================================================================
# 排行条
# ================================================================

class _RankRow(QWidget):
    """排行里的一行：名称 + 数值 + 一条比例条。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(SPACING["sm"])
        self._name = QLabel(self)
        self._name.setObjectName("rankName")
        self._value = QLabel(self)
        self._value.setObjectName("rankValue")
        head.addWidget(self._name)
        head.addStretch(1)
        head.addWidget(self._value)

        lay.addLayout(head)
        self._bar = RatioBar(self)
        lay.addWidget(self._bar)

    def update_row(self, name: str, value_text: str, ratio: float, token: str) -> None:
        self._name.setText(name)
        self._value.setText(value_text)
        self._bar.set_ratio(ratio, token)


class RankBar(QWidget):
    """应用排行：按比例长的横条列表。

    行数是固定的（`limit`），`set_items` 只更新内容不重建控件树 ——
    重建会让滚动位置和焦点在每次刷新时跳掉。
    """

    def __init__(self, parent=None, limit: int = 5):
        super().__init__(parent)
        self._limit = max(1, int(limit))
        self._rows: List[_RankRow] = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(SPACING["sm"])
        for _ in range(self._limit):
            row = _RankRow(self)
            self._rows.append(row)
            lay.addWidget(row)

    def set_items(self, items: Iterable[Dict], *, value_text=None) -> None:
        """`items` 每项：`{"label": str, "value": float, "category": str}`。

        `value_text` 是可选格式化函数（默认把 value 当秒数交给调用方处理）——
        时长格式化留在 `engine.activity.summary`，控件不重复实现。
        """
        rows = list(items or [])
        top = max((float(r.get("value") or 0.0) for r in rows), default=0.0)
        for i, row in enumerate(self._rows):
            if i >= len(rows):
                row.setVisible(False)
                continue
            item = rows[i]
            value = float(item.get("value") or 0.0)
            text = value_text(value) if callable(value_text) else str(item.get("text") or "")
            row.setVisible(True)
            row.update_row(
                str(item.get("label") or ""),
                text,
                (value / top) if top > 0 else 0.0,
                category_color_token(item.get("category")),
            )

    def row_count(self) -> int:
        # 用 isHidden() 而不是 isVisible()：后者要求所有祖先都可见，
        # 控件还没 show 时恒为 False，测不出「隐藏了第几行」。
        return sum(1 for r in self._rows if not r.isHidden())

    # ----- 只读访问器（测试用：验证「数字来自真实分段」） -----

    def name_at(self, index: int) -> str:
        return self._rows[index]._name.text()

    def value_text_at(self, index: int) -> str:
        return self._rows[index]._value.text()


# ================================================================
# 刻度标签
# ================================================================

class AxisLabels(QWidget):
    """在**精确比例位置**摆一排小标签（时间轴刻度 / 柱状图日期）。

    为什么不用 QHBoxLayout
        布局会把标签**自身的宽度**算进空间分配里：5 个等 stretch 的格子
        中心在 10% / 30% / 50% / 70% / 90%，于是「6 点」的刻度会漂到 30%
        而不是 25%。刻度是用来读位置的，漂了就没意义 —— 所以这里在
        `resizeEvent` 里按比例直接算 x 坐标。

    为什么用 QLabel 而不是 `drawText`
        与 `BarChart` 同样的理由：QLabel 走系统字体渲染更清晰，
        也更好做本地化（换语言不用改绘制代码）。
    """

    def __init__(self, parent=None, height: int = 18):
        super().__init__(parent)
        self._labels: List[QLabel] = []
        self._items: List[tuple] = []
        self.setFixedHeight(height)

    def set_labels(self, items: Iterable) -> None:
        """`items`：`[(fraction, text), ...]`，fraction ∈ [0, 1]。"""
        # 必须**立刻**把旧的从控件上摘掉。`deleteLater()` 只是排队删除 ——
        # 在真正销毁之前旧标签仍挂在父控件上、仍然会被绘制，于是换刻度
        # 时会有一帧把新旧两套叠着画出来。P2.14 趋势页切「近 7 天 / 近 30 天」
        # 时目检到的重影就是这个：首刻度糊成一团、底部出现两个「0:00」。
        for label in self._labels:
            label.hide()
            label.setParent(None)
            label.deleteLater()
        self._labels = []
        self._items = []
        for fraction, text in items or []:
            label = QLabel(str(text), self)
            label.setObjectName("axisLabel")
            self._labels.append(label)
            self._items.append((float(fraction), label))
        self._place()

    def count(self) -> int:
        return len(self._labels)

    def text_at(self, index: int) -> str:
        return self._labels[index].text()

    def label_x(self, index: int) -> int:
        """某个刻度标签的左边缘（测试用：验证它落在比例位置上）。

        注意：返回的是**按比例算出的**位置，与它当前是否可见无关 ——
        挤不下时标签会被隐藏，但位置照算（见 `_place`）。
        """
        return self._labels[index].x()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place()

    def _place(self) -> None:
        width = self.width()
        if width <= 0 or not self._items:
            return
        last_right = None
        for fraction, label in self._items:
            label.adjustSize()
            w = label.width()
            if fraction <= 0.0:
                x = 0                       # 第一个左对齐，否则会被裁掉
            elif fraction >= 1.0:
                x = width - w               # 最后一个右对齐
            else:
                x = int(round(width * fraction)) - w // 2
            x = max(0, min(x, max(0, width - w)))
            label.move(x, 0)
            # 刻度是用来读位置的，两个标签叠在一起就都读不出来了。
            # 放不下时**隐藏靠后的那一个**（保留靠前的）—— 密度是按
            # 「应该标几个」定的，能不能放下只有这里才知道（要量实际
            # 字体宽度）。窗口变宽时 `resizeEvent` 会重新放、重新显示。
            if last_right is not None and x < last_right:
                label.setVisible(False)
                continue
            label.setVisible(True)
            last_right = x + w


# ================================================================
# 24 小时时间轴
# ================================================================

class TimelineBar(QWidget):
    """把一天的记录画成一条横向色带。

    为什么自绘
        色块数量随记录变化（可能几块，也可能几十块）。用 QSS + 子控件
        会建出几十个 widget，重绘和布局都变慢；一次 `paintEvent` 画完最省。

    为什么调用方要先合并
        频繁切窗口会留下大量十几秒的小段，不合并就是一堆看不清的细线。
        合并规则在 `engine.activity.timeline.merge_segments`（有测试钉死）。
        本控件只负责画。
    """

    def __init__(self, parent=None, height: int = 26, radius: float = 3.0):
        super().__init__(parent)
        self._segments: List[Dict] = []
        self._start = 0.0
        self._end = 0.0
        self._radius = float(radius)
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        theme().changed.connect(self.update)

    def set_segments(self, segments: Iterable[Dict], *, start: float, end: float) -> None:
        self._segments = list(segments or [])
        self._start = float(start)
        self._end = float(end)
        self.update()

    def segment_count(self) -> int:
        return len(self._segments)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect()

        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), self._radius, self._radius)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme().color("chart_idle"))
        painter.drawPath(path)

        span = self._end - self._start
        if span <= 0 or not self._segments:
            return

        painter.setClipPath(path)
        for seg in self._segments:
            x1 = rect.x() + (float(seg.get("start_at") or 0.0) - self._start) / span * rect.width()
            x2 = rect.x() + (float(seg.get("end_at") or 0.0) - self._start) / span * rect.width()
            width = x2 - x1
            if width <= 0:
                continue
            painter.setBrush(theme().color(category_color_token(seg.get("category"))))
            # 用 drawRect 而不是圆角矩形 —— 相邻色块必须无缝衔接
            painter.drawRect(QRectF(x1, rect.y(), width, rect.height()))


# ================================================================
# 柱状图（趋势页）
# ================================================================

class BarChart(QWidget):
    """按天（或按任意分组）的柱状图。

    只画柱子，不画坐标轴 —— 刻度与日期标签由调用方用 QLabel 排在下面，
    这样文字能用系统字体渲染（比 `drawText` 更清晰，也更好做本地化）。
    """

    def __init__(self, parent=None, height: int = 120, bar_width: int = 26,
                 highlight: Optional[int] = None):
        super().__init__(parent)
        self._rows: List[Dict] = []
        self._value_key = "value"
        self._bar_width = int(bar_width)
        self._highlight = highlight
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        theme().changed.connect(self.update)

    def set_data(self, rows: Iterable[Dict], *, value_key: str = "value",
                 highlight: Optional[int] = None) -> None:
        self._rows = list(rows or [])
        self._value_key = str(value_key)
        self._highlight = highlight
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect()
        rows = self._rows
        if not rows:
            return

        values = [max(0.0, float(r.get(self._value_key) or 0.0)) for r in rows]
        top = max(values) if values else 0.0
        slot = rect.width() / len(rows)
        bar_w = min(self._bar_width, max(4.0, slot * 0.6))
        painter.setPen(Qt.PenStyle.NoPen)

        for i, value in enumerate(values):
            ratio = (value / top) if top > 0 else 0.0
            height = max(2.0, rect.height() * ratio) if value > 0 else 2.0
            x = rect.x() + slot * i + (slot - bar_w) / 2.0
            y = rect.y() + rect.height() - height
            color = QColor(theme().color("chart_work"))
            if self._highlight is not None and i != self._highlight:
                color.setAlpha(140)          # 非高亮日淡一点，突出峰值
            painter.setBrush(color)
            painter.drawRoundedRect(QRectF(x, y, bar_w, height), 3.0, 3.0)

    # ----- 只读访问器（测试用：验证「柱子数 = 天数」「峰值被高亮」） -----

    def count(self) -> int:
        return len(self._rows)

    def highlight(self) -> Optional[int]:
        return self._highlight

    def value_at(self, index: int) -> float:
        return float(self._rows[index].get(self._value_key) or 0.0)
