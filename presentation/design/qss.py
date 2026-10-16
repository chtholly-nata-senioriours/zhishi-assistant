# -*- coding: utf-8 -*-
"""从 Theme 生成全应用样式表（QSS）与 QPalette。

两条硬规矩
    1. **这里不出现任何颜色字面量**。所有颜色走 `t.palette.xxx`，
       于是换主题时样式表整体重算，不可能有「漏改一处」的角落。
    2. **不用裸 `QWidget` 类型选择器**。它会匹配所有子类，把按钮 / 输入框
       自己的背景一起覆盖掉。需要选「普通容器」时用 `.QWidget`
       （Qt 的精确类选择器，只匹配裸 QWidget）。

为什么还要 QPalette
    QSS 覆盖不到的地方（原生 QMessageBox 的按钮、菜单勾选标记、
    QComboBox 弹窗、禁用态文字）由 QPalette 兜底。只给 QSS 的话，
    浅色主题下会突然冒出一块深色原生控件。
"""
from __future__ import annotations

from PySide6.QtGui import QColor, QPalette

from .tokens import (
    CONTROL_HEIGHT,
    FONT_SIZE,
    FONT_SIZE_SMALL,
    FONT_SIZE_TITLE,
    ICON_SIZE,
    RADIUS,
    ROW_HEIGHT,
    SCROLLBAR_WIDTH,
    SCROLLBAR_WIDTH_HOVER,
    SPACING,
    TOOLBAR_HEIGHT,
    mono_font_family,
)

#: handle 在常态下相对轨道两侧的内缩量。
#: 轨道宽 = SCROLLBAR_WIDTH_HOVER(12)，内缩后 handle 视觉宽 = SCROLLBAR_WIDTH(8)。
#: hover 时内缩归零 → handle 撑满轨道 → 变宽到 12px。
_SCROLLBAR_INSET = max(0, (SCROLLBAR_WIDTH_HOVER - SCROLLBAR_WIDTH) // 2)


# ================================================================
# QPalette —— 给 QSS 覆盖不到的原生控件兜底
# ================================================================

def build_qt_palette(t) -> QPalette:
    p = t.palette
    qp = QPalette()

    def c(key: str) -> QColor:
        return t.color(key)

    qp.setColor(QPalette.ColorRole.Window, c("window"))
    qp.setColor(QPalette.ColorRole.WindowText, c("text"))
    qp.setColor(QPalette.ColorRole.Base, c("panel"))
    qp.setColor(QPalette.ColorRole.AlternateBase, c("surface_alt"))
    qp.setColor(QPalette.ColorRole.Text, c("text"))
    qp.setColor(QPalette.ColorRole.PlaceholderText, c("text_disabled"))
    qp.setColor(QPalette.ColorRole.Button, c("surface"))
    qp.setColor(QPalette.ColorRole.ButtonText, c("text"))
    qp.setColor(QPalette.ColorRole.BrightText, c("error"))
    qp.setColor(QPalette.ColorRole.Highlight, c("accent"))
    qp.setColor(QPalette.ColorRole.HighlightedText, c("accent_text"))
    qp.setColor(QPalette.ColorRole.ToolTipBase, c("tooltip_bg"))
    qp.setColor(QPalette.ColorRole.ToolTipText, c("tooltip_text"))
    qp.setColor(QPalette.ColorRole.Link, c("accent"))
    qp.setColor(QPalette.ColorRole.LinkVisited, c("accent_pressed"))
    qp.setColor(QPalette.ColorRole.Mid, c("border_strong"))

    # 禁用态：文字降到 40%，这是规格里的三级灰阶之一
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText,
                 QPalette.ColorRole.WindowText):
        qp.setColor(QPalette.ColorGroup.Disabled, role, c("text_disabled"))
    qp.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Base, c("window"))
    qp.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Button, c("window"))
    return qp


# ================================================================
# QSS
# ================================================================

