# -*- coding: utf-8 -*-
"""设计令牌 —— 颜色 / 间距 / 圆角 / 字体 / 图标尺寸。

这是整套 UI 的**唯一**颜色来源
    所有颜色都在 `Palette` 里定义，`qss.build_qss()` 从 Palette 生成样式表。
    QSS 字符串里**不允许**出现 `#RRGGBB` 字面量 —— 一旦写死，换主题时它不会变，
    就会重演 P2.6 之前「面板深色、对话框浅色」的割裂。

配色基准
    深色：VS Code Dark+（窗口 #252526 / 面板 #1E1E1E / 强调 #4C8DFF）
    浅色：Windows 11 原生（窗口 #F3F3F3 / 面板 #FFFFFF / 强调 #0067C0）

命名约定
    · `window`  —— 窗口/工具栏底色（最外层）
    · `panel`   —— 内容面板底色（工作区）
    · `surface` —— 列表/卡片底色（在 panel 之上抬一层）
    · `text` / `text_secondary` / `text_disabled` —— 三级灰阶
    · `border`  —— 1px 分割线（前景色 12% 透明度，不用阴影）
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


# ================================================================
# 颜色工具
# ================================================================

def rgba(hex_color: str, alpha: float) -> str:
    """`#RRGGBB` + 透明度(0~1) → QSS 可直接用的 `rgba(r, g, b, a)`。

    为什么不用 `#AARRGGBB`
        Qt 的 QSS 里 `#AARRGGBB` 只在部分选择器生效，行为不一致；
        `rgba()` 是唯一在 QSS / QPalette / QPainter 三处都可靠的形式。
    """
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r}, {g}, {b}, {round(alpha * 255)})"


# 前景色 12% —— 边框与分割线的统一透明度（规格要求，不用阴影）
BORDER_ALPHA = 0.12
BORDER_STRONG_ALPHA = 0.22
# 禁用态 = 主文字 40% 透明度
DISABLED_ALPHA = 0.40


# ================================================================
# 调色板
# ================================================================

@dataclass(frozen=True)
class Palette:
    """一套完整配色。字段名即语义，不要按用途以外的含义复用。"""

    name: str
    dark: bool

    # --- 三层底色 ---
    window: str
    panel: str
    surface: str
    surface_alt: str
    input_bg: str

    # --- 交互态 ---
    hover: str
    selected: str
    selected_text: str
    table_header: str

    # --- 工具栏 ---
    toolbar: str
    toolbar_hover: str
    toolbar_pressed: str
    toolbar_checked: str

    # --- 线与文字 ---
    border: str
    border_strong: str
    text: str
    text_secondary: str
    text_disabled: str

    # --- 强调色 ---
    accent: str
    accent_hover: str
    accent_pressed: str
    accent_text: str
    accent_soft: str          # 强调色 20% 底，用于选中项/徽标

    # --- 语义色 ---
    success: str
    warning: str
    warning_soft: str         # warning 的软底，用于「进行中」这类非交互态
    error: str
    info: str

    # --- 图表（时间轴 / 排行条 / 柱状图）---
    # 为什么图表色也要进 Palette
    #   图表是最容易「顺手写死 #RRGGBB」的地方。一旦写死，换主题时
    #   时间轴还是深色那套颜色，跟周围控件对不上 —— 正是 P2.6 之前
    #   「面板深色、对话框浅色」那种割裂的重演。所以时间轴、排行条、
    #   柱状图的每一块颜色都必须从这里取。
    #
    # 关于 chart_idle / chart_track（踩过一次，别再犯）
    #   时间轴画的是**整天 0:00–24:00**，有记录的部分是彩色块，没记录的部分
    #   就是 chart_idle；排行条的「底槽」是 chart_track。
    #   两者一度都取成「跟页面底色差不多」的值 —— chart_idle 浅色 #F0F0EE
    #   与 window(#F3F3F3) 只差 3 级、深色 #2A2A2B **正好等于** surface_alt；
    #   chart_track 浅色 #ECECEC 与 window 只差 7 级。后果：
    #     · 时间轴上「空闲」那段与页面融为一体，整条轴看起来像
    #       **只画到最后一个色块就断了**（第一次目检就是这么误读的）；
    #     · 排行条的底槽看不见，就分不清那条彩色条「占了多大比例」。
    #   所以这两个值都必须与 window / surface / surface_alt 拉得开，
    #   由 `tests/test_design.py::test_chart_track_and_idle_visible_on_page_bg` 钉死。
    chart_work: str        # 工作
    chart_study: str       # 学习
    chart_comm: str        # 沟通
    chart_fun: str         # 娱乐
    chart_other: str       # 其他
    chart_idle: str        # 空闲 / 无记录（**必须与 window/surface 拉得开**，见下）
    chart_track: str       # 条形底槽（同上）

    # --- 日志级别（只有级别标签着色，正文保持常规灰）---
    log_time: str
    log_info: str
    log_warn: str
    log_error: str
    log_debug: str

    # --- 滚动条 ---
    scrollbar: str
    scrollbar_hover: str

    # --- 其他 ---
    tooltip_bg: str
    tooltip_text: str

    def as_dict(self) -> Dict[str, str]:
        return {k: v for k, v in self.__dict__.items()}


def _make_dark() -> Palette:
    fg = "#FFFFFF"
    return Palette(
        name="dark",
        dark=True,
        window="#252526",
        panel="#1E1E1E",
        surface="#2D2D30",
        surface_alt="#2A2A2B",
        input_bg="#3C3C3C",
        hover="#2A2D2E",
        selected="#094771",
        selected_text="#FFFFFF",
        table_header="#2D2D30",
        toolbar="#2D2D30",
        toolbar_hover=rgba(fg, 0.08),
        toolbar_pressed=rgba(fg, 0.12),
        toolbar_checked=rgba("#4C8DFF", 0.24),
        border=rgba(fg, BORDER_ALPHA),
        border_strong=rgba(fg, BORDER_STRONG_ALPHA),
        text="#CCCCCC",
        text_secondary="#9D9D9D",
        text_disabled=rgba("#CCCCCC", DISABLED_ALPHA),
        accent="#4C8DFF",
        accent_hover="#6BA1FF",
        accent_pressed="#3A7AE8",
        accent_text="#FFFFFF",
        accent_soft=rgba("#4C8DFF", 0.20),
        success="#4EC9B0",
        warning="#D7BA7D",
        warning_soft=rgba("#D7BA7D", 0.20),
        error="#F14C4C",
        info="#4C8DFF",
        chart_work="#4C8DFF",
        chart_study="#5FBF9F",
        chart_comm="#D7BA7D",
        chart_fun="#CE9178",
        chart_other="#7A7A7A",
        chart_idle="#3A3A3E",
        chart_track="#3C3C3C",
        log_time="#6A9955",
        log_info="#CCCCCC",
        log_warn="#DCDCAA",
        log_error="#F14C4C",
        log_debug="#808080",
        scrollbar=rgba(fg, 0.18),
        scrollbar_hover=rgba(fg, 0.35),
        tooltip_bg="#3C3C3C",
        tooltip_text="#CCCCCC",
    )


def _make_light() -> Palette:
    fg = "#000000"
    return Palette(
        name="light",
        dark=False,
        window="#F3F3F3",
        panel="#FFFFFF",
        surface="#FFFFFF",
        surface_alt="#F7F7F7",
        input_bg="#FFFFFF",
        hover="#E5E5E5",
        selected="#0067C0",
        selected_text="#FFFFFF",
        table_header="#ECECEC",
        toolbar="#F3F3F3",
        toolbar_hover=rgba(fg, 0.08),
        toolbar_pressed=rgba(fg, 0.14),
        toolbar_checked=rgba("#0067C0", 0.16),
        border=rgba(fg, BORDER_ALPHA),
        border_strong=rgba(fg, BORDER_STRONG_ALPHA),
        text="#1F1F1F",
        text_secondary="#616161",
        text_disabled=rgba("#1F1F1F", DISABLED_ALPHA),
        accent="#0067C0",
        accent_hover="#1A7AD1",
        accent_pressed="#005AA8",
        accent_text="#FFFFFF",
        accent_soft=rgba("#0067C0", 0.14),
        success="#107C10",
        warning="#9D5D00",
        warning_soft=rgba("#9D5D00", 0.14),
        error="#C42B1C",
        info="#0067C0",
        chart_work="#5B9BD5",
        chart_study="#3E9E7E",
        chart_comm="#E8A33D",
        chart_fun="#E07B5A",
        chart_other="#A8A8A0",
        chart_idle="#E0E0DC",
        chart_track="#DCDCDC",
        log_time="#008000",
        log_info="#1F1F1F",
        log_warn="#9D5D00",
        log_error="#C42B1C",
        log_debug="#767676",
        scrollbar=rgba(fg, 0.20),
        scrollbar_hover=rgba(fg, 0.38),
        tooltip_bg="#FFFFFF",
        tooltip_text="#1F1F1F",
    )


DARK = _make_dark()
LIGHT = _make_light()

PALETTES: Dict[str, Palette] = {"dark": DARK, "light": LIGHT}


# ================================================================
# 间距 —— 4px 基准栅格
# ================================================================

SPACING = {
    "xs": 4,     # 图标与文字之间
    "sm": 8,     # 控件内 padding / 紧凑行距
    "md": 12,    # 常规控件间距
    "lg": 16,    # 分组之间
    "xl": 24,    # 页面边距
}


# ================================================================
# 圆角 —— 工具类应用，不追求大圆角
# ================================================================

RADIUS = {
    "window": 2,   # 窗口 / 面板 / 卡片
    "control": 2,  # 输入框 / 列表项 / 表格
    "button": 3,   # 按钮
    "scroll": 2,   # 滚动条
}


# ================================================================
# 尺寸
# ================================================================

#: 工具栏图标边长
ICON_SIZE = 16
#: 控件高度（输入框 / 按钮 / 下拉）
CONTROL_HEIGHT = 28
#: 数据密集区行高（表格 / 列表 / 日志）
ROW_HEIGHT = 28
#: 左侧导航宽度区间
NAV_WIDTH = (200, 240)
#: 滚动条：常态 8px，hover 变宽到 12px
SCROLLBAR_WIDTH = 8
SCROLLBAR_WIDTH_HOVER = 12
#: 工具栏高度
TOOLBAR_HEIGHT = 34
#: 状态栏高度
STATUSBAR_HEIGHT = 24


# ================================================================
# 字体 —— 一律用 pt，禁止写死 px（DPI 自适应）
# ================================================================

#: 基础字号（9pt）
FONT_SIZE = 9
#: 标题字号
FONT_SIZE_TITLE = 12
#: 小号（辅助说明）
FONT_SIZE_SMALL = 8

UI_FAMILIES = [
    "Segoe UI",
    "Microsoft YaHei UI",
    "微软雅黑",
    "PingFang SC",
    "Noto Sans CJK SC",
    "Source Han Sans SC",
    "sans-serif",
]

MONO_FAMILIES = [
    "Cascadia Mono",
    "Consolas",
    "JetBrains Mono",
    "Sarasa Mono SC",
    "Noto Sans Mono CJK SC",
    "Courier New",
    "monospace",
]


def ui_font_family() -> str:
    return ", ".join(f'"{f}"' if " " in f else f for f in UI_FAMILIES)


def mono_font_family() -> str:
    return ", ".join(f'"{f}"' if " " in f else f for f in MONO_FAMILIES)


def ui_font_qfamilies() -> list:
    """给 QFont.setFamilies() 用（Qt 会按顺序回退到有字形的那个）。"""
    return list(UI_FAMILIES)


def mono_font_qfamilies() -> list:
    return list(MONO_FAMILIES)
