# -*- coding: utf-8 -*-
"""design —— 本项目统一的设计系统。

分层
    tokens.py       颜色 / 间距 / 圆角 / 字体 / 尺寸（**唯一**的颜色来源）
    theme.py        Theme 类 + 单例 + 切主题 + 装到 QApplication
    qss.py          从 token 生成全应用样式表与 QPalette（零 hex 字面量）
    icons.py        内联 Lucide 风格 SVG，按主题色着色
    widgets.py      工具栏按钮 / 导航 / 日志视图 / 空状态 / 忙碌反馈…
    charts.py       数字块 / 排行条 / 时间轴 / 柱状图（P2.14 新增）
    advice_card.py  结构化建议卡（结论 / 证据 / 动作，P2.14 新增）

用法
    from presentation.design import theme, set_theme, icons
    from presentation.design.widgets import Button, Card, NavList
    from presentation.design.charts import StatTile, RankBar, TimelineBar

    theme()                 # 当前主题
    theme().color("accent") # 取色（QColor）
    icons.icon("gear")      # 取图标（QIcon，随主题变色）
"""
from . import advice_card, charts, icons, qss, tokens, widgets  # noqa: F401
from .theme import (  # noqa: F401
    CONFIG_KEY,
    THEME_DARK,
    THEME_DEFAULT,
    THEME_LIGHT,
    Theme,
    install,
    is_dark,
    make_font,
    normalize_theme,
    reset_for_tests,
    resolve_theme,
    set_theme,
    theme,
    theme_name,
)
from .tokens import (  # noqa: F401
    CONTROL_HEIGHT,
    FONT_SIZE,
    ICON_SIZE,
    RADIUS,
    ROW_HEIGHT,
    SPACING,
    Palette,
)

__all__ = [
    "theme", "set_theme", "theme_name", "install", "Theme",
    "normalize_theme", "resolve_theme", "is_dark", "make_font",
    "reset_for_tests", "CONFIG_KEY",
    "THEME_DEFAULT", "THEME_LIGHT", "THEME_DARK",
    "SPACING", "RADIUS", "ICON_SIZE", "ROW_HEIGHT", "CONTROL_HEIGHT",
    "FONT_SIZE", "Palette",
    "icons", "qss", "tokens", "widgets", "charts", "advice_card",
]