def build_qss(t) -> str:
    p = t.palette
    mono = mono_font_family()

    # QSS 里需要用「图片」的地方（勾选标记、下拉箭头、树展开箭头）。
    # 这些 SVG 由 icons.py 按**当前主题色**现场生成 —— 于是深色一套、
    # 浅色一套，且颜色仍然只来自 Palette。
    from . import icons as _icons
    urls = _icons.qss_urls(t)

    # 局部快捷方式：把常用 token 取出来，下面的模板才读得下去
    V = lambda k: p.as_dict()[k]  # noqa: E731  —— token 直取（本模块内可控）
    accent, accent_hover, accent_pressed = V("accent"), V("accent_hover"), V("accent_pressed")
    accent_text, accent_soft = V("accent_text"), V("accent_soft")

    return f"""
/* ============================================================
 * 全局
 * 字体走 QApplication.setFont(theme.font)（见 theme._apply_to），
 * 不在这里写 `*` 通配规则 —— Qt 对通配选择器要逐控件匹配，代价高，
 * 而且会盖掉控件自己设的等宽字体。
 * ============================================================ */

/* 窗口级底色。
 *
 * 这里**刻意不写 `.QWidget`**。`.QWidget` 确实是 Qt 的精确类选择器
 * （只匹配裸 QWidget，不波及 QPushButton 等子类），但它同样会命中
 * 「卡片内部的普通 QWidget 容器」—— 控制中心里每个表单行、分隔条、
 * 面板的动作行都是裸 QWidget。结果是白色卡片里冒出一条条窗口底色的
 * 灰带（浅色主题下尤其明显，实测可见）。
 *
 * 顶层裸 QWidget 窗口（AIPanel / ShellWindow）的底色由 QPalette 提供
 * ——见 `build_qt_palette()`，Fusion 会拿 Window 角色给顶层窗口上色。
 * 所以去掉这条规则不会让任何窗口失去底色。
 *
 * 规矩仍然是「禁止裸 `QWidget` 类型选择器」：它会波及所有子类，
 * 把按钮 / 输入框自己的背景一起覆盖掉。
 */
QMainWindow, QDialog {{
    background-color: {V("window")};
    color: {V("text")};
}}

/* 卡片 / 面板内部的普通容器一律透明 —— 显式写出来，避免将来有人
   加回 `.QWidget` 时又被灰带咬一次。 */
QFrame#card > .QWidget,
QFrame#card .QWidget,
QFrame#aiCard > .QWidget,
QFrame#aiCard .QWidget {{
    background: transparent;
}}

QMainWindow::separator {{
    background: {V("border")};
    width: 1px;
    height: 1px;
}}

/* ============================================================
 * 工具栏：iconOnly + tooltip，四态齐全
 * ============================================================ */

QToolBar {{
    background: {V("toolbar")};
    border: none;
    border-bottom: 1px solid {V("border")};
    padding: {SPACING["xs"]}px {SPACING["sm"]}px;
    spacing: {SPACING["xs"]}px;
    min-height: {TOOLBAR_HEIGHT}px;
}}
QToolBar::separator {{
    background: {V("border")};
    width: 1px;
    margin: {SPACING["xs"]}px {SPACING["sm"]}px;
}}

QToolButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: {RADIUS["control"]}px;
    padding: {SPACING["xs"]}px;
    color: {V("text")};
}}
QToolButton:hover {{
    background: {V("toolbar_hover")};
    border-color: {V("border")};
}}
QToolButton:pressed {{
    background: {V("toolbar_pressed")};
}}
QToolButton:checked {{
    background: {V("toolbar_checked")};
    border-color: {accent};
}}
QToolButton:disabled {{
    background: transparent;
    border-color: transparent;
    color: {V("text_disabled")};
}}
QToolButton::menu-indicator {{ image: none; width: 0; }}

/* 主工具栏里的「保存」这类强调动作 */
QToolButton[accent="true"]:hover {{
    background: {V("toolbar_checked")};
    border-color: {accent};
}}

/* 分段选择器（浅色 / 深色 这类二选一） */
QToolButton[segment="true"] {{
    background: {V("surface")};
    border: 1px solid {V("border_strong")};
    border-radius: {RADIUS["control"]}px;
    padding: {SPACING["xs"]}px {SPACING["md"]}px;
    color: {V("text_secondary")};
}}
QToolButton[segment="true"]:hover {{ background: {V("hover")}; color: {V("text")}; }}
QToolButton[segment="true"]:checked {{
    background: {accent_soft};
    border-color: {accent};
    color: {accent};
    font-weight: 600;
}}

/* ============================================================
 * 按钮：默认 / 强调 / 危险 三种变体
 * ============================================================ */

QPushButton {{
    background: {V("surface")};
    border: 1px solid {V("border_strong")};
    border-radius: {RADIUS["button"]}px;
    color: {V("text")};
    padding: {SPACING["xs"]}px {SPACING["sm"]}px;
    min-height: {CONTROL_HEIGHT - 8}px;
    min-width: 64px;
}}
QPushButton:hover {{
    background: {V("hover")};
    border-color: {V("border_strong")};
}}
QPushButton:pressed {{
    background: {V("surface_alt")};
}}
QPushButton:focus {{
    border-color: {accent};
}}
QPushButton:disabled {{
    background: {V("window")};
    border-color: {V("border")};
    color: {V("text_disabled")};
}}

QPushButton[accent="true"] {{
    background: {accent};
    border-color: {accent};
    color: {accent_text};
    font-weight: 600;
}}
QPushButton[accent="true"]:hover {{ background: {accent_hover}; border-color: {accent_hover}; }}
QPushButton[accent="true"]:pressed {{ background: {accent_pressed}; border-color: {accent_pressed}; }}
QPushButton[accent="true"]:disabled {{
    background: {V("window")};
    border-color: {V("border")};
    color: {V("text_disabled")};
}}

QPushButton[variant="danger"]:hover {{
    background: {V("error")};
    border-color: {V("error")};
    color: {accent_text};
}}

/* 扁平按钮（对话框次要动作 / 行内动作） */
QPushButton[flat="true"] {{
    background: transparent;
    border-color: transparent;
    min-width: 0;
}}
QPushButton[flat="true"]:hover {{ background: {V("hover")}; border-color: transparent; }}
QPushButton[flat="true"]:pressed {{ background: {V("surface_alt")}; }}

/* ============================================================
 * 输入控件
 * ============================================================ */

QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {V("input_bg")};
    border: 1px solid {V("border_strong")};
    border-radius: {RADIUS["control"]}px;
    color: {V("text")};
    padding: {SPACING["xs"]}px {SPACING["sm"]}px;
    min-height: {CONTROL_HEIGHT - 8}px;
    selection-background-color: {accent};
    selection-color: {accent_text};
}}
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {{
    border-color: {V("text_disabled")};
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border-color: {accent};
}}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{
    background: {V("window")};
    color: {V("text_disabled")};
}}
QLineEdit[echoMode="2"] {{ lineedit-password-character: 9679; }}

QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 18px;
    border: none;
    background: transparent;
}}
QComboBox::down-arrow {{ image: url({urls["chevron-down"]}); width: 12px; height: 12px; }}
QComboBox::down-arrow:disabled {{ image: url({urls["chevron-down-disabled"]}); }}
QComboBox QAbstractItemView {{
    background: {V("panel")};
    border: 1px solid {V("border_strong")};
    border-radius: {RADIUS["control"]}px;
    padding: {SPACING["xs"]}px 0;
    selection-background-color: {V("selected")};
    selection-color: {V("selected_text")};
    outline: none;
}}
QComboBox QAbstractItemView::item {{ min-height: {ROW_HEIGHT - 6}px; padding: 0 {SPACING["sm"]}px; }}

QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-origin: border; subcontrol-position: top right;
    width: 16px; border: none; background: transparent;
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border; subcontrol-position: bottom right;
    width: 16px; border: none; background: transparent;
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url({urls["chevron-up"]}); width: 10px; height: 10px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url({urls["chevron-down"]}); width: 10px; height: 10px; }}
QSpinBox::up-arrow:disabled, QSpinBox::down-arrow:disabled {{ image: none; }}

/* ============================================================
 * 勾选 / 单选
 * ============================================================ */

QCheckBox, QRadioButton {{
    spacing: {SPACING["sm"]}px;
    color: {V("text")};
    background: transparent;
}}
QCheckBox:disabled, QRadioButton:disabled {{ color: {V("text_disabled")}; }}

QCheckBox::indicator {{
    width: 14px; height: 14px;
    border: 1px solid {V("border_strong")};
    border-radius: {RADIUS["control"]}px;
    background: {V("input_bg")};
}}
QCheckBox::indicator:hover {{ border-color: {accent}; }}
QCheckBox::indicator:checked {{
    background: {accent};
    border-color: {accent};
    image: url({urls["check"]});
}}
QCheckBox::indicator:checked:hover {{ background: {accent_hover}; border-color: {accent_hover}; }}
QCheckBox::indicator:disabled {{ border-color: {V("border")}; background: {V("window")}; }}
QCheckBox::indicator:indeterminate {{ background: {accent}; border-color: {accent}; }}

QRadioButton::indicator {{
    width: 14px; height: 14px;
    border: 1px solid {V("border_strong")};
    border-radius: 7px;
    background: {V("input_bg")};
}}
QRadioButton::indicator:hover {{ border-color: {accent}; }}
QRadioButton::indicator:checked {{
    border-color: {accent};
    image: url({urls["dot"]});
}}

/* ============================================================
 * 列表 / 树 / 表格 —— 数据密集区
 * 行高紧凑、行 hover 变色、选中整行高亮、表头底色区分
 * ============================================================ */

QListView, QTreeView, QTableView {{
    background: {V("panel")};
    alternate-background-color: {V("surface_alt")};
    border: 1px solid {V("border")};
    border-radius: {RADIUS["window"]}px;
    color: {V("text")};
    outline: none;
    gridline-color: {V("border")};
    selection-background-color: {V("selected")};
    selection-color: {V("selected_text")};
}}
QListView::item, QTreeView::item, QTableView::item {{
    min-height: {ROW_HEIGHT - 2}px;
    padding: 0 {SPACING["sm"]}px;
    border: none;
    color: {V("text")};
}}
QListView::item:hover, QTreeView::item:hover, QTableView::item:hover {{
    background: {V("hover")};
}}
QListView::item:selected, QTreeView::item:selected, QTableView::item:selected {{
    background: {V("selected")};
    color: {V("selected_text")};
}}
QListView::item:disabled, QTreeView::item:disabled, QTableView::item:disabled {{
    color: {V("text_disabled")};
}}

QHeaderView {{ background: {V("table_header")}; border: none; }}
QHeaderView::section {{
    background: {V("table_header")};
    color: {V("text_secondary")};
    padding: {SPACING["xs"]}px {SPACING["sm"]}px;
    border: none;
    border-right: 1px solid {V("border")};
    border-bottom: 1px solid {V("border")};
    min-height: {ROW_HEIGHT - 8}px;
}}
QHeaderView::section:hover {{ color: {V("text")}; }}
QHeaderView::section:last {{ border-right: none; }}
QTableCornerButton::section {{ background: {V("table_header")}; border: none; }}

QTreeView::branch {{ background: transparent; }}
QTreeView::branch:has-children:!has-siblings:closed,
QTreeView::branch:closed:has-children:has-siblings {{ image: url({urls["chevron-right"]}); }}
QTreeView::branch:open:has-children:!has-siblings,
QTreeView::branch:open:has-children:has-siblings {{ image: url({urls["chevron-down"]}); }}

/* ============================================================
 * 左侧导航（控制中心）
 * ============================================================ */

QListWidget#navList {{
    background: {V("panel")};
    border: none;
    border-right: 1px solid {V("border")};
    border-radius: 0;
    padding: {SPACING["xs"]}px;
}}
QListWidget#navList::item {{
    min-height: {ROW_HEIGHT + 4}px;
    padding: 0 {SPACING["sm"]}px;
    border-radius: {RADIUS["control"]}px;
    margin: 1px 0;
    color: {V("text")};
}}
QListWidget#navList::item:hover {{ background: {V("hover")}; }}
QListWidget#navList::item:selected {{
    background: {V("selected")};
    color: {V("selected_text")};
}}

/* 无边框变体：日志 / 输出这类自带外框的区域 */
QListView[border="none"], QTreeView[border="none"], QTableView[border="none"],
QPlainTextEdit[border="none"], QTextEdit[border="none"] {{
    border: none;
    border-radius: 0;
    background: {V("panel")};
}}

/* ============================================================
 * 文本区 / 日志
 * ============================================================ */

QPlainTextEdit#logView, QTextEdit#logView {{
    background: {V("panel")};
    border: 1px solid {V("border")};
    border-radius: {RADIUS["window"]}px;
    color: {V("log_info")};
    font-family: {mono};
    font-size: {FONT_SIZE}pt;
    padding: {SPACING["xs"]}px;
    selection-background-color: {V("selected")};
}}

/* 「测试连接」结果输出区。颜色随 role 动态属性走，
   调用方只设 role，不拼任何颜色字符串。 */
QPlainTextEdit#probeStatus {{
    background: {V("input_bg")};
    border: 1px solid {V("border")};
    border-radius: {RADIUS["control"]}px;
    color: {V("text_secondary")};
    font-family: {mono};
    padding: {SPACING["sm"]}px;
    selection-background-color: {V("selected")};
}}
QPlainTextEdit#probeStatus[role="info"]  {{ color: {V("text_secondary")}; }}
QPlainTextEdit#probeStatus[role="ok"]    {{ color: {V("success")}; }}
QPlainTextEdit#probeStatus[role="warn"]  {{ color: {V("warning")}; }}
QPlainTextEdit#probeStatus[role="error"] {{ color: {V("error")}; }}

QLabel#pageTitle {{ font-size: {FONT_SIZE + 3}pt; font-weight: 600; color: {V("text")}; }}
QLabel#dialogTitle {{ font-size: {FONT_SIZE_TITLE}pt; font-weight: 600; color: {V("text")}; }}
QLabel#pageHint  {{ color: {V("text_secondary")}; }}
QLabel#sectionLabel {{ color: {V("text_secondary")}; font-weight: 600; }}
QLabel#emptyTitle {{ color: {V("text")}; font-size: {FONT_SIZE + 1}pt; }}
QLabel#emptyHint  {{ color: {V("text_secondary")}; }}
QLabel#statusInfo {{ color: {V("text_secondary")}; }}
QLabel#statusOk   {{ color: {V("success")}; }}
QLabel#statusWarn {{ color: {V("warning")}; }}
QLabel#statusErr  {{ color: {V("error")}; }}

/* 活动建议（P2.14）：数字块 / 排行 / 建议卡的文字 */
QLabel#statTileLabel {{ color: {V("text_secondary")}; }}
QLabel#statTileValue {{ color: {V("text")}; font-size: {FONT_SIZE + 5}pt; font-weight: 600; }}
/* 头条指标（P2.15）：更大字号 + 强调色数字 —— 和别的格子拉开层级 */
QLabel#statTileValue[primary="true"] {{
    color: {V("accent")};
    font-size: {FONT_SIZE + 12}pt;
}}
QLabel#rankName  {{ color: {V("text")}; }}
QLabel#rankValue {{ color: {V("text_secondary")}; }}
QLabel#axisLabel {{ color: {V("text_secondary")}; font-size: {FONT_SIZE_SMALL}pt; }}
QLabel#adviceHeadline {{ color: {V("text")}; font-weight: 600; }}
QLabel#adviceEvidence {{ color: {V("text_secondary")}; }}

/* 插件状态行（giwifi 等）：语义 role 决定文字色 */
QLabel#pluginStatus[role="info"]    {{ color: {V("text")}; }}
QLabel#pluginStatus[role="online"]  {{ color: {V("success")}; }}
QLabel#pluginStatus[role="offline"] {{ color: {V("error")}; }}
QLabel#pluginStatus[role="warning"] {{ color: {V("warning")}; }}
QLabel#pluginStatus[role="ok"]      {{ color: {V("success")}; }}
QLabel#pluginStatus[role="error"]   {{ color: {V("error")}; }}
QLabel#monoValue  {{ font-family: {mono}; color: {V("text_secondary")}; }}

/* 桌宠提示气泡（浮在精灵图上）。配色随主题走，由这里统一负责。 */
QLabel#petBubble {{
    color: {V("text")};
    background: {V("panel")};
    border: 1px solid {V("border_strong")};
    border-radius: {RADIUS["control"]}px;
    padding: {SPACING["xs"]}px {SPACING["sm"]}px;
}}

/* 形象预览：有图时无框，无图时虚线占位框 + 引导文案 */
QLabel#petPreview {{
    background: {V("input_bg")};
    border: 1px solid {V("border")};
    border-radius: {RADIUS["control"]}px;
}}
QLabel#petPreview[empty="true"] {{
    background: transparent;
    border: 1px dashed {V("border_strong")};
    color: {V("text_disabled")};
    font-size: {FONT_SIZE_SMALL}pt;
}}

/* 番茄钟倒计时：字号由代码按 DPI 设置，这里只管颜色 */
QLabel#tomatoClock[role="normal"] {{ color: {V("text")}; }}
QLabel#tomatoClock[role="accent"] {{ color: {V("accent")}; }}
QLabel#tomatoClock[role="ok"]     {{ color: {V("success")}; }}
QLabel#tomatoClock[role="warn"]   {{ color: {V("warning")}; }}

/* ============================================================
 * 卡片 / 分组
 * ============================================================ */

QFrame#card {{
    background: {V("panel")};
    border: 1px solid {V("border")};
    border-radius: {RADIUS["window"]}px;
}}
QFrame#hairline {{ background: {V("border")}; border: none; max-height: 1px; }}
QFrame#vHairline {{ background: {V("border")}; border: none; max-width: 1px; }}

/* 概览仪表盘（P2.15）：「数据」两页的头条区。
   顶边一条 accent 线是**整页唯一**的 —— 原来概览只是几个 surface_alt
   灰块摊在页面底色上（浅色主题下只差 4 级，几乎看不见），最该被看见的
   信息反而最不显眼。 */
QFrame#overviewBoard {{
    background: {V("panel")};
    border: 1px solid {V("border")};
    border-top: 3px solid {V("accent")};
    border-radius: {RADIUS["window"]}px;
}}
QLabel#overviewTitle {{
    color: {V("text")};
    font-size: {FONT_SIZE_TITLE}pt;
    font-weight: 600;
}}
/* 指标格：默认**透明**（它活在 overviewBoard 的台面上，自己不再铺底），
   只有 primary 那一格铺 accent 软底 —— 整页唯一的彩色底块。 */
QFrame#statTile {{
    background: transparent;
    border: none;
    border-radius: {RADIUS["control"]}px;
}}
QFrame#statTile[primary="true"] {{ background: {V("accent_soft")}; }}
/* 建议卡：有描边的独立卡片 —— 每条建议在视觉上是「一个东西」 */
QFrame#adviceCard {{
    background: {V("panel")};
    border: 1px solid {V("border")};
    border-radius: {RADIUS["window"]}px;
}}
/* 卡片左侧的强调竖条 —— 让建议在列表里一眼可辨 */
QFrame#adviceAccent {{
    background: {V("accent")};
    border: none;
    border-radius: 1px;
}}
/* 总结：**刻意与建议卡长得不一样**。它不是「第 0 条建议」，
   而是那次生成的结论本身 —— 用强调软底把它托起来，
   一眼就能看出「先读这块，再看下面的卡片」。 */
QFrame#adviceSummary {{
    background: {V("accent_soft")};
    border: none;
    border-radius: {RADIUS["window"]}px;
}}
QLabel#adviceSummaryLabel {{
    color: {V("accent")};
    font-size: {FONT_SIZE_SMALL}pt;
    font-weight: 600;
}}
QLabel#adviceSummaryText {{ color: {V("text")}; }}

/* 专注倒计时卡 —— 进行中一眼可见，暂停时整卡换成 warning 语义色 */
QFrame#focusCard {{
    background: {V("panel")};
    border: 1px solid {V("accent")};
    border-radius: {RADIUS["window"]}px;
}}
QFrame#focusCard[paused="true"] {{ border-color: {V("warning")}; }}
QLabel#focusTitle {{ color: {V("text_secondary")}; font-weight: 600; }}
QLabel#focusClock {{ color: {V("accent")}; }}
QFrame#focusCard[paused="true"] QLabel#focusClock {{ color: {V("warning")}; }}
QProgressBar#focusBar {{ min-height: 4px; max-height: 4px; }}
/* 进度条自己挂 paused 属性（而不是靠祖先选择器）—— 见 focus_card.py 的说明 */
QProgressBar#focusBar[paused="true"]::chunk {{ background: {V("warning")}; }}

/* 建议卡上「专注中…」的按钮：**不是禁用，是正在进行** ——
   一片灰会被读成「这按钮坏了」，而它其实在说「这轮专注还没结束」。
   用与悬浮球 / 托盘环同一个琥珀（warning）语义色，全项目一个口径。

   两处写法都不是随便写的：
   · 用 `#focusEntry` 这个 id 把特异度抬到 (1,1,1)，
     压过通用的 `QPushButton:disabled`（(0,1,1)）—— 按钮确实是
     `setEnabled(False)`，不抬特异度就会被那片灰盖住。
     今日页顶部按钮与建议卡按钮**共用这一个 id**（`focus_card.FOCUS_ENTRY_ID`），
     否则同一页面上会出现两种「专注中…」。
   · 属性叫 **`phase` 而不是 `focus`**：`focus` 是 QWidget 的**内建 bool
     属性**（QSS 里还是 `:focus` 伪状态），`setProperty("focus", "running")`
     会被它吞掉、读回来是 `False`，`[focus="…"]` 于是**永远不匹配**且不报错
     （实测踩到，见 `focus_card.apply_phase` 的说明）。 */
QPushButton#focusEntry[phase="running"] {{
    background: {V("warning_soft")};
    border-color: {V("warning")};
    color: {V("warning")};
}}
QPushButton#focusEntry[phase="paused"] {{
    background: transparent;
    border-color: {V("warning")};
    color: {V("warning")};
}}

QGroupBox {{
    border: 1px solid {V("border")};
    border-radius: {RADIUS["window"]}px;
    margin-top: {SPACING["sm"]}px;
    padding: {SPACING["md"]}px {SPACING["sm"]}px {SPACING["sm"]}px {SPACING["sm"]}px;
    color: {V("text")};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: {SPACING["sm"]}px;
    padding: 0 {SPACING["xs"]}px;
    color: {V("text_secondary")};
}}

/* ============================================================
 * 选项卡
 * ============================================================ */

QTabWidget::pane {{
    border: 1px solid {V("border")};
    border-radius: {RADIUS["window"]}px;
    top: -1px;
    background: {V("panel")};
}}
QTabBar {{ qproperty-drawBase: 0; }}
QTabBar::tab {{
    background: transparent;
    color: {V("text_secondary")};
    border: none;
    border-bottom: 2px solid transparent;
    padding: {SPACING["xs"]}px {SPACING["md"]}px;
    min-height: {ROW_HEIGHT - 8}px;
}}
QTabBar::tab:hover {{ color: {V("text")}; }}
QTabBar::tab:selected {{
    color: {V("text")};
    border-bottom-color: {accent};
}}
QTabBar::tab:disabled {{ color: {V("text_disabled")}; }}

/* ============================================================
 * 滚动条：8px 窄条，hover 变宽，圆角 2px
 *
 * 手法：**轨道宽度固定**为 hover 宽度，靠 handle 的 margin 控制视觉粗细。
 * 为什么不直接改轨道宽度：滚动条占位一变，viewport 就要重排 ——
 * hover 瞬间正文会左右抖一下，是很廉价的手感。
 * ============================================================ */

QScrollBar:vertical {{
    background: transparent;
    width: {SCROLLBAR_WIDTH_HOVER}px;
    margin: 0;
    border: none;
}}
QScrollBar::handle:vertical {{
    background: {V("scrollbar")};
    border-radius: {RADIUS["scroll"]}px;
    margin: {_SCROLLBAR_INSET}px;
    min-height: {ROW_HEIGHT}px;
}}
QScrollBar::handle:vertical:hover {{
    background: {V("scrollbar_hover")};
    margin: 0;                      /* 撑满轨道：8px → 12px，即「hover 变宽」 */
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; width: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}

QScrollBar:horizontal {{
    background: transparent;
    height: {SCROLLBAR_WIDTH_HOVER}px;
    margin: 0;
    border: none;
}}
QScrollBar::handle:horizontal {{
    background: {V("scrollbar")};
    border-radius: {RADIUS["scroll"]}px;
    margin: {_SCROLLBAR_INSET}px;
    min-width: {ROW_HEIGHT}px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {V("scrollbar_hover")};
    margin: 0;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ height: 0; width: 0; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}

QScrollArea {{ border: none; background: transparent; }}
/* 用 `.QWidget` 而不是 `QWidget`：后者会连 QLineEdit / QComboBox 等子类
   一起透明化，滚动区里的输入框就没底色了。 */
QScrollArea .QWidget {{ background: transparent; }}

/* ============================================================
 * 状态栏
 * ============================================================ */

QStatusBar {{
    background: {V("toolbar")};
    border-top: 1px solid {V("border")};
    color: {V("text_secondary")};
    min-height: 22px;
}}
QStatusBar::item {{ border: none; }}
QStatusBar QLabel {{ color: {V("text_secondary")}; padding: 0 {SPACING["xs"]}px; }}

/* ============================================================
 * 菜单 / 提示 / 进度
 * ============================================================ */

QMenu {{
    background: {V("panel")};
    border: 1px solid {V("border_strong")};
    border-radius: {RADIUS["window"]}px;
    padding: {SPACING["xs"]}px 0;
    color: {V("text")};
}}
QMenu::item {{
    padding: {SPACING["xs"]}px {SPACING["lg"]}px;
    min-height: {ROW_HEIGHT - 8}px;
    background: transparent;
}}
QMenu::item:selected {{ background: {V("selected")}; color: {V("selected_text")}; }}
QMenu::item:disabled {{ color: {V("text_disabled")}; }}
QMenu::separator {{ height: 1px; background: {V("border")}; margin: {SPACING["xs"]}px 0; }}
QMenu::icon {{ padding-left: {SPACING["sm"]}px; }}

QMenuBar {{ background: {V("window")}; color: {V("text")}; }}
QMenuBar::item {{ padding: {SPACING["xs"]}px {SPACING["sm"]}px; background: transparent; }}
QMenuBar::item:selected {{ background: {V("hover")}; }}

QToolTip {{
    background: {V("tooltip_bg")};
    color: {V("tooltip_text")};
    border: 1px solid {V("border_strong")};
    border-radius: {RADIUS["control"]}px;
    padding: {SPACING["xs"]}px {SPACING["sm"]}px;
}}

QProgressBar {{
    background: {V("surface_alt")};
    border: 1px solid {V("border")};
    border-radius: {RADIUS["control"]}px;
    text-align: center;
    color: {V("text_secondary")};
    min-height: 6px;
    max-height: 6px;
}}
QProgressBar::chunk {{ background: {accent}; border-radius: {RADIUS["control"]}px; }}

QSplitter::handle {{ background: {V("border")}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}

/* ============================================================
 * 悬浮面板（AI 唤起面板）—— 无边框 + 1px 描边，不用阴影
 * ============================================================ */

QFrame#aiCard {{
    background: {V("panel")};
    border: 1px solid {V("border_strong")};
    border-radius: {RADIUS["window"]}px;
}}
QLabel#aiTitle  {{ color: {V("text")}; font-weight: 600; }}
QLabel#aiHint   {{ color: {V("text_secondary")}; }}
QLabel#aiStatus {{ color: {V("text_secondary")}; font-size: {FONT_SIZE_SMALL}pt; }}
QFrame#aiSep    {{ background: {V("border")}; border: none; max-height: 1px; }}

/* `#aiIcon` / `#aiIconDanger` 已删除 —— 面板改用 `IconButton`（objectName
   为 iconButton / iconButtonDanger），旧规则没人匹配，留着只会误导。 */

QPushButton#aiAction {{
    background: {V("surface")};
    border: 1px solid {V("border_strong")};
    border-radius: {RADIUS["button"]}px;
    color: {V("text")};
    padding: 3px {SPACING["sm"]}px;
    min-width: 0;
    min-height: 0;
}}
QPushButton#aiAction:hover {{ background: {V("hover")}; }}

QTextBrowser#aiOutput {{
    background: transparent;
    border: none;
    color: {V("text")};
}}

/* ============================================================
 * 图标按钮（标题栏关闭 / 行内动作）
 *
 * 尺寸由 Python 侧 `IconButton.setFixedSize()` 决定，**不在这里写
 * min/max-width** —— QSS 的 min/max 会盖掉 setFixedSize，两者打架时
 * 表现为「按钮突然变成 120x30 的灰块」（实测：danger 变体漏了基础规则，
 * 退化成通用 QPushButton，尺寸与底色全跑偏）。
 * ============================================================ */

QPushButton#iconButton, QPushButton#iconButtonDanger {{
    background: transparent;
    border: none;
    border-radius: {RADIUS["button"]}px;
    padding: 0;
}}
QPushButton#iconButton:hover {{ background: {V("hover")}; }}
QPushButton#iconButton:pressed {{ background: {V("surface_alt")}; }}
QPushButton#iconButtonDanger:hover {{ background: {V("error")}; }}
QPushButton#iconButtonDanger:pressed {{ background: {V("error")}; }}
"""
